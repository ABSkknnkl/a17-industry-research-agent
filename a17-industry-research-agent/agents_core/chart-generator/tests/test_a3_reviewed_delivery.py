import asyncio
from dataclasses import replace
import json
from pathlib import Path
from datetime import date

import pytest

from chart_generator.agent import ChartGeneratorAgent, _Candidate
from chart_generator.config import Settings
from chart_generator.models import (
    ChartGenerationRequest,
    ChartPreferences,
    EvidenceRef,
    InterpretationReport,
)


def ref(rid, entity, metric="gross_margin", value=12.3456, unit="%", domain="financials", year=2025):
    return EvidenceRef(
        record_id=rid, domain=domain, entity=entity, metric=metric, value=value, unit=unit,
        period=date(year, 12, 31), period_start=date(year, 1, 1), period_type="annual",
        period_provenance="row",
    )


def report_for(*refs, **kwargs):
    return InterpretationReport(
        report_id="A2", subject="新能源汽车", as_of=date(2026, 11, 9), status="completed",
        evidence_index={row.record_id: row for row in refs}, **kwargs,
    )


class MixedLLM:
    is_available = True

    async def run_skill_and_chart_loop(self, **kwargs):
        return [], {
            "suppressed_charts": [{"requested_type": [], "evidence_ids": None}],
            "charts": [
                {"chart_type": [], "evidence_ids": 123},
                {"chart_type": "radar", "evidence_ids": ["gm", "roe", "sales"]},
                {"chart_type": "bar", "evidence_ids": ["gm", "gm2"],
                 "option": {"series": [{"data": [9999, 9999]}]}, "footnotes": None},
            ],
        }


def test_bad_model_rows_keep_good_llm_candidate_and_ignore_model_numbers():
    report = report_for(
        ref("gm", "宁德时代"), ref("gm2", "亿纬锂能"),
        ref("roe", "宁德时代", "roe"), ref("sales", "宁德时代", "销量", 10, "辆", year=2024),
    )
    events = []

    async def emit(event):
        events.append(event)

    result = asyncio.run(ChartGeneratorAgent(llm=MixedLLM()).run(
        ChartGenerationRequest(report=report, preferences=ChartPreferences(max_charts=1)),
        emit=emit, save_artifacts=False,
    ))
    assert any(event["event"] == "llm_candidate_rejected" for event in events)
    assert any(event["event"] == "chart_ready" and event["details"]["selection_source"] == "llm"
               for event in events)
    assert len(result.charts) == 1
    assert {p["value"] for p in result.charts[0].data_contract["points"]} == {12.3456}


def test_reviewed_cohorts_reject_mixed_company_ranking_and_chain_valuation():
    report = report_for(
        ref("a", "宁德时代"), ref("b", "亿纬锂能"),
        ref("c", "比亚迪"), ref("d", "赛力斯"),
        ref("pe-a", "宁德时代", "pe_dynamic", 20, "倍", domain="industry_chain"),
        ref("pe-b", "中国中车", "pe_dynamic", 30, "倍", domain="industry_chain"),
        chain_analysis={"method": "reviewed_chain_facts_group_comparison",
                        "groups": {"电池组": {"members": ["宁德时代", "亿纬锂能"]},
                                   "整车组": {"members": ["比亚迪", "赛力斯"]}}},
    )
    agent = ChartGeneratorAgent()
    for ids in (["a", "b", "c", "d"], ["pe-a", "pe-b"]):
        assert agent._verify_numeric_candidate(_Candidate("比较", "bar", {}, ids, "", "CH-05"), report)
    candidates, _ = agent._deterministic_fallback(ChartGenerationRequest(report=report))
    cohorts = {frozenset(c.evidence_ids) for c in candidates
               if c.chart_type == "bar" and not agent._verify_numeric_candidate(c, report)}
    assert {frozenset(("a", "b")), frozenset(("c", "d"))} <= cohorts


def test_radar_rejects_mixed_units_and_periods_without_downgrading_to_a_bar():
    report = report_for(
        ref("gm", "宁德时代"), ref("roe", "宁德时代", "roe"),
        ref("sales", "宁德时代", "销量", 10, "辆", year=2024),
    )
    candidate = _Candidate("雷达", "radar", {}, list(report.evidence_index), "", "CH-05")
    assert ChartGeneratorAgent()._verify_numeric_candidate(candidate, report)


@pytest.mark.parametrize(("explicit", "defaulted", "types", "wanted"), [
    (False, False, ["industry_chain"], False),
    (True, False, ["industry_chain"], True),
    (None, False, [], True),
    (None, True, [], False),
])
def test_reviewed_chain_uses_three_segments_and_respects_intent(
    tmp_path, monkeypatch, explicit, defaulted, types, wanted,
):
    monkeypatch.delenv("CHAIN_INTENT_OVERRIDE", raising=False)
    report = report_for(
        ref("a", "宁德时代"), ref("b", "比亚迪"),
        industry_chain_topology={"nodes": [{"id": "wrong", "label": "旧拓扑", "stage": "support"}]},
        industry_chain_segments=[
            {"segment_name": "材料", "stage": "upstream", "source_tier": "gap",
             "attribution_basis": "chain_facts:vehicle@2026-11-09", "gap_declaration": "上游未纳入样本"},
            {"segment_name": "电池", "stage": "midstream", "source_tier": "reviewed_profile",
             "attribution_basis": "chain_facts:vehicle@2026-11-09", "representative_companies": ["宁德时代"]},
            {"segment_name": "整车", "stage": "downstream", "source_tier": "reviewed_profile",
             "attribution_basis": "chain_facts:vehicle@2026-11-09", "representative_companies": ["比亚迪"]},
        ],
    )
    agent = ChartGeneratorAgent(settings=replace(Settings.from_env(), output_dir=tmp_path))
    result = asyncio.run(agent.run(ChartGenerationRequest(
        report=report, want_industry_chain=explicit, focus_points=["分析产业链"],
        defaulted_focus=defaulted, preferences=ChartPreferences(requested_types=types),
    )))
    charts = [chart for chart in result.charts if chart.chart_type == "industry_chain"]
    assert bool(charts) is wanted
    if wanted:
        assert "上游未纳入样本" in charts[0].inline_svg
        assert "旧拓扑" not in charts[0].inline_svg
        assert "宁德时代" in charts[0].inline_svg and "比亚迪" in charts[0].inline_svg
        assert "整车设计与研发" not in charts[0].inline_svg
        assert "配套：服务" not in charts[0].inline_svg
        assert [s["stage_id"] for s in charts[0].chain_graph["stages"]] == [
            "upstream", "midstream", "downstream",
        ]
        assert result.chain_quality["passed"]
        assert charts[0].evidence_ids == []
        assert charts[0].insight_goal == "展示 A2 已审的产业环节和样本覆盖。"
        assert {stage["stage_id"]: stage["title"] for stage in charts[0].chain_graph["stages"]} == {
            node["stage"]: node["name"] for node in charts[0].chain_graph["nodes"]
        }
        option_file = Path(result.artifact_dir) / "charts" / f"{charts[0].chart_id}.json"
        assert json.loads(option_file.read_text()) == charts[0].option


def test_derived_rd_rate_recomputes_both_inputs_and_refuses_missing_or_mismatched_data():
    refs = [
        ref(f"{company}-{metric}-{year}", company, metric, value, "元", year=year)
        for year in (2024, 2025) for company, cost, revenue in (("甲", 10, 100), ("乙", 10, 300))
        for metric, value in (("rd_expense", cost), ("revenue", revenue))
    ]
    analysis = {
        "method": "reviewed_chain_facts_group_comparison",
        "groups": {"电池组": {"members": ["甲", "乙"], "series": {"rd_ratio_derived": {
            "years": [2024, 2025], "group_mean": {"2024": 0.05, "2025": 0.05},
            "evidence_record_ids": [row.record_id for row in refs],
        }}}},
    }
    for broken in (None, "missing", "mismatch"):
        report = report_for(*refs, chain_analysis=analysis)
        if broken == "missing":
            del report.evidence_index[refs[0].record_id]
        elif broken == "mismatch":
            report.evidence_index[refs[0].record_id] = refs[0].model_copy(update={"value": 80})
        result = asyncio.run(ChartGeneratorAgent().run(
            ChartGenerationRequest(report=report), save_artifacts=False,
        ))
        derived = [chart for chart in result.charts if chart.data_contract.get("calculation")]
        if broken:
            assert not derived
        else:
            assert len(derived) == 1
            assert [p["value"] for p in derived[0].data_contract["points"]] == [5, 5]
            assert all(len(p["source_record_ids"]) == 4 for p in derived[0].data_contract["points"])


def test_monthly_industry_observations_keep_source_period_metadata():
    rows = [
        ref("mar", "中国", "国内零售渗透率:新能源汽车:当月值", 51.1, domain="industry").model_copy(
            update={"period": date(2025, 3, 31), "period_type": "q1"}),
        ref("dec", "中国", "国内零售渗透率:新能源汽车:当月值", 59.1, domain="industry"),
    ]
    report = report_for(*rows)
    candidate = _Candidate("渗透率趋势", "line", {}, ["mar", "dec"], "", "CH-02")
    assert ChartGeneratorAgent()._verify_numeric_candidate(candidate, report) is None
    contract = candidate.data_contract
    assert contract["observation_range"] == {"start": "2025-03-31", "end": "2025-12-31"}
    assert [point["period_type"] for point in contract["points"]] == ["q1", "annual"]
    assert [point["observation_period_type"] for point in contract["points"]] == ["month", "month"]


@pytest.mark.parametrize("source", ["llm", "llm_repair"])
def test_one_compiler_value_error_does_not_discard_other_proposals(monkeypatch, source):
    report = report_for(
        ref("gm", "甲"), ref("gm2", "乙"),
        ref("roe", "甲", "roe"), ref("roe2", "乙", "roe"),
    )
    agent = ChartGeneratorAgent()
    verify = agent._verify_numeric_candidate

    def compiler_failure(candidate, report):
        if candidate.evidence_ids == ["roe", "roe2"]:
            raise ValueError("incompatible chart candidate")
        return verify(candidate, report)

    monkeypatch.setattr(agent, "_verify_numeric_candidate", compiler_failure)
    events = []

    async def record(event, **details):
        events.append((event, details))

    candidates, rejected = asyncio.run(agent._parse_llm_plan({
        "charts": [
            {"chart_type": "bar", "evidence_ids": ["roe", "roe2"]},
            {"chart_type": "bar", "evidence_ids": ["gm", "gm2"]},
        ],
    }, ChartGenerationRequest(report=report), record, source))

    assert [item.selection_source for item in candidates] == [source]
    assert [item.evidence_ids for item in candidates] == [["gm", "gm2"]]
    assert [item.evidence_ids for item in rejected] == [["roe", "roe2"]]
    assert ("llm_candidate_compile_error", {"source": source, "index": 0, "error": "ValueError"}) in events


def test_automatic_model_bars_for_trends_use_the_same_semantic_key_as_lines():
    report = report_for(ref("2024", "甲", year=2024), ref("2025", "甲"))
    agent = ChartGeneratorAgent()

    async def record(event, **details):
        pass

    payload = {"charts": [
        {"chart_type": "comparison_bar", "evidence_ids": ["2024", "2025"]},
        {"chart_type": "line", "evidence_ids": ["2024", "2025"]},
    ]}
    candidates, _ = asyncio.run(agent._parse_llm_plan(
        payload, ChartGenerationRequest(report=report), record, "llm",
    ))
    assert [candidate.chart_type for candidate in candidates] == ["line", "line"]
    assert len({agent._candidate_semantic_key(c, report.evidence_index) for c in candidates}) == 1
    requested, _ = asyncio.run(agent._parse_llm_plan(
        payload, ChartGenerationRequest(
            report=report, preferences=ChartPreferences(requested_types=["comparison_bar"]),
        ), record, "llm",
    ))
    assert requested[0].chart_type == "comparison_bar"
