import asyncio
from datetime import date, datetime, timezone
import json

import pytest

from data_fetcher.models import (
    Domain, ResearchRecord, ResearchRequirement, SourceRef, StructuredResearchDataset,
)
from data_fetcher.agent import DataFetcherAgent
from data_fetcher.dynamic_probe import ProbeOutcome


AS_OF = date(2026, 11, 17)


def record(metric, entity="甲公司", period=date(2025, 12, 31), *, issues=None):
    return ResearchRecord(
        record_id=f"{entity}-{metric}-{period.year}", domain=Domain.FINANCIALS,
        entity_name=entity, entity_code="000001.SZ", metric=metric, value=120,
        unit="元", period_start=date(period.year, 1, 1), period_end=period,
        period_type="annual", scope="consolidated", issues=issues or [],
        source=SourceRef(task_id="probe", skill_id="hithink-finance-query", skill_version="1",
                         query=f"{entity} {metric}", trace_id="a" * 64,
                         status="success",
                         retrieved_at=datetime.now(timezone.utc)),
    )


def dataset(metrics):
    result = StructuredResearchDataset(subject="测试行业", research_as_of=AS_OF)
    rows = []
    for domain, metric in metrics:
        req = ResearchRequirement(
            requirement_id=f"{domain}-{metric}", label=f"甲公司2025年{metric}", domain=domain,
            entity_names=["甲公司"], period_ends=[date(2025, 12, 31)], metric_families=[metric],
        )
        rows.append({"requirement": req.model_dump(mode="json"),
                     "coverage": DataFetcherAgent._evaluate_requirement(result, req).model_dump(mode="json")})
    result.quality_summary["requirement_evidence_matrix"] = rows
    return result


def install_probe(monkeypatch, calls, *, succeeds=True):
    from data_fetcher import dynamic_probe

    async def probe(demand, as_of, *, before_call, on_attempt, accept_records, **kwargs):
        calls.append(demand)
        records = [record(demand["metrics"][0])]
        for attempt in range(1, 5):
            if not await before_call("llm", {"attempt": attempt}):
                return ProbeOutcome("budget_exhausted")
            if not await before_call("skill", {"query": demand["query_hint"], "attempt": attempt}):
                return ProbeOutcome("budget_exhausted")
            audit = {"attempt": attempt, "round": attempt, "query": demand["query_hint"],
                     "skill_id": "hithink-finance-query", "trace_id": "a" * 64}
            await on_attempt(audit)
            if succeeds:
                return ProbeOutcome("success", accept_records(records), [audit])
        return ProbeOutcome("no_data", attempts=[audit])

    monkeypatch.setattr(dynamic_probe, "run_dynamic_probe", probe)


@pytest.mark.anyio
async def test_gap_scan_limits_each_chapter_and_replays_cached_evidence(tmp_path, monkeypatch):
    from backend.app.agents.gap_scan import scan_and_supplement

    metrics = [("financials", metric) for metric in ("revenue", "net_profit", "rd_expense", "operating_cash_flow")]
    original = dataset(metrics)
    calls = []
    install_probe(monkeypatch, calls)
    summary = await scan_and_supplement(original, AS_OF, tmp_path, context={"input": "stable"})
    assert len(calls) == 3
    assert summary["calls_used"] == 6 and summary["chapter_points"] == {"CH-05": 3}
    assert summary["remaining_requirements"] == 1
    assert len(original.financials) == 3
    assert all(r.raw_fields["auto_probe"]["round"] == 1 for r in original.financials)
    assert all(r.source.trace_id for r in original.financials)
    assert any(row["reason"] == "chapter_point_limit" for row in summary["skipped"])
    replay = dataset(metrics)
    repeated = await scan_and_supplement(replay, AS_OF, tmp_path, context={"input": "stable"})
    assert len(calls) == 3 and repeated["calls_used"] == 6
    assert {r.record_id for r in replay.financials} == {r.record_id for r in original.financials}


@pytest.mark.anyio
async def test_gap_scan_hard_budget_counts_llm_and_skill_requests(tmp_path, monkeypatch):
    from backend.app.agents.gap_scan import scan_and_supplement

    ds = dataset([("financials", "revenue"), ("financials", "net_profit"), ("industry", "market_size")])
    calls = []
    install_probe(monkeypatch, calls, succeeds=False)
    result = await scan_and_supplement(ds, AS_OF, tmp_path, context={})
    assert result["calls_used"] == 12
    assert len(calls) == 2 and result["status"] == "budget_exhausted"
    assert result["remaining_requirements"] == 3
    journal = json.loads((tmp_path / "auto_probe.json").read_text())
    assert len(journal["calls"]) == 12
    await scan_and_supplement(ds, AS_OF, tmp_path, context={})
    assert len(calls) == 2


@pytest.mark.anyio
async def test_gap_scan_skips_passed_soft_and_unstructured_requirements(tmp_path, monkeypatch):
    from backend.app.agents.gap_scan import scan_and_supplement

    ds = dataset([("financials", "revenue")])
    ds.financials.append(record("revenue"))
    row = ds.quality_summary["requirement_evidence_matrix"][0]
    row["coverage"]["passed"] = True
    ds.quality_summary["requirement_evidence_matrix"].extend([
        {"requirement": ResearchRequirement(requirement_id="soft", label="可选", domain=Domain.FINANCIALS,
                                           hard=False, metric_families=["net_profit"]).model_dump(mode="json"),
         "coverage": {"passed": False}},
        {"requirement": ResearchRequirement(requirement_id="domain_macro", label="宏观覆盖", domain=Domain.MACRO).model_dump(mode="json"),
         "coverage": {"passed": False}},
    ])
    calls = []
    install_probe(monkeypatch, calls)
    result = await scan_and_supplement(ds, AS_OF, tmp_path, context={})
    assert not calls and result["calls_used"] == 0


@pytest.mark.anyio
async def test_gap_scan_rejects_wrong_period_and_quality_issues(tmp_path, monkeypatch):
    from backend.app.agents.gap_scan import scan_and_supplement
    from data_fetcher import dynamic_probe

    ds = dataset([("financials", "revenue")])

    async def probe(demand, as_of, *, accept_records, **kwargs):
        invalid = [record("revenue", period=date(2024, 12, 31)),
                   record("revenue", issues=["unit_unknown"]), record("net_profit")]
        assert accept_records(invalid) == []
        return ProbeOutcome("no_data")

    monkeypatch.setattr(dynamic_probe, "run_dynamic_probe", probe)
    result = await scan_and_supplement(ds, AS_OF, tmp_path, context={})
    assert not ds.financials and result["remaining_requirements"] == 1


@pytest.mark.anyio
async def test_gap_scan_cancelled_requests_keep_reservations(tmp_path, monkeypatch):
    from backend.app.agents.gap_scan import scan_and_supplement
    from data_fetcher import dynamic_probe

    ds = dataset([("financials", "revenue")])

    async def cancelled(demand, as_of, *, before_call, **kwargs):
        assert await before_call("llm", {"attempt": 1})
        raise asyncio.CancelledError

    monkeypatch.setattr(dynamic_probe, "run_dynamic_probe", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await scan_and_supplement(ds, AS_OF, tmp_path, context={})
    journal = json.loads((tmp_path / "auto_probe.json").read_text())
    assert len(journal["calls"]) == 1
    calls = []
    install_probe(monkeypatch, calls)
    result = await scan_and_supplement(ds, AS_OF, tmp_path, context={})
    assert not calls and result["calls_used"] == 1
    assert result["points"][0]["status"] == "interrupted"


@pytest.mark.anyio
@pytest.mark.parametrize("enabled", [True, False])
async def test_a1_runs_gap_scan_before_publishing_and_respects_switch(tmp_path, monkeypatch, enabled):
    from backend.app.agents.adapters import FiveAgentsAdapter
    from backend.app.core.storage import storage
    from backend.app.schemas.workflow import RunExecutionSnapshot
    from data_fetcher.models import Coverage, RequirementCoverage, ResearchRunResult

    monkeypatch.setattr(storage, "base_dir", tmp_path)
    run_id = "a1-auto-probe"
    run_dir = storage.get_run_dir(run_id)
    (run_dir / "execution_snapshot.json").write_text(RunExecutionSnapshot(
        auto_probe_enabled=enabled, chain_requested=False,
    ).model_dump_json(), encoding="utf-8")
    ds = dataset([("financials", "revenue")])
    req = ResearchRequirement.model_validate(ds.quality_summary["requirement_evidence_matrix"][0]["requirement"])
    check = RequirementCoverage.model_validate(ds.quality_summary["requirement_evidence_matrix"][0]["coverage"])

    async def main_fetch(*args, **kwargs):
        return ResearchRunResult(
            run_id=run_id, status="partial", stop_reason="skill_budget_exhausted", dataset=ds,
            model_requirements=[req], coverage=Coverage(
                required_domains=[Domain.FINANCIALS], covered_domains=[], missing_domains=[Domain.FINANCIALS],
                score=0, complete=False, requirement_coverage=[check],
            ),
        )

    calls = []
    monkeypatch.setattr(DataFetcherAgent, "run", main_fetch)
    install_probe(monkeypatch, calls)
    result = await FiveAgentsAdapter.run_data_fetcher(
        run_id=run_id, industry="半导体设备", focus_points=["2025年甲公司营业收入"], research_as_of=str(AS_OF),
    )
    assert bool(calls) is enabled
    assert result.data["auto_probe"]["status"] == ("completed" if enabled else "disabled")
    assert result.data["metric_requirements"][0]["passed"] is enabled
    assert ("data_gap_notice" in result.data) is not enabled
    if enabled:
        assert result.data["agent_status"] == "completed"
        persisted = StructuredResearchDataset.model_validate_json((run_dir / "artifacts" / "dataset.json").read_bytes())
        assert persisted.financials[0].raw_fields["auto_probe"]["round"] == 1
        assert any(ref.artifact_id == "auto_probe_audit" for ref in result.artifacts)


@pytest.mark.anyio
async def test_changed_or_corrupt_journal_does_not_reset_the_budget(tmp_path, monkeypatch):
    from backend.app.agents.gap_scan import scan_and_supplement

    ds = dataset([("financials", "revenue")])
    calls = []
    install_probe(monkeypatch, calls, succeeds=False)
    await scan_and_supplement(ds, AS_OF, tmp_path, context={"input": "first"})
    changed = await scan_and_supplement(ds, AS_OF, tmp_path, context={"input": "changed"})
    assert changed["status"] == "input_changed" and len(calls) == 1
    (tmp_path / "auto_probe.json").write_text("truncated", encoding="utf-8")
    corrupted = await scan_and_supplement(ds, AS_OF, tmp_path, context={"input": "first"})
    assert corrupted["status"] == "audit_unavailable" and len(calls) == 1


@pytest.mark.anyio
async def test_unattended_run_automatically_repairs_before_entering_a2(tmp_path, monkeypatch):
    from backend.app.agents.adapters import FiveAgentsAdapter
    from backend.app.core.storage import storage
    from backend.app.engine.state_machine import WorkflowEngine
    from backend.app.schemas.workflow import ResearchInput, RunCreateRequest, StageResult
    from data_fetcher.models import Coverage, ResearchRunResult

    monkeypatch.setattr(storage, "base_dir", tmp_path)
    ds = dataset([("financials", "revenue")])
    check = DataFetcherAgent._evaluate_requirement(
        ds, ResearchRequirement.model_validate(ds.quality_summary["requirement_evidence_matrix"][0]["requirement"])
    )

    async def main_fetch(*args, **kwargs):
        return ResearchRunResult(
            run_id="unattended", status="partial", stop_reason="skill_budget_exhausted", dataset=ds,
            coverage=Coverage(required_domains=[Domain.FINANCIALS], covered_domains=[], missing_domains=[Domain.FINANCIALS],
                              score=0, complete=False, requirement_coverage=[check]),
        )

    interpreted = []

    async def interpret(*, run_id, **kwargs):
        actual = StructuredResearchDataset.model_validate_json(
            (storage.get_run_dir(run_id) / "artifacts" / "dataset.json").read_bytes()
        )
        interpreted.append(actual.financials[0].raw_fields["auto_probe"])
        return StageResult(stage="data_interpret", status="waiting_review")

    monkeypatch.setattr(DataFetcherAgent, "run", main_fetch)
    monkeypatch.setattr(FiveAgentsAdapter, "run_data_interpreter", interpret)
    calls = []
    install_probe(monkeypatch, calls)
    engine = WorkflowEngine()
    state = await engine.create_run(RunCreateRequest(
        project_id="unattended", input_data=ResearchInput(
            industry_topic="半导体设备", focus_questions=["甲公司2025年营业收入"], research_as_of=str(AS_OF),
        ), review_stages=["data_interpret"],
    ))
    if task := engine._running_tasks.get(state.run_id):
        await task
    final = storage.load_state(state.run_id)
    assert final.current_stage == "data_interpret" and final.status == "waiting_review"
    assert len(calls) == 1 and interpreted[0]["round"] == 1
    assert final.stage_results["data_fetch"].status == "approved"


@pytest.mark.anyio
async def test_cached_probe_collision_preserves_current_data_and_budget(tmp_path, monkeypatch):
    from backend.app.agents.gap_scan import scan_and_supplement

    ds = dataset([("financials", "revenue")])
    calls = []
    install_probe(monkeypatch, calls)
    await scan_and_supplement(ds, AS_OF, tmp_path, context={})
    ds.financials[0].value = 999
    summary = await scan_and_supplement(ds, AS_OF, tmp_path, context={})
    assert len(calls) == 1 and summary["calls_used"] == 2
    assert ds.financials[0].value == 999
    assert summary["points"][0]["status"] == "replay_conflict"
