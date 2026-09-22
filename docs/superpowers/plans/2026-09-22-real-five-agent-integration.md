# Real Five-Agent Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect the supplied five standalone agents to the repository's authenticated LangGraph workflow and deliver a compact self-contained ZIP.

**Architecture:** Vendor the supplied packages unchanged, adapt them behind the existing `StageAgent` protocol, and select them in the production registry with a configuration flag. Preserve public APIs, ownership checks, checkpoints, and artifact security.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, LangGraph, pytest, Vue 3, TypeScript, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-22-real-five-agent-integration-design.md`

## Global Constraints

- No production mock fallback.
- No Desktop absolute-path dependency.
- No secret, database, runtime artifact, dependency cache, or VCS metadata in the ZIP.
- Existing authenticated API and owner isolation remain enforced.
- Artifact URIs are relative to `ARTIFACT_ROOT` and cannot escape it.

## Review Focus

- Missing LLM or IWENCAI credentials must fail closed with a stable error, never mock data.
- A malicious or absolute artifact path must not become downloadable.
- A missing upstream stage artifact must stop the next agent with a recoverable stage error.
- Review regeneration must use the new revision and replace only that run's stage artifacts.
- A complete run must contain all five real stage outputs and Markdown, HTML, and PDF deliverables.

---

### Task 1: Vendor and load the supplied agents

**Files:**
- Create: `agents_core/**`
- Create: `backend/app/agents/real_core/bootstrap.py`
- Create: `backend/tests/agents/real_core/test_bootstrap.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `ensure_real_agent_packages() -> None`
- Produces: importable `data_fetcher`, `data_interpreter`, `chart_generator`, `chapter_writer`, and `report_fusion` packages.

- [ ] Write a failing test that calls `ensure_real_agent_packages()` and imports all five package entrypoints from the repository copy.
- [ ] Run `backend/.venv/bin/pytest backend/tests/agents/real_core/test_bootstrap.py -q`; expect failure because the bridge and vendored packages do not exist.
- [ ] Copy the five supplied packages and required resources, excluding outputs, caches, `.env`, and metadata files.
- [ ] Implement `ensure_real_agent_packages()` using paths derived from `Path(__file__)`, never the Desktop path.
- [ ] Re-run the test and expect pass.
- [ ] Commit the vendored engine and bootstrap.

### Task 2: Adapt five real agents to StageAgent

**Files:**
- Create: `backend/app/agents/real_core/__init__.py`
- Create: `backend/app/agents/real_core/artifacts.py`
- Create: `backend/app/agents/real_core/adapter.py`
- Create: `backend/app/agents/real_core/stages.py`
- Create: `backend/tests/agents/real_core/test_adapter.py`
- Create: `backend/tests/agents/real_core/test_stages.py`

**Interfaces:**
- Produces: `RealAgentArtifactStore.run_dir(run_id: str) -> Path`
- Produces: `normalize_artifacts(result: StageResult) -> StageResult`
- Produces: five `StageAgent` implementations accepting `StageContext` and returning repository `StageResult`.

- [ ] Write failing tests proving safe relative artifact URIs, traversal rejection, correct `ResearchInput` mapping, upstream artifact checks, and exception-to-error conversion.
- [ ] Run the focused tests and verify the expected missing-symbol failures.
- [ ] Port the supplied adapter logic behind the repository schema and artifact root.
- [ ] Implement the five stage wrappers and no-secret event sink.
- [ ] Run focused tests and the supplied agents' unit suites; expect pass.
- [ ] Commit the bridge.

### Task 3: Wire the real engine into application composition

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/core/readiness.py`
- Modify: `backend/app/workflow/factory.py`
- Modify: `backend/app/workflow/graph.py`
- Modify: `backend/.env.example`
- Create: `backend/tests/workflow/test_real_agent_registry.py`
- Modify: `backend/tests/core/test_readiness.py`

**Interfaces:**
- Consumes: the five stage wrappers from Task 2.
- Produces: `REAL_AGENTS_ENABLED: bool` and a complete selected `StageRegistry`.

- [ ] Write failing tests that enable the flag, assert all five registered stages use the real bridge, and assert missing credentials are reported without values.
- [ ] Run focused tests and verify failures come from absent selection/configuration.
- [ ] Add the setting, registry selection, readiness metadata, and graph compatibility for bridge payloads.
- [ ] Run workflow, security, contract, and readiness tests; expect pass.
- [ ] Commit application wiring.

### Task 4: Verify frontend compatibility and full-chain behavior

**Files:**
- Modify as required: `frontend/src/api/types.ts`
- Modify as required: `frontend/src/components/StageDigest.vue`
- Create: `backend/tests/integration/test_real_agents_bridge.py`
- Create: `backend/scripts/run_real_agents_smoke.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: unchanged `/api/v1` workflow endpoints and Task 3 registry.
- Produces: credential-gated full-chain smoke command and documented setup.

- [ ] Write a failing integration test that exercises all five adapters with controlled external boundaries and asserts required artifacts.
- [ ] Add only the frontend compatibility changes demonstrated necessary by the test fixtures.
- [ ] Add the live smoke runner and setup documentation without embedding credentials.
- [ ] Run backend full tests, agent suites, frontend tests, lint, and build; expect pass.
- [ ] Commit integration and documentation.

### Task 5: Produce the compact delivery archive

**Files:**
- Create outside repository: `outputs/a17-industry-research-agent-integrated.zip`
- Create outside repository: `outputs/a17-industry-research-agent-integrated.zip.sha256`

**Interfaces:**
- Consumes: verified repository HEAD.
- Produces: compact source archive and checksum.

- [ ] Run `./scripts/verify.sh` and read the complete result.
- [ ] Audit the spec requirement-by-requirement and inspect tracked files for forbidden content.
- [ ] Create the ZIP from tracked source plus required vendored resources, excluding `.git`, `.venv`, `node_modules`, caches, databases, logs, `.env`, and runtime artifacts.
- [ ] List and scan the ZIP, extract it to a temporary directory, and run source/import plus frontend build checks there.
- [ ] Generate SHA-256 and report archive size.
