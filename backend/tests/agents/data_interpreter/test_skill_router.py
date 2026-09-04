from app.agents.data_interpreter.skill_loader import load_supporting_skills
from app.agents.data_interpreter.skill_router import SupportingSkillRouter
from app.schemas.analysis import AnalysisRequest


def _request(*focus_questions: str) -> AnalysisRequest:
    return AnalysisRequest.model_validate(
        {
            "industry_topic": "全球新能源汽车行业",
            "market_scope": ["中国内地", "美国"],
            "security_types": ["普通股"],
            "reporting_currency": "CNY",
            "research_as_of": "2026-06-30",
            "focus_questions": list(focus_questions),
            "evidence_items": [
                {
                    "evidence_id": "E-001",
                    "metric_name": "行业收入同比增速",
                    "value": 12.0,
                    "unit": "%",
                    "period_end": "2026-03-31",
                    "available_at": "2026-05-01",
                    "audit_status": "not_applicable",
                    "restatement_status": "not_applicable",
                    "scope": "全球可比上市公司样本",
                    "market": "全球",
                    "exchange": "多市场",
                    "security_type": "普通股",
                    "currency": "CNY",
                    "accounting_standard": "mixed_reconciled",
                    "corporate_action_adjustment": "not_applicable",
                    "source_name": "测试数据",
                    "source_locator": "fixture:E-001",
                    "grade": "C",
                }
            ],
        }
    )


def test_router_selects_all_existing_domain_skills_for_matching_questions() -> None:
    router = SupportingSkillRouter(load_supporting_skills())

    selected = router.route(
        _request(
            "投资者情绪与成交量是否出现过度反应？",
            "龙头公司的市场份额和竞争壁垒是否增强？",
            "产业链利润池是否向中游迁移？",
        )
    )

    assert [skill.key for skill in selected] == [
        "behavioral_finance",
        "competitive_landscape",
        "restricted_industry_chain",
    ]


def test_router_uses_macro_method_for_interest_rate_transmission() -> None:
    router = SupportingSkillRouter(load_supporting_skills())

    selected = router.route(_request("利率变化如何影响行业收入增速？"))

    assert [skill.key for skill in selected] == ["macro_cycle"]


def test_router_selects_institutional_research_only_for_matching_evidence() -> None:
    router = SupportingSkillRouter(load_supporting_skills())
    request = _request("盈利预测和一致预期是否出现明显预期差？")

    selected = router.route(request)

    assert [skill.key for skill in selected] == ["institutional_research"]


def test_router_selects_financial_commodity_and_macro_methods_by_scope() -> None:
    router = SupportingSkillRouter(load_supporting_skills())

    selected = router.route(
        _request(
            "对目标公司进行三表勾稽、经营现金流和杜邦分析",
            "分析铜库存周期、期货升贴水和供需结构",
            "PMI、CPI和利率变化如何影响行业景气？",
        )
    )

    assert [skill.key for skill in selected] == [
        "financial_statement",
        "commodity_analysis",
        "macro_cycle",
    ]
