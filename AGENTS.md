# Repository Guidelines

## Project Structure & Module Organization

- `a17-industry-research-agent/` contains the application: `backend/app/` implements FastAPI orchestration; `frontend/src/` contains Vue views, components, and API clients.
- Application `agents_core/` contains five Python packages: data fetching, analysis, chart generation, chapter writing, and report fusion. Keep algorithms in their package and orchestration in the backend.
- Tests live in `backend/tests/`, `agents_core/*/tests/`, `eval/tests/`, frontend `__tests__/` directories, and `frontend/e2e/`.
- `skills包/` holds shared financial skills and supporting resources.
- Report templates/styles live under `agents_core/report-fusion/report_fusion/`; runtime artifacts belong in `data/runs/` or `output/`.
- Documentation: root `项目全景技术深度解析.md` provides the comprehensive architecture and engineering whitepaper; `a17-industry-research-agent/docs/` holds competition submission drafts, test reports, and archived audits (`PROJECT_AUDIT.md`, `PROJECT_REPAIR_STATUS.md`).

## Build, Test, and Development Commands

Run commands from `a17-industry-research-agent/` unless noted. Use Python 3.11+ and Node.js 22–26 with npm 10+.

- `pip install -r requirements.txt`: install backend and agent dependencies.
- `cd frontend && npm install`: install frontend dependencies.
- `python3 backend/run_server.py`: serve the API on port 8000.
- `cd frontend && npm run dev`: serve the UI on port 5173.
- `./start_system.sh`: launch both services; this script forcibly releases ports 8000 and 5173.
- `python3 -m pytest`: run the default Python suite, excluding `live` tests.
- From `frontend/`, run `npm run verify` for type checking, lint, formatting, and unit tests; `npm run build` for production output; `npm run test:e2e` for Playwright browser tests using installed Chrome.

## Coding Style & Naming Conventions

Use four-space Python indentation, type annotations, `snake_case` functions/modules, and `PascalCase` classes. Use two-space indentation in Vue/TypeScript and `PascalCase.vue` component names. Follow frontend ESLint and Prettier configuration: single quotes, no semicolons, and 100-column print width. Run `npm run format` from `frontend/` when needed.

## Testing Guidelines

Use pytest `test_*.py` files and Vitest `*.spec.ts` files. Cover changed behavior, especially workflow transitions, evidence references, and report rendering. No numeric coverage threshold is configured. Mark credential-dependent Python tests `live`; run deliberately with `python3 -m pytest -m live`.

## Commit & Pull Request Guidelines

Git metadata is absent, so historical conventions cannot be verified. Prefer imperative subjects such as `fix: preserve stage revision history`. Keep changes focused. PRs should describe behavior changes, link relevant issues, list validation, and include screenshots for UI changes.

## Configuration & Agent Guidance

Copy the application's `.env.example` to `.env` for local setup. Keep credentials, `user_settings.json`, generated reports, and logs out of commits. Preserve `record_id` evidence references across pipeline stages. If a repository root contains `.codegraph/`, use CodeGraph before text searches or source reads; otherwise skip it.
