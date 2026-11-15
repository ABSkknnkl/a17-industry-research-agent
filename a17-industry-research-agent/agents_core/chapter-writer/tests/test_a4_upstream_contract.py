"""P1：A2/A3 窄字段契约在 A4 的解析、装包与提示白名单。"""

import json
from datetime import date

from chapter_writer.agent import SYSTEM_PROMPT, prepare_chapter_context
from chapter_writer.models import (
    ChapterWritingRequest,
    ChartRef,
    ChartResult,
    InterpretationReport,
)
from chapter_writer.outline import DEFAULT_OUTLINE
from chapter_writer.retriever import DynamicEvidenceRetriever


def report_with_upstream_fields() -> InterpretationReport:
    return InterpretationReport.model_validate({
        "report_id": "rep-p1",
        "subject": "新能源汽车",
        "as_of": "2026-11-09",
        "status": "completed",
        "data_quality_appendix": {
            "requirement_evidence_matrix": [{
                "requirement": {"requirement_id": "nev.q1.annual_penetration",
                                "domain": "financials", "hard": True},
                "coverage": {"passed": False},
            }],
        },
        "evidence_index": {
            "R-VERDICT": {
                "record_id": "R-VERDICT", "domain": "financials", "entity": "甲公司",
                "metric": "毛利率", "value": 22.5, "unit": "%", "period": "2025-12-31",
                "period_start": "2025-01-01", "period_type": "annual", "skill_id": "fixture",
                "trace_id": "fixture",
            },
            "R-OTHER": {
                "record_id": "R-OTHER", "domain": "financials", "entity": "乙公司",
                "metric": "毛利率", "value": 18.0, "unit": "%", "period": "2025-12-31",
                "period_start": "2025-01-01", "period_type": "annual", "skill_id": "fixture",
                "trace_id": "fixture",
            },
        },
        "chain_analysis": {
            "method": "reviewed_chain_facts_group_comparison",
            "hypothesis_verdicts": [
                {
                    "hypothesis_id": "H-01",
                    "statement": "中游材料价格回落带动毛利率修复",
                    "verdict": "partially_supported",
                    "required_evidence": ["毛利率", "现金流"],
                    "covered_evidence": ["分组毛利率走势"],
                    "basis": "仅 1/2 项要求有序列支撑",
                },
                {
                    "hypothesis_id": "H-02",
                    "statement": "垂直整合可稳定供应",
                    "verdict": "insufficient_evidence",
                    "required_evidence": ["供应关系"],
                    "covered_evidence": [],
                    "basis": "所需证据不在 A1 数据底座内",
                },
                {
                    "hypothesis_id": "H-BAD",
                    "statement": "无法核验的判定",
                    "verdict": "certain",
                    "required_evidence": [],
                    "covered_evidence": [],
                    "basis": "",
                },
            ],
        },
        "analysis_facts": {
            "observations": [
                {"record_id": "R-VERDICT", "entity": "甲公司", "metric": "毛利率",
                 "value": 22.5, "unit": "%", "period": "2025-12-31",
                 "period_start": "2025-01-01", "period_type": "annual"},
                {"record_id": "R-ABSENT", "entity": "丙公司", "metric": "毛利率",
                 "value": 30.0, "unit": "%", "period": "2025-12-31",
                 "period_start": "2025-01-01", "period_type": "annual"},
            ],
            "comparisons": [
                {"from_record_id": "R-VERDICT", "to_record_id": "R-OTHER",
                 "direction": "down", "absolute_change": -4.5},
                {"from_record_id": "R-ABSENT", "to_record_id": "R-OTHER",
                 "direction": "up", "absolute_change": 12.0},
            ],
            "conflicts": [],
            "coverage": [],
        },
        "semantic_checks": [
            {"location": "executive_summary", "original": "全年毛利率达到 99%（错误句）",
             "replacement": "年度毛利率为 22.5%", "status": "reconciled",
             "metrics": ["毛利率"], "evidence_record_ids": ["R-VERDICT"]},
            {"location": "other", "original": "别章错误句",
             "replacement": "无", "status": "reconciled",
             "metrics": ["毛利率"], "evidence_record_ids": ["R-ABSENT"]},
        ],
    })


def charts_with_upstream_fields() -> ChartResult:
    return ChartResult.model_validate({
        "charts": [{
            "chart_id": "CHART-GM", "title": "毛利率趋势", "chart_type": "line",
            "status": "ready", "evidence_ids": ["R-VERDICT", "R-OTHER"],
            "recommended_chapter_id": "CH-05",
            "footnotes": ["单位：%", "来源：公司年报", "口径：合并报表", "期间：2025 年度"],
            "point_evidence_ids": ["R-VERDICT", "R-ABSENT"],
            "data_contract": {
                "points": [
                    {"record_id": "R-VERDICT", "value": 22.5, "period_type": "annual",
                     "period_start": "2025-01-01", "unit": "%", "scope": "consolidated"},
                    {"record_id": "R-ABSENT", "value": 30.0, "period_type": "annual",
                     "period_start": "2025-01-01", "unit": "%", "scope": "consolidated"},
                ],
                "observation_range": {"start": "2025-01-01", "end": "2025-12-31"},
                "source": "fixture",
            },
        }],
        "suppressed_charts": [
            {"title": "渗透率年度图", "requested_type": "line", "reason_code": "missing_annual",
             "reason": "缺少同范围年度分子分母", "evidence_ids": ["R-VERDICT"]},
            {"title": "别章图", "requested_type": "bar", "reason_code": "other",
             "reason": "与本章无关", "evidence_ids": ["R-ABSENT"]},
        ],
        "question_coverage": [
            {"requirement_id": "nev.q1.annual_penetration", "status": "gap",
             "reason": "年度证据缺口", "evidence_ids": ["R-VERDICT"]},
            {"requirement_id": "other.requirement", "status": "covered"},
        ],
    })


def test_old_report_and_chart_json_still_parse():
    old_report = InterpretationReport.model_validate({
        "report_id": "old", "subject": "测试", "as_of": "2026-01-01", "status": "completed",
    })
    assert old_report.chain_analysis is None
    assert old_report.analysis_facts == {}
    old_chart = ChartResult.model_validate({"charts": [{
        "chart_id": "C1", "title": "旧图", "chart_type": "line",
    }]})
    assert old_chart.charts[0].data_contract == {}
    assert old_chart.charts[0].footnotes == []
    assert old_chart.suppressed_charts == []


def test_retriever_keeps_narrow_fields_and_filters_by_evidence():
    request = ChapterWritingRequest(report=report_with_upstream_fields(), charts=charts_with_upstream_fields())
    context = DynamicEvidenceRetriever(request).retrieve(
        "CH-05", next(c for c in DEFAULT_OUTLINE if c.chapter_id == "CH-05"))

    verdicts = context["hypothesis_verdicts"]
    assert {v["hypothesis_id"] for v in verdicts} == {"H-01", "H-02", "H-BAD"}
    # 覆盖说明不是 record_id，不能变成证据白名单键。
    assert "分组毛利率走势" not in context["evidence"]
    assert context["verdict_diagnostics"][0]["hypothesis_id"] == "H-BAD"

    facts = context["analysis_facts"]
    assert [o["record_id"] for o in facts["observations"]] == ["R-VERDICT"]
    assert [(c["from_record_id"], c["to_record_id"]) for c in facts["comparisons"]] == [
        ("R-VERDICT", "R-OTHER")
    ]
    checks = context["semantic_checks"]
    assert [c["location"] for c in checks] == ["executive_summary"]
    assert "original" not in checks[0]
    assert "99%" not in json.dumps(context, ensure_ascii=False)

    chart = context["charts"][0]
    assert [p["record_id"] for p in chart["data_contract"]["points"]] == ["R-VERDICT"]
    assert chart["data_contract"]["observation_range"]["start"] == "2025-01-01"
    assert len(chart["footnotes"]) == 4
    assert chart["point_evidence_ids"] == ["R-VERDICT"]

    # 问题覆盖按本章主答需求过滤；抑制图只保留与本章证据相交的条目。
    assert [row["requirement_id"] for row in context["question_coverage"]] == [
        "nev.q1.annual_penetration"
    ]


def test_prompt_whitelist_matches_the_packed_context():
    request = ChapterWritingRequest(report=report_with_upstream_fields(), charts=charts_with_upstream_fields())
    context = DynamicEvidenceRetriever(request).retrieve(
        "CH-05", next(c for c in DEFAULT_OUTLINE if c.chapter_id == "CH-05"))
    prompt, _ = prepare_chapter_context(
        {"outline": {"chapter_id": "CH-05"}, "context": context}, SYSTEM_PROMPT
    )
    packed = json.loads(prompt)
    for key in ("hypothesis_verdicts", "analysis_facts", "semantic_checks",
                "question_coverage", "suppressed_charts"):
        assert key in packed["context"]
    for key in ("hypothesis_verdicts", "analysis_facts", "semantic_checks",
                "question_coverage", "suppressed_charts", "data_contract"):
        assert key in SYSTEM_PROMPT
