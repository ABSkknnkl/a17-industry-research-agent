"""Independent input and output contracts for chart generation."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ChartType = Literal[
    "line", "bar", "comparison_bar", "horizontal_bar", "diverging_bar", "pie", "donut", "radar", "industry_chain",
    "combo", "area", "scatter", "bubble", "heatmap", "boxplot", "treemap",
]


class EvidenceRef(BaseModel):
    model_config = ConfigDict(extra="ignore")
    record_id: str
    domain: str
    entity: str | None = None
    metric: str
    value: Any = None
    unit: str | None = None
    period: date | None = None
    period_start: date | None = None
    period_type: str = "unknown"
    period_provenance: str = "unknown"
    scope: str = "consolidated"
    currency: str = "CNY"
    issues: list[str] = Field(default_factory=list)
    skill_id: str = ""
    trace_id: str = ""
    source_url: str | None = None
    source_locator: str | None = None
    published_at: date | None = None
    document_sha256: str | None = None


class KeyMetric(BaseModel):
    model_config = ConfigDict(extra="ignore")
    metric_id: str
    name: str
    entity: str | None = None
    value: float
    unit: str | None = None
    period: date | None = None
    evidence_record_ids: list[str] = Field(default_factory=list)


class TrendFinding(BaseModel):
    model_config = ConfigDict(extra="ignore")
    trend_id: str
    metric: str
    entity: str | None = None
    direction: str
    strength: str
    period_start: date | None = None
    period_end: date | None = None
    observations: int = 1
    total_change_pct: float | None = None
    evidence_record_ids: list[str] = Field(default_factory=list)


class Insight(BaseModel):
    model_config = ConfigDict(extra="ignore")
    insight_id: str
    title: str
    conclusion: str
    significance: str = ""
    evidence_record_ids: list[str] = Field(default_factory=list)


class ContentSection(BaseModel):
    model_config = ConfigDict(extra="ignore")
    heading: str
    purpose: str = ""
    key_points: list[str] = Field(default_factory=list)
    evidence_record_ids: list[str] = Field(default_factory=list)


class InterpretationReport(BaseModel):
    model_config = ConfigDict(extra="ignore")
    report_id: str
    subject: str
    as_of: date
    status: str
    data_quality_appendix: dict[str, Any] = Field(default_factory=dict)
    # 阶段2 产出的产业链拓扑（老项目 chain_designer 范式：LLM 设计拓扑 + 代码裁判）。
    # 必须显式声明——本模型 extra="ignore"，不声明会被静默丢弃（改契约坑④）。
    industry_chain_topology: dict[str, Any] | None = None
    key_metrics: list[KeyMetric] = Field(default_factory=list)
    trends: list[TrendFinding] = Field(default_factory=list)
    insights: list[Insight] = Field(default_factory=list)
    content_outline: list[ContentSection] = Field(default_factory=list)
    evidence_index: dict[str, EvidenceRef] = Field(default_factory=dict)
    comps_matrix: dict[str, Any] | list[Any] | None = None
    comps_table: dict[str, Any] | None = None
    anomalies: list[dict[str, Any]] = Field(default_factory=list)
    industry_chain_segments: list[dict[str, Any]] = Field(default_factory=list)
    chain_analysis: dict[str, Any] | None = None
    financial_ratios: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ChartPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    max_charts: int | None = Field(default=None, ge=0)
    prefer_combined: bool = False
    requested_types: list[ChartType] = Field(default_factory=list)
    theme: Literal["research_light", "research_dark", "warm"] = "research_light"
    include_advanced: bool = True

    @field_validator("requested_types", mode="before")
    @classmethod
    def normalize_requested_types(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return value
        return ["industry_chain" if isinstance(item, str) and item.strip().casefold() == "chain" else item
                for item in value]


def extract_dataset_industry(dataset: Any) -> str | None:
    """Extracts or infers the primary industry/subject of the dataset."""
    if not dataset:
        return None
    if isinstance(dataset, dict):
        if isinstance(dataset.get("subject"), str) and dataset.get("subject").strip():
            return dataset["subject"].strip()
        if isinstance(dataset.get("industry"), str) and dataset.get("industry").strip():
            return dataset["industry"].strip()
    elif hasattr(dataset, "subject") and isinstance(dataset.subject, str) and dataset.subject.strip():
        return dataset.subject.strip()

    ind_records = getattr(dataset, "industry", None)
    if ind_records is None and isinstance(dataset, dict):
        ind_records = dataset.get("industry", [])
    if isinstance(ind_records, list):
        for r in ind_records:
            metric = getattr(r, "metric", None) if not isinstance(r, dict) else r.get("metric")
            val = getattr(r, "value", None) if not isinstance(r, dict) else r.get("value")
            if metric == "industry_name" and val and isinstance(val, str) and val.strip():
                return val.strip()
            ent = getattr(r, "entity_name", None) if not isinstance(r, dict) else r.get("entity_name")
            if ent and isinstance(ent, str) and ent.strip():
                return ent.strip()

    sources = getattr(dataset, "sources", None)
    if sources is None and isinstance(dataset, dict):
        sources = dataset.get("sources", [])
    if sources and isinstance(sources, list):
        for s in sources:
            q = getattr(s, "query", None) if not isinstance(s, dict) else s.get("query")
            if q and isinstance(q, str):
                tokens = q.strip().split()
                if tokens:
                    first = tokens[0]
                    if len(first) >= 2 and first not in ("查询", "股票", "A股", "行情"):
                        return first

    return None


def validate_request_consistency(dataset: Any, subject: str | None) -> None:
    """Validates that the input dataset's industry aligns with the requested subject."""
    if not dataset or not subject:
        return
    if subject in ("研究主题", "默认主题", ""):
        return
    norm_sub = subject.strip().casefold()

    # 1. 显式主题匹配
    ds_sub = getattr(dataset, "subject", None) or (dataset.get("subject") if isinstance(dataset, dict) else None)
    if ds_sub and isinstance(ds_sub, str) and ds_sub.strip():
        norm_ds = ds_sub.strip().casefold()
        if norm_ds in norm_sub or norm_sub in norm_ds:
            return

    # 2. 溯源检索词中是否包含目标行业主题
    sources = getattr(dataset, "sources", None) or (dataset.get("sources", []) if isinstance(dataset, dict) else [])
    for s in sources:
        q = getattr(s, "query", None) or (s.get("query") if isinstance(s, dict) else None)
        if q and isinstance(q, str):
            q_cf = q.casefold()
            if norm_sub in q_cf or any(token in q_cf for token in norm_sub.split() if len(token) >= 2):
                return

    # 3. 行业与产业链记录匹配
    for dom_key in ("industry", "industry_chain"):
        records = getattr(dataset, dom_key, None) or (dataset.get(dom_key, []) if isinstance(dataset, dict) else [])
        for r in records:
            ent = getattr(r, "entity_name", None) or (r.get("entity_name") if isinstance(r, dict) else None)
            val = getattr(r, "value", None) or (r.get("value") if isinstance(r, dict) else None)
            for item in (ent, val):
                if item and isinstance(item, str):
                    item_cf = item.casefold()
                    if norm_sub in item_cf or item_cf in norm_sub:
                        return

    # 4. 兜底提取推断行业名称，若存在实质行业冲突则拦截
    ds_ind = extract_dataset_industry(dataset)
    if not ds_ind:
        return
    norm_ds = ds_ind.strip().casefold()
    if norm_ds not in norm_sub and norm_sub not in norm_ds:
        raise ValueError(f"输入数据集行业 ({ds_ind}) 与请求分析主题 ({subject}) 不一致！")


class ChartGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report: InterpretationReport
    input_dataset: dict[str, Any] | None = None
    preferences: ChartPreferences = Field(default_factory=ChartPreferences)
    question_ids: list[str] = Field(default_factory=list)
    # A3 用户问题驱动选图（方案 3.1 / 5.5）：后端从执行快照读取模式，
    # 把题面卡以 dict 形式透传，避免与旧 question_ids（行业预设编号）混用。
    question_plan_mode: str = "off"
    question_briefs: list[dict[str, Any]] = Field(default_factory=list)
    # 2026-10-21：用户是否**明确**需要产业链图（见 chart_generator.chain_intent）。
    #   True  → 出产业链图 + 调豆包
    #   False → **不出产业链图**（改出别的图），也不调豆包
    #   None  → 按 user_wants_industry_chain() 自动判定
    # 前端显式开关优先级最高，可 100% 覆盖自动判断。
    want_industry_chain: bool | None = None
    # focus_points 是否为系统默认注入（adapters.py 的默认值含"产业链"，
    # 不该被当成用户意图）。默认 False 即"视为用户自填"。
    focus_points: list[str] = Field(default_factory=list)
    defaulted_focus: bool = False
    # 产业链图口径（2026-10-21）：
    #   "entity"   = 企业专属版：主题点名一家公司，品牌卡恰好 1 家（不补竞品）
    #   "industry" = 行业全景版：主题是一个行业，品牌卡 2-8 家龙头
    #   None       = 按 chart_generator.chain_scope.detect_subject_kind() 自动判定
    # 前端显式开关优先级最高，与 want_industry_chain 同路透传。
    chain_scope: Literal["entity", "industry"] | None = None

    @model_validator(mode="after")
    def validate_dataset_consistency(self) -> "ChartGenerationRequest":
        if self.input_dataset and self.report and self.report.subject:
            validate_request_consistency(self.input_dataset, self.report.subject)
        return self


class ChartSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chart_id: str
    title: str
    chart_type: ChartType
    status: Literal["ready"] = "ready"
    option: dict[str, Any]
    evidence_ids: list[str]
    # 点级证据：与 option 中各数据点对应的 record_id，用于逐点溯源。
    point_evidence_ids: list[str] = Field(default_factory=list)
    data_contract: dict[str, Any] = Field(default_factory=dict)
    insight_goal: str
    recommended_chapter_id: str | None = None
    footnotes: list[str] = Field(default_factory=list)
    svg_uri: str | None = None
    html_uri: str | None = None
    data_fingerprint: str
    figure_number: str | None = None
    subtitle: str | None = None
    source_line: str | None = None
    # AI 产业链生图元数据（render_mode=generated_image 时必填，见前端 ChartSpec 契约）
    # render_mode=svg 时（2026-10-07 新增）：产业链图由确定性模板渲染为 SVG 矢量，
    # 经 inline_svg 下发，前端内联渲染实现浏览器无损缩放（替代 ECharts canvas 位图）。
    render_mode: Literal["echarts", "generated_image", "svg"] = "echarts"
    inline_svg: str | None = None
    image_uri: str | None = None
    image_mime_type: Literal["image/png", "image/webp", "image/jpeg"] | None = None
    generation_prompt: str | None = None
    generation_prompt_model: str | None = None
    generation_image_model: str | None = None
    chain_template: Literal["product_decomposition", "horizontal_flow"] | None = None
    # 产业链结构（ChainGraphSpec 序列化）。render_mode=svg 时必填：
    # 审核门按用户意见修改后据此重建 inline_svg（否则前端会渲染改前的过期图）。
    chain_graph: dict[str, Any] | None = None
    # 补充视图（2026-10-17）：同一份拓扑的「LLM 排 HTML → chromium 截图」版本。
    # 为什么不顶替主图：HTML 版只有卡片与连线文字标签，**画不出连线与箭头**（用户实测
    # "连线的节点不见了"），而产业链图的骨架正是连线。故主图恒为确定性 SVG，
    # HTML 版降为并存的可切换补充视图（信息密度高，适合细读卡片内容）。
    supplement_image_uri: str | None = None
    supplement_html_uri: str | None = None
    supplement_note: str | None = None

    @model_validator(mode="after")
    def require_grounded_chart(self) -> "ChartSpec":
        if not self.evidence_ids and not (
            self.chart_type == "industry_chain"
            and self.chain_graph
            and self.data_contract.get("structure_source") == "a2_reviewed_segments"
        ):
            raise ValueError("图表缺少证据引用")
        return self


class SuppressedChart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    requested_type: ChartType | None = None
    reason_code: str
    reason: str
    evidence_ids: list[str] = Field(default_factory=list)


class DataSupplementDemand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    demand_id: str
    requirement_id: str | None = None
    target_chart_type: ChartType
    target_title: str
    entities: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    domain: str = "financials"
    query_hint: str
    reason: str


class ChartQualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    passed: bool
    ready_count: int
    suppressed_count: int
    requested_count: int | None = None
    issues: list[str] = Field(default_factory=list)


class AppliedSkill(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str
    source: str
    adaptation: str
    status: Literal["applied"] = "applied"


class QuestionBrief(BaseModel):
    """用户题面卡（方案 5.2）：由 focus_questions 确定性生成，题号由系统分配，不由 LLM 生成。

    优先级由关系标签按规则计算；显式禁图与必出图分别标记，避免模型擅自取消用户要求。
    """

    model_config = ConfigDict(extra="forbid")
    question_id: str
    text: str
    relation_tags: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    years: list[int] = Field(default_factory=list)
    period_types: list[str] = Field(default_factory=list)
    scopes: list[str] = Field(default_factory=list)
    requests_chart: bool = False
    chart_forbidden: bool = False
    requested_chart_types: list[str] = Field(default_factory=list)
    priority: Literal["P0", "P1", "P2"] = "P2"
    sub_questions: list[str] = Field(default_factory=list)
    defaulted_focus: bool = False


class CandidateCard(BaseModel):
    """候选图卡（方案 5.2）：由上游证据确定性生成。

    ideal_role 与 feasible_expression 分开保存，数据不足时保留理想角色并登记 gap，
    不静默降级；发给模型的摘要排除数值与证据 ID。
    """

    model_config = ConfigDict(extra="forbid")
    card_id: str
    question_ids: list[str] = Field(default_factory=list)
    sub_requirements: list[str] = Field(default_factory=list)
    chart_type: ChartType
    ideal_role: str = ""
    feasible_expression: str = ""
    gap: str | None = None
    metrics: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    periods: list[str] = Field(default_factory=list)
    scope: str | None = None
    units: list[str] = Field(default_factory=list)
    evidence_complete: bool = False
    candidate_ref: str | None = None
    rank: int = 0


class QuestionPlanItem(BaseModel):
    """单题选图计划：needs_chart / 优先级 / 缺口均由规则与校验结果结算。"""

    model_config = ConfigDict(extra="forbid")
    question_id: str
    needs_chart: bool = True
    primary_card_ids: list[str] = Field(default_factory=list)
    supporting_card_ids: list[str] = Field(default_factory=list)
    rationale: str = ""
    priority: Literal["P0", "P1", "P2"] = "P2"
    uncovered: list[str] = Field(default_factory=list)
    selection_source: Literal["llm", "deterministic_fallback", "not_needed"] = "deterministic_fallback"
    validation_errors: list[str] = Field(default_factory=list)
    fallback_reason: str | None = None
    data_reality: str = ""


class QuestionCoverageItem(BaseModel):
    """最终覆盖（方案 5.3 第 7 步）：以实际发布图为准，不再由 ChartIntent.matches 反推。"""

    model_config = ConfigDict(extra="forbid")
    question_id: str
    status: Literal[
        "published", "partially_published", "not_needed",
        "not_published", "evidence_gap", "capability_gap",
    ]
    chart_ids: list[str] = Field(default_factory=list)
    uncovered: list[str] = Field(default_factory=list)
    reason: str | None = None
    chart_digest: str | None = None


class QuestionChartPlan(BaseModel):
    """A3 选图计划（附加产物）；question_plan 为可选字段，保证旧结果仍可读取。"""

    model_config = ConfigDict(extra="forbid")
    version: int = 1
    mode: Literal["off", "observe", "apply"] = "off"
    questions: list[QuestionPlanItem] = Field(default_factory=list)
    coverage: list[QuestionCoverageItem] = Field(default_factory=list)
    capability_gaps: list[str] = Field(default_factory=list)


class ChartGenerationResult(BaseModel):
    chain_quality: dict[str, Any] | None = None
    model_config = ConfigDict(extra="forbid")
    run_id: str
    source_report_id: str
    subject: str
    as_of: date
    status: Literal["completed", "partial", "failed"]
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    applied_skills: list[AppliedSkill] = Field(default_factory=list)
    charts: list[ChartSpec] = Field(default_factory=list)
    suppressed_charts: list[SuppressedChart] = Field(default_factory=list)
    data_demands: list[DataSupplementDemand] = Field(default_factory=list)
    question_coverage: list[dict[str, Any]] = Field(default_factory=list)
    report_tables: list[dict[str, Any]] = Field(default_factory=list)
    quality: ChartQualityReport
    warnings: list[str] = Field(default_factory=list)
    upstream_warnings: list[str] = Field(default_factory=list)
    artifact_dir: str | None = None
    # 附加产物：off / 旧产物不带该字段，A5 不消费（方案 4.3 契约隔离）。
    question_plan: QuestionChartPlan | None = None

    @model_validator(mode="after")
    def unique_chart_ids(self) -> "ChartGenerationResult":
        ids = [item.chart_id for item in self.charts]
        if len(ids) != len(set(ids)):
            raise ValueError("chart ids must be unique")
        return self
