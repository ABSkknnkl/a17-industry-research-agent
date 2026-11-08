# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Workspace layout

- `a17-industry-research-agent/` — the application (FastAPI backend + Vue 3 frontend + `agents_core/`). **Run all build/test commands from this directory** unless stated otherwise.
- `skills包/` — shared financial skill resources discovered at runtime; not an installed Python package.
- `项目全景技术深度解析.md` — architecture whitepaper (background, state machine, evidence chain, defect history).
- `AGENTS.md` — repository guidance. `项目全景技术深度解析.md` is the only project-level document kept in this workspace; older handoff notes and plan records were removed.
- No git metadata exists in this workspace.

## Product and pipeline

The system generates industry research reports through five sequential agents:

`data_fetch → data_interpret → chart_generate → chapter_write → report_fusion`

Each stage can pause for human review (`review_stages`), and conclusions must remain traceable through `record_id` evidence references. The backend is a custom state machine over FastAPI; the frontend is a Vue 3 workbench. There is no server-side authentication — the default service must not be exposed publicly.

## Common commands

All paths below assume `cd a17-industry-research-agent` first.

```bash
# Setup
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium   # required for PDF export
cd frontend && npm install && cd ..
cp .env.example .env                              # do not overwrite an existing .env

# Run
./start_system.sh                                 # kills ports 8000/5173, starts both services
.venv/bin/python backend/run_server.py            # backend only
cd frontend && npm run dev                        # frontend only (Vite, port 5173)

# Python tests (offline by default; conftest blanks credentials)
.venv/bin/python -m pytest
.venv/bin/python -m pytest backend/tests/test_event_hub.py::test_event_hub_emit_and_get  # single test
.venv/bin/python -m pytest agents_core/data-fetcher -q                    # one agent package
.venv/bin/python -m pytest -m live                                        # real external services

# Frontend
cd frontend
npm run verify                                    # type-check + lint + prettier + vitest
npm run build
npx vitest run src/views/__tests__/ReportDownloadView.spec.ts              # single spec
npm run test:e2e                                  # Playwright, uses installed Chrome
npx playwright test e2e/comps-editor.spec.ts      # single e2e

# Fully automated end-to-end runs (review_stages=[], no human gate)
.venv/bin/python scripts/run_pipeline_auto.py --topic 低空经济 --depth standard
.venv/bin/python scripts/run_pipeline_auto.py --resume-run <run_id>
.venv/bin/python scripts/run_real_pipeline.py --topic 具身智能 --focus-points ...
```

`pytest.ini` sets `testpaths = agents_core backend eval`, adds every `agents_core/*` package to `pythonpath`, and excludes `live` by default. `eval/` holds fail-closed gate/terminal evaluation harnesses and JSON case files; `scripts/` holds live probes, pipeline runners, and verification utilities.

## Architecture

### Orchestration and persistence

`backend/app/engine/state_machine.py` (`WorkflowEngine`) is the core. `create_run` resolves an `execution_snapshot.json` **once** (chain engine, profile, reference release, model config, input/source hashes), writes `input_data.json`, then launches `data_fetch` as an asyncio task. Later stages and `resume_run` read that snapshot instead of re-reading environment variables, so a run's behavior cannot change mid-flight.

State lives in `data/runs/<run_id>/`:

- `state.json` (current), `revisions/<n>.json` (history), `input_data.json`, `execution_snapshot.json`
- `artifacts/` (stage outputs), `artifacts/charts/` (SVG), `artifacts/images/`

`StorageManager` validates `run_id`/filenames against path traversal and writes atomically. Deleting a run also cleans matching `output/runs/` directories.

### Stage execution and review

`backend/app/agents/adapters.py` (`FiveAgentsAdapter`) wraps each `agents_core` package and is the only bridge between orchestration and agent implementations. Stages exchange files inside the run directory:

- `artifacts/dataset.json` → `artifacts/interpretation_report.json` → `artifacts/chart_result.json` (+ `artifacts/charts/<chart_id>.svg`) → `artifacts/chapter_result.json` → `artifacts/report.md|html|pdf`, `report_view.json`, `consistency_report.json`, `manifest.json`

Stage progression is decided in `_execute_stage`: if the stage is in the run's `review_stages`, it stops at `waiting_review`; otherwise it auto-approves and recurses into the next stage. Passing `review_stages=[]` runs the whole pipeline unattended. `assess_stage_progression` is the single gate that blocks `failed`, zero-record, or hard-blocked stages before downstream execution.

Concurrency is controlled with per-run locks plus a revision CAS: long agent calls capture `input_revision`; when they finish, results are merged only if the latest `state.revision` still matches. User edits (direct edit, revise, regenerate, restore) increment the revision and invalidate downstream stages via `DOWNSTREAM_INVALIDATION`; the stale in-flight result is discarded. `expected_revision` on review requests makes conflicts explicit (`RevisionConflictError`).

### agents_core packages

`backend/app/core/setup_env.py` injects `agents_core/` and each package directory into `sys.path`; packages are **not** installed, so imports are plain top-level names (`data_fetcher`, `data_interpreter`, `chart_generator`, `chapter_writer`, `report_fusion`, `chain_research`). If you add a package, update `setup_env.py`, `pytest.ini`'s `pythonpath`, and the `PYTHONPATH` in `start_system.sh`.

- `data-fetcher/` — planner/coverage loop over the 问财 SkillHub; emits `dataset.json`; owns industry-chain research via `chain-research/` (`CHAIN_ENGINE=evidence_v2`).
- `data-analysis/` — deterministic trend/anomaly/cross-source analysis plus evidence-cited semantic skills; emits `interpretation_report.json`.
- `chart-generator/` — evidence-constrained chart selection and ECharts/SVG generation; zero charts is valid.
- `chapter-writer/` — default 7-chapter/21-section drafting and chapter-level evidence audit.
- `report-fusion/` — fusion, global consistency checks, Markdown/HTML/PDF export via Playwright.
- `chain-research/` — versioned `ChainKnowledgeBundle` shared contract/provider layer; does not import downstream agents.
- `skill_policy/` — merges deterministic `skillhub.select` routing with LLM-selected skills.
- `industry_reference/` — versioned industry master data.
- Shared modules at `agents_core/`: `call_ledger.py`, `context_budget.py` (fails instead of truncating evidence), `event_safety.py`, `financial_semantics.py`.

Skills are discovered by scanning `SKILL.md` files in each agent's `skills/` directory and the workspace `skills包/`; the catalog is served by `GET /api/v1/skills`.

### Configuration precedence

`backend/app/core/config.py` loads `.env` with `os.environ.setdefault` (real environment variables win), then applies `data/user_settings.json` (written by the UI settings endpoints) and copies values back into `os.environ` for agents. Changing `.env` requires a backend restart. `CHAIN_ENGINE` only affects newly created runs; existing runs use their snapshot.

### Events and API

`event_hub` emits `AgentTraceEvent` records per run and supports SSE streaming. Event detail payloads pass through `event_safety.safe_event_details` (whitelisted fields only) before storage/export.

Main endpoints under `/api/v1`: create/list/get/delete runs, revisions and restore, submit reviews, cancel/resume, events (list/summary/SSE), artifact download, skills catalog/detail, and settings config/test endpoints. Report download is gated by `built_at_revision == state.revision`: after any direct edit the old PDF/quality result is stale until re-fusion; `?mode=draft` returns a sanitized limited export when available.

### Frontend

Vue 3 + TypeScript + Vite + Element Plus. Routes (`frontend/src/router.ts`): `/` landing, `/create`, `/runs`, `/skills`, `/runs/:runId` review workbench, `/runs/:runId/report`, `/runs/:runId/download`. `frontend/src/api/client.ts` mirrors the backend endpoints and uses a 5-minute timeout for synchronous create/review calls (a stage can take minutes). Vite proxies `/api` to `http://localhost:8000`; override with `VITE_PROXY_TARGET` or set `VITE_API_BASE_URL`. Unit tests are colocated in `__tests__/`; Playwright e2e is in `frontend/e2e/` and starts Vite on port 4173 with a deliberately unreachable backend proxy.

## Conventions and gotchas

- Preserve `record_id` evidence references across every stage; do not synthesize facts that lack upstream evidence.
- Renaming artifact files or IDs requires coordinated updates in `adapters.py`, `StorageManager.get_artifact_path` / `id_map`, report export code, and the frontend.
- A stage must not be advanced if `assess_stage_progression` returns false; the frontend also surfaces the block reason.
- Direct edits to a fused report invalidate the old PDF and quality verdict — re-fusion and re-validation are required before formal download.
- Do not commit `.env`, `data/user_settings.json`, `data/runs/`, or `output/` (see `.gitignore`).
- The README warns that the current audit status does not certify formal report delivery; treat generated content as requiring human verification.
