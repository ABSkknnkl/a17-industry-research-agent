"""Offline candidate/duplicate and readability evaluator for the A4 refactor.

Usage::

    python3 scripts/evaluate_agent4_refactor.py \
      --baseline A4_BASELINE_CHAPTERS.json \
      --candidate A4_CANDIDATE_CHAPTERS.json \
      --annotations A4_ANNOTATIONS.json \
      --output A4_EVAL_JSON --gate

Exit codes: 0 = gates passed, 1 = gate failure, 2 = invalid/incomparable input.
Candidates are automatic hints only; confirmed duplicates and blinded readout
scores come from the annotation file and must be supplied by a human reviewer.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any

NEAR_DUPLICATE_THRESHOLD = 0.85
MIN_READOUT_SAMPLES = 6
REQUIRED_ROOT_FIELDS = ("case_id", "input_sha256", "requirements",
                        "duplicate_paragraph_ids", "readout_reviews")
ANSWER_STATUSES = {"answered", "gap", "missing", "unknown"}
EXCLUDED_KINDS = {"transition", "methodology"}
CAPTION_PREFIXES = ("数据来源：", "表注：", "图注：", "注：")

_CHART_TAG = re.compile(r"\[CHART-[^\]]+\]")
_REF_TAG = re.compile(r"\[[A-Za-z0-9_\-\.]+\]")
_NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?%?")
_UP = ("上升", "提高", "扩大", "增长", "高于", "增加", "改善")
_DOWN = ("下降", "回落", "收窄", "减少", "低于", "恶化")
_NEGATION = ("不", "未", "无", "无法", "不能")


class EvaluationInputError(ValueError):
    """Invalid, incomplete or incomparable evaluation input."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(f"{field}: {message}")
        self.field = field


def _load(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise EvaluationInputError(path, "file does not exist")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise EvaluationInputError(path, f"cannot parse JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise EvaluationInputError(path, "root object must be a JSON object")
    return data


def _require(result: dict[str, Any], label: str) -> None:
    for field in ("run_id", "source_report_id", "subject", "outline_version", "chapters"):
        if field not in result:
            raise EvaluationInputError(f"{label}.{field}", "missing required field")
    if not isinstance(result["chapters"], list) or not result["chapters"]:
        raise EvaluationInputError(f"{label}.chapters", "must be a non-empty list")


def normalise(text: str) -> str:
    """Strip whitespace, chart placeholders and citation tags; keep the rest."""
    cleaned = _CHART_TAG.sub("", text or "")
    cleaned = _REF_TAG.sub("", cleaned)
    return re.sub(r"\s+", "", cleaned)


def _numeric_signature(text: str) -> tuple[str, ...]:
    return tuple(_NUMBER.findall(text))


def _direction_conflict(a: str, b: str) -> bool:
    up_a, down_a = any(w in a for w in _UP), any(w in a for w in _DOWN)
    up_b, down_b = any(w in b for w in _UP), any(w in b for w in _DOWN)
    if (up_a and down_b) or (down_a and up_b):
        return True
    return any(w in a for w in _NEGATION) != any(w in b for w in _NEGATION)


def _trigrams(text: str) -> set[str]:
    if len(text) < 3:
        return {text} if text else set()
    return {text[i:i + 3] for i in range(len(text) - 2)}


def jaccard(a: str, b: str) -> float:
    left, right = _trigrams(a), _trigrams(b)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _is_caption(text: str) -> bool:
    """Exclude source notes and pure chart captions, not chart-neighbour readouts.

    The chapter audit injects a short "如图 [CHART-xx] 所示，" prefix into real
    body paragraphs; treating those as captions would hide comparable text.
    """
    stripped = (text or "").strip()
    if stripped.startswith(CAPTION_PREFIXES):
        return True
    return bool(_CHART_TAG.search(stripped)) and len(normalise(stripped)) < 30


def collect_paragraphs(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Comparable body paragraphs only; summaries and captions are excluded."""
    rows: list[dict[str, Any]] = []
    for chapter in result["chapters"]:
        chapter_id = chapter.get("chapter_id", "")
        for section in chapter.get("sections", []):
            section_id = section.get("section_id", "")
            for paragraph in section.get("paragraphs", []):
                kind = paragraph.get("kind", "analysis")
                text = str(paragraph.get("text") or "")
                if kind in EXCLUDED_KINDS or _is_caption(text) or not normalise(text):
                    continue
                rows.append({
                    "locator": f"{chapter_id}/{section_id}/{paragraph.get('paragraph_id', '')}",
                    "chapter_id": chapter_id, "section_id": section_id,
                    "paragraph_id": paragraph.get("paragraph_id", ""),
                    "kind": kind, "text": text,
                    "evidence_ids": list(paragraph.get("evidence_ids") or []),
                })
    return rows


def locator_index(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["locator"]: row for row in collect_paragraphs(result)}


def duplicate_candidates(result: dict[str, Any],
                         threshold: float = NEAR_DUPLICATE_THRESHOLD) -> list[dict[str, Any]]:
    """Cross-chapter exact and near-duplicate hints, with rejection reasons."""
    rows = collect_paragraphs(result)
    candidates: list[dict[str, Any]] = []
    for i, left in enumerate(rows):
        for right in rows[i + 1:]:
            if left["chapter_id"] == right["chapter_id"]:
                continue
            a, b = normalise(left["text"]), normalise(right["text"])
            if a == b:
                candidates.append({"baseline_locator": left["locator"],
                                   "candidate_locator": right["locator"],
                                   "method": "exact", "score": 1.0, "shared_evidence":
                                   sorted(set(left["evidence_ids"]) & set(right["evidence_ids"]))})
                continue
            if _numeric_signature(a) != _numeric_signature(b):
                continue  # different periods / values / units
            if _direction_conflict(a, b):
                continue  # opposite conclusion
            score = jaccard(a, b)
            shared = sorted(set(left["evidence_ids"]) & set(right["evidence_ids"]))
            if score >= threshold and shared:
                candidates.append({"baseline_locator": left["locator"],
                                   "candidate_locator": right["locator"],
                                   "method": "near", "score": round(score, 4),
                                   "shared_evidence": shared})
    return candidates


def _validate_annotations(annotations: dict[str, Any]) -> None:
    for field in REQUIRED_ROOT_FIELDS:
        if field not in annotations:
            raise EvaluationInputError(f"annotations.{field}", "missing required field")
    duplicates = annotations["duplicate_paragraph_ids"]
    if not isinstance(duplicates, dict) or "baseline" not in duplicates:
        raise EvaluationInputError("annotations.duplicate_paragraph_ids",
                                   "must contain a baseline list")
    for item in annotations["requirements"]:
        status = item.get("answer_status")
        if status not in ANSWER_STATUSES:
            raise EvaluationInputError("annotations.requirements[].answer_status",
                                       f"invalid value {status!r}")
    for item in annotations["readout_reviews"]:
        for field in ("comparison", "meaning", "boundary"):
            if item.get(field) not in (0, 1):
                raise EvaluationInputError(f"annotations.readout_reviews[].{field}",
                                           "must be 0 or 1")


def _check_comparable(baseline: dict[str, Any], candidate: dict[str, Any]) -> None:
    for field in ("source_report_id", "subject", "outline_version"):
        if baseline.get(field) != candidate.get(field):
            raise EvaluationInputError(f"versions.{field}",
                                       f"baseline {baseline.get(field)!r} != candidate {candidate.get(field)!r}")
    if baseline.get("run_id") == candidate.get("run_id"):
        raise EvaluationInputError("versions.run_id", "baseline and candidate must differ")
    left = {(c.get("chapter_id"), s.get("section_id"))
            for c in baseline["chapters"] for s in c.get("sections", [])}
    right = {(c.get("chapter_id"), s.get("section_id"))
             for c in candidate["chapters"] for s in c.get("sections", [])}
    if left != right:
        raise EvaluationInputError("versions.outline", "chapter/section ids are not comparable")


def _resolve_locators(index: dict[str, dict[str, Any]], locators: list[str], label: str) -> None:
    for locator in locators:
        parts = locator.split("/")
        if len(parts) != 3 or not all(parts):
            raise EvaluationInputError(f"annotations.{label}",
                                       f"locator {locator!r} must be chapter_id/section_id/paragraph_id")
        if locator not in index:
            raise EvaluationInputError(f"annotations.{label}",
                                       f"locator {locator!r} not found in comparable paragraphs")


def _readout_summary(reviews: list[dict[str, Any]], version: str) -> dict[str, Any]:
    rows = [r for r in reviews if r.get("version") == version]
    if not rows:
        return {"version": version, "samples": 0, "average": None, "per_locator": {}}
    per_locator = {
        r["locator"]: int(r["comparison"]) + int(r["meaning"]) + int(r["boundary"])
        for r in rows
    }
    return {
        "version": version, "samples": len(rows),
        "average": round(sum(per_locator.values()) / (3 * len(rows)), 4),
        "per_locator": per_locator,
    }


def _coverage_summary(requirements: list[dict[str, Any]], version: str) -> dict[str, Any]:
    rows = [r for r in requirements if r.get("version") == version]
    counts = {status: sum(1 for r in rows if r.get("answer_status") == status)
              for status in ANSWER_STATUSES}
    with_evidence = [r for r in rows if r.get("evidence_ids") or r.get("answer_status") == "answered"]
    return {
        "version": version, "total": len(rows), "counts": counts,
        "unanswered_with_evidence": [r.get("requirement_id") for r in with_evidence
                                     if r.get("answer_status") == "missing"],
        "unknown": [r.get("requirement_id") for r in rows if r.get("answer_status") == "unknown"],
    }


def evaluate(baseline: dict[str, Any], candidate: dict[str, Any],
             annotations: dict[str, Any], *, gate: bool) -> tuple[dict[str, Any], int]:
    _require(baseline, "baseline")
    _require(candidate, "candidate")
    _validate_annotations(annotations)
    _check_comparable(baseline, candidate)

    base_index = locator_index(baseline)
    cand_index = locator_index(candidate)
    duplicates = annotations["duplicate_paragraph_ids"]
    base_confirmed = sorted(set(duplicates.get("baseline") or []))
    cand_confirmed = sorted(set(duplicates.get("candidate") or []))
    _resolve_locators(base_index, base_confirmed, "duplicate_paragraph_ids.baseline")
    _resolve_locators(cand_index, cand_confirmed, "duplicate_paragraph_ids.candidate")

    for version, index in (("baseline", base_index), ("candidate", cand_index)):
        for item in annotations["readout_reviews"]:
            if item.get("version") == version and item.get("locator") not in index:
                raise EvaluationInputError("annotations.readout_reviews[].locator",
                                           f"{item['locator']!r} not found in {version} paragraphs")

    base_count, cand_count = len(base_index), len(cand_index)
    # An empty candidate duplicate list only means "no confirmed duplicates"
    # after an independent review. Without that review it is "not evaluated",
    # never a 100% reduction.
    reviewed = duplicates.get("candidate_reviewed") is True
    base_rate = len(base_confirmed) / base_count if base_count else 0.0
    cand_rate = len(cand_confirmed) / cand_count if cand_count else 0.0
    reduction = (base_rate - cand_rate) / base_rate if reviewed and base_rate else None

    base_readout = _readout_summary(annotations["readout_reviews"], "baseline")
    cand_readout = _readout_summary(annotations["readout_reviews"], "candidate")
    base_cov = _coverage_summary(annotations["requirements"], "baseline")
    cand_cov = _coverage_summary(annotations["requirements"], "candidate")

    checks: list[dict[str, Any]] = []

    def _check(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    completeness_ok = (
        not base_cov["unknown"] and not cand_cov["unknown"]
        and base_readout["samples"] >= MIN_READOUT_SAMPLES
        and cand_readout["samples"] >= MIN_READOUT_SAMPLES
        and isinstance(duplicates.get("candidate"), list)
        and reviewed
    )
    _check("annotations_complete", completeness_ok,
           f"readout_samples={base_readout['samples']}/{cand_readout['samples']}, "
           f"unknown_requirements={len(base_cov['unknown']) + len(cand_cov['unknown'])}, "
           f"candidate_reviewed={reviewed}")
    _check("mandatory_completeness",
           not cand_cov["unanswered_with_evidence"],
           f"unanswered_with_evidence={cand_cov['unanswered_with_evidence']}")
    _check("duplicate_reduction_30pct",
           completeness_ok and reduction is not None and reduction >= 0.30,
           f"baseline={base_rate:.4f}, candidate={cand_rate:.4f}, reduction={reduction}"
           if completeness_ok else "not_evaluated: candidate duplicates not independently reviewed")
    # Only explicitly paired baseline/candidate paragraphs can count as improved.
    # An unpaired candidate paragraph must not inherit a baseline score of zero.
    improved = 0
    unpaired = 0
    for item in annotations["readout_reviews"]:
        if item.get("version") != "candidate":
            continue
        paired = item.get("pair_locator") or item.get("locator")
        baseline_score = base_readout["per_locator"].get(paired)
        if baseline_score is None:
            unpaired += 1
            continue
        candidate_score = cand_readout["per_locator"].get(item["locator"])
        if candidate_score is not None and candidate_score > baseline_score:
            improved += 1
    _check("readout_average_not_lower",
           base_readout["average"] is not None and cand_readout["average"] is not None
           and cand_readout["average"] >= base_readout["average"],
           f"baseline={base_readout['average']}, candidate={cand_readout['average']}")
    _check("readout_at_least_two_improved", improved >= 2,
           f"improved_segments={improved}, unpaired_candidate_segments={unpaired}")

    report = {
        "case_id": annotations["case_id"], "input_sha256": annotations["input_sha256"],
        "versions": {
            "baseline": {"run_id": baseline["run_id"], "comparable_paragraphs": base_count},
            "candidate": {"run_id": candidate["run_id"], "comparable_paragraphs": cand_count},
        },
        "candidates": {
            "baseline": duplicate_candidates(baseline),
            "candidate": duplicate_candidates(candidate),
        },
        "confirmed_duplicates": {"baseline": base_confirmed, "candidate": cand_confirmed},
        "duplicate_rates": {"baseline": round(base_rate, 4), "candidate": round(cand_rate, 4),
                            "relative_reduction": round(reduction, 4) if reduction is not None else None},
        "readout": {"baseline": base_readout, "candidate": cand_readout,
                    "improved_segments": improved,
                    "unpaired_candidate_segments": unpaired},
        "candidate_reviewed": reviewed,
        "requirement_coverage": {"baseline": base_cov, "candidate": cand_cov},
        "gates": checks if gate else [],
        "status": "PASS" if gate and all(c["passed"] for c in checks) else
                  "FAIL" if gate else "OBSERVATION_ONLY",
    }
    return report, 0 if not gate or report["status"] == "PASS" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--annotations", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--gate", action="store_true")
    args = parser.parse_args(argv)

    try:
        baseline = _load(args.baseline)
        candidate = _load(args.candidate)
        annotations = _load(args.annotations)
        report, code = evaluate(baseline, candidate, annotations, gate=args.gate)
    except EvaluationInputError as exc:
        print(f"ERROR field={exc.field} message={exc}", file=sys.stderr)
        return 2

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"EVAL={out} STATUS={report['status']}")
    for check in report["gates"]:
        print(f"  {'PASS' if check['passed'] else 'FAIL'} {check['name']}: {check['detail']}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
