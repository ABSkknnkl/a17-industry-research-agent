"""Interpretation agent: deterministic analysis followed by grounded semantic synthesis."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import secrets
from typing import Any

from pydantic import ValidationError

from data_interpreter.config import Settings
from data_interpreter.engine import DeterministicAnalysisEngine
from data_interpreter.llm import OpenAICompatibleLLM, SemanticLLM
from data_interpreter.models import (
    AnalysisRequest,
    AnalysisTraceEvent,
    AppliedSkill,
    ContentSection,
    Insight,
    InterpretationReport,
    KnowledgeFact,
    SkillExecutionResult,
    StructuredResearchDataset,
)
from data_interpreter.skillhub import AnalysisSkill, AnalysisSkillHub


SKILL_PLANNING_SYSTEM_PROMPT = """你是顶级产业与金融研报数据解读规划总监。
你负责根据取数数据集的结构、领域分布、关键指标、异常情况与核心公司，自主调用投研方法论技能库中的专业技能（通过 invoke_skill 工具），以实现针对性的深度行业解读。
【原则】
1. 必须根据实际数据特征（如是否包含产业链上下游数据、是否有财务三大表、是否有估值/异动指标、是否有宏观周期指标）精准调用技能；
2. 每次调用 invoke_skill 必须结合当前数据形态给出清晰、专业的调用理由与预期分析重点；
3. 请自主挑选 4 到 7 个最适用的技能进行深入剖析。"""

SEMANTIC_SYSTEM_PROMPT = """你是顶级研报数据解读智能体的语义分析模块。
你的唯一事实来源是输入 JSON 中的 deterministic_findings（含 key_metrics、trends、anomalies、cross_validations、comps_matrix、industry_chain、financial_ratios）和 evidence_index。
不得补充外部未经证明的事实，不得给出投资建议。每条洞察必须引用输入中真实存在的 evidence_record_ids；证据不足时明确写“证据不足”。百分比小数 0.12 表示 12%。

仅返回 JSON 对象，字段为：
1. executive_summary：3-5 句，高水准概括行业市场定位、核心竞争龙头财务表现（结合可比矩阵与估值分位数）、产业链关键瓶颈及数据限制；
2. knowledge_facts：从文本或数值证据中抽取的原子事实数组，每项仅含 fact_id、subject、predicate、
   object_summary、category、confidence、evidence_record_ids；不得把观点或预测写成事实；
   category 必须是以下之一: industry, company, financial, macro, industry_chain, event, other；
3. insights：数组（6-12项），每项仅含 insight_id、title、conclusion、significance、confidence、
   evidence_record_ids、related_metric_ids、related_trend_ids、related_anomaly_ids；
   要求结合财务比率（杜邦分解、毛利率、净现比质量）、同行可比估值溢价与产业链上下游环节进行专业深度归纳；
4. content_outline：数组，每项仅含 heading、purpose、key_points、evidence_record_ids。
confidence 只能为 low、medium、high。所有引用 ID 必须逐字来自输入。"""

SKILL_EXECUTION_SYSTEM_PROMPT = """你是数据解读 SkillHub 中的专业分析执行单元。
你必须严格按照当前技能的方法论指南（instructions），对输入的确定性发现（deterministic_findings）和证据库（evidence_index）进行深度专业剖析。
不得补取外部事实、不得猜测因果、不得提供投资建议。每项提取的事实和洞察必须引用真实存在的 evidence_record_ids。

【必须返回的严格 JSON 格式】：
{
  "summary": "2-3句概括本技能分析的核心结论与数据边界",
  "knowledge_facts": [
    {
      "fact_id": "F-001",
      "subject": "公司或行业主体，如'目标公司'或'研究行业'",
      "predicate": "属性或关系，如'2026半年度营收'或'产业链所处环节'",
      "object_summary": "客观事实陈述，包含明确数值与单位",
      "category": "industry|company|financial|macro|industry_chain|event|other",
      "confidence": "low|medium|high",
      "evidence_record_ids": ["必须逐字来自 evidence_index 的真实记录ID"]
    }
  ],
  "insights": [
    {
      "insight_id": "I-001",
      "title": "洞察标题，精炼反映分析核心",
      "conclusion": "深入分析结论，阐明数据指标背后的业务机制、竞争地位或财务健康状况",
      "significance": "该结论对行业格局或投资分析的重要性评估",
      "confidence": "low|medium|high",
      "evidence_record_ids": ["真实记录ID"],
      "related_metric_ids": [],
      "related_trend_ids": [],
      "related_anomaly_ids": []
    }
  ],
  "warnings": ["数据限制说明，若无明显缺陷可留空"]
}
【提取要求】：
请立足当前技能的方法论视角（如竞争格局、事件催化、产业链分工、估值水平等），积极提炼出 3~6 条高质量的 knowledge_facts，以及 2~4 条深度 insights。严禁无故返回空数组。"""

BATCH_SKILL_EXECUTION_SYSTEM_PROMPT = """你是数据解读 SkillHub 中的专业多技能联合分析执行单元。
你负责对输入的确定性发现（deterministic_findings）和证据库（evidence_index），同时运用输入的多个投研方法论技能（skills）进行联合深度分析。
请严格针对输入 skills 列表中的【每一个技能】，分别结合该技能的方法论指南（instructions）和视角，提取专业事实与洞察。
不得补取外部事实、不得猜测因果、不得提供投资建议。每项提取的事实和洞察必须引用真实存在的 evidence_record_ids。

【必须返回的严格 JSON 格式】：
{
  "skills": [
    {
      "skill_name": "精确对应输入的技能名称（如 macro-cycle-analysis）",
      "summary": "2-3句概括本技能分析的核心结论与数据边界",
      "knowledge_facts": [
        {
          "fact_id": "F-001",
          "subject": "公司或行业主体，如'目标公司'或'研究行业'",
          "predicate": "属性或关系，如'2026半年度营收'或'产业链所处环节'",
          "object_summary": "客观事实陈述，包含明确数值与单位",
          "category": "industry|company|financial|macro|industry_chain|event|other",
          "confidence": "low|medium|high",
          "evidence_record_ids": ["必须逐字来自 evidence_index 的真实记录ID"]
        }
      ],
      "insights": [
        {
          "insight_id": "I-001",
          "title": "洞察标题，精炼反映分析核心",
          "conclusion": "深入分析结论，阐明数据指标背后的业务机制、竞争地位或财务健康状况",
          "significance": "该结论对行业格局或投资分析的重要性评估",
          "confidence": "low|medium|high",
          "evidence_record_ids": ["真实记录ID"],
          "related_metric_ids": [],
          "related_trend_ids": [],
          "related_anomaly_ids": []
        }
      ],
      "warnings": ["数据限制说明，若无明显缺陷可留空"]
    }
  ]
}
【提取要求】：
请针对 skills 列表中的每一个技能，分别提炼 2~5 条高质量的 knowledge_facts 与 1~3 条深度 insights。确保 skills 数组完整覆盖输入的所有技能。"""


class DataInterpreterAgent:
    def __init__(
        self,
        *,
        llm: SemanticLLM | None = None,
        engine: DeterministicAnalysisEngine | None = None,
        skillhub: AnalysisSkillHub | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or Settings.from_env()
        self.llm = llm or OpenAICompatibleLLM(self.settings)
        self.engine = engine or DeterministicAnalysisEngine()
        self.skillhub = skillhub or AnalysisSkillHub()

    async def run(
        self,
        dataset: StructuredResearchDataset | dict[str, Any],
        request: AnalysisRequest | None = None,
        *,
        emit: Any | None = None,
        save_artifacts: bool = True,
    ) -> InterpretationReport:
        request = request or AnalysisRequest()
        if not isinstance(dataset, StructuredResearchDataset):
            dataset = StructuredResearchDataset.model_validate(dataset)
        report_id = f"analysis-{request.as_of.strftime('%Y%m%d')}-{secrets.token_hex(4)}"
        artifact_dir = self.settings.output_dir / "runs" / report_id if save_artifacts else None

        class TraceList(list):
            def append(self, item: Any) -> None:
                super().append(item)
                if emit:
                    try:
                        event_dict = {
                            "event": getattr(item, "event", str(item)),
                            "skill_name": getattr(item, "skill_name", None),
                            "task_id": getattr(item, "task_id", None),
                            "details": getattr(item, "details", {})
                        }
                        if asyncio.iscoroutinefunction(emit):
                            asyncio.create_task(emit(event_dict))
                        else:
                            emit(event_dict)
                    except Exception:
                        pass

        trace = TraceList()
        trace.append(AnalysisTraceEvent(
            event="agent_started",
            details={"subject": request.subject, "record_count": len(dataset.all_records())},
        ))
        metrics, trends, anomalies, validations, evidence, quality = self.engine.analyze(dataset, request)
        evidence.update(self._textual_evidence(dataset, request, exclude=set(evidence)))
        warnings = list(quality.limitations)
        trace.append(AnalysisTraceEvent(event="deterministic_analysis_completed", details={
            "key_metrics": len(metrics), "trends": len(trends), "anomalies": len(anomalies),
            "cross_validations": len(validations),
        }))

        # Compute specialized financial modeling & peer comparisons
        comps_matrix = self.engine.build_peer_comps_matrix(dataset)
        industry_chain_segments = self.engine.extract_industry_chain(dataset, request.subject)
        financial_ratios = self.engine.compute_financial_ratios(dataset)

        # LLM autonomous skill planning when LLM is available, fallback to deterministic select
        if request.enable_semantic_analysis and self.llm.is_available and hasattr(self.llm, "plan_skills_with_tools"):
            selected_skills = await self._plan_skills(
                request, dataset, metrics, trends, anomalies, validations, quality, trace
            )
        else:
            selected_skills = self.skillhub.select(request, dataset)
            trace.append(AnalysisTraceEvent(event="skill_routed_by_policy", details={
                "skills": [s.name for s in selected_skills],
                "reason": "基于数据集结构与字段覆盖特征，快速路由分析方法论技能",
            }))

        trace.append(AnalysisTraceEvent(event="skills_planned", details={
            "skills": [skill.name for skill in selected_skills],
        }))
        semantic_status = "skipped"
        executive_summary, insights, outline = self._deterministic_narrative(
            request, metrics, trends, anomalies, quality
        )
        knowledge_facts: list[KnowledgeFact] = []
        skill_results: list[SkillExecutionResult] = []

        if request.enable_semantic_analysis and self.llm.is_available and evidence:
            try:
                skill_results = await self._execute_skills(
                    selected_skills, request, metrics, trends, anomalies, validations,
                    evidence, quality, trace,
                    comps_matrix=comps_matrix,
                    industry_chain_segments=industry_chain_segments,
                    financial_ratios=financial_ratios,
                )
                skill_knowledge = self._dedupe_knowledge(
                    item for result in skill_results for item in result.knowledge_facts
                )
                skill_insights = self._dedupe_insights(
                    item for result in skill_results for item in result.insights
                )
                knowledge_facts = skill_knowledge
                insights = skill_insights or insights

                # Focus evidence payload for semantic fusion to prevent token bloat
                fusion_eids: set[str] = set()
                for sr in skill_results:
                    for kf in getattr(sr, "knowledge_facts", []):
                        fusion_eids.update(kf.evidence_record_ids)
                    for ins in getattr(sr, "insights", []):
                        fusion_eids.update(ins.evidence_record_ids)
                for m in metrics[:20]:
                    fusion_eids.update(getattr(m, "evidence_record_ids", []))
                for t in trends[:15]:
                    fusion_eids.update(getattr(t, "evidence_record_ids", []))
                for a in anomalies[:15]:
                    fusion_eids.update(getattr(a, "evidence_record_ids", []))

                if len(fusion_eids) < 40:
                    for k in evidence.keys():
                        fusion_eids.add(k)
                        if len(fusion_eids) >= 60:
                            break

                fusion_evidence = {
                    key: evidence[key].model_dump(mode="json")
                    for key in list(fusion_eids)[:80]
                    if key in evidence
                }

                trace.append(AnalysisTraceEvent(
                    event="semantic_fusion_started",
                    details={"skills_count": len(skill_results), "evidence_count": len(fusion_evidence)},
                ))

                response = await self.llm.generate_json(
                    SEMANTIC_SYSTEM_PROMPT,
                    json.dumps({
                        "request": request.model_dump(mode="json"),
                        "deterministic_findings": {
                            "key_metrics": [item.model_dump(mode="json") for item in metrics],
                            "trends": [item.model_dump(mode="json") for item in trends[:30]],
                            "anomalies": [item.model_dump(mode="json") for item in anomalies[:30]],
                            "cross_validations": [item.model_dump(mode="json") for item in validations[:30]],
                            "comps_matrix": comps_matrix.model_dump(mode="json") if comps_matrix else None,
                            "industry_chain": [item.model_dump(mode="json") for item in industry_chain_segments],
                            "financial_ratios": financial_ratios[:20],
                            "data_quality": quality.model_dump(mode="json"),
                        },
                        "evidence_index": fusion_evidence,
                        "limits": {"max_insights": request.max_insights},
                        "skill_results": [item.model_dump(mode="json") for item in skill_results],
                        "analysis_methodologies": [
                            {
                                "name": skill.name,
                                "description": skill.description,
                                "instructions": skill.instructions,
                                "boundary": "方法论只用于组织和验证已有证据，不能充当事实来源。",
                            }
                            for skill in selected_skills
                        ],
                    }, ensure_ascii=False, default=str),
                )
                executive_summary, knowledge_facts, insights, outline = self._validate_semantic(
                    response,
                    allowed_record_ids=set(evidence),
                    allowed_metric_ids={item.metric_id for item in metrics},
                    allowed_trend_ids={item.trend_id for item in trends},
                    allowed_anomaly_ids={item.anomaly_id for item in anomalies},
                    max_insights=request.max_insights,
                    fallback=(
                        executive_summary,
                        skill_knowledge,
                        skill_insights or insights,
                        outline,
                    ),
                )
                semantic_status = "completed"
                trace.append(AnalysisTraceEvent(event="skill_linter_checked", details={
                    "facts_validated": len(knowledge_facts),
                    "insights_validated": len(insights),
                    "grounding_passed": True,
                }))
                trace.append(AnalysisTraceEvent(event="semantic_fusion_completed", details={
                    "successful_skills": sum(item.status == "completed" for item in skill_results),
                    "failed_skills": sum(item.status == "failed" for item in skill_results),
                }))
            except Exception as exc:
                semantic_status = "failed"
                warnings.append(f"语义分析失败，已保留确定性分析结果：{exc}")
                trace.append(AnalysisTraceEvent(event="semantic_fusion_failed", details={"error": str(exc)}))
        elif request.enable_semantic_analysis and not self.llm.is_available:
            warnings.append("未配置模型，语义深化已跳过；报告仍包含确定性指标、趋势、异常与交叉验证结果")

        if quality.record_count == 0:
            status = "failed"
        elif quality.analyzability_score < 0.35:
            status = "partial"
        else:
            status = "completed"
        data_quality_appendix = self.engine.build_data_quality_appendix(
            dataset, comps_matrix, anomalies, validations, quality
        )
        report = InterpretationReport(
            report_id=report_id,
            subject=request.subject,
            as_of=request.as_of,
            status=status,
            semantic_status=semantic_status,
            applied_skills=[AppliedSkill(
                name=skill.name,
                description=skill.description,
                source=skill.source,
                adaptation=skill.adaptation,
                status=(
                    "executed" if any(result.skill_name == skill.name and result.status == "completed" for result in skill_results)
                    else "failed" if any(result.skill_name == skill.name and result.status == "failed" for result in skill_results)
                    else "skipped" if semantic_status == "skipped"
                    else "selected"
                ),
            ) for skill in selected_skills],
            skill_results=skill_results,
            execution_trace=trace,
            executive_summary=executive_summary,
            key_metrics=metrics,
            trends=trends,
            anomalies=anomalies,
            cross_validations=validations,
            knowledge_facts=knowledge_facts,
            insights=insights,
            content_outline=outline,
            comps_matrix=comps_matrix,
            industry_chain_segments=industry_chain_segments,
            financial_ratios=financial_ratios,
            evidence_index=evidence,
            data_quality=quality,
            data_quality_appendix=data_quality_appendix,
            warnings=warnings,
            artifact_dir=str(artifact_dir.resolve()) if artifact_dir else None,
        )
        self._save(artifact_dir, request, dataset, report)
        return report

    async def _plan_skills(
        self,
        request: AnalysisRequest,
        dataset: StructuredResearchDataset,
        metrics: list[KeyMetric],
        trends: list[TrendFinding],
        anomalies: list[AnomalyFinding],
        validations: list[CrossValidationFinding],
        quality: Any,
        trace: list[AnalysisTraceEvent],
    ) -> list[AnalysisSkill]:
        populated_domains = [
            d for d in ("industry", "companies", "financials", "macro", "industry_chain", "reports", "news")
            if getattr(dataset, d)
        ]
        sample_companies = [c.entity_name for c in dataset.companies[:10] if c.entity_name]
        user_prompt = json.dumps({
            "subject": request.subject,
            "focus_points": request.focus_points,
            "data_summary": {
                "record_count": quality.record_count,
                "populated_domains": populated_domains,
                "sample_companies": sample_companies,
                "metrics_count": len(metrics),
                "sample_metrics": [m.name for m in metrics[:10]],
                "anomalies_count": len(anomalies),
                "validations_count": len(validations),
            },
            "instruction": "请分析上述取数特征，自主调用 4~7 个最适用的方法论技能指导深度研报解读。",
        }, ensure_ascii=False, indent=2)

        try:
            planned = await self.llm.plan_skills_with_tools(
                SKILL_PLANNING_SYSTEM_PROMPT,
                user_prompt,
                tools=self.skillhub.get_tool_spec(),
            )
            skills_map: dict[str, AnalysisSkill] = {}
            for item in planned:
                sname = item.get("skill_name", "")
                reason = item.get("reason", "")
                skill = self.skillhub.get(sname)
                if skill:
                    enriched = AnalysisSkill(
                        name=skill.name,
                        description=skill.description,
                        instructions=skill.instructions,
                        domains=skill.domains,
                        keywords=skill.keywords,
                        source=skill.source,
                        adaptation=reason or skill.adaptation,
                        always=skill.always,
                        requires_signal=skill.requires_signal,
                        path=skill.path,
                    )
                    skills_map[sname] = enriched
                    trace.append(AnalysisTraceEvent(
                        event="skill_invoked_by_llm",
                        details={"skill": sname, "reason": reason},
                    ))

            # Ensure always skills are included
            for s in self.skillhub.catalog.values():
                if s.always and s.name not in skills_map:
                    skills_map[s.name] = s

            if skills_map:
                return sorted(skills_map.values(), key=lambda x: (not x.always, x.name))
        except Exception as exc:
            trace.append(AnalysisTraceEvent(
                event="skill_planning_fallback",
                details={"error": str(exc)},
            ))

        return self.skillhub.select(request, dataset)

    async def _execute_skills(
        self, selected_skills, request, metrics, trends, anomalies, validations,
        evidence, quality, trace,
        *,
        comps_matrix: Any = None,
        industry_chain_segments: Any = None,
        financial_ratios: Any = None,
    ) -> list[SkillExecutionResult]:
        if not selected_skills:
            return []

        findings = {
            "key_metrics": [item.model_dump(mode="json") for item in metrics],
            "trends": [item.model_dump(mode="json") for item in trends[:30]],
            "anomalies": [item.model_dump(mode="json") for item in anomalies[:30]],
            "cross_validations": [item.model_dump(mode="json") for item in validations[:30]],
            "comps_matrix": comps_matrix.model_dump(mode="json") if comps_matrix else None,
            "industry_chain": [item.model_dump(mode="json") for item in industry_chain_segments] if industry_chain_segments else [],
            "financial_ratios": financial_ratios[:20] if financial_ratios else [],
            "data_quality": quality.model_dump(mode="json"),
        }

        if self.settings.batch_skills and len(selected_skills) > 2:
            return await self._execute_skills_batched(
                selected_skills, request, findings, evidence, metrics, trace
            )
        return await self._execute_skills_individual(
            selected_skills, request, findings, evidence, metrics, trace
        )

    async def _execute_skills_individual(
        self, selected_skills, request, findings, evidence, metrics, trace
    ) -> list[SkillExecutionResult]:
        semaphore = asyncio.Semaphore(self.settings.skill_concurrency_limit)

        async def execute(index, skill):
            task_id = f"S{index:02d}-{skill.name}"
            trace.append(AnalysisTraceEvent(
                event="skill_scheduled", task_id=task_id, skill_name=skill.name
            ))
            try:
                skill_evidence = self._filter_evidence_for_skill(skill, evidence, metrics)
                async with semaphore:
                    response = await self.llm.generate_json(
                        SKILL_EXECUTION_SYSTEM_PROMPT,
                        json.dumps({
                            "task_id": task_id,
                            "skill": {
                                "name": skill.name,
                                "description": skill.description,
                                "instructions": skill.instructions,
                            },
                            "request": request.model_dump(mode="json"),
                            "deterministic_findings": findings,
                            "evidence_index": skill_evidence,
                        }, ensure_ascii=False, default=str),
                    )
                result = self._validate_skill_response(
                    task_id, skill.name, response, set(evidence), request.max_insights
                )
                trace.append(AnalysisTraceEvent(
                    event="skill_completed", task_id=task_id, skill_name=skill.name,
                    details={"facts": len(result.knowledge_facts), "insights": len(result.insights)},
                ))
                return result
            except Exception as exc:
                trace.append(AnalysisTraceEvent(
                    event="skill_failed", task_id=task_id, skill_name=skill.name,
                    details={"error": str(exc)},
                ))
                return SkillExecutionResult(
                    task_id=task_id, skill_name=skill.name, status="failed", error=str(exc)
                )

        return list(await asyncio.gather(*(
            execute(index, skill) for index, skill in enumerate(selected_skills, 1)
        )))

    async def _execute_skills_batched(
        self, selected_skills, request, findings, evidence, metrics, trace
    ) -> list[SkillExecutionResult]:
        macro_chain_keywords = {"macro", "chain", "landscape", "overview", "sentiment", "rotation", "geopolitical"}
        macro_chain_domains = {"macro", "industry_chain", "industry"}

        batch_a: list[tuple[int, Any]] = []
        batch_b: list[tuple[int, Any]] = []

        for idx, skill in enumerate(selected_skills, 1):
            name_lower = skill.name.lower()
            domains = {str(d).lower() for d in getattr(skill, "domains", ())}
            if any(kw in name_lower for kw in macro_chain_keywords) or bool(domains.intersection(macro_chain_domains)):
                batch_a.append((idx, skill))
            else:
                batch_b.append((idx, skill))

        if not batch_a and batch_b:
            mid = len(batch_b) // 2
            batch_a = batch_b[:mid]
            batch_b = batch_b[mid:]
        elif not batch_b and batch_a:
            mid = len(batch_a) // 2
            batch_b = batch_a[mid:]
            batch_a = batch_a[:mid]

        async def execute_batch(batch_name: str, batch_items: list[tuple[int, Any]]) -> list[SkillExecutionResult]:
            for idx, skill in batch_items:
                task_id = f"S{idx:02d}-{skill.name}"
                trace.append(AnalysisTraceEvent(
                    event="skill_scheduled", task_id=task_id, skill_name=skill.name
                ))

            batch_evidence: dict[str, Any] = {}
            for _, skill in batch_items:
                batch_evidence.update(self._filter_evidence_for_skill(skill, evidence, metrics, max_items=35))
            if len(batch_evidence) > 70:
                batch_evidence = dict(list(batch_evidence.items())[:70])

            skills_payload = [
                {
                    "name": skill.name,
                    "description": skill.description,
                    "instructions": skill.instructions,
                }
                for _, skill in batch_items
            ]

            try:
                response = await self.llm.generate_json(
                    BATCH_SKILL_EXECUTION_SYSTEM_PROMPT,
                    json.dumps({
                        "batch_name": batch_name,
                        "skills": skills_payload,
                        "request": request.model_dump(mode="json"),
                        "deterministic_findings": findings,
                        "evidence_index": batch_evidence,
                    }, ensure_ascii=False, default=str),
                )

                skill_response_map: dict[str, dict[str, Any]] = {}
                if isinstance(response, dict):
                    if "skills" in response and isinstance(response["skills"], list):
                        for item in response["skills"]:
                            if isinstance(item, dict) and "skill_name" in item:
                                skill_response_map[str(item["skill_name"]).strip()] = item
                            elif isinstance(item, dict) and "name" in item:
                                skill_response_map[str(item["name"]).strip()] = item
                    for key, val in response.items():
                        if key != "skills" and isinstance(val, dict):
                            skill_response_map[str(key).strip()] = val

                if not skill_response_map and isinstance(response, dict) and ("knowledge_facts" in response or "insights" in response):
                    for _, sk in batch_items:
                        skill_response_map[sk.name] = response

                results: list[SkillExecutionResult] = []
                for idx, skill in batch_items:
                    task_id = f"S{idx:02d}-{skill.name}"
                    sub_resp = skill_response_map.get(skill.name)
                    if not sub_resp:
                        for k, v in skill_response_map.items():
                            if k.lower() == skill.name.lower() or k in skill.name or skill.name in k:
                                sub_resp = v
                                break
                    if not sub_resp:
                        sub_resp = {}

                    result = self._validate_skill_response(
                        task_id, skill.name, sub_resp, set(evidence), request.max_insights
                    )
                    trace.append(AnalysisTraceEvent(
                        event="skill_completed", task_id=task_id, skill_name=skill.name,
                        details={"facts": len(result.knowledge_facts), "insights": len(result.insights)},
                    ))
                    results.append(result)
                return results
            except Exception as exc:
                results = []
                for idx, skill in batch_items:
                    task_id = f"S{idx:02d}-{skill.name}"
                    trace.append(AnalysisTraceEvent(
                        event="skill_failed", task_id=task_id, skill_name=skill.name,
                        details={"error": str(exc)},
                    ))
                    results.append(SkillExecutionResult(
                        task_id=task_id, skill_name=skill.name, status="failed", error=str(exc)
                    ))
                return results

        tasks = []
        if batch_a:
            tasks.append(execute_batch("Batch-A-Topology-Macro", batch_a))
        if batch_b:
            tasks.append(execute_batch("Batch-B-Fundamentals-Quant", batch_b))

        batch_outputs = await asyncio.gather(*tasks)
        skill_result_map: dict[str, SkillExecutionResult] = {}
        for b_res in batch_outputs:
            for item in b_res:
                skill_result_map[item.skill_name] = item

        return [
            skill_result_map.get(
                skill.name,
                SkillExecutionResult(task_id=f"S{i:02d}-{skill.name}", skill_name=skill.name, status="failed", error="未返回结果")
            )
            for i, skill in enumerate(selected_skills, 1)
        ]

    @staticmethod
    def _filter_evidence_for_skill(
        skill: Any,
        evidence: dict[str, Any],
        metrics: list[Any],
        max_items: int = 60,
    ) -> dict[str, Any]:
        domain_aliases = {
            "financial": {"financial", "financials", "finance"},
            "financials": {"financial", "financials", "finance"},
            "company": {"company", "companies"},
            "companies": {"company", "companies"},
            "industry": {"industry", "industries"},
            "industries": {"industry", "industries"},
            "macro": {"macro", "macros"},
            "macros": {"macro", "macros"},
            "industry_chain": {"industry_chain", "chains", "chain"},
            "chains": {"industry_chain", "chains", "chain"},
            "news": {"news"},
            "reports": {"reports", "report"},
            "report": {"reports", "report"},
            "events": {"events", "event"},
            "event": {"events", "event"},
        }
        target_domains: set[str] = set()
        for d in getattr(skill, "domains", ()):
            target_domains.update(domain_aliases.get(str(d).lower(), {str(d).lower()}))

        selected_keys: list[str] = []
        for m in metrics[:15]:
            for rid in getattr(m, "evidence_record_ids", []):
                if rid in evidence and rid not in selected_keys:
                    selected_keys.append(rid)

        if target_domains:
            for k, item in evidence.items():
                dom = str(getattr(item, "domain", "")).lower()
                if dom in target_domains and k not in selected_keys:
                    selected_keys.append(k)
                    if len(selected_keys) >= max_items:
                        break

        if len(selected_keys) < 30:
            for k in evidence.keys():
                if k not in selected_keys:
                    selected_keys.append(k)
                    if len(selected_keys) >= 30:
                        break

        return {k: evidence[k].model_dump(mode="json") for k in selected_keys[:max_items]}

    @staticmethod
    def _validate_skill_response(task_id, skill_name, response, allowed_ids, max_insights):
        cat_map = {
            "financials": "financial", "finance": "financial", "companies": "company",
            "events": "event", "industries": "industry", "chains": "industry_chain",
            "macros": "macro",
        }
        valid_cats = {"industry", "company", "financial", "macro", "industry_chain", "event", "other"}

        knowledge: list[KnowledgeFact] = []
        for raw in response.get("knowledge_facts", []):
            if isinstance(raw, dict):
                norm = dict(raw)
                if "fact_id" not in norm and "id" in norm:
                    norm["fact_id"] = str(norm["id"])
                if "fact_id" not in norm:
                    norm["fact_id"] = f"F-{len(knowledge)+1:03d}"
                if "evidence_record_ids" not in norm:
                    norm["evidence_record_ids"] = norm.get("evidence_ids") or norm.get("evidence") or []
                if isinstance(norm.get("evidence_record_ids"), str):
                    norm["evidence_record_ids"] = [norm["evidence_record_ids"]]
                cat = str(norm.get("category", "other")).lower()
                norm["category"] = cat_map.get(cat, cat if cat in valid_cats else "other")
                conf = str(norm.get("confidence", "high")).lower()
                norm["confidence"] = conf if conf in {"low", "medium", "high"} else "high"
                if "subject" not in norm:
                    norm["subject"] = str(norm.get("entity") or norm.get("title") or skill_name)
                if "predicate" not in norm:
                    norm["predicate"] = str(norm.get("metric") or norm.get("attribute") or "核心特征")
                if "object_summary" not in norm:
                    norm["object_summary"] = str(norm.get("value") or norm.get("summary") or norm.get("description") or "")
                raw = norm
            try:
                item = KnowledgeFact.model_validate(raw)
            except ValidationError:
                continue
            item.evidence_record_ids = [value for value in item.evidence_record_ids if value in allowed_ids]
            if item.evidence_record_ids:
                item.fact_id = f"{skill_name}:{item.fact_id}"
                knowledge.append(item)

        insights: list[Insight] = []
        for raw in response.get("insights", [])[:max_insights]:
            if isinstance(raw, dict):
                norm = dict(raw)
                if "insight_id" not in norm and "id" in norm:
                    norm["insight_id"] = str(norm["id"])
                if "insight_id" not in norm:
                    norm["insight_id"] = f"I-{len(insights)+1:03d}"
                if "evidence_record_ids" not in norm:
                    norm["evidence_record_ids"] = norm.get("evidence_ids") or norm.get("evidence") or []
                if isinstance(norm.get("evidence_record_ids"), str):
                    norm["evidence_record_ids"] = [norm["evidence_record_ids"]]
                conf = str(norm.get("confidence", "high")).lower()
                norm["confidence"] = conf if conf in {"low", "medium", "high"} else "high"
                if "title" not in norm:
                    norm["title"] = str(norm.get("name") or f"{skill_name}分析发现")
                if "conclusion" not in norm:
                    norm["conclusion"] = str(norm.get("summary") or norm.get("desc") or "")
                if "significance" not in norm:
                    norm["significance"] = "对产业发展格局具有参考意义"
                raw = norm
            try:
                item = Insight.model_validate(raw)
            except ValidationError:
                continue
            item.evidence_record_ids = [value for value in item.evidence_record_ids if value in allowed_ids]
            if item.evidence_record_ids:
                item.insight_id = f"{skill_name}:{item.insight_id}"
                insights.append(item)

        cited = list(dict.fromkeys(
            value for item in [*knowledge, *insights] for value in item.evidence_record_ids
        ))
        return SkillExecutionResult(
            task_id=task_id,
            skill_name=skill_name,
            status="completed",
            summary=str(response.get("summary") or response.get("executive_summary") or "").strip(),
            knowledge_facts=knowledge,
            insights=insights,
            evidence_record_ids=cited,
            warnings=[str(value) for value in response.get("warnings", [])],
        )

    @staticmethod
    def _dedupe_knowledge(items):
        result, seen = [], set()
        for item in items:
            key = (item.subject.casefold(), item.predicate.casefold(), item.object_summary.casefold())
            if key not in seen:
                seen.add(key)
                result.append(item)
        return result

    @staticmethod
    def _dedupe_insights(items):
        result, seen = [], set()
        for item in items:
            key = (item.title.casefold(), item.conclusion.casefold())
            if key not in seen:
                seen.add(key)
                result.append(item)
        return result

    @staticmethod
    def _textual_evidence(dataset, request, *, exclude: set[str]):
        preferred = {
            "summary", "source_original", "title", "report_title", "main_business",
            "business_composition", "chain_segment", "主营业务", "主营构成", "产业链环节",
            "项目名称", "指标", "行业名称",
        }
        focus = [request.subject.casefold(), *(item.casefold() for item in request.focus_points)]
        candidates = []
        for record in dataset.all_records():
            if record.record_id in exclude or not isinstance(record.value, str) or not record.value.strip():
                continue
            metric = record.metric.casefold()
            text = record.value.strip()
            preferred_score = 2 if metric in preferred else 0
            focus_score = sum(token in text.casefold() or token in metric for token in focus if token)
            if not preferred_score and not focus_score:
                continue
            candidates.append((preferred_score + focus_score, record.published_at or record.period_end, record))
        candidates.sort(key=lambda item: (item[0], item[1] or request.as_of), reverse=True)
        result = {}
        for _, _, record in candidates[:60]:
            result[record.record_id] = DeterministicAnalysisEngine._evidence(record)
        return result

    @staticmethod
    def _deterministic_narrative(request, metrics, trends, anomalies, quality):
        if not quality.record_count:
            return "输入数据集为空，无法形成数据解读结论。", [], []
        summary = (
            f"围绕“{request.subject}”共分析 {quality.record_count} 条结构化记录，"
            f"识别 {len(metrics)} 个关键指标、{len(trends)} 个趋势和 {len(anomalies)} 个异常候选。"
            f"数据可分析度为 {quality.analyzability_score:.0%}；确定性结果不包含未经证据支持的因果判断。"
        )
        insights: list[Insight] = []
        for index, trend in enumerate(trends[: request.max_insights], 1):
            direction = {"up": "上升", "down": "下降", "flat": "基本持平", "volatile": "波动"}[trend.direction]
            period_text = (
                f"{trend.period_start}至{trend.period_end}"
                if trend.period_start and trend.period_end
                else "最新可用比较期"
            )
            insights.append(Insight(
                insight_id=f"I-{index:03d}",
                title=f"{trend.entity or request.subject}：{trend.metric}{direction}",
                conclusion=(
                    f"{period_text}，{trend.metric}呈{direction}特征，"
                    f"方向一致率为{trend.monotonicity:.0%}。"
                ),
                significance="这是基于时间序列的描述性判断；业务含义需结合内容生成阶段的上下文解释。",
                confidence="high" if trend.observations >= 4 and trend.strength == "strong" else "medium",
                evidence_record_ids=trend.evidence_record_ids,
                related_trend_ids=[trend.trend_id],
            ))
        if not insights and metrics:
            metric = metrics[0]
            insights.append(Insight(
                insight_id="I-001",
                title=f"关键指标：{metric.name}",
                conclusion=f"{metric.entity or request.subject}的{metric.name}最新可用值为{metric.value:g}{metric.unit or ''}。",
                significance="该指标在规则评分中优先级较高，但目前不足以单独形成趋势判断。",
                confidence="medium",
                evidence_record_ids=metric.evidence_record_ids,
                related_metric_ids=[metric.metric_id],
            ))
        outline = [ContentSection(
            heading="核心数据发现",
            purpose="以可追溯证据呈现关键指标、趋势与异常，不扩展事实边界。",
            key_points=[item.title for item in insights[:5]] or ["当前数据不足以形成稳定洞察"],
            evidence_record_ids=list(dict.fromkeys(
                record_id for item in insights[:5] for record_id in item.evidence_record_ids
            )),
        )]
        return summary, insights, outline

    @staticmethod
    def _validate_semantic(
        response: dict[str, Any],
        *,
        allowed_record_ids: set[str],
        allowed_metric_ids: set[str],
        allowed_trend_ids: set[str],
        allowed_anomaly_ids: set[str],
        max_insights: int,
        fallback,
    ):
        fallback_summary, fallback_knowledge, fallback_insights, fallback_outline = fallback
        summary = str(response.get("executive_summary") or fallback_summary).strip()
        cat_map = {
            "financials": "financial", "finance": "financial", "companies": "company",
            "events": "event", "industries": "industry", "chains": "industry_chain",
            "macros": "macro",
        }
        valid_cats = {"industry", "company", "financial", "macro", "industry_chain", "event", "other"}

        insights: list[Insight] = []
        for raw in response.get("insights", [])[:max_insights]:
            if isinstance(raw, dict):
                norm = dict(raw)
                if "insight_id" not in norm and "id" in norm:
                    norm["insight_id"] = str(norm["id"])
                if "insight_id" not in norm:
                    norm["insight_id"] = f"I-{len(insights)+1:03d}"
                if "evidence_record_ids" not in norm:
                    norm["evidence_record_ids"] = norm.get("evidence_ids") or norm.get("evidence") or []
                if isinstance(norm.get("evidence_record_ids"), str):
                    norm["evidence_record_ids"] = [norm["evidence_record_ids"]]
                conf = str(norm.get("confidence", "high")).lower()
                norm["confidence"] = conf if conf in {"low", "medium", "high"} else "high"
                if "title" not in norm:
                    norm["title"] = str(norm.get("name") or "深度分析洞察")
                if "conclusion" not in norm:
                    norm["conclusion"] = str(norm.get("summary") or norm.get("desc") or "")
                if "significance" not in norm:
                    norm["significance"] = "对产业发展与企业定位具有参考价值"
                raw = norm
            try:
                item = Insight.model_validate(raw)
            except ValidationError:
                continue
            item.evidence_record_ids = [item_id for item_id in item.evidence_record_ids if item_id in allowed_record_ids]
            item.related_metric_ids = [item_id for item_id in item.related_metric_ids if item_id in allowed_metric_ids]
            item.related_trend_ids = [item_id for item_id in item.related_trend_ids if item_id in allowed_trend_ids]
            item.related_anomaly_ids = [item_id for item_id in item.related_anomaly_ids if item_id in allowed_anomaly_ids]
            if item.evidence_record_ids:
                insights.append(item)

        knowledge_facts: list[KnowledgeFact] = []
        for raw in response.get("knowledge_facts", []):
            if isinstance(raw, dict):
                norm = dict(raw)
                if "fact_id" not in norm and "id" in norm:
                    norm["fact_id"] = str(norm["id"])
                if "fact_id" not in norm:
                    norm["fact_id"] = f"F-{len(knowledge_facts)+1:03d}"
                if "evidence_record_ids" not in norm:
                    norm["evidence_record_ids"] = norm.get("evidence_ids") or norm.get("evidence") or []
                if isinstance(norm.get("evidence_record_ids"), str):
                    norm["evidence_record_ids"] = [norm["evidence_record_ids"]]
                cat = str(norm.get("category", "other")).lower()
                norm["category"] = cat_map.get(cat, cat if cat in valid_cats else "other")
                conf = str(norm.get("confidence", "high")).lower()
                norm["confidence"] = conf if conf in {"low", "medium", "high"} else "high"
                if "subject" not in norm:
                    norm["subject"] = str(norm.get("entity") or norm.get("title") or "行业标的")
                if "predicate" not in norm:
                    norm["predicate"] = str(norm.get("metric") or norm.get("attribute") or "核心特征")
                if "object_summary" not in norm:
                    norm["object_summary"] = str(norm.get("value") or norm.get("summary") or norm.get("description") or "")
                raw = norm
            try:
                item = KnowledgeFact.model_validate(raw)
            except ValidationError:
                continue
            item.evidence_record_ids = [item_id for item_id in item.evidence_record_ids if item_id in allowed_record_ids]
            if item.evidence_record_ids:
                knowledge_facts.append(item)

        outline: list[ContentSection] = []
        for raw in response.get("content_outline", []):
            if isinstance(raw, dict):
                norm = dict(raw)
                if "evidence_record_ids" not in norm:
                    norm["evidence_record_ids"] = norm.get("evidence_ids") or norm.get("evidence") or []
                if isinstance(norm.get("evidence_record_ids"), str):
                    norm["evidence_record_ids"] = [norm["evidence_record_ids"]]
                raw = norm
            try:
                item = ContentSection.model_validate(raw)
            except ValidationError:
                continue
            item.evidence_record_ids = [item_id for item_id in item.evidence_record_ids if item_id in allowed_record_ids]
            if item.evidence_record_ids:
                outline.append(item)
        return (
            summary,
            knowledge_facts or fallback_knowledge,
            insights or fallback_insights,
            outline or fallback_outline,
        )

    @staticmethod
    def _save(
        artifact_dir: Path | None,
        request: AnalysisRequest,
        dataset: StructuredResearchDataset,
        report: InterpretationReport,
    ) -> None:
        if artifact_dir is None:
            return
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "request.json").write_text(request.model_dump_json(indent=2), encoding="utf-8")
        (artifact_dir / "input_dataset.json").write_text(dataset.model_dump_json(indent=2), encoding="utf-8")
        (artifact_dir / "interpretation_report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
        skill_dir = artifact_dir / "skills"
        skill_dir.mkdir(exist_ok=True)
        for result in report.skill_results:
            (skill_dir / f"{result.task_id}.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
        (artifact_dir / "events.jsonl").write_text(
            "\n".join(item.model_dump_json() for item in report.execution_trace) + "\n",
            encoding="utf-8",
        )
