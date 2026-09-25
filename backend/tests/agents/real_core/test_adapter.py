"""N23–N25 · 接口安全：run_id / artifact 路径穿越防护（适配版）。

**改写来源**：源库 `backend/tests/agents/real_core/test_adapter.py`（43 行）。
源库测 `app.agents.real_core.artifacts.RealAgentArtifactStore` 与 `normalize_artifacts`；
本项目对应实现是 `backend/app/core/storage.py::StorageManager`。

**判据（任务书 §3.3 N23–N25）**：
- N23 `artifacts/{artifact_id}` 路径穿越必须被拒；
- N24 `run_id` 穿越（`../outside`）必须被拒；
- N25 `DELETE /runs/{id}` 的删除语义与产物清理。

**设计说明（为什么用 pytest.raises + 副作用断言）**：
判据是"必须被拒"，因此断言写"抛错/返回 None + 逃逸目标未被创建/未被删除"。
若实现未做校验，测试将**失败**——这是刻意的：按任务书边界一，发现生产缺陷只登记不修，
缺陷记入《系统测试报告》缺陷台账（N23–N25 关联）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.core.storage import StorageManager


@pytest.fixture()
def store(tmp_path: Path) -> StorageManager:
    """独立沙箱存储：base_dir 指向 pytest 临时目录，绝不触碰真实 data/runs。"""
    return StorageManager(base_dir=tmp_path / "runs")


def test_run_id_path_traversal_is_rejected(store: StorageManager, tmp_path: Path) -> None:
    """N24：run_id=../outside 不得在 base_dir 之外建立目录。"""
    outside = tmp_path / "outside"
    with pytest.raises(Exception):
        store.get_run_dir("../outside")
    assert not outside.exists(), "run_id 穿越逃逸：base_dir 之外被创建了目录"


def test_run_id_absolute_path_is_rejected(store: StorageManager, tmp_path: Path) -> None:
    """N24 补强：绝对路径形式的 run_id 同样必须被拒。"""
    abs_target = tmp_path / "abs_run"
    with pytest.raises(Exception):
        store.get_run_dir(str(abs_target))
    assert not abs_target.exists(), "绝对路径 run_id 逃逸成功"


def test_artifact_id_traversal_cannot_escape(store: StorageManager) -> None:
    """N23：artifact_id 含 ../ 时不得读到 artifacts 目录之外的任何文件。"""
    store.save_artifact_file("run-1", "report.md", "ok")
    assert store.get_artifact_path("run-1", "../../../etc/passwd") is None
    assert store.get_artifact_path("run-1", "../../secret.txt") is None


def test_delete_run_rejects_traversal_and_keeps_outside_intact(
    store: StorageManager, tmp_path: Path
) -> None:
    """N25：delete_run 不得删除 base_dir 之外的内容。"""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("must survive", encoding="utf-8")

    with pytest.raises(Exception):
        store.delete_run("../outside")

    assert outside.exists() and (outside / "keep.txt").exists(), (
        "delete_run 穿越逃逸：base_dir 之外的目录被删除"
    )


def test_delete_run_removes_only_target_run_dir(store: StorageManager) -> None:
    """N25 正向：正常 run_id 的删除语义 = 目标 run 目录消失、同级 run 不受影响。"""
    store.save_artifact_file("run-keep", "report.md", "keep")
    store.save_artifact_file("run-drop", "report.md", "drop")

    assert store.delete_run("run-drop") is True
    assert not (store.base_dir / "run-drop").exists()
    assert (store.base_dir / "run-keep" / "artifacts" / "report.md").exists()
