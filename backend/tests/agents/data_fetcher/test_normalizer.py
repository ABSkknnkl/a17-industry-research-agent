from dataclasses import replace
from datetime import date

import pytest

from app.agents.data_fetcher.executor import ExecutedTask
from app.agents.data_fetcher.normalizer import normalize_tasks
from app.schemas.acquisition import (
    SkillCallRecord,
    SkillName,
    SkillPayload,
    SkillQueryTask,
    SkillTier,
)


def _executed(row: dict[str, object]) -> ExecutedTask:
    task = SkillQueryTask(
        task_id="Q-01",
        skill_name=SkillName.FINANCE,
        tier=SkillTier.P0,
        research_dimension="finance",
        query="测试公司2025年年报营业收入",
        time_range="2025",
        market_scope=["中国内地"],
    )
    payload = SkillPayload(
        skill_name=SkillName.FINANCE,
        query=task.query,
        rows=[row],
        total_count=1,
        page=1,
        trace_id="trace-normalizer",
        raw_sha256="a" * 64,
        source_name="同花顺问财财务数据",
        source_locator="SkillHub:hithink-finance-query:trace",
    )
    record = SkillCallRecord(
        call_id="CALL-01",
        task_id=task.task_id,
        skill_name=task.skill_name,
        tier=task.tier,
        query=task.query,
        status="succeeded",
        row_count=1,
        pages_fetched=1,
        attempts=1,
    )
    return ExecutedTask(task=task, payloads=[payload], record=record)


def _executed_for_skill(
    skill: SkillName,
    row: dict[str, object],
    *,
    query: str,
    dimension: str,
    task_id: str,
) -> ExecutedTask:
    executed = _executed(row)
    task = executed.task.model_copy(
        update={
            "task_id": task_id,
            "skill_name": skill,
            "tier": SkillTier.P1,
            "research_dimension": dimension,
            "query": query,
        }
    )
    payload = executed.payloads[0].model_copy(
        update={
            "skill_name": skill,
            "query": query,
            "source_name": f"同花顺问财 {skill.value}",
            "source_locator": f"SkillHub:{skill.value}:trace",
        }
    )
    record = executed.record.model_copy(
        update={
            "task_id": task_id,
            "skill_name": skill,
            "tier": SkillTier.P1,
            "query": query,
        }
    )
    return ExecutedTask(task=task, payloads=[payload], record=record)


def _normalize_result(
    executed: list[ExecutedTask],
    *,
    industry_topic: str = "储能行业",
):
    return normalize_tasks(
        executed,
        industry_topic=industry_topic,
        market_scope=["中国内地"],
        security_types=["普通股"],
        reporting_currency="CNY",
        research_as_of=date(2026, 8, 11),
    )


def _normalize(row: dict[str, object]):
    evidence, _, _ = normalize_tasks(
        [_executed(row)],
        industry_topic="储能行业",
        market_scope=["中国内地"],
        security_types=["普通股"],
        reporting_currency="CNY",
        research_as_of=date(2026, 8, 11),
    )
    return next(item for item in evidence if item.metric_name == "营业收入")


def test_financial_period_and_publication_date_are_not_conflated() -> None:
    item = _normalize(
        {
            "股票简称": "测试公司",
            "报告期": "2025-12-31",
            "公告日期": "2026-03-31",
            "营业收入(亿元)": 320,
        }
    )

    assert item.period_end == date(2025, 12, 31)
    assert item.available_at == date(2026, 3, 31)


def test_missing_period_is_preserved_instead_of_fabricated() -> None:
    item = _normalize({"股票简称": "测试公司", "营业收入(亿元)": 320})

    assert item.period_end is None
    assert item.available_at == date(2026, 8, 11)


def test_publication_date_is_not_copied_into_missing_financial_period() -> None:
    item = _normalize({"股票简称": "测试公司", "公告日期": "2026-03-31", "营业收入(亿元)": 320})

    assert item.period_end is None
    assert item.available_at == date(2026, 3, 31)


def test_period_is_parsed_from_dynamic_provider_field_name() -> None:
    evidence, _, _ = normalize_tasks(
        [_executed({"股票简称": "测试公司", "净利润[20251231]": 32.0})],
        industry_topic="储能行业",
        market_scope=["中国内地"],
        security_types=["普通股"],
        reporting_currency="CNY",
        research_as_of=date(2026, 8, 11),
    )

    item = next(entry for entry in evidence if entry.metric_name == "净利润")
    assert item.period_end == date(2025, 12, 31)


def test_evidence_cap_keeps_all_sources_and_represents_later_skills() -> None:
    first = _executed(
        {
            "股票简称": "高字段公司",
            "报告期": "2025-12-31",
            **{f"指标{index}": index for index in range(220)},
        }
    )
    second = _executed(
        {
            "股票简称": "后续技能公司",
            "报告期": "2025-12-31",
            "后续技能指标": 42,
        }
    )
    second = replace(
        second,
        task=second.task.model_copy(update={"task_id": "Q-02", "skill_name": SkillName.BUSINESS}),
        payloads=[
            second.payloads[0].model_copy(
                update={
                    "skill_name": SkillName.BUSINESS,
                    "trace_id": "trace-later-skill",
                    "raw_sha256": "b" * 64,
                    "source_name": "同花顺问财经营数据",
                    "source_locator": "SkillHub:hithink-business-query:trace",
                }
            )
        ],
    )

    evidence, sources, _ = normalize_tasks(
        [first, second],
        industry_topic="储能行业",
        market_scope=["中国内地"],
        security_types=["普通股"],
        reporting_currency="CNY",
        research_as_of=date(2026, 8, 11),
    )

    assert len(evidence) <= 200
    assert len(sources) == 2
    assert any(item.metric_name == "后续技能指标" for item in evidence)


def test_cleaning_removes_html_invisible_text_and_missing_values() -> None:
    result = _normalize_result(
        [
            _executed(
                {
                    "股票简称": "<b> 测\u200b试公司 </b>",
                    "报告期": "2025-12-31",
                    "营业收入(亿元)": " 320 ",
                    "空字段1": "--",
                    "空字段2": "N/A",
                    "空字段3": None,
                }
            )
        ]
    )

    revenue = next(item for item in result.evidence if item.metric_name == "营业收入")
    assert revenue.scope == "测试公司"
    assert revenue.value == 32_000_000_000
    assert revenue.unit == "元"
    assert not any(item.metric_name.startswith("空字段") for item in result.evidence)


def test_metric_aliases_and_units_are_canonicalized_before_fusion() -> None:
    result = _normalize_result(
        [
            _executed(
                {
                    "股票简称": "测试公司",
                    "报告期": "2025-12-31",
                    "归属于母公司股东的净利润(亿元)": 3.2,
                    "销售毛利率(%)": 22.8,
                    "新增装机量(GW)": 2,
                }
            )
        ]
    )
    by_metric = {item.metric_name: item for item in result.evidence}

    assert by_metric["归母净利润"].value == 320_000_000
    assert by_metric["归母净利润"].unit == "元"
    assert by_metric["毛利率"].unit == "%"
    assert by_metric["新增装机量"].value == 2_000
    assert by_metric["新增装机量"].unit == "兆瓦"


def test_finance_provider_contract_supplies_units_when_dynamic_fields_omit_them() -> None:
    result = _normalize_result(
        [
            _executed(
                {
                    "股票简称": "宁德时代",
                    "报告期": "2025-12-31",
                    "营业收入[20251231]": 423_701_834_000,
                    "营业成本[20251231]": 312_383_297_000,
                    "营业收入同比增长率[20251231]": 17.0406,
                }
            )
        ],
        industry_topic="动力电池",
    )
    by_metric = {item.metric_name: item for item in result.evidence}

    assert by_metric["营业收入"].unit == "元"
    assert by_metric["营业成本"].unit == "元"
    assert by_metric["营业收入同比增长率"].unit == "%"


def test_duplicate_rows_across_pages_are_counted_once() -> None:
    executed = _executed({"股票简称": "测试公司", "报告期": "2025-12-31", "营业收入(亿元)": 320})
    second_page = executed.payloads[0].model_copy(
        update={"page": 2, "raw_sha256": "b" * 64, "trace_id": "trace-page-two"}
    )
    executed = replace(
        executed,
        payloads=[executed.payloads[0], second_page],
        record=executed.record.model_copy(update={"row_count": 2, "pages_fetched": 2}),
    )

    result = _normalize_result([executed])

    assert result.summary.raw_row_count == 2
    assert result.summary.unique_row_count == 1
    assert result.summary.clean_row_count == 1
    assert result.summary.duplicate_raw_row_count == 1


def test_relevance_filter_quarantines_mismatch_but_keeps_verified_cross_sector_company() -> None:
    mismatch = _executed(
        {
            "股票简称": "煤炭公司",
            "所属概念": "煤炭开采",
            "营业收入(亿元)": 10,
        }
    )
    verified = _executed(
        {
            "股票简称": "鄂尔多斯",
            "所属概念": "光伏硅料、煤炭",
            "销售毛利率(%)": 22.88,
        }
    )
    verified = replace(
        verified,
        task=verified.task.model_copy(update={"task_id": "Q-02"}),
        payloads=[
            verified.payloads[0].model_copy(
                update={"raw_sha256": "c" * 64, "trace_id": "trace-verified"}
            )
        ],
    )

    result = _normalize_result([mismatch, verified], industry_topic="光伏行业")

    assert len(result.quarantined) == 1
    assert result.quarantined[0].entity == "煤炭公司"
    assert result.quarantined[0].reason_code == "topic_mismatch"
    assert any(item.scope == "鄂尔多斯" for item in result.evidence)


def test_relevance_accepts_provider_subsector_declared_inside_broader_topic() -> None:
    result = _normalize_result(
        [
            _executed(
                {
                    "股票简称": "测试电池公司",
                    "所属概念": "动力电池、锂电池",
                    "产量": 20.6,
                }
            )
        ],
        industry_topic="新能源动力电池行业",
    )

    assert result.quarantined == []
    assert any(item.scope == "测试电池公司" for item in result.evidence)


def test_target_company_task_quarantines_sector_constituent_substitution() -> None:
    executed = _executed(
        {
            "股票简称": "富奥股份",
            "所属概念": "动力电池",
            "营业收入(亿元)": 10,
        }
    )
    executed = replace(
        executed,
        task=executed.task.model_copy(update={"target_entities": ["宁德时代", "比亚迪"]}),
    )

    result = _normalize_result([executed], industry_topic="动力电池")

    assert result.evidence == []
    assert result.summary.task_clean_row_counts["Q-01"] == 0
    assert result.quarantined[0].reason_code == "target_entity_mismatch"


def test_source_identity_does_not_collide_when_raw_hash_is_reused() -> None:
    first = _executed({"股票简称": "公司A", "营业收入(亿元)": 1})
    second = _executed({"股票简称": "公司B", "行业指标": 2})
    second = replace(
        second,
        task=second.task.model_copy(update={"task_id": "Q-02", "skill_name": SkillName.INDUSTRY}),
        payloads=[
            second.payloads[0].model_copy(
                update={
                    "skill_name": SkillName.INDUSTRY,
                    "source_name": "同花顺问财行业数据",
                    "source_locator": "SkillHub:hithink-industry-query:trace",
                }
            )
        ],
    )

    result = _normalize_result([first, second])

    assert len(result.sources) == 2
    assert len({source.source_id for source in result.sources}) == 2


def test_single_metric_history_is_bounded_without_dropping_audit_counts() -> None:
    row: dict[str, object] = {"股票简称": "测试公司"}
    for month in range(1, 13):
        row[f"营业收入[2025{month:02d}28]"] = month
    row["营业收入[20241231]"] = 99

    result = _normalize_result([_executed(row)])

    assert sum(item.metric_name == "营业收入" for item in result.evidence) == 12
    assert result.summary.raw_row_count == 1


def test_verified_market_skill_fields_use_provider_units_without_guessing_futures_quote_unit() -> (
    None
):
    index = _executed_for_skill(
        SkillName.INDEX,
        {
            "指数代码": "000300.SH",
            "指数简称": "沪深300",
            "市盈率(pe,ttm)[20260814]": 14.312913,
            "市净率[20260817]": 1.3534,
            "收盘价分位点[20260817]": 0.908893,
            "最新涨跌幅:前复权": 1.6121,
        },
        query="沪深300 市盈率 市净率 历史分位",
        dimension="industry",
        task_id="Q-INDEX",
    )
    futures = _executed_for_skill(
        SkillName.FUTURES,
        {
            "合约代码": "LCZL.GFE",
            "合约简称": "碳酸锂主连",
            "收盘价": 153500.0,
            "最新涨跌幅": -0.441043,
        },
        query="碳酸锂主连 收盘价",
        dimension="industry",
        task_id="Q-FUTURES",
    )
    selector = _executed_for_skill(
        SkillName.STOCK_SELECTOR,
        {
            "股票代码": "300750.SZ",
            "股票简称": "宁德时代",
            "营业收入[20251231]": 423701834000,
            "营业收入同比增长率[20251231]": 12.4,
        },
        query="动力电池概念股 2025年营业收入 从高到低",
        dimension="competition",
        task_id="Q-SELECTOR",
    )

    result = _normalize_result(
        [index, futures, selector],
        industry_topic="动力电池",
    )
    metrics = {item.metric_name: item for item in result.evidence}

    assert metrics["市盈率"].unit == "倍"
    assert metrics["市净率"].unit == "倍"
    assert metrics["收盘价分位点"].unit == "%"
    assert metrics["收盘价分位点"].value == pytest.approx(90.8893)
    assert metrics["最新涨跌幅:前复权"].unit == "%"
    assert metrics["收盘价"].unit == "未提供"
    assert metrics["最新涨跌幅"].unit == "%"
    assert metrics["营业收入"].unit == "元"
    assert metrics["营业收入同比增长率"].unit == "%"
