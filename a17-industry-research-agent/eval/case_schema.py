"""Canonical V7 case loading and fail-closed schema validation."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

CASES_DIR = Path(__file__).resolve().parent / "cases"

DATA_SKILLS = frozenset(
    {
        "hithink_industry_query",
        "hithink_finance_query",
        "hithink_macro_query",
        "industry_chain_analysis",
        "report_search",
        "news_search",
        "announcement_search",
        "hithink_event_query",
        "hithink_business_query",
        "hithink_sector_selector",
        "hithink_insresearch_query",
        "hithink_index_query",
        "hithink_futures_query",
        "hithink_stock_selector",
        "hithink_basicinfo_query",
    }
)

METHODOLOGIES = frozenset(
    {
        "financial_statement",
        "commodity_analysis",
        "competitive_landscape",
        "restricted_industry_chain",
        "macro_cycle",
        "behavioral_finance",
        "institutional_research",
    }
)

REQUIRED_FIELDS = frozenset(
    {
        "id",
        "level",
        "group",
        "runs",
        "threshold",
        "must_pass",
        "veto",
        "checks",
        "required_skills",
        "expected_stages",
        "expected_handoffs",
        "subgoals",
    }
)

_NEGATIVE_ERROR_MAP = {
    "E-03": ("data_interpret", ["requested_calculation_data_unavailable"]),
    "E-17": ("data_interpret", ["requested_calculation_data_unavailable"]),
    "E-18": ("data_interpret", ["requested_calculation_data_unavailable"]),
    "E-19": ("data_interpret", ["requested_calculation_data_unavailable", "evidence_metadata_incomplete"]),
    "E-20": ("data_interpret", ["requested_calculation_data_unavailable"]),
    "E-29": ("data_fetch", ["intent_clarification_required"]),
    "E-30": ("data_fetch", ["intent_clarification_required", "required_data_unavailable"]),
    "E-32": ("data_fetch", ["required_data_unavailable"]),
    "E-33": ("data_fetch", ["intent_clarification_required", "required_data_unavailable"]),
    "E-34": ("data_fetch", ["intent_clarification_required", "required_data_unavailable"]),
    "E-35": ("data_fetch", ["required_data_unavailable"]),
    "E-36": ("data_fetch", ["required_data_unavailable"]),
    "E-37": ("data_interpret", ["requested_calculation_data_unavailable"]),
    "E-38": ("data_fetch", ["intent_clarification_required", "required_data_unavailable"]),
    "E-40": ("data_fetch", ["required_data_unavailable"]),
}


def _normalise_methodology(value: str) -> str:
    aliases = {
        "财务报表深度解读": "financial_statement",
        "财务报表解读": "financial_statement",
        "大宗商品分析": "commodity_analysis",
        "竞争格局分析": "competitive_landscape",
        "受限产业链解读": "restricted_industry_chain",
        "宏观周期分析": "macro_cycle",
        "行为金融分析": "behavioral_finance",
        "机构研究解读": "institutional_research",
    }
    return aliases.get(value, value)


def _normalise_case(raw: dict[str, Any]) -> dict[str, Any]:
    case = copy.deepcopy(raw)
    cid = str(case["id"])
    case.setdefault("runs", 1)
    case.setdefault("threshold", 1.0)
    case.setdefault(
        "must_pass",
        case.get("group") in {"intent_routing", "core_calc", "intercept", "tool_planning"},
    )
    case.setdefault("veto", [])
    case.setdefault("checks", [])
    case.setdefault("required_skills", [])
    case.setdefault("required_methodologies", [])
    case["required_methodologies"] = [
        _normalise_methodology(item) for item in case["required_methodologies"]
    ]
    if "hithink_futures_query" in case["required_skills"] and not case["required_methodologies"]:
        case["required_methodologies"].append("commodity_analysis")

    if cid.startswith("I-"):
        case.setdefault("expected_outcome", "intent_plan")
        case.setdefault("expected_stages", {"agent1": {"intent_plan": True}})
        case.setdefault("expected_handoffs", [])
        case.setdefault("subgoals", ["a1_plan", "a1_fetch"])
    elif cid.startswith("S-C"):
        case.setdefault("expected_outcome", "specialized")
        case.setdefault("expected_stages", {"agent2": {"deterministic_calculation": True}})
        case.setdefault("expected_handoffs", [])
        case.setdefault("subgoals", ["a2_calc"])
    elif cid.startswith("S-G"):
        case.setdefault("expected_outcome", "specialized")
        case.setdefault("expected_stages", {"agent3": {"chart_rule": True}})
        case.setdefault("expected_handoffs", [])
        case.setdefault("subgoals", ["a3_chart"])
    elif cid.startswith("S-E"):
        case.setdefault("expected_outcome", "specialized")
        case.setdefault("expected_stages", {"agent2": {"evidence_closed": True}})
        case.setdefault("expected_handoffs", ["a1_to_a2", "a2_to_a4"])
        case.setdefault("subgoals", ["a1_fetch", "a2_calc", "a4_chapter"])
    elif cid.startswith("T-"):
        case.setdefault("expected_outcome", "tool_plan")
        case.setdefault("expected_stages", {"agent1": {"retrieval_plan": True}})
        case.setdefault("expected_handoffs", [])
        case.setdefault("subgoals", ["a1_plan", "a1_fetch"])
        if cid == "T-05":
            case["synthetic_override"] = "duplicate_query"
        elif cid == "T-06":
            case["synthetic_override"] = "over_30_tasks"
        elif cid == "T-12":
            case["trajectory_injection"] = "wrong_then_correct_skill"
    else:
        negative = bool(case.get("negative") or case.get("expect_intercept") or cid in _NEGATIVE_ERROR_MAP)
        if negative:
            stage, codes = _NEGATIVE_ERROR_MAP.get(
                cid, ("data_fetch", ["required_data_unavailable"])
            )
            case.setdefault("expected_outcome", "intercept")
            case.setdefault("expected_stop_stage", stage)
            case.setdefault("expected_error_codes", codes)
            case.setdefault("forbid_downstream_stages", True)
            case.setdefault("expected_stages", {})
            case.setdefault("expected_handoffs", [])
            case.setdefault("subgoals", ["a1_plan", "a1_fetch"] if stage == "data_fetch" else ["a1_plan", "a1_fetch", "a2_calc"])
        else:
            case.setdefault("expected_outcome", "completed")
            case.setdefault(
                "expected_stages",
                {
                    "agent2": {"evidence_closed": True, "min_claims": 1},
                    "agent3": {"max_industry_chain_images": 1},
                    "agent4": {"chapters": 7, "sections": 21, "numeric_traceability": 1.0},
                    "agent5": {"required_artifacts": ["markdown", "html", "pdf", "manifest"]},
                },
            )
            case.setdefault(
                "expected_handoffs",
                ["a1_to_a2", "a2_to_a3", "a2_to_a4", "a3_to_a4", "a4_to_a5"],
            )
            case.setdefault(
                "subgoals",
                ["a1_plan", "a1_fetch", "a2_calc", "a3_chart", "a4_chapter", "a5_export"],
            )
    return case


def load_case_suite() -> list[dict[str, Any]]:
    intent = json.loads((CASES_DIR / "intent_golden.json").read_text(encoding="utf-8"))
    rest = json.loads((CASES_DIR / "cases_v1.json").read_text(encoding="utf-8"))
    return [_normalise_case(item) for item in [*intent, *rest]]


def validate_case_suite(
    cases: list[dict[str, Any]], *, registered_checks: frozenset[str]
) -> list[str]:
    errors: list[str] = []
    ids = [case.get("id") for case in cases]
    if len(ids) != len(set(ids)):
        errors.append("case ids must be unique")
    for case in cases:
        cid = str(case.get("id", "<missing>"))
        missing = REQUIRED_FIELDS - set(case)
        if missing:
            errors.append(f"{cid}: missing fields {sorted(missing)}")
        unknown_checks = (set(case.get("checks", [])) | set(case.get("veto", []))) - registered_checks
        if unknown_checks:
            errors.append(f"{cid}: unknown checks {sorted(unknown_checks)}")
        unknown_skills = set(case.get("required_skills", [])) - DATA_SKILLS
        if unknown_skills:
            errors.append(f"{cid}: unknown skills {sorted(unknown_skills)}")
        unknown_methods = set(case.get("required_methodologies", [])) - METHODOLOGIES
        if unknown_methods:
            errors.append(f"{cid}: unknown methodologies {sorted(unknown_methods)}")
        if not isinstance(case.get("runs"), int) or case.get("runs", 0) < 1:
            errors.append(f"{cid}: runs must be a positive integer")
        threshold = case.get("threshold")
        if not isinstance(threshold, (int, float)) or not 0 < threshold <= 1:
            errors.append(f"{cid}: threshold must be in (0,1]")
        if case.get("expected_outcome") == "intercept":
            if not case.get("expected_stop_stage") or not case.get("expected_error_codes"):
                errors.append(f"{cid}: intercept requires exact stage and error codes")
    if set().union(*(set(c.get("required_skills", [])) for c in cases)) != DATA_SKILLS:
        missing_skills = DATA_SKILLS - set().union(
            *(set(c.get("required_skills", [])) for c in cases)
        )
        errors.append(f"suite missing Skill coverage: {sorted(missing_skills)}")
    if set().union(*(set(c.get("required_methodologies", [])) for c in cases)) != METHODOLOGIES:
        missing_methods = METHODOLOGIES - set().union(
            *(set(c.get("required_methodologies", [])) for c in cases)
        )
        errors.append(f"suite missing methodology coverage: {sorted(missing_methods)}")
    return errors


def apply_synthetic_override(kind: str, plan: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(plan)
    tasks = result.setdefault("tasks", [])
    if kind == "duplicate_query" and tasks:
        tasks.append(copy.deepcopy(tasks[0]))
    elif kind == "over_30_tasks":
        seed = copy.deepcopy(tasks[0] if tasks else {"skill_name": "hithink_finance_query", "query": "seed"})
        while len(tasks) <= 30:
            item = copy.deepcopy(seed)
            item["query"] = f"{seed.get('query', 'seed')} #{len(tasks) + 1}"
            tasks.append(item)
    else:
        raise ValueError(f"unknown synthetic override: {kind}")
    return result


def inject_trajectory(kind: str, *, required_skill: str, wrong_skill: str) -> list[dict[str, Any]]:
    if kind != "wrong_then_correct_skill":
        raise ValueError(f"unknown trajectory injection: {kind}")
    return [
        {"sequence": 1, "skill": wrong_skill, "outcome": "empty"},
        {"sequence": 2, "skill": required_skill, "outcome": "success"},
    ]
