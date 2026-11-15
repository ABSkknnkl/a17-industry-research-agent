"""P2：上游叙述按可核验子句保留，错误数字不整条删除。"""

from chapter_writer import retriever


EVIDENCE = {
    "R1": {
        "record_id": "R1", "entity": "甲公司", "metric": "营业收入",
        "value": 1000000000, "unit": "元", "period": "2023-12-31",
        "period_start": "2023-01-01", "period_type": "annual",
        "scope": "consolidated", "currency": "CNY",
    },
}


def test_mixed_sentence_keeps_supported_clause_and_drops_unsupported_number():
    rows = [{
        "subject": "甲公司", "predicate": "营业收入",
        "object_summary": "2023年营业收入为10亿元。2023年净利润为5亿元。",
        "evidence_record_ids": ["R1"],
    }]
    kept, removed = retriever.filter_unverified_findings(rows, EVIDENCE)
    assert len(kept) == 1
    assert "10亿元" in kept[0]["object_summary"]
    assert "5亿元" not in kept[0]["object_summary"]
    assert kept[0]["evidence_record_ids"] == ["R1"]
    assert removed == 1


def test_supported_finding_is_not_altered_by_the_filter():
    rows = [{
        "subject": "甲公司", "predicate": "营业收入",
        "object_summary": "2023年营业收入为10亿元。",
        "claim": "公司收入规模保持稳定。",
        "key_points": ["年收入为 10 亿元。"],
        "evidence_record_ids": ["R1"],
    }]
    kept, removed = retriever.filter_unverified_findings(rows, EVIDENCE)
    assert removed == 0
    assert kept[0]["object_summary"] == rows[0]["object_summary"]
    assert kept[0]["claim"] == rows[0]["claim"]
    assert kept[0]["key_points"] == rows[0]["key_points"]


def test_fully_unsupported_finding_keeps_field_shape_not_number():
    rows = [{
        "subject": "乙公司", "predicate": "装机量",
        "object_summary": "2023年装机量达 387.7GWh。",
        "evidence_record_ids": ["R1"],
    }]
    kept, removed = retriever.filter_unverified_findings(rows, EVIDENCE)
    assert len(kept) == 1
    assert kept[0]["subject"] == "乙公司" and kept[0]["predicate"] == "装机量"
    assert kept[0]["object_summary"] == ""
    assert kept[0]["evidence_record_ids"] == ["R1"]
    assert removed == 1
