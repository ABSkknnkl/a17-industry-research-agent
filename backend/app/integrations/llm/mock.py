"""Deterministic LLM substitute for local development and tests."""

import json

from app.schemas.analysis import (
    AnalysisClaim,
    AnalysisDraft,
    ChartCandidate,
    DimensionAnalysis,
    ScenarioAnalysis,
    ValidationCard,
)
from app.schemas.chapter import ChapterDraftLoose, LooseParagraph, LooseSection


class MockAnalysisModel:
    model_name = "mock-financial-analysis"

    async def generate_analysis(
        self,
        *,
        system_prompt: str,
        runtime_prompt: str,
    ) -> AnalysisDraft:
        del system_prompt
        payload = json.loads(runtime_prompt)
        request = payload["analysis_request"]
        evidence = request["evidence_items"]
        first = evidence[0]
        evidence_id = first["evidence_id"]
        metric = first["metric_name"]
        value = first["value"]
        unit = first.get("unit") or ""

        claim = AnalysisClaim(
            claim_id="C-001",
            claim_type="fact",
            text=f"{metric}为{value}{unit}，该事实仅用于行业研究。",
            evidence_ids=[evidence_id],
            confidence="medium",
            uncertainty="当前测试数据仅覆盖一个指标，不能据此确认完整行业趋势。",
        )
        scenarios = [
            ScenarioAnalysis(
                name=name,
                assumptions=["现有证据口径保持不变"],
                triggers=["后续同口径指标发生可观测变化"],
                transmission_path="指标变化 → 行业供需判断更新 → 研究结论重估",
                evidence_ids=[evidence_id],
                disconfirming_conditions=["后续权威数据与当前证据方向冲突"],
                monitoring_indicators=[metric],
            )
            for name in ("base", "upside", "downside")
        ]
        return AnalysisDraft(
            headline=f"{request['industry_topic']}测试分析已形成可追溯事实底座。",
            overall_confidence="medium",
            financial_quality="differences_pending_verification",
            claims=[claim],
            dimensions=[
                DimensionAnalysis(
                    name=name,
                    summary=(
                        "当前仅验证结构化分析链路；除增长事实外，" "其余维度均需更多独立证据。"
                    ),
                    claim_ids=[claim.claim_id] if name == "growth" else [],
                )
                for name in (
                    "competition",
                    "growth",
                    "macro_policy",
                    "industry_chain",
                    "risk",
                )
            ],
            validation_cards=[
                ValidationCard(
                    name=name,
                    status="pending_verification",
                    summary="当前测试证据不足，校验结论待补充数据。",
                    evidence_ids=[evidence_id],
                )
                for name in (
                    "scope_comparability",
                    "financial_quality",
                    "valuation_expectation",
                )
            ],
            scenarios=scenarios,
            risks=["证据数量有限，结果不构成投资建议。"],
            chart_candidates=[
                ChartCandidate(
                    title=metric,
                    chart_type="bar",
                    evidence_ids=[evidence_id],
                )
            ],
        )


class MockChapterWritingModel:
    """Deterministic chapter generator used by tests and local demos."""

    model_name = "mock-chapter-writer"

    async def generate_chapter(
        self,
        *,
        system_prompt: str,
        runtime_prompt: str,
    ) -> ChapterDraftLoose:
        del system_prompt
        payload = json.loads(runtime_prompt)
        chapter_config = payload["chapter_config"]
        claims = payload.get("allowed_claims", [])
        ready_charts = payload.get("available_charts", [])
        claim_ids = list(dict.fromkeys(claim["claim_id"] for claim in claims))
        evidence_ids = list(
            dict.fromkeys(
                evidence_id for claim in claims for evidence_id in claim.get("evidence_ids", [])
            )
        )
        chart_ids = list(dict.fromkeys(chart["chart_id"] for chart in ready_charts))
        sections: list[LooseSection] = []

        for section_index, section in enumerate(chapter_config["sections"], start=1):
            if claims:
                claim = claims[(section_index - 1) % len(claims)]
                paragraph = LooseParagraph(
                    paragraph_id=(
                        f"P-{chapter_config['chapter_id'].removeprefix('CH-')}-"
                        f"{section_index:02d}-01"
                    ),
                    kind="analysis",
                    text=f"{claim['text']}限制条件：{claim['uncertainty']}",
                    claim_ids=[claim["claim_id"]],
                    evidence_ids=claim["evidence_ids"],
                )
                key_points = [claim["text"]]
                uncertainties = [claim["uncertainty"]]
            else:
                paragraph = LooseParagraph(
                    paragraph_id=(
                        f"P-{chapter_config['chapter_id'].removeprefix('CH-')}-"
                        f"{section_index:02d}-01"
                    ),
                    kind="methodology",
                    text="当前没有可用结论，本节仅保留研究边界。",
                )
                key_points = ["当前证据待补充"]
                uncertainties = ["缺少当前章节可用的结论"]

            sections.append(
                LooseSection(
                    section_id=section["section_id"],
                    title=section["title"],
                    purpose=section["purpose"],
                    key_points=key_points,
                    paragraphs=[paragraph],
                    chart_ids=chart_ids if section_index == 1 else [],
                    uncertainties=uncertainties,
                )
            )

        return ChapterDraftLoose(
            chapter_id=chapter_config["chapter_id"],
            title=chapter_config["title"],
            summary=(
                "本章仅使用已提供的可追溯结论。" if claims else "当前证据不足，本章仅保留研究边界。"
            ),
            sections=sections,
            claim_ids=claim_ids,
            evidence_ids=evidence_ids,
            chart_ids=chart_ids,
            missing_inputs=[] if claims else ["需补充当前章节的结论与证据"],
            revision=int(payload.get("revision", 1)),
        )
