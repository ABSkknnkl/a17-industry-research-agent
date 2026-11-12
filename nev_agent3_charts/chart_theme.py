"""智能体3图表实现的统一主题与结构骨架。

所有配色、网格、字号、坐标轴、图例、脚注均对齐项目
``chart-generator/chart_generator/compiler.py`` 的 publication-grade 约定，
保证「命名、样式和结构的一致性」：

* PRIMARY_COLOR / ACCENT_COLOR / PALETTE 与 compiler.py 第 31~38 行逐字一致；
* BASE_GRID 与 compiler.py ``compile()`` 的 base_grid 一致；
* tooltip=axis+crossPointer、legend.top=4、axisLine #94a3b8、
  splitLine dashed #e2e8f0、类目标签 fontSize=12 / lineHeight=16 全部沿用；
* 每个图表统一返回带 ``chart_meta`` 的 ECharts option，
  ``chart_meta`` 承载证据 ID、脚注、口径与字段绑定，供渲染层生成图注。
"""

from __future__ import annotations

from typing import Any

from chart_data import NormalizedChartTable

# ---------------------------------------------------------------------------
# 配色（与 compiler.py 一致）
# ---------------------------------------------------------------------------
PRIMARY_COLOR = "#1B365D"       # CICC Deep Blue
ACCENT_COLOR = "#D52B1E"        # HSBC Brick Red
AMBER_COLOR = "#D97706"         # Resilient Amber / Gold
SECONDARY_COLOR = "#0f766e"     # Deep Teal
NEUTRAL_COLOR = "#64748B"       # Slate Grey
PURPLE_COLOR = "#6941c6"        # Deep Violet
NEGATIVE_COLOR = "#D52B1E"      # Risk / Deficit Red
PALETTE = [PRIMARY_COLOR, ACCENT_COLOR, AMBER_COLOR, SECONDARY_COLOR, NEUTRAL_COLOR, PURPLE_COLOR]

AXIS_LINE_COLOR = "#94a3b8"
SPLIT_LINE_COLOR = "#e2e8f0"
TEXT_COLOR = "#334155"
MUTED_TEXT_COLOR = "#64748B"
FONT_SIZE = 12
LINE_HEIGHT = 16

# ---------------------------------------------------------------------------
# 公共骨架
# ---------------------------------------------------------------------------
BASE_GRID = {"containLabel": True, "left": 50, "right": 32, "top": 38, "bottom": 28}


def category_axis(categories: list[str], *, horizontal: bool = False) -> dict[str, Any]:
    """与 compiler.py ``_category_labels`` 一致的类目标签策略。"""
    return {
        "type": "category",
        "data": categories,
        "axisLine": {"lineStyle": {"color": AXIS_LINE_COLOR}},
        "axisTick": {"show": False},
        "axisLabel": {
            "interval": 0,
            "fontSize": FONT_SIZE,
            "lineHeight": LINE_HEIGHT,
            "color": TEXT_COLOR,
            "hideOverlap": False,
            "width": 120 if horizontal else max(35, 720 / max(len(categories), 1) - 5),
            "overflow": "break",
        },
    }


def value_axis(name: str = "", *, show_split_line: bool = True, **extra: Any) -> dict[str, Any]:
    """数值轴：写明指标与单位（financial-charting 硬规则）。"""
    axis: dict[str, Any] = {
        "type": "value",
        "name": name,
        "nameTextStyle": {"fontSize": FONT_SIZE, "color": MUTED_TEXT_COLOR},
        "axisLine": {"show": True, "lineStyle": {"color": AXIS_LINE_COLOR}},
        "axisLabel": {"fontSize": FONT_SIZE, "color": TEXT_COLOR},
        "splitLine": (
            {"lineStyle": {"type": "dashed", "color": SPLIT_LINE_COLOR}}
            if show_split_line else {"show": False}
        ),
    }
    axis.update(extra)
    return axis


def legend(names: list[str]) -> dict[str, Any]:
    return {
        "data": names,
        "top": 4,
        "textStyle": {"fontSize": FONT_SIZE, "color": TEXT_COLOR},
        "itemWidth": 14,
        "itemHeight": 9,
    }


def tooltip(trigger: str = "axis") -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "trigger": trigger,
        "textStyle": {"fontSize": FONT_SIZE},
        "backgroundColor": "rgba(255,255,255,0.96)",
        "borderColor": SPLIT_LINE_COLOR,
        "borderWidth": 1,
    }
    if trigger == "axis":
        cfg["axisPointer"] = {"type": "cross"}
    return cfg


def series_color(index: int) -> str:
    return PALETTE[index % len(PALETTE)]


def footprint_note(footnotes: list[str]) -> str:
    """脚注压缩为一行，用于图表底部 graphic 兜底（完整脚注由渲染层展示）。"""
    return "  |  ".join(footnotes)


def base_option(
    spec: dict[str, Any],
    table: NormalizedChartTable,
    *,
    x_axis: dict[str, Any] | None = None,
    y_axis: dict[str, Any] | list[dict[str, Any]] | None = None,
    series: list[dict[str, Any]] | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    """所有图表共用的唯一组装入口，保证 option 结构一致。

    ``spec`` 为智能体3大模型推荐清单（chart_plan.json）中的单条记录，
    其 ``chart_type`` 决定本函数被哪个 build 函数调用，二者由注册表强校验。
    """
    option: dict[str, Any] = {
        "backgroundColor": "#FFFFFF",
        "color": PALETTE,
        "title": {
            "text": spec["title"],
            "left": "center",
            "top": 8,
            "textStyle": {"fontSize": 15, "fontWeight": 600, "color": TEXT_COLOR},
        },
        "tooltip": tooltip(),
        "legend": legend(list(table.series_data.keys())),
        "grid": dict(BASE_GRID),
        "xAxis": x_axis or category_axis(table.categories),
        "yAxis": y_axis if y_axis is not None else value_axis(table.unit),
        "series": series or [],
        "chart_meta": {
            "chart_id": spec["chart_id"],
            "chart_type": spec["chart_type"],
            "title": spec["title"],
            "insight_goal": spec.get("insight_goal", ""),
            "recommended_chapter_id": spec.get("recommended_chapter_id", ""),
            "insight_refs": spec.get("insight_refs", []),
            "data_binding": spec.get("data_binding", {}),
            "evidence_ids": list(dict.fromkeys(table.evidence_ids)),
            "unit": table.unit,
            "footnotes": list(table.footnotes),
        },
    }
    option.update(overrides)
    return option


def bar_series(name: str, data: list[float | None], *, color: str, **extra: Any) -> dict[str, Any]:
    s: dict[str, Any] = {
        "name": name,
        "type": "bar",
        "data": data,
        "itemStyle": {"color": color, "borderRadius": [3, 3, 0, 0]},
        "barMaxWidth": 34,
        "connectNulls": False,
    }
    s.update(extra)
    return s


def line_series(name: str, data: list[float | None], *, color: str, **extra: Any) -> dict[str, Any]:
    s: dict[str, Any] = {
        "name": name,
        "type": "line",
        "data": data,
        "connectNulls": False,
        "itemStyle": {"color": color},
        "lineStyle": {"width": 2.5, "color": color},
        "symbol": "circle",
        "symbolSize": 6,
    }
    s.update(extra)
    return s
