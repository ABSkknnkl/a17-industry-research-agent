import sys
from pathlib import Path
from backend.app.core.config import settings

def init_agent_paths() -> None:
    agents_core = settings.AGENTS_CORE_DIR
    subdirs = [
        agents_core / "data-fetcher",
        agents_core / "data-analysis",
        agents_core / "chart-generator",
        agents_core / "chapter-writer",
        agents_core / "report-fusion",
    ]
    for d in subdirs:
        abs_path = str(d.resolve())
        if abs_path not in sys.path:
            sys.path.insert(0, abs_path)

# 执行初始化
init_agent_paths()
