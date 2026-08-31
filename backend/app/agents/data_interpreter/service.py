"""Public StageAgent implementation for financial data interpretation."""

from typing import Any, Literal

from pydantic import ValidationError

from app.agents.data_interpreter.anomaly import (
    detect_value_anomalies,
    to_quality_issue,
)
from app.agents.data_interpreter.calculations import calculate_p0_metrics
from app.agents.data_interpreter.graph import (
    AnalysisGraphState,
    build_data_interpreter_graph,
)
from app.agents.data_interpreter.prompt_loader import load_global_equity_analysis_prompt
from app.agents.data_interpreter.reconciliation import reconcile_comparables
from app.agents.data_interpreter.skill_loader import load_supporting_skills
from app.agents.data_interpreter.skill_router import SupportingSkillRouter
from app.integrations.llm.openai_compatible import StructuredOutputError
from app.integrations.llm.protocol import AnalysisModel
from app.schemas.analysis import (
    AnalysisRequest,
    AnalysisResult,
    CalculationIssue,
    DataQualityIssue,
)
from app.schemas.decision import (
    DecisionPackage,
    DecisionStatus,
    RiskDisposition,
    RiskNotice,
    RiskSeverity,
    compute_risk_snapshot_sha256,
)
from app.schemas.evidence import EvidenceItem
from app.schemas.workflow import StageName, StageResult, StageStatus
from app.workflow.stages import StageContext


def _detect_series_anomalies(items: list[EvidenceItem]) -> list[DataQualityIssue]:
    """功能2：按指标+范围聚合数值序列做确定性异常质检。

    只标记偏离（CRITICAL/WARN/INFO），不阻断分析；序列样本不足 3 个
    时跳过（无法建立稳定基线）。INFO 级复用 medium 并以 [INFO] 前缀
    标记，不改 DataQualityIssue 结构体。
    """

    series: dict[tuple[str, str], list[tuple[str, float]]] = {}
    for item in items:
        value = item.value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        key = (item.metric_name, item.scope)
        period = item.period_end.isoformat() if item.period_end else ""
        series.setdefault(key, []).append((period, float(value)))

    issues: list[DataQualityIssue] = []
    seen_ids: set[str] = set()
    for (metric, _scope), points in sorted(series.items()):
        if len(points) < 3:
            continue
        points.sort(key=lambda point: point[0])
        findings = detect_value_anomalies(
            [value for _, value in points],
            metric_name=metric,
            periods=[period for period, _ in points],
        )
        for finding in findings:
            suffix = str(len(seen_ids) + 1).zfill(2)
            issue_id = f"DQ-ANOM-{suffix}"
            while issue_id in seen_ids:
                suffix = str(int(suffix) + 1).zfill(2)
                issue_id = f"DQ-ANOM-{suffix}"
            seen_ids.add(issue_id)
            issues.append(to_quality_issue(finding, issue_id=issue_id))
    return issues


def _partition_evidence(
    request: AnalysisRequest,
) -> tuple[list[EvidenceItem], list[DataQualityIssue]]:
    """Separate admissible evidence from item-level metadata failures.

    Missing period/unit are valid for qualitative news, reports and policy
    evidence. Missing traceability, future availability and E-grade inputs are
    excluded from model input, but one bad item must not block an otherwise
    usable mixed evidence package.
    """

    eligible: list[EvidenceItem] = []
    issues: list[DataQualityIssue] = []
    for item in request.evidence_items:
        reasons: list[str] = []
        issue_type: Literal["missing", "stale", "not_comparable"] = "not_comparable"
        if item.available_at is None:
            reasons.append(f"{item.evidence_id}缺少公告日/可得日")
        elif item.available_at > request.research_as_of:
            reasons.append(f"{item.evidence_id}公告日/可得日晚于研究时点，存在前视偏差")
            issue_type = "stale"
        if item.source_locator is None:
            reasons.append(f"{item.evidence_id}缺少证据定位")
            issue_type = "missing"
        if item.grade.value == "E":
            reasons.append(f"{item.evidence_id}为E级待核验输入，不得直接支持核心结论")
        if not reasons:
            eligible.append(item)
            continue
        issues.append(
            DataQualityIssue(
                issue_id=f"DQ-PREFLIGHT-{item.evidence_id[2:]}",
                issue_type=issue_type,
                metric=item.metric_name,
                description="；".join(reasons),
                impact_level="high" if issue_type in {"missing", "stale"} else "medium",
                evidence_ids=[item.evidence_id],
                suggested_handling=(
                    "该证据已从本轮模型输入和确定性计算中隔离；"
                    "补充元数据或调整研究时点后可重新纳入。"
                ),
            )
        )
    return eligible, issues


_CALCULATION_REQUEST_TERMS: dict[str, tuple[str, ...]] = {
    "cr3": ("cr3", "集中度"),
    "cr5": ("cr5", "集中度"),
    "gross_margin": ("毛利率",),
    "net_margin": ("净利率",),
    "r_and_d_expense_ratio": ("研发费用率", "研发投入占比"),
    "selling_expense_ratio": ("销售费用率",),
    "management_expense_ratio": ("管理费用率",),
    "overseas_revenue_share": ("海外收入占比", "境外营收占比"),
    "revenue_yoy": ("营收同比", "营业收入同比"),
    "net_profit_yoy": ("净利润同比",),
    "dupont_roe": ("杜邦", "roe拆解"),
    "asset_turnover": ("总资产周转",),
    "inventory_turnover": ("存货周转",),
    "inventory_days": ("存货周转天数",),
    "receivables_turnover": ("应收账款周转",),
    "receivables_days": ("应收账款周转天数",),
    "capacity_utilization": ("产能利用率",),
    "production_sales_ratio": ("产销率",),
}

_DIRECT_DISCLOSURE_TERMS: dict[str, tuple[str, ...]] = {
    "gross_margin": ("毛利率",),
    "net_margin": ("净利率", "净利润率"),
    "r_and_d_expense_ratio": ("研发费用率", "研发投入占比"),
    "selling_expense_ratio": ("销售费用率",),
    "management_expense_ratio": ("管理费用率",),
    "overseas_revenue_share": ("海外收入占比", "境外营收占比"),
    "revenue_yoy": ("营收同比", "营业收入同比", "营业收入同比增长率"),
    "net_profit_yoy": ("净利润同比", "净利润同比增长率"),
    "dupont_roe": ("roe", "净资产收益率"),
    "asset_turnover": ("总资产周转率",),
    "inventory_turnover": ("存货周转率",),
    "inventory_days": ("存货周转天数",),
    "receivables_turnover": ("应收账款周转率",),
    "receivables_days": ("应收账款周转天数",),
    "capacity_utilization": ("产能利用率",),
    "production_sales_ratio": ("产销率",),
}


def _has_directly_disclosed_metric(
    evidence_items: list[EvidenceItem],
    issue: CalculationIssue,
) -> bool:
    """Return whether the failed calculation is already disclosed as a fact.

    A missing formula input must not hide a provider-disclosed derived metric.
    The match remains strict on entity and reporting period so a value from a
    different company or year cannot silently satisfy the request.
    """

    terms = _DIRECT_DISCLOSURE_TERMS.get(issue.calculation_type, ())
    if not terms:
        return False
    issue_scope = issue.entity_scope.replace(" ", "").casefold()
    for item in evidence_items:
        metric_name = item.metric_name.replace(" ", "").casefold()
        if item.value is None or not any(term.casefold() in metric_name for term in terms):
            continue
        item_scope = item.scope.replace(" ", "").casefold()
        if issue_scope != item_scope:
            continue
        if issue.period_end is not None and item.period_end != issue.period_end:
            continue
        return True
    return False


def _requested_calculation_gaps(
    request: AnalysisRequest,
    issues: list[CalculationIssue],
    *,
    calculated_types: frozenset[str] | None = None,
) -> list[CalculationIssue]:
    request_text = (
        "".join(
            [
                *request.focus_questions,
                *request.research_brief.included_topics,
            ]
        )
        .replace(" ", "")
        .casefold()
    )
    gaps: list[CalculationIssue] = []
    for issue in issues:
        terms = _CALCULATION_REQUEST_TERMS.get(issue.calculation_type, ())
        if not terms or not any(term.casefold() in request_text for term in terms):
            continue
        if _has_directly_disclosed_metric(request.evidence_items, issue):
            continue
        if issue.missing_inputs or "单位" in issue.reason or "报告期" in issue.reason:
            # Partial coverage: the same calculation already succeeded for
            # other scopes (e.g. gross margin is computable for industrial
            # names while banks disclose no cost-of-sales line at all).
            # A single uncomputable scope must not block the whole request
            # when the user-requested metric has usable results; the gap
            # stays visible in calculation_issues for report disclosure.
            if calculated_types and issue.calculation_type in calculated_types:
                continue
            gaps.append(issue)
    return gaps


class DataInterpreterAgent:
    stage: StageName = StageName.DATA_INTERPRET

    def __init__(self, *, model: AnalysisModel) -> None:
        self._model = model
        self._prompt = load_global_equity_analysis_prompt()
        self._skills = load_supporting_skills()
        self._skill_router = SupportingSkillRouter(self._skills)

    async def run(self, context: StageContext) -> StageResult:
        source_data = context.input_data
        fetch_result = context.previous_results.get(StageName.DATA_FETCH)
        if fetch_result is not None:
            if fetch_result.status not in {StageStatus.COMPLETED, StageStatus.APPROVED}:
                return StageResult(
                    stage=self.stage,
                    status=StageStatus.WAITING_REVIEW,
                    revision=context.revision,
                    data={
                        "collaboration_requests": [
                            {
                                "request_id": "DATA-FETCH-NOT-COMPLETED",
                                "question": "请先完成或审核 Agent 1 的数据获取结果。",
                                "reason": (
                                    f"Agent 1 当前状态为 {fetch_result.status.value}，"
                                    "Agent 2 不得越级使用未完成的数据包。"
                                ),
                                "affected_dimensions": ["all"],
                            }
                        ]
                    },
                    error="data_fetch_not_completed",
                )
            # Agent 1 owns the normalized evidence package. The original API
            # request may contain an empty evidence_items list, so it must not
            # overwrite newly acquired evidence. Agent 2 review edits win only
            # after the workflow revision has advanced beyond Agent 1's result.
            source_data = {**context.input_data, **fetch_result.data}
            if context.revision > fetch_result.revision:
                for field_name in (
                    "focus_questions",
                    "analysis_depth",
                    "risk_preference",
                    "evidence_items",
                    "research_brief",
                    "rejected_claim_ids",
                ):
                    if field_name in context.input_data:
                        source_data[field_name] = context.input_data[field_name]

        # Agent 1 also emits query plans, call traces, source records and chart
        # datasets. Agent 2 consumes only its declared public input contract so
        # acquisition metadata cannot become accidental prompt input.
        request_data = {
            field_name: source_data[field_name]
            for field_name in AnalysisRequest.model_fields
            if field_name in source_data
        }
        if context.review_feedback:
            request_data["review_feedback"] = context.review_feedback
        if context.rejected_claim_ids:
            request_data["rejected_claim_ids"] = context.rejected_claim_ids

        try:
            request = AnalysisRequest.model_validate(request_data)
        except ValidationError as exc:
            return StageResult(
                stage=self.stage,
                status=StageStatus.WAITING_REVIEW,
                revision=context.revision,
                data={
                    "collaboration_requests": [
                        {
                            "request_id": "INPUT-VALIDATION",
                            "question": "请补充或修正数据分析所需输入。",
                            "reason": str(exc),
                            "affected_dimensions": ["all"],
                        }
                    ]
                },
                error="analysis_input_invalid",
            )

        eligible_evidence, preflight_issues = _partition_evidence(request)
        if not eligible_evidence:
            return StageResult(
                stage=self.stage,
                status=StageStatus.WAITING_REVIEW,
                revision=context.revision,
                data={
                    "collaboration_requests": [
                        {
                            "request_id": "EVIDENCE-METADATA",
                            "question": "请补充、复核或确认以下证据元数据。",
                            "reason": "；".join(issue.description for issue in preflight_issues),
                            "affected_dimensions": ["all"],
                        }
                    ]
                },
                evidence_sources=[item.evidence_id for item in request.evidence_items],
                error="evidence_metadata_incomplete",
            )
        request = request.model_copy(update={"evidence_items": eligible_evidence})

        # 功能3：口径统一——不可统一的输入隔离并记录，同值冲突择优；
        # 完全隔离时沿用元数据不全的人工审核路径，部分隔离继续执行。
        reconciled_entries, reconciliation_issues = reconcile_comparables(eligible_evidence)
        admissible_evidence = [entry.evidence for entry in reconciled_entries]
        if not admissible_evidence:
            return StageResult(
                stage=self.stage,
                status=StageStatus.WAITING_REVIEW,
                revision=context.revision,
                data={
                    "collaboration_requests": [
                        {
                            "request_id": "EVIDENCE-RECONCILIATION",
                            "question": "请补充同口径证据或确认换算关系。",
                            "reason": "；".join(
                                issue.description for issue in reconciliation_issues
                            )[:2_000],
                            "affected_dimensions": ["all"],
                        }
                    ]
                },
                evidence_sources=[item.evidence_id for item in request.evidence_items],
                error="evidence_reconciliation_incomplete",
            )
        if len(admissible_evidence) < len(eligible_evidence):
            eligible_evidence = admissible_evidence
            request = request.model_copy(update={"evidence_items": admissible_evidence})

        # 功能2：确定性数值异常质检（≥3 样本才建立基线，只标记不阻断）。
        anomaly_issues = _detect_series_anomalies(eligible_evidence)

        calculated_metrics, calculation_issues = calculate_p0_metrics(
            request.evidence_items
        )
        requested_calculation_gaps = _requested_calculation_gaps(
            request,
            calculation_issues,
            calculated_types=frozenset(
                item.calculation_type for item in calculated_metrics
            ),
        )
        # 用户裁决门（计算缺数）：不再早退拦 LLM——先完成结构化分析，由
        # 用户决定「继续生成（缺口披露）」还是「修改条件重跑」。确认码经
        # 审核门写入 input_data.accepted_risk_codes 后重跑时跳过本门。
        accepted_risk_codes = set(context.input_data.get("accepted_risk_codes", []))
        calc_gap_pending = bool(requested_calculation_gaps) and (
            "CALCULATION-DATA-MISSING" not in accepted_risk_codes
        )

        selected_skills = self._skill_router.route(request)
        graph = build_data_interpreter_graph(
            model=self._model,
            prompt=self._prompt,
            supporting_skills=selected_skills,
        )
        graph_state: AnalysisGraphState = {
            "request": request.model_dump(mode="json"),
            "prepared_evidence_ids": [],
            "calculated_metrics": [],
            "calculation_issues": [],
            "draft": None,
            "audit_feedback": [],
            "revision_count": 0,
            "quality": None,
            "result": None,
        }
        try:
            final_state = await graph.ainvoke(graph_state)
            analysis = AnalysisResult.model_validate(final_state["result"])
            precheck_issues = [
                *preflight_issues,
                *reconciliation_issues,
                *anomaly_issues,
            ]
            if precheck_issues:
                analysis = analysis.model_copy(
                    update={
                        "data_quality_issues": [
                            *analysis.data_quality_issues,
                            *precheck_issues,
                        ][:100]
                    }
                )
        except Exception as exc:
            error_data: dict[str, Any] = {
                "model_name": self._model.model_name,
                "prompt_version": self._prompt.version,
                "error_type": type(exc).__name__,
            }
            if isinstance(exc, StructuredOutputError):
                error_data.update(
                    {
                        "error_code": exc.code.value,
                        "retryable": exc.retryable,
                        "diagnostics": exc.diagnostics,
                    }
                )
            return StageResult(
                stage=self.stage,
                status=StageStatus.FAILED,
                revision=context.revision,
                data=error_data,
                evidence_sources=[item.evidence_id for item in request.evidence_items],
                error="analysis_generation_failed",
            )
        has_blocking_request = any(
            item.blocking or item.severity == "blocking" for item in analysis.collaboration_requests
        )
        quality_acknowledged = "ANALYSIS-QUALITY" in accepted_risk_codes
        if calc_gap_pending:
            # 计算缺数决策门：分析本体已生成（data 前缀即 AnalysisResult 字段），
            # 信封字段（决策包/协作请求）经审核门 accept_with_risks 确认后剥离，
            # 下游仍拿到纯 AnalysisResult 契约。
            risk_code = "CALCULATION-DATA-MISSING"
            risk_notices = [
                RiskNotice(
                    risk_code=risk_code,
                    stage=self.stage.value,
                    severity=RiskSeverity.HIGH,
                    disposition=RiskDisposition.ACKNOWLEDGEMENT_REQUIRED,
                    title="用户指定的计算缺少原始数据",
                    detail=(
                        "以下计算缺少必要数据或可比口径；系统不会补造数值，"
                        "继续生成时报告将保留指标缺口说明。"
                    ),
                    affected_ids=[
                        issue.issue_id for issue in requested_calculation_gaps
                    ],
                    recommendation=(
                        "调整指标、企业或时间范围后重跑，"
                        "或确认接受缺口并继续生成。"
                    ),
                    consequence="若继续，相关派生指标将缺席或降级为待核验说明。",
                    can_override=True,
                )
            ]
            snapshot = compute_risk_snapshot_sha256(
                risk_notices=risk_notices,
                blocking_risk_codes=[],
                acknowledgement_required_codes=[risk_code],
            )
            decision_package = DecisionPackage(
                decision_id=f"DEC-{context.run_id}-INTERP-{context.revision}",
                run_id=context.run_id,
                stage=self.stage.value,
                revision=context.revision,
                risk_notices=risk_notices,
                blocking_risk_codes=[],
                acknowledgement_required_codes=[risk_code],
                decision_status=DecisionStatus.AWAITING_USER,
                risk_snapshot_sha256=snapshot,
            )
            data = analysis.model_dump(mode="json")
            data["blocking_issues"] = []
            data["advisory_issues"] = ["requested_calculation_data_unavailable"]
            data["calculation_issues"] = [
                item.model_dump(mode="json") for item in requested_calculation_gaps
            ]
            data["collaboration_requests"] = [
                {
                    "request_id": "CALCULATION-DATA-MISSING",
                    "question": (
                        "用户指定的计算缺少必要数据或可比口径。"
                        "可继续生成（该指标将标注为缺口），或调整条件后重跑。"
                    ),
                    "reason": "；".join(
                        item.reason for item in requested_calculation_gaps[:10]
                    ),
                    "affected_dimensions": ["finance"],
                }
            ]
            data["allowed_review_actions"] = [
                "revise",
                "regenerate",
                "accept_with_risks",
                "cancel",
            ]
            data["decision_package"] = decision_package.model_dump(mode="json")
            return StageResult(
                stage=self.stage,
                status=StageStatus.WAITING_REVIEW,
                revision=context.revision,
                data=data,
                evidence_sources=[item.evidence_id for item in request.evidence_items],
                error="requested_calculation_data_unavailable",
            )
        if not analysis.quality.passed and not quality_acknowledged:
            # 质量降级决策门：分析质量门未过不再强制返工——用户确认后
            # Agent 4 以条件性写作继续，风险由 Agent 5 汇总披露。
            risk_code = "ANALYSIS-QUALITY"
            quality_reason = "；".join(analysis.quality.issues[:10]) or "质量门未通过"
            risk_notices = [
                RiskNotice(
                    risk_code=risk_code,
                    stage=self.stage.value,
                    severity=RiskSeverity.HIGH,
                    disposition=RiskDisposition.ACKNOWLEDGEMENT_REQUIRED,
                    title="Agent 2分析质量门未通过",
                    detail=(
                        f"结构化分析未通过确定性质量门（{quality_reason[:300]}）。"
                        "继续生成时章节将采用条件性表达并披露该限制。"
                    ),
                    affected_ids=[],
                    recommendation=(
                        "确认接受质量降级后继续生成，或修改条件后重跑分析。"
                    ),
                    consequence="若继续，报告将以受限模式交付并保留质量风险披露。",
                    can_override=True,
                )
            ]
            snapshot = compute_risk_snapshot_sha256(
                risk_notices=risk_notices,
                blocking_risk_codes=[],
                acknowledgement_required_codes=[risk_code],
            )
            decision_package = DecisionPackage(
                decision_id=f"DEC-{context.run_id}-INTERP-{context.revision}",
                run_id=context.run_id,
                stage=self.stage.value,
                revision=context.revision,
                risk_notices=risk_notices,
                blocking_risk_codes=[],
                acknowledgement_required_codes=[risk_code],
                decision_status=DecisionStatus.AWAITING_USER,
                risk_snapshot_sha256=snapshot,
            )
            data = analysis.model_dump(mode="json")
            data["blocking_issues"] = []
            data["advisory_issues"] = ["analysis_quality_degraded"]
            data["collaboration_requests"] = [
                {
                    "request_id": "ANALYSIS-QUALITY",
                    "question": (
                        "Agent 2质量门未通过。可确认风险后继续生成"
                        "（章节将条件性表达并披露限制），或修改条件重跑分析。"
                    ),
                    "reason": quality_reason,
                    "affected_dimensions": ["all"],
                }
            ]
            data["allowed_review_actions"] = [
                "revise",
                "regenerate",
                "accept_with_risks",
                "cancel",
            ]
            data["decision_package"] = decision_package.model_dump(mode="json")
            return StageResult(
                stage=self.stage,
                status=StageStatus.WAITING_REVIEW,
                revision=context.revision,
                data=data,
                evidence_sources=[item.evidence_id for item in request.evidence_items],
            )
        status = (
            StageStatus.COMPLETED
            if (analysis.quality.passed or quality_acknowledged) and not has_blocking_request
            else StageStatus.WAITING_REVIEW
        )
        return StageResult(
            stage=self.stage,
            status=status,
            revision=context.revision,
            data=analysis.model_dump(mode="json"),
            evidence_sources=[item.evidence_id for item in request.evidence_items],
        )
