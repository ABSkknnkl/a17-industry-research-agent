"""智能体3推荐图表的全部 ECharts option 实现代码（主智能体亲自编写）。

约定
----
* 智能体3大模型只负责推荐 ``chart_type``；本模块按推荐清单逐一实现 option。
* ``CHARTS`` 注册表以 ``chart_id`` 为键，每个键对应**一个**图表实现函数；
  ``build_all()`` 会强校验：清单条数 == 实现个数 == 图表种类数，且每个
  ``chart_id`` 声明的 ``chart_type`` 与清单完全一致。
* 所有实现共用 ``chart_theme.base_option()`` 骨架与 ``chart_data`` 取数层，
  保证命名、样式、结构一致；每个 option 均携带 ``chart_meta``（证据、脚注、字段绑定）。
* 数值只来自 A1 dataset.json 的真实记录，不外推、不补缺失值。
"""

from __future__ import annotations

from typing import Any, Callable

import chart_data as cd
import chart_theme as th
from chart_data import NormalizedChartTable

BuildFn = Callable[[dict[str, Any]], dict[str, Any]]

# chart_id -> (实现函数, 该实现声明的 chart_type)
CHARTS: dict[str, tuple[BuildFn, str]] = {}


def register(chart_id: str, chart_type: str):
    """把一个图表实现函数登记到注册表，chart_type 与大模型选型强绑定。"""
    def decorator(fn: BuildFn) -> BuildFn:
        if chart_id in CHARTS:
            raise ValueError(f"重复的 chart_id: {chart_id}")
        CHARTS[chart_id] = (fn, chart_type)
        return fn
    return decorator


def _finalize(spec: dict[str, Any], table: NormalizedChartTable, option: dict[str, Any]) -> dict[str, Any]:
    """所有图表实现返回前的统一收口：证据校验 + 脚注合并。"""
    bad = cd.validate_evidence_ids(table.evidence_ids)
    if bad:
        raise ValueError(f"{spec['chart_id']} 引用了不存在的证据 ID: {bad}")
    meta = option["chart_meta"]
    meta["footnotes"] = list(dict.fromkeys(list(table.footnotes) + list(spec.get("footnotes", []))))
    meta["evidence_ids"] = list(dict.fromkeys(table.evidence_ids))
    return option


def build_all(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """按大模型推荐清单的顺序，逐一生成全部图表的 ECharts option。"""
    specs = plan["charts"]
    ids = [s["chart_id"] for s in specs]
    types = [s["chart_type"] for s in specs]

    if len(ids) != len(set(ids)):
        raise ValueError("清单中存在重复 chart_id")
    if len(types) != len(set(types)):
        raise ValueError("清单要求每种 chart_type 唯一，但出现重复类型")
    if set(ids) != set(CHARTS):
        raise ValueError(
            f"实现个数与清单不一致：清单 {sorted(ids)} / 实现 {sorted(CHARTS)}"
        )

    options: list[dict[str, Any]] = []
    for spec in specs:
        fn, declared_type = CHARTS[spec["chart_id"]]
        if declared_type != spec["chart_type"]:
            raise ValueError(
                f"{spec['chart_id']} 实现类型 {declared_type} 与大模型选型 {spec['chart_type']} 不一致"
            )
        option = fn(spec)
        if option["chart_meta"]["chart_type"] != spec["chart_type"]:
            raise ValueError(f"{spec['chart_id']} chart_meta.chart_type 不一致")
        options.append(option)
    return options


# ---------------------------------------------------------------------------
# 以下 9 个实现与 chart_plan.json 的 9 种选型一一对应，顺序与清单完全一致。
# 每个函数：@register(chart_id, chart_type) → 取数 → base_option → ECharts option。
# ---------------------------------------------------------------------------
@register("C01", "combo")
def build_c01_combo(spec: dict[str, Any]) -> dict[str, Any]:
    """C01 双轴组合图：销量累计规模（左轴柱）＋ 同比增速（右轴线）。"""
    t = cd.annual_sales_wan()
    option = th.base_option(
        spec, t,
        x_axis=th.category_axis(t.categories),
        y_axis=[
            th.value_axis("销量累计值（万辆）"),
            th.value_axis("销量同比（%）", show_split_line=False, min=0, max=100, interval=25),
        ],
        series=[
            th.bar_series(
                "销量累计值", t.series_data["销量累计值"],
                color=th.PRIMARY_COLOR, yAxisIndex=0,
                label={"show": True, "position": "top", "fontSize": 10, "color": th.TEXT_COLOR},
            ),
            th.line_series(
                "销量同比", t.series_data["销量同比"],
                color=th.ACCENT_COLOR, yAxisIndex=1,
                label={"show": True, "position": "top", "fontSize": 10,
                       "formatter": "{c}%", "color": th.ACCENT_COLOR},
            ),
        ],
    )
    return _finalize(spec, t, option)


@register("C02", "line")
def build_c02_line(spec: dict[str, Any]) -> dict[str, Any]:
    """C02 折线图：2025 年国内零售渗透率年内观测序列（含 50% 关口参考线）。"""
    t = cd.penetration_2025()
    option = th.base_option(
        spec, t,
        x_axis=th.category_axis(t.categories),
        y_axis=th.value_axis("国内零售渗透率（%）", min=45, max=65, interval=5),
        series=[th.line_series(
            "国内零售渗透率", t.series_data["国内零售渗透率"],
            color=th.PRIMARY_COLOR,
            smooth=False,
            label={"show": True, "position": "top", "fontSize": 10,
                   "formatter": "{c}%", "color": th.TEXT_COLOR},
            markLine={
                "silent": True, "symbol": "none",
                "lineStyle": {"type": "dashed", "color": th.AMBER_COLOR, "width": 1.5},
                "label": {"formatter": "50% 关口", "color": th.AMBER_COLOR, "fontSize": 10},
                "data": [{"yAxis": 50}],
            },
        )],
    )
    return _finalize(spec, t, option)


@register("C03", "area")
def build_c03_area(spec: dict[str, Any]) -> dict[str, Any]:
    """C03 面积图：2021—2025 出口量年度规模（只用 annual 出口值，不叠加同比）。"""
    src = cd.annual_exports_wan()
    t = NormalizedChartTable(
        categories=src.categories,
        series_data={"出口量": src.series_data["出口量"]},
        series_units={"出口量": "万辆"},
        primary_series_name="出口量",
        evidence_ids=src.evidence_ids,
        unit="万辆",
        footnotes=list(src.footnotes),
        axis_type="time_series",
    )
    option = th.base_option(
        spec, t,
        x_axis=th.category_axis(t.categories),
        y_axis=th.value_axis("出口量（万辆）"),
        series=[th.line_series(
            "出口量", t.series_data["出口量"],
            color=th.PRIMARY_COLOR,
            areaStyle={"color": "rgba(27,54,93,0.18)"},
            label={"show": True, "position": "top", "fontSize": 10, "color": th.TEXT_COLOR},
        )],
    )
    return _finalize(spec, t, option)


@register("C04", "comparison_bar")
def build_c04_comparison_bar(spec: dict[str, Any]) -> dict[str, Any]:
    """C04 对比柱状图：2025 营收规模 vs 归母净利（双系列共享单一金额轴）。"""
    t = cd.comparison_2025(cd.M_REVENUE, "营业收入", cd.M_NET_PROFIT, "归母净利润")
    option = th.base_option(
        spec, t,
        x_axis=th.category_axis(t.categories),
        y_axis=th.value_axis("金额（亿元）"),
        series=[
            th.bar_series("营业收入", t.series_data["营业收入"],
                          color=th.PRIMARY_COLOR, barGap="10%"),
            th.bar_series("归母净利润", t.series_data["归母净利润"],
                          color=th.ACCENT_COLOR),
        ],
    )
    return _finalize(spec, t, option)


@register("C05", "horizontal_bar")
def build_c05_horizontal_bar(spec: dict[str, Any]) -> dict[str, Any]:
    """C05 横向排名条形图：2025 毛利率降序（ECharts y 轴自下而上，故数据升序）。"""
    t = cd.company_metric_cross_section(cd.M_GROSS_MARGIN, series_name="毛利率", scale=1.0)
    vals = t.series_data["毛利率"]
    order = sorted(range(len(vals)), key=lambda i: (vals[i] if vals[i] is not None else -1))
    t.categories = [cd.COMPANIES[i] for i in order]
    t.series_data["毛利率"] = [vals[i] for i in order]
    option = th.base_option(
        spec, t,
        x_axis=th.value_axis("毛利率（%）", min=0, max=35, interval=5),
        y_axis=th.category_axis(t.categories, horizontal=True),
        series=[th.bar_series(
            "毛利率", t.series_data["毛利率"],
            color=th.PRIMARY_COLOR,
            label={"show": True, "position": "right", "fontSize": 11,
                   "formatter": "{c}%", "color": th.TEXT_COLOR},
        )],
    )
    return _finalize(spec, t, option)


@register("C06", "scatter")
def build_c06_scatter(spec: dict[str, Any]) -> dict[str, Any]:
    """C06 四象限散点：毛利率 × 营收同比 + 样本内中位数十字参考线。"""
    t = cd.margin_vs_revenue_yoy_2025()
    points = t.points  # type: ignore[attr-defined]
    data = [
        {"name": p["entity"], "value": [p["x"], p["y"]],
         "itemStyle": {"color": th.series_color(cd.COMPANIES.index(p["entity"]))}}
        for p in points
    ]
    option = th.base_option(
        spec, t,
        x_axis=th.value_axis("毛利率（%）", min=10, max=35, interval=5),
        y_axis=th.value_axis("营收同比（%）", min=0, max=30, interval=5),
        series=[{
            "name": "样本企业",
            "type": "scatter",
            "data": data,
            "symbolSize": 14,
            "label": {"show": True, "position": "top", "formatter": "{b}",
                      "fontSize": 11, "color": th.TEXT_COLOR},
            "markLine": {
                "silent": True, "symbol": "none",
                "lineStyle": {"type": "dashed", "color": th.NEUTRAL_COLOR, "width": 1.5},
                "label": {"fontSize": 10, "color": th.NEUTRAL_COLOR},
                "data": [
                    {"xAxis": t.median_x, "label": {"formatter": "毛利率中位数"}},  # type: ignore[attr-defined]
                    {"yAxis": t.median_y, "label": {"formatter": "营收同比中位数"}},  # type: ignore[attr-defined]
                ],
            },
        }],
        legend=th.legend([p["entity"] for p in points]),
        tooltip={
            "trigger": "item",
            "formatter": "{b}<br/>毛利率 / 营收同比（%）：{c}",
            "textStyle": {"fontSize": th.FONT_SIZE},
            "backgroundColor": "rgba(255,255,255,0.96)",
            "borderColor": th.SPLIT_LINE_COLOR,
            "borderWidth": 1,
        },
    )
    # 散点用 value-value 坐标系，类目轴结构不适用，已在上方显式给定双数值轴
    return _finalize(spec, t, option)


@register("C07", "radar")
def build_c07_radar(spec: dict[str, Any]) -> dict[str, Any]:
    """C07 雷达图：5 维互补指标，样本内 min-max 0—100 标准化。"""
    t = cd.radar_quality_2025()
    option = th.base_option(
        spec, t,
        x_axis=None, y_axis=None, series=[],
    )
    for key in ("xAxis", "yAxis", "grid"):
        option.pop(key, None)
    option["radar"] = {
        "center": ["50%", "54%"],
        "radius": "66%",
        "splitNumber": 4,
        "axisName": {"fontSize": th.FONT_SIZE, "color": th.TEXT_COLOR},
        "splitLine": {"lineStyle": {"color": th.SPLIT_LINE_COLOR}},
        "splitArea": {"areaStyle": {"color": ["#FFFFFF", "#F8FAFC"]}},
        "axisLine": {"lineStyle": {"color": th.SPLIT_LINE_COLOR}},
        "indicator": [{"name": dim, "min": 0, "max": 100} for dim in t.categories],
    }
    option["series"] = [{
        "name": "财务质量五维画像",
        "type": "radar",
        "data": [
            {
                "name": ent,
                "value": t.series_data[ent],
                "lineStyle": {"width": 2, "color": th.series_color(i)},
                "itemStyle": {"color": th.series_color(i)},
                "areaStyle": {"color": th.series_color(i), "opacity": 0.06},
            }
            for i, ent in enumerate(cd.COMPANIES)
        ],
    }]
    option["legend"] = th.legend(list(cd.COMPANIES))
    option["tooltip"] = {"trigger": "item", "textStyle": {"fontSize": th.FONT_SIZE}}
    return _finalize(spec, t, option)


@register("C08", "donut")
def build_c08_donut(spec: dict[str, Any]) -> dict[str, Any]:
    """C08 环形构成图：2025 归母净利价值量分布（可加总广延量，中心标样本合计）。"""
    t = cd.donut_profit_2025()
    vals = t.series_data["归母净利"]
    total = sum(v for v in vals if v is not None)
    pie_data = [
        {"name": ent, "value": vals[i],
         "itemStyle": {"color": th.series_color(i)}}
        for i, ent in enumerate(t.categories)
        if vals[i] is not None and vals[i] > 0
    ]
    detail = "样本归母净利构成（亿元 / %）\n" + "\n".join(
        f"{d['name']}  {d['value']:.2f}  ({d['value'] / total * 100:.1f}%)"
        for d in pie_data
    )
    option = th.base_option(
        spec, t,
        x_axis=None, y_axis=None,
        series=[{
            "name": "归母净利润",
            "type": "pie",
            "radius": ["44%", "68%"],
            "center": ["36%", "54%"],
            "avoidLabelOverlap": True,
            "data": pie_data,
            "label": {"show": True, "formatter": "{b} {d}%",
                      "fontSize": 11, "color": th.TEXT_COLOR},
            "labelLine": {"length": 8, "length2": 8},
        }],
    )
    for key in ("xAxis", "yAxis", "grid"):
        option.pop(key, None)
    option["legend"] = {
        "data": [d["name"] for d in pie_data],
        "orient": "vertical", "right": 8, "top": "middle",
        "textStyle": {"fontSize": th.FONT_SIZE, "color": th.TEXT_COLOR},
    }
    option["graphic"] = [
        {"type": "text", "left": "28%", "top": "48%",
         "style": {"text": f"样本合计\n{total:.2f} 亿元", "textAlign": "center",
                   "fill": th.PRIMARY_COLOR, "fontSize": 13, "fontWeight": 600, "lineHeight": 20}},
        {"type": "text", "left": "68%", "top": "22%",
         "style": {"text": detail, "fill": th.TEXT_COLOR, "fontSize": 11, "lineHeight": 22}},
    ]
    option["tooltip"] = {
        "trigger": "item", "formatter": "{b}<br/>{c} 亿元（{d}%）",
        "textStyle": {"fontSize": th.FONT_SIZE},
    }
    return _finalize(spec, t, option)


@register("C09", "diverging_bar")
def build_c09_diverging_bar(spec: dict[str, Any]) -> dict[str, Any]:
    """C09 正负偏离发散条形图：2026 1—9 月销量当月同比，零轴基线清晰。"""
    t = cd.macro_sales_yoy_2026()
    name = "销量当月同比"
    data = [
        {"value": v,
         "itemStyle": {"color": th.NEGATIVE_COLOR if (v is not None and v < 0) else th.PRIMARY_COLOR}}
        for v in t.series_data[name]
    ]
    option = th.base_option(
        spec, t,
        x_axis=th.category_axis(t.categories),
        y_axis=th.value_axis("销量当月同比（%）", min=-20, max=30, interval=10),
        series=[th.bar_series(
            name, data, color=th.PRIMARY_COLOR,
            label={"show": True, "position": "top", "fontSize": 10,
                   "formatter": "{c}%", "color": th.TEXT_COLOR},
            markLine={
                "silent": True, "symbol": "none",
                "lineStyle": {"type": "solid", "color": th.TEXT_COLOR, "width": 1.5},
                "label": {"formatter": "零轴", "color": th.TEXT_COLOR, "fontSize": 10},
                "data": [{"yAxis": 0}],
            },
        )],
    )
    return _finalize(spec, t, option)
