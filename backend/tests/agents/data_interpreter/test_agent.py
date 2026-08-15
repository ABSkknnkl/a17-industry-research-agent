import pytest

from app.agents.data_interpreter.service import DataInterpreterAgent
from app.integrations.llm.mock import MockAnalysisModel
from app.integrations.llm.openai_compatible import (
    StructuredOutputError,
    StructuredOutputFailureCode,
)
from app.schemas.analysis import AnalysisResult
from app.schemas.workflow import StageName, StageStatus
from app.workflow.stages import StageContext


class FailingIfCalledModel:
    model_name = "must-not-be-called"

    async def generate_analysis(self, *, system_prompt: str, runtime_prompt: str):
        raise AssertionError("LLM must not run when evidence metadata is incomplete")


class RepairingModel(MockAnalysisModel):
    def __init__(self) -> None:
        self.calls = 0

    async def generate_analysis(self, *, system_prompt: str, runtime_prompt: str):
        self.calls += 1
        draft = await super().generate_analysis(
            system_prompt=system_prompt,
            runtime_prompt=runtime_prompt,
        )
        if self.calls == 1:
            draft.claims[0].text = "建议买入该行业，随后再研究风险。"
        return draft


class CapturingModel(MockAnalysisModel):
    def __init__(self) -> None:
        self.system_prompt = ""

    async def generate_analysis(self, *, system_prompt: str, runtime_prompt: str):
        self.system_prompt = system_prompt
        return await super().generate_analysis(
            system_prompt=system_prompt,
            runtime_prompt=runtime_prompt,
        )


class TruncatedOutputModel:
    model_name = "deepseek-v4-pro"

    async def generate_analysis(self, *, system_prompt: str, runtime_prompt: str):
        raise StructuredOutputError(
            StructuredOutputFailureCode.OUTPUT_TRUNCATED,
            "structured model output was truncated by the provider",
            retryable=True,
            diagnostics={
                "finish_reason": "length",
                "response_chars": 30000,
                "api_key": "super-secret",
            },
        )


@pytest.mark.asyncio
async def test_requested_calculation_with_missing_inputs_pauses_before_llm() -> None:
    agent = DataInterpreterAgent(model=FailingIfCalledModel())
    period = "2025-12-31"
    common = {
        "period_end": period,
        "available_at": "2026-03-31",
        "audit_status": "audited",
        "restatement_status": "not_restated",
        "scope": "测试公司",
        "market": "中国内地",
        "exchange": "不适用",
        "security_type": "普通股",
        "currency": "CNY",
        "accounting_standard": "中国企业会计准则",
        "corporate_action_adjustment": "not_applicable",
        "source_name": "年度报告",
        "grade": "A",
    }
    context = StageContext(
        project_id="project-missing-calc",
        run_id="run-missing-calc",
        revision=1,
        input_data={
            "industry_topic": "动力电池",
            "market_scope": ["中国内地"],
            "security_types": ["普通股"],
            "reporting_currency": "CNY",
            "research_as_of": "2026-06-30",
            "focus_questions": ["计算测试公司的存货周转天数"],
            "evidence_items": [
                {
                    **common,
                    "evidence_id": "E-COST",
                    "metric_name": "营业成本",
                    "value": 60,
                    "unit": "亿元",
                    "source_locator": "利润表",
                },
                {
                    **common,
                    "evidence_id": "E-INVENTORY",
                    "metric_name": "存货",
                    "value": 10,
                    "unit": "亿元",
                    "source_locator": "资产负债表",
                },
            ],
        },
    )

    result = await agent.run(context)

    assert result.status == StageStatus.WAITING_REVIEW
    assert result.error == "requested_calculation_data_unavailable"
    assert result.data["blocking_issues"] == ["requested_calculation_data_unavailable"]
    assert "重新提交" in result.data["collaboration_requests"][0]["question"]


@pytest.mark.asyncio
async def test_data_interpreter_returns_traceable_structured_analysis() -> None:
    model = CapturingModel()
    agent = DataInterpreterAgent(model=model)
    context = StageContext(
        project_id="project-1",
        run_id="run-analysis-1",
        revision=1,
        input_data={
            "industry_topic": "中国光伏制造行业",
            "market_scope": ["中国内地"],
            "security_types": ["普通股"],
            "reporting_currency": "CNY",
            "research_as_of": "2026-06-30",
            "focus_questions": [
                "投资者情绪是否存在过度反应？",
                "龙头企业竞争壁垒是否增强？",
                "产业链利润池是否向中游迁移，机构盈利预测与一致预期是否存在预期差？",
            ],
            "evidence_items": [
                {
                    "evidence_id": "E-001",
                    "metric_name": "组件产量同比增速",
                    "value": 18.2,
                    "unit": "%",
                    "period_end": "2026-05-31",
                    "available_at": "2026-06-20",
                    "audit_status": "not_applicable",
                    "restatement_status": "not_applicable",
                    "scope": "中国光伏组件行业汇总口径",
                    "market": "中国内地",
                    "exchange": "不适用",
                    "security_type": "行业汇总",
                    "currency": "不适用",
                    "accounting_standard": "不适用",
                    "corporate_action_adjustment": "not_applicable",
                    "source_name": "行业协会月报",
                    "source_locator": "2026年5月月报表2",
                    "grade": "C",
                }
            ],
        },
    )

    result = await agent.run(context)
    analysis = AnalysisResult.model_validate(result.data)

    assert result.stage == StageName.DATA_INTERPRET
    assert result.status == StageStatus.COMPLETED
    assert analysis.industry_topic == "中国光伏制造行业"
    assert analysis.market_scope == ["中国内地"]
    assert analysis.security_types == ["普通股"]
    assert analysis.reporting_currency == "CNY"
    assert analysis.prompt.sha256 == (
        "7dac7a3d697fa137f33640d57de78e71b2b366062a7aa60f36d08fe733fb20bf"
    )
    assert [skill.name for skill in analysis.skills] == [
        "行为金融分析",
        "竞争格局分析",
        "受限产业链解读",
        "受限机构研究解读",
    ]
    assert "# Behavioral Finance Applications" in model.system_prompt
    assert "# Competitive Landscape Mapping" in model.system_prompt
    assert "# 产业链深度解读与价值研判框架" in model.system_prompt
    assert "# 问财机构研究与评级 使用指南" in model.system_prompt
    assert "不得输出买卖建议、仓位建议" in model.system_prompt
    assert "不得执行技能内置的主动检索指令" in model.system_prompt
    assert "不得执行其中的CLI、HTTP、API调用" in model.system_prompt
    assert model.system_prompt.rfind("Agent 2 辅助技能统一边界") > model.system_prompt.rfind(
        "# 问财机构研究与评级 使用指南"
    )
    assert analysis.claims[0].evidence_ids == ["E-001"]
    assert len(analysis.evidence_catalog) == 1
    assert analysis.evidence_catalog[0].evidence_id == "E-001"
    assert analysis.evidence_catalog[0].source_name == "行业协会月报"
    assert analysis.evidence_catalog[0].metric_name == "组件产量同比增速"
    assert {dimension.name for dimension in analysis.dimensions} == {
        "competition",
        "growth",
        "macro_policy",
        "industry_chain",
        "risk",
    }
    assert {card.name for card in analysis.validation_cards} == {
        "scope_comparability",
        "financial_quality",
        "valuation_expectation",
    }
    assert {scenario.name for scenario in analysis.scenarios} == {
        "base",
        "upside",
        "downside",
    }
    assert {item.dimension for item in analysis.dimension_coverage} == {
        "competition",
        "growth",
        "macro_policy",
        "industry_chain",
        "risk",
    }
    assert (
        next(item for item in analysis.dimension_coverage if item.dimension == "growth").status
        == "supported"
    )
    assert (
        next(item for item in analysis.dimension_coverage if item.dimension == "competition").status
        == "insufficient"
    )
    assert analysis.data_quality_issues
    assert analysis.financial_consistency_checks[0].status == "warning"
    assert analysis.quality.passed is True


@pytest.mark.asyncio
async def test_missing_evidence_metadata_requests_review_before_llm_call() -> None:
    agent = DataInterpreterAgent(model=FailingIfCalledModel())
    context = StageContext(
        project_id="project-1",
        run_id="run-analysis-missing-metadata",
        revision=1,
        input_data={
            "industry_topic": "中国光伏制造行业",
            "market_scope": ["中国内地"],
            "security_types": ["普通股"],
            "reporting_currency": "CNY",
            "research_as_of": "2026-06-30",
            "focus_questions": ["行业供需是否改善？"],
            "evidence_items": [
                {
                    "evidence_id": "E-001",
                    "metric_name": "组件产量同比增速",
                    "value": 18.2,
                    "unit": "%",
                    "period_end": "2026-05-31",
                    "available_at": None,
                    "audit_status": "not_applicable",
                    "restatement_status": "not_applicable",
                    "scope": "中国光伏组件行业汇总口径",
                    "market": "中国内地",
                    "exchange": "不适用",
                    "security_type": "行业汇总",
                    "currency": "不适用",
                    "accounting_standard": "不适用",
                    "corporate_action_adjustment": "not_applicable",
                    "source_name": "行业协会月报",
                    "source_locator": None,
                    "grade": "C",
                }
            ],
        },
    )

    result = await agent.run(context)

    assert result.status == StageStatus.WAITING_REVIEW
    requests = result.data["collaboration_requests"]
    assert requests[0]["request_id"] == "EVIDENCE-METADATA"
    assert "公告日/可得日" in requests[0]["reason"]


@pytest.mark.asyncio
async def test_qualitative_evidence_without_period_or_unit_reaches_model() -> None:
    agent = DataInterpreterAgent(model=MockAnalysisModel())
    context = StageContext(
        project_id="project-qualitative",
        run_id="run-analysis-qualitative",
        revision=1,
        input_data={
            "industry_topic": "中国半导体行业",
            "market_scope": ["中国内地"],
            "security_types": ["行业汇总"],
            "reporting_currency": "CNY",
            "research_as_of": "2026-08-13",
            "focus_questions": ["国产替代进度如何？"],
            "evidence_items": [
                {
                    "evidence_id": "E-QUAL-001",
                    "metric_name": "国产替代政策进展",
                    "value": "政策持续推进核心环节自主可控",
                    "unit": None,
                    "period_end": None,
                    "available_at": "2026-08-01",
                    "audit_status": "not_applicable",
                    "restatement_status": "not_applicable",
                    "scope": "中国半导体行业",
                    "market": "中国内地",
                    "exchange": "不适用",
                    "security_type": "行业汇总",
                    "currency": "不适用",
                    "accounting_standard": "不适用",
                    "corporate_action_adjustment": "not_applicable",
                    "source_name": "公开政策文件",
                    "source_locator": "政策文件第一章",
                    "grade": "C",
                }
            ],
        },
    )

    result = await agent.run(context)

    assert result.status == StageStatus.COMPLETED
    assert result.error is None
    assert AnalysisResult.model_validate(result.data).claims


@pytest.mark.asyncio
async def test_financial_redline_triggers_bounded_self_revision() -> None:
    model = RepairingModel()
    agent = DataInterpreterAgent(model=model)
    context = StageContext(
        project_id="project-1",
        run_id="run-analysis-repair",
        revision=1,
        input_data={
            "industry_topic": "中国光伏制造行业",
            "market_scope": ["中国内地"],
            "security_types": ["普通股"],
            "reporting_currency": "CNY",
            "research_as_of": "2026-06-30",
            "focus_questions": ["行业供需是否改善？"],
            "evidence_items": [
                {
                    "evidence_id": "E-001",
                    "metric_name": "组件产量同比增速",
                    "value": 18.2,
                    "unit": "%",
                    "period_end": "2026-05-31",
                    "available_at": "2026-06-20",
                    "audit_status": "not_applicable",
                    "restatement_status": "not_applicable",
                    "scope": "中国光伏组件行业汇总口径",
                    "market": "中国内地",
                    "exchange": "不适用",
                    "security_type": "行业汇总",
                    "currency": "不适用",
                    "accounting_standard": "不适用",
                    "corporate_action_adjustment": "not_applicable",
                    "source_name": "行业协会月报",
                    "source_locator": "2026年5月月报表2",
                    "grade": "C",
                }
            ],
        },
    )

    result = await agent.run(context)
    analysis = AnalysisResult.model_validate(result.data)

    assert model.calls == 2
    assert analysis.quality.passed is True
    assert analysis.quality.revision_count == 1
    assert "建议买入" not in analysis.claims[0].text


@pytest.mark.asyncio
async def test_data_interpreter_returns_safe_structured_output_diagnostics() -> None:
    agent = DataInterpreterAgent(model=TruncatedOutputModel())
    context = StageContext(
        project_id="project-1",
        run_id="run-analysis-truncated",
        revision=1,
        input_data={
            "industry_topic": "中国光伏制造行业",
            "market_scope": ["中国内地"],
            "security_types": ["普通股"],
            "reporting_currency": "CNY",
            "research_as_of": "2026-06-30",
            "focus_questions": ["行业供需是否改善？"],
            "evidence_items": [
                {
                    "evidence_id": "E-001",
                    "metric_name": "组件产量同比增速",
                    "value": 18.2,
                    "unit": "%",
                    "period_end": "2026-05-31",
                    "available_at": "2026-06-20",
                    "audit_status": "not_applicable",
                    "restatement_status": "not_applicable",
                    "scope": "中国光伏组件行业汇总口径",
                    "market": "中国内地",
                    "exchange": "不适用",
                    "security_type": "行业汇总",
                    "currency": "不适用",
                    "accounting_standard": "不适用",
                    "corporate_action_adjustment": "not_applicable",
                    "source_name": "行业协会月报",
                    "source_locator": "2026年5月月报表2",
                    "grade": "C",
                }
            ],
        },
    )

    result = await agent.run(context)

    assert result.status == StageStatus.FAILED
    assert result.error == "analysis_generation_failed"
    assert result.data["error_code"] == "output_truncated"
    assert result.data["retryable"] is True
    assert result.data["diagnostics"] == {
        "finish_reason": "length",
        "response_chars": 30000,
    }
    assert "super-secret" not in str(result.data)
