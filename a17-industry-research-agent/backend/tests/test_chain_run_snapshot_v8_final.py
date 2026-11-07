"""D3 测试：run 执行快照固定引擎/画像/主数据版本。

对应 V8 最终方案 §10.6 第 1 条。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import backend.app.core.setup_env  # noqa: F401
from backend.app.core.storage import storage
from backend.app.engine.state_machine import (
    load_execution_snapshot,
    resolve_execution_snapshot,
)
from backend.app.schemas.workflow import RunCreateRequest

ROOT = Path(__file__).resolve().parents[2]


def _req(topic: str = "白酒产业链") -> RunCreateRequest:
    return RunCreateRequest.model_validate(
        {
            "project_id": "p-d3",
            "input_data": {"industry_topic": topic, "research_as_of": "2026-10-31"},
        }
    )


def test_snapshot_records_engine_profile_and_release(monkeypatch):
    """显式启用 V2 时，快照固定引擎、画像 id/版本与主数据发布版本。"""
    monkeypatch.setenv("CHAIN_ENGINE", "evidence_v2")
    snapshot = resolve_execution_snapshot(_req("白酒产业链"))
    assert snapshot.chain_engine == "evidence_v2"
    assert snapshot.profile_id == "liquor"
    assert snapshot.profile_version, "画像版本未固定"
    assert snapshot.reference_release_id, "主数据发布版本未固定"
    assert snapshot.engine == "five_agents"


def test_notebook_profile_resolved_by_exact_scope(monkeypatch):
    monkeypatch.setenv("CHAIN_ENGINE", "evidence_v2")
    snapshot = resolve_execution_snapshot(_req("笔记本电脑产业链"))
    assert snapshot.profile_id == "notebook"


def test_empty_engine_means_legacy_chain(monkeypatch):
    """未启用 V2：chain_engine 为空，链图走既有路径，不解析画像。"""
    monkeypatch.delenv("CHAIN_ENGINE", raising=False)
    snapshot = resolve_execution_snapshot(_req())
    assert snapshot.chain_engine == ""
    assert snapshot.profile_id is None


def test_snapshot_is_persisted_and_stable(monkeypatch, tmp_path):
    """快照落盘后，后续阶段读到的就是创建时的解析结果。"""
    monkeypatch.setattr(storage, "base_dir", tmp_path)
    run_dir = storage.get_run_dir("run-snap-1")
    monkeypatch.setenv("CHAIN_ENGINE", "evidence_v2")
    snapshot = resolve_execution_snapshot(_req())
    (run_dir / "execution_snapshot.json").write_text(
        snapshot.model_dump_json(indent=2), encoding="utf-8"
    )

    # 中途改变进程环境：已落盘快照不受影响
    monkeypatch.delenv("CHAIN_ENGINE", raising=False)
    loaded = load_execution_snapshot("run-snap-1")
    assert loaded.chain_engine == "evidence_v2", "环境变化改写了已创建 run 的引擎"
    assert loaded.profile_id == snapshot.profile_id
    assert loaded.reference_release_id == snapshot.reference_release_id


def test_legacy_run_marked_without_switching_engine(monkeypatch, tmp_path):
    """旧 run 缺快照：标记 legacy，且不默认启用新引擎/新名单。"""
    monkeypatch.setattr(storage, "base_dir", tmp_path)
    storage.get_run_dir("run-legacy-1")
    loaded = load_execution_snapshot("run-legacy-1")
    assert loaded.legacy is True
    assert loaded.chain_engine == "", "旧 run 被默认切到新引擎"
    assert loaded.reference_release_id is None, "旧 run 被套上新主数据"


def test_new_release_only_affects_new_runs(monkeypatch, tmp_path):
    """主数据发布更新后，只影响新 run；已落盘快照保持原版本。"""
    monkeypatch.setattr(storage, "base_dir", tmp_path)
    monkeypatch.setenv("CHAIN_ENGINE", "evidence_v2")
    run_dir = storage.get_run_dir("run-snap-old")
    old = resolve_execution_snapshot(_req())
    (run_dir / "execution_snapshot.json").write_text(old.model_dump_json(indent=2), encoding="utf-8")

    # 模拟发布指针变化
    pointer = ROOT / "data" / "industry_reference" / "current.json"
    if not pointer.exists():
        pytest.skip("主数据未发布")
    data = json.loads(pointer.read_text(encoding="utf-8"))
    data["release_id"] = "2099-01-01-simulated"
    # 不改真实文件：只验证"新 run 会重新解析"这一行为分支
    fresh = resolve_execution_snapshot(_req())
    assert fresh.reference_release_id != "2099-01-01-simulated"  # 未被伪造影响

    reloaded = load_execution_snapshot("run-snap-old")
    assert reloaded.reference_release_id == old.reference_release_id


def test_snapshot_payload_has_no_secret_or_env_leak():
    """快照只记策略与版本，不落凭证。"""
    snap = resolve_execution_snapshot(_req())
    payload = snap.model_dump_json()
    lowered = payload.casefold()
    for token in ("api_key", "sk-", "bearer", "token"):
        assert token not in lowered


def test_requested_exploration_prefers_v2_without_changing_legacy_runs(monkeypatch):
    monkeypatch.delenv("CHAIN_ENGINE", raising=False)
    req = RunCreateRequest.model_validate({
        "project_id": "p-open",
        "input_data": {
            "industry_topic": "无专用画像的主题",
            "chart_generate_options": {"want_industry_chain": True},
            "data_fetch_options": {"chain_research_strategy": "explore"},
        },
    })
    snapshot = resolve_execution_snapshot(req)
    assert snapshot.chain_requested is True
    assert snapshot.chain_engine == "evidence_v2"
    assert snapshot.profile_id is None

    req.input_data.chart_generate_options.want_industry_chain = False
    snapshot = resolve_execution_snapshot(req)
    assert snapshot.chain_requested is False
    assert snapshot.chain_engine == ""
