"""BettaFish-inspired deterministic quality report for chart artifacts."""

import json
import re
from typing import Any

from app.agents.chart_generator.constants import CONTRAST_MIN_RATIO
from app.schemas.chart import (
    ChartDataset,
    ChartQualityReport,
    ChartSpec,
    SuppressedChart,
)
from app.schemas.decision import RiskNotice

# P1-1（2026-09-13 方案）：结论式标题判定——标题需含数值或比较/趋势词。
_CONCLUSIVE_PATTERNS = re.compile(
    r"\d|同比|环比|增|降|涨|跌|领先|承压|攀升|回落|下滑|高增|收窄|扩大|转正|转负"
)

# P1-6：WCAG 相对亮度对比度（对白色报告背景）。
_BACKGROUND_COLOR = "#FFFFFF"


def _hex_to_rgb(color: str) -> tuple[int, int, int] | None:
    text = color.strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        return None
    try:
        return tuple(int(text[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return None


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    def channel(value: int) -> float:
        ratio = value / 255
        return ratio / 12.92 if ratio <= 0.04045 else ((ratio + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(value) for value in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(color_a: str, color_b: str) -> float | None:
    """WCAG 对比度；非法颜色返回 None。"""

    rgb_a = _hex_to_rgb(color_a)
    rgb_b = _hex_to_rgb(color_b)
    if rgb_a is None or rgb_b is None:
        return None
    lum_a = _relative_luminance(rgb_a)
    lum_b = _relative_luminance(rgb_b)
    lighter = max(lum_a, lum_b)
    darker = min(lum_a, lum_b)
    return (lighter + 0.05) / (darker + 0.05)


def validate_option(option: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    try:
        serialized = json.dumps(option, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        return [f"echarts_option_not_json_serializable:{type(exc).__name__}"]
    if "function(" in serialized or "=>" in serialized:
        issues.append("echarts_option_contains_executable_code")
    if not option.get("series"):
        issues.append("echarts_option_has_no_series")
    # P0-2（2026-09-13 方案）：单位缺失/占位符兜底规则——builder 层把
    # 占位单位规范化为图注 [需核实:货币单位]，质检据此报缺。
    if any(
        "[需核实:货币单位]" in str(item) for item in option.get("footnotes", [])
    ):
        issues.append("unit_missing_or_placeholder")
    return issues


def check_title_conclusive(spec: ChartSpec) -> bool:
    """P1-1（2026-09-13 方案）：标题结论化校验（Agent3 校验层）。

    标题含数值或比较/趋势词 → 结论式；纯描述性标题（如"碳酸锂价格趋势"）
    → False，调用方标记 title_not_conclusive。生成侧改进（Agent2 提示词）
    按方案延后，本校验负责兜底标记。
    """

    return bool(_CONCLUSIVE_PATTERNS.search(spec.title))


def check_palette_contrast(option: dict[str, Any]) -> list[str]:
    """P1-6（2026-09-13 方案）：主题配色对白色背景对比度 >= 4.5:1。"""

    issues: list[str] = []
    for color in option.get("color", [])[:8]:
        ratio = contrast_ratio(str(color), _BACKGROUND_COLOR)
        if ratio is not None and ratio < CONTRAST_MIN_RATIO:
            issues.append(f"low_contrast_palette:{color}:{ratio:.2f}")
    return issues


def data_health_check(dataset: ChartDataset) -> list[str]:
    """P3-5（2026-09-13 方案）：数据体检——字段>=2列/行数>=5/缺失<=20%/
    列内类型一致。任一不过即返回 issue 码（service 路由前拦截）。
    """

    points = list(dataset.points)
    if dataset.kind == "industry_chain":
        # 产业链图的数据契约在 nodes/edges，points 为空属正常。
        return []
    if dataset.kind in {"xy", "matrix", "distribution", "hierarchy"}:
        # 散点/矩阵/分布/树图的数据在专用字段（xy_points/matrix_cells/
        # distribution_samples/hierarchy_nodes）；深度校验由 route_chart
        # 的 requirements_not_met 防线承担，体检只做存在性检查。
        field_map = {
            "xy": dataset.xy_points,
            "matrix": dataset.matrix_cells,
            "distribution": dataset.distribution_samples,
            "hierarchy": dataset.hierarchy_nodes,
        }
        return [] if field_map[dataset.kind] else ["data_health_min_fields"]
    issues: list[str] = []
    if len(points) < 5:
        issues.append("data_health_min_rows")
    values = [point.value for point in points]
    numeric = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    # 预测占位点（value=None 且 value_kind=forecast 或 label 以 E 结尾，
    # 如 2026E）是数据特性而非异常缺失，不计入缺失率。
    forecast_placeholders = sum(
        1
        for point in points
        if point.value is None
        and (point.value_kind == "forecast" or str(point.label).upper().endswith("E"))
    )
    missing = len(points) - len(numeric) - forecast_placeholders
    if points and missing / len(points) > 0.2:
        issues.append("data_health_missing_ratio")
    # 字段 >=2 列：label + value 是最低要求（period/series 加分项不计）。
    if not points or not any(point.label for point in points):
        issues.append("data_health_min_fields")
    numeric_types = {type(v) for v in numeric}
    if len(numeric_types) > 1:
        issues.append("data_health_type_consistency")
    return issues


def preflight_checklist(
    specs: list[ChartSpec],
    *,
    recommended_range: tuple[int, int] = (5, 8),
) -> list[str]:
    """P1-7（2026-09-13 方案）：输出前自查清单 5 问。

    1. 3D？2. 颜色>5？3. 标签缺？4. 类型匹配？5. 布局优先级？
    全过返回空列表；任一不过返回对应 issue 码（advisory 级）。
    """

    issues: list[str] = []
    for spec in specs:
        option = spec.option
        serialized = json.dumps(option, ensure_ascii=False, default=str)
        if "bar3D" in serialized or "globe" in serialized:
            issues.append(f"preflight_no_3d:{spec.chart_id}")
        colors = option.get("color", [])
        if len(colors) > 5 and spec.chart_type not in {"pie", "treemap", "heatmap", "radar"}:
            issues.append(f"preflight_color_budget:{spec.chart_id}:{len(colors)}")
        series = option.get("series", [])
        data_length = max(
            (len(item.get("data", [])) for item in series if isinstance(item, dict)),
            default=0,
        )
        if data_length <= 12 and all(
            not item.get("label", {}).get("show")
            for item in series
            if isinstance(item, dict)
        ):
            issues.append(f"preflight_label_missing:{spec.chart_id}")
        if not spec.variant:
            issues.append(f"preflight_type_mismatch:{spec.chart_id}")
    low, high = recommended_range
    if specs and len(specs) < low:
        issues.append(f"preflight_chart_count_low:{len(specs)}")
    if len(specs) > high:
        issues.append(f"preflight_chart_count_high:{len(specs)}")
    return issues


def review_gate_checklist(specs: list[ChartSpec]) -> dict[str, bool]:
    """P1-8（2026-09-13 方案）：质量门三问（专家·图官）。

    - five_second_readable：≤12 点 + 结论式标题
    - axis_not_misleading：截断轴有提示 / 柱图轴含零基线
    - key_point_highlighted：有标注或高亮（缺省视为通过，避免误报）
    """

    if not specs:
        return {
            "five_second_readable": True,
            "axis_not_misleading": True,
            "key_point_highlighted": True,
        }
    readable = all(
        max(
            (
                len(item.get("data", []))
                for item in spec.option.get("series", [])
                if isinstance(item, dict)
            ),
            default=0,
        )
        <= 12
        and check_title_conclusive(spec)
        for spec in specs
    )
    axis_ok = all(
        (
            not any(
                axis.get("scale") is True
                for axis in (
                    spec.option.get("yAxis", [])
                    if isinstance(spec.option.get("yAxis"), list)
                    else [spec.option.get("yAxis", {})]
                )
                if isinstance(axis, dict)
            )
        )
        or any("纵轴未从 0 开始" in str(item) for item in spec.footnotes)
        or any(
            "纵轴未从 0 开始" in str(item)
            for item in spec.option.get("footnotes", [])
        )
        for spec in specs
    )
    highlight_ok = all(
        any(
            key in str(item)
            for item in spec.option.get("series", [])
            for key in ("markLine", "markArea", "markPoint")
        )
        or spec.option.get("footnotes")
        or spec.footnotes
        for spec in specs
    )
    return {
        "five_second_readable": readable,
        "axis_not_misleading": axis_ok,
        "key_point_highlighted": highlight_ok,
    }


def build_quality_report(
    *,
    candidate_count: int,
    specs: list[ChartSpec],
    suppressed: list[SuppressedChart],
    risk_notices: list[RiskNotice] | None = None,
) -> ChartQualityReport:
    """Build quality report with risk-aware classification.

    - hard_blocked issues → quality.passed = False
    - advisory/acknowledgement issues → quality.passed = True but with notices
    """
    issues = [issue for spec in specs for issue in validate_option(spec.option)]
    # P1-1（2026-09-13 方案）：标题结论化校验（soft，不阻断）。
    issues.extend(
        f"title_not_conclusive:{spec.chart_id}" for spec in specs if not check_title_conclusive(spec)
    )
    # P1-6（2026-09-13 方案）：主题配色对比度 >= 4.5:1（soft，不阻断）。
    issues.extend(
        issue for spec in specs for issue in check_palette_contrast(spec.option)
    )
    # P1-7（2026-09-13 方案）：输出前自查清单 5 问（soft，不阻断）。
    issues.extend(preflight_checklist(specs))

    # 只有硬阻断才标记为 failed
    # 软规则（预算/重复/章节密度）不再标记为失败
    hard_blocked = {
        item.reason_code
        for item in (suppressed or [])
        if item.reason_code
        not in {
            "duplicate_chart",
            "duplicate_chart_family",
            "chart_budget_exceeded",
            "p1_chart_budget_exceeded",
            "chapter_chart_budget_exceeded",
            "chart_family_budget_exceeded",
            "chart_downgraded",
            "industry_chain_budget_exceeded",
            "chart_count_over_recommended",
            "chart_chapter_density",
            "chart_family_duplicate",
        }
    }
    if hard_blocked:
        issues.extend(sorted(hard_blocked))

    # A failed individual candidate is advisory once at least one audited chart
    # is renderable. The fact gate lives in Agents 1/2; Agent 3 reports gaps but
    # does not suppress the whole report for a partial visualisation mismatch.
    passed = bool(specs) or candidate_count == 0
    if candidate_count > 0 and not specs and "no_ready_charts" not in issues:
        issues.append("no_ready_charts")
    return ChartQualityReport(
        passed=passed,
        ready_count=len(specs),
        suppressed_count=len(suppressed),
        issues=issues,
        # P1-8（2026-09-13 方案）：质量门三问纳入报告。
        review_checklist=review_gate_checklist(specs),
    )
