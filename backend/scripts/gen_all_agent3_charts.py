"""用捏造数据调用 Agent 3 全部图表 builder，导出 option JSON + SVG。

演示用途，不代表真实研究结论。
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

from app.agents.chart_generator.builders import (
    build_area_option,
    build_bar_option,
    build_boxplot_option,
    build_bubble_option,
    build_combo_option,
    build_dual_panel_option,
    build_heatmap_option,
    build_industry_chain_option,
    build_line_option,
    build_pie_option,
    build_radar_option,
    build_scatter_option,
    build_treemap_option,
)
from app.reporting.svg import render_chart_svg
from app.schemas.chart import (
    ChainEdge,
    ChainNode,
    ChartDataset,
    ChartPanel,
    ChartPoint,
    ChartSeriesMeta,
    ChartSpec,
    DistributionSample,
    HierarchyNode,
    MatrixCell,
    XYPoint,
)

OUT = Path(__file__).resolve().parent.parent / "test_output" / "agent3_all_charts"
BANNER = "演示捏造数据，不代表真实研究结论"


def _fp(title: str) -> str:
    return hashlib.sha256(f"demo-{title}".encode()).hexdigest()


def _spec(chart_id: str, title: str, chart_type: str, variant: str, option: dict, evidences: list[str], **kw) -> ChartSpec:
    return ChartSpec(
        chart_id=chart_id,
        title=title,
        chart_type=chart_type,
        variant=variant,
        option=option,
        evidence_ids=evidences,
        insight_goal=f"{title}（{BANNER}）",
        footnotes=[BANNER],
        data_fingerprint=_fp(title),
        dedupe_key=f"demo::{chart_id}",
        **kw,
    )


def periods(n: int, start: int = 2023) -> list[date]:
    return [date(start + i, 12, 31) for i in range(n)]


def build_all() -> list[tuple[str, ChartSpec]]:
    out: list[tuple[str, ChartSpec]] = []
    ev = ["E-DEMO-001", "E-DEMO-002", "E-DEMO-003"]

    # 1) line
    ds_line = ChartDataset(
        dataset_id="DS-LINE",
        kind="time_series",
        metric_name="动力电池装机量",
        unit="GWh",
        evidence_ids=ev,
        points=[
            ChartPoint(label=str(y), value=v, series="装机量", period_end=date(y, 12, 31), evidence_id="E-DEMO-001")
            for y, v in [(2023, 388), (2024, 548), (2025, 720), (2026, 880)]
        ],
    )
    out.append(("line", _spec("CHART-DEMO-LINE", "演示：装机量趋势", "line", "line", build_line_option("演示：装机量趋势", ds_line), ev)))

    # 2) bar vertical
    ds_bar = ChartDataset(
        dataset_id="DS-BAR",
        kind="categorical",
        metric_name="市场份额",
        unit="%",
        evidence_ids=ev,
        points=[
            ChartPoint(label=lab, value=val, series="份额", evidence_id="E-DEMO-002")
            for lab, val in [("宁德时代", 43.1), ("比亚迪", 24.7), ("中创新航", 8.1), ("其他", 24.1)]
        ],
    )
    out.append(("bar", _spec("CHART-DEMO-BAR", "演示：装机份额", "bar", "vertical", build_bar_option("演示：装机份额", ds_bar, "vertical"), ev)))

    # 3) pie
    ds_pie = ChartDataset(
        dataset_id="DS-PIE",
        kind="categorical",
        metric_name="收入结构",
        unit="%",
        is_composition=True,
        evidence_ids=ev,
        points=[
            ChartPoint(label=lab, value=val, series="结构", evidence_id="E-DEMO-003")
            for lab, val in [("数据中心", 42), ("客户端", 28), ("游戏", 18), ("嵌入式", 12)]
        ],
    )
    out.append(("pie", _spec("CHART-DEMO-PIE", "演示：收入结构", "pie", "pie", build_pie_option("演示：收入结构", ds_pie), ev)))

    # 4) radar
    dims = ["规模", "盈利", "成长", "研发", "份额"]
    ds_radar = ChartDataset(
        dataset_id="DS-RADAR",
        kind="categorical",
        metric_name="企业综合得分",
        unit="分",
        is_standardized=True,
        scale_min=0,
        scale_max=100,
        evidence_ids=ev,
        points=[
            ChartPoint(label=d, value=v, series=s, evidence_id="E-DEMO-001")
            for s, vals in [("宁德时代", [90, 88, 75, 86, 92]), ("中创新航", [62, 58, 70, 64, 55])]
            for d, v in zip(dims, vals)
        ],
    )
    out.append(("radar", _spec("CHART-DEMO-RADAR", "演示：企业对比雷达", "radar", "radar", build_radar_option("演示：企业对比雷达", ds_radar), ev)))

    # 5) industry_chain
    ds_chain = ChartDataset(
        dataset_id="DS-CHAIN",
        kind="industry_chain",
        metric_name="产业链结构",
        evidence_ids=ev,
        core_product_name="动力电池",
        chain_template_hint="horizontal_flow",
        nodes=[
            ChainNode(node_id="N1", label="锂资源", stage="upstream", node_kind="material", evidence_ids=ev),
            ChainNode(node_id="N2", label="正极材料", stage="upstream", node_kind="material", evidence_ids=ev),
            ChainNode(node_id="N3", label="电芯制造", stage="midstream", node_kind="manufacturing", is_core=True, evidence_ids=ev),
            ChainNode(node_id="N4", label="PACK", stage="midstream", node_kind="product", evidence_ids=ev),
            ChainNode(node_id="N5", label="整车", stage="downstream", node_kind="application", evidence_ids=ev),
            ChainNode(node_id="N6", label="设备与回收", stage="support", node_kind="service", evidence_ids=ev),
        ],
        edges=[
            ChainEdge(source="N1", target="N2", evidence_ids=ev),
            ChainEdge(source="N2", target="N3", evidence_ids=ev),
            ChainEdge(source="N3", target="N4", evidence_ids=ev),
            ChainEdge(source="N4", target="N5", evidence_ids=ev),
            ChainEdge(source="N6", target="N3", flow_type="support", evidence_ids=ev),
        ],
    )
    out.append(
        (
            "industry_chain",
            _spec(
                "CHART-DEMO-CHAIN",
                "演示：动力电池产业链",
                "industry_chain",
                "graph",
                build_industry_chain_option("演示：动力电池产业链", ds_chain),
                ev,
                chain_template="horizontal_flow",
                chain_graph={"nodes": [], "edges": []},
            ),
        )
    )

    # 6) combo —— 真正的双轴复合：柱（出货）+ 线（均价）
    ds_combo = ChartDataset(
        dataset_id="DS-COMBO",
        kind="time_series",
        metric_name="出货与均价",
        unit="混合",
        evidence_ids=ev,
        series_meta=[
            ChartSeriesMeta(name="出货量", unit="GWh", render_as="bar"),
            ChartSeriesMeta(name="均价", unit="万元/吨", render_as="line"),
        ],
        points=[
            *[
                ChartPoint(label=q, value=v, series="出货量", period_end=d, evidence_id="E-DEMO-001")
                for q, v, d in [
                    ("Q1", 120, date(2025, 3, 31)),
                    ("Q2", 135, date(2025, 6, 30)),
                    ("Q3", 150, date(2025, 9, 30)),
                    ("Q4", 160, date(2025, 12, 31)),
                ]
            ],
            *[
                ChartPoint(label=q, value=v, series="均价", period_end=d, evidence_id="E-DEMO-002")
                for q, v, d in [
                    ("Q1", 9.8, date(2025, 3, 31)),
                    ("Q2", 9.1, date(2025, 6, 30)),
                    ("Q3", 7.8, date(2025, 9, 30)),
                    ("Q4", 7.2, date(2025, 12, 31)),
                ]
            ],
        ],
    )
    out.append(
        (
            "combo",
            _spec(
                "CHART-DEMO-COMBO",
                "演示：出货量（柱）× 均价（线）双轴复合",
                "combo",
                "combo",
                build_combo_option("演示：出货量（柱）× 均价（线）双轴复合", ds_combo),
                ev,
            ),
        )
    )

    # 7) area
    ds_area = ChartDataset(
        dataset_id="DS-AREA",
        kind="time_series",
        metric_name="累计装机",
        unit="GWh",
        is_additive=True,
        evidence_ids=ev,
        points=[
            ChartPoint(label=str(y), value=v, series="累计", period_end=date(y, 12, 31), evidence_id="E-DEMO-003")
            for y, v in [(2023, 388), (2024, 936), (2025, 1656), (2026, 2536)]
        ],
    )
    out.append(("area", _spec("CHART-DEMO-AREA", "演示：累计装机面积", "area", "area", build_area_option("演示：累计装机面积", ds_area), ev)))

    # 8) scatter
    ds_sc = ChartDataset(
        dataset_id="DS-SCATTER",
        kind="xy",
        metric_name="研发费用率 vs 净利率",
        x_metric="研发费用率",
        x_unit="%",
        y_metric="净利率",
        y_unit="%",
        evidence_ids=ev,
        xy_points=[
            XYPoint(entity="宁德时代", x=5.2, y=17.0, evidence_ids=["E-DEMO-001"]),
            XYPoint(entity="比亚迪", x=7.9, y=4.1, evidence_ids=["E-DEMO-002"]),
            XYPoint(entity="亿纬锂能", x=5.6, y=6.7, evidence_ids=["E-DEMO-003"]),
            XYPoint(entity="国轩高科", x=7.5, y=3.2, evidence_ids=["E-DEMO-001"]),
        ],
    )
    out.append(("scatter", _spec("CHART-DEMO-SCATTER", "演示：研发 vs 盈利", "scatter", "scatter", build_scatter_option("演示：研发 vs 盈利", ds_sc), ev)))

    # 9) bubble
    ds_bub = ChartDataset(
        dataset_id="DS-BUBBLE",
        kind="xy",
        metric_name="规模-盈利-研发",
        x_metric="营收",
        x_unit="亿元",
        y_metric="净利率",
        y_unit="%",
        size_metric="研发支出",
        size_unit="亿元",
        evidence_ids=ev,
        xy_points=[
            XYPoint(entity="宁德时代", x=4237, y=17.0, size=221, evidence_ids=["E-DEMO-001"]),
            XYPoint(entity="比亚迪", x=8040, y=4.1, size=634, evidence_ids=["E-DEMO-002"]),
            XYPoint(entity="亿纬锂能", x=615, y=6.7, size=34, evidence_ids=["E-DEMO-003"]),
        ],
    )
    out.append(("bubble", _spec("CHART-DEMO-BUBBLE", "演示：气泡图", "bubble", "bubble", build_bubble_option("演示：气泡图", ds_bub), ev)))

    # 10) heatmap
    rows = ["宁德", "比亚迪", "中创新航"]
    cols = ["规模", "盈利", "成长"]
    ds_hm = ChartDataset(
        dataset_id="DS-HEAT",
        kind="matrix",
        metric_name="能力热力",
        unit="分",
        evidence_ids=ev,
        matrix_cells=[
            MatrixCell(row=r, column=c, value=v, evidence_id="E-DEMO-001")
            for r, vals in zip(rows, [[90, 88, 75], [95, 55, 70], [60, 58, 72]])
            for c, v in zip(cols, vals)
        ],
    )
    out.append(("heatmap", _spec("CHART-DEMO-HEAT", "演示：能力热力图", "heatmap", "heatmap", build_heatmap_option("演示：能力热力图", ds_hm), ev)))

    # 11) boxplot
    ds_box = ChartDataset(
        dataset_id="DS-BOX",
        kind="distribution",
        metric_name="毛利率分布",
        unit="%",
        evidence_ids=ev,
        distribution_samples=[
            DistributionSample(group=g, entity=f"E{i}", value=v, evidence_id="E-DEMO-002")
            for g, vals in [("2023", [18, 20, 22, 25, 28]), ("2024", [16, 19, 21, 24, 27]), ("2025", [17, 20, 23, 26, 30])]
            for i, v in enumerate(vals)
        ],
    )
    out.append(("boxplot", _spec("CHART-DEMO-BOX", "演示：毛利率箱线", "boxplot", "boxplot", build_boxplot_option("演示：毛利率箱线", ds_box), ev)))

    # 12) treemap
    ds_tm = ChartDataset(
        dataset_id="DS-TM",
        kind="hierarchy",
        metric_name="收入层级",
        unit="亿元",
        is_composition=True,
        evidence_ids=ev,
        hierarchy_nodes=[
            HierarchyNode(node_id="R", label="合计", value=100, evidence_ids=ev),
            HierarchyNode(node_id="A", label="电池系统", parent_id="R", value=55, evidence_ids=ev),
            HierarchyNode(node_id="B", label="储能", parent_id="R", value=25, evidence_ids=ev),
            HierarchyNode(node_id="C", label="材料回收", parent_id="R", value=20, evidence_ids=ev),
        ],
    )
    out.append(("treemap", _spec("CHART-DEMO-TM", "演示：收入矩形树图", "treemap", "treemap", build_treemap_option("演示：收入矩形树图", ds_tm), ev)))

    # 13) dual_panel
    ds_dp = ChartDataset(
        dataset_id="DS-DP",
        kind="time_series",
        metric_name="产量与价格双面板",
        unit="混合",
        evidence_ids=ev,
        panels=[
            ChartPanel(panel_id="L", position="left", series=["产量"], axis_name="产量"),
            ChartPanel(panel_id="R", position="right", series=["价格"], axis_name="价格"),
        ],
        points=[
            *[ChartPoint(label=m, value=v, series="产量", period_end=d, evidence_id="E-DEMO-001") for m, v, d in [("1月", 28, date(2023, 1, 31)), ("6月", 60, date(2023, 6, 30)), ("12月", 78, date(2023, 12, 31))]],
            *[ChartPoint(label=m, value=v, series="价格", period_end=d, evidence_id="E-DEMO-003") for m, v, d in [("1月", 48, date(2023, 1, 31)), ("6月", 18, date(2023, 6, 30)), ("12月", 9.4, date(2023, 12, 31))]],
        ],
    )
    out.append(
        (
            "dual_panel",
            _spec("CHART-DEMO-DP", "演示：产量与价格双面板", "combo", "dual_panel", build_dual_panel_option("演示：产量与价格双面板", ds_dp), ev),
        )
    )

    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    index = []
    for kind, spec in build_all():
        option_path = OUT / f"{kind}.option.json"
        svg_path = OUT / f"{kind}.svg"
        option_path.write_text(json.dumps(spec.option, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            svg = render_chart_svg(spec)
            svg_path.write_text(svg, encoding="utf-8")
            svg_ok = True
        except Exception as exc:  # noqa: BLE001
            svg_path.write_text(f"<!-- render failed: {exc} -->", encoding="utf-8")
            svg_ok = False
        index.append(
            {
                "kind": kind,
                "chart_id": spec.chart_id,
                "title": spec.title,
                "chart_type": spec.chart_type,
                "variant": spec.variant,
                "option": str(option_path.name),
                "svg": str(svg_path.name),
                "svg_ok": svg_ok,
            }
        )
        print(f"[ok] {kind:15s} {spec.chart_id}  svg={'Y' if svg_ok else 'N'}  option_bytes={option_path.stat().st_size}")
    (OUT / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n输出目录: {OUT}")
    print(f"图表数: {len(index)}  SVG成功: {sum(1 for i in index if i['svg_ok'])}")


if __name__ == "__main__":
    main()
