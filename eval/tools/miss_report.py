"""周度 miss 提取脚本（2026-09-01 方案 §2 第四刀·改动点 1）。

从 ``artifacts/routing_telemetry/*.jsonl`` 提取四类观测事件并按
sha256 聚合，输出周报：

- ``route_decision`` 中 ``skill=None`` 或 ``below_threshold=True`` → miss；
- ``clarification`` → 澄清门事件（含 unsupported_metrics 回流）；
- ``llm_veto`` → LLM 显式否决（周审否决率，健康区间 5%-20%）；
- ``advisory_passed`` / ``derivative_suspected`` → 放行与降级观测。

用法::

    python -m eval.tools.miss_report
    python -m eval.tools.miss_report --dir artifacts/routing_telemetry --top 20
    python -m eval.tools.miss_report --run-prefix eval-20260901   # 只看评测批次

遥测卫生：只读不删。清理历史日志时必须按 run_id 精确删除本批记录，
严禁整文件删除（其中混有生产真实日志）。
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def _default_dir() -> Path:
    # eval/tools/miss_report.py -> 项目根 / artifacts / routing_telemetry
    return Path(__file__).resolve().parents[2] / "artifacts" / "routing_telemetry"


def _text_sha(record: dict, field: str) -> str:
    payload = record.get(field) or {}
    if isinstance(payload, dict):
        return str(payload.get("sha256") or "")
    return ""


def _iter_records(directory: Path, *, run_prefix: str | None):
    for path in sorted(directory.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if run_prefix and not str(record.get("run_id") or "").startswith(run_prefix):
                continue
            yield record


def build_report(
    directory: Path,
    *,
    top: int = 10,
    run_prefix: str | None = None,
) -> dict:
    misses: Counter[str] = Counter()
    clarifications: Counter[str] = Counter()
    vetoes: Counter[str] = Counter()
    advisories: Counter[str] = Counter()
    derivatives: Counter[str] = Counter()
    total = 0
    route_decisions = 0

    for record in _iter_records(directory, run_prefix=run_prefix):
        total += 1
        event = record.get("event")
        if event == "route_decision":
            route_decisions += 1
            if record.get("skill") is None or record.get("below_threshold"):
                misses[_text_sha(record, "text") or "(unknown)"] += 1
        elif event == "clarification":
            clarifications[_text_sha(record, "question") or "(unknown)"] += 1
        elif event == "llm_veto":
            vetoes[_text_sha(record, "text") or "(unknown)"] += 1
        elif event == "advisory_passed":
            advisories[_text_sha(record, "question") or "(unknown)"] += 1
        elif event == "derivative_suspected":
            derivatives[str(record.get("metric") or "(unknown)")] += 1

    veto_rate = len(vetoes) / route_decisions if route_decisions else 0.0
    advisory_rate = len(advisories) / route_decisions if route_decisions else 0.0
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "directory": str(directory),
        "run_prefix": run_prefix,
        "total_records": total,
        "route_decisions": route_decisions,
        "veto_rate": round(veto_rate, 4),
        "advisory_rate": round(advisory_rate, 4),
        "top_misses": misses.most_common(top),
        "top_clarifications": clarifications.most_common(top),
        "top_vetoes": vetoes.most_common(top),
        "top_advisories": advisories.most_common(top),
        "top_derivative_metrics": derivatives.most_common(top),
    }


def render_report(report: dict) -> str:
    lines = [
        "==== Agent 1 路由 miss 周报 ====",
        f"生成时间: {report['generated_at']}",
        f"遥测目录: {report['directory']}",
        f"批次过滤: {report['run_prefix'] or '(全部)'}",
        f"记录总数: {report['total_records']}  路由决策数: {report['route_decisions']}",
        f"否决率: {report['veto_rate']:.2%}  advisory 率: {report['advisory_rate']:.2%}",
        "(否决率健康区间 5%-20%；>30% 触发 prompt 审查)",
        "",
        "-- Top miss（route_decision 未命中/低置信，按 sha256 聚合）--",
    ]
    for sha, count in report["top_misses"]:
        lines.append(f"  {count:>4}  {sha}")
    lines += ["", "-- Top 澄清门事件 --"]
    for sha, count in report["top_clarifications"]:
        lines.append(f"  {count:>4}  {sha}")
    lines += ["", "-- Top LLM 否决 --"]
    for sha, count in report["top_vetoes"]:
        lines.append(f"  {count:>4}  {sha}")
    lines += ["", "-- Top advisory 放行 --"]
    for sha, count in report["top_advisories"]:
        lines.append(f"  {count:>4}  {sha}")
    lines += ["", "-- Top 派生词降级指标 --"]
    for metric, count in report["top_derivative_metrics"]:
        lines.append(f"  {count:>4}  {metric}")
    lines += [
        "",
        "分流规则（方案 §2 第四刀）:",
        "  高频词/别名（周≥3次）→ 进词表配置（不发版）",
        "  仲裁规则 case → 改否定表/仲裁代码，走评测集回归",
        "  长尾口语 → 留给 L2，不进 L1",
        "  真数据缺口 → 登记研究边界词表，永不硬路由",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent 1 路由 miss 周报")
    parser.add_argument("--dir", type=Path, default=None, help="遥测目录（默认 artifacts/routing_telemetry）")
    parser.add_argument("--top", type=int, default=10, help="每类输出的聚合条数")
    parser.add_argument("--run-prefix", default=None, help="只统计指定 run_id 前缀（评测批次隔离）")
    parser.add_argument("--json", action="store_true", help="输出 JSON 而不是周报文本")
    args = parser.parse_args()

    directory = args.dir or _default_dir()
    if not directory.exists():
        raise SystemExit(f"遥测目录不存在: {directory}")
    report = build_report(directory, top=args.top, run_prefix=args.run_prefix)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_report(report))


if __name__ == "__main__":
    main()
