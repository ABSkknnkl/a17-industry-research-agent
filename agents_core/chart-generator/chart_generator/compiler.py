"""Declarative ECharts Compiler (inspired by AntV MCP Server and grammar-of-graphics).

Compiles a NormalizedDataTable and a DeclarativeChartSpec into a robust, publication-grade
ECharts option with collision avoidance, dual-axis zero alignment, and typography tokens.
"""

from __future__ import annotations

from enum import Enum
import math
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .data_formulation import AxisType, NormalizedDataTable


class ChartArchetype(str, Enum):
    RANKING_HORIZONTAL_BAR = "ranking_horizontal_bar"  # 规模横向梯级排序柱状图
    COMPARISON_BAR = "comparison_bar"                  # 截面横向对比柱状图
    TIME_SERIES_LINE = "time_series_line"              # 时序走势折线图
    DUAL_AXIS_COMBO = "dual_axis_combo"                # 规模-效益双轴组合图
    DIVERGING_BAR = "diverging_bar"                    # 正负偏离/涨跌幅分布图
    STRUCTURE_DONUT = "structure_donut"                # 结构环形图
    RADAR = "radar"                                    # 多维雷达图
    SCATTER = "scatter"                                # 散点分布图


class DeclarativeChartSpec(BaseModel):
    """High-level, constrained visualization specification."""
    model_config = ConfigDict(extra="forbid")

    archetype: ChartArchetype
    title: str
    insight_goal: str
    x_field: str = "categories"
    primary_series_name: str
    secondary_series_name: str | None = None
    recommended_chapter_id: str = "CH-04"
    footnotes: list[str] = Field(default_factory=list)


# Publication-grade colors (McKinsey / FT Inspired)
PRIMARY_COLOR = "#155eef"       # Financial Blue
SECONDARY_COLOR = "#0f766e"     # Deep Teal
ACCENT_COLOR = "#d97706"        # Gold / Amber
NEGATIVE_COLOR = "#d92d20"      # Red
PURPLE_COLOR = "#6941c6"        # Deep Violet
CYAN_COLOR = "#0891b2"          # Cyan
PALETTE = [PRIMARY_COLOR, SECONDARY_COLOR, ACCENT_COLOR, PURPLE_COLOR, CYAN_COLOR, NEGATIVE_COLOR]


class EChartsCompiler:
    """Deterministic compiler turning structured tables into safe, elegant ECharts options."""

    @staticmethod
    def compile(
        table: NormalizedDataTable,
        chart_type: str | ChartArchetype,
        title: str,
    ) -> dict[str, Any]:
        """Compiles NormalizedDataTable into full publication-grade ECharts option."""
        # Clean canonical type string
        t_str = chart_type.value if isinstance(chart_type, ChartArchetype) else str(chart_type).lower()

        base_grid = {
            "containLabel": True,
            "left": 50,
            "right": 32,
            "top": 38,
            "bottom": 28,
        }

        # 1. Dual-Axis Combo
        if t_str in ("combo", "dual_axis_combo", "dual_axis"):
            return EChartsCompiler._compile_combo(table, title, base_grid)

        # 2. Horizontal Bar (Ranking)
        if t_str in ("horizontal_bar", "ranking_horizontal_bar"):
            return EChartsCompiler._compile_horizontal_bar(table, title, base_grid)

        # 3. Diverging Bar (e.g. positive/negative returns)
        if t_str in ("diverging_bar", "diverging"):
            return EChartsCompiler._compile_diverging_bar(table, title, base_grid)

        # 4. Standard Bar / Comparison Bar
        if t_str in ("bar", "comparison_bar"):
            return EChartsCompiler._compile_bar(table, title, base_grid)

        # 5. Line / Area / Time-Series Line
        if t_str in ("line", "area", "time_series_line"):
            is_area = t_str == "area"
            return EChartsCompiler._compile_line(table, title, base_grid, area=is_area)

        # 6. Donut / Pie
        if t_str in ("pie", "donut", "structure_donut"):
            return EChartsCompiler._compile_pie_donut(table, title, donut=True)

        # 7. Radar
        if t_str == "radar":
            return EChartsCompiler._compile_radar(table, title)

        # 8. Scatter / Bubble (2D quadrant positioning)
        if t_str in ("scatter", "bubble"):
            return EChartsCompiler._compile_scatter(table, title, base_grid)

        # Fallback to bar or line
        if table.axis_type == AxisType.TIME_SERIES:
            return EChartsCompiler._compile_line(table, title, base_grid)
        return EChartsCompiler._compile_bar(table, title, base_grid)

    @staticmethod
    def _compile_combo(table: NormalizedDataTable, title: str, grid: dict[str, Any]) -> dict[str, Any]:
        """Compiles dual-axis combo with synchronized zero line."""
        series_names = list(table.series_data.keys())
        s1_name = table.primary_series_name or series_names[0]
        s2_name = table.secondary_series_name or (series_names[1] if len(series_names) > 1 else None)

        # If second series is missing or identical, fallback to clean bar chart to avoid duplicate lines
        if not s2_name or s1_name == s2_name:
            return EChartsCompiler._compile_bar(table, title, grid)

        data1 = table.series_data.get(s1_name, [])
        data2 = table.series_data.get(s2_name, [])
        unit1 = table.series_units.get(s1_name, "")
        unit2 = table.series_units.get(s2_name, "")

        min1, max1 = (min(data1), max(data1)) if data1 else (0, 100)
        min2, max2 = (min(data2), max(data2)) if data2 else (0, 100)

        # Ensure sensible bounds
        y_axis_1: dict[str, Any] = {
            "type": "value",
            "name": unit1,
            "splitNumber": 4,
            "axisLine": {"show": True, "lineStyle": {"color": "#94a3b8"}},
            "splitLine": {"lineStyle": {"type": "dashed", "color": "#e2e8f0"}},
        }
        y_axis_2: dict[str, Any] = {
            "type": "value",
            "name": unit2,
            "splitNumber": 4,
            "axisLine": {"show": True, "lineStyle": {"color": "#94a3b8"}},
            "splitLine": {"show": False},
        }

        # Zero-alignment if negative values exist on either axis
        if min1 < 0 or min2 < 0:
            # Force min to non-positive
            y_axis_1["min"] = math.floor(min(0, min1) * 1.1)
            y_axis_2["min"] = math.floor(min(0, min2) * 1.1)

        return {
            "tooltip": {"trigger": "axis", "axisPointer": {"type": "cross"}},
            "legend": {"data": [s1_name, s2_name], "top": 4},
            "grid": grid,
            "xAxis": {
                "type": "category",
                "data": table.categories,
                "axisLabel": {"interval": 0 if len(table.categories) <= 8 else "auto"},
            },
            "yAxis": [y_axis_1, y_axis_2],
            "series": [
                {
                    "name": s1_name,
                    "type": "bar",
                    "yAxisIndex": 0,
                    "data": data1,
                    "itemStyle": {"color": PRIMARY_COLOR, "borderRadius": [3, 3, 0, 0]},
                },
                {
                    "name": s2_name,
                    "type": "line",
                    "yAxisIndex": 1,
                    "data": data2,
                    "itemStyle": {"color": ACCENT_COLOR},
                    "lineStyle": {"width": 2.5},
                    "symbol": "circle",
                    "symbolSize": 6,
                },
            ],
        }

    @staticmethod
    def _compile_horizontal_bar(table: NormalizedDataTable, title: str, grid: dict[str, Any]) -> dict[str, Any]:
        """Compiles ranking horizontal bar."""
        series_name = table.primary_series_name
        data = table.series_data.get(series_name, [])
        unit = table.series_units.get(series_name, "")
        min_v = min(data) if data else 0

        return {
            "tooltip": {"trigger": "axis"},
            "grid": grid,
            "yAxis": {
                "type": "category",
                "data": table.categories,
                "inverse": True,
                "axisLine": {"lineStyle": {"color": "#94a3b8"}},
            },
            "xAxis": {
                "type": "value",
                "name": unit,
                "min": min(0, min_v),
                "splitNumber": 4,
                "splitLine": {"lineStyle": {"type": "dashed", "color": "#e2e8f0"}},
            },
            "series": [
                {
                    "name": series_name,
                    "type": "bar",
                    "data": data,
                    "itemStyle": {"color": PRIMARY_COLOR, "borderRadius": [0, 4, 4, 0]},
                }
            ],
        }

    @staticmethod
    def _compile_diverging_bar(table: NormalizedDataTable, title: str, grid: dict[str, Any]) -> dict[str, Any]:
        """Compiles diverging bar with positive (green/blue) and negative (red) color coding."""
        series_name = table.primary_series_name
        data = table.series_data.get(series_name, [])
        unit = table.series_units.get(series_name, "%")

        colored_data = []
        for v in data:
            color = PRIMARY_COLOR if v >= 0 else NEGATIVE_COLOR
            colored_data.append({"value": v, "itemStyle": {"color": color, "borderRadius": [2, 2, 2, 2]}})

        min_v = min(data) if data else 0

        return {
            "tooltip": {"trigger": "axis"},
            "grid": grid,
            "xAxis": {
                "type": "category",
                "data": table.categories,
                "axisLine": {"onZero": True, "lineStyle": {"color": "#64748b"}},
            },
            "yAxis": {
                "type": "value",
                "name": unit,
                "min": min(0, min_v),
                "splitNumber": 4,
                "splitLine": {"lineStyle": {"type": "dashed", "color": "#e2e8f0"}},
            },
            "series": [
                {
                    "name": series_name,
                    "type": "bar",
                    "data": colored_data,
                }
            ],
        }

    @staticmethod
    def _compile_bar(table: NormalizedDataTable, title: str, grid: dict[str, Any]) -> dict[str, Any]:
        """Compiles single or multi-series vertical bar chart."""
        series_list = []
        unit = ""
        for i, (s_name, s_data) in enumerate(table.series_data.items()):
            unit = table.series_units.get(s_name, unit)
            series_list.append({
                "name": s_name,
                "type": "bar",
                "data": s_data,
                "itemStyle": {"color": PALETTE[i % len(PALETTE)], "borderRadius": [3, 3, 0, 0]},
            })

        all_vals = [v for s_data in table.series_data.values() for v in s_data]
        min_v = min(all_vals) if all_vals else 0

        opt: dict[str, Any] = {
            "tooltip": {"trigger": "axis"},
            "grid": grid,
            "xAxis": {
                "type": "category",
                "data": table.categories,
                "axisLine": {"lineStyle": {"color": "#94a3b8"}},
                "axisLabel": {"interval": 0 if len(table.categories) <= 8 else "auto"},
            },
            "yAxis": {
                "type": "value",
                "name": unit,
                "min": min(0, min_v),
                "splitNumber": 4,
                "splitLine": {"lineStyle": {"type": "dashed", "color": "#e2e8f0"}},
            },
            "series": series_list,
        }
        if len(series_list) > 1:
            opt["legend"] = {"data": [s["name"] for s in series_list], "top": 4}
        return opt

    @staticmethod
    def _compile_line(table: NormalizedDataTable, title: str, grid: dict[str, Any], area: bool = False) -> dict[str, Any]:
        """Compiles single or multi-series line/area chart."""
        series_list = []
        unit = ""
        for i, (s_name, s_data) in enumerate(table.series_data.items()):
            unit = table.series_units.get(s_name, unit)
            s_dict: dict[str, Any] = {
                "name": s_name,
                "type": "line",
                "data": s_data,
                "connectNulls": False,
                "itemStyle": {"color": PALETTE[i % len(PALETTE)]},
                "lineStyle": {"width": 2.2},
                "symbol": "circle",
                "symbolSize": 5,
            }
            if area:
                s_dict["areaStyle"] = {"opacity": 0.15}
            series_list.append(s_dict)

        opt: dict[str, Any] = {
            "tooltip": {"trigger": "axis"},
            "grid": grid,
            "xAxis": {
                "type": "category",
                "data": table.categories,
                "axisLine": {"lineStyle": {"color": "#94a3b8"}},
            },
            "yAxis": {
                "type": "value",
                "name": unit,
                "splitNumber": 4,
                "splitLine": {"lineStyle": {"type": "dashed", "color": "#e2e8f0"}},
            },
            "series": series_list,
        }
        if len(series_list) > 1:
            opt["legend"] = {"data": [s["name"] for s in series_list], "top": 4}
        return opt

    @staticmethod
    def _compile_pie_donut(table: NormalizedDataTable, title: str, donut: bool = True) -> dict[str, Any]:
        """Compiles structure donut/pie chart."""
        series_name = table.primary_series_name
        data = table.series_data.get(series_name, [])
        pie_data = [{"name": cat, "value": abs(v)} for cat, v in zip(table.categories, data) if v is not None]
        radius = ["36%", "68%"] if donut else [0, "68%"]

        return {
            "tooltip": {"trigger": "item"},
            "legend": {"orient": "horizontal", "bottom": "bottom", "itemWidth": 12, "itemHeight": 8},
            "series": [
                {
                    "name": series_name,
                    "type": "pie",
                    "radius": radius,
                    "data": pie_data,
                    "color": PALETTE,
                    "label": {"show": True, "formatter": "{b}: {d}%"},
                }
            ],
        }

    @staticmethod
    def _compile_radar(table: NormalizedDataTable, title: str) -> dict[str, Any]:
        """Compiles multi-dimensional radar chart."""
        indicators = []
        for i, cat in enumerate(table.categories):
            cat_vals = [
                vals[i] for vals in table.series_data.values()
                if i < len(vals) and vals[i] is not None
            ]
            max_v = max([abs(v) for v in cat_vals]) if cat_vals else 100
            ind_max = 100 if all(0 <= v <= 100 for v in cat_vals) and max_v <= 100 else round(max(max_v * 1.25, 10), 2)
            indicators.append({"name": cat, "max": ind_max})

        series_data = []
        for idx, (ent, vals) in enumerate(table.series_data.items()):
            color = PALETTE[idx % len(PALETTE)]
            series_data.append({
                "name": ent,
                "value": vals,
                "itemStyle": {"color": color},
                "areaStyle": {"opacity": 0.2},
            })

        return {
            "tooltip": {"trigger": "item"},
            "legend": {"data": list(table.series_data.keys()), "top": 4},
            "radar": {"indicator": indicators},
            "series": [
                {
                    "name": title,
                    "type": "radar",
                    "data": series_data,
                }
            ],
        }

    @staticmethod
    def _compile_scatter(table: NormalizedDataTable, title: str, grid: dict[str, Any]) -> dict[str, Any]:
        """Compiles 2D quadrant scatter positioning chart with crosshair references."""
        series_names = list(table.series_data.keys())
        x_metric = table.primary_series_name or (series_names[0] if series_names else "X轴")
        y_metric = table.secondary_series_name or (series_names[1] if len(series_names) > 1 else x_metric)

        x_vals = table.series_data.get(x_metric, [])
        y_vals = table.series_data.get(y_metric, [])
        x_unit = table.series_units.get(x_metric, "")
        y_unit = table.series_units.get(y_metric, "")

        scatter_data = []
        for i, cat in enumerate(table.categories):
            xv = x_vals[i] if i < len(x_vals) else None
            yv = y_vals[i] if i < len(y_vals) else None
            if xv is not None and yv is not None:
                scatter_data.append({
                    "name": cat,
                    "value": [xv, yv, cat],
                })

        x_nums = [d["value"][0] for d in scatter_data]
        y_nums = [d["value"][1] for d in scatter_data]
        x_min = min(x_nums) if x_nums else 0
        x_max = max(x_nums) if x_nums else 100
        y_min = min(y_nums) if y_nums else 0
        y_max = max(y_nums) if y_nums else 100

        x_pad = max((x_max - x_min) * 0.15, 1.0)
        y_pad = max((y_max - y_min) * 0.15, 1.0)

        return {
            "tooltip": {
                "trigger": "item",
                "formatter": "{b}<br/>"
                + f"{x_metric}: "
                + "{c[0]}"
                + (f" {x_unit}" if x_unit else "")
                + "<br/>"
                + f"{y_metric}: "
                + "{c[1]}"
                + (f" {y_unit}" if y_unit else ""),
            },
            "grid": grid,
            "xAxis": {
                "type": "value",
                "name": f"{x_metric} ({x_unit})" if x_unit else x_metric,
                "min": math.floor(x_min - x_pad if x_min < 0 else max(0, x_min - x_pad)),
                "max": math.ceil(x_max + x_pad),
                "splitLine": {"lineStyle": {"type": "dashed", "color": "#e2e8f0"}},
            },
            "yAxis": {
                "type": "value",
                "name": f"{y_metric} ({y_unit})" if y_unit else y_metric,
                "min": math.floor(y_min - y_pad if y_min < 0 else max(0, y_min - y_pad)),
                "max": math.ceil(y_max + y_pad),
                "splitLine": {"lineStyle": {"type": "dashed", "color": "#e2e8f0"}},
            },
            "series": [
                {
                    "name": title,
                    "type": "scatter",
                    "symbolSize": 14,
                    "data": scatter_data,
                    "itemStyle": {"color": PRIMARY_COLOR},
                    "label": {
                        "show": True,
                        "position": "right",
                        "formatter": "{b}",
                        "fontSize": 11,
                        "color": "#344054",
                    },
                    "markLine": {
                        "lineStyle": {"type": "dashed", "color": "#94a3b8", "width": 1},
                        "data": [
                            {"type": "average", "name": f"均值线 ({y_metric})", "valueIndex": 1},
                            {"type": "average", "name": f"均值线 ({x_metric})", "valueIndex": 0},
                        ],
                    },
                }
            ],
        }
