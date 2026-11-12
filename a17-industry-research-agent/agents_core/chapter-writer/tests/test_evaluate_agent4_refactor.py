"""T06: duplicate-candidate detection and the evaluator CLI contract."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import pytest

from chapter_writer.outline import DEFAULT_OUTLINE

ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "evaluate_agent4_refactor", ROOT / "scripts" / "evaluate_agent4_refactor.py")
assert _spec and _spec.loader
evaluator = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(evaluator)

LOCATORS = [
    f"{c.chapter_id}/{s.section_id}/P-{s.section_id[4:]}-01"
    for c in DEFAULT_OUTLINE for s in c.sections
]
CROSS_CHAPTER = [
    "CH-02/SEC-02-01/P-02-01-01",
    "CH-05/SEC-05-01/P-05-01-01",
    "CH-07/SEC-07-03/P-07-03-01",
]


def _chapters(texts: dict[str, str] | None = None,
              kinds: dict[str, str] | None = None) -> list[dict]:
    chapters = []
    for chapter in DEFAULT_OUTLINE:
        sections = []
        for section in chapter.sections:
            pid = f"P-{section.section_id[4:]}-01"
            locator = f"{chapter.chapter_id}/{section.section_id}/{pid}"
            sections.append({
                "section_id": section.section_id, "title": section.title,
                "purpose": section.purpose,
                "paragraphs": [{
                    "paragraph_id": pid,
                    "kind": (kinds or {}).get(locator, "analysis"),
                    "text": (texts or {}).get(locator, f"默认正文 {locator}，本期数值 12.5 亿元。"),
                    "evidence_ids": ["R-A"],
                }],
            })
        chapters.append({"chapter_id": chapter.chapter_id, "title": chapter.title,
                         "sections": sections})
    return chapters


def _result(run_id: str, chapters: list[dict], **overrides) -> dict:
    payload = {
        "run_id": run_id, "source_report_id": "synthetic-a", "subject": "测试行业",
        "outline_version": "2026.1", "chapters": chapters,
    }
    payload.update(overrides)
    return payload


def _write(tmp_path: Path, name: str, payload: dict) -> str:
    path = tmp_path / name
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _annotations(base_dups: list[str], cand_dups: list[str],
                 *, candidate_reviews: bool = True,
                 candidate_reviewed: bool = True,
                 paired: bool = True) -> dict:
    requirements = []
    for version in ("baseline", "candidate"):
        for i in range(4):
            requirements.append({
                "requirement_id": f"q-{i}", "version": version,
                "owner_section_id": "SEC-05-01" if version == "candidate" else None,
                "paragraph_locator": LOCATORS[i], "evidence_ids": ["R-A"],
                "answer_status": "answered" if i < 3 else "gap",
                "reason": "合成标注",
            })
    reviews = []
    for version in ("baseline", "candidate"):
        high = version == "candidate" and candidate_reviews
        for i in range(6):
            reviews.append({
                "version": version, "locator": LOCATORS[i],
                "pair_locator": LOCATORS[i] if paired else f"UNPAIRED-{i}",
                "comparison": 1 if high else 0,
                "meaning": 1 if high and i < 4 else 0,
                "boundary": 1 if high and i < 2 else 0,
                "reason": "合成盲评",
            })
    if not candidate_reviews:
        reviews = [r for r in reviews if r["version"] == "baseline"]
    return {
        "case_id": "case_a_repetitive", "input_sha256": "synthetic",
        "requirements": requirements,
        "duplicate_paragraph_ids": {"baseline": base_dups, "candidate": cand_dups,
                                    "candidate_reviewed": candidate_reviewed},
        "readout_reviews": reviews,
    }


def test_normalise_keeps_numbers_years_units_and_negation():
    text = "  2021 年销量 352.1 万辆 [CHART-02] [R-A] 不能据此判断上升。 "
    cleaned = evaluator.normalise(text)
    assert "[CHART-02]" not in cleaned and "[R-A]" not in cleaned
    assert "2021" in cleaned and "352.1" in cleaned and "万辆" in cleaned
    assert "不能" in cleaned and "上升" in cleaned
    assert " " not in cleaned


def test_jaccard_is_one_for_identical_text():
    assert evaluator.jaccard("abcde", "abcde") == 1.0
    assert evaluator.jaccard("abc", "xyz") == 0.0


def test_exact_cross_chapter_rewrite_is_detected():
    texts = {loc: "比亚迪 2024 年营业收入 7771.02 亿元、毛利率 20.7%。" for loc in CROSS_CHAPTER}
    candidates = evaluator.duplicate_candidates(_result("r1", _chapters(texts)))
    exact = [c for c in candidates if c["method"] == "exact"]
    assert len(exact) == 3  # three pairs across three chapters
    assert all(c["baseline_locator"] in CROSS_CHAPTER for c in exact)


def test_different_periods_are_not_duplicates():
    left, right = CROSS_CHAPTER[0], CROSS_CHAPTER[1]
    texts = {
        left: "2021 年销量 352.1 万辆、渗透率 13.4%，同期出口量未披露。",
        right: "2025 年销量 1286.6 万辆、渗透率 45.8%，同期出口量未披露。",
    }
    candidates = evaluator.duplicate_candidates(_result("r1", _chapters(texts)))
    assert not any({c["baseline_locator"], c["candidate_locator"]} == {left, right}
                   for c in candidates)


def test_different_subject_or_opposite_conclusion_is_not_duplicate():
    left, right = CROSS_CHAPTER[0], CROSS_CHAPTER[1]
    texts_diff_subject = {
        left: "比亚迪 2024 年营业收入 7771.02 亿元，毛利率 20.7%。",
        right: "宁德时代 2024 年研发费用 186.07 亿元，净利率 14.1%。",
    }
    assert not evaluator.duplicate_candidates(_result("r1", _chapters(texts_diff_subject)))

    texts_opposite = {
        left: "该口径下 2024 年毛利率 20.7% 较上年上升，且高于同业中枢。",
        right: "该口径下 2024 年毛利率 20.7% 较上年下降，且低于同业中枢。",
    }
    assert not evaluator.duplicate_candidates(_result("r1", _chapters(texts_opposite)))


def test_negation_difference_is_not_duplicate():
    left, right = CROSS_CHAPTER[0], CROSS_CHAPTER[1]
    texts = {
        left: "2024 年毛利率 20.7%，不能据此判断盈利能力改善。",
        right: "2024 年毛利率 20.7%，可以据此判断盈利能力改善。",
    }
    assert not evaluator.duplicate_candidates(_result("r1", _chapters(texts)))


def test_summary_recap_and_chart_caption_are_excluded():
    loc = CROSS_CHAPTER[0]
    chapters = _chapters(kinds={loc: "transition"})
    rows = evaluator.collect_paragraphs(_result("r1", chapters))
    assert loc not in {r["locator"] for r in rows}

    caption_loc = CROSS_CHAPTER[1]
    chapters = _chapters(texts={caption_loc: "如图 [CHART-01] 所示，数据来自本次证据。"})
    rows = evaluator.collect_paragraphs(_result("r1", chapters))
    assert caption_loc not in {r["locator"] for r in rows}


def test_near_duplicate_respects_threshold_and_shared_evidence():
    left, right = CROSS_CHAPTER[0], CROSS_CHAPTER[1]
    base = "比亚迪 2024 年营业收入 7771.02 亿元、毛利率 20.7%、经营现金流 1335.4 亿元。"
    texts = {left: base, right: base.replace("20.7%", "20.7%").replace("亿元。", "亿元，口径一致。")}
    chapters = _chapters(texts)
    # Give the two paragraphs no shared evidence -> no near-duplicate claim.
    for chapter in chapters:
        for section in chapter["sections"]:
            for paragraph in section["paragraphs"]:
                paragraph["evidence_ids"] = []
    assert not [c for c in evaluator.duplicate_candidates(_result("r1", chapters))
                if c["method"] == "near"]


def test_cli_rejects_missing_file_and_incomparable_versions(tmp_path):
    baseline = _write(tmp_path, "baseline.json", _result("r1", _chapters()))
    candidate = _write(tmp_path, "candidate.json", _result("r2", _chapters()))
    annotations = _write(tmp_path, "annotations.json", _annotations(CROSS_CHAPTER, []))
    output = str(tmp_path / "eval.json")

    assert evaluator.main(["--baseline", str(tmp_path / "nope.json"), "--candidate", candidate,
                           "--annotations", annotations, "--output", output]) == 2

    bad = _write(tmp_path, "bad.json", _result("r3", _chapters(), source_report_id="other"))
    assert evaluator.main(["--baseline", baseline, "--candidate", bad,
                           "--annotations", annotations, "--output", output]) == 2


def test_cli_rejects_locator_that_cannot_be_resolved(tmp_path):
    baseline = _write(tmp_path, "baseline.json", _result("r1", _chapters()))
    candidate = _write(tmp_path, "candidate.json", _result("r2", _chapters()))
    annotations = _write(tmp_path, "annotations.json",
                         _annotations(["CH-99/SEC-99-99/P-99-99-99"], []))
    assert evaluator.main(["--baseline", baseline, "--candidate", candidate,
                           "--annotations", annotations,
                           "--output", str(tmp_path / "eval.json")]) == 2


def test_gate_fails_when_human_candidate_annotations_are_missing(tmp_path):
    baseline = _write(tmp_path, "baseline.json", _result("r1", _chapters()))
    candidate = _write(tmp_path, "candidate.json", _result("r2", _chapters()))
    annotations = _write(tmp_path, "annotations.json",
                         _annotations(CROSS_CHAPTER, [], candidate_reviews=False))
    output = str(tmp_path / "eval.json")
    assert evaluator.main(["--baseline", baseline, "--candidate", candidate,
                           "--annotations", annotations, "--output", output, "--gate"]) == 1
    report = json.loads(Path(output).read_text(encoding="utf-8"))
    assert report["status"] == "FAIL"
    assert any(not check["passed"] for check in report["gates"])


def test_gate_passes_with_complete_annotations(tmp_path):
    texts = {loc: "比亚迪 2024 年营业收入 7771.02 亿元、毛利率 20.7%。" for loc in CROSS_CHAPTER}
    baseline = _write(tmp_path, "baseline.json", _result("r1", _chapters(texts)))
    candidate = _write(tmp_path, "candidate.json", _result("r2", _chapters()))
    annotations = _write(tmp_path, "annotations.json", _annotations(CROSS_CHAPTER, []))
    output = str(tmp_path / "eval.json")
    assert evaluator.main(["--baseline", baseline, "--candidate", candidate,
                           "--annotations", annotations, "--output", output, "--gate"]) == 0
    report = json.loads(Path(output).read_text(encoding="utf-8"))
    assert report["status"] == "PASS"
    assert report["duplicate_rates"]["relative_reduction"] == 1.0
    assert len(report["candidates"]["baseline"]) >= 1


def test_gate_does_not_publish_reduction_without_independent_review(tmp_path):
    """A candidate list that was never reviewed is 'not evaluated', not 100% better."""
    texts = {loc: "比亚迪 2024 年营业收入 7771.02 亿元、毛利率 20.7%。" for loc in CROSS_CHAPTER}
    baseline = _result("r1", _chapters(texts))
    candidate = _result("r2", _chapters())
    annotations = _annotations(CROSS_CHAPTER, [], candidate_reviewed=False)
    report, code = evaluator.evaluate(baseline, candidate, annotations, gate=True)
    assert code == 1
    assert report["candidate_reviewed"] is False
    assert report["duplicate_rates"]["relative_reduction"] is None
    reduction_check = next(c for c in report["gates"] if c["name"] == "duplicate_reduction_30pct")
    assert reduction_check["passed"] is False
    assert "not_evaluated" in reduction_check["detail"]


def test_unpaired_candidate_segments_do_not_inflate_improvement():
    """Unpaired paragraphs must not inherit a baseline score of zero."""
    texts = {loc: "比亚迪 2024 年营业收入 7771.02 亿元、毛利率 20.7%。" for loc in CROSS_CHAPTER}
    baseline = _result("r1", _chapters(texts))
    candidate = _result("r2", _chapters())
    annotations = _annotations(CROSS_CHAPTER, [], paired=False)
    report, _ = evaluator.evaluate(baseline, candidate, annotations, gate=True)
    assert report["readout"]["unpaired_candidate_segments"] == 6
    assert report["readout"]["improved_segments"] == 0
    improved_check = next(c for c in report["gates"] if c["name"] == "readout_at_least_two_improved")
    assert improved_check["passed"] is False


@pytest.mark.parametrize("threshold", [0.85])
def test_default_threshold_matches_spec(threshold):
    assert evaluator.NEAR_DUPLICATE_THRESHOLD == threshold
