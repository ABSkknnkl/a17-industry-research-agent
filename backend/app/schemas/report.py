"""Deterministic report-fusion contracts shared by backend and frontend.

合并说明（2026-09-21 Agent 5 外部实现同步）：
以目标项目为本（保留 `comparison_bar`、100 分质量评分字段、
`FusionChapterOutline`/`outline_version`），吸收外部新增的编辑/分页/复检模型
（`TemplateProfile`、`EditorialPlan`、`PageCompositionPlan`、`ReportBlueprint`、
`VisualReviewReport`、`VisualReviewSummary`、`ReportDecisionBrief` 等）。
新增字段一律可选或带安全默认值，保证旧任务存档仍可反序列化。
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.analysis import (
    DataQualityIssue,
    DimensionCoverage,
    FinancialConsistencyCheck,
)
from app.schemas.chapter import ChapterDraft
from app.schemas.chart import DisplayKind

ReportFormat = Literal["markdown", "html", "pdf"]
ReportArtifactKind = Literal["report_markdown", "report_html", "report_pdf", "artifact_manifest"]
VisualStyle = Literal["data_manual", "analysis_note", "deep_research"]
RequestedVisualStyle = Literal["auto", "data_manual", "analysis_note", "deep_research"]
VisualDensity = Literal["compact", "balanced", "detailed"]
TemplateProfileName = Literal[
    "auto",
    "classic_research",
    "modern_analysis",
    "data_intensive",
    "narrative_flow",
]
CoverStyle = Literal[
    "two_column_dense",
    "two_column_headline",
    "meta_row_dense",
    "headline_wide",
]
ChartPreference = Literal[
    "balanced",
    "prefer_pairs",
    "prefer_hero",
    "prefer_hero_with_text",
]
TableHeaderStyle = Literal["solid", "minimal"]
LayoutPattern = Literal[
    "hero_metric",
    "chart_led",
    "comparison",
    "narrative",
    "table_led",
    "risk_matrix",
]
PageRole = Literal[
    "narrative",
    "chart_page",
    "comparison_page",
    "table_page",
    "risk_matrix",
    "research_coverage",
]
PageGrid = Literal[
    "single_column",
    "single_hero",
    "two_up",
    "hero_plus_two",
    "two_by_two",
    "full_table",
    "risk_matrix",
]
ChartArrangement = Literal[
    "none",
    "single_hero",
    "two_up",
    "hero_plus_two",
    "two_by_two",
]
EditorialSource = Literal["deterministic", "model", "fallback"]
EditorialEmphasis = Literal["balanced", "metric", "comparison", "risk", "evidence"]
HtmlReportMode = Literal["auto", "narrative_led", "chart_led"]
HtmlSectionComposition = Literal[
    "prose_flow",
    "evidence_split",
    "chart_focus",
    "chart_sequence",
    "small_multiples",
    "metric_strip",
    "comparison_board",
    "table_story",
    "diagram_story",
    "risk_register",
]
HtmlReadingOrder = Literal["insight_first", "data_first", "balanced"]
HtmlContentWidth = Literal["prose", "wide", "full"]
EditorialIssueCode = Literal[
    "TITLE_DATA_MISMATCH",
    "DUPLICATE_CONTENT",
    "INSUFFICIENT_EVIDENCE",
    "CHART_NOT_NEEDED",
    "CHART_SEMANTIC_MISMATCH",
    "WEAK_HIERARCHY",
]


class ReportContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReportConclusion(ReportContract):
    claim_id: str = Field(pattern=r"^C-[A-Za-z0-9_-]+$")
    text: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    confidence: Literal["high", "medium", "low"]
    uncertainty: str = Field(min_length=1)


class ExecutiveSummary(ReportContract):
    headline: str = Field(min_length=1)
    conclusions: list[ReportConclusion] = Field(default_factory=list, max_length=8)
    scenarios: list[str] = Field(min_length=3, max_length=3)
    risks: list[str] = Field(min_length=1)
    research_boundaries: list[str] = Field(min_length=1)


class ReportDecisionBrief(ReportContract):
    """User-owned research intent preserved through editing and delivery."""

    focus_questions: list[str] = Field(default_factory=list, max_length=12)
    included_topics: list[str] = Field(default_factory=list, max_length=12)
    excluded_topics: list[str] = Field(default_factory=list, max_length=12)
    focus_companies: list[str] = Field(default_factory=list, max_length=20)
    editorial_instruction: str | None = Field(default=None, min_length=1, max_length=2_500)


class EmbeddedChart(ReportContract):
    chart_id: str = Field(pattern=r"^CHART-[A-Za-z0-9_-]+$")
    title: str = Field(min_length=1, max_length=200)
    chart_type: Literal[
        "line",
        "bar",
        "comparison_bar",
        "pie",
        "radar",
        "industry_chain",
        "combo",
        "area",
        "scatter",
        "bubble",
        "heatmap",
        "boxplot",
        "treemap",
    ]
    display_kind: DisplayKind = "chart"
    evidence_ids: list[str] = Field(min_length=1)
    insight_goal: str | None = Field(default=None, min_length=1, max_length=500)
    quality_issue_ids: list[str] = Field(default_factory=list, max_length=100)
    footnotes: list[str] = Field(default_factory=list, max_length=20)
    placement_section_id: str | None = Field(default=None, pattern=r"^SEC-\d{2}-\d{2}$")
    svg: str = Field(min_length=1)


class ReportQualityAppendix(ReportContract):
    data_quality_issues: list[DataQualityIssue] = Field(default_factory=list, max_length=100)
    financial_consistency_checks: list[FinancialConsistencyCheck] = Field(
        default_factory=list,
        max_length=20,
    )
    dimension_coverage: list[DimensionCoverage] = Field(default_factory=list, max_length=5)
    skipped_chart_notes: list[str] = Field(default_factory=list, max_length=100)


class EvidenceSourceEntry(ReportContract):
    """Chinese presentation entry backed by one or more internal evidence IDs."""

    citation_number: int = Field(ge=1)
    display_label: str = Field(min_length=1, max_length=500)
    material_title: str = Field(min_length=1, max_length=500)
    publishers: list[str] = Field(default_factory=list, max_length=20)
    retrieval_methods: list[str] = Field(default_factory=list, max_length=20)
    metric_names: list[str] = Field(min_length=1, max_length=100)
    available_dates: list[str] = Field(default_factory=list, max_length=100)
    reporting_periods: list[str] = Field(default_factory=list, max_length=100)
    locators: list[str] = Field(default_factory=list, max_length=100)
    source_levels: list[str] = Field(default_factory=list, max_length=5)
    audit_labels: list[str] = Field(default_factory=list, max_length=5)
    scopes: list[str] = Field(default_factory=list, max_length=20)
    # Kept for machine traceability only. Renderers must never expose this field.
    evidence_ids: list[str] = Field(min_length=1, max_length=200)


class ChapterVisualStrategy(ReportContract):
    chart_count: int = Field(default=0, ge=0, le=30)
    table_candidate_count: int = Field(default=0, ge=0, le=21)
    dominant_content: Literal[
        "narrative",
        "time_series",
        "comparison",
        "financial_detail",
        "industry_chain",
        "risk",
        "scenario",
        "summary",
    ]
    layout_pattern: LayoutPattern = "narrative"


class TemplateProfile(ReportContract):
    """Visual preset within the research-report genre."""

    name: Literal[
        "classic_research",
        "modern_analysis",
        "data_intensive",
        "narrative_flow",
    ]
    brand_color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    semantic_red: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    semantic_green: str = Field(default="#1B7F4B", pattern=r"^#[0-9A-Fa-f]{6}$")
    neutral_grey: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    heading_h2_pt: float = Field(ge=14.0, le=18.0)
    heading_h3_pt: float = Field(ge=11.0, le=14.0)
    body_size_pt: float = Field(ge=9.0, le=11.0)
    line_height: float = Field(ge=1.28, le=1.50)
    cover_style: CoverStyle
    chart_preference: ChartPreference
    spacing: Literal["compact", "balanced", "generous"]
    table_header_style: TableHeaderStyle


class VisualDecision(ReportContract):
    recommended_style: VisualStyle
    requested_style: RequestedVisualStyle = "auto"
    effective_style: VisualStyle
    selection_source: Literal[
        "user",
        "agent_recommendation",
        "editorial_model",
        "default",
    ]
    density: VisualDensity = "balanced"
    chart_density: Literal["low", "medium", "high"] = "medium"
    table_priority: Literal["low", "medium", "high"] = "medium"
    recommendation_reasons: list[str] = Field(default_factory=list, max_length=20)
    override_warnings: list[str] = Field(default_factory=list, max_length=20)
    per_chapter_strategy: dict[str, ChapterVisualStrategy] = Field(
        default_factory=dict,
        max_length=7,
    )
    requested_template_profile: TemplateProfileName = "auto"
    template_profile: TemplateProfile | None = None


class EditorialFinding(ReportContract):
    """A model suggestion that is advisory and cannot rewrite report facts."""

    issue_code: EditorialIssueCode
    severity: Literal["major", "minor"]
    chapter_ids: list[str] = Field(default_factory=list, max_length=7)
    section_ids: list[str] = Field(default_factory=list, max_length=21)
    explanation: str = Field(min_length=1, max_length=500)
    recommendation: str = Field(min_length=1, max_length=500)


class ChapterEditorialDecision(ReportContract):
    """Whitelisted component choices for one existing chapter."""

    chapter_id: str = Field(pattern=r"^CH-\d{2}$")
    layout_pattern: LayoutPattern = "narrative"
    emphasis: EditorialEmphasis = "balanced"
    featured_chart_ids: list[str] = Field(default_factory=list, max_length=6)
    featured_paragraph_ids: list[str] = Field(default_factory=list, max_length=6)
    rationale: str = Field(min_length=1, max_length=500)


class SectionEditorialDecision(ReportContract):
    """Fact-safe HTML composition choice for one existing research section."""

    section_id: str = Field(pattern=r"^SEC-\d{2}-\d{2}$")
    composition: HtmlSectionComposition = "prose_flow"
    reading_order: HtmlReadingOrder = "balanced"
    content_width: HtmlContentWidth = "wide"
    featured_chart_ids: list[str] = Field(default_factory=list, max_length=6)
    rationale: str = Field(min_length=1, max_length=500)


class EditorialPlan(ReportContract):
    """Cached, validated decisions from the optional report-editor role."""

    schema_version: Literal["1.0"] = "1.0"
    enabled: bool = False
    source: EditorialSource = "deterministic"
    model_name: str | None = Field(default=None, max_length=200)
    recommended_style: VisualStyle
    recommended_density: VisualDensity = "balanced"
    html_report_mode: HtmlReportMode = "auto"
    html_design_direction: str = Field(
        default="以内容信号决定版式，在专业研究报告边界内保持阅读节奏。",
        min_length=1,
        max_length=500,
    )
    chapter_decisions: list[ChapterEditorialDecision] = Field(
        min_length=1,
        max_length=7,
    )
    section_decisions: list[SectionEditorialDecision] = Field(
        default_factory=list,
        max_length=21,
    )
    findings: list[EditorialFinding] = Field(default_factory=list, max_length=30)
    warnings: list[str] = Field(default_factory=list, max_length=20)
    fingerprint: str = Field(default="", pattern=r"^$|^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_chapter_decisions(self) -> "EditorialPlan":
        chapter_ids = [item.chapter_id for item in self.chapter_decisions]
        if len(chapter_ids) != len(set(chapter_ids)):
            raise ValueError("editorial chapter decisions must be unique")
        section_ids = [item.section_id for item in self.section_decisions]
        if len(section_ids) != len(set(section_ids)):
            raise ValueError("editorial section decisions must be unique")
        return self


class ChapterPageDecision(ReportContract):
    """Deterministic page-composition choice for one existing chapter."""

    chapter_id: str = Field(pattern=r"^CH-\d{2}$")
    page_role: PageRole
    grid: PageGrid
    start_new_page: bool = True
    chart_arrangement: ChartArrangement = "none"
    chart_slots: dict[str, Literal["hero", "half"]] = Field(
        default_factory=dict,
        max_length=30,
    )
    compact_empty_state: bool = False
    rationale: str = Field(min_length=1, max_length=500)


class PageCompositionPlan(ReportContract):
    """Fact-safe bridge between editorial choices and deterministic rendering."""

    schema_version: Literal["1.0"] = "1.0"
    document_profile: Literal["brief_note", "research_report", "data_dashboard"]
    publication_chrome: bool = True
    front_matter_mode: Literal["compact", "standard"] = "standard"
    appendix_mode: Literal["public_compact", "internal_full"] = "public_compact"
    chapter_decisions: list[ChapterPageDecision] = Field(min_length=7, max_length=7)
    condensed_chapter_ids: list[str] = Field(default_factory=list, max_length=7)
    warnings: list[str] = Field(default_factory=list, max_length=20)
    fingerprint: str = Field(default="", pattern=r"^$|^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_chapter_decisions(self) -> "PageCompositionPlan":
        chapter_ids = [item.chapter_id for item in self.chapter_decisions]
        if len(chapter_ids) != len(set(chapter_ids)):
            raise ValueError("page-composition chapter decisions must be unique")
        if not set(self.condensed_chapter_ids).issubset(chapter_ids):
            raise ValueError("condensed chapters must exist in page-composition decisions")
        return self


class ReportBlueprint(ReportContract):
    """Executable hand-off from editorial judgment to deterministic rendering."""

    schema_version: Literal["1.0"] = "1.0"
    report_id: str = Field(pattern=r"^REPORT-[A-Za-z0-9_-]+$")
    renderer_contract: Literal["html-svg-playwright-v1"] = "html-svg-playwright-v1"
    immutable_fact_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    editorial_plan: EditorialPlan
    visual_decision: VisualDecision
    page_composition_plan: PageCompositionPlan
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


class VisualIssue(ReportContract):
    issue_code: str = Field(pattern=r"^[A-Z][A-Z0-9_-]+$")
    severity: Literal["critical", "major", "minor"]
    source: Literal["deterministic", "vision", "panel"]
    page: int | None = Field(default=None, ge=1)
    bbox: tuple[float, float, float, float] | None = None
    description: str = Field(min_length=1, max_length=1_000)
    evidence: str = Field(default="", max_length=1_000)
    fix_action: str = Field(min_length=1, max_length=1_000)
    confidence: float = Field(default=1.0, ge=0, le=1)
    resolved: bool = False


class VisualReviewReport(ReportContract):
    passed: bool
    score: float = Field(ge=0, le=1)
    review_round: int = Field(default=0, ge=0, le=2)
    page_count: int = Field(default=0, ge=0)
    layout_pattern_count: int = Field(default=0, ge=0, le=6)
    reviewer_model: str | None = Field(default=None, max_length=200)
    degraded: bool = False
    issues: list[VisualIssue] = Field(default_factory=list, max_length=1_000)


class VisualReviewSummary(ReportContract):
    passed: bool
    score: float = Field(ge=0, le=1)
    critical_count: int = Field(default=0, ge=0)
    major_count: int = Field(default=0, ge=0)
    minor_count: int = Field(default=0, ge=0)
    review_rounds: int = Field(default=1, ge=1, le=3)
    degraded: bool = False


class ReportViewModel(ReportContract):
    report_id: str = Field(pattern=r"^REPORT-[A-Za-z0-9_-]+$")
    title: str = Field(min_length=1)
    industry_topic: str = Field(min_length=2)
    research_as_of: date
    generated_at: datetime
    tone: Literal["professional", "plain_language"]
    report_depth: Literal["brief", "standard", "deep"] = "standard"
    delivery_status: Literal["ready", "ready_with_limits", "blocked"] = "ready"
    decision_brief: ReportDecisionBrief = Field(default_factory=ReportDecisionBrief)
    executive_summary: ExecutiveSummary
    chapters: list[ChapterDraft] = Field(min_length=7, max_length=7)
    charts: list[EmbeddedChart] = Field(default_factory=list, max_length=30)
    disclaimer: str = Field(min_length=1)
    methodology_note: str = Field(min_length=1)
    release_mode: Literal["formal", "draft_with_warnings"] = "formal"
    unresolved_risks: list[str] = Field(default_factory=list)
    risk_acknowledged_at: datetime | None = None
    quality_appendix: ReportQualityAppendix = Field(default_factory=ReportQualityAppendix)
    evidence_catalog: list[EvidenceSourceEntry] = Field(default_factory=list, max_length=200)
    visual_decision: VisualDecision
    editorial_plan: EditorialPlan | None = None
    # Optional for backwards compatibility with saved report_view.json files.
    # The renderer deterministically derives it when loading a legacy artifact.
    page_composition_plan: PageCompositionPlan | None = None


class SourceRevision(ReportContract):
    stage: Literal["data_interpret", "chart_generate", "chapter_write"]
    revision: int = Field(ge=1)


class ReportArtifactManifestEntry(ReportContract):
    artifact_id: str = Field(min_length=1)
    kind: ReportArtifactKind
    uri: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(ge=1)


class ScoreBreakdownItem(ReportContract):
    """单维度评分明细：dimension 为稳定英文标识，score ≤ max_score == weight。"""

    dimension: str = Field(min_length=1)
    score: int = Field(ge=0)
    weight: int = Field(ge=0)
    max_score: int = Field(ge=0)
    reason: str = Field(default="")


class QualityThresholds(ReportContract):
    """分数档阈值：total_score ≥ good 为优，≥ warn 为警示，其余为差。"""

    good: int = Field(ge=0, le=100)
    warn: int = Field(ge=0, le=100)


class ReportQualityReport(ReportContract):
    passed: bool
    chapter_count: int = Field(ge=0)
    section_count: int = Field(ge=0)
    included_chart_count: int = Field(ge=0, le=30)
    evidence_coverage: float = Field(ge=0, le=1)
    issues: list[str] = Field(default_factory=list)
    # 评分基准（分母）：由后端按大纲下发，前端不再写死 7 / 21
    expected_chapter_count: int = Field(ge=1)
    expected_section_count: int = Field(ge=1)
    # ---- 总分 100 评分模型（2026-09-19 方案）：后端确定性产出，前端只渲染 ----
    total_score: int = Field(default=0, ge=0, le=100)
    score_breakdown: list[ScoreBreakdownItem] = Field(default_factory=list)
    thresholds: QualityThresholds = Field(
        default_factory=lambda: QualityThresholds(good=90, warn=70)
    )


class FusionSectionOutline(ReportContract):
    """轻量小节结构：供前端目录渲染，**不含正文**（paragraphs 体积大）。"""

    section_id: str = Field(pattern=r"^SEC-\d{2}-\d{2}$")
    title: str = Field(min_length=1)


class FusionChapterOutline(ReportContract):
    """轻量章节结构：只暴露 id 与标题，让前端「后端给什么就显示什么」。

    不含 summary / paragraphs / claim_ids —— 前端目录只需要标题，
    带上正文会让 API 响应无谓膨胀（正文已在 HTML/PDF 产物里）。
    """

    chapter_id: str = Field(pattern=r"^CH-\d{2}$")
    title: str = Field(min_length=1)
    sections: list[FusionSectionOutline] = Field(min_length=3, max_length=3)


class ReportFusionResult(ReportContract):
    report_id: str = Field(pattern=r"^REPORT-[A-Za-z0-9_-]+$")
    title: str = Field(min_length=1)
    industry_topic: str = Field(min_length=2)
    research_as_of: date
    generated_at: datetime
    tone: Literal["professional", "plain_language"]
    report_depth: Literal["brief", "standard", "deep"] = "standard"
    delivery_status: Literal["ready", "ready_with_limits", "blocked"] = "ready"
    decision_brief: ReportDecisionBrief = Field(default_factory=ReportDecisionBrief)
    formats: list[ReportFormat] = Field(min_length=1, max_length=3)
    source_revisions: list[SourceRevision] = Field(min_length=3, max_length=3)
    included_chart_ids: list[str] = Field(default_factory=list, max_length=30)
    artifacts: list[ReportArtifactManifestEntry] = Field(min_length=2)
    quality: ReportQualityReport
    release_mode: Literal["formal", "draft_with_warnings"] = "formal"
    formal_eligible: bool = True
    draft_eligible: bool = True
    acknowledged_risks: list[str] = Field(default_factory=list)
    unresolved_risks: list[str] = Field(default_factory=list)
    visual_decision: VisualDecision
    visual_review: VisualReviewSummary | None = None
    editorial_plan: EditorialPlan | None = None
    report_blueprint: ReportBlueprint | None = None
    page_composition_plan: PageCompositionPlan | None = None
    # 动态章节结构：让前端目录「后端给什么就显示什么」。
    # 顺序与 HTML 模板 report.html.j2 的 {% for chapter in report.chapters %} 一致，
    # 前端锚点 chapter-${idx+1} 因此不会串位。
    chapters: list[FusionChapterOutline] = Field(min_length=7, max_length=7)
    # 大纲版本（chapter_writer 的 OUTLINE_VERSION），便于溯源标题命名归属
    outline_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_artifact_formats(self) -> "ReportFusionResult":
        kinds = {artifact.kind for artifact in self.artifacts}
        required = {f"report_{item}" for item in self.formats}
        if not required.issubset(kinds):
            raise ValueError("each requested report format requires a manifest entry")
        if "artifact_manifest" not in kinds:
            raise ValueError("artifact manifest entry is required")
        return self
