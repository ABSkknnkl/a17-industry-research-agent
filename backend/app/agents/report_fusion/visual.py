"""Deterministic visual planning for Agent 5.

Agent 4 describes section semantics; Agent 5 recommends a presentation shell.
An explicit user choice overrides that recommendation, while evidence and export
constraints remain enforced elsewhere in the report-fusion stage.
"""

from collections import Counter
from collections.abc import Sequence

from app.schemas.chapter import ChapterDraft
from app.schemas.report import (
    ChapterVisualStrategy,
    RequestedVisualStyle,
    VisualDecision,
    VisualDensity,
)


_STYLE_LABELS = {
    "data_manual": "数据手册型",
    "analysis_note": "分析笔记型",
    "deep_research": "深度研究型",
}


def visual_style_label(style: str) -> str:
    return _STYLE_LABELS.get(style, style)


def _dominant_content(chapter: ChapterDraft) -> str:
    counts = Counter(
        section.visual_semantics.content_type for section in chapter.sections
    )
    return counts.most_common(1)[0][0]


def plan_visual_decision(
    *,
    chapters: Sequence[ChapterDraft],
    charts: Sequence[object],
    requested_style: RequestedVisualStyle = "auto",
    requested_density: VisualDensity = "balanced",
) -> VisualDecision:
    sections = [section for chapter in chapters for section in chapter.sections]
    section_count = max(len(sections), 1)
    table_candidates = sum(
        1 for section in sections if section.visual_semantics.preferred_table
    )
    quantitative_ratio = sum(
        section.visual_semantics.quantitative_density or 0 for section in sections
    ) / section_count
    qualitative_ratio = sum(
        section.visual_semantics.qualitative_density or 0 for section in sections
    ) / section_count
    chart_count = len(charts)

    reasons: list[str]
    if table_candidates >= max(4, chart_count * 2) or (
        quantitative_ratio >= 0.70 and table_candidates >= 3
    ):
        recommended = "data_manual"
        reasons = [
            f"量化内容占比约{quantitative_ratio:.0%}",
            f"识别到{table_candidates}个精确表格候选",
        ]
    elif qualitative_ratio >= 0.60 and chart_count <= 4:
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
        effective = recommended
        source = "agent_recommendation"
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
        )

    chart_density = "low" if chart_count <= 4 else ("medium" if chart_count <= 10 else "high")
    table_priority = "high" if table_candidates >= 4 else (
        "medium" if table_candidates else "low"
    )
    return VisualDecision(
        recommended_style=recommended,
        requested_style=requested_style,
        effective_style=effective,
        selection_source=source,
        density=requested_density,
        chart_density=chart_density,
        table_priority=table_priority,
        recommendation_reasons=reasons,
        override_warnings=warnings,
        per_chapter_strategy=strategies,
    )
