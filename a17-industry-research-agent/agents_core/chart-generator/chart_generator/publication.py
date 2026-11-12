"""Verify that the compiled chart still describes its approved data."""
from __future__ import annotations

import math
from typing import Any


def comparison_issue(kind: str, contract: dict[str, Any]) -> str | None:
    """A comparison must have at least two distinct final comparison objects."""
    if kind not in ("bar", "comparison_bar", "horizontal_bar", "diverging_bar"):
        return None
    if contract.get("axis_type") == "time_series":
        return None
    points = contract.get("points") or []
    if points and len({point.get("category") for point in points if point.get("category")}) < 2:
        return "有效比较对象少于两个，单值以表格呈现"
    return None


def option_contract_issue(option: dict[str, Any], contract: dict[str, Any], kind: str) -> str | None:
    """Check every plotted cell, axis and legend before publishing a numeric chart."""
    try:
        categories = contract["categories"]
        names = contract["series_order"]
        units = contract["series_units"]
        points = contract["points"]
        series = option["series"]
        legend = option.get("legend", {}).get("data")
        expected = {(point["series"], point["index"]): point["value"] for point in points}
        if not expected or len(expected) != len(points) or any(
            categories[point["index"]] != point["category"]
            or point["unit"] != units[point["category"] if kind == "radar" else point["series"]]
            for point in points
        ):
            return "数据点与类目或单位契约不一致"

        plotted = {}
        if kind == "radar":
            entries = series[0]["data"]
            if (len(series) != 1 or legend != names or [row["name"] for row in entries] != names
                    or [axis["name"] for axis in option["radar"]["indicator"]] != categories):
                return "雷达维度或图例与证据规格不一致"
            rows = [(row["name"], row["value"]) for row in entries]
        elif kind in ("scatter", "bubble", "pie", "donut"):
            entries = series[0]["data"]
            labels = [row["name"] for row in entries]
            if len(series) != 1 or len(set(labels)) != len(labels):
                return "绘制主体重复或系列结构不合法"
            if kind in ("scatter", "bubble"):
                if len(names) != 2 or any(
                    option[axis]["type"] != "value"
                    or option[axis]["name"] != (f"{name} ({units[name]})" if units[name] else name)
                    for axis, name in zip(("xAxis", "yAxis"), names)
                ):
                    return "散点坐标轴或单位与证据规格不一致"
                for row in entries:
                    for j, name in enumerate(names):
                        plotted[name, categories.index(row["name"])] = row["value"][j]
            else:
                if len(names) != 1 or legend not in (None, labels):
                    return "构成图图例与证据规格不一致"
                plotted = {(names[0], categories.index(row["name"])): row["value"] for row in entries}
            rows = []
        else:
            category_axis, value_axis = ("yAxis", "xAxis") if kind == "horizontal_bar" else ("xAxis", "yAxis")
            if (option[category_axis]["type"] != "category" or option[category_axis]["data"] != categories
                    or [row["name"] for row in series] != names
                    or (legend != names if len(names) > 1 else legend not in (None, names))):
                return "类目轴、系列或图例与证据规格不一致"
            axes = option[value_axis]
            axes = axes if isinstance(axes, list) else [axes]
            rows = []
            for row in series:
                axis = axes[row.get(value_axis + "Index", 0)]
                if axis["type"] != "value" or (axis.get("name") or "") != (units[row["name"]] or ""):
                    return "数值轴或单位与证据规格不一致"
                rows.append((row["name"], row["data"]))

        for name, values in rows:
            if len(values) != len(categories):
                return "系列点数与类目数不一致"
            for index, value in enumerate(values):
                value = value["value"] if isinstance(value, dict) else value
                if value is not None:
                    plotted[name, index] = value

        if plotted != expected or any(
            isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
            for value in plotted.values()
        ):
            return "绘制数值与点级契约不一致"
        if option.get("observation_range") != contract.get("observation_range"):
            return "图表观察期与证据规格不一致"
    except (KeyError, IndexError, TypeError, ValueError, OverflowError):
        return "图表配置缺少可核验的坐标、系列或数据点"
    return None
