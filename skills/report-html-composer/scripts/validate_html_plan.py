#!/usr/bin/env python3
"""Validate the canonical HTML layout catalog and an optional composition plan."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


CATALOG_PATH = Path(__file__).resolve().parents[1] / "references" / "layout-catalog.json"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: root must be an object")
    return value


def validate_catalog(catalog: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    layouts = catalog.get("layouts")
    thresholds = catalog.get("thresholds")
    run_exempt = catalog.get("run_exempt_layouts")
    evidence_center = catalog.get("evidence_center")
    if catalog.get("schema_version") != "1.0":
        errors.append("catalog.schema_version must be 1.0")
    if not isinstance(layouts, dict) or len(layouts) < 5:
        errors.append("catalog.layouts must define at least five layouts")
    if not isinstance(thresholds, dict):
        errors.append("catalog.thresholds must be an object")
    else:
        for key in (
            "side_by_side_max_text_chars",
            "side_by_side_max_charts",
            "desktop_two_column_min_viewport_px",
            "minimum_text_column_px",
            "reader_max_content_px",
            "reader_narrow_max_content_px",
            "max_same_layout_run",
        ):
            if not isinstance(thresholds.get(key), int) or thresholds[key] <= 0:
                errors.append(f"catalog.thresholds.{key} must be a positive integer")
    if not isinstance(run_exempt, list) or not all(
        isinstance(value, str) for value in run_exempt
    ):
        errors.append("catalog.run_exempt_layouts must be an array of layout ids")
    elif isinstance(layouts, dict):
        unknown = sorted(set(run_exempt) - set(layouts))
        if unknown:
            errors.append(f"catalog.run_exempt_layouts contains unknown layouts: {unknown}")
    if isinstance(layouts, dict):
        for layout_id, spec in layouts.items():
            if not isinstance(spec, dict):
                errors.append(f"catalog.layouts.{layout_id} must be an object")
                continue
            semantic_only = spec.get("semantic_only", False)
            if not isinstance(semantic_only, bool):
                errors.append(f"catalog.layouts.{layout_id}.semantic_only must be boolean")
    required_source_fields = {
        "material",
        "publisher",
        "metric",
        "scope",
        "available_date",
        "reporting_period",
        "locator",
        "usage",
        "retrieval_method",
        "source_level",
    }
    if not isinstance(evidence_center, dict):
        errors.append("catalog.evidence_center must be an object")
    else:
        required_fields = evidence_center.get("required_fields")
        if not isinstance(required_fields, list) or not all(
            isinstance(value, str) and value for value in required_fields
        ):
            errors.append("catalog.evidence_center.required_fields must be an array of strings")
        else:
            missing = sorted(required_source_fields - set(required_fields))
            if missing:
                errors.append(f"catalog.evidence_center.required_fields missing: {missing}")
    return errors


def validate_plan(plan: dict[str, Any], catalog: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    layouts = catalog["layouts"]
    thresholds = catalog["thresholds"]
    run_exempt = set(catalog.get("run_exempt_layouts", []))
    decisions = plan.get("section_decisions")
    chapter_decisions = plan.get("chapter_decisions")
    if not isinstance(decisions, list):
        return ["plan.section_decisions must be an array"]
    if not isinstance(chapter_decisions, list) or len(chapter_decisions) != 7:
        errors.append("plan.chapter_decisions must contain exactly seven items")
    elif any(
        not isinstance(item, dict) or "chapter_id" in item or not item.get("chapter_key")
        for item in chapter_decisions
    ):
        errors.append("plan.chapter_decisions must use public chapter_key values")

    seen: set[str] = set()
    run_layout = ""
    run_length = 0
    for index, item in enumerate(decisions):
        prefix = f"plan.section_decisions[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue
        section_key = item.get("section_key")
        layout_id = item.get("layout_id")
        chart_count = item.get("chart_count")
        text_chars = item.get("text_chars")
        if not isinstance(section_key, str) or not section_key:
            errors.append(f"{prefix}.section_key must be a string")
        elif section_key in seen:
            errors.append(f"duplicate section_key: {section_key}")
        else:
            seen.add(section_key)
        if layout_id not in layouts:
            errors.append(f"{prefix}.layout_id is not in the catalog: {layout_id}")
            continue
        if layout_id in run_exempt:
            run_layout, run_length = "", 0
        elif layout_id == run_layout:
            run_length += 1
        else:
            run_layout, run_length = layout_id, 1
        if layout_id not in run_exempt and run_length > thresholds["max_same_layout_run"]:
            errors.append(f"layout run too long at {section_key}: {layout_id} x {run_length}")
        if layout_id in {"chart_story_left", "chart_story_right"}:
            if chart_count != 1:
                errors.append(f"{section_key}: side-by-side layout requires exactly one chart")
            if not isinstance(text_chars, int) or text_chars > thresholds["side_by_side_max_text_chars"]:
                errors.append(f"{section_key}: side-by-side text budget exceeded")
        required_charts = layouts[layout_id].get("requires_chart_count", -1)
        semantic_only = layouts[layout_id].get("semantic_only", False)
        if not semantic_only and isinstance(required_charts, int) and required_charts >= 0:
            if not isinstance(chart_count, int) or chart_count < required_charts:
                errors.append(
                    f"{section_key}: {layout_id} requires at least {required_charts} chart(s)"
                )
    return errors


def main() -> int:
    try:
        catalog = _load(CATALOG_PATH)
        errors = validate_catalog(catalog)
        plan_path = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None
        if plan_path is not None:
            errors.extend(validate_plan(_load(plan_path), catalog))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "errors": [str(exc)]}, ensure_ascii=False))
        return 2
    print(
        json.dumps(
            {
                "ok": not errors,
                "catalog": str(CATALOG_PATH),
                "layout_count": len(catalog["layouts"]),
                "errors": errors,
            },
            ensure_ascii=False,
        )
    )
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
