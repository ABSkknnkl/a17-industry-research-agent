"""Replay verified A17 evidence for the opt-in probe demonstration."""

from collections.abc import Awaitable, Callable
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from backend.app.schemas.workflow import RunCreateRequest
from data_fetcher.dynamic_probe import ProbeOutcome
from data_fetcher.models import ResearchRunResult, StructuredResearchDataset
from data_fetcher.nev_profile import DATASET_PATH, verify_dataset


AS_OF = date(2026, 11, 17)
BASELINE = DATASET_PATH.parent / "nev_probe_demo"
POINTS = {
    "changan_2025_revenue": ("营业收入", "revenue", "R-3d3cb5464b8ab74ecbba"),
    "changan_2025_cashflow": ("经营活动产生的现金流量净额", "operating_cash_flow", "R-83b2a177b46648f5d083"),
}
FILES = {
    "archive": BASELINE / "nev_a1_2025.json",
    "input": BASELINE / "input_data.json",
    "charts": BASELINE / "chart_result.json",
    "chapters": BASELINE / "chapter_result.json",
}
GATE_MESSAGE = "请补齐新能源汽车演示数据后再进入数据解读。"


def prepare_request(request: RunCreateRequest) -> tuple[RunCreateRequest, dict[str, str]]:
    inputs = {key: path.read_bytes() for key, path in FILES.items()}
    snapshot = {key: sha256(payload).hexdigest() for key, payload in inputs.items()}
    baseline = RunCreateRequest.model_validate_json(inputs["input"])
    from chart_generator.nev_template import PROFILE, matches_template
    from chapter_writer.models import ChapterWritingResult

    ChapterWritingResult.model_validate_json(inputs["chapters"])
    chart_baseline = json.loads(inputs["charts"])

    if (baseline.delivery_profile != "competition"
            or baseline.input_data.research_as_of != AS_OF.isoformat()
            or not matches_template(baseline.input_data.industry_topic, baseline.input_data.focus_questions)
            or chart_baseline.get("figure_profile") != PROFILE
            or len(chart_baseline.get("charts", [])) != 15
            or not archive(snapshot).coverage.complete):
        raise ValueError("新能源汽车五问演示归档验收未通过")
    return baseline.model_copy(update={
        "project_id": request.project_id,
        "nev_probe_demo": True,
        "review_stages": ["data_fetch", "report_fusion"],
    }), snapshot


def _verified_bytes(snapshot: dict[str, str], key: str) -> bytes:
    payload = FILES[key].read_bytes()
    if sha256(payload).hexdigest() != snapshot.get(key):
        raise ValueError(f"新能源汽车演示归档已变更：{FILES[key].name}")
    return payload


def archive(snapshot: dict[str, str], run_id: str = "") -> ResearchRunResult:
    records = StructuredResearchDataset.model_validate_json(_verified_bytes(snapshot, "archive"))
    for _, metric, record_id in POINTS.values():
        matches = [r for r in records.financials if r.record_id == record_id]
        if len(matches) != 1 or (
            matches[0].entity_code, matches[0].metric, matches[0].period_end,
            matches[0].period_type, matches[0].scope, matches[0].unit, matches[0].currency,
        ) != ("000625.SZ", metric, date(2025, 12, 31), "annual", "consolidated", "元", "CNY"):
            raise ValueError(f"新能源汽车演示归档的数据点不匹配：{metric}")
    return verify_dataset(run_id, records, AS_OF)


def masked_run(snapshot: dict[str, str], run_id: str) -> ResearchRunResult:
    result = archive(snapshot, run_id)
    withheld = {point[2] for point in POINTS.values()}
    dataset = result.dataset
    dataset.financials = [r for r in dataset.financials if r.record_id not in withheld]
    result = verify_dataset(run_id, dataset, AS_OF)
    result.status = "partial"
    result.stop_reason = "demo_probe_gaps"
    result.errors = []
    return result


def stage_data(result: ResearchRunResult) -> dict[str, Any]:
    existing = {r.record_id: r for r in result.dataset.financials}
    points = []
    for key, (label, _, record_id) in POINTS.items():
        record = existing.get(record_id)
        points.append({
            "id": key, "label": label, "entity": "长安汽车", "period": "2025 年度 · 合并报表",
            "value": f"{record.value / 100_000_000:,.3f} 亿元" if record else None,
            "missing": record is None,
            "record_id": record_id if record else None,
        })
    missing = sum(p["missing"] for p in points)
    checks = result.coverage.requirement_coverage
    passed = sum(c.passed for c in checks)
    return {
        "nev_probe_demo": True,
        "demo_probe_points": points,
        "demo_question_coverage": {"passed": passed, "total": len(checks)},
        "demo_probe_pending": not result.coverage.complete,
        "agent_status": "partial" if missing else result.status,
        "numeric_status": "partial" if missing else result.status,
        "stop_reason": "demo_probe_gaps" if missing else result.stop_reason,
        "evidence_count": result.dataset.total_record_count,
        "blocked": not result.coverage.complete,
        "block_reason": GATE_MESSAGE if not result.coverage.complete else "",
        "data_gap_notice": (
            f"演示模式 · 已采集 {result.dataset.total_record_count} 条 · {missing} 个数据点待补 · 五问证据覆盖 {passed}/{len(checks)}"
            if missing else ""
        ),
        "probe_hint": "点击「探针补采」回放同花顺归档。" if missing else "",
    }


async def replay_probe(
    snapshot: dict[str, str], dataset: StructuredResearchDataset, point_ids: Any,
    on_attempt: Callable[[dict[str, Any]], Awaitable[None]],
) -> ProbeOutcome:
    if not isinstance(point_ids, list) or not point_ids or any(
        not isinstance(key, str) or key not in POINTS for key in point_ids
    ):
        return ProbeOutcome(status="failed", message="请选择演示清单中的数据点。")
    wanted = {POINTS[key][2] for key in point_ids}
    existing = {r.record_id for r in dataset.all_records()}
    archived = archive(snapshot).dataset
    records = [r for r in archived.financials if r.record_id in wanted - existing]
    if not records:
        return ProbeOutcome(status="no_data", message="所选数据点已补齐。")
    source = records[0].source
    audit = {
        "attempt": 1, "skill_id": source.skill_id, "query": source.query,
        "trace_id": source.trace_id, "probe_source": "archive_replay",
        "target_hit": len(records), "usable_records": len(records), "success": True,
    }
    await on_attempt(audit)
    return ProbeOutcome("success", records, [audit], f"同花顺归档回放匹配 {len(records)} 条记录。")


def reusable_chapters(snapshot: dict[str, str], run_dir: Path, chart_raw: dict[str, Any]) -> bytes | None:
    try:
        baseline_input = RunCreateRequest.model_validate_json(_verified_bytes(snapshot, "input"))
        current_input = RunCreateRequest.model_validate_json((run_dir / "input_data.json").read_bytes())
        if current_input.input_data != baseline_input.input_data:
            return None
        current = StructuredResearchDataset.model_validate_json(
            (run_dir / "artifacts" / "dataset.json").read_bytes()
        )
        expected = archive(snapshot).dataset
        if {r.record_id: r for r in current.all_records()} != {r.record_id: r for r in expected.all_records()}:
            return None
        charts = json.loads(_verified_bytes(snapshot, "charts"))
        if chart_raw.get("figure_profile") != charts.get("figure_profile"):
            return None
        fields = ("data_contract", "evidence_ids", "inline_svg")
        current_charts = {c["chart_id"]: tuple(c.get(k) for k in fields) for c in chart_raw["charts"]}
        baseline_charts = {c["chart_id"]: tuple(c.get(k) for k in fields) for c in charts["charts"]}
        if current_charts != baseline_charts:
            return None
        return _verified_bytes(snapshot, "chapters")
    except (OSError, ValueError, KeyError):
        return None
