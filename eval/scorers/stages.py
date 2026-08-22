"""V7 Agent 2-5 and handoff contract scoring for real chain results."""

from __future__ import annotations

from typing import Any


def _data(final: dict[str, Any], name: str) -> dict[str, Any]:
    return ((final.get("stage_results", {}) or {}).get(name, {}) or {}).get("data", {}) or {}


def score_expected_stages(case: dict[str, Any], final: dict[str, Any]) -> list[dict[str, Any]]:
    expected = case.get("expected_stages", {}) or {}
    fetch = _data(final, "data_fetch")
    analysis = _data(final, "data_interpret")
    charts = _data(final, "chart_generate")
    chapters = _data(final, "chapter_write")
    fusion = _data(final, "report_fusion")
    rows: list[dict[str, Any]] = []

    a2 = expected.get("agent2")
    if a2:
        claims = analysis.get("claims", []) or []
        evidence = {item.get("evidence_id") for item in fetch.get("evidence_items", []) or []}
        closed = all(
            claim.get("evidence_ids") and set(claim.get("evidence_ids", [])) <= evidence
            for claim in claims
        )
        ok = len(claims) >= int(a2.get("min_claims", 0))
        if a2.get("evidence_closed"):
            ok = ok and closed
        rows.append({"check_id": "A2", "passed": ok, "reason": "Agent 2 结论与证据闭环"})

    a3 = expected.get("agent3")
    if a3:
        specs = charts.get("chart_specs", []) or []
        wanted = set(a3.get("required_chart_types", []))
        actual = {item.get("chart_type") for item in specs}
        chain_count = sum(1 for item in specs if item.get("chart_type") == "industry_chain")
        ok = wanted <= actual
        limit = a3.get("max_industry_chain_images")
        if limit is not None:
            ok = ok and chain_count <= int(limit)
        rows.append({"check_id": "A3", "passed": ok, "reason": "Agent 3 图表类型与数量约束"})

    a4 = expected.get("agent4")
    if a4:
        actual_chapters = chapters.get("chapters", []) or []
        count = len(actual_chapters)
        sections = sum(len(item.get("sections", []) or []) for item in actual_chapters)
        ok = count == int(a4.get("chapters", count)) and sections == int(a4.get("sections", sections))
        rows.append({"check_id": "A4", "passed": ok, "reason": "Agent 4 章节骨架"})

    a5 = expected.get("agent5")
    if a5:
        aliases = {
            "report_markdown": "markdown",
            "report_html": "html",
            "report_pdf": "pdf",
            "artifact_manifest": "manifest",
        }
        actual = {aliases.get(item.get("kind"), item.get("kind")) for item in fusion.get("artifacts", []) or []}
        missing = set(a5.get("required_artifacts", [])) - actual
        rows.append({"check_id": "A5", "passed": not missing, "reason": f"Agent 5 缺少产物 {sorted(missing)}" if missing else "Agent 5 交付品完整"})
    return rows


def score_handoffs(case: dict[str, Any], final: dict[str, Any]) -> list[dict[str, Any]]:
    requested = case.get("expected_handoffs", []) or []
    if not requested:
        return []
    fetch = _data(final, "data_fetch")
    analysis = _data(final, "data_interpret")
    charts = _data(final, "chart_generate")
    chapters = _data(final, "chapter_write")
    fusion = _data(final, "report_fusion")
    evidence = {item.get("evidence_id") for item in fetch.get("evidence_items", []) or []}
    claim_ids = {item.get("claim_id") for item in analysis.get("claims", []) or []}
    chart_ids = {item.get("chart_id") for item in charts.get("charts", []) or []}
    # A3→A4 消费信号有两条：mock/规划路径的 chart_requests（planned）与
    # live 路径的章节/小节 chart_ids 引用（ready 图表由章节正文消费）。
    chapter_chart_ids = {
        item.get("chart_id")
        for item in chapters.get("chart_requests", []) or []
    }
    for chapter in chapters.get("chapters", []) or []:
        chapter_chart_ids.update(chapter.get("chart_ids", []) or [])
        for section in chapter.get("sections", []) or []:
            chapter_chart_ids.update(section.get("chart_ids", []) or [])
    rows: list[dict[str, Any]] = []
    for name in requested:
        if name == "a1_to_a2":
            ok = bool(evidence) and all(
                set(item.get("evidence_ids", []) or []) <= evidence
                for item in analysis.get("claims", []) or []
            )
        elif name == "a2_to_a3":
            ok = bool(analysis.get("claims", []) or analysis.get("calculated_metrics", []))
        elif name == "a2_to_a4":
            ok = bool(claim_ids) and bool(chapters.get("chapters", []))
        elif name == "a3_to_a4":
            ok = chart_ids <= chapter_chart_ids
        elif name == "a4_to_a5":
            ok = bool(chapters.get("chapters", [])) and bool(fusion.get("artifacts", []))
        else:
            ok = False
        rows.append({"check_id": f"H-{name}", "passed": ok, "reason": f"交接契约 {name}"})
    return rows

