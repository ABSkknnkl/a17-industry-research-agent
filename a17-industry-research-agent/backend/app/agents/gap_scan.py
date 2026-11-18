"""A1 critical-gap repair with a durable request budget and replayable evidence."""

from collections import Counter
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from agents_core.financial_semantics import metric_family
from data_fetcher.agent import DataFetcherAgent
from data_fetcher.models import ResearchObjective, ResearchRecord, ResearchRequirement, StructuredResearchDataset


MAX_CALLS = 12
MAX_CHAPTER_POINTS = 3
CHAPTERS = {
    "industry": "CH-02", "companies": "CH-04", "financials": "CH-05",
    "industry_chain": "CH-03", "macro": "CH-06", "reports": "CH-06",
    "news": "CH-06", "events": "CH-07",
}


def _digest(value: Any) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def _save(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _points(dataset: StructuredResearchDataset):
    seen = set()
    for row in dataset.quality_summary.get("requirement_evidence_matrix") or []:
        requirement = ResearchRequirement.model_validate(row["requirement"])
        if row["coverage"].get("passed") or not requirement.hard:
            continue
        # Domain-level presence and announcement-search completion have no point target.
        terms = requirement.metric_families or [
            term for group in requirement.expected_metric_groups for term in group
        ]
        metrics = sorted({metric_family(term) for term in terms if term.strip()})
        for entity in requirement.entity_names or [""]:
            for period in requirement.period_ends or [None]:
                for metric in metrics:
                    cell = requirement.model_copy(update={
                        "entity_names": [entity] if entity else [],
                        "period_ends": [period] if period else [],
                        "metric_families": [metric], "expected_metric_groups": [],
                        "min_records": 1,
                    })
                    if DataFetcherAgent._evaluate_requirement(dataset, cell).passed:
                        continue
                    key = _digest((requirement.domain.value, entity, period, metric))
                    if key in seen:
                        continue
                    seen.add(key)
                    chapter = CHAPTERS[requirement.domain.value]
                    demand = {
                        "action_type": "partial_refetch", "probe_mode": "llm_dynamic",
                        "domain": requirement.domain.value, "entities": cell.entity_names,
                        "metrics": [metric], "target_keywords": [metric],
                        "period_ends": [str(period)] if period else [],
                        "min_records": 1, "requirement_id": requirement.requirement_id,
                        "chapter_id": chapter,
                        "reason": f"关键缺口：{requirement.label}",
                        "query_hint": " ".join(filter(None, (
                            entity, str(period or ""), metric, requirement.label,
                            f"研究主题 {dataset.subject}",
                        ))),
                    }
                    yield key, cell, demand


def _accept(
    dataset: StructuredResearchDataset, cell: ResearchRequirement, records: list[ResearchRecord],
) -> list[ResearchRecord]:
    candidates = StructuredResearchDataset(research_as_of=dataset.research_as_of)
    candidates.companies = list(dataset.companies)
    existing = {record.record_id for record in dataset.all_records()}
    eligible = [r for r in records if r.record_id not in existing and not r.issues
                and r.domain == cell.domain and r.source.trace_id and r.source.query
                and r.source.status in ("success", "verified")]
    for record in eligible:
        candidates.records_for(record.domain).append(record)
    check = DataFetcherAgent._evaluate_requirement(candidates, cell)
    accepted_ids = set(check.evidence_record_ids)
    return [record for record in eligible if record.record_id in accepted_ids]


def _merge(
    dataset: StructuredResearchDataset, records: list[ResearchRecord], as_of: date,
) -> list[str]:
    from backend.app.agents.adapters import merge_supplemental_records

    if not records:
        return []
    candidate = dataset.model_copy(deep=True)
    added = merge_supplemental_records(candidate, {}, records, as_of)
    if not added:
        return []
    if candidate.quality_summary.get("data_source") == "iwencai_verified_capture":
        from data_fetcher.nev_profile import verify_dataset

        verify_dataset("", candidate, as_of)
    else:
        matrix = candidate.quality_summary.get("requirement_evidence_matrix") or []
        DataFetcherAgent().reevaluate_requirements(candidate, ResearchObjective(
            industry=candidate.subject, as_of=as_of,
            requirements=[ResearchRequirement.model_validate(row["requirement"]) for row in matrix],
        ))
    for field in StructuredResearchDataset.model_fields:
        setattr(dataset, field, getattr(candidate, field))
    return added


async def scan_and_supplement(
    dataset: StructuredResearchDataset, as_of: date, artifacts: Path, *,
    context: dict[str, Any], on_event=None,
) -> dict[str, Any]:
    from data_fetcher.dynamic_probe import run_dynamic_probe

    artifacts.mkdir(parents=True, exist_ok=True)
    path = artifacts / "auto_probe.json"
    context_hash = _digest(context)
    try:
        journal = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
            "version": 1, "context_sha256": context_hash, "calls": [], "points": {},
        }
        if (journal["version"] != 1 or not isinstance(journal.get("context_sha256"), str)
                or not isinstance(journal["calls"], list)
                or not isinstance(journal["points"], dict)):
            raise ValueError("invalid journal")
        for entry in journal["points"].values():
            if (not isinstance(entry["chapter_id"], str) or not isinstance(entry["demand"], dict)
                    or not isinstance(entry["attempts"], list) or not isinstance(entry["status"], str)):
                raise ValueError("invalid point journal")
            for raw in entry["records"]:
                ResearchRecord.model_validate(raw)
    except (OSError, ValueError, KeyError, TypeError):
        return {"status": "audit_unavailable", "message": "自动补采审计不可读，请手动复核。"}
    if journal["context_sha256"] != context_hash:
        return {"status": "input_changed", "message": "研究输入已变化，自动补采保留原预算，请手动补采。"}

    dataset.research_as_of = as_of
    # A1 restarts reuse saved evidence, including a result saved just before cancellation.
    for entry in journal["points"].values():
        if entry["status"] == "running":
            entry.update(status="interrupted", message="上次尝试已中断，保留预算并交由手动复核。")
        records = [ResearchRecord.model_validate(r) for r in entry.get("records", [])]
        try:
            _merge(dataset, records, as_of)
            entry.pop("replay_error", None)
        except ValueError as exc:
            entry["replay_error"] = type(exc).__name__
    counts = Counter(entry["chapter_id"] for entry in journal["points"].values())
    skipped = []
    for key, cell, demand in list(_points(dataset)):
        if key in journal["points"]:
            continue
        chapter = demand["chapter_id"]
        reason = ("call_budget" if len(journal["calls"]) >= MAX_CALLS else
                  "chapter_point_limit" if counts[chapter] >= MAX_CHAPTER_POINTS else "")
        if reason:
            skipped.append({"requirement_id": cell.requirement_id, "point_id": key,
                            "chapter_id": chapter, "reason": reason})
            continue
        entry = {
            "chapter_id": chapter, "demand": demand, "status": "running",
            "attempts": [], "records": [],
        }
        journal["points"][key] = entry
        counts[chapter] += 1
        _save(path, journal)

        async def reserve(kind: str, details: dict[str, Any]) -> bool:
            if len(journal["calls"]) >= MAX_CALLS:
                return False
            journal["calls"].append({
                **details, "kind": kind, "point_id": key,
                "reserved_at": datetime.now(timezone.utc).isoformat(),
            })
            _save(path, journal)
            return True

        async def observe(attempt: dict[str, Any]) -> None:
            entry["attempts"].append(attempt)
            _save(path, journal)
            if on_event:
                await on_event({"point_id": key, "chapter_id": chapter, **attempt})

        try:
            outcome = await run_dynamic_probe(
                demand, as_of, max_attempts=4, before_call=reserve, on_attempt=observe,
                accept_records=lambda rows: _accept(dataset, cell, rows),
            )
            entry["status"], entry["message"] = outcome.status, outcome.message
            entry["attempts"] = outcome.attempts
            accepted = _accept(dataset, cell, outcome.records)
            last = outcome.attempts[-1] if outcome.attempts else {}
            for record in accepted:
                record.raw_fields = {**record.raw_fields, "auto_probe": {
                    "point_id": key, "requirement_id": cell.requirement_id, "chapter_id": chapter,
                    "round": last.get("round") or last.get("attempt"),
                    "audit_artifact": "auto_probe.json",
                }}
            entry["records"] = [r.model_dump(mode="json") for r in accepted]
            # Persist response evidence before publication so a restart can replay it.
            _save(path, journal)
            _merge(dataset, accepted, as_of)
        except Exception as exc:
            entry.update(status="failed", message=type(exc).__name__, records=[])
            _save(path, journal)

    matrix = dataset.quality_summary.get("requirement_evidence_matrix") or []
    remaining = sum(not row["coverage"].get("passed") for row in matrix)
    exhausted = len(journal["calls"]) >= MAX_CALLS
    summary = {
        "status": "budget_exhausted" if exhausted and remaining else "completed",
        "calls_used": len(journal["calls"]), "max_calls": MAX_CALLS,
        "max_points_per_chapter": MAX_CHAPTER_POINTS, "chapter_points": dict(counts),
        "remaining_requirements": remaining, "skipped": skipped,
        "points": [{
            "point_id": key, "chapter_id": item["chapter_id"],
            "status": "replay_conflict" if item.get("replay_error") else item["status"],
            "label": item["demand"]["reason"],
            "message": item.get("message", ""),
            "requirement_id": item["demand"]["requirement_id"], "attempts": item["attempts"],
            "evidence_record_ids": [r["record_id"] for r in item["records"]],
        } for key, item in journal["points"].items()],
    }
    journal["summary"] = summary
    _save(path, journal)
    dataset.quality_summary["auto_probe"] = summary
    return summary
