#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT_DIR/backend"
.venv/bin/python -m pytest
.venv/bin/black --check app tests
.venv/bin/flake8 app tests
.venv/bin/mypy app

cd "$ROOT_DIR/frontend"
npm run verify
npm run build
