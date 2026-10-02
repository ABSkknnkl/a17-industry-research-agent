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
