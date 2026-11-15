"""P0 统计闸门回归：零 blocker 才允许进入 P1 改码阶段。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "fixtures"))

from baseline_check import run_checks  # noqa: E402


def test_p0_gate_has_no_blocker_failures():
    result = run_checks()
    blockers = [r for r in result["rules"]
                if r["severity"] == "blocker" and r["status"] == "FAIL"]
    assert blockers == [], f"P0 blocker: {blockers}"
    assert result["passed"] is True
    assert result["rule_count"] >= 70


def test_p0_freezes_both_mothers():
    result = run_checks()
    detail = " ".join(r["detail"] for r in result["rules"])
    assert "19 页" in detail or "页数 19" in detail
    assert "21 页" in detail or "页数 21" in detail
    assert "42" in detail and "35" in detail


def test_a3_discovery_correction_is_recorded():
    import json
    manifest = json.loads((ROOT / "fixtures" / "freeze_manifest.json").read_text(encoding="utf-8"))
    assert "CORRECTION-A3-DISCOVERY" in {
        c["id"] for c in manifest.get("corrections", [])}
    audit = json.loads((ROOT / "fixtures" / "a3_audit.json").read_text(encoding="utf-8"))
    assert audit["run"]["artifact_dir_present"] is True
    assert audit["discovery"]["chart_results_scanned"] > 1
    assert audit["input_lock"]["all_match"] is True
    assert not run_checks()["deferred_blockers"], "产物已验真，不应再有 P3 引用级降级"
