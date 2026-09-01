"""P0-6（2026-09-01 方案）回归：字段相关性校验与口径标签（治成因 D）。

背景：真实问财接口实测发现，`hithink_business_query` 查不到业务字段
（如"隆基绿能组件出货量"）时不返回空，而是**静默回退行情数据**（最
新价/涨跌幅/大单卖出量）——行数>0、能过既有质量门，Agent 2 会把"当
日行情"当成"查到了出货量"。这比空返回危险：空返回会被 data_gaps 捕
获披露，静默降级是拿假证据编真报告。

覆盖：
- `_field_relevance_check` 单元判定（纯行情行/合法场景不误伤）
- 口径标签（`_evidence_caliber`：行业级/公司级/None）
- planner 行业口径查询（公司名不进行业查询）
- service 端到端（方案回归用例 1：行情回退 → gap + 隔离 + 无伪证据）
"""

from datetime import date
from pathlib import Path

import pytest

from app.agents.data_fetcher.executor import RetrievalExecutor
from app.agents.data_fetcher.intent_merger import build_intent_plan
from app.agents.data_fetcher.normalizer import (
    _evidence_caliber,
    _field_relevance_check,
)
from app.agents.data_fetcher.planner import QueryPlanner
from app.agents.data_fetcher.service import DataFetcherAgent
from app.integrations.skillhub.mock import MockSkillHubClient
from app.integrations.skillhub.registry import create_skillhub_gateway
from app.schemas.acquisition import RequirementCoverage, SkillName, SkillPayload
from app.workflow.stages import StageContext

from tests.agents.data_fetcher.test_p0_routing_fix import (
    RecordingDecomposer,
    _entity,
    _metric,
    _p0_agent,
    _p0_context,
    _plan,
    _sub,
)


# ---------------------------------------------------------------------------
# _field_relevance_check 单元判定
# ---------------------------------------------------------------------------


def test_p06_field_relevance_check_detects_market_quote_fallback() -> None:
    """成因 D：BUSINESS 返回列全部为行情字段且请求指标非行情类 →
    判定 market_quote_fallback，绝不计为成功证据。"""
    quote_rows = [
        {
            "股票代码": "601012.SH",
            "股票简称": "隆基绿能",
            "最新价": 12.07,
            "最新涨跌幅": 0.0,
            "大单卖出量[20260901]": 6541932,
        }
    ]
    relevant, reason = _field_relevance_check(
        rows=quote_rows,
        requested_metrics=["出货量", "销量"],
        skill=SkillName.BUSINESS,
    )
    assert relevant is False
    assert reason == "market_quote_fallback"


def test_p06_field_relevance_check_passes_legitimate_cases() -> None:
    """合法场景不误伤：请求行情本身、INDUSTRY 技能、纯业务字段、
    业务+行情混合行（行级通过，行情列由字段级过滤剔除）。"""
    quote_rows = [
        {
            "股票代码": "601012.SH",
            "股票简称": "隆基绿能",
            "最新价": 12.07,
            "大单卖出量[20260901]": 6541932,
        }
    ]
    # 请求指标本身是行情类 → 合法返回。
    assert _field_relevance_check(
        rows=quote_rows,
        requested_metrics=["最新价"],
        skill=SkillName.BUSINESS,
    ) == (True, None)
    # INDUSTRY/MACRO 走宏观指标路径，校验不适用。
    assert _field_relevance_check(
        rows=quote_rows,
        requested_metrics=["产能"],
        skill=SkillName.INDUSTRY,
    ) == (True, None)
    # 纯业务字段 → 通过。
    assert _field_relevance_check(
        rows=[{"股票简称": "隆基绿能", "海外收入占比": 30.0}],
        requested_metrics=["海外收入占比"],
        skill=SkillName.BUSINESS,
    ) == (True, None)
    # 混合行（业务字段+行情列）→ 行级保留，字段级过滤交给 normalizer。
    assert _field_relevance_check(
        rows=[{"股票简称": "隆基绿能", "海外收入占比": 30.0, "最新价": 12.07}],
        requested_metrics=["海外收入占比"],
        skill=SkillName.BUSINESS,
    ) == (True, None)


def test_p06_field_relevance_check_covers_stock_selector() -> None:
    """2026-09-01 真实接口实测：STOCK_SELECTOR 查市场份额同样静默回退
    行情列（成交量/成交额/换手率冒充市场份额），必须同等拦截；
    而按换手率选股（请求指标本身是行情类）是合法用法，放行。"""
    quote_rows = [
        {
            "股票代码": "300750.SZ",
            "股票简称": "天合光能",
            "成交量": 6541932,
            "成交额": 120000000.0,
            "换手率": 1.2,
            "振幅": 2.1,
        }
    ]
    relevant, reason = _field_relevance_check(
        rows=quote_rows,
        requested_metrics=["市场份额", "市占率"],
        skill=SkillName.STOCK_SELECTOR,
    )
    assert relevant is False
    assert reason == "market_quote_fallback"
    # 请求指标本身是行情类（按换手率选股）→ 合法返回。
    assert _field_relevance_check(
        rows=quote_rows,
        requested_metrics=["换手率"],
        skill=SkillName.STOCK_SELECTOR,
    ) == (True, None)


# ---------------------------------------------------------------------------
# 口径标签
# ---------------------------------------------------------------------------


def test_p06_evidence_caliber_labels() -> None:
    """P0-6 配套：口径标签——行业口径技能/公司口径技能/定性技能(None)。"""
    assert _evidence_caliber(SkillName.INDUSTRY) == "industry_level"
    assert _evidence_caliber(SkillName.MACRO) == "industry_level"
    assert _evidence_caliber(SkillName.SECTOR) == "industry_level"
    assert _evidence_caliber(SkillName.FINANCE) == "company_level"
    assert _evidence_caliber(SkillName.BUSINESS) == "company_level"
    assert _evidence_caliber(SkillName.REPORT) is None


# ---------------------------------------------------------------------------
# planner：行业口径查询（公司级需求降级路径）
# ---------------------------------------------------------------------------


def test_p06_planner_builds_industry_caliber_query_for_company_shipment() -> None:
    """方案回归：公司级出货量需求降级为行业口径查询——查询携带
    行业主题与注册指标字段，绝不携带公司名（行业接口不认识公司名，
    带名只会空返回或触发行情回退）。"""
    question = "隆基绿能组件出货量？"
    intent_plan = _plan(
        question,
        [
            _sub(
                "SUB-LLM-01",
                "隆基绿能组件出货量",
                entities=[_entity("隆基绿能")],
                metrics=[_metric("出货量", "industry")],
                skills=[SkillName.INDUSTRY.value],
            ),
        ],
    )
    plan = QueryPlanner().build(
        industry_topic="光伏组件行业",
        market_scope=["中国内地"],
        research_as_of=date(2026, 8, 31),
        analysis_depth="standard",
        focus_questions=[question],
        research_brief={"focus_companies": ["隆基绿能"]},
        data_fetch_options={},
        review_feedback=None,
        intent_plans=[intent_plan],
    )
    industry_tasks = [
        task
        for task in plan.tasks
        if task.skill_name == SkillName.INDUSTRY and task.intent_requirement_id
    ]
    assert industry_tasks, "产业运营指标必须产生 INDUSTRY 行业口径查询"
    for task in industry_tasks:
        assert "隆基绿能" not in task.query, "公司名不得进入行业口径查询"
        assert "光伏组件行业" in task.query
        assert "出货量" in task.query
    # 行业口径任务不绑定公司实体（行业行没有公司实体列）。
    assert all(not task.target_entities for task in industry_tasks)


@pytest.mark.asyncio
async def test_p06_registry_routes_shipment_metrics_to_industry_skill() -> None:
    """注册修正：出货量/产能/产量经确定性解析锁定 INDUSTRY（行业口径），
    不再进 BUSINESS（公司口径查询会静默回退行情数据）。"""
    plan = await build_intent_plan(
        "隆基绿能组件出货量？",
        industry_topic="光伏组件行业",
        known_entities=["隆基绿能"],
        decomposer=None,
    )
    routed = {
        skill for sub in plan.sub_requirements for skill in sub.candidate_skills
    }
    assert SkillName.INDUSTRY in routed or not routed, (
        "确定性层出货量应锁定 INDUSTRY（或整段留澄清），绝不能锁 BUSINESS"
    )
    assert SkillName.BUSINESS not in routed


# ---------------------------------------------------------------------------
# service 端到端（方案 P0-6 回归用例 1）
# ---------------------------------------------------------------------------


class _QuoteFallbackClient(MockSkillHubClient):
    """成因 D 实测复现：BUSINESS 查不到业务字段时静默回退行情数据
    （行数>0、不报错）；海外收入占比可查（返回业务+行情混合行）。"""

    provider_mode = "live"

    async def execute(self, skill_name, args):
        if skill_name is SkillName.BUSINESS and "出货量" in args.query:
            return SkillPayload(
                skill_name=skill_name,
                query=args.query,
                rows=[
                    {
                        "股票代码": "601012.SH",
                        "股票简称": "隆基绿能",
                        "最新价": 12.07,
                        "最新涨跌幅": 0.0,
                        "大单卖出量[20260901]": 6541932,
                    }
                ],
                total_count=1,
                page=1,
                trace_id="0" * 64,
                raw_sha256="1" * 64,
                source_name="本地测试桩 hithink_business_query",
                source_locator="mock://quote-fallback",
            )
        if skill_name is SkillName.BUSINESS and "海外收入" in args.query:
            return SkillPayload(
                skill_name=skill_name,
                query=args.query,
                rows=[
                    {
                        "股票简称": "隆基绿能",
                        "海外收入占比": 30.0,
                        "最新价": 12.07,
                    }
                ],
                total_count=1,
                page=1,
                trace_id="2" * 64,
                raw_sha256="3" * 64,
                source_name="本地测试桩 hithink_business_query",
                source_locator="mock://mixed-business-quote",
            )
        return await super().execute(skill_name, args)


@pytest.mark.asyncio
async def test_p06_service_quarantines_market_quote_fallback_e2e(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """方案 P0-6 回归用例 1（成因 D）："隆基绿能组件出货量"经
    BUSINESS 查询返回纯行情行 → 必须标记 market_quote_fallback、
    不产生出货量证据、进 data_gaps/quarantined 如实披露；同问题
    海外收入占比返回混合行 → 业务字段保留为证据（company_level
    口径），行情列被剔除不产证据。"""
    monkeypatch.setenv("ROUTING_TELEMETRY_DIR", str(tmp_path / "telemetry"))
    monkeypatch.delenv("ROUTING_TELEMETRY_RAW_TEXT", raising=False)
    client = _QuoteFallbackClient()
    question = "隆基绿能海外收入占比与组件出货量？"
    agent = _p0_agent(
        client,
        intent_decomposer=RecordingDecomposer(
            _plan(
                question,
                [
                    _sub(
                        "SUB-LLM-01",
                        "隆基绿能海外收入占比",
                        entities=[_entity("隆基绿能")],
                        metrics=[_metric("海外收入占比", "business")],
                        skills=[SkillName.BUSINESS.value],
                    ),
                    _sub(
                        "SUB-LLM-02",
                        "隆基绿能组件出货量",
                        entities=[_entity("隆基绿能")],
                        metrics=[_metric("出货量", "business")],
                        skills=[SkillName.BUSINESS.value],
                    ),
                ],
            )
        ),
    )
    context = _p0_context(
        run_id="run-p0-quote-fallback",
        focus_questions=[question],
        focus_companies=["隆基绿能"],
        metrics=[],
    )

    result = await agent.run(context)

    # 出货量需求按缺口披露，绝不拿行情数据冒充成功证据。
    assert result.error == "required_data_unavailable"
    gaps = result.data["data_gaps"]
    assert any(
        gap.get("reason_code") == "market_quote_fallback" for gap in gaps
    ), "行情回退必须写入 data_gaps 披露"
    quarantined = result.data["quarantined_records"]
    assert any(
        record.get("reason_code") == "market_quote_fallback"
        for record in quarantined
    ), "行情回退行必须进隔离区，不得进入证据池"
    metrics_in_evidence = {
        item.get("metric_name") for item in result.data["evidence_items"]
    }
    assert not any(
        "出货量" in str(name) for name in metrics_in_evidence
    ), "不得产生出货量伪证据"
    assert not any(
        str(name) in {"最新价", "最新涨跌幅"} or "大单卖出量" in str(name)
        for name in metrics_in_evidence
    ), "行情字段不得混进证据（混合行中的行情列同样剔除）"
    # 混合行业务字段保留，并带公司级口径标签。
    overseas = [
        item
        for item in result.data["evidence_items"]
        if "海外收入" in str(item.get("metric_name"))
    ]
    assert overseas, "混合行中的业务字段必须保留为证据"
    assert all(
        item.get("caliber") == "company_level" for item in overseas
    ), "BUSINESS 证据必须带公司级口径标签"
