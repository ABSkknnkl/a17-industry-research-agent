"""P0-1：源表期间字段必须优先于年末日期形状。

真实缺陷样本：`国内零售渗透率:新能源汽车:当月值` 的源行长表带着
`周期=月`、`时间=20251231`，A1 只按日期推导成 annual / 2025-01-01 起日，
于是月度观测被放行成全年口径。这里固定三条边界：
1. 当月值 + 周期=月 → month，起日为当月月初；
2. 累计值 + 周期=月 → 保留全年累计口径（合法年报推导）；
3. 源字段彼此冲突 → 记 period_conflict，退出量化核验与年度覆盖。
"""

from datetime import date, datetime, timezone

from data_fetcher.fusion import DataFusion
from data_fetcher.models import Domain, SkillResult
from agents_core.financial_semantics import measurement_period

AS_OF = date(2026, 11, 9)

MONTHLY_PENETRATION_ROW = {
    "时间": "20251231",
    "指标": "新能源汽车渗透率",
    "指标值": 59.1,
    "周期": "月",
    "macro_id": "S009287586",
    "macro_name": "国内零售渗透率:新能源汽车:当月值",
    "单位": "%",
    "国家": "中国",
    "地区级别": ["国家"],
}


def _fuse(rows: list[dict]) -> SkillResult:
    return DataFusion().fuse(
        [SkillResult(
            task_id="annual_industry_nev_penetration",
            skill_name="hithink-industry-query",
            skill_id="hithink-industry-query",
            skill_version="1.0.0",
            domain=Domain.INDUSTRY,
            query="中国新能源汽车市场渗透率 全年 年度序列",
            trace_id="fixture",
            records=rows,
            success=True,
        )],
        AS_OF,
    )


def test_month_source_period_wins_over_year_end_shape():
    dataset = _fuse([MONTHLY_PENETRATION_ROW])
    record = dataset.industry[0]
    assert record.metric == "国内零售渗透率:新能源汽车:当月值"
    assert record.period_type == "month"
    assert record.period_start == date(2025, 12, 1)
    assert record.period_end == date(2025, 12, 31)
    assert record.issues == []


def test_cumulative_source_period_stays_annual():
    """`周期=月` 描述序列频率，累计值语义仍是全年累计，不能被降成单月。"""
    dataset = _fuse([{
        "时间": "20251231",
        "指标": "动力电池出口量",
        "指标值": 189700.0,
        "周期": "月",
        "macro_id": "S018915880",
        "macro_name": "动力电池:出口量:合计:累计值",
        "单位": "兆瓦时",
        "国家": "中国",
    }])
    record = dataset.industry[0]
    assert record.period_type == "annual"
    assert record.period_start == date(2025, 1, 1)
    assert record.issues == []


def test_conflicting_source_period_fields_are_flagged_and_excluded():
    row = {**MONTHLY_PENETRATION_ROW, "期间类型": "年度"}
    dataset = _fuse([row])
    record = dataset.industry[0]
    assert "period_conflict" in record.issues
    # 冲突记录保留原值供审查，但不取得任何可比较期间。
    assert measurement_period(record) is None


def test_independent_annual_observation_keeps_annual_shape():
    dataset = _fuse([{
        "时间": "20251231",
        "指标": "新能源汽车渗透率",
        "指标值": 59.1,
        "周期": "年",
        "macro_name": "新能源汽车:渗透率:年度",
        "单位": "%",
        "国家": "中国",
    }])
    record = dataset.industry[0]
    assert record.period_type == "annual"
    assert record.period_start == date(2025, 1, 1)
    assert measurement_period(record) == (date(2025, 1, 1), date(2025, 12, 31), "annual")


def test_same_value_month_and_annual_observations_stay_distinct():
    dataset = _fuse([
        MONTHLY_PENETRATION_ROW,
        {
            "时间": "20251231",
            "指标": "新能源汽车渗透率",
            "指标值": 59.1,
            "周期": "年",
            "macro_name": "新能源汽车:渗透率:年度",
            "单位": "%",
            "国家": "中国",
        },
    ])
    kinds = {(r.period_type, r.period_start) for r in dataset.industry}
    assert kinds == {("month", date(2025, 12, 1)), ("annual", date(2025, 1, 1))}
    for record in dataset.industry:
        assert measurement_period(record) is not None
