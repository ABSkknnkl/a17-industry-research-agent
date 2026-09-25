"""N26 · 五智能体包动态注册（适配版）。

**改写来源**：源库 `backend/tests/agents/real_core/test_bootstrap.py`（26 行）。
源库测 `app.agents.real_core.bootstrap.ensure_real_agent_packages`（vendored 五包加载器）；
本项目对应实现是 `backend/app/core/setup_env.py::init_agent_paths`。

**判据（任务书 §3.3 N26）**：五个包全部可加载，**不得依赖任何绝对路径 / 桌面路径**。
本适配版把"不得依赖绝对路径"落成两条可判事实：
1. 注入 sys.path 的五个目录必须**由 `settings.AGENTS_CORE_DIR` 推导**（而非硬编码）；
2. 五个包名必须都能 `import` 成功。

**离线自证**：import 五个包只读磁盘与注入 sys.path，不触发任何网络或模型调用
（`provider_mode=mock`，`input_source=synthetic`）。
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

from backend.app.core.config import settings
from backend.app.core.setup_env import init_agent_paths

# 五个包的 import 名（目录名 → 包名不同，故显式列出）
AGENT_PACKAGES = {
    "data-fetcher": "data_fetcher",
    "data-analysis": "data_interpreter",
    "chart-generator": "chart_generator",
    "chapter-writer": "chapter_writer",
    "report-fusion": "report_fusion",
}


def test_injected_paths_are_derived_from_configured_agents_core_dir() -> None:
    """注入的五个目录必须来自 AGENTS_CORE_DIR 推导，不得是硬编码/桌面路径。"""
    init_agent_paths()
    expected = {
        str((settings.AGENTS_CORE_DIR / subdir).resolve())
        for subdir in AGENT_PACKAGES
    }
    missing = expected - set(sys.path)
    assert missing == set(), f"未按配置注入的目录: {sorted(missing)}"


def test_all_five_agent_packages_importable() -> None:
    """五个包必须全部可加载（缺一个即为 vendored 资产缺失）。"""
    init_agent_paths()
    failures: dict[str, str] = {}
    for package in sorted(AGENT_PACKAGES.values()):
        try:
            importlib.import_module(package)
        except Exception as exc:  # noqa: BLE001  逐包收集失败原因，最后统一断言
            failures[package] = f"{type(exc).__name__}: {exc}"
    assert failures == {}, f"五个包未全部可加载: {failures}"


def test_agent_paths_do_not_require_desktop_location() -> None:
    """不允许把桌面工作副本路径写进 sys.path（便携性硬约束）。

    判据：注入路径中不得出现 Desktop/桌面目录；允许项目自身的 Downloads 工作区路径。
    """
    init_agent_paths()
    injected = {
        p for p in sys.path if Path(p).parent.name == "agents_core"
    }
    assert injected, "未检测到任何 agents_core 注入路径"
    desktop_hits = [p for p in injected if "Desktop" in p or "桌面" in p]
    assert desktop_hits == [], f"注入路径含桌面依赖: {desktop_hits}"
