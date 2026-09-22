# Real Five-Agent Integration Design

## Goal

Make the GitHub repository the only runnable project while using the five agent implementations supplied in `行业研究智能体-全链路系统/agents_core` as the production execution engine. Preserve the repository's Vue application, API authentication, ownership checks, LangGraph checkpoints, review flow, and versioned public contracts.

## Constraints

- Production execution must not silently fall back to mock agents.
- Tokens, prompts, raw model responses, `.env` files, databases, and generated reports must not be committed or included in the delivery archive.
- The delivered source must be self-contained and may not depend on the original Desktop path.
- Existing `/api/v1/runs`, review, history, and artifact download contracts remain available.
- Large payloads live in the artifact store; checkpoints retain lightweight state and public summaries.
- A stage cannot report success when its real agent failed or its required artifact is missing.

## Architecture

The five standalone packages are vendored at repository root under `agents_core/`, retaining their package data, skills, templates, and independent tests. `backend/app/agents/real_core/` provides a narrow bridge: a path bootstrap, artifact workspace, no-secret event sink, the imported five-agent adapter, and `StageAgent` wrappers. The existing `workflow/factory.py` registers these wrappers when `REAL_AGENTS_ENABLED=true`; existing implementations remain available for tests and controlled rollback.

The bridge converts `StageContext` into each standalone request, invokes the supplied agent, persists complete results under `ARTIFACT_ROOT/<run_id>/`, and returns the repository's `StageResult`. Artifact references are rewritten to safe paths relative to `ARTIFACT_ROOT`. The LangGraph graph remains responsible for timeout, revision, review, and checkpoint behavior.

## Stage Data Flow

1. `data_fetch` creates the standalone `ResearchRequest`, runs `DataFetcherAgent`, and writes `dataset.json`.
2. `data_interpret` reads `dataset.json`, runs `DataInterpreterAgent`, and writes `interpretation_report.json`.
3. `chart_generate` reads both upstream artifacts, runs `ChartGeneratorAgent`, and writes chart JSON plus SVG files.
4. `chapter_write` reads the analysis and chart artifacts, runs `ChapterWriterAgent`, and writes the 7-chapter/21-section result.
5. `report_fusion` reads all upstream artifacts, runs `ReportFusionAgent`, and publishes Markdown, HTML, PDF, and structured manifests.

The frontend continues to consume `WorkflowState`. Stage payloads remain dictionaries, and the existing views are extended only where the supplied real-agent payload differs from the prototype payload. Bearer authentication remains mandatory in real mode.

## Configuration and Readiness

`REAL_AGENTS_ENABLED` selects the supplied execution engine. Existing settings provide `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`, `IWENCAI_API_KEY`, timeouts, and concurrency. The bridge synchronizes only the required values into the standalone packages at call time. `/health/ready` reports the selected engine and missing credentials without revealing values.

## Failure Handling

Each stage writes into a stage-local temporary directory and publishes artifacts only after model validation. Missing upstream artifacts, credential failures, timeouts, malformed agent results, and renderer failures map to stable public error codes. The graph stops downstream execution and exposes a recoverable review state where appropriate. Download paths remain owner-checked and constrained below `ARTIFACT_ROOT`.

## Testing

- Unit tests cover engine selection, request mapping, safe artifact URIs, missing artifacts, and exception mapping.
- Bridge integration tests run all five supplied agents with deterministic fixtures or their internal fallback boundaries while external network calls are replaced below the agent boundary.
- Workflow/API tests cover auth, ownership, revision conflict, review resume, and artifact download with the real bridge selected.
- The supplied agent test suites run from their vendored locations.
- Frontend tests and production build remain green.
- A credential-gated smoke script runs one complete live task and asserts the five required stage artifacts plus Markdown, HTML, and PDF.

## Delivery

The final ZIP contains tracked source and required static resources only. It excludes `.git`, virtual environments, `node_modules`, caches, databases, logs, `.env` files, test output, and generated runtime artifacts. A SHA-256 checksum accompanies the archive.
