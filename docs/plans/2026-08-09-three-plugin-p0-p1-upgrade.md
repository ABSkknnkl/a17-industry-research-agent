# Agent 2—5 P0/P1 Research Quality Upgrade Plan

**Scope:** Borrow the best non-Agent-1 ideas from the industry-researcher, earnings-interpretation, and industry-panorama-research plugins without installing or copying them. Preserve the current human-review workflow and existing 7-chapter/21-section contract.

**Implementation status (2026-08-09):** P0 and P1 scope in this document is complete. Focused Agent 2—5 tests, the full backend suite, strict mypy, targeted Black/Flake8, frontend tests/build, and the Playwright Chromium smoke test passed. The repository-wide frontend format check still reports six pre-existing frontend files; none is part of this backend change.

## Design constraints

- Do not modify Agent 1 or add any data-provider dependency.
- Do not add a new agent or a second workflow engine.
- Keep Agent 2 as the fact/evidence gate.
- Agent 3/4/5 must complete with advisory warnings when upstream evidence passed; only schema/security/runtime failures may block.
- Additive Pydantic fields must have defaults so stored historical runs remain readable.
- Keep Markdown, self-contained HTML, and Playwright Chromium PDF outputs.

### Task 1: Add research-quality data contracts

**Files:**
- Modify: `backend/app/schemas/analysis.py`
- Modify: `backend/app/schemas/chart.py`
- Modify: `backend/app/schemas/report.py`
- Modify: `backend/app/schemas/__init__.py`
- Test: `backend/tests/schemas/test_global_equity_analysis.py`
- Test: `backend/tests/schemas/test_chart_reference.py`
- Test: `backend/tests/agents/report_fusion/test_agent.py`

- [x] Write schema tests for `DataQualityIssue`, `FinancialConsistencyCheck`, `DimensionCoverage`, chart footnotes/quality links, and `delivery_status`.
- [x] Add bounded enums and identifier validation. Use default empty lists on new aggregate fields for backward compatibility.
- [x] Add cross-reference validation where the containing object already knows valid identifiers.
- [x] Run `cd backend && .venv/bin/python -m pytest tests/schemas -q`; all schema tests pass.

### Task 2: Populate and audit Agent 2 quality metadata

**Files:**
- Modify: `backend/app/agents/data_interpreter/graph.py`
- Modify: `backend/app/agents/data_interpreter/prompt_adapter.py`
- Test: `backend/tests/agents/data_interpreter/test_agent.py`

- [x] Add tests proving Agent 2 returns all five `dimension_coverage` entries and quality metadata.
- [x] Extend the runtime contract with explicit `missing/stale/conflict/estimated/not_comparable` semantics and advisory financial checks.
- [x] Audit evidence IDs in quality issues and financial checks exactly like claims, validation cards, scenarios, and chart candidates.
- [x] Keep the existing evidence preflight and quality failure behavior unchanged.
- [x] Run `cd backend && .venv/bin/python -m pytest tests/agents/data_interpreter -q`.

### Task 3: Propagate quality metadata through Agent 3

**Files:**
- Modify: `backend/app/agents/chart_generator/service.py`
- Modify: `backend/app/schemas/chart.py`
- Test: `backend/tests/agents/chart_generator/test_agent.py`
- Test: `backend/tests/agents/chart_generator/test_planner.py`

- [x] Add tests showing a chart linked to advisory data issues is still rendered with footnotes and issue IDs.
- [x] Carry `insight_goal`, evidence IDs, linked issue IDs, and generated footnotes into each ready chart/reference.
- [x] Keep unsupported datasets and render failures advisory; never fabricate replacement values.
- [x] Preserve deterministic routing, mutual-exclusion groups, chart budget, and user selection behavior.
- [x] Run `cd backend && .venv/bin/python -m pytest tests/agents/chart_generator -q`.

### Task 4: Expose quality boundaries to Agent 4

**Files:**
- Modify: `backend/app/agents/chapter_writer/prompt_adapter.py`
- Modify: `backend/app/agents/chapter_writer/service.py`
- Test: `backend/tests/agents/chapter_writer/test_agent.py`

- [x] Add prompt tests proving dimension coverage and quality metadata reach the relevant chapter.
- [x] Pass only chapter-relevant quality issues, consistency checks, and coverage entries to each prompt.
- [x] Instruct the model to use conditional wording for `partial`, explicit boundaries for `insufficient`, and no unsupported numeric conclusions.
- [x] Keep deterministic fallback and targeted regeneration intact.
- [x] Run `cd backend && .venv/bin/python -m pytest tests/agents/chapter_writer -q`.

### Task 5: Add Agent 5 delivery status and quality appendix

**Files:**
- Modify: `backend/app/agents/report_fusion/assembler.py`
- Modify: `backend/app/agents/report_fusion/service.py`
- Modify: `backend/app/reporting/markdown.py`
- Modify: `backend/app/reporting/templates/report.html.j2`
- Modify: `backend/app/schemas/report.py`
- Test: `backend/tests/agents/report_fusion/test_agent.py`

- [x] Add tests for `ready` and `ready_with_limits`, quality appendix content, and preservation of Markdown/HTML when PDF export fails.
- [x] Aggregate data-quality issues, financial checks, incomplete dimensions, skipped charts, and unresolved risks into one report-quality appendix.
- [x] Map usable reports with advisory issues to `ready_with_limits`; reserve stage failure for the absence of every valid deliverable.
- [x] Render the appendix into Markdown and self-contained HTML; let the existing Chromium path include it in PDF.
- [x] Run `cd backend && .venv/bin/python -m pytest tests/agents/report_fusion -q`.

### Task 6: Add P1 research scope and report-depth compatibility

**Files:**
- Modify: `backend/app/schemas/run.py`
- Modify: `backend/app/schemas/analysis.py`
- Modify: `backend/app/schemas/workflow.py`
- Modify: `backend/app/schemas/report.py`
- Modify: `backend/app/agents/chapter_writer/prompt_adapter.py`
- Modify: `backend/app/agents/report_fusion/service.py`
- Test: `backend/tests/workflow/test_pipeline.py`
- Test: `backend/tests/agents/report_fusion/test_agent.py`

- [x] Introduce an optional additive `ResearchBrief` containing geography, time range, inclusions, exclusions, focus companies, and `brief/standard/deep` depth.
- [x] Map the existing `analysis_depth` and chapter target length to this brief without removing old request fields.
- [x] Keep the canonical seven chapters for `standard/deep`; implement `brief` as a concise reading view rather than a different evidence pipeline.
- [x] Verify old run payloads still validate and new payloads propagate to Agents 2, 4, and 5.

### Task 7: Regression and documentation

**Files:**
- Modify: `backend/app/workflow/README.md`
- Modify: `docs/agents/agent2-data-interpreter.md` if present
- Modify: `docs/agents/agent3-chart-generator.md` if present
- Modify: `docs/agents/agent4-chapter-writer.md` if present
- Modify: `docs/agents/agent5-report-fusion.md` if present

- [x] Run focused Agent 2—5 tests.
- [x] Run the full backend suite plus the Playwright Chromium smoke test.
- [x] Run strict mypy, targeted Black/Flake8, frontend tests, and the production build.
- [x] Confirm no tracked environment, secret, generated report, or plugin source was added.
- [x] Update Agent 2—5 and workflow handoff documentation with the new contracts.

## Acceptance criteria

- Historical `AnalysisResult`, chart, chapter, and report JSON remains valid.
- New quality metadata is evidence-linked and visible in the final report.
- Agent 3/4/5 complete when quality issues are advisory.
- The final report clearly distinguishes supported, partial, and insufficient analysis dimensions.
- Markdown and single-file HTML always survive a PDF-only failure.
- No Agent 1 file or external plugin source is modified.
