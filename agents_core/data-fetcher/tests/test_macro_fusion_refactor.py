import pytest
from datetime import date
from data_fetcher.models import Domain, SkillResult
from data_fetcher.fusion import DataFusion


def test_macro_tabular_records_atomically_fused():
    raw_macro_rows = [
        {"时间": "20231231", "指标": "GDP", "指标值": 129427170000000.0, "单位": "元", "国家": "中国"},
        {"时间": "20241231", "指标": "GDP", "指标值": 134806620000000.0, "单位": "元", "国家": "中国"},
        {"时间": "20251231", "指标": "GDP", "指标值": 140187920000000.0, "单位": "元", "国家": "中国"},
    ]
    skill_result = SkillResult(
        task_id="t_macro",
        skill_name="iwencai-macro-query",
        skill_id="iwencai-macro-timeseries",
        skill_version="1.0.0",
        domain=Domain.MACRO,
        query="中国近三年GDP",
        trace_id="tr_m",
        records=raw_macro_rows,
        success=True,
    )
    fusion = DataFusion()
    dataset = fusion.fuse([skill_result], as_of=date(2026, 1, 1))

    # Currently it will fail because it unpivots each row into multiple records (时间, 指标, 指标值, 单位, 国家)
    assert len(dataset.macro) == 3
    metrics = [r.metric for r in dataset.macro]
    assert metrics == ["GDP", "GDP", "GDP"]
    assert dataset.macro[0].value == 129427170000000.0
    assert dataset.macro[0].unit == "元"
    assert dataset.macro[0].period_end == date(2023, 12, 31)
    assert dataset.macro[0].entity_name in ("中国", "全国")
