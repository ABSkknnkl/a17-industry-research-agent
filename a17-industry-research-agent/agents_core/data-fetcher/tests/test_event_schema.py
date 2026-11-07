"""类D(P-06) 事件/公告 Schema 修复回归测试。

覆盖：结构化抽取、碎片消除、类型推断、缺字段留痕不造数、
未来日期丢弃、P0-1 口径（events 计入 _total_records）、非事件源零影响、向后兼容。
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from data_fetcher.agent import _total_records
from data_fetcher.fusion import DataFusion
from data_fetcher.models import Domain, EventRecord, SkillResult, StructuredResearchDataset

AS_OF = date(2026, 9, 30)


def _result(skill_id: str, records: list[dict], domain: Domain = Domain.NEWS) -> SkillResult:
    return SkillResult(
        task_id="T1",
        skill_name=skill_id,
        skill_id=skill_id,
        skill_version="1.0.0",
        domain=domain,
        query="测试事件查询",
        trace_id="tr-1",
        retrieved_at=datetime(2026, 9, 30, tzinfo=timezone.utc),
        success=True,
        records=records,
    )


def _fuse(results: list[SkillResult]) -> StructuredResearchDataset:
    return DataFusion().fuse(results, AS_OF)


class TestEventStructuredExtraction:
    def test_event_skill_produces_structured_event(self):
        ds = _fuse([_result("hithink-event-query", [{
            "股票代码": "300750.SZ", "股票简称": "宁德时代",
            "事件类型": "股权激励", "公告日期": "20250601",
            "公告标题": "宁德时代2025年股票期权激励计划公告",
        }])])
        assert len(ds.events) == 1
        ev = ds.events[0]
        assert isinstance(ev, EventRecord)
        assert ev.event_type == "股权激励"
        assert ev.title == "宁德时代2025年股票期权激励计划公告"
        assert ev.announce_date == date(2025, 6, 1)
        assert ev.entity_name == "宁德时代"
        assert ev.entity_code == "300750.SZ"
        assert ev.issues == []
        # 碎片消除：news 域不得再出现 metric="事件类型" 的伪指标记录
        assert all(r.metric != "事件类型" for r in ds.news)
        assert all(r.metric != "title" for r in ds.news)

    def test_pure_event_record_leaves_no_news_fragment(self):
        ds = _fuse([_result("hithink-event-query", [{
            "股票代码": "300750.SZ", "股票简称": "宁德时代",
            "事件类型": "业绩预告", "公告日期": "20250710",
            "公告标题": "宁德时代2025年半年度业绩预告",
        }])])
        assert len(ds.events) == 1
        # 纯事件记录（无数值字段）：news 域不应有 record 兜底碎片
        assert ds.news == []

    def test_numeric_fields_alongside_event_still_parsed(self):
        ds = _fuse([_result("hithink-event-query", [{
            "股票代码": "002594.SZ", "股票简称": "比亚迪",
            "事件类型": "增发配股", "公告日期": "20250801",
            "公告标题": "比亚迪向特定对象发行股票公告",
            "增发数量(万股)": 5000.0,
        }])])
        assert len(ds.events) == 1
        # 数值字段保留为指标记录
        metric_names = {r.metric: r for r in ds.news}
        assert "增发数量(万股)" in metric_names or any("增发数量" in m for m in metric_names)

    def test_announcement_without_event_type_infers_from_title(self):
        ds = _fuse([_result("announcement-search", [{
            "股票代码": "300033.SZ", "股票简称": "同花顺",
            "公告日期": "20240115",
            "公告标题": "同花顺关于回购股份的进展公告",
        }])])
        assert len(ds.events) == 1
        assert ds.events[0].event_type == "回购增持"  # 确定性推断，非 LLM
        assert ds.events[0].issues == []


class TestEventGuardrails:
    def test_missing_fields_flagged_not_fabricated(self):
        # 有标题但缺类型/日期（部分字段缺失）→ 落库且留痕，缺失字段保持 None
        ds = _fuse([_result("announcement-search", [{
            "股票代码": "300750.SZ", "title": "宁德时代关于某项事宜的公告",
        }])])
        assert len(ds.events) == 1
        ev = ds.events[0]
        assert ev.title == "宁德时代关于某项事宜的公告"
        assert ev.event_type is None
        assert ev.announce_date is None
        assert "missing_event_type" in ev.issues
        assert "missing_announce_date" in ev.issues
        assert "missing_title" not in ev.issues
        # 不造数：缺失日期不得用 as_of 冒充
        assert ev.announce_date != AS_OF

    def test_event_query_market_snapshot_produces_no_event(self):
        # 实测 hithink-event-query 部分 query 返回行情型字段，无任何事件要素 → 不产空壳事件
        ds = _fuse([_result("hithink-event-query", [{
            "股票代码": "002594.SZ", "股票简称": "比亚迪",
            "最新价": "83.31", "最新涨跌幅": 1.5727,
            "报告期[20260930]": "2026年三季报",
        }])])
        assert ds.events == []
        # 行情字段照常走通用指标拆分
        assert any("最新价" in r.metric or "涨跌幅" in r.metric for r in ds.news)

    def test_announcement_stock_infos_supplies_entity(self):
        # announcement-search 真实返回原样：stock_infos 首个元素常无 name，需遍历取带名称项
        ds = _fuse([_result("announcement-search", [{
            "channel": "announcement", "id": "abc_29", "uid": "abc",
            "url": "http://static.cninfo.com.cn/x.PDF",
            "title": "宁德时代：关于2022年股票期权与限制性股票激励计划归属结果公告",
            "summary": "（六）股票来源：公司向激励对象定向发行公司A股普通股股票。",
            "source_original": "（六）股票来源：公司向激励对象定向发行公司A股普通股股票。",
            "index": "iwc_index_china_notice_daily_v5_vector",
            "score": 0.169,
            "extra": {"seq": "5293173086", "publish_source": "公告"},
            "name": "admin",
            "status": 0,
            "data_source": "ZH_NOTICE_KEYWORD",
            "para_index": 29,
            "publish_time": 1789056000,
            "publish_date": "2026-09-11 00:00:00",
            "stock_infos": [
                {"code": "CYATY"}, {"code": "CATL23"}, {"code": "CATL01"},
                {"name": "宁德时代", "code": "300750"}, {"code": "CATL80"},
            ],
            "traceability_type": 0, "site_authority": 4, "modify_time": 0, "operation_type": 0,
        }])])
        assert len(ds.events) == 1
        ev = ds.events[0]
        assert ev.entity_name == "宁德时代"
        assert ev.entity_code == "300750.SZ"
        assert ev.announce_date == date(2026, 9, 11)
        assert ev.event_type == "股权激励"  # 从标题推断
        assert ev.body and ev.body.startswith("（六）股票来源")
        assert ev.issues == []
        # 检索型元数据（channel/id/url/index/score/stock_infos/admin…）不得产指标碎片
        assert not any(
            r.metric in ("channel", "id", "url", "score", "index", "name", "status",
                         "data_source", "para_index", "stock_infos", "source_original")
            for r in ds.news
        )

    def test_future_dated_event_dropped(self):
        ds = _fuse([_result("hithink-event-query", [{
            "股票代码": "300750.SZ", "事件类型": "解禁",
            "公告日期": "20270101", "公告标题": "未来事件",
        }])])
        assert ds.events == []
        assert ds.quality_summary["dropped_future_records"] >= 1

    def test_duplicate_events_deduped(self):
        rec = {"股票代码": "300750.SZ", "事件类型": "解禁", "公告日期": "20250301", "公告标题": "同一公告"}
        ds = _fuse([_result("hithink-event-query", [rec, dict(rec)])])
        assert len(ds.events) == 1

    def test_non_event_source_unchanged(self):
        # news-search 非白名单、无事件特征键 → 完全走老路径，events 为空
        ds = _fuse([_result("news-search", [{
            "股票代码": "300750.SZ", "股票简称": "宁德时代", "标题": "某新闻标题",
        }])])
        assert ds.events == []
        assert any(r.metric == "title" for r in ds.news)  # 老行为保留


class TestP01AndCompatibility:
    def test_total_records_counts_events(self):
        # 无股票代码的纯事件记录：七域真全空，仅 events 有值 → 不再被判空
        ds = _fuse([_result("hithink-event-query", [{
            "事件类型": "解禁", "公告日期": "20250301", "公告标题": "纯事件",
        }])])
        assert len(ds.events) == 1
        assert _total_records(ds) == len(ds.events) == 1

    def test_total_records_sums_seven_domains_plus_events(self):
        # 含股票代码的事件记录会按既有行为产 companies 实体身份记录；
        # 验证口径：总数 = 七域之和 + events 条数
        ds = _fuse([_result("hithink-event-query", [{
            "股票代码": "300750.SZ", "事件类型": "解禁", "公告日期": "20250301", "公告标题": "带代码事件",
        }])])
        seven = sum(
            len(getattr(ds, name, []) or [])
            for name in ("industry", "companies", "financials", "macro", "industry_chain", "reports", "news")
        )
        assert seven == 1  # companies 实体身份记录
        assert _total_records(ds) == seven + len(ds.events)

    def test_backward_compat_dataset_without_events_key(self):
        # 旧 dataset.json（迁移前的产物）无 events 键，必须能正常加载
        old = {
            "subject": "动力电池", "industry": [], "companies": [], "financials": [],
            "macro": [], "industry_chain": [], "reports": [], "news": [],
            "sources": [], "conflicts": [], "quality_summary": {},
        }
        ds = StructuredResearchDataset.model_validate(old)
        assert ds.events == []

    def test_quality_summary_reports_event_count(self):
        ds = _fuse([_result("hithink-event-query", [{
            "股票代码": "300750.SZ", "事件类型": "解禁", "公告日期": "20250301", "公告标题": "事件A",
        }])])
        assert ds.quality_summary["event_count"] == 1
        assert ds.quality_summary["events_with_issues"] == 0
