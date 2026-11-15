"""P3 · 注册表编号/provenance/outline/coverage 与发布门禁。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent
FIX = ROOT / "fixtures"
sys.path.insert(0, str(ROOT))

from layout.registry import (  # noqa: E402
    build_registry, evaluate_coverage, make_penetration_coverage,
)


def _load(name: str):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def _inputs():
    a3_charts = json.loads(
        (PROJECT / "新能源汽车行业优化报告样例" / "report_a3_charts.json")
        .read_text(encoding="utf-8"))
    return (_load("nev_structure.json"), _load("nev_toc_map.json"),
            _load("a3_audit.json"), a3_charts, _load("nev_outline.json"))


def _build(**kwargs):
    sb_path = FIX / "source_bindings.json"
    sb = json.loads(sb_path.read_text(encoding="utf-8")) if sb_path.exists() else None
    return build_registry(*_inputs(), asset_root=PROJECT,
                          figure_asset_root=PROJECT / "新能源汽车行业优化报告样例",
                          source_bindings=sb, **kwargs)


@pytest.fixture(scope="module")
def registry():
    return _build()


def test_registry_covers_all_toc_keys_and_outline_only_entries(registry):
    kinds = {}
    for e in registry.entries:
        kinds[e.kind] = kinds.get(e.kind, 0) + 1
    assert kinds["section"] == 27
    assert kinds["figure"] == 8
    assert kinds["table"] == 7
    assert kinds["outline_only"] == 6
    assert kinds["section"] + kinds["figure"] + kinds["table"] == 42
    assert len(registry.entries) == 48


def test_fixture_reproduces_mother_numbering(registry):
    # 母本 caption 顺序是 表4/表1/表2/表3/表5/表A1/表A2，不是阅读顺序。
    assert registry.numbering_mode == "preserve_mother"
    assert [e.number for e in registry.figures] == [f"图{i}" for i in range(1, 9)]
    assert [e.number for e in registry.tables] == [
        "表4", "表1", "表2", "表3", "表5", "表A1", "表A2"]
    assert [e.reading_order_number for e in registry.tables] == [
        f"表{i}" for i in range(1, 8)]
    assert registry.validate() == [], registry.validate()


def test_reading_order_mode_numbers_continuously():
    reg = _build(numbering_mode="reading_order")
    assert reg.numbering_mode == "reading_order"
    assert [e.number for e in reg.tables] == [f"表{i}" for i in range(1, 8)]
    assert [e.number for e in reg.figures] == [f"图{i}" for i in range(1, 9)]
    assert reg.validate() == [], reg.validate()


def test_include_in_outline_matches_35_bookmarks(registry):
    selected = [e for e in registry.entries if e.include_in_outline]
    assert len(selected) == 35
    assert registry.outline_only_count == 6
    assert all(e.title for e in selected)
    tabA = {e.meta.get("toc_key") for e in selected if e.kind == "table"}
    assert tabA == {"tabA1", "tabA2"}


def test_figure8_uses_confirmed_panorama_asset(registry):
    fig8 = registry.figures[7]
    prov = fig8.provenance
    assert prov["origin"] == "a3_standalone_chain_panorama"
    assert prov["mother_asset"] == "assets/fig8_chain.png"
    assert prov["asset_replaced_pending"] is True
    assert "产业链图_单跑" in prov["asset_path"]
    assert fig8.title.startswith("图8"), "题注仍来自母本，替换前不得称作 A3 全景图题"
    assert prov["asset_exists"] is True
    assert prov["hash_mismatch"] is False
    assert prov["asset_sha256"] == "11187b00aacd40419129b180f1976d91c2ade557a60dd23f0f8f312241f1bf99"
    assert "不伪造关系证据" in prov["conversion_note"]
    assert fig8.coverage["period_status"] == "not_applicable"
    assert "ASSET_HASH_MISMATCH" not in fig8.blockers


def test_a3_run_artifact_is_verified(registry):
    assert not any(g["id"] == "GAP-A3-RUN-ARTIFACT" for g in registry.blocking_gaps)
    for entry in registry.figures:
        prov = entry.provenance
        # 只有 accepted_a3_chart 是「已验收 ready 图」；a3_compiled 与独立
        # 全景资产各有自己的验收级别，不应硬套 accepted=True。
        if prov["origin"] == "accepted_a3_chart":
            assert prov["accepted"] is True
            assert prov["acceptance_level"] == "artifact_verified"
        else:
            assert prov["acceptance_level"] != "reference_only"
        assert prov["a3_quality"]["passed"] is True
        assert prov["a3_point_errors"] == 0
        assert prov["a3_real_model_participated"] is True
        assert not any("A3_RUN_ARTIFACT_MISSING" in w for w in entry.warnings)


def test_table_a2_source_is_generated_with_gaps(registry):
    tab = next(e for e in registry.tables if e.mother_number == "A2")
    assert tab.source.startswith("资料来源：由图表注册表逐行绑定生成")
    assert tab.meta["source_origin"] == "generated_by_registry_from_row_bindings"
    assert len(tab.meta["source_bindings"]) == 5
    assert {g["id"] for g in tab.meta["source_gaps"]} == {
        "SOURCE_GAP-TABA2-02", "SOURCE_GAP-TABA2-05"}
    assert "SOURCE_MISSING" not in tab.blockers
    assert tab.publish_allowed is True
    assert tab.meta["c5_c6_update"]["mother_preserved"] is True
    assert "59" in tab.meta["c5_c6_update"]["registry_updated_text"]["C-05_current"]


def test_figure8_is_a3_standalone_panorama(registry):
    prov = registry.figures[7].provenance
    assert prov["role"] == "a3_standalone_panorama"
    assert "行业全景" in prov["caption_scope"]
    assert "不是 A2 五家财务样本" in prov["caption_scope"]
    assert prov["acceptance_level"] == "artifact_verified_standalone"
    assert "伪造关系证据" in prov["a3_note"]


def test_publish_gate_is_consistent(registry):
    for e in registry.entries:
        assert e.publish_allowed == (not e.blockers)
    for e in registry.figures:
        assert "UNREGISTERED_REDRAW" not in e.blockers
        assert "ASSET_HASH_MISMATCH" not in e.blockers
    missing_source = [e for e in registry.tables if "SOURCE_MISSING" in e.blockers]
    assert all(not e.publish_allowed for e in missing_source)


def test_old_c5_10_points_cannot_support_full_range():
    cov = make_penetration_coverage(10)
    assert cov["period_start"] == "2025-03" and cov["period_end"] == "2025-12"
    verdict = evaluate_coverage(cov, "2021-02", "2025-12")
    assert not verdict.allowed and verdict.coverage_warning
    assert verdict.code == "COVERAGE_OVERFLOW"
    assert evaluate_coverage(cov, "2025-03", "2025-12").allowed


def test_new_c5_59_points_covers_range_but_keeps_2021_01_gap():
    cov = make_penetration_coverage(59)
    assert cov["period_start"] == "2021-02" and cov["period_end"] == "2025-12"
    assert cov["missing_points"] == ["2021-01"]
    assert cov["expected_points"] == 59
    assert evaluate_coverage(cov, "2021-02", "2025-12").allowed
    assert not evaluate_coverage(cov, "2021-01", "2025-12").allowed


def test_missing_point_blocks_full_assertion():
    cov = make_penetration_coverage(59)
    cov["period_start"] = "2021-01"
    verdict = evaluate_coverage(cov, "2021-01", "2025-12")
    assert not verdict.allowed
    assert verdict.code == "MISSING_POINTS"
    assert verdict.missing_points == ["2021-01"]


def test_c6_unknown_period_is_reported_not_fabricated():
    cov = {"period_status": "unknown", "period_start": None,
           "period_end": None, "missing_points": []}
    verdict = evaluate_coverage(cov, "2023-01", "2025-12")
    assert not verdict.allowed and verdict.coverage_warning
    assert verdict.code == "UNKNOWN_PERIOD"
    assert "照实标注" in verdict.detail
