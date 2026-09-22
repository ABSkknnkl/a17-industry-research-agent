"""Code-level Hard Linters for chart-generator agent.

Enforces:
1. ChartDiversityLinter: Minimum 3 distinct chart types when count >= 4, and bar charts <= 40%.
2. ZeroAxisLinter: Ensures zero axis is preserved and negative values are not clipped.
3. EvidenceGroundingLinter: Ensures 100% of cited evidence IDs exist in the report evidence index.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .metric_guard import DimensionGuard, resolve_metric_meta


@dataclass
class ChartLinterViolation:
    code: str
    message: str
    chart_title: str | None = None
    severity: str = "error"  # "error" | "warning"

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "chart_title": self.chart_title,
            "severity": self.severity,
        }


BAR_TYPES = {"bar", "comparison_bar", "horizontal_bar"}


class ChartSkillLinter:
    """Rigorous hard linter for chart candidates enforcing data-fitness and presentation standards."""

    def __init__(
        self,
        *,
        min_diversity_threshold: int = 4,
        min_unique_types: int = 3,
        max_bar_ratio: float = 0.60,
    ) -> None:
        self.min_diversity_threshold = min_diversity_threshold
        self.min_unique_types = min_unique_types
        self.max_bar_ratio = max_bar_ratio

    def lint(
        self,
        candidates: list[Any],
        evidence_index: dict[str, Any],
    ) -> list[ChartLinterViolation]:
        """Runs all linter rules against candidates and evidence_index."""
        violations: list[ChartLinterViolation] = []

        if not candidates:
            return violations

        # 1. Grounding Linter
        for cand in candidates:
            eids = getattr(cand, "evidence_ids", [])
            title = getattr(cand, "title", "未命名图表")
            if not eids:
                violations.append(ChartLinterViolation(
                    code="missing_evidence_ids",
                    message=f"图表《{title}》缺少 evidence_ids 引用",
                    chart_title=title,
                    severity="error",
                ))
            else:
                invalid_eids = [eid for eid in eids if str(eid) not in evidence_index]
                if invalid_eids:
                    violations.append(ChartLinterViolation(
                        code="hallucinated_evidence",
                        message=f"图表《{title}》引用了不存在的证据ID: {invalid_eids}",
                        chart_title=title,
                        severity="error",
                    ))

        # 2. Zero-Axis Linter (check for negative clipping)
        for cand in candidates:
            title = getattr(cand, "title", "未命名图表")
            option = getattr(cand, "option", {})
            series_list = option.get("series", []) if isinstance(option, dict) else []

            values: list[float] = []
            for s in series_list:
                data = s.get("data", [])
                for d in data:
                    if isinstance(d, (int, float)) and not isinstance(d, bool):
                        values.append(float(d))
                    elif isinstance(d, dict) and "value" in d:
                        v = d["value"]
                        if isinstance(v, (int, float)) and not isinstance(v, bool):
                            values.append(float(v))
                        elif isinstance(v, list) and len(v) >= 2 and isinstance(v[1], (int, float)):
                            values.append(float(v[1]))
                    elif isinstance(d, (list, tuple)) and len(d) >= 2 and isinstance(d[1], (int, float)):
                        values.append(float(d[1]))

            has_negative = any(v < 0 for v in values)
            if has_negative:
                # Check if yAxis explicitly clips negative numbers
                y_axis = option.get("yAxis")
                if isinstance(y_axis, dict):
                    y_min = y_axis.get("min")
                    if y_min is not None and isinstance(y_min, (int, float)) and y_min > 0:
                        violations.append(ChartLinterViolation(
                            code="zero_axis_clipped",
                            message=f"图表《{title}》包含负数但在 yAxis 中设置了 min={y_min} > 0，导致零轴被截断",
                            chart_title=title,
                            severity="error",
                        ))
                elif isinstance(y_axis, list):
                    for idx, y_cfg in enumerate(y_axis):
                        y_min = y_cfg.get("min")
                        if y_min is not None and isinstance(y_min, (int, float)) and y_min > 0:
                            violations.append(ChartLinterViolation(
                                code="zero_axis_clipped",
                                message=f"图表《{title}》第 {idx+1} 个 yAxis 设置了 min={y_min} > 0，导致零轴被截断",
                                chart_title=title,
                                severity="error",
                            ))

        # 3. Data-Fitness Linters
        for cand in candidates:
            title = getattr(cand, "title", "未命名图表")
            ctype = getattr(cand, "chart_type", "")
            option = getattr(cand, "option", {})
            eids = getattr(cand, "evidence_ids", [])
            series_list = option.get("series", []) if isinstance(option, dict) else []

            # 3.1 Boxplot requires sufficient sample size (>= 15 points)
            if ctype == "boxplot":
                point_count = len(eids)
                if point_count < 15:
                    violations.append(ChartLinterViolation(
                        code="boxplot_insufficient_sample",
                        message=f"图表《{title}》使用箱线图但样本仅 {point_count} 个点 (<15)，统计学五数概括无意义。应根据数据特征改用横向条形图或散点图",
                        chart_title=title,
                        severity="error",
                    ))

            # 3.2 Treemap requires sufficient categories (>= 8 items)
            if ctype == "treemap":
                item_count = sum(len(s.get("data", [])) for s in series_list if isinstance(s, dict))
                if item_count < 8:
                    violations.append(ChartLinterViolation(
                        code="treemap_insufficient_items",
                        message=f"图表《{title}》使用矩形树图但仅有 {item_count} 个项 (<8) 且缺乏分级层级，易造成平铺误读。应改用水平条形图或环形图",
                        chart_title=title,
                        severity="error",
                    ))

        # 3.3 Redundant duplicate line and area charting for the identical evidence
        line_area_map: dict[frozenset[str], list[str]] = {}
        for cand in candidates:
            ctype = getattr(cand, "chart_type", "")
            if ctype in ("line", "area"):
                eids_key = frozenset(getattr(cand, "evidence_ids", []))
                if eids_key:
                    line_area_map.setdefault(eids_key, []).append(ctype)
        for eids_key, types in line_area_map.items():
            if "line" in types and "area" in types:
                violations.append(ChartLinterViolation(
                    code="redundant_line_and_area",
                    message="对同一组时序证据重复生成了折线图和面积图，属于冗余生成。应根据指标是否具有累计含义仅保留最适配的一种",
                    severity="error",
                ))
                break

        # 4. Chart Diversity Linter (Data-Fitness first, avoid monoculture)
        n = len(candidates)
        if n >= self.min_diversity_threshold:
            types = {getattr(c, "chart_type", "") for c in candidates}
            if len(types) < self.min_unique_types:
                violations.append(ChartLinterViolation(
                    code="lack_of_chart_diversity",
                    message=(
                        f"全套候选图表类型数不足: 共 {n} 张图表仅包含 {len(types)} 种类型 ({types})，"
                        f"要求至少 {self.min_unique_types} 种不同类型"
                    ),
                    severity="error",
                ))

            bar_count = sum(1 for c in candidates if getattr(c, "chart_type", "") in BAR_TYPES)
            bar_ratio = bar_count / n
            if bar_ratio > self.max_bar_ratio:
                violations.append(ChartLinterViolation(
                    code="bar_chart_ratio_exceeded",
                    message=(
                        f"柱状图占比超标: 柱状/条形图共 {bar_count}/{n} 张 ({bar_ratio:.1%})，"
                        f"超过 {self.max_bar_ratio:.0%} 上限。在数据支持的维度下，应优先挖掘 combo、line、area、pie、radar 等启用表达"
                    ),
                    severity="error",
                ))

        # 5. Category Naming and English Slug Linter
        for cand in candidates:
            title = getattr(cand, "title", "未命名图表")
            option = getattr(cand, "option", {})
            if not isinstance(option, dict):
                continue
            x_axis = option.get("xAxis", {})
            x_data = x_axis.get("data", []) if isinstance(x_axis, dict) else []
            for item in x_data:
                if isinstance(item, str) and item.lower() in ("close_price", "change_pct", "trade_volume", "open_price", "high_price", "low_price"):
                    violations.append(ChartLinterViolation(
                        code="raw_technical_slug_in_axis",
                        message=f"图表《{title}》X轴包含技术英文字段名 '{item}'，应使用标准中文或真实日期",
                        chart_title=title,
                        severity="error",
                    ))
                    break

        # 6. Dimension Homogeneity Linter (strictly forbids mixing incompatible dimensions on single axis)
        for cand in candidates:
            title = getattr(cand, "title", "未命名图表")
            ctype = getattr(cand, "chart_type", "")
            eids = getattr(cand, "evidence_ids", [])
            if ctype not in ("combo", "dual_axis", "dual_axis_combo") and len(eids) >= 2:
                metrics = [evidence_index[eid].metric for eid in eids if str(eid) in evidence_index and hasattr(evidence_index[eid], "metric")]
                if metrics and not DimensionGuard.are_same_dimension(metrics):
                    violations.append(ChartLinterViolation(
                        code="mixed_incompatible_dimensions",
                        message=f"图表《{title}》单轴混入了不同量纲指标({set(metrics)})，造成刻度错乱",
                        chart_title=title,
                        severity="error",
                    ))

        return violations
