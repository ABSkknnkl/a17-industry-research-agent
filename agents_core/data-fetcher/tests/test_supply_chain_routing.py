"""A1 供应链取数意图路由测试（2026-10-07）。

- chain_structure 触发词从「产业链」扩到 供应商/客户/合作伙伴/上下游/配套，
  可接受技能扩为「公告+研报+新闻」三检索并集；
- 新增 supply_chain_relations 需求（供应商/客户/合作伙伴类查询）；
- PLANNER 提示词包含实体锚定的三检索任务指导。
"""
from data_fetcher.agent import PLANNER_SYSTEM_PROMPT, DataFetcherAgent
from data_fetcher.models import Domain, ResearchRequest


def _baseline(focus_points: list[str], data_requirements: list[str] | None = None):
    request = ResearchRequest(
        industry="测试行业",
        focus_points=focus_points,
        data_requirements=data_requirements or [],
    )
    return DataFetcherAgent._baseline_requirements(request, list(Domain))


def _by_id(reqs, rid):
    return next((r for r in reqs if r.requirement_id == rid), None)


# ── chain_structure 触发词扩展 ─────────────────────────────────────────────

def test_chain_structure_triggered_by_supply_chain_terms():
    for term in ("供应链", "上下游", "供应商", "客户", "合作伙伴", "配套"):
        reqs = _baseline([f"分析英伟达{term}格局"])
        assert _by_id(reqs, "chain_structure") is not None, f"触发词 {term} 未命中 chain_structure"


def test_chain_structure_accepts_three_search_skills():
    reqs = _baseline(["低空经济产业链全景"])
    req = _by_id(reqs, "chain_structure")
    assert req is not None
    for skill in ("announcement-search", "report-search", "news-search"):
        assert skill in req.acceptable_skill_ids, f"chain_structure 缺少 {skill}"
    # 原有技能保留（并集不是替代）
    assert "hithink-business-query" in req.acceptable_skill_ids


def test_chain_structure_not_triggered_by_unrelated_query():
    reqs = _baseline(["公司近三年营收与净利润"])
    assert _by_id(reqs, "chain_structure") is None


# ── supply_chain_relations 新需求 ───────────────────────────────────────────

def test_supply_chain_relations_added_for_supplier_query():
    reqs = _baseline(["英伟达供应商名单"])
    req = _by_id(reqs, "supply_chain_relations")
    assert req is not None
    assert req.domain == Domain.INDUSTRY_CHAIN
    assert set(req.acceptable_skill_ids) == {"announcement-search", "report-search", "news-search"}


def test_supply_chain_relations_added_for_partner_query():
    reqs = _baseline(["小米手机合作伙伴与代工厂"])
    assert _by_id(reqs, "supply_chain_relations") is not None


def test_supply_chain_relations_not_added_for_plain_chain_query():
    """只说「产业链」不提关系词时，不出 supply_chain_relations（避免过度取数）。"""
    reqs = _baseline(["低空经济产业链结构"])
    assert _by_id(reqs, "supply_chain_relations") is None
    assert _by_id(reqs, "chain_structure") is not None


# ── PLANNER 提示词包含三检索任务指导 ────────────────────────────────────────

def test_planner_prompt_contains_supply_chain_guidance():
    assert "供应链上下游关系" in PLANNER_SYSTEM_PROMPT
    assert "announcement-search" in PLANNER_SYSTEM_PROMPT
    assert "供应商 客户 合作伙伴" in PLANNER_SYSTEM_PROMPT
    assert "严禁用财务指标查询技能代替" in PLANNER_SYSTEM_PROMPT
