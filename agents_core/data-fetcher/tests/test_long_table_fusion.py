"""长表（long-format）解析错位的回归测试。

缺陷：问财"序列类"查询（市场规模/出口量/装机量…）不论从哪个技能进入，底层返回
都是宏观库长表（时间/指标/指标值/周期/macro_id/macro_name/单位/国家/地区级别）。
fusion 原有的长表原子化通道被硬门限在 `Domain.MACRO`，经 `hithink-industry-query`
（domain=INDUSTRY）进来时被跳过，落到通用逐键拆分 → 一行炸成 8 条碎片
（metric='时间'/'指标值'/'周期'…），指标名与数值彻底脱钩。

测试数据逐字节取自真实探针 run 的 raw_fields：
run-20261003150133-d2da3e（M-01 动力电池市场规模，2026-10-03）。
"""

from datetime import date

from data_fetcher.fusion import DataFusion
from data_fetcher.models import Domain, SkillResult

AS_OF = date(2026, 10, 3)

# 真实返回形状：一行 = 一个时间点；指标名在"指标"列值里，数值在"指标值"列
REAL_LONG_TABLE_ROWS = [
    {"时间": "20221231", "指标": "动力电池出口量", "指标值": 68083.1, "周期": "月",
     "macro_id": "S018915880", "macro_name": "动力电池:出口量:合计:累计值",
     "单位": "兆瓦时", "国家": "中国", "地区级别": ["国家"]},
    {"时间": "20231231", "指标": "动力电池出口量", "指标值": 127400.0, "周期": "月",
     "macro_id": "S018915880", "macro_name": "动力电池:出口量:合计:累计值",
     "单位": "兆瓦时", "国家": "中国", "地区级别": ["国家"]},
    {"时间": "20241231", "指标": "动力电池出口量", "指标值": 133700.0, "周期": "月",
     "macro_id": "S018915880", "macro_name": "动力电池:出口量:合计:累计值",
     "单位": "兆瓦时", "国家": "中国", "地区级别": ["国家"]},
    {"时间": "20251231", "指标": "动力电池出口量", "指标值": 189700.0, "周期": "月",
     "macro_id": "S018915880", "macro_name": "动力电池:出口量:合计:累计值",
     "单位": "兆瓦时", "国家": "中国", "地区级别": ["国家"]},
]


def _result(domain: Domain, skill_id: str, records: list[dict], query: str = "动力电池 市场规模") -> SkillResult:
    return SkillResult(
        task_id="t1",
        skill_name=skill_id,
        skill_id=skill_id,
        skill_version="1.0.0",
        domain=domain,
        query=query,
        trace_id="tr1",
        records=records,
        success=True,
    )


def test_industry_long_table_rows_atomically_fused():
    """行业技能返回的长表：每行原子化为 1 条记录，不再炸成 8 条碎片。"""
    dataset = DataFusion().fuse(
        [_result(Domain.INDUSTRY, "hithink-industry-query", REAL_LONG_TABLE_ROWS)], AS_OF
    )
    assert len(dataset.industry) == 4
    assert {r.metric for r in dataset.industry} == {"动力电池出口量"}
    assert [r.value for r in dataset.industry] == [68083.1, 127400.0, 133700.0, 189700.0]
    assert {r.unit for r in dataset.industry} == {"兆瓦时"}
    assert [r.period_end for r in dataset.industry] == [
        date(2022, 12, 31), date(2023, 12, 31), date(2024, 12, 31), date(2025, 12, 31),
    ]
    # 关键断言：错位碎片一个都不许存在
    fragments = {"时间", "指标", "指标值", "周期", "macro_id", "macro_name",
                 "单位", "地区级别", "record"}
    assert not (fragments & {r.metric for r in dataset.industry})


def test_long_table_keeps_skill_domain():
    """域归属必须保持 result.domain：重定向到 macro 会让 industry 域验收永远不过。"""
    dataset = DataFusion().fuse(
        [_result(Domain.INDUSTRY, "hithink-industry-query", REAL_LONG_TABLE_ROWS)], AS_OF
    )
    assert dataset.industry
    assert dataset.macro == []
    # 时间序列信息完整：4 个年度点可拼接
    periods = sorted(r.period_end for r in dataset.industry)
    assert periods[0].year == 2022 and periods[-1].year == 2025


def test_macro_channel_unchanged_for_domain_macro():
    """MACRO 域专属通道保持原行为（含无时间键时仍原子化 + 记 missing_period_end）。"""
    rows = [
        {"时间": "20231231", "指标": "GDP", "指标值": 129427170000000.0, "单位": "元", "国家": "中国"},
        {"指标": "CPI", "指标值": 0.6, "单位": "%"},  # 缺时间键
    ]
    dataset = DataFusion().fuse([_result(Domain.MACRO, "hithink-macro-query", rows)], AS_OF)
    assert len(dataset.macro) == 2
    gdp = next(r for r in dataset.macro if r.metric == "GDP")
    assert gdp.unit == "元" and gdp.period_end == date(2023, 12, 31)
    assert gdp.entity_name == "中国"
    cpi = next(r for r in dataset.macro if r.metric == "CPI")
    assert cpi.issues == ["missing_period_end"]
    assert cpi.entity_name == "全国"  # MACRO 通道的 default_entity 兜底


def test_wide_table_not_misrouted():
    """三键签名不误伤宽表：公司财务宽表不含"指标值/指标"列名，仍走通用拆分。"""
    wide = [{
        "证券代码": "300750.SZ",
        "证券简称": "宁德时代",
        "营业收入[20241231](元)": 362000000000.0,
        "净利润[20241231](元)": 50700000000.0,
    }]
    dataset = DataFusion().fuse(
        [_result(Domain.FINANCIALS, "hithink-finance-query", wide, query="宁德时代 财务数据")],
        AS_OF,
    )
    metrics = {r.metric for r in dataset.financials}
    assert {"revenue", "net_profit"} <= metrics
    assert "动力电池出口量" not in metrics


def test_empty_and_metadata_only_records_dropped():
    """空 raw / 纯身份 raw 不再硬造 metric='record' 占位记录。"""
    dataset = DataFusion().fuse(
        [
            _result(Domain.INDUSTRY, "hithink-industry-query", [{}], query="动力电池 行业估值"),
            _result(
                Domain.COMPANIES,
                "hithink-basicinfo-query",
                [{"股票代码": "300750", "股票简称": "宁德时代"}],
                query="宁德时代 基本信息",
            ),
        ],
        AS_OF,
    )
    assert all(r.metric != "record" for r in dataset.all_records())
    assert not dataset.industry
    # 身份记录仍由 company 通道产出
    assert [r.metric for r in dataset.companies] == ["entity_identity"]
    assert dataset.quality_summary["structured_record_count"] == 1


def test_future_dated_long_table_row_dropped():
    """长表行的日期晚于 as_of 时丢弃，并计入 dropped_future_records。"""
    rows = REAL_LONG_TABLE_ROWS + [
        {"时间": "20271231", "指标": "动力电池出口量", "指标值": 999999.0,
         "单位": "兆瓦时", "国家": "中国"},
    ]
    dataset = DataFusion().fuse(
        [_result(Domain.INDUSTRY, "hithink-industry-query", rows)], AS_OF
    )
    assert len(dataset.industry) == 4
    assert all(r.period_end.year <= 2025 for r in dataset.industry)
    assert dataset.quality_summary["dropped_future_records"] == 1


def test_long_table_records_keep_audit_trail_without_polluting_issues():
    """守卫记录质量口径：正确解析的长表记录不写 issues（否则会虚增
    records_with_issues、污染 A2 的数据质量披露），原始长表键保留在 raw_fields 供审计。
    """
    dataset = DataFusion().fuse(
        [_result(Domain.INDUSTRY, "hithink-industry-query", REAL_LONG_TABLE_ROWS)], AS_OF
    )
    assert all(r.issues == [] for r in dataset.industry)
    assert dataset.quality_summary["records_with_issues"] == 0
    raw = dataset.industry[0].raw_fields
    for key in ("时间", "指标", "指标值", "周期", "macro_id", "macro_name", "单位"):
        assert key in raw
