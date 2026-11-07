"""Run pytest in a disposable source copy without credentials or external sockets.

Usage: python3.11 scripts/verify_audit_offline.py [pytest arguments]
Run this with the project's Python dependencies installed.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile


def main() -> int:
    source = Path(__file__).resolve().parents[1]
    work = Path(tempfile.mkdtemp(prefix="a17-offline-verification-"))
    root = work / "project"
    shutil.copytree(source, root, ignore=shutil.ignore_patterns(
        ".env", ".env.*", "user_settings.json", "node_modules", ".git", ".codegraph",
        "__pycache__", ".pytest_cache", "output", "data", "*.log", "dist",
        "test-results", "playwright-report", ".venv",
    ))
    # Versioned industry reference releases are source inputs, not run output.
    # Keep the allowlisted bundle while excluding runtime data and credentials.
    reference = source / "data" / "industry_reference"
    if reference.is_dir():
        shutil.copytree(reference, root / "data" / "industry_reference")
    os.chdir(root)
    sys.path.insert(0, str(root))
    sys.dont_write_bytecode = True
    for key in tuple(os.environ):
        if any(word in key.upper() for word in ("API_KEY", "TOKEN", "SECRET", "BASE_URL", "OUTPUT_DIR")):
            os.environ.pop(key, None)
    os.environ.update(
        LLM_API_KEY="", OPENAI_API_KEY="", DEEPSEEK_API_KEY="",
        IWENCAI_API_KEY="", IWENCAI_API_KEY_BACKUP="", BATCH_SKILLS="false",
        PYTHONDONTWRITEBYTECODE="1",
    )
    connect = socket.socket.connect

    def offline_connect(sock: socket.socket, address: object) -> object:
        if isinstance(address, tuple) and address[0] not in ("127.0.0.1", "localhost", "::1"):
            raise RuntimeError("External networking disabled during synthetic verification")
        return connect(sock, address)

    socket.socket.connect = offline_connect
    import pytest

    log = work / "pytest.log"
    print(f"COPY={root}\nLOG={log}", flush=True)
    with log.open("w") as handle, contextlib.redirect_stdout(handle), contextlib.redirect_stderr(handle):
        code = pytest.main(["-q", "-rs", "-p", "no:cacheprovider", "--tb=short", *sys.argv[1:]])
    print(log.read_text()[-26000:], flush=True)
    print(f"EXIT={code}", flush=True)
    return int(code)


if __name__ == "__main__":
    raise SystemExit(main())
