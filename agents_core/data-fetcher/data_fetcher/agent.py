"""Research agent control plane: understand, observe, plan, execute, and stop."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
import json
from pathlib import Path
import secrets
from time import monotonic
from typing import Any

from pydantic import ValidationError

from data_fetcher.config import Settings
from data_fetcher.fusion import DataFusion
from data_fetcher.llm import LLMConfigurationError, OpenAICompatibleLLM, PlannerLLM
from data_fetcher.models import (
    AgentDecision,
    Coverage,
    Domain,
    RequirementCoverage,
    ResearchObjective,
    ResearchRecord,
    ResearchRequirement,
    ResearchRequest,
    ResearchRunResult,
    RunError,
    SkillResult,
    SkillTask,
    TraceEvent,
)
from data_fetcher.skillhub import IwencaiAuthenticationError, REMOTE_SKILL_DOMAINS, SkillHub, SkillValidationError


EventEmitter = Callable[[dict[str, Any]], Awaitable[None]]

INTENT_SYSTEM_PROMPT = """你是数据获取智能体的需求理解模块。
你只能整理用户给出的行业、关注点和数据要求，不得提供或猜测任何行业事实、公司、数值或结论。
观察中可能提供 planning_methodologies；它们只能帮助拆解客观数据字段，不能作为事实来源，也不能改变系统架构。
返回 JSON 对象，字段仅限 industry、focus_points、data_requirements、required_domains。
required_domains 只能从 industry、companies、financials、macro、industry_chain、reports、news 中选择。
为建立完整客观研究底座，默认保留全部七个领域。"""

PLANNER_SYSTEM_PROMPT = """你是数据获取智能体的任务规划模块。
你只能选择给定 Skill 并生成查询任务，绝对不能在输出中写入金融事实、数值或研究结论。
planning_methodologies 只用于补全查询维度；它们不是可执行 Skill，禁止写入 task.skill_name。
返回 JSON：decision(continue|stop|blocked)、assessment、tasks。
每个 task 只能包含 task_id、skill_name、arguments、depends_on、purpose、requirement_ids、expected_fields；arguments 必须包含 query，在板块或选股类查询中 arguments 可包含 limit（如 20 或 30）。
任务必须优先服务 observation.requirement_coverage 中未通过的要求，并填写对应 requirement_ids。
任务依赖必须显式列出。只有观察中已识别公司时才可规划财务类 Skill。
【核心选股与龙头识别规范】：
1. 规划公司筛选或龙头识别类任务（hithink-astock-selector 或 hithink-basicinfo-query）时，必须构建具备行业代表性的分层样本库：
   - query 必须显式包含按总市值从大到小排序，覆盖样本量取前 20~30 家行业龙头企业（例如：“按A股总市值从大到小排序取前25~30家核心龙头企业”）；
   - 优先选取主板、创业板与科创板中大市值核心标的（可增加“总市值大于30亿元或50亿元”约束），避免样本结构严重偏向北交所微盘股或壳股；
   - expected_fields 必须包含：“证券代码”、“证券简称”、“总市值”、“营业收入”、“所属行业”、“所属概念”；
   - 若行业存在具有战略影响力的非上市/一级市场代表企业（如商业航天之蓝箭航天、中科宇航、天兵科技；人形机器人之宇树科技、智元机器人等），必须在研报或行业事件检索任务（report-search, news-search）中显式规划对其商业化进展、订单发射与最新融资的针对性查询。
【核心时序与财务三表深度规范】：
1. 规划财务类（hithink-finance-query）任务时，query 必须包含多年度连续时序（例如“近3~5年及最新报告期”或“2021年至2025年”），严禁只查单一报告期，以确保下游能计算多期复合增速（CAGR）和连续年度趋势；同行横向对比时必须统一约束基准报告期（例如统一以近三年或最新完整财年为锚点），严禁不同标的出现跨度数年的基准错配；
2. 财务查询必须完整覆盖资产负债表、利润表、现金流量表三表核心指标：营业收入、归母净利润、销售毛利率、销售净利率、ROE、资产负债率、经营活动产生的现金流量净额、研发费用及其同比增速；
3. 当目标包含“龙头”时，必须从 identified_companies 中具有 selection_basis 的高排名候选规划财务查询，支持对核心纯度高的一揽子标的进行同行横截面对比；
【核心宏观与行业周期规范】：
1. 规划宏观类（hithink-macro-query）任务时，query 必须指定明确的多期时间跨度（如“近3~5年GDP及工业增加值季度趋势”、“近3年社会融资规模存量月度数据”），确保抓取的数据带有明确报告期（period_end），严禁抓取无时间维度的静态孤立点；
2. 对 failed_skill_calls 中仍未满足的要求，应拆分查询或换用同领域 Skill 补救；
3. 优先并行补足缺失要求，禁止重复已执行的同一 Skill 与查询。"""


class DataFetcherAgent:
    def __init__(
        self,
        *,
        llm: PlannerLLM | None = None,
        skillhub: SkillHub | None = None,
        fusion: DataFusion | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or Settings.from_env()
        self.llm = llm or OpenAICompatibleLLM(self.settings)
        self.skillhub = skillhub or SkillHub()
        self.fusion = fusion or DataFusion()

    async def run(
        self,
        request: ResearchRequest,
        emit: EventEmitter | None = None,
        save_artifacts: bool = True,
    ) -> ResearchRunResult:
        run_id = f"run-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4)}"
        trace: list[TraceEvent] = []
        errors: list[RunError] = []
        all_results: list[SkillResult] = []
        successful_task_ids: set[str] = set()
        used_task_ids: set[str] = set()
        completed_signatures: set[str] = set()
        no_progress = 0
        deadline = monotonic() + request.max_execution_seconds
        artifact_dir = self.settings.output_dir / "runs" / run_id if save_artifacts else None

        async def record_event(
            event: str,
            *,
            iteration: int | None = None,
            task_id: str | None = None,
            **details: Any,
        ) -> None:
            item = TraceEvent(event=event, iteration=iteration, task_id=task_id, details=details)
            trace.append(item)
            if emit:
                try:
                    await emit(item.model_dump(mode="json"))
                except Exception:
                    pass

        if not self.llm.is_available:
            message = "Agent planning requires a configured LLM; no rule fallback is enabled."
            errors.append(RunError(stage="configuration", message=message))
            result = self._result(
                run_id, "failed", "llm_unconfigured", request, all_results, trace, errors, artifact_dir
            )
            self._save_artifacts(artifact_dir, request, all_results, result)
            return result

        await record_event("agent_started", industry=request.industry, as_of=request.as_of.isoformat())
        try:
            objective = await self._understand(request)
        except Exception as exc:
            errors.append(RunError(stage="intent", message=str(exc)))
            await record_event("agent_failed", reason="invalid_intent", error=str(exc))
            result = self._result(
                run_id, "failed", "invalid_intent", request, all_results, trace, errors, artifact_dir
            )
            self._save_artifacts(artifact_dir, request, all_results, result)
            return result

        await record_event(
            "objective_ready",
            required_domains=[domain.value for domain in objective.required_domains],
        )
        dataset = self.fusion.fuse([], request.as_of)

        stop_reason = "max_iterations"
        status: str = "partial"
        for iteration in range(1, request.max_iterations + 1):
            if monotonic() >= deadline:
                status, stop_reason = ("partial" if all_results else "failed"), "timeout"
                break
            coverage = self._coverage(dataset, objective.required_domains, objective.requirements)
            await record_event(
                "observation_ready",
                iteration=iteration,
                coverage=coverage.score,
                missing=[domain.value for domain in coverage.missing_domains],
                unmet_requirements=[
                    item.model_dump(mode="json")
                    for item in coverage.requirement_coverage
                    if item.hard and not item.passed
                ],
                companies=self._company_context(dataset),
                remaining_skill_calls=request.max_skill_calls - len(all_results),
            )
            if coverage.complete:
                status, stop_reason = "completed", "coverage_complete"
                break
            remaining = request.max_skill_calls - len(all_results)
            if remaining <= 0:
                stop_reason = "skill_budget_exhausted"
                break

            try:
                decision = await self._decide(
                    objective, dataset, coverage, iteration, all_results
                )
            except Exception as exc:
                errors.append(RunError(stage="planning", message=str(exc)))
                await record_event("planning_failed", iteration=iteration, error=str(exc))
                status, stop_reason = "blocked", "invalid_planner_decision"
                break

            await record_event(
                "decision_ready",
                iteration=iteration,
                decision=decision.decision,
                assessment=decision.assessment,
                proposed_tasks=len(decision.tasks),
            )
            if decision.decision == "blocked":
                status, stop_reason = "blocked", "planner_blocked"
                break
            if decision.decision == "stop" and coverage.complete:
                status, stop_reason = "completed", "planner_stop"
                break

            accepted, validation_errors = self._validate_tasks(
                decision.tasks,
                dataset=dataset,
                remaining=remaining,
                used_task_ids=used_task_ids,
                completed_signatures=completed_signatures,
                successful_task_ids=successful_task_ids,
                requirements=objective.requirements,
            )
            errors.extend(validation_errors)
            for error in validation_errors:
                await record_event(
                    "task_rejected", iteration=iteration, task_id=error.task_id, reason=error.message
                )

            if not accepted:
                no_progress += 1
                if no_progress >= 2:
                    stop_reason = "no_progress"
                    break
                continue

            used_task_ids.update(task.task_id for task in accepted)
            for task in accepted:
                completed_signatures.add(self._task_signature(task))
                await record_event(
                    "task_scheduled", iteration=iteration, task_id=task.task_id,
                    skill=task.skill_name, depends_on=task.depends_on,
                    requirement_ids=task.requirement_ids,
                    expected_fields=task.expected_fields,
                )

            async def on_result(result: SkillResult) -> None:
                await record_event(
                    "skill_completed" if result.success else "skill_failed",
                    iteration=iteration,
                    task_id=result.task_id,
                    skill_id=result.skill_id,
                    record_count=len(result.records),
                    attempts=result.attempts,
                    error=result.error,
                )

            before_count = int(dataset.quality_summary.get("structured_record_count", 0))
            try:
                remaining_seconds = max(0.001, deadline - monotonic())
                iteration_results = await asyncio.wait_for(
                    self.skillhub.execute_plan(
                        accepted,
                        completed_task_ids=successful_task_ids,
                        on_result=on_result,
                    ),
                    timeout=remaining_seconds,
                )
            except asyncio.TimeoutError:
                errors.append(RunError(stage="execution", message="global execution deadline exceeded"))
                status, stop_reason = ("partial" if all_results else "failed"), "timeout"
                break
            except IwencaiAuthenticationError as exc:
                errors.append(RunError(stage="skillhub", message=str(exc)))
                status, stop_reason = "failed", "iwencai_authentication_failed"
                break
            except SkillValidationError as exc:
                errors.append(RunError(stage="skillhub", message=str(exc)))
                status, stop_reason = "blocked", "invalid_task_graph"
                break

            all_results.extend(iteration_results)
            for result in iteration_results:
                if result.success:
                    successful_task_ids.add(result.task_id)
                else:
                    errors.append(RunError(
                        stage="skill_execution", message=result.error or "skill failed",
                        task_id=result.task_id, retryable=False,
                    ))
            dataset = self.fusion.fuse(all_results, request.as_of)
            after_count = int(dataset.quality_summary.get("structured_record_count", 0))
            no_progress = 0 if after_count > before_count else no_progress + 1
            await record_event(
                "fusion_updated",
                iteration=iteration,
                new_records=max(0, after_count - before_count),
                total_records=after_count,
                conflicts=len(dataset.conflicts),
            )
            if no_progress >= 2:
                stop_reason = "no_progress"
                break
        else:
            stop_reason = "max_iterations"

        final_coverage = self._coverage(dataset, objective.required_domains, objective.requirements)
        if final_coverage.complete:
            status, stop_reason = "completed", "coverage_complete"
        elif status not in ("failed", "blocked"):
            status = "partial"
        await record_event(
            "agent_completed",
            status=status,
            stop_reason=stop_reason,
            coverage=final_coverage.score,
            unmet_requirements=[
                item.requirement_id
                for item in final_coverage.requirement_coverage
                if item.hard and not item.passed
            ],
            skill_calls=len(all_results),
        )
        result = ResearchRunResult(
            run_id=run_id,
            status=status,
            stop_reason=stop_reason,
            dataset=dataset,
            coverage=final_coverage,
            errors=errors,
            execution_trace=trace,
            artifact_dir=str(artifact_dir.resolve()) if artifact_dir else None,
        )
        self._save_artifacts(artifact_dir, request, all_results, result)
        return result

    async def _understand(self, request: ResearchRequest) -> ResearchObjective:
        observation = {
            "request": request.model_dump(mode="json"),
            "planning_methodologies": self._planning_methodologies(),
        }
        response = await self.llm.generate_json(
            INTENT_SYSTEM_PROMPT,
            json.dumps(observation, ensure_ascii=False),
        )
        proposed = response.get("required_domains", [domain.value for domain in Domain])
        allowed = {domain.value: domain for domain in Domain}
        required = [allowed[item] for item in proposed if item in allowed]
        # All seven sections form the default data foundation. The LLM may order them,
        # but cannot silently remove the baseline contract.
        required = list(dict.fromkeys(required + list(Domain)))
        requirements = self._baseline_requirements(request, required)
        return ResearchObjective(
            industry=request.industry,
            focus_points=request.focus_points,
            data_requirements=request.data_requirements,
            required_domains=required,
            requirements=requirements,
            as_of=request.as_of,
        )

    async def _decide(
        self,
        objective: ResearchObjective,
        dataset: Any,
        coverage: Coverage,
        iteration: int,
        results: list[SkillResult],
    ) -> AgentDecision:
        catalog = [
            {
                "name": name,
                "domain": spec.domain.value,
                "description": spec.description,
                "skill_document": spec.source_path,
            }
            for name, spec in self.skillhub.catalog.items()
            if name == spec.skill_id
        ]
        observation = {
            "iteration": iteration,
            "objective": objective.model_dump(mode="json"),
            "coverage": coverage.model_dump(mode="json"),
            "identified_companies": self._company_context(dataset),
            "available_skills": catalog,
            "planning_methodologies": self._planning_methodologies(),
            "failed_skill_calls": [
                {
                    "task_id": item.task_id,
                    "skill_id": item.skill_id,
                    "query": item.query,
                    "error": item.error,
                }
                for item in results
                if not item.success
            ],
        }
        response = await self.llm.generate_json(
            PLANNER_SYSTEM_PROMPT,
            json.dumps(observation, ensure_ascii=False),
        )
        try:
            return AgentDecision.model_validate(response)
        except ValidationError as exc:
            raise ValueError(f"planner returned invalid task JSON: {exc}") from exc

    def _planning_methodologies(self) -> list[dict[str, str]]:
        return [
            {
                "name": item["name"],
                "description": item["description"],
                "source_material": item.get("source_material") or "",
            }
            for item in self.skillhub.skill_documents
            if item.get("role") == "planning"
        ]

    def _validate_tasks(
        self,
        tasks: list[SkillTask],
        *,
        dataset: Any,
        remaining: int,
        used_task_ids: set[str],
        completed_signatures: set[str],
        successful_task_ids: set[str],
        requirements: list[ResearchRequirement] | None = None,
    ) -> tuple[list[SkillTask], list[RunError]]:
        accepted: list[SkillTask] = []
        errors: list[RunError] = []
        plan_ids = {task.task_id for task in tasks}
        companies_known = bool(dataset.companies)
        company_context = self._company_context(dataset)
        leader_required = any(
            item.requirement_id == "leader_identification" for item in requirements or []
        )
        accepted_signatures: set[str] = set()
        known_requirement_ids = {item.requirement_id for item in requirements or []}
        requirements_by_domain: dict[Domain, list[str]] = {}
        for item in requirements or []:
            requirements_by_domain.setdefault(item.domain, []).append(item.requirement_id)
        for task in tasks:
            reason: str | None = None
            signature = self._task_signature(task)
            if len(accepted) >= remaining:
                reason = "global skill-call budget would be exceeded"
            elif task.task_id in used_task_ids:
                reason = "task_id was already used"
            elif task.skill_name not in self.skillhub.catalog:
                reason = f"unregistered skill: {task.skill_name}"
            elif not str(task.arguments.get("query", "")).strip():
                reason = "query argument is required"
            elif task.requirement_ids and not set(task.requirement_ids) <= known_requirement_ids:
                reason = "task references an unknown research requirement"
            elif signature in completed_signatures or signature in accepted_signatures:
                reason = "duplicate skill and query"
            elif (
                self.skillhub.catalog.get(task.skill_name)
                and self.skillhub.catalog[task.skill_name].domain == Domain.FINANCIALS
                and not companies_known
            ):
                reason = "financial_data requires an identified company from an earlier iteration"
            elif (
                self.skillhub.catalog.get(task.skill_name)
                and self.skillhub.catalog[task.skill_name].domain == Domain.FINANCIALS
                and companies_known
            ):
                eligible = company_context
                if leader_required:
                    with_basis = [item for item in company_context if item["selection_basis"]]
                    eligible = with_basis[:10] if with_basis else company_context[:10]
                query = str(task.arguments.get("query", "")).casefold()
                if not eligible:
                    reason = "financial_data requires identified companies in dataset"
                elif not any(
                    token and str(token).casefold() in query
                    for item in eligible
                    for token in (item["name"], item["code"], str(item["code"] or "").split(".")[0])
                ):
                    reason = "financial_data target is not an eligible identified company"
                elif set(task.depends_on) - plan_ids - successful_task_ids:
                    reason = "task contains unknown dependency"
            elif set(task.depends_on) - plan_ids - successful_task_ids:
                reason = "task contains unknown dependency"
            if reason:
                errors.append(RunError(stage="task_validation", message=reason, task_id=task.task_id))
            else:
                if not task.requirement_ids and task.skill_name in self.skillhub.catalog:
                    domain = self.skillhub.catalog[task.skill_name].domain
                    task = task.model_copy(update={
                        "requirement_ids": requirements_by_domain.get(domain, [])
                    })
                accepted.append(task)
                accepted_signatures.add(signature)
        try:
            self.skillhub.validate_plan(accepted, successful_task_ids)
        except SkillValidationError as exc:
            errors.append(RunError(stage="task_validation", message=str(exc)))
            return [], errors
        return accepted, errors

    @staticmethod
    def _task_signature(task: SkillTask) -> str:
        return f"{task.skill_name}:{json.dumps(task.arguments, sort_keys=True, ensure_ascii=False, default=str)}"

    @staticmethod
    def _company_context(dataset: Any) -> list[dict[str, Any]]:
        companies: dict[str, dict[str, Any]] = {}
        leader_metrics = (
            "总市值", "市值", "market_cap", "营业收入", "营业总收入", "营收", "主营业务收入",
            "revenue", "净利润", "归母净利润", "资产总计", "总资产", "市场份额", "行业排名"
        )
        for item in dataset.companies:
            if not (item.entity_code or item.entity_name):
                continue
            key = item.entity_code or item.entity_name
            entry = companies.setdefault(key, {
                "name": item.entity_name,
                "code": item.entity_code,
                "leader_score": None,
                "selection_basis": None,
            })
            if any(token.casefold() in item.metric.casefold() for token in leader_metrics):
                value = DataFetcherAgent._numeric_value(item.value)
                if value is not None and (entry["leader_score"] is None or value > entry["leader_score"]):
                    entry["leader_score"] = value
                    entry["selection_basis"] = item.metric
        return sorted(
            companies.values(),
            key=lambda item: (item["leader_score"] is not None, item["leader_score"] or 0),
            reverse=True,
        )[:20]

    @staticmethod
    def _numeric_value(value: Any) -> float | None:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.replace(",", ""))
            except ValueError:
                return None
        return None

    @staticmethod
    def _coverage(
        dataset: Any,
        required: list[Domain],
        requirements: list[ResearchRequirement] | None = None,
    ) -> Coverage:
        criteria = requirements or [
            ResearchRequirement(
                requirement_id=f"domain_{domain.value}", label=f"{domain.value} 数据", domain=domain
            )
            for domain in required
        ]
        requirement_coverage = [
            DataFetcherAgent._evaluate_requirement(dataset, item) for item in criteria
        ]
        by_domain = {
            domain: [item for item in requirement_coverage if item.domain == domain]
            for domain in required
        }
        covered = [
            domain for domain in required
            if by_domain[domain] and all(item.passed for item in by_domain[domain] if item.hard)
        ]
        missing = [domain for domain in required if domain not in covered]
        hard = [item for item in requirement_coverage if item.hard]
        score = sum(item.passed for item in hard) / len(hard) if hard else 1.0
        return Coverage(
            required_domains=required,
            covered_domains=covered,
            missing_domains=missing,
            score=score,
            complete=not missing and all(item.passed for item in hard),
            requirement_coverage=requirement_coverage,
        )

    @staticmethod
    def _evaluate_requirement(dataset: Any, requirement: ResearchRequirement) -> RequirementCoverage:
        records = list(dataset.records_for(requirement.domain))
        if requirement.acceptable_skill_ids:
            records = [
                item for item in records if item.source.skill_id in requirement.acceptable_skill_ids
            ]
        missing: list[str] = []
        if len(records) < requirement.min_records:
            missing.append(f"至少需要 {requirement.min_records} 条合格记录")
        if requirement.requires_entity_code and not any(item.entity_code for item in records):
            missing.append("缺少已对齐证券代码")
        if requirement.requires_period_end and not any(item.period_end for item in records):
            missing.append("缺少报告期")
        if requirement.requires_published_at and not any(item.published_at for item in records):
            missing.append("缺少发布日期")
        metrics = [item.metric.casefold() for item in records]
        for group in requirement.expected_metric_groups:
            if not any(any(token.casefold() in metric for token in group) for metric in metrics):
                missing.append("缺少指标组：" + "/".join(group))
        return RequirementCoverage(
            requirement_id=requirement.requirement_id,
            label=requirement.label,
            domain=requirement.domain,
            hard=requirement.hard,
            passed=not missing,
            evidence_count=len(records),
            evidence_record_ids=[item.record_id for item in records[:20]],
            missing=missing,
        )

    @staticmethod
    def _baseline_requirements(
        request: ResearchRequest, required: list[Domain]
    ) -> list[ResearchRequirement]:
        skill_ids = {
            Domain.INDUSTRY: ["hithink-industry-query"],
            Domain.COMPANIES: [
                "hithink-basicinfo-query", "hithink-astock-selector",
                "hithink-hkstock-selector", "hithink-usstock-selector",
            ],
            Domain.FINANCIALS: ["hithink-finance-query"],
            Domain.MACRO: ["hithink-macro-query"],
            Domain.INDUSTRY_CHAIN: ["hithink-business-query", "hithink-futures-query"],
            Domain.REPORTS: ["report-search", "hithink-insresearch-query"],
            Domain.NEWS: ["news-search", "announcement-search", "hithink-event-query"],
        }
        requirements = [
            ResearchRequirement(
                requirement_id=f"domain_{domain.value}",
                label=f"{domain.value} 核心数据",
                domain=domain,
                acceptable_skill_ids=skill_ids[domain],
                requires_entity_code=domain in (Domain.COMPANIES, Domain.FINANCIALS),
                requires_period_end=domain == Domain.FINANCIALS,
                requires_published_at=domain in (Domain.REPORTS, Domain.NEWS),
            )
            for domain in required
        ]
        text = " ".join(request.focus_points + request.data_requirements)
        if "龙头" in text:
            requirements.append(ResearchRequirement(
                requirement_id="leader_identification",
                label="龙头候选具有客观排名依据",
                domain=Domain.COMPANIES,
                requires_entity_code=True,
                acceptable_skill_ids=skill_ids[Domain.COMPANIES],
                expected_metric_groups=[["总市值", "market_cap", "营业收入", "revenue", "市场份额", "行业排名"]],
            ))
        if "财务" in text:
            requirements.append(ResearchRequirement(
                requirement_id="focused_financials",
                label="目标公司核心财务数据",
                domain=Domain.FINANCIALS,
                requires_entity_code=True,
                requires_period_end=True,
                acceptable_skill_ids=skill_ids[Domain.FINANCIALS],
                expected_metric_groups=[
                    ["revenue", "营业收入"],
                    ["net_profit", "parent_net_profit", "净利润"],
                    ["operating_cash_flow", "经营活动产生的现金流量净额", "经营现金流"],
                ],
            ))
        if "产业链" in text:
            requirements.append(ResearchRequirement(
                requirement_id="chain_structure",
                label="产业链结构或主营构成",
                domain=Domain.INDUSTRY_CHAIN,
                acceptable_skill_ids=skill_ids[Domain.INDUSTRY_CHAIN],
                expected_metric_groups=[[
                    "chain_segment", "产业链", "main_business", "主营", "business_composition",
                    "分类标准", "项目名称", "参控", "客户", "供应商", "合同",
                ]],
            ))
        return requirements

    def _result(
        self,
        run_id: str,
        status: str,
        stop_reason: str,
        request: ResearchRequest,
        results: list[SkillResult],
        trace: list[TraceEvent],
        errors: list[RunError],
        artifact_dir: Path | None,
    ) -> ResearchRunResult:
        dataset = self.fusion.fuse(results, request.as_of)
        coverage = self._coverage(
            dataset,
            list(Domain),
            self._baseline_requirements(request, list(Domain)),
        )
        return ResearchRunResult(
            run_id=run_id,
            status=status,
            stop_reason=stop_reason,
            dataset=dataset,
            coverage=coverage,
            errors=errors,
            execution_trace=trace,
            artifact_dir=str(artifact_dir.resolve()) if artifact_dir else None,
        )

    async def fetch_supplemental(
        self,
        demand: dict[str, Any] | Any,
        as_of: date | None = None,
        timeout_seconds: float = 15.0,
    ) -> list[ResearchRecord]:
        """Executes a targeted, single-shot supplementary query on behalf of downstream agents."""
        as_of = as_of or date.today()
        d_dict = demand if isinstance(demand, dict) else demand.model_dump()
        domain = str(d_dict.get("domain") or "financials").lower()
        query_hint = str(d_dict.get("query_hint") or "")
        entities = d_dict.get("entities", [])

        # Determine appropriate skill and query
        if "chain" in domain or "industry_chain" in str(d_dict.get("target_chart_type", "")):
            skill_name = "hithink-industry-query"
            query = query_hint or f"查询{entities[0] if entities else '行业'}产业链结构上中下游环节与代表企业"
        elif "macro" in domain:
            skill_name = "hithink-macro-query"
            query = query_hint or "查询宏观经济与行业相关时间序列月度季度指标"
        else:
            skill_name = "hithink-finance-query"
            ent_str = "、".join(str(e) for e in entities[:4]) if entities else "龙头企业"
            query = query_hint or f"查询{ent_str}近3年各季度营业收入、归母净利润、销售毛利率、资产负债率"

        task = SkillTask(
            task_id=f"SUPP_{secrets.token_hex(4)}",
            skill_name=skill_name,
            arguments={"query": query},
            purpose=f"反向补采协同: {d_dict.get('reason', '下游图表数据补全')}",
        )

        try:
            results = await asyncio.wait_for(
                self.skillhub.execute_plan([task]),
                timeout=timeout_seconds,
            )
            dataset = self.fusion.fuse(results, as_of)
            records = dataset.all_records()
            return records
        except Exception as exc:
            return []

    @staticmethod
    def _save_artifacts(
        artifact_dir: Path | None,
        request: ResearchRequest,
        results: list[SkillResult],
        result: ResearchRunResult,
    ) -> None:
        if artifact_dir is None:
            return
        raw_dir = artifact_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "request.json").write_text(
            request.model_dump_json(indent=2), encoding="utf-8"
        )
        for skill_result in results:
            (raw_dir / f"{skill_result.task_id}.json").write_text(
                json.dumps(skill_result.raw_payload, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        (artifact_dir / "events.jsonl").write_text(
            "\n".join(event.model_dump_json() for event in result.execution_trace) + "\n",
            encoding="utf-8",
        )
        (artifact_dir / "dataset.json").write_text(
            result.dataset.model_dump_json(indent=2), encoding="utf-8"
        )
        (artifact_dir / "result.json").write_text(
            result.model_dump_json(indent=2), encoding="utf-8"
        )
