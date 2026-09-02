"""BUG-3（2026-09-02）：宏观任务结果相关性过滤。

宏观技能（SkillName.MACRO）的行不含行业/概念/主营业务字段，也不属于文本检索
技能，导致 `_is_low_relevance` 对其恒为放行——PMI、CPI 等与研究主题无关的
宏观序列会整批进入证据库（RUN 5e73b49f 实测 94 条证据混入 12+ 条 PMI/CPI）。

本组测试约束：对宏观行按“任务意图 tokens ∪ 研究主题 tokens”做相关性过滤，
无匹配者隔离为 ``macro_off_topic``；有匹配者照常成为证据。过滤只发生在清洗
阶段，仅影响新任务，不回溯历史证据。
"""

from datetime import date

from app.agents.data_fetcher.executor import ExecutedTask
from app.agents.data_fetcher.normalizer import NormalizationResult, normalize_tasks
from app.schemas.acquisition import (
    SkillCallRecord,
    SkillName,
    SkillPayload,
    SkillQueryTask,
    SkillTier,
)


def _macro_task(
    rows: list[dict[str, object]],
    *,
    query: str,
    task_origin: str = "baseline",
    target_entities: list[str] | None = None,
    task_id: str = "Q-03",
) -> ExecutedTask:
    task = SkillQueryTask(
        task_id=task_id,
        skill_name=SkillName.MACRO,
        tier=SkillTier.P1,
        research_dimension="macro_policy",
        query=query,
        time_range="2025",
        market_scope=["中国内地"],
        task_origin=task_origin,
        target_entities=target_entities or [],
    )
    payload = SkillPayload(
        skill_name=SkillName.MACRO,
        query=query,
        rows=rows,
        total_count=len(rows),
        page=1,
        trace_id="trace-macro",
        raw_sha256="b" * 64,
        source_name="同花顺问财宏观数据",
        source_locator="SkillHub:hithink-macro-query:trace",
    )
    record = SkillCallRecord(
        call_id=f"CALL-{task_id.removeprefix('Q-')}",
        task_id=task_id,
        skill_name=SkillName.MACRO,
        tier=SkillTier.P1,
        query=query,
        status="succeeded",
        row_count=len(rows),
        pages_fetched=1,
        attempts=1,
    )
    return ExecutedTask(task=task, payloads=[payload], record=record)


def _run(executed: list[ExecutedTask], *, industry_topic: str = "动力电池行业") -> NormalizationResult:
    return normalize_tasks(
        executed,
        industry_topic=industry_topic,
        market_scope=["中国内地"],
        security_types=["普通股"],
        reporting_currency="CNY",
        research_as_of=date(2026, 8, 11),
    )


def _macro_row(indicator: str, value: float, unit: str) -> dict[str, object]:
    return {
        "指标名称": indicator,
        "指标值": value,
        "单位": unit,
        "报告期": "2025-12-31",
        "数据日期": "2026-01-15",
    }


def test_unrelated_macro_indicators_are_quarantined_not_evidence() -> None:
    """意图宏观任务只要出货量，PMI/CPI 与之无关，必须被隔离、不进证据库。"""
    task = _macro_task(
        [
            _macro_row("制造业PMI", 50.1, "%"),
            _macro_row("CPI当月同比", 0.2, "%"),
            _macro_row("动力电池出货量", 500.0, "GWh"),
        ],
        query="动力电池行业 出货量 宏观指标",
        task_origin="hybrid_intent",
    )

    result = _run([task])

    evidence_metrics = {item.metric_name for item in result.evidence}
    assert "动力电池出货量" in evidence_metrics
    assert "制造业PMI" not in evidence_metrics
    assert "CPI当月同比" not in evidence_metrics

    macro_quarantined = [
        record for record in result.quarantined if record.reason_code == "macro_off_topic"
    ]
    assert {record.entity for record in macro_quarantined} == {"制造业PMI", "CPI当月同比"}


def test_matching_macro_indicator_still_becomes_evidence() -> None:
    """与研究主题/任务意图匹配的宏观指标照常成为证据，不被误杀。"""
    task = _macro_task(
        [_macro_row("动力电池出货量", 500.0, "GWh")],
        query="动力电池行业 出货量 宏观指标",
        task_origin="hybrid_intent",
    )

    result = _run([task])

    assert [item.metric_name for item in result.evidence] == ["动力电池出货量"]
    assert result.quarantined == []


def test_explicitly_queried_indicator_without_topic_overlap_is_kept() -> None:
    """任务明确点名的指标，即便与研究主题无字面重合也必须保留（防误杀）。

    对应既有场景：查“中国房地产行业 商品房销售面积”，指标“商品房销售面积”
    与主题 token“房地产”无字面交集，但它是任务直接索取的对象，不能被隔离。
    """
    task = _macro_task(
        [_macro_row("商品房销售面积", 881_013_711.0, "平方米")],
        query="中国房地产行业 商品房销售面积 2021-01-01至2025-12-31",
        task_origin="baseline",
    )

    result = _run([task], industry_topic="中国房地产行业")

    assert [item.metric_name for item in result.evidence] == ["商品房销售面积"]
    assert result.quarantined == []


def test_baseline_macro_generic_indicators_are_filtered_by_topic() -> None:
    """baseline 宏观任务无意图 tokens，退回主题 tokens：PMI 无主题关联 → 隔离。"""
    task = _macro_task(
        [
            _macro_row("制造业PMI", 50.1, "%"),
            _macro_row("储能装机容量", 120.0, "GWh"),
        ],
        query="储能行业 宏观 装机容量 数据",
        task_origin="baseline",
    )

    result = _run([task], industry_topic="储能行业")

    assert [item.metric_name for item in result.evidence] == ["储能装机容量"]
    assert [record.entity for record in result.quarantined] == ["制造业PMI"]
    assert result.quarantined[0].reason_code == "macro_off_topic"


def test_macro_filter_does_not_touch_non_macro_skills() -> None:
    """过滤只作用于 MACRO 技能；财务技能证据照常产出，宏观行仍被隔离。"""
    macro_task = _macro_task(
        [_macro_row("制造业PMI", 50.1, "%")],
        query="动力电池行业 出货量 宏观指标",
        task_origin="hybrid_intent",
    )
    finance_task = ExecutedTask(
        task=SkillQueryTask(
            task_id="Q-01",
            skill_name=SkillName.FINANCE,
            tier=SkillTier.P0,
            research_dimension="finance",
            query="宁德时代 2025 营业收入",
            time_range="2025",
            market_scope=["中国内地"],
            target_entities=["宁德时代"],
        ),
        payloads=[
            SkillPayload(
                skill_name=SkillName.FINANCE,
                query="宁德时代 2025 营业收入",
                rows=[
                    {
                        "股票简称": "宁德时代",
                        "报告期": "2025-12-31",
                        "营业收入(亿元)": 3620.0,
                    }
                ],
                total_count=1,
                page=1,
                trace_id="trace-finance",
                raw_sha256="c" * 64,
                source_name="同花顺问财财务数据",
                source_locator="SkillHub:hithink-finance-query:trace",
            )
        ],
        record=SkillCallRecord(
            call_id="CALL-01",
            task_id="Q-01",
            skill_name=SkillName.FINANCE,
            tier=SkillTier.P0,
            query="宁德时代 2025 营业收入",
            status="succeeded",
            row_count=1,
            pages_fetched=1,
            attempts=1,
        ),
    )

    result = _run([finance_task, macro_task])

    evidence_metrics = {item.metric_name for item in result.evidence}
    assert "营业收入" in evidence_metrics
    macro_quarantined = [
        record for record in result.quarantined if record.skill_name == SkillName.MACRO
    ]
    assert [record.entity for record in macro_quarantined] == ["制造业PMI"]
    assert all(record.reason_code == "macro_off_topic" for record in macro_quarantined)
