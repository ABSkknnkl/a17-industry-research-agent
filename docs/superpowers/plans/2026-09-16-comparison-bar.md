# Comparison Bar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `comparison_bar` as Agent 3's thirteenth production chart type, with signed grouped bars in ECharts and SVG/PDF plus a verified real-code preview.

**Architecture:** Reuse the existing categorical `ChartDataset` and `ChartPoint` models, while adding one public chart type and one dedicated deterministic builder. The router validates two complete aligned series, the service dispatches the builder, and both ECharts and SVG consume the same option semantics.

**Tech Stack:** Python 3.12, Pydantic, pytest, ECharts 5, Vue 3, TypeScript, Vitest, deterministic SVG rendering.

**Spec:** `docs/superpowers/specs/2026-09-16-comparison-bar-design.md`

## Global Constraints

- Keep existing 12 chart types backward compatible.
- Use `ChartDataset(kind="categorical")`; do not add a parallel dataset model.
- Do not fabricate missing series values as zero.
- Keep snake_case across backend, JSON Schema, and TypeScript.
- Preserve financial direction semantics and evidence traceability.
- Do not add runtime dependencies or generated build artifacts to git.
- Push only to `origin/agent/chart-mvp-sync`; never force push.

---

### Task 1: Public chart contract

**Files:**
- Modify: `backend/app/schemas/chart.py`
- Modify: `backend/app/schemas/workflow.py`
- Modify: `backend/app/schemas/analysis.py`
- Modify: `backend/app/schemas/report.py`
- Modify: `contracts/schemas/chart-generation-result.schema.json`
- Modify: `contracts/schemas/chapter-writing-result.schema.json`
- Modify: `frontend/src/api/types.ts`
- Test: `backend/tests/test_contracts.py`

**Interfaces:**
- Consumes: existing `ChartType`, `ChartVariant`, and serialized `ChartSpec`.
- Produces: public literal `comparison_bar` and variant `comparison_bar` in every contract surface.

- [ ] **Step 1: Write failing contract tests**

Add `comparison_bar` to the chart-type enumeration and add this public schema case:

```python
def test_comparison_bar_result_matches_public_schema() -> None:
    spec = ChartSpec(
        chart_id="CHART-COMPARISON",
        title="公司涨跌幅对比",
        chart_type="comparison_bar",
        variant="comparison_bar",
        status="ready",
        dataset_id="DS-COMPARISON",
        evidence_ids=["E-1", "E-2"],
        option={"series": []},
        dedupe_key="comparison_bar:test",
    )
    validate(instance=spec.model_dump(mode="json"), schema=chart_schema)
```

- [ ] **Step 2: Run the contract test and verify rejection**

Run: `cd backend && .venv/bin/pytest -q tests/test_contracts.py`

Expected: FAIL because `comparison_bar` is not accepted by the runtime model and JSON Schema.

- [ ] **Step 3: Add the literal everywhere**

Insert `"comparison_bar"` beside `"bar"` in all chart type unions, and insert it in the variant union:

```python
ChartType = Literal[
    "line",
    "bar",
    "comparison_bar",
    # existing values remain unchanged
]
```

Apply the equivalent string member to both JSON Schemas and both TypeScript chart unions.

- [ ] **Step 4: Run contract tests**

Run: `cd backend && .venv/bin/pytest -q tests/test_contracts.py`

Expected: PASS.

- [ ] **Step 5: Commit the contract slice**

```bash
git add backend/app/schemas contracts/schemas frontend/src/api/types.ts backend/tests/test_contracts.py
git commit -m "feat(chart): add comparison bar contract"
```

### Task 2: Router and ECharts builder

**Files:**
- Modify: `backend/app/agents/chart_generator/router.py`
- Modify: `backend/app/agents/chart_generator/builders.py`
- Modify: `backend/app/agents/chart_generator/service.py`
- Modify: `backend/app/agents/chart_generator/constants.py`
- Test: `backend/tests/agents/chart_generator/test_router.py`
- Test: `backend/tests/agents/chart_generator/test_builders.py`
- Test: `backend/tests/agents/chart_generator/test_chart_capability_mvp.py`

**Interfaces:**
- Consumes: `route_chart("comparison_bar", dataset)` with categorical points.
- Produces: `ChartRouteDecision(accepted=True, variant="comparison_bar")` and `build_comparison_bar_option(title, dataset, theme) -> dict[str, Any]`.

- [ ] **Step 1: Write failing router tests**

Create fixtures with two named series over identical labels, then assert:

```python
decision = route_chart("comparison_bar", complete_dataset)
assert decision.accepted is True
assert decision.variant == "comparison_bar"

incomplete = route_chart("comparison_bar", missing_category_dataset)
assert incomplete.accepted is False
assert incomplete.reason_code == "comparison_bar_series_not_aligned"
```

Also cover one series and all-null values with stable rejection codes.

- [ ] **Step 2: Run router tests and verify failure**

Run: `cd backend && .venv/bin/pytest -q tests/agents/chart_generator/test_router.py`

Expected: FAIL because the expected-kind map and comparison validation are absent.

- [ ] **Step 3: Implement routing**

Map `comparison_bar` to `categorical`, classify it as `comparison`, and validate:

```python
def _has_aligned_comparison_series(dataset: ChartDataset) -> bool:
    by_series: dict[str, set[str]] = defaultdict(set)
    for point in dataset.points:
        if point.value is not None:
            by_series[point.series].add(point.label)
    return len(by_series) == 2 and len({frozenset(labels) for labels in by_series.values()}) == 1
```

Return `comparison_bar_series_not_aligned` when the predicate fails.

- [ ] **Step 4: Write failing builder tests**

Assert two grouped bar series, signed values, explicit zero line, finance direction colors, rotated labels, data zoom for more than the density threshold, evidence mapping, and `%` axis unit:

```python
option = build_comparison_bar_option("涨跌幅对比", dataset, "finance_dashboard")
assert [series["type"] for series in option["series"]] == ["bar", "bar"]
assert option["yAxis"]["min"] < 0 < option["yAxis"]["max"]
assert option["series"][0]["markLine"]["data"] == [{"yAxis": 0}]
assert option["xAxis"]["axisLabel"]["rotate"] == 32
```

- [ ] **Step 5: Run builder tests and verify failure**

Run: `cd backend && .venv/bin/pytest -q tests/agents/chart_generator/test_builders.py -k comparison_bar`

Expected: FAIL because the builder does not exist.

- [ ] **Step 6: Implement the builder and dispatch**

Build categories in first-seen order, calculate a padded signed domain that includes zero, and style each data item by direction:

```python
def direction_item(value: float, series_index: int) -> dict[str, Any]:
    positive = "#C23531" if series_index == 0 else "#E59A96"
    negative = "#2CA58D" if series_index == 0 else "#92CFC2"
    return {"value": value, "itemStyle": {"color": positive if value >= 0 else negative}}
```

Add `_build_option` service dispatch before the generic bar branch.

- [ ] **Step 7: Run focused Agent 3 tests**

Run: `cd backend && .venv/bin/pytest -q tests/agents/chart_generator/test_router.py tests/agents/chart_generator/test_builders.py tests/agents/chart_generator/test_chart_capability_mvp.py`

Expected: PASS.

- [ ] **Step 8: Commit router and builder**

```bash
git add backend/app/agents/chart_generator backend/tests/agents/chart_generator
git commit -m "feat(chart): render signed comparison bars"
```

### Task 3: SVG and report delivery

**Files:**
- Modify: `backend/app/reporting/svg.py`
- Modify: `backend/app/reporting/presentation.py`
- Test: `backend/tests/reporting/test_svg.py`
- Test: `backend/tests/reporting/test_chart_delivery.py`

**Interfaces:**
- Consumes: `ChartSpec(chart_type="comparison_bar", option=<builder output>)`.
- Produces: SVG with grouped positive/negative bars positioned around the true zero coordinate and report label `涨跌幅对比图`.

- [ ] **Step 1: Write failing SVG tests**

Parse rect coordinates from a spec containing `40`, `-20`, `8`, and `-5`; assert positive and negative bars lie on opposite sides of the zero line, both series labels are present, and special characters are escaped.

- [ ] **Step 2: Run SVG tests and verify failure**

Run: `cd backend && .venv/bin/pytest -q tests/reporting/test_svg.py tests/reporting/test_chart_delivery.py -k 'comparison_bar'`

Expected: FAIL with unsupported chart type or missing comparison semantics.

- [ ] **Step 3: Add report labeling and SVG dispatch**

Add:

```python
CHART_TYPE_LABELS["comparison_bar"] = "涨跌幅对比图"
```

Dispatch `comparison_bar` through the cartesian renderer, preserving per-item `itemStyle.color`. Calculate `zero_y` with the same scale transform used for all numeric y positions.

- [ ] **Step 4: Run report tests**

Run: `cd backend && .venv/bin/pytest -q tests/reporting/test_svg.py tests/reporting/test_chart_delivery.py`

Expected: PASS.

- [ ] **Step 5: Commit report delivery**

```bash
git add backend/app/reporting backend/tests/reporting
git commit -m "feat(report): deliver comparison bars in SVG"
```

### Task 4: Frontend type label and rendering regression

**Files:**
- Modify: `frontend/src/components/ChartGallery.vue`
- Modify: `frontend/src/components/__tests__/ChartGallery.spec.ts`

**Interfaces:**
- Consumes: chart specs whose `chart_type` is `comparison_bar`.
- Produces: the user-facing type label `涨跌幅对比图` while preserving generic ECharts mounting and responsive resize behavior.

- [ ] **Step 1: Write a failing component test**

Create a comparison-bar spec and assert:

```typescript
expect(wrapper.text()).toContain('涨跌幅对比图')
expect(echartsInit).toHaveBeenCalledTimes(1)
expect(setOption).toHaveBeenCalledWith(spec.option, true)
```

- [ ] **Step 2: Run the test and verify failure**

Run: `cd frontend && npm run test -- ChartGallery.spec.ts`

Expected: FAIL because the type label map has no `comparison_bar` entry.

- [ ] **Step 3: Add the frontend label**

Add `comparison_bar: '涨跌幅对比图'` to the existing `typeLabels` map. Do not create a special renderer; use the shared ECharts code path.

- [ ] **Step 4: Run frontend verification**

Run: `cd frontend && npm run verify && npm run build`

Expected: all tests, type checks, lint, formatting, and production build pass.

- [ ] **Step 5: Commit frontend support**

```bash
git add frontend/src/components/ChartGallery.vue frontend/src/components/__tests__/ChartGallery.spec.ts
git commit -m "feat(frontend): label comparison bar charts"
```

### Task 5: Thirteenth real-code preview and visual QA

**Files:**
- Modify outside git: `/Users/hanyaohui/Documents/Codex/2026-09-15/x/work/run_agent3_all_finance_charts_preview.py`
- Generate outside git: `/Users/hanyaohui/Documents/Codex/2026-09-15/x/outputs/Agent3-全部13类金融图表生产代码效果.html`
- Generate outside git: `/Users/hanyaohui/Documents/Codex/2026-09-15/x/outputs/Agent3-全部13类金融图表生产代码效果-最终.png`
- Create: `design-qa.md`

**Interfaces:**
- Consumes: the production `build_comparison_bar_option` and a two-series categorical fixture.
- Produces: a 13-card HTML preview, screenshot, and Product Design QA report with `final result: passed`.

- [ ] **Step 1: Add realistic preview data**

Use ten company names and two complete `%` series with both positive and negative values. Append:

```python
(
    "涨跌幅对比图",
    build_comparison_bar_option("公司年度与上周涨跌幅", comparison_dataset, theme),
)
```

- [ ] **Step 2: Generate and capture the preview**

Run the preview script, open the HTML in a real browser, and capture the full desktop grid. Confirm there are exactly 13 chart cards.

- [ ] **Step 3: Run visual comparison**

Compare the attached reference with the rendered thirteenth card. Record zero-axis accuracy, signed direction, series separation, long-label readability, legend clarity, spacing, and responsive containment in `design-qa.md`.

- [ ] **Step 4: Fix P0/P1/P2 findings and repeat capture**

Repeat until `design-qa.md` contains:

```text
final result: passed
```

- [ ] **Step 5: Keep preview artifacts out of git**

Run: `git status --short`

Expected: generated HTML/PNG files outside the repository and only intended source/test changes inside it.

### Task 6: Full verification, commit, and push

**Files:**
- Modify: `docs/changes/2026-09-16-agent3-comparison-bar.md`
- Modify: `design-qa.md`

**Interfaces:**
- Consumes: all prior task outputs.
- Produces: one documented, fully verified branch state pushed to `origin/agent/chart-mvp-sync`.

- [ ] **Step 1: Record the requirement-to-test mapping**

Document the new chart type, important design choices, verification commands, screenshot path, and known limitations without copying test output verbatim.

- [ ] **Step 2: Run full verification**

```bash
cd backend && .venv/bin/pytest -q
cd ../frontend && npm run verify && npm run build
cd ../backend && .venv/bin/black --check app tests
.venv/bin/flake8 --max-line-length=100 app/agents/chart_generator app/reporting tests/agents/chart_generator tests/reporting
.venv/bin/mypy --follow-imports=skip app/agents/chart_generator app/reporting/svg.py
cd .. && git diff --check
```

Expected: all commands exit 0. Existing Rollup chunk-size warnings are non-fatal.

- [ ] **Step 3: Commit documentation and any final verified edits**

```bash
git add docs/changes/2026-09-16-agent3-comparison-bar.md design-qa.md
git commit -m "docs: record comparison bar delivery"
```

- [ ] **Step 4: Confirm clean branch and remote relationship**

```bash
git status --short
git fetch origin agent/chart-mvp-sync
git rev-list --left-right --count origin/agent/chart-mvp-sync...HEAD
```

Expected: clean status and no unexpected remote-only commits.

- [ ] **Step 5: Push without rewriting history**

```bash
git push -u origin agent/chart-mvp-sync
```

If HTTP/2 fails, retry with `git -c http.version=HTTP/1.1 push -u origin agent/chart-mvp-sync`. Never use `--force`.

- [ ] **Step 6: Verify remote SHA**

```bash
git ls-remote --heads origin agent/chart-mvp-sync
git rev-parse HEAD
```

Expected: both SHAs match.
