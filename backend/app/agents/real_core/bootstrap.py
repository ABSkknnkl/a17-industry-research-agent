"""Load the standalone agent packages from this repository only."""

from __future__ import annotations

import sys
from pathlib import Path


_PACKAGE_DIRECTORIES = (
    "data-fetcher",
    "data-analysis",
    "chart-generator",
    "chapter-writer",
    "report-fusion",
)


def ensure_real_agent_packages() -> tuple[Path, ...]:
    """Add the five vendored package roots to ``sys.path`` and return them.

    The standalone projects intentionally retain their original import names
    (``data_fetcher``, ``data_interpreter``, and so on).  Resolving from this
    file keeps production independent from the source folder supplied by the
    user and makes the packaged repository relocatable.
    """

    repository_root = Path(__file__).resolve().parents[4]
    agents_root = repository_root / "agents_core"
    package_roots = tuple(agents_root / name for name in _PACKAGE_DIRECTORIES)
    missing = [str(path) for path in package_roots if not path.is_dir()]
    if missing:
        raise RuntimeError(f"Vendored real-agent packages are missing: {', '.join(missing)}")
    for path in reversed(package_roots):
        value = str(path)
        if value not in sys.path:
            sys.path.insert(0, value)
    return package_roots
