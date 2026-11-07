"""v3 接线回归测试：模型生成指标验收需求（metric_requirements）的解析/校验/融合/验收闭环。

对应方案 output/指标识别与意图解析方案_v3_20261003.md：
- 验收标准由模型生成，代码只做白名单/格式校验（算术，非决策）；
- 校验不过的条目退化为不参与验收并记录原因；
- 模型需求排在基线之前，反馈循环优先逼问；
- 库外指标（如"获批创新药数量"）不依赖任何代码词典。
"""

import asyncio
from datetime import date
from pathlib import Path

from data_fetcher.agent import DataFetcherAgent
from data_fetcher.config import Settings
from data_fetcher.models import (
    Domain,
    ResearchRecord,
    ResearchRequest,
    ResearchRequirement,
    SourceRef,
    StructuredResearchDataset,
)
from data_fetcher.skillhub import SkillHub


def _baseline() -> list[ResearchRequirement]:
    return [
        ResearchRequirement(
            requirement_id=f"domain_{d.value}", label=f"{d.value} 核心数据", domain=d
        )
        for d in Domain
    ] + [
        ResearchRequirement(
            requirement_id="leader_identification", label="龙头", domain=Domain.COMPANIES
        ),
    ]


def _parse(response: dict):
    return DataFetcherAgent._parse_metric_requirements(response, _baseline())


# ---------- 解析与白名单校验 ----------


def test_parse_valid_metric_requirement():
    accepted, rejected = _parse({
        "metric_requirements": [
            {
                "requirement_id": "market_scale_series",
                "label": "2021-2025 年市场规模年度序列",
                "metric_terms": ["市场规模", "行业规模", "市场空间"],
                "domain": "industry",
                "time_range": "2021-2025",
                "min_records": 3,
                "requires_period_end": True,
                "reasoning": "用户明确询问各年市场规模",
            }
        ]
    })
    assert rejected == []
    assert len(accepted) == 1
    req = accepted[0]
    assert req.requirement_id == "market_scale_series"
    assert req.domain == Domain.INDUSTRY
    assert req.hard is True
    assert req.min_records == 3
    assert req.requires_period_end is True
    assert req.expected_metric_groups == [["市场规模", "行业规模", "市场空间"]]
    # 模型决定路由：代码不得替它指定 acceptable_skill_ids
    assert req.acceptable_skill_ids == []


def test_parse_non_list_is_ignored():
    accepted, rejected = _parse({"metric_requirements": "市场规模"})
    assert accepted == []
    assert rejected and "不是数组" in rejected[0]


def test_parse_rejects_out_of_whitelist_domain():
    accepted, rejected = _parse({
        "metric_requirements": [
            {
                "requirement_id": "bad_domain",
                "label": "某指标",
                "metric_terms": ["某指标"],
                "domain": "cryptocurrency",
            }
        ]
    })
    assert accepted == []
    assert any("白名单" in r for r in rejected)


def test_parse_rejects_empty_terms_and_label():
    accepted, rejected = _parse({
        "metric_requirements": [
            {"requirement_id": "no_terms", "label": "有标签没指标词", "domain": "news", "metric_terms": []},
            {"requirement_id": "no_label", "label": " ", "domain": "news", "metric_terms": ["x"]},
        ]
    })
    assert accepted == []
    assert any("metric_terms 为空" in r for r in rejected)
    assert any("label 为空" in r for r in rejected)


def test_parse_rejects_id_collision_with_baseline():
    accepted, rejected = _parse({
        "metric_requirements": [
            {
                "requirement_id": "leader_identification",
                "label": "撞基线 ID",
                "metric_terms": ["龙头"],
                "domain": "companies",
            }
        ]
    })
    assert accepted == []
    assert any("重复" in r for r in rejected)


def test_parse_rejects_malformed_id():
    accepted, rejected = _parse({
        "metric_requirements": [
            {
                "requirement_id": "市场规模序列",  # 契约 pattern 只允许 ASCII
                "label": "中文 ID",
                "metric_terms": ["市场规模"],
                "domain": "industry",
            }
        ]
    })
    assert accepted == []
    assert any("契约校验失败" in r for r in rejected)


def test_parse_dedupes_terms_and_accepts_string_terms():
    accepted, rejected = _parse({
        "metric_requirements": [
            {
                "requirement_id": "sales_peak",
                "label": "商业化销售峰值",
                "metric_terms": "销售峰值",
                "domain": "financials",
            }
        ]
    })
    assert rejected == []
    assert accepted[0].expected_metric_groups == [["销售峰值"]]
    assert accepted[0].min_records == 1


# ---------- _understand 接线（断点 A/B）----------


class _IntentLLM:
    is_available = True

    def __init__(self, intent_payload: dict):
        self.intent_payload = intent_payload

    async def generate_json(self, system_prompt, user_prompt):
        return self.intent_payload


def _agent_with_intent(payload: dict) -> DataFetcherAgent:
    return DataFetcherAgent(
        llm=_IntentLLM(payload),
        skillhub=SkillHub(gateway=None),
        settings=Settings(output_dir=Path("output")),
    )


def test_understand_merges_model_requirements_ahead_of_baseline():
    agent = _agent_with_intent({
        "industry": "创新药",
        "focus_points": ["获批数量", "销售峰值"],
        "data_requirements": ["客观数据"],
        "metric_requirements": [
            {
                "requirement_id": "approved_drug_count",
                "label": "近三年国内获批创新药数量（年度计数）",
                "metric_terms": ["获批", "批准", "创新药", "获批数量"],
                "domain": "news",
                "min_records": 3,
                "reasoning": "用户问年度计数",
            }
        ],
    })
    objective = asyncio.run(agent._understand(ResearchRequest(
        industry="创新药",
        focus_points=["获批数量", "销售峰值"],
        data_requirements=["客观数据"],
        as_of=date(2026, 10, 3),
    )))
    # 模型需求排在基线之前
    assert objective.requirements[0].requirement_id == "approved_drug_count"
    assert {r.requirement_id for r in objective.requirements} >= {
        "approved_drug_count", "domain_industry", "domain_news"
    }
    # 模型理解不再被丢弃（断点 B）
    assert [r.requirement_id for r in objective.model_requirements] == ["approved_drug_count"]
    assert "近三年国内获批创新药数量（年度计数）" in objective.data_requirements
    assert objective.rejected_metric_requirements == []


def test_understand_surfaces_rejected_items():
    agent = _agent_with_intent({
        "industry": "创新药",
        "metric_requirements": [
            {"requirement_id": "ok_one", "label": "合法需求", "metric_terms": ["获批"], "domain": "news"},
            {"requirement_id": "bad_one", "label": "非法领域", "metric_terms": ["x"], "domain": "mars"},
        ],
    })
    objective = asyncio.run(agent._understand(ResearchRequest(industry="创新药", as_of=date(2026, 10, 3))))
    assert [r.requirement_id for r in objective.model_requirements] == ["ok_one"]
    assert len(objective.rejected_metric_requirements) == 1
    assert "白名单" in objective.rejected_metric_requirements[0]


def test_understand_tolerates_missing_metric_requirements():
    agent = _agent_with_intent({"industry": "低空经济", "focus_points": ["产业链"]})
    objective = asyncio.run(agent._understand(ResearchRequest(industry="低空经济", as_of=date(2026, 10, 3))))
    assert objective.model_requirements == []
    assert objective.rejected_metric_requirements == []
    # 基线保底不受影响
    assert any(r.requirement_id.startswith("domain_") for r in objective.requirements)


# ---------- AB-2/S01 明确点名样本（含单公司）----------


def test_understand_single_named_company_enters_comparison_entities():
    """AB-2/S01：单一明确公司只写在问题里、结构化名单为空时，仍进入固定样本约束。

    原缺陷（§4.4）：问题文本推断 explicit 需要至少两个识别到的公司，单一点名
    不会进入 comparison_entities，财务样本失去固定名单约束。
    """
    agent = _agent_with_intent({
        "industry": "动力电池",
        "must_include_entities": ["宁德时代"],  # 模型识别出的目标公司
    })
    objective = asyncio.run(agent._understand(ResearchRequest(
        industry="动力电池",
        focus_points=["分析宁德时代2025年营业收入与毛利率"],
        must_include_entities=[],  # 结构化名单为空
        as_of=date(2026, 11, 7),
    )))
    assert objective.comparison_entities == ["宁德时代"]
    assert "宁德时代" in objective.must_include_entities


def test_understand_model_concept_expansion_does_not_enter_sample():
    """AB-2/S01：模型扩写的概念股（未出现在问题文本）不得改变研究样本。"""
    agent = _agent_with_intent({
        "industry": "动力电池",
        "must_include_entities": ["宁德时代", "优刻得", "寒武纪"],  # 模型扩写名单
    })
    objective = asyncio.run(agent._understand(ResearchRequest(
        industry="动力电池",
        focus_points=["分析宁德时代2025年营业收入"],  # 问题只点名宁德时代
        must_include_entities=[],
        as_of=date(2026, 11, 7),
    )))
    # 固定样本只含问题文本中明确点名的公司，模型扩写被过滤
    assert objective.comparison_entities == ["宁德时代"]
    assert "优刻得" not in objective.comparison_entities
    assert "寒武纪" not in objective.must_include_entities


def test_understand_structured_list_takes_priority_over_model():
    """AB-2/S01：用户给了结构化名单时，模型不得扩写或替换研究样本。"""
    agent = _agent_with_intent({
        "industry": "白酒",
        "must_include_entities": ["贵州茅台", "五粮液", "洋河股份"],  # 模型想扩写
    })
    objective = asyncio.run(agent._understand(ResearchRequest(
        industry="白酒",
        focus_points=["比较贵州茅台和五粮液2025年营业收入"],
        must_include_entities=["贵州茅台", "五粮液"],  # 用户结构化名单
        as_of=date(2026, 11, 7),
    )))
    assert objective.comparison_entities == ["贵州茅台", "五粮液"]
    assert "洋河股份" not in objective.must_include_entities


# ---------- 验收闭环（库外指标，不依赖代码词典）----------


def _news_record(record_id: str, metric: str) -> ResearchRecord:
    return ResearchRecord(
        record_id=record_id,
        domain=Domain.NEWS,
        metric=metric,
        value="1",
        source=SourceRef(
            task_id="t1",
            skill_id="news-search",
            skill_version="1.0.0",
            query="创新药 获批",
            trace_id="trace-1",
            retrieved_at=date(2026, 10, 3).isoformat() + "T00:00:00+00:00",
        ),
    )


def test_coverage_passes_out_of_dictionary_metric_when_data_matches():
    """"获批创新药数量"不在任何代码词典里：验收只看模型给的指标词是否命中。"""
    req = ResearchRequirement(
        requirement_id="approved_drug_count",
        label="近三年国内获批创新药数量（年度计数）",
        domain=Domain.NEWS,
        min_records=2,
        expected_metric_groups=[["获批", "批准", "创新药"]],
    )
    dataset = StructuredResearchDataset(news=[
        _news_record("r1", "2024年创新药获批数量"),
        _news_record("r2", "2025年创新药批准上市数量"),
    ])
    cov = DataFetcherAgent._evaluate_requirement(dataset, req)
    assert cov.passed is True
    assert cov.missing == []


def test_coverage_fails_out_of_dictionary_metric_without_data():
    req = ResearchRequirement(
        requirement_id="approved_drug_count",
        label="近三年国内获批创新药数量（年度计数）",
        domain=Domain.NEWS,
        min_records=2,
        expected_metric_groups=[["获批", "批准", "创新药"]],
    )
    dataset = StructuredResearchDataset(news=[_news_record("r1", "行业动态")])
    cov = DataFetcherAgent._evaluate_requirement(dataset, req)
    assert cov.passed is False
    assert any("至少需要 2 条" in m for m in cov.missing)
    assert any("缺少指标组" in m for m in cov.missing)


# ---------- 端到端：run 结果携带模型需求 ----------


class _EndToEndLLM:
    is_available = True

    def __init__(self):
        self.calls = 0

    async def generate_json(self, system_prompt, user_prompt):
        self.calls += 1
        if self.calls == 1:
            return {
                "industry": "动力电池",
                "focus_points": ["市场规模"],
                "metric_requirements": [
                    {
                        "requirement_id": "market_scale_series",
                        "label": "2021-2025 年市场规模年度序列",
                        "metric_terms": ["市场规模", "行业规模"],
                        "domain": "industry",
                        "min_records": 1,
                    }
                ],
            }
        return {"decision": "stop", "assessment": "指标不可得，如实汇报", "tasks": []}


class _EmptyGateway:
    async def call(self, spec, arguments, *, call_type, trace_id):
        return {"datas": []}


def test_run_result_carries_model_requirements_and_trace():
    agent = DataFetcherAgent(
        llm=_EndToEndLLM(),
        skillhub=SkillHub(gateway=_EmptyGateway(), retry_backoff_seconds=0),
        settings=Settings(output_dir=Path("output")),
    )
    result = asyncio.run(agent.run(ResearchRequest(
        industry="动力电池",
        focus_points=["市场规模"],
        max_iterations=2,
        as_of=date(2026, 10, 3),
    ), save_artifacts=False))
    assert [r.requirement_id for r in result.model_requirements] == ["market_scale_series"]
    ready = next(e for e in result.execution_trace if e.event == "objective_ready")
    assert ready.details["model_requirements"] == ["market_scale_series"]
    assert ready.details["rejected_metric_requirements"] == []
    # 模型需求进入验收：空数据下该条目必然未通过并出现在终态 coverage 中
    cov = next(
        c for c in result.coverage.requirement_coverage
        if c.requirement_id == "market_scale_series"
    )
    assert cov.passed is False


def test_focus_keeps_separate_macro_and_company_year_windows():
    import json

    case_path = Path(__file__).resolve().parents[3] / "eval/cases/research_report_quality.json"
    cases = json.loads(case_path.read_text())
    case = next(c for c in cases if c["id"] == "pv-1")
    inputs = case["request"]["input_data"]
    expected = case["expected"]
    request = ResearchRequest(
        industry=inputs["industry_topic"], as_of=inputs["research_as_of"],
        focus_points=inputs["focus_questions"], must_include_entities=expected["companies"],
    )
    objective = asyncio.run(_agent_with_intent({})._understand(request))
    annual = [r for r in objective.requirements if r.requirement_id.startswith("annual_")]
    assert {p.year for r in annual if r.domain == Domain.FINANCIALS for p in r.period_ends} == {2023, 2024, 2025}
    assert {p.year for r in annual if r.domain == Domain.INDUSTRY for p in r.period_ends} == {2021, 2022, 2023, 2024, 2025}

    fixture_path = case_path.parents[2] / "backend/tests/fixtures/research_report_quality.json"
    fixture = json.loads(fixture_path.read_text())
    source = {r["record_id"]: r for r in fixture["financials"]}
    mapping = {"R-MT-25": "通威股份", "R-FJ-25-LATE": "隆基绿能", "R-MT-26-YTD": "通威股份"}
    records = [
        ResearchRecord.model_validate({**source[rid], "entity_name": name, "entity_code": None})
        for rid, name in mapping.items()
    ]
    ds = StructuredResearchDataset(research_as_of=request.as_of, financials=records)
    requirements = {
        (r.entity_names[0], r.period_ends[0].year): r for r in annual
        if r.domain == Domain.FINANCIALS and r.metric_families == ["revenue"]
    }
    assert DataFetcherAgent._evaluate_requirement(ds, requirements["通威股份", 2025]).passed
    assert not DataFetcherAgent._evaluate_requirement(ds, requirements["通威股份", 2024]).passed
    late = DataFetcherAgent._evaluate_requirement(ds, requirements["隆基绿能", 2025])
    assert not late.passed and "after_research_cutoff" in late.rejected_evidence["R-FJ-25-LATE"]


def test_yoy_uses_prior_year_as_a_calculation_baseline():
    request = ResearchRequest(industry="白酒", focus_points=["2023—2025年营业收入，请展示同比。"])
    rows = DataFetcherAgent._annual_financial_requirements(request, ["贵州茅台"])
    assert {r.period_ends[0].year for r in rows if not r.comparison_baseline} == {2023, 2024, 2025}
    assert {r.period_ends[0].year for r in rows if r.comparison_baseline} == {2022}
