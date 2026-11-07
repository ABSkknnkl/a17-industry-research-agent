#!/usr/bin/env python
"""产业链图基线验收打分（方案 §7.1，2026-10-25）。

对**历史产物**做确定性打分，不调模型、不联网、不重跑流水线——秒级出结果，
所以每次改渲染/修复层都可以先跑它看有没有变好，再决定要不要真跑。

指标（口径见 `output/AI产业链图优化方案_复用ChainKnowledgeGraph_20261025.md` §7.1）：

| 指标 | 计算 | 门槛 |
|---|---|---|
| 结构命中率 | golden `must_have` 必备环节命中组数 / 总组数 | 100% |
| 覆盖率 | 有企业的环节 / 可承载企业的环节 | ≥80% |
| 下游场景完整率 | 有 `buyer` 的下游卡 / 下游卡总数 | ≥80% |
| 泛词环节 | 标题是「核心部件/关键材料…」的环节数 | = 0 |
| 数字/占位违规 | 环节名·品类·企业名含数字 + description 占位语 | = 0 |
| 主题词进品牌卡 | 品牌卡企业名等于主题/核心产品词 | = 0 |
| KB 命中 | 有 KB 记录的企业名 / 全部企业名 | 信息项，见下 |

**两处口径（2026-10-25 修正，不是放宽门槛）**

1. 覆盖率分母**排除「下游卡 + buyer 已填」**。依据是系统契约而非指标好看：
   `ChainNode.buyer` 的注释就是「下游场景采购方」，`chain_render.py` 画「采购方：…」，
   `chain_lint.py` 校验的是 buyer 是否上图，`chain_topology.repair_topology` 0.1 步
   专门把客户类型（个人消费者/高校/政府机构）从 `companies` 搬进 `buyer`。
   所以下游卡 `companies` 为空、`buyer` 有内容 = **内容完整**，把它算成「缺企业」是错口径。
   下游卡 `buyer` 也空的仍然计入分母（那才是真缺口：没人说清谁在用）。
   ⚠️ 本口径不校验 `buyer` 本身是否属实，那由 `chain_lint` 与人工抽检覆盖。

2. KB 命中率**只作信息项，不进退出码**。底座 `chart_kb/index.json` 写明
   `data_as_of = 2021-10`：2021 年 10 月之后上市的公司根本不在里面
   （实测笔记本图 12 家未命中里，华勤技术/亿道信息/龙旗科技/智微智能/思看科技
   5 家都是 2022-2025 上市的 A 股）。「不命中」不等于「图上写错」，
   拿它当硬门槛会逼着人去放宽 `chain_kb._role_of`，而那正是模块文档里记着的
   历史事故（86 项只对 48 项、误杀 4 个真品牌）。

用法：
    python scripts/score_chain_baseline.py                        # 扫 data/runs 全部产物
    python scripts/score_chain_baseline.py --since 20261017       # 只扫该日期之后的（验收基线）
    python scripts/score_chain_baseline.py --limit 40             # 只扫最近 40 个 run
    python scripts/score_chain_baseline.py --write                # 同时写 output/ 报告
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "agents_core", "chart-generator"))

from chart_generator import chain_kb                      # noqa: E402
from chart_generator.chain_lint import sanitize_text_no_numbers  # noqa: E402
from chart_generator.chain_ontology import (              # noqa: E402
    is_generic_label,
    provides_companies,
    role_for_label,
)

GOLDEN = os.path.join(ROOT, "agents_core", "chart-generator", "tests", "golden",
                      "chain_brand_golden.json")
PLACEHOLDERS = ("证据未覆盖", "证据不足", "待补充", "暂无数据", "暂无", "待核实")
THRESHOLDS = {"structure": 1.0, "coverage": 0.80}


def baseline_failed(rows: list[dict]) -> bool:
    """Strict per-artifact release gate; unknown structure is not a passing score."""
    if not rows:
        return True
    for row in rows:
        if row.get('structure') is None or row['structure'] < THRESHOLDS['structure']:
            return True
        if row.get('coverage', 0) < THRESHOLDS['coverage']:
            return True
        if row.get('scene_rate') is not None and row['scene_rate'] < THRESHOLDS['coverage']:
            return True
        if any(row.get(key) for key in ('violations', 'topic_leak', 'generic')):
            return True
    return False
# KB 命中率的 70% 门槛已撤销（2026-10-25）：底座快照截止 2021-10，新上市公司必然不命中，
# 拿它判失败等于逼人放宽 chain_kb._role_of。现值只作信息项打印。


def is_number_violation(text: str) -> bool:
    """该文本是否因含「数值」而在渲染边界被杀掉。

    🔴 必须复用 `chain_lint.sanitize_text_no_numbers` 的判据，不能自己写 ``[0-9]``。
    那个函数放行**型号/等级代号**（3D / 3C / 5G / L4 / H800 / HBM3 / 35KV / 220KV 海缆），
    只杀财务数值与占位符。本脚本旧版用粗判据，把「3D激光雷达与深度相机」
    「3C电子装配」「220KV海缆」全报成违规——83 条违规里 24 条是这么来的假阳性。
    项目里已经因为「体检器放行、清洗器删掉」的口径不一致丢过 3 张下游卡
    （run-20261019124137 车载激光雷达），这里不再制造第二处。
    """
    t = str(text or "").strip()
    if not t:
        return False
    if any(p in t for p in PLACEHOLDERS):
        return False                       # 占位语单独统计，别同一问题报两次
    return not sanitize_text_no_numbers(t, max_len=len(t) + 10)


def load_golden() -> dict:
    with open(GOLDEN, encoding="utf-8") as fh:
        return json.load(fh)


def match_industry(title: str, core_product: str, cases: list[dict]) -> dict | None:
    """按标题/核心产品词匹配金标准行业（长词优先，避免「机器人」抢走「工业机器人」）。"""
    text = f"{title} {core_product}"
    best: tuple[int, dict] | None = None
    for case in cases:
        ind = case["industry"]
        if ind in text:
            if best is None or len(ind) > best[0]:
                best = (len(ind), case)
    return best[1] if best else None


def score_artifact(cg: dict, golden: dict) -> dict:
    nodes = [n for n in (cg.get("nodes") or []) if isinstance(n, dict)]
    title = str(cg.get("title") or "")
    core_product = str(cg.get("core_product") or "")
    case = match_industry(title, core_product, golden.get("structure_cases") or [])
    forbidden = set(golden.get("forbidden_slot_labels") or [])

    # ① 泛词环节
    generic = [str(n.get("name") or "") for n in nodes
               if is_generic_label(n.get("name"))]

    # ② 覆盖率（`in_house` 不计分母；下游卡改由 `buyer` 承载，见模块 docstring 口径 1）
    denom = num = 0
    scene_total = scene_ok = 0
    for n in nodes:
        name = str(n.get("name") or "")
        role = role_for_label(name, is_core=bool(n.get("is_core")))
        stage = str(n.get("stage") or "")
        buyer = str(n.get("buyer") or "").strip()
        if stage == "downstream":
            scene_total += 1
            if buyer:
                scene_ok += 1
        if not provides_companies(role):
            continue
        # 下游卡 + buyer 已填 = 场景卡内容完整，companies 空是设计（客户不是企业）
        if stage == "downstream" and buyer:
            continue
        denom += 1
        if [c for c in (n.get("companies") or []) if str(c).strip()]:
            num += 1
    coverage = (num / denom) if denom else 0.0
    scene_rate = (scene_ok / scene_total) if scene_total else None

    # ③ 数字 / 占位语违规（数字判据复用 chain_lint，见 is_number_violation）
    violations: list[str] = []
    for n in nodes:
        name = str(n.get("name") or "")
        if is_number_violation(name):
            violations.append(f"环节名含数值「{name}」")
        for c in (n.get("companies") or []):
            if is_number_violation(str(c)):
                violations.append(f"企业名含数值「{c}」")
        for it in (n.get("items") or []):
            if is_number_violation(str(it)):
                violations.append(f"品类含数值「{it}」")
        desc = str(n.get("description") or "")
        if any(p in desc for p in PLACEHOLDERS):
            violations.append(f"占位语「{desc}」")
        if name in forbidden:
            violations.append(f"泛词标题「{name}」")

    # ④ 主题词进品牌卡
    core = next((n for n in nodes if n.get("is_core")), None)
    topic_leak: list[str] = []
    if core is not None:
        for c in (core.get("companies") or []):
            c = str(c).strip()
            if not c:
                continue
            if c == core_product or c == title.replace("产业链", "").replace("图谱", "") \
                    or (len(c) >= 3 and c in title and c in (core_product or "")):
                topic_leak.append(c)

    # ⑤ KB 命中
    names = [str(c).strip() for n in nodes for c in (n.get("companies") or [])
             if str(c).strip()]
    hit = sum(1 for c in names if chain_kb.company_profile(c) is not None)
    kb_rate = (hit / len(names)) if names else 0.0

    # ⑥ 结构命中（仅当行业在金标准里）
    struct_hit = struct_total = 0
    missed: list[str] = []
    if case:
        labels = " ".join(str(n.get("name") or "") + " " + " ".join(
            str(i) for i in (n.get("items") or [])) for n in nodes)
        for group in case.get("must_have") or []:
            struct_total += 1
            if any(k in labels for k in group):
                struct_hit += 1
            else:
                missed.append(group[0])

    return {
        "title": title, "core_product": core_product,
        "industry": (case or {}).get("industry", ""),
        "nodes": len(nodes),
        "companies": len(names),
        "generic": generic,
        "coverage": coverage,
        "scene_rate": scene_rate,
        "kb_rate": kb_rate,
        "violations": violations,
        "topic_leak": topic_leak,
        "structure": (struct_hit / struct_total) if struct_total else None,
        "struct_missed": missed,
    }


def collect(limit: int | None, since: str = "") -> list[dict]:
    """收集历史产物。``since`` 形如 ``20261017``，只收该日期及之后的 run。

    为什么要按日期切：`data/runs` 里混着 9 月与 10 月中旬的旧产物，
    其中 5 张是 `nodes=3` 的空壳图（10-17 之前「六主题逐字节相同」那个 bug 的遗留，
    覆盖率恒 0%），还有白酒那批 F1-F4 修复前的旧版本。
    把它们算进「当前能力」会把均值从 82% 拉到 74%，是拿历史债给现在的代码定罪。
    """
    paths = sorted(glob.glob(os.path.join(ROOT, "data", "runs", "*", "artifacts",
                                          "chart_result.json")))
    if since:
        paths = [p for p in paths
                 if p.split(os.sep)[-3].replace("run-", "")[:8] >= since]
    if limit:
        paths = paths[-limit:]
    out: list[dict] = []
    for p in paths:
        try:
            with open(p, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            continue
        for chart in (data.get("charts") or []):
            cg = chart.get("chain_graph")
            if isinstance(cg, dict) and cg.get("nodes"):
                out.append({"run": p.split(os.sep)[-3], "graph": cg})
    return out


def fmt_pct(v: float | None) -> str:
    return "—" if v is None else f"{v * 100:.0f}%"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="只扫最近 N 个 run")
    ap.add_argument("--since", default="",
                    help="只扫该日期及之后的 run，形如 20261017（验收基线建议用）")
    ap.add_argument("--write", action="store_true", help="写 output/ 报告")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    golden = load_golden()
    items = collect(args.limit, args.since)
    if not items:
        print("没找到任何 chain_graph 产物（data/runs/*/artifacts/chart_result.json）")
        return 1

    rows = [dict(score_artifact(it["graph"], golden), run=it["run"]) for it in items]
    n = len(rows)

    # ── 汇总 ────────────────────────────────────────────────────────────────
    def avg(key: str) -> float:
        vals = [r[key] for r in rows if r[key] is not None]
        return sum(vals) / len(vals) if vals else 0.0

    def med(key: str) -> float:
        vals = sorted(r[key] for r in rows if r[key] is not None)
        if not vals:
            return 0.0
        mid = len(vals) // 2
        return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2

    cov_vals = [r["coverage"] for r in rows]
    cov_pass = sum(1 for c in cov_vals if c >= THRESHOLDS["coverage"])
    # 判定用中位数：均值会被 `nodes=3` 空壳图（恒 0%）单点拖垮，
    # 那是 10-17 之前旧 bug 的遗留产物，不该给现在的代码定罪。
    cov_judge = med("coverage")

    generic_clean = sum(1 for r in rows if not r["generic"])
    viol_clean = sum(1 for r in rows if not r["violations"])
    leak_clean = sum(1 for r in rows if not r["topic_leak"])
    struct_rows = [r for r in rows if r["structure"] is not None]

    lines: list[str] = []
    add = lines.append
    add(f"# 产业链图基线验收报告（{datetime.now():%Y-%m-%d %H:%M}）")
    add("")
    scope = f"（时间窗 `--since {args.since}`）" if args.since else "（全量历史，含 10-17 前的旧产物）"
    add(f"样本：`data/runs` 下 {n} 张产业链图{scope}，离线打分，未重跑流水线。")
    add("")
    add("## 一、汇总")
    add("")
    add("| 指标 | 当前 | 门槛 | 判定 |")
    add("|---|---|---|---|")
    add(f"| 覆盖率中位数（抗空壳图干扰） | {fmt_pct(cov_judge)} | ≥80% | "
        f"{'✅' if cov_judge >= THRESHOLDS['coverage'] else '❌'} |")
    add(f"| 覆盖率均值（参考） | {fmt_pct(avg('coverage'))} | — | ℹ️ |")
    add(f"| 覆盖率达标图（≥80%） | {cov_pass}/{n} = {cov_pass / n * 100:.0f}% | — | ℹ️ |")
    scene_avg = avg("scene_rate") if any(r["scene_rate"] is not None for r in rows) else None
    add(f"| 下游场景完整率（有 buyer 的下游卡） | {fmt_pct(scene_avg)} | ≥80% | "
        f"{'✅' if (scene_avg or 0) >= THRESHOLDS['coverage'] else '❌'} |")
    add(f"| KB 命中（信息项，不判失败） | {fmt_pct(avg('kb_rate'))} | — | ℹ️ 见下 |")
    add(f"| 泛词环节为 0 的图 | {generic_clean}/{n} | 全部 | "
        f"{'✅' if generic_clean == n else '❌'} |")
    add(f"| 数字/占位/泛词零违规的图 | {viol_clean}/{n} | 全部 | "
        f"{'✅' if viol_clean == n else '❌'} |")
    add(f"| 主题词未进品牌卡的图 | {leak_clean}/{n} | 全部 | "
        f"{'✅' if leak_clean == n else '❌'} |")
    if struct_rows:
        add(f"| 结构命中率（golden must_have） | {fmt_pct(avg('structure'))} | 100% | "
            f"{'✅' if avg('structure') >= THRESHOLDS['structure'] else '❌'} |")
    add("")
    add(f"泛词环节总数：**{sum(len(r['generic']) for r in rows)}** 个；"
        f"违规总数：**{sum(len(r['violations']) for r in rows)}** 条；"
        f"主题词进品牌卡：**{sum(len(r['topic_leak']) for r in rows)}** 处。")
    add("")
    add("> **KB 命中为什么是信息项**：底座 `chart_kb/index.json` 的 `data_as_of` 是 "
        "2021-10，2021 年 10 月后上市的公司不在快照里（实测笔记本图 12 家未命中中 "
        "5 家是 2022-2025 上市的 A 股）。「不命中」≠「写错」，做成硬门槛只会逼人"
        "放宽 `chain_kb._role_of`，而那在模块文档里记着历史事故。")
    add("")

    # ── 分行业 ──────────────────────────────────────────────────────────────
    if struct_rows:
        add("## 二、分行业结构命中（金标准必备环节）")
        add("")
        add("| 行业 | 图数 | 结构命中 | 覆盖率 | 下游完整 | 泛词图数 | 缺的必备环节 |")
        add("|---|---|---|---|---|---|---|")
        by_ind: dict[str, list[dict]] = {}
        for r in struct_rows:
            by_ind.setdefault(r["industry"], []).append(r)
        for ind, group in sorted(by_ind.items(),
                                 key=lambda kv: -sum(1 for g in kv[1])):
            s = sum(g["structure"] for g in group) / len(group)
            c = sum(g["coverage"] for g in group) / len(group)
            sc = [g["scene_rate"] for g in group if g["scene_rate"] is not None]
            sc_avg = sum(sc) / len(sc) if sc else None
            g_count = sum(1 for g in group if g["generic"])
            missed = sorted({m for g in group for m in g["struct_missed"]})
            add(f"| {ind} | {len(group)} | {fmt_pct(s)} | {fmt_pct(c)} | {fmt_pct(sc_avg)} | "
                f"{g_count} | {'、'.join(missed) or '—'} |")
        add("")

    # ── 最差样本 ────────────────────────────────────────────────────────────
    add("## 三、问题最集中的样本（按违规+泛词排序）")
    add("")
    add("| run | 标题 | 节点 | 企业 | 泛词 | 违规 | 主题词进品牌卡 | 覆盖率 |")
    add("|---|---|---|---|---|---|---|---|")
    worst = sorted(rows, key=lambda r: -(len(r["violations"]) + len(r["generic"])))[:12]
    for r in worst:
        add(f"| {r['run'][:24]} | {r['title'][:20]} | {r['nodes']} | {r['companies']} | "
            f"{'、'.join(r['generic'][:3]) or '—'} | {len(r['violations'])} | "
            f"{'、'.join(r['topic_leak']) or '—'} | {fmt_pct(r['coverage'])} |")
    add("")
    add("> 说明：本报告只统计**确定性可判**的项。归属正确率（人工抽检 ≥95%）"
        "需要真跑后人工确认，见方案 §7.2。")

    text = "\n".join(lines)
    if not args.quiet:
        print(text)
    if args.write:
        suffix = f"_since{args.since}" if args.since else "_全量"
        out = os.path.join(ROOT, "output",
                           f"产业链图基线验收报告_{datetime.now():%Y%m%d}{suffix}.md")
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"\n已写入 {out}")

    # 退出码：任一门槛不过 → 1（可接 CI）
    # ⚠️ kb_rate 刻意不在其中：它是信息项，理由见模块 docstring 口径 2。
    failed = baseline_failed(rows)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
