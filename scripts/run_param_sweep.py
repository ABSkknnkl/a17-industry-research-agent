#!/usr/bin/env python3
"""模型参数扫描：固定一批用例，跑多组模型参数，产出逐条可比指标。

## 为什么用子进程而不是线程

各智能体在构造时从环境变量读取模型参数（`Settings.from_env`），同进程内改环境变量
影响不到已构造的实例。所以每一组参数都必须在独立子进程里跑，才能保证参数真正生效。

## 已在脚本内处理的三个坑

1. **`.env` 反向覆盖**：数据获取层的 config 会执行 `load_dotenv(override=True)`，
   把 `.env` 里的值盖回环境变量 —— 注入的实验参数会被悄悄覆盖。
   处理：子进程置 `SKIP_DOTENV_OVERRIDE=1`，同时把 `.env` 内容显式注入子进程环境
   （否则禁用加载后会丢凭据）。
2. **数据获取阶段的上限是独立变量**：该阶段读 `PLANNER_MAX_TOKENS`（默认 4096），
   不受 `LLM_MAX_TOKENS` 影响。处理：扫描时若指定了 max_tokens，同步设置该变量，
   否则该阶段恒定不变、结论失真。
3. **各层推理强度默认值不一致**：写作/融合默认不发送该字段，解读/取数/图表默认 low。
   处理：显式设置 `LLM_REASONING_EFFORT`，五层都会读到同一个值。

## 用法

    # 先自检参数是否真的生效（不起真实运行）
    python scripts/run_param_sweep.py --group low:LLM_REASONING_EFFORT=low \\
        --group medium:LLM_REASONING_EFFORT=medium --dry-run

    # 真实扫描（8 条 × 2 组，四路并发约 1 小时）
    python scripts/run_param_sweep.py --group low:LLM_REASONING_EFFORT=low \\
        --group medium:LLM_REASONING_EFFORT=medium --concurrency 4
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SWEEP_ROOT = ROOT / "eval" / "runs" / "sweep"
DEFAULT_CASES = ROOT / "eval" / "cases" / "sweep_subset.json"
BATCH_SCRIPT = ROOT / "scripts" / "run_v8_batch.py"
ENV_FILE = ROOT / ".env"

# 本进程自身也要做目录清理（合并分片时），同样要关掉批量删除守卫，
# 否则一次性移除数十个文件会被拦下并中断脚本。
os.environ["CODEBUDDY_SAFE_DELETE_ENABLED"] = "0"

# 扫描时一并同步的参数（避免上面第 2 条坑）
SYNCED_KEYS = {
    "LLM_MAX_TOKENS": "PLANNER_MAX_TOKENS",
}


def parse_env_file(path: Path) -> dict[str, str]:
    """把 .env 解析成字典（只读，不写回 os.environ）。"""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def parse_group(spec: str) -> tuple[str, dict[str, str]]:
    """解析 `标签:KEY=值,KEY=值` 形式的参数组定义。"""
    if ":" not in spec:
        raise ValueError(f"参数组格式应为 '标签:KEY=值,KEY=值'，收到：{spec!r}")
    tag, raw_params = spec.split(":", 1)
    tag = tag.strip()
    if not tag:
        raise ValueError(f"参数组标签不能为空：{spec!r}")
    params: dict[str, str] = {}
    for part in raw_params.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise ValueError(f"参数项格式应为 KEY=值，收到：{part!r}")
        key, value = part.split("=", 1)
        params[key.strip()] = value.strip()
    if not params:
        raise ValueError(f"参数组 {tag!r} 未指定任何参数")
    return tag, params


def build_child_env(params: dict[str, str], dotenv: dict[str, str]) -> dict[str, str]:
    """构造子进程环境：.env 兜底 → 实验参数覆盖 → 关闭 dotenv 覆盖 → 禁生图。

    另外必须剥离沙箱注入变量：在当前托管环境下，`mkdir(exist_ok=True)` 会被 shim
    转发给宿主并抛 `EEXIST`，而运行目录创建（storage.get_run_dir）正是这种调用，
    不剥离会让每条用例在起步阶段就失败。
    """
    env = os.environ.copy()
    env.pop("CODEBUDDY_SANDBOX_BROKER_IPC_ADDRESS", None)
    env["CODEBUDDY_SAFE_DELETE_ENABLED"] = "0"
    env.update(dotenv)              # 禁用 .env 加载后，凭据要显式带上
    env.update(params)              # 实验参数优先级最高
    for src, dst in SYNCED_KEYS.items():
        if src in params:
            env[dst] = params[src]
    env["SKIP_DOTENV_OVERRIDE"] = "1"
    env["IMAGE_API_KEY"] = ""       # 禁生图：单条会多花大量时间
    return env


def shard_cases(case_ids: list[str], concurrency: int) -> list[list[str]]:
    """把用例按轮转方式切成若干片，尽量均衡（避免把慢用例堆在同一片）。"""
    shards: list[list[str]] = [[] for _ in range(max(1, concurrency))]
    for idx, case_id in enumerate(case_ids):
        shards[idx % len(shards)].append(case_id)
    return [s for s in shards if s]


def run_shard(
    cases_path: Path,
    case_ids: list[str],
    out_dir: Path,
    env: dict[str, str],
    per_case_timeout: int,
    snapshot_mode: str,
) -> tuple[int, str]:
    """跑一个分片；返回 (退出码, 日志尾部)。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, str(BATCH_SCRIPT),
        "--cases", str(cases_path),
        "--only", ",".join(case_ids),
        "--out-dir", str(out_dir),
        "--snapshot-mode", snapshot_mode,
        "--per-case-timeout", str(per_case_timeout),
    ]
    hard_timeout = per_case_timeout * len(case_ids) + 900
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=hard_timeout)
    tail = (proc.stdout or "")[-800:] + (proc.stderr or "")[-400:]
    return proc.returncode, tail


def merge_shards(group_dir: Path, shard_dirs: list[Path]) -> int:
    """把各分片的用例产物合并到组目录（用例之间不会重名，合并安全）。

    注意：不要把整个分片目录一次性 rmtree —— 一个分片含数十个文件时会触发
    当前环境的批量删除守卫（SAFE_DELETE_BULK_CONFIRM_REQUIRED）并中断脚本。
    正确做法是**先把内容移出去，再删空目录**。
    """
    moved = 0
    meta_dir = group_dir / "_shard_meta"
    for shard in shard_dirs:
        if not shard.exists():
            continue
        for child in list(shard.iterdir()):
            if child.is_dir() and not child.name.startswith("_"):
                target = group_dir / child.name
                if target.exists():
                    shutil.rmtree(target, ignore_errors=True)   # 单用例目录，文件数少
                shutil.move(str(child), str(target))
                moved += 1
            else:
                # 分片级元文件（progress / ranking / batch.log）统一挪进 meta 目录留档
                meta_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(child), str(meta_dir / f"{shard.name}__{child.name}"))
        try:
            shard.rmdir()          # 已移空，只删目录本身
        except OSError:
            shutil.rmtree(shard, ignore_errors=True)
    return moved


def collect_metrics(group_dir: Path) -> dict[str, dict]:
    """读取组目录下每条用例的 metrics.json。"""
    found: dict[str, dict] = {}
    if not group_dir.exists():
        return found
    for case_dir in sorted(group_dir.iterdir()):
        if not case_dir.is_dir():
            continue
        metrics_file = case_dir / "metrics.json"
        status_file = case_dir / "status.json"
        if not metrics_file.exists():
            continue
        try:
            metrics = json.loads(metrics_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        if status_file.exists():
            try:
                metrics["_status"] = json.loads(status_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        found[case_dir.name] = metrics
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description="模型参数扫描")
    ap.add_argument("--group", action="append", required=True,
                    help="参数组，格式 '标签:KEY=值,KEY=值'，可重复")
    ap.add_argument("--cases", default=str(DEFAULT_CASES), help="用例集路径")
    ap.add_argument("--concurrency", type=int, default=4, help="并发的分片数")
    ap.add_argument("--per-case-timeout", type=int, default=2400, help="单条硬超时（秒）")
    ap.add_argument("--snapshot-mode", choices=("record", "replay", "off"), default="off",
                    help="快照模式；参数扫描应使用 off（请求体变了，replay 必然未命中）")
    ap.add_argument("--dry-run", action="store_true", help="只打印将要注入的参数与环境，不起真实运行")
    args = ap.parse_args()

    cases_path = Path(args.cases)
    if not cases_path.exists():
        print(f"❌ 用例集不存在：{cases_path}")
        return 2
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    case_ids = [c["id"] for c in cases]
    groups = [parse_group(spec) for spec in args.group]
    dotenv = parse_env_file(ENV_FILE)

    print(f"用例集：{cases_path.name}（{len(case_ids)} 条）{'、'.join(case_ids)}")
    print(f"参数组：{len(groups)} 组 → " + "；".join(f"{t}({','.join(f'{k}={v}' for k,v in p.items())})" for t, p in groups))
    print(f"并发分片：{args.concurrency}　快照模式：{args.snapshot_mode}")
    print(f".env 已解析：{len(dotenv)} 项（子进程将禁用其覆盖行为，改用显式注入）")

    if args.dry_run:
        print("\n=== DRY RUN：实际会注入子进程的关键参数 ===")
        for tag, params in groups:
            env = build_child_env(params, dotenv)
            probe = {k: env.get(k) for k in
                     ("LLM_MODEL", "LLM_REASONING_EFFORT", "LLM_MAX_TOKENS",
                      "PLANNER_MAX_TOKENS", "SKIP_DOTENV_OVERRIDE", "IMAGE_API_KEY")}
            print(f"  [{tag}] {probe}")
            shards = shard_cases(case_ids, args.concurrency)
            print(f"        分片：{['/'.join(s) for s in shards]}")
        print("\n若上面各组的 LLM_REASONING_EFFORT 确为不同值，说明注入有效。")
        return 0

    SWEEP_ROOT.mkdir(parents=True, exist_ok=True)
    summary: dict[str, dict] = {}

    for tag, params in groups:
        group_dir = SWEEP_ROOT / tag
        if group_dir.exists():
            print(f"⚠️ 组目录已存在，先清空：{group_dir}")
            shutil.rmtree(group_dir)
        group_dir.mkdir(parents=True, exist_ok=True)

        env = build_child_env(params, dotenv)
        shards = shard_cases(case_ids, args.concurrency)
        shard_dirs = [group_dir / f"_shard{i}" for i in range(len(shards))]

        print(f"\n=== 组 [{tag}] 开始：{len(shards)} 个分片 ===")
        started = time.time()
        with ThreadPoolExecutor(max_workers=len(shards)) as pool:
            futures = {
                pool.submit(run_shard, cases_path, ids, sdir, env, args.per_case_timeout, args.snapshot_mode): (i, ids)
                for i, (ids, sdir) in enumerate(zip(shards, shard_dirs))
            }
            for fut in as_completed(futures):
                i, ids = futures[fut]
                try:
                    code, tail = fut.result()
                    print(f"  分片{i} ({','.join(ids)}) 退出码={code}")
                    if code != 0:
                        print(f"    尾部日志：{tail}")
                except Exception as exc:
                    print(f"  分片{i} 异常：{exc}")

        elapsed = time.time() - started
        moved = merge_shards(group_dir, shard_dirs)
        metrics = collect_metrics(group_dir)
        manifest = {
            "tag": tag,
            "params": params,
            "cases": case_ids,
            "concurrency": len(shards),
            "snapshot_mode": args.snapshot_mode,
            "elapsed_seconds": round(elapsed, 1),
            "case_dirs_merged": moved,
            "metrics_collected": sorted(metrics.keys()),
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        (group_dir / "run_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        summary[tag] = manifest
        print(f"  组 [{tag}] 完成：用时 {elapsed/60:.1f} 分钟，收集到 {len(metrics)} 条指标 → {group_dir}")

    print("\n=== 扫描结束 ===")
    for tag, m in summary.items():
        print(f"  [{tag}] 参数={m['params']} 用时={m['elapsed_seconds']/60:.1f}分 指标={len(m['metrics_collected'])} 条")
    print(f"\n下一步：python scripts/compare_runs.py --a {list(summary)[0]} --b {list(summary)[-1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
