"""生成智能体3 的六图交付产物（line/bar/combo/area/pie/radar）。

## 为什么这样驱动

本脚本**只调用智能体3（chart_generate）自身的代码**，不触发其余四个智能体：

    chart_generator.data_formulation.DataFormulator   # 证据 -> 规范化数据表
    chart_generator.compiler.EChartsCompiler          # 数据表 -> ECharts option
    chart_generator.render.render_svg                 # option -> 出版级 SVG

绕开 LLM 选型环节的原因：`agent.py` 的候选生成由 LLM 的图表选型指引驱动，LLM
不保证为每类图都产出候选（实测 `pie` 不会被选中），因此这里按类型**显式驱动**
编译器，以验证并交付六种图型的渲染能力。

## 数据来源

- 真实数据：`data/runs/run-20260922213739-783/artifacts/interpretation_report.json`
  （动力电池行业，evidence_index 502 条，含真实 record_id）
- 演示数据：`output/agent3_demo/source/interpretation_report.json`
  （构成类份额数据，仅用于 `pie`；record_id 前缀 `R-DEMO-`，指标名含「（演示数据）」）

用法:
    python scripts/generate_agent3_six_charts.py
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHART_AGENT_DIR = PROJECT_ROOT / "agents_core/chart-generator"
sys.path.insert(0, str(CHART_AGENT_DIR))
sys.path.insert(0, str(PROJECT_ROOT))

from chart_generator.compiler import EChartsCompiler  # noqa: E402
from chart_generator.data_formulation import DataFormulator  # noqa: E402
from chart_generator.models import InterpretationReport  # noqa: E402
from chart_generator.render import render_svg  # noqa: E402

REAL_SOURCE = PROJECT_ROOT / "data/runs/run-20260922213739-783/artifacts/interpretation_report.json"
DEMO_SOURCE = PROJECT_ROOT / "output/agent3_demo/source/interpretation_report.json"
OUTPUT_DIR = PROJECT_ROOT / "output/agent3_six_charts"

# 六种启用图型 + 各自的候选指标名（用于挑选合适的数据形态）
TARGETS: list[tuple[str, str, str]] = [
    # (chart_type, 标题, 提示：用哪类数据)
    ("line", "财务诊断评分趋势", "real"),
    ("bar", "营业收入横向比较", "real"),
    ("combo", "研发费用同比增长率与归母净利润", "real"),
    ("area", "归母净利润趋势（面积）", "real"),
    ("radar", "单实体多指标雷达", "real"),
    ("pie", "动力电池装机份额构成（演示数据）", "demo"),
]

# radar 需要的指标名（单实体多维）
RADAR_METRICS = ["营业收入", "归母净利润", "毛利率", "净利率", "资产负债率", "研发费用同比增长率"]


def load_reports() -> tuple[InterpretationReport, InterpretationReport | None]:
    """载入真实与演示数据源。

    Returns:
        (真实报告, 演示报告或 None)

    Raises:
        FileNotFoundError: 真实数据源缺失。
    """
    if not REAL_SOURCE.is_file():
        raise FileNotFoundError(f"真实数据源不存在：{REAL_SOURCE}")
    real = InterpretationReport.model_validate(
        json.loads(REAL_SOURCE.read_text(encoding="utf-8"))
    )
    demo = None
    if DEMO_SOURCE.is_file():
        demo = InterpretationReport.model_validate(
            json.loads(DEMO_SOURCE.read_text(encoding="utf-8"))
        )
    return real, demo


def group_ids_by_metric(report: InterpretationReport) -> dict[str, list[str]]:
    """把 evidence_index 按 metric 分组为 record_id 列表。"""
    buckets: dict[str, list[str]] = defaultdict(list)
    for record_id, ref in report.evidence_index.items():
        buckets[ref.metric].append(record_id)
    return dict(buckets)


def build_for_type(
    chart_type: str,
    report: InterpretationReport,
    by_metric: dict[str, list[str]],
) -> tuple[object | None, str]:
    """为指定图型挑选可用数据并构建规范化数据表。

    Args:
        chart_type: 六图之一。
        report: 数据源报告。
        by_metric: metric -> record_id 列表。

    Returns:
        (NormalizedDataTable 或 None, 说明信息)
    """
    if chart_type == "radar":
        # 雷达图要求「单一实体的多个不同指标」。
        # 动态挑选覆盖指标数最多的实体 —— 不可硬编码指标名：evidence_index 里的
        # metric 名带单位/嵌套（如「净资产收益率(净资产收益率(ROE))」），硬编码会
        # 挑不到数据，导致 formulate 退化成 TIME_SERIES、最终渲染成时序图而非雷达。
        ent_to_ids: dict[str, list[str]] = defaultdict(list)
        for _metric, ids in by_metric.items():
            for rid in ids:
                ref = report.evidence_index.get(rid)
                if ref is None or not ref.entity or not isinstance(ref.value, (int, float)):
                    continue
                if rid not in ent_to_ids[ref.entity]:
                    ent_to_ids[ref.entity].append(rid)
        if ent_to_ids:
            entity, ids = max(ent_to_ids.items(), key=lambda kv: len(kv[1]))
            if len(ids) >= 3:
                # 雷达维度过多会互相挤压、不可读，取前 8 项（业内 5~8 维为宜）
                picked = ids[:8]
                table = DataFormulator.formulate(picked, report, target_chart_type="radar")
                if table is not None:
                    return table, f"{entity} 的 {len(picked)} 项指标"

    # 其余图型：逐个 metric 试探，命中即用
    for metric, ids in by_metric.items():
        if len(ids) < 2:
            continue
        table = DataFormulator.formulate(ids, report, target_chart_type=chart_type)
        if table is not None:
            return table, f"指标「{metric}」，{len(ids)} 条证据"
    return None, "无适配数据"


def main() -> int:
    """生成六图交付产物，返回进程退出码。"""
    real, demo = load_reports()
    real_by_metric = group_ids_by_metric(real)
    demo_by_metric = group_ids_by_metric(demo) if demo else {}

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, object]] = []

    print("=" * 78)
    print("智能体3 六图交付（仅调用 chart_generator，不触发其他智能体）")
    print("=" * 78)

    for chart_type, title, source_kind in TARGETS:
        report = real if source_kind == "real" else demo
        by_metric = real_by_metric if source_kind == "real" else demo_by_metric
        if report is None:
            print(f"[跳过] {chart_type:6} 数据源缺失")
            manifest.append({"chart_type": chart_type, "title": title, "status": "skipped"})
            continue

        table, note = build_for_type(chart_type, report, by_metric)
        if table is None:
            print(f"[失败] {chart_type:6} {title} — {note}")
            manifest.append(
                {"chart_type": chart_type, "title": title, "status": "failed", "note": note}
            )
            continue

        # 关键：编译器入口只接受六图，禁用类型无法产出
        option = EChartsCompiler.compile(table, chart_type, title)
        footnotes = [f"数据来源：{'演示数据（非真实）' if source_kind == 'demo' else '项目现有数据源'}", note]
        svg = render_svg(title, chart_type, option, footnotes)

        svg_name = f"{chart_type}.svg"
        (OUTPUT_DIR / svg_name).write_text(svg, encoding="utf-8")

        series_count = len(getattr(table, "series_data", {}) or {})
        point_count = sum(len(v) for v in (getattr(table, "series_data", {}) or {}).values())
        eid_map = getattr(table, "point_evidence_ids", {}) or {}
        eid_count = sum(len(v) for v in eid_map.values())
        manifest.append(
            {
                "chart_type": chart_type,
                "title": title,
                "status": "ok",
                "source": "demo" if source_kind == "demo" else "real",
                "svg": svg_name,
                "svg_bytes": len(svg.encode("utf-8")),
                "series": series_count,
                "points": point_count,
                "point_evidence_ids": eid_count,
                "axis_type": str(getattr(table, "axis_type", "")),
                "note": note,
            }
        )
        flag = "演示" if source_kind == "demo" else "真实"
        print(
            f"[成功] {chart_type:6} {title[:28]:30} 系列={series_count} 点={point_count} "
            f"点级证据={eid_count} [{flag}]"
        )

    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    ok = sum(1 for m in manifest if m["status"] == "ok")
    print("-" * 78)
    print(f"完成：{ok}/{len(TARGETS)} 种图型产出，输出目录 {OUTPUT_DIR}")
    return 0 if ok == len(TARGETS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
