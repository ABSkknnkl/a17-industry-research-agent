"""Deterministic visual planning for Agent 5.

Agent 4 describes section semantics; Agent 5 recommends a presentation shell.
An explicit user choice overrides that recommendation, while evidence and export
constraints remain enforced elsewhere in the report-fusion stage.

合并说明（2026-09-21 Agent 5 外部实现同步）：
- 保留目标项目的视觉密度口径：样式推荐与 ``chart_density`` 仍取
  ``chart_generator.constants`` 的共享预算区间（low<=4 / medium<=8）。
- 吸收外部的模板配置（``TemplateProfile``）与章级布局模式
  （``LayoutPattern`` / ``_layout_pattern`` / 多样性兜底），
  全部为确定性规则，只影响版式，不触碰图表事实与证据。
"""

from collections import Counter
from collections.abc import Sequence
from typing import Literal, cast

from app.agents.chart_generator.constants import DENSITY_LOW_MAX, DENSITY_MEDIUM_MAX
from app.schemas.chapter import ChapterDraft
from app.schemas.report import (
    ChapterVisualStrategy,
    LayoutPattern,
    RequestedVisualStyle,
    TemplateProfile,
    TemplateProfileName,
    VisualDecision,
    VisualDensity,
    VisualStyle,
)

DominantContent = Literal[
    "narrative",
    "time_series",
    "comparison",
    "financial_detail",
    "industry_chain",
    "risk",
    "scenario",
    "summary",
]

_STYLE_LABELS = {
    "data_manual": "数据手册型",
    "analysis_note": "分析笔记型",
    "deep_research": "深度研究型",
}

_PROFILE_LABELS = {
    "classic_research": "经典研报型",
    "modern_analysis": "现代分析型",
    "data_intensive": "数据密集型",
    "narrative_flow": "叙事流畅型",
}

# CSS-variable-driven profile configs. All share:
#   white background, #000000 body, 10.4pt body size, no chart cards.
# Each differs only in brand color, heading sizes, spacing, and layout preference.
_PROFILE_CONFIGS: dict[str, TemplateProfile] = {
    "classic_research": TemplateProfile(
        name="classic_research",
        brand_color="#0243A4",
        semantic_red="#D33333",
        semantic_green="#1B7F4B",
        neutral_grey="#595959",
        heading_h2_pt=15.9,
        heading_h3_pt=12.5,
        body_size_pt=10.4,
        line_height=1.34,
        cover_style="two_column_dense",
        chart_preference="balanced",
        spacing="balanced",
        table_header_style="solid",
    ),
    "modern_analysis": TemplateProfile(
        name="modern_analysis",
        brand_color="#0A5C5C",
        semantic_red="#C0392B",
        semantic_green="#4C8C2B",
        neutral_grey="#595959",
        heading_h2_pt=16.0,
        heading_h3_pt=12.0,
        body_size_pt=10.4,
        line_height=1.38,
        cover_style="two_column_headline",
        chart_preference="prefer_pairs",
        spacing="generous",
        table_header_style="solid",
    ),
    "data_intensive": TemplateProfile(
        name="data_intensive",
        brand_color="#1B3154",
        semantic_red="#C0392B",
        semantic_green="#1B7F4B",
        neutral_grey="#595959",
        heading_h2_pt=15.5,
        heading_h3_pt=12.0,
        body_size_pt=10.4,
        line_height=1.32,
        cover_style="meta_row_dense",
        chart_preference="prefer_hero",
        spacing="compact",
        table_header_style="solid",
    ),
    "narrative_flow": TemplateProfile(
        name="narrative_flow",
        brand_color="#7A1F3D",
        semantic_red="#C0392B",
        semantic_green="#2F7D4F",
        neutral_grey="#595959",
        heading_h2_pt=16.0,
        heading_h3_pt=13.0,
        body_size_pt=10.4,
        line_height=1.40,
        cover_style="headline_wide",
        chart_preference="prefer_hero_with_text",
        spacing="generous",
        table_header_style="minimal",
    ),
}

_CANONICAL_LAYOUT_FALLBACK: dict[str, LayoutPattern] = {
    "CH-01": "narrative",
    "CH-02": "chart_led",
    "CH-03": "comparison",
    "CH-04": "comparison",
    "CH-05": "table_led",
    "CH-06": "narrative",
    "CH-07": "risk_matrix",
}


def visual_style_label(style: str) -> str:
    return _STYLE_LABELS.get(style, style)


def template_profile_label(profile: str) -> str:
    return _PROFILE_LABELS.get(profile, profile)


def get_profile_config(name: str) -> TemplateProfile:
    """Return the immutable TemplateProfile config for a given profile name."""
    return _PROFILE_CONFIGS[name]


def _recommend_profile(
    *,
    quantitative_ratio: float,
    qualitative_ratio: float,
    table_candidates: int,
    chart_count: int,
    chapter_count: int,
) -> tuple[str, list[str]]:
    """Deterministic template-profile recommendation based on content structure."""
    if quantitative_ratio >= 0.70 and table_candidates >= 3:
        return "data_intensive", [
            f"量化内容占比约{quantitative_ratio:.0%}",
            f"识别到{table_candidates}个表格候选，适合数据密集型编排",
        ]
    if qualitative_ratio >= 0.60 and chart_count <= DENSITY_LOW_MAX:
        return "narrative_flow", [
            f"定性论述占比约{qualitative_ratio:.0%}",
            f"核心图表数量为{chart_count}张，适合叙事型编排",
        ]
    if chapter_count >= 5 and 0.35 <= quantitative_ratio <= 0.65:
        return "modern_analysis", [
            "图表、数据与解释相对均衡",
            f"章节数{chapter_count}，适合现代分析型编排",
        ]
    return "classic_research", [
        "内容结构适配经典研报型",
        "采用默认研报编排以保持稳定阅读节奏",
    ]


def _dominant_content(chapter: ChapterDraft) -> DominantContent:
    counts = Counter(section.visual_semantics.content_type for section in chapter.sections)
    return cast(DominantContent, counts.most_common(1)[0][0])


def _layout_pattern(
    chapter: ChapterDraft,
    *,
    chart_display_kinds: dict[str, str],
    table_candidate_count: int,
) -> LayoutPattern:
    dominant = _dominant_content(chapter)
    chapter_kinds = {
        chart_display_kinds[chart_id]
        for chart_id in chapter.chart_ids
        if chart_id in chart_display_kinds
    }
    if dominant in {"risk", "scenario"} or chapter.chapter_id == "CH-07":
        return "risk_matrix"
    if "metric_card" in chapter_kinds:
        return "hero_metric"
    if chapter_kinds:
        return "chart_led"
    if table_candidate_count:
        return "table_led"
    if dominant == "comparison" or chapter.chapter_id in {"CH-03", "CH-04"}:
        return "comparison"
    return _CANONICAL_LAYOUT_FALLBACK.get(chapter.chapter_id, "narrative")


def plan_visual_decision(
    *,
    chapters: Sequence[ChapterDraft],
    charts: Sequence[object],
    requested_style: RequestedVisualStyle = "auto",
    requested_density: VisualDensity = "balanced",
    requested_template_profile: TemplateProfileName = "auto",
) -> VisualDecision:
    sections = [section for chapter in chapters for section in chapter.sections]
    section_count = max(len(sections), 1)
    table_candidates = sum(1 for section in sections if section.visual_semantics.preferred_table)
    quantitative_ratio = (
        sum(section.visual_semantics.quantitative_density or 0 for section in sections)
        / section_count
    )
    qualitative_ratio = (
        sum(section.visual_semantics.qualitative_density or 0 for section in sections)
        / section_count
    )
    chart_count = len(charts)
    chart_display_kinds = {
        str(getattr(chart, "chart_id", "")): str(getattr(chart, "display_kind", "chart"))
        for chart in charts
    }

    recommended: VisualStyle
    reasons: list[str]
    if table_candidates >= max(4, chart_count * 2) or (
        quantitative_ratio >= 0.70 and table_candidates >= 3
    ):
        recommended = "data_manual"
        reasons = [
            f"量化内容占比约{quantitative_ratio:.0%}",
            f"识别到{table_candidates}个精确表格候选",
        ]
    elif qualitative_ratio >= 0.60 and chart_count <= DENSITY_LOW_MAX:
        recommended = "deep_research"
        reasons = [
            f"定性论述占比约{qualitative_ratio:.0%}",
            f"核心图表数量为{chart_count}张，适合叙事型编排",
        ]
    else:
        recommended = "analysis_note"
        reasons = [
            "图表、精确数据与解释性文字相对均衡",
            "采用默认分析笔记型以保持阅读节奏",
        ]

    if requested_style == "auto":
        effective: VisualStyle = recommended
        source: Literal["user", "agent_recommendation", "default"] = "agent_recommendation"
        warnings: list[str] = []
    else:
        effective = requested_style
        source = "user"
        warnings = (
            []
            if requested_style == recommended
            else [
                f"Agent 5推荐{visual_style_label(recommended)}，"
                f"已按用户选择改用{visual_style_label(requested_style)}"
            ]
        )

    strategies: dict[str, ChapterVisualStrategy] = {}
    for chapter in chapters:
        chapter_chart_count = len(chapter.chart_ids)
        chapter_table_count = sum(
            1 for section in chapter.sections if section.visual_semantics.preferred_table
        )
        strategies[chapter.chapter_id] = ChapterVisualStrategy(
            chart_count=chapter_chart_count,
            table_candidate_count=chapter_table_count,
            dominant_content=_dominant_content(chapter),
            layout_pattern=_layout_pattern(
                chapter,
                chart_display_kinds=chart_display_kinds,
                table_candidate_count=chapter_table_count,
            ),
        )

    # Diversity is part of the layout contract, not a last-minute CSS tweak.
    # Preserve semantic choices unless they would produce three identical
    # chapter compositions in a row, then use the canonical chapter fallback.
    ordered_ids = [chapter.chapter_id for chapter in chapters]
    for index in range(2, len(ordered_ids)):
        current_ids = ordered_ids[index - 2 : index + 1]
        current_patterns = [strategies[item].layout_pattern for item in current_ids]
        if len(set(current_patterns)) == 1:
            chapter_id = ordered_ids[index]
            replacement = _CANONICAL_LAYOUT_FALLBACK.get(chapter_id, "narrative")
            if replacement == current_patterns[-1]:
                replacement = "comparison" if replacement != "comparison" else "narrative"
            strategies[chapter_id].layout_pattern = replacement

    if (
        len(chapters) >= 7
        and len({strategy.layout_pattern for strategy in strategies.values()}) < 3
    ):
        for chapter_id in ordered_ids:
            strategies[chapter_id].layout_pattern = _CANONICAL_LAYOUT_FALLBACK.get(
                chapter_id,
                strategies[chapter_id].layout_pattern,
            )
            if len({item.layout_pattern for item in strategies.values()}) >= 3:
                break

    # 密度沿用共享预算区间（low<=DENSITY_LOW_MAX / medium<=DENSITY_MEDIUM_MAX），
    # 与 chart_generator 的图量预算同一套常量，避免两端口径漂移。
    chart_density: Literal["low", "medium", "high"] = (
        "low"
        if chart_count <= DENSITY_LOW_MAX
        else ("medium" if chart_count <= DENSITY_MEDIUM_MAX else "high")
    )
    table_priority: Literal["low", "medium", "high"] = (
        "high" if table_candidates >= 4 else ("medium" if table_candidates else "low")
    )

    # Template profile selection: deterministic recommendation with user override.
    recommended_profile, profile_reasons = _recommend_profile(
        quantitative_ratio=quantitative_ratio,
        qualitative_ratio=qualitative_ratio,
        table_candidates=table_candidates,
        chart_count=chart_count,
        chapter_count=len(chapters),
    )
    if requested_template_profile == "auto":
        effective_profile_name = recommended_profile
        profile_source: Literal["user", "agent_recommendation", "default"] = (
            "agent_recommendation"
        )
        profile_warnings: list[str] = []
    else:
        effective_profile_name = requested_template_profile
        profile_source = "user"
        profile_warnings = (
            []
            if requested_template_profile == recommended_profile
            else [
                f"Agent 5推荐{template_profile_label(recommended_profile)}，"
                f"已按用户选择改用{template_profile_label(requested_template_profile)}"
            ]
        )
    effective_profile = _PROFILE_CONFIGS[effective_profile_name]

    return VisualDecision(
        recommended_style=recommended,
        requested_style=requested_style,
        effective_style=effective,
        selection_source=source,
        density=requested_density,
        chart_density=chart_density,
        table_priority=table_priority,
        recommendation_reasons=reasons + profile_reasons,
        override_warnings=warnings + profile_warnings,
        per_chapter_strategy=strategies,
        requested_template_profile=requested_template_profile,
        template_profile=effective_profile,
    )
