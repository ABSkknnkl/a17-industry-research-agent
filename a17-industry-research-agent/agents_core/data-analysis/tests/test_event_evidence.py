"""类D(P-06) 下游衔接回归测试：事件流进 A2（data_interpreter）。

核心闸门：adapters.py 用 A2 自己的 StructuredResearchDataset 副本反序列化 A1 的
dataset.json——副本 extra="ignore" 且字段表缺 events 时，事件被静默丢弃。
本文件覆盖：闸门回归、事件证据构造、技能证据域匹配（含枚举转换修复）、agent 全链路注入。
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone

from data_interpreter.agent import DataInterpreterAgent
from data_interpreter.engine import DeterministicAnalysisEngine
from data_interpreter.models import (
    AnalysisRequest,
    Domain,
    EventRecord,
    ResearchRecord,
    SourceRef,
    StructuredResearchDataset,
)

AS_OF = date(2026, 9, 30)


def _source(skill: str = "announcement-search") -> SourceRef:
    return SourceRef(
        task_id="t1",
        skill_id=skill,
        skill_version="1.0.0",
        query="测试事件查询",
        trace_id="tr1",
        retrieved_at=datetime(2026, 9, 30, tzinfo=timezone.utc),
    )


def _event(rid: str, etype: str, title: str, day: int, entity: str = "宁德时代") -> EventRecord:
    return EventRecord(
        record_id=rid,
        entity_name=entity,
        entity_code="300750.SZ",
        title=title,
        event_type=etype,
        announce_date=date(2026, 9, day),
        source=_source(),
    )


def _financial_record(rid: str, value: float) -> ResearchRecord:
    return ResearchRecord(
        record_id=rid,
        domain=Domain.FINANCIALS,
        entity_name="宁德时代",
        metric="revenue",
        value=value,
        period_end=date(2025, 12, 31),
        source=_source("hithink-finance-query"),
    )


class _NoLLM:
    is_available = False

    async def generate_json(self, system_prompt, user_prompt):
        raise AssertionError("must not be called")


class _Skill:
    def __init__(self, domains):
        self.domains = domains


class TestGateAndConstruction:
    def test_dataset_deserialization_keeps_events(self):
        """闸门回归：A2 模型副本解析带 events 的 dataset.json 不得丢弃事件。"""
        payload = {
            "subject": "动力电池",
            "industry": [],
            "companies": [],
            "financials": [{
                "record_id": "r1", "domain": "financials", "metric": "revenue",
                "value": 100.0,
                "source": {"task_id": "t1", "skill_id": "hithink-finance-query",
                           "trace_id": "tr1", "retrieved_at": "2026-09-30T00:00:00Z"},
            }],
            "macro": [], "industry_chain": [], "reports": [], "news": [],
            "events": [{
                "record_id": "E-1", "entity_name": "宁德时代", "entity_code": "300750.SZ",
                "title": "宁德时代：关于2022年股票期权激励计划归属结果公告",
                "event_type": "股权激励", "announce_date": "2026-09-11",
                "body": None,
                "source": {"task_id": "t2", "skill_id": "announcement-search",
                           "trace_id": "tr2", "retrieved_at": "2026-09-11T00:00:00Z"},
                "raw_fields": {}, "issues": [],
            }],
            "sources": [], "conflicts": [], "quality_summary": {},
        }
        ds = StructuredResearchDataset.model_validate(payload)
        assert len(ds.events) == 1
        assert ds.events[0].event_type == "股权激励"
        assert ds.events[0].announce_date == date(2026, 9, 11)
        assert ds.events[0].source.skill_id == "announcement-search"
        # all_records 保持类型纯净：只含七域指标记录，事件不进数值分析
        assert len(ds.all_records()) == 1
        assert all(isinstance(r, ResearchRecord) for r in ds.all_records())

    def test_backward_compat_without_events_key(self):
        old = {"subject": "x", "industry": [], "companies": [], "financials": [],
               "macro": [], "industry_chain": [], "reports": [], "news": [],
               "sources": [], "conflicts": [], "quality_summary": {}}
        ds = StructuredResearchDataset.model_validate(old)
        assert ds.events == []

    def test_event_evidence_construction(self):
        ev = _event("E-1", "股权激励", "宁德时代关于激励计划公告", day=1)
        ref = DeterministicAnalysisEngine._event_evidence(ev)
        assert ref.domain == "events"
        assert ref.entity == "宁德时代"
        assert ref.metric == "股权激励"
        assert ref.value == "宁德时代关于激励计划公告"
        assert ref.period == date(2026, 9, 1)
        assert ref.skill_id == "announcement-search"
        dumped = ref.model_dump(mode="json")
        assert dumped["domain"] == "events"  # 序列化后为纯字符串，LLM 侧与七域格式一致

    def test_event_evidence_falls_back_to_body_when_no_title(self):
        ev = _event("E-2", "解禁", "", day=2)
        ev.body = "限售股上市流通提示"
        ref = DeterministicAnalysisEngine._event_evidence(ev)
        assert ref.value == "限售股上市流通提示"

    def test_event_evidence_preserves_title_and_body(self):
        """AB-2/E01：短标题+关键正文的事件，正文不得丢失。

        原缺陷：value=ev.title or ev.body，标题存在时正文被丢弃；若标题只是
        "公告"，关键催化内容（仅在正文）就进不了技能上下文。
        """
        ev = _event("E-9", "对外投资", "公告", day=3)
        ev.body = "公司拟以自有资金10亿元投建固态电池中试线，2026年内投产。"
        ref = DeterministicAnalysisEngine._event_evidence(ev)
        assert "公告" in ref.value
        assert "10亿元投建固态电池中试线" in ref.value  # 正文保全
        # 溯源四要素保持
        assert ref.record_id == "E-9"
        assert ref.period == date(2026, 9, 3)
        assert ref.skill_id == "announcement-search"

    def test_two_events_same_company_keep_distinct_bodies(self):
        """AB-2/E01：同公司两条事件各有不同正文，不得互相合并或覆盖。"""
        ev_a = _event("E-A", "股权激励", "公告A", day=5)
        ev_a.body = "授予限制性股票100万股，行权价每股12元。"
        ev_b = _event("E-B", "股权激励", "公告B", day=5)
        ev_b.body = "预留授予部分作废注销，涉及30万股。"
        ref_a = DeterministicAnalysisEngine._event_evidence(ev_a)
        ref_b = DeterministicAnalysisEngine._event_evidence(ev_b)
        assert ref_a.record_id != ref_b.record_id
        assert "行权价每股12元" in ref_a.value and "作废注销" not in ref_a.value
        assert "作废注销" in ref_b.value and "行权价每股12元" not in ref_b.value

    def test_event_body_not_duplicated_when_already_in_title(self):
        """正文已包含在标题中时不重复合并，避免冗余。"""
        ev = _event("E-D", "业绩预告", "公司2026年前三季度净利润预增50%", day=6)
        ev.body = "公司2026年前三季度净利润预增50%"
        ref = DeterministicAnalysisEngine._event_evidence(ev)
        assert ref.value == "公司2026年前三季度净利润预增50%"


class TestSkillEvidenceRouting:
    def test_events_domain_skill_receives_event_evidence(self):
        ev_ref = DeterministicAnalysisEngine._event_evidence(
            _event("E-1", "股权激励", "公告A", day=8))
        news_ref = DeterministicAnalysisEngine._evidence(ResearchRecord(
            record_id="N-1", domain=Domain.NEWS, metric="title",
            value="某新闻", source=_source("news-search"),
        ))
        evidence = {"E-1": ev_ref, "N-1": news_ref}
        selected = DataInterpreterAgent._filter_evidence_for_skill(_Skill(["events"]), evidence, [])
        assert "E-1" in selected
        assert selected["E-1"]["domain"] == "events"
        assert selected["E-1"]["metric"] == "股权激励"

    def test_domain_match_uses_enum_value_not_str_repr(self):
        """域匹配枚举修复回归：str(Domain.NEWS) 得 'Domain.NEWS' 曾失配别名 'news'。

        构造 35 条 financials 证据占满「前 30 条兜底」名额：修复前 news 证据进不去，
        修复后靠域匹配命中——用例可精确区分修复前后。
        """
        evidence = {}
        for i in range(35):
            evidence[f"F-{i}"] = DeterministicAnalysisEngine._evidence(_financial_record(f"F-{i}", float(i)))
        news_ref = DeterministicAnalysisEngine._evidence(ResearchRecord(
            record_id="N-1", domain=Domain.NEWS, metric="title",
            value="行业动态新闻", source=_source("news-search"),
        ))
        evidence["N-1"] = news_ref

        selected = DataInterpreterAgent._filter_evidence_for_skill(_Skill(["news"]), evidence, [])
        assert "N-1" in selected, "news 域证据应经域匹配（而非兜底）被选中"
        assert selected["N-1"]["domain"] == "news"


class TestAgentRunIntegration:
    def test_run_injects_events_and_keeps_same_type_same_day(self):
        """全链路：事件进入最终 evidence_index；同公司同类型同日期的多条事件
        不被 dedup（按 entity/metric/period 折叠）误删——必须在 dedup 之后注入。"""
        ds = StructuredResearchDataset(financials=[
            _financial_record("r1", 100.0),
            _financial_record("r2", 130.0),
        ])
        ds.events.append(_event("E-1", "股权激励", "公告A：归属结果", day=8))
        ds.events.append(_event("E-3", "股权激励", "公告C：行权条件成就", day=8))  # 与 E-1 同类型同日
        ds.events.append(_event("E-2", "股权激励", "公告B：注销完成", day=11))

        report = asyncio.run(DataInterpreterAgent(llm=_NoLLM()).run(
            ds, AnalysisRequest(subject="宁德时代 股权激励"), save_artifacts=False,
        ))
        assert report.status == "completed"
        for rid in ("E-1", "E-2", "E-3"):
            assert rid in report.evidence_index, f"事件 {rid} 应进入 evidence_index"
            assert report.evidence_index[rid].domain == "events"
            assert report.evidence_index[rid].metric == "股权激励"
        # 事件证据带完整溯源字段（skill_id/trace_id），供 evidence_record_ids 引用
        assert report.evidence_index["E-1"].skill_id == "announcement-search"

    def test_run_without_events_unchanged(self):
        ds = StructuredResearchDataset(financials=[
            _financial_record("r1", 100.0),
            _financial_record("r2", 130.0),
        ])
        report = asyncio.run(DataInterpreterAgent(llm=_NoLLM()).run(
            ds, AnalysisRequest(subject="测试行业"), save_artifacts=False,
        ))
        assert report.status == "completed"
        assert all(v.domain != "events" for v in report.evidence_index.values())


class TestEventRequirementMatrix:
    """AB-2/E02+AB-2.5：明确要求事件催化时建立可验收事件需求。

    有效事件（有公告日期）成为必答证据，语义融合预算挤压不丢；
    缺日期事件不计入催化事实；无事件时保留显式缺口，不用行情或财务记录顶替。
    """

    def _coverage_rows(self, report):
        return [
            row for row in (report.data_quality_appendix.get("requested_requirement_coverage") or [])
            if row.get("requirement_id") == "event_catalysts"
        ]

    def test_explicit_event_demand_binds_dated_events_as_required_evidence(self):
        ds = StructuredResearchDataset(financials=[_financial_record("r1", 100.0)])
        ds.events.append(_event("E-1", "股权激励", "公告A：归属结果", day=8))
        undated = _event("E-2", "解禁", "无日期公告", day=9)
        undated.announce_date = None
        undated.issues = ["missing_announce_date"]
        ds.events.append(undated)

        report = asyncio.run(DataInterpreterAgent(llm=_NoLLM()).run(
            ds,
            AnalysisRequest(subject="宁德时代", focus_points=["分析宁德时代近期事件催化"]),
            save_artifacts=False,
        ))
        rows = self._coverage_rows(report)
        assert rows, "事件催化需求未进附录覆盖"
        assert rows[0]["passed"] is True
        # 缺日期事件不得计入催化事实
        assert rows[0]["evidence_record_ids"] == ["E-1"]
        assert "E-1" in report.evidence_index

    def test_explicit_event_demand_without_events_yields_explicit_gap(self):
        ds = StructuredResearchDataset(financials=[_financial_record("r1", 100.0)])
        report = asyncio.run(DataInterpreterAgent(llm=_NoLLM()).run(
            ds,
            AnalysisRequest(subject="宁德时代", focus_points=["关注宁德时代的事件催化"]),
            save_artifacts=False,
        ))
        rows = self._coverage_rows(report)
        assert rows, "无事件时需求格丢失"
        assert rows[0]["passed"] is False
        assert rows[0]["missing"], "无事件时必须显式缺口，不得静默通过"

    def test_undated_events_do_not_satisfy_catalyst_requirement(self):
        ds = StructuredResearchDataset(financials=[_financial_record("r1", 100.0)])
        undated = _event("E-9", "解禁", "无日期公告", day=9)
        undated.announce_date = None
        undated.issues = ["missing_announce_date"]
        ds.events.append(undated)

        report = asyncio.run(DataInterpreterAgent(llm=_NoLLM()).run(
            ds,
            AnalysisRequest(subject="宁德时代", focus_points=["分析宁德时代近期事件催化"]),
            save_artifacts=False,
        ))
        rows = self._coverage_rows(report)
        assert rows and rows[0]["passed"] is False, "无日期事件不得当催化事实"

    def test_no_event_demand_leaves_no_synthetic_event_requirement(self):
        ds = StructuredResearchDataset(financials=[_financial_record("r1", 100.0)])
        ds.events.append(_event("E-1", "股权激励", "公告A：归属结果", day=8))
        report = asyncio.run(DataInterpreterAgent(llm=_NoLLM()).run(
            ds,
            AnalysisRequest(subject="宁德时代", focus_points=["分析宁德时代2025年营业收入"]),
            save_artifacts=False,
        ))
        assert self._coverage_rows(report) == [], "未要求事件时不得凭空造事件需求"


def test_final_appendix_counts_the_same_event_and_structured_sources_as_evidence_index():
    """Event citations join evidence_index but not all_records or financial periods."""
    financial_a = _financial_record("f-2024", 100)
    financial_a.period_end = date(2024, 12, 31)
    financial_b = _financial_record("f-2025", 130)
    company = ResearchRecord(record_id="company", domain=Domain.COMPANIES,
        entity_name="公司乙", metric="industry_name", value="测试行业",
        period_end=date(2023, 12, 31), source=_source())
    ds = StructuredResearchDataset(companies=[company], financials=[financial_a, financial_b],
        events=[_event("event", "股权激励", "公告：计划归属", day=8)])
    report = asyncio.run(DataInterpreterAgent(llm=_NoLLM()).run(
        ds, AnalysisRequest(subject="测试行业"), save_artifacts=False))
    sample = report.data_quality_appendix["sample_info"]
    assert set(report.evidence_index) == {"company", "f-2024", "f-2025", "event"}
    assert sample["total_records"] == len(report.evidence_index) == 4
    assert sample["structured_record_count"] == 3
    assert sample["event_record_count"] == 1
    assert sample["total_records"] == sample["structured_record_count"] + sample["event_record_count"]
    assert sample["total_companies"] == 1
    assert sample["primary_periods"] == ["2024-12-31", "2025-12-31"]


def test_event_skill_does_not_receive_unrelated_financial_fallback():
    evidence = {f'F-{i}': DeterministicAnalysisEngine._evidence(_financial_record(f'F-{i}', float(i))) for i in range(3)}
    assert DataInterpreterAgent._filter_evidence_for_skill(_Skill(['events']), evidence, []) == {}


def test_skill_evidence_budget_is_stable_across_source_order():
    evidence = {f'F-{i:03}': DeterministicAnalysisEngine._evidence(_financial_record(f'F-{i:03}', float(i))) for i in range(80)}
    skill = _Skill(['financials'])
    a = DataInterpreterAgent._filter_evidence_for_skill(skill, evidence, [], max_items=10)
    b = DataInterpreterAgent._filter_evidence_for_skill(skill, dict(reversed(list(evidence.items()))), [], max_items=10)
    assert set(a) == set(b)


def test_skill_evidence_budget_preserves_multiple_entities():
    evidence = {}
    for i in range(30):
        rec = _financial_record(f'A-{i:03}', float(i))
        rec.entity_name = '公司甲'
        evidence[rec.record_id] = DeterministicAnalysisEngine._evidence(rec)
    for i in range(3):
        rec = _financial_record(f'B-{i:03}', float(i))
        rec.entity_name = '公司乙'
        evidence[rec.record_id] = DeterministicAnalysisEngine._evidence(rec)
    selected = DataInterpreterAgent._filter_evidence_for_skill(_Skill(['financials']), evidence, [], max_items=4)
    assert {item['entity'] for item in selected.values()} == {'公司甲', '公司乙'}


def test_requirement_evidence_is_prioritized_before_other_same_entity_records():
    evidence = {f'F-{i:03}': DeterministicAnalysisEngine._evidence(_financial_record(f'F-{i:03}', float(i))) for i in range(20)}
    selected = DataInterpreterAgent._filter_evidence_for_skill(_Skill(['financials']), evidence, [], max_items=3, priority_ids={'F-019'})
    assert 'F-019' in selected


def test_all_hard_requirement_evidence_is_preserved_above_nominal_limit():
    evidence={f'F-{i:03}': DeterministicAnalysisEngine._evidence(_financial_record(f'F-{i:03}',float(i))) for i in range(80)}
    required={f'F-{i:03}' for i in range(70)}
    selected=DataInterpreterAgent._filter_evidence_for_skill(_Skill(['financials']),evidence,[],max_items=60,priority_ids=required)
    assert required <= set(selected)
