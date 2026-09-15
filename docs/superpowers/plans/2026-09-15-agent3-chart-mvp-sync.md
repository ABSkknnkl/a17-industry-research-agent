# Agent 3 Chart MVP Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver all 16 Agent 3 chart capabilities from `图表改动.md` on the latest `main`, with synchronized runtime, JSON Schema, TypeScript, ECharts, SVG/PDF, tests, audit records, and a pushed change report.

**Architecture:** Keep the existing 12 base chart types and extend their deterministic recipe layer with unit normalization, semantic deduplication, combo routing, annotations, `broker_thin`, and the `dual_panel` layout variant. Agent 3 produces the single semantic chart contract; frontend ECharts and report SVG/PDF consume that contract without independently inferring units, axes, colors, labels, or annotations. Reuse only the relevant production behavior from commit `8bcdd76`, then correct its contract gaps and regressions on current `main`.

**Tech Stack:** Python 3.12, Pydantic v2, pytest, JSON Schema 2020-12, Vue 3, TypeScript, ECharts, Jinja2, SVG, Playwright PDF rendering, Git/GitHub CLI.

**Spec:** `docs/superpowers/specs/2026-09-15-agent3-chart-mvp-sync-design.md`

## Global Constraints

- Implement every one of the 16 numbered requirements in `图表改动.md`; no narrower substitute counts as completion.
- Keep the existing 12 `chart_type` values; `dual_panel` is a variant, not a new base type.
- Unit placeholders are exactly `未提供`, `文本`, `不适用`, and the empty string; they become `[需核实:货币单位]` footnotes instead of axis text.
- Automatic data labels are enabled at 12 visible points and disabled at 13.
- Data health blocks ordinary point data with fewer than 5 rows, fewer than 2 required fields, more than 20% missing values, or inconsistent numeric types.
- `broker_thin` has no grid lines, 1.5px lines, no point circles, and a deep navy primary color.
- A-share directional series use red for positive values and green for negative values.
- `dual_panel` is left/right, shares the time dimension, and does not cross series between panels.
- Audit JSONL has the seven business fields `chart_id`, `stage`, `decision`, `evidence_ids`, `quality_issues`, `degradation`, `retry_of`, plus the runtime envelope.
- Preserve backwards compatibility for chart results without panels or annotations.
- Do not add 3D, maps, smooth curves, Agent 2 prompting, workflow resume changes, or a renderer replacement.
- Do not copy or commit iwencai bundles, caches, virtual environments, logs, build output, or unrelated historical-branch files.
- Work only on `agent/chart-mvp-sync`; never force-push or update `main`.

---

## File Structure

### New files

- `backend/app/agents/chart_generator/constants.py`: single source of chart limits, label threshold, theme colors, contrast threshold, and unit placeholders.
- `backend/app/agents/chart_generator/audit.py`: best-effort append-only JSONL audit writer.
- `backend/tests/agents/chart_generator/test_chart_capability_mvp.py`: requirements 1-10, 14-16 unit and service tests.
- `backend/tests/reporting/test_chart_delivery.py`: requirements 11-13 report, SVG, and HTML delivery tests.
- `docs/changes/2026-09-15-agent3-chart-mvp-sync.md`: user-facing implementation and verification report.

### Modified files

- `backend/app/schemas/chart.py`: panel/annotation contracts, four-series limit, `dual_panel` variant, quality checklist.
- `backend/app/agents/chart_generator/builders.py`: units, labels, axis footnote, annotations, A-share colors, theme, combo, dual panel.
- `backend/app/agents/chart_generator/router.py`: combo unit branches and semantic dedupe normalization.
- `backend/app/agents/chart_generator/quality.py`: conclusive-title, contrast, data-health, and preflight checks.
- `backend/app/agents/chart_generator/service.py`: health gate, true suppression, audit calls, failure records, constants.
- `backend/app/agents/chart_generator/datasets.py`: dataset merge limits and metadata preservation.
- `backend/app/agents/chart_generator/planner.py`: centralized thresholds and semantic fingerprint normalization.
- `backend/app/agents/data_fetcher/fusion.py`: source unit normalization.
- `backend/app/agents/report_fusion/evidence.py`: named source extraction.
- `backend/app/agents/report_fusion/quality.py`: source and chart delivery quality checks.
- `backend/app/agents/report_fusion/visual.py`: centralized density thresholds.
- `backend/app/reporting/html.py`: two-pass continuous numbering and chart directory context.
- `backend/app/reporting/svg.py`: semantic parity for labels, colors, annotations, footnotes, combo, and dual panel.
- `backend/app/reporting/templates/report.html.j2`: chart directory markup.
- `contracts/schemas/chart-generation-result.schema.json`: public contract for variants, panels, annotations, and quality fields.
- `frontend/src/api/types.ts`: TypeScript mirror of the public contract.
- `frontend/src/components/ChartGallery.vue`: consume panel/annotation metadata without dropping it.
- `backend/tests/test_contracts.py`: validate real expanded model output against JSON Schema.
- Existing focused tests under `backend/tests/agents/chart_generator/`, `backend/tests/agents/report_fusion/`, and `backend/tests/reporting/`: regression expectations.

---

### Task 1: Lock the expanded chart contract and centralized constants

**Files:**
- Create: `backend/app/agents/chart_generator/constants.py`
- Create: `backend/tests/agents/chart_generator/test_chart_capability_mvp.py`
- Modify: `backend/app/schemas/chart.py`
- Test: `backend/tests/agents/chart_generator/test_chart_capability_mvp.py`

**Interfaces:**
- Produces: `ChartPanel`, `ChartAnnotation`, `ChartVariant` containing `dual_panel`, `ChartDataset.panels`, `ChartDataset.annotations`, `ChartSpec.panels`.
- Produces: `DATALABEL_MAX_POINTS`, `UNIT_PLACEHOLDERS`, `UP_COLOR`, `DOWN_COLOR`, and existing chart budget constants.
- Consumes: existing Pydantic chart models and `ChartPoint`/`ChartSeriesMeta` conventions.

- [ ] **Step 1: Write failing schema and constant tests**

```python
from datetime import date

from app.agents.chart_generator.constants import DATALABEL_MAX_POINTS, UNIT_PLACEHOLDERS
from app.schemas.chart import (
    ChartAnnotation,
    ChartDataset,
    ChartPanel,
    ChartPoint,
    ChartSeriesMeta,
    ChartSpec,
)

def dataset_with_values(values: list[int | float | None], *, unit: str = "亿元", metric: str = "收入") -> ChartDataset:
    return ChartDataset(
        dataset_id="DS-TEST",
        kind="time_series",
        metric_name=metric,
        unit=unit,
        points=[
            ChartPoint(label=f"202{index}", value=value, evidence_id=f"E-{index}")
            for index, value in enumerate(values, 1)
        ],
        evidence_ids=[f"E-{index}" for index in range(1, len(values) + 1)],
    )

def dataset_with_n_points(count: int) -> ChartDataset:
    return dataset_with_values(list(range(1, count + 1)), metric="同比增速")

def dataset_with_unit(unit: str) -> ChartDataset:
    return dataset_with_values([1, 2, 3, 4, 5], unit=unit)

def spec_with_title(title: str) -> ChartSpec:
    return ChartSpec(
        chart_id="CHART-TITLE",
        title=title,
        chart_type="line",
        variant="line",
        option={"series": [{"type": "line", "data": [1, 2]}]},
        evidence_ids=["E-1"],
        data_fingerprint="a" * 64,
        dedupe_key="trend:test",
    )

def combo_dataset(units: list[str | None], values: list[int | float | None] | None = None) -> ChartDataset:
    names = ["收入", "增速"]
    actual = values or [100, 12]
    metas = [
        ChartSeriesMeta(name=name, unit=unit or "未提供", render_as="bar" if index == 0 else "line")
        for index, (name, unit) in enumerate(zip(names, units, strict=True))
    ]
    return ChartDataset(
        dataset_id="DS-COMBO",
        kind="time_series",
        metric_name="量价",
        points=[
            ChartPoint(label="2025", value=value, series=name, period_end=date(2025, 12, 31), evidence_id=f"E-{index}")
            for index, (name, value) in enumerate(zip(names, actual, strict=True), 1)
        ],
        series_meta=metas,
        evidence_ids=["E-1", "E-2"],
    )

def annotated_panel_dataset() -> ChartDataset:
    return ChartDataset(
        dataset_id="DS-PANELS",
        kind="time_series",
        metric_name="同比增速",
        points=[
            ChartPoint(label=year, value=value, series=series, evidence_id=f"E-{year}-{series}")
            for year, value, series in (("2024", 100, "销量"), ("2025", 120, "销量"), ("2024", -2, "增速"), ("2025", 20, "增速"))
        ],
        series_meta=[
            ChartSeriesMeta(name="销量", unit="万吨", render_as="bar"),
            ChartSeriesMeta(name="增速", unit="%", render_as="line"),
        ],
        panels=[
            ChartPanel(panel_id="volume", position="left", series=["销量"], axis_name="万吨"),
            ChartPanel(panel_id="rate", position="right", series=["增速"], axis_name="%"),
        ],
        annotations=[
            ChartAnnotation(annotation_type="reference_line", label="目标价 8.0", value=8),
            ChartAnnotation(annotation_type="shaded_region", label="政策窗口", start="2024", end="2025"),
            ChartAnnotation(annotation_type="callout", label="年内低点", start="2024", value=-2, series="增速"),
        ],
        evidence_ids=["E-2024-销量", "E-2025-销量", "E-2024-增速", "E-2025-增速"],
    )

def test_chart_contract_supports_four_series_panels_and_annotations() -> None:
    dataset = ChartDataset.model_validate({
        "dataset_id": "DS-PANEL",
        "kind": "time_series",
        "metric_name": "量价",
        "points": [
            {"label": "2024", "value": 1, "series": name, "evidence_id": f"E-{i}"}
            for i, name in enumerate(("销量", "产量", "增速", "价格"), 1)
        ],
        "evidence_ids": ["E-1", "E-2", "E-3", "E-4"],
        "panels": [
            {"panel_id": "volume", "position": "left", "series": ["销量", "产量"], "axis_name": "万吨"},
            {"panel_id": "rate", "position": "right", "series": ["增速", "价格"], "axis_name": "%"},
        ],
        "annotations": [
            {"annotation_type": "reference_line", "label": "目标", "value": 8.0}
        ],
    })
    assert [panel.position for panel in dataset.panels or []] == ["left", "right"]
    assert isinstance(dataset.annotations[0], ChartAnnotation)
    assert isinstance(dataset.panels[0], ChartPanel)
    assert DATALABEL_MAX_POINTS == 12
    assert UNIT_PLACEHOLDERS == frozenset({"未提供", "文本", "不适用", ""})
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `cd backend && .venv/bin/python -m pytest tests/agents/chart_generator/test_chart_capability_mvp.py::test_chart_contract_supports_four_series_panels_and_annotations -q`

Expected: collection/import failure because the constants module and new chart models do not exist.

- [ ] **Step 3: Add the minimum contract and constant definitions**

```python
ChartVariant = Literal[
    "line", "vertical", "horizontal", "grouped", "stacked", "pie",
    "radar", "graph", "combo", "area", "scatter", "bubble", "heatmap",
    "boxplot", "treemap", "dual_panel",
]

class ChartPanel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    panel_id: str = Field(min_length=1, max_length=50)
    position: Literal["left", "right"]
    series: list[str] = Field(min_length=1, max_length=4)
    axis_name: str | None = Field(default=None, max_length=100)

class ChartAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    annotation_type: Literal["reference_line", "shaded_region", "callout"]
    label: str = Field(min_length=1, max_length=100)
    value: float | None = None
    start: str | None = Field(default=None, max_length=200)
    end: str | None = Field(default=None, max_length=200)
    series: str | None = Field(default=None, max_length=100)

DATALABEL_MAX_POINTS = 12
UNIT_PLACEHOLDERS = frozenset({"未提供", "文本", "不适用", ""})
UP_COLOR = "#C0392B"
DOWN_COLOR = "#1E8449"
```

- [ ] **Step 4: Run schema tests and existing chart-model tests**

Run: `cd backend && .venv/bin/python -m pytest tests/agents/chart_generator/test_chart_capability_mvp.py tests/test_contracts.py -q`

Expected: new runtime-model test passes; public JSON Schema test may remain red until Task 6 and is recorded as the expected cross-end gap.

- [ ] **Step 5: Commit the contract foundation**

```bash
git add backend/app/schemas/chart.py backend/app/agents/chart_generator/constants.py backend/tests/agents/chart_generator/test_chart_capability_mvp.py
git commit -m "feat(chart): add panel annotation and limit contracts"
```

### Task 2: Add unit hygiene, data health, conclusive titles, audit, and true suppression

**Files:**
- Create: `backend/app/agents/chart_generator/audit.py`
- Modify: `backend/app/agents/chart_generator/quality.py`
- Modify: `backend/app/agents/chart_generator/service.py`
- Modify: `backend/app/agents/data_fetcher/fusion.py`
- Modify: `backend/tests/agents/chart_generator/test_chart_capability_mvp.py`
- Test: `backend/tests/agents/chart_generator/test_agent.py`

**Interfaces:**
- Produces: `data_health_check(dataset: ChartDataset) -> list[str]`, `check_title_conclusive(spec: ChartSpec) -> bool`, and `record_chart_operation(*, chart_id: str, stage: str, decision: str, evidence_ids: list[str] | None = None, quality_issues: list[str] | None = None, degradation: str | None = None, retry_of: str | None = None, title: str | None = None) -> None`.
- Produces: quality codes `data_health_min_rows`, `data_health_min_fields`, `data_health_missing_ratio`, `data_health_type_consistency`, `title_not_conclusive`.
- Consumes: constants and expanded models from Task 1.

- [ ] **Step 1: Add failing boundary, title, audit, and suppression tests**

```python
def test_data_health_boundaries_and_title_rule(tmp_path, monkeypatch) -> None:
    four_rows = dataset_with_values([1, 2, 3, 4])
    five_rows = dataset_with_values([1, 2, 3, 4, 5])
    exactly_twenty_percent_missing = dataset_with_values([1, 2, 3, 4, None])
    over_twenty_percent_missing = dataset_with_values([1, 2, 3, None, None])
    assert "data_health_min_rows" in data_health_check(four_rows)
    assert "data_health_min_rows" not in data_health_check(five_rows)
    assert "data_health_missing_ratio" not in data_health_check(exactly_twenty_percent_missing)
    assert "data_health_missing_ratio" in data_health_check(over_twenty_percent_missing)
    assert check_title_conclusive(spec_with_title("收入同比增长20%")) is True
    assert check_title_conclusive(spec_with_title("收入趋势")) is False

def test_audit_writes_seven_business_fields(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CHART_AUDIT_DIR", str(tmp_path))
    record_chart_operation(chart_id="CHART-1", stage="route", decision="generated")
    row = json.loads(next(tmp_path.glob("*.jsonl")).read_text().splitlines()[0])
    expected = {"chart_id", "stage", "decision", "evidence_ids", "quality_issues", "degradation", "retry_of"}
    assert expected <= row.keys()
```

- [ ] **Step 2: Run the new focused tests and verify RED**

Run: `cd backend && .venv/bin/python -m pytest tests/agents/chart_generator/test_chart_capability_mvp.py -k 'health or title or audit or suppression' -q`

Expected: missing quality and audit functions, followed by service behavior failures.

- [ ] **Step 3: Implement deterministic validation and audit integration**

```python
_CONCLUSIVE_PATTERNS = re.compile(
    r"\d|同比|环比|增|降|涨|跌|领先|承压|攀升|回落|下滑|高增|收窄|扩大|转正|转负"
)

def check_title_conclusive(spec: ChartSpec) -> bool:
    return bool(_CONCLUSIVE_PATTERNS.search(spec.title))

def data_health_check(dataset: ChartDataset) -> list[str]:
    if dataset.kind == "industry_chain":
        return []
    specialized = {
        "xy": dataset.xy_points,
        "matrix": dataset.matrix_cells,
        "distribution": dataset.distribution_samples,
        "hierarchy": dataset.hierarchy_nodes,
    }
    if dataset.kind in specialized:
        return [] if specialized[dataset.kind] else ["data_health_min_fields"]
    points = list(dataset.points)
    issues: list[str] = []
    if len(points) < 5:
        issues.append("data_health_min_rows")
    values = [point.value for point in points]
    numeric = [value for value in values if isinstance(value, (int, float)) and not isinstance(value, bool)]
    forecast_nulls = sum(
        point.value is None and (point.value_kind == "forecast" or point.label.upper().endswith("E"))
        for point in points
    )
    if points and (len(points) - len(numeric) - forecast_nulls) / len(points) > 0.2:
        issues.append("data_health_missing_ratio")
    if not points or not any(point.label for point in points):
        issues.append("data_health_min_fields")
    if len({type(value) for value in numeric}) > 1:
        issues.append("data_health_type_consistency")
    return issues

def record_chart_operation(*, chart_id: str, stage: str, decision: str,
                           evidence_ids: list[str] | None = None,
                           quality_issues: list[str] | None = None,
                           degradation: str | None = None,
                           retry_of: str | None = None,
                           title: str | None = None) -> None:
    try:
        directory = Path(os.environ.get("CHART_AUDIT_DIR", "artifacts/chart_audit"))
        directory.mkdir(parents=True, exist_ok=True)
        row = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "run_id": _RUN_ID,
            "revision": _REVISION,
            "chart_id": chart_id,
            "stage": stage,
            "decision": decision,
            "evidence_ids": (evidence_ids or [])[:50],
            "quality_issues": (quality_issues or [])[:30],
            "degradation": degradation,
            "retry_of": retry_of,
        }
        if title:
            row["title_sha256"] = hashlib.sha256(title.encode("utf-8")).hexdigest()[:16]
        path = directory / f"{datetime.now(timezone.utc):%Y%m%d}.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    except Exception:
        return
```

In `service.py`, run health checks before routing, omit suppressed duplicates from `specs`, append a `SuppressedChart` with a stable reason, audit generated/suppressed/degraded outcomes, and write chart-generation failures to the existing artifact root. In `fusion.py`, normalize the four unit placeholders before constructing `ChartDataset`.

- [ ] **Step 4: Run Agent 3 service, quality, and workflow smoke tests**

Run: `cd backend && .venv/bin/python -m pytest tests/agents/chart_generator tests/workflow/test_pipeline.py::test_default_registry_runs_real_interpreter_and_chart_generator -q`

Expected: all selected tests pass; if the workflow smoke test fails, stop and diagnose before Task 3.

- [ ] **Step 5: Commit validation and observability**

```bash
git add backend/app/agents/chart_generator/audit.py backend/app/agents/chart_generator/quality.py backend/app/agents/chart_generator/service.py backend/app/agents/data_fetcher/fusion.py backend/tests/agents/chart_generator
git commit -m "feat(chart): enforce health quality and audit gates"
```

### Task 3: Implement semantic dedupe and combo routing

**Files:**
- Modify: `backend/app/agents/chart_generator/router.py`
- Modify: `backend/app/agents/chart_generator/planner.py`
- Modify: `backend/app/agents/chart_generator/datasets.py`
- Modify: `backend/tests/agents/chart_generator/test_chart_capability_mvp.py`
- Test: `backend/tests/agents/chart_generator/test_router.py`
- Test: `backend/tests/agents/chart_generator/test_planner.py`

**Interfaces:**
- Produces: normalized intent slots where `趋势`, `变化`, and `走势` map to `trend`.
- Produces: `route_chart("combo", dataset)` selecting `combo`, `dual_panel`, or suppression/degradation based on non-empty series units.
- Consumes: `ChartDataset.series_meta`, `ChartDataset.panels`, and budget constants.

- [ ] **Step 1: Add failing routing and semantic-dedupe tests**

```python
def test_combo_same_unit_is_single_axis_and_different_unit_is_dual_axis() -> None:
    same = combo_dataset(units=["亿元", "亿元"])
    mixed = combo_dataset(units=["亿元", "%"])
    empty = combo_dataset(units=[None, None], values=[None, None])
    assert route_chart("combo", same).variant == "combo"
    assert len(build_combo_option("收入与利润均增长", same)["yAxis"]) == 1
    assert route_chart("combo", mixed).variant == "combo"
    assert len(build_combo_option("收入增长且增速回升", mixed)["yAxis"]) == 2
    assert route_chart("combo", empty).accepted is False

def test_trend_synonyms_share_one_dedupe_slot() -> None:
    source = dataset_with_values([1, 2, 3, 4, 5])
    keys = {
        build_dedupe_key("line", source, purpose=purpose)
        for purpose in ("展示趋势", "展示变化", "展示走势")
    }
    assert len(keys) == 1
```

- [ ] **Step 2: Run router/planner tests and verify RED**

Run: `cd backend && .venv/bin/python -m pytest tests/agents/chart_generator/test_router.py tests/agents/chart_generator/test_planner.py tests/agents/chart_generator/test_chart_capability_mvp.py -k 'combo or dedupe or synonym' -q`

Expected: same-unit combo currently degrades and synonym keys differ.

- [ ] **Step 3: Implement unit-branch routing and normalized intent keys**

```python
_PURPOSE_ALIASES = {"趋势": "trend", "变化": "trend", "走势": "trend"}

def normalize_purpose(value: str) -> str:
    normalized = normalize_text(value)
    for alias, slot in _PURPOSE_ALIASES.items():
        if alias in normalized:
            return slot
    return normalized

def _normalized_unit(unit: str | None) -> str:
    text = (unit or "").strip()
    return "" if text in UNIT_PLACEHOLDERS else text

def _combo_units(dataset: ChartDataset) -> set[tuple[str, str]]:
    units = {
        (meta.currency or "", _normalized_unit(meta.unit))
        for meta in dataset.series_meta
    }
    units.discard(("", ""))
    return units
```

Accept combo only when it is business-linked, has 2–4 complete time-aligned series, and `_combo_units()` contains one or two units. The builder creates one axis for one unit and left/right axes for two units; no valid unit or all-empty periods are rejected. Preserve merged dataset series metadata and the four-series cap.

- [ ] **Step 4: Run all router/planner/dataset tests**

Run: `cd backend && .venv/bin/python -m pytest tests/agents/chart_generator/test_router.py tests/agents/chart_generator/test_planner.py tests/agents/chart_generator/test_datasets.py tests/agents/chart_generator/test_chart_capability_mvp.py -q`

Expected: all pass.

- [ ] **Step 5: Commit routing behavior**

```bash
git add backend/app/agents/chart_generator/router.py backend/app/agents/chart_generator/planner.py backend/app/agents/chart_generator/datasets.py backend/tests/agents/chart_generator
git commit -m "feat(chart): route combo units and suppress semantic duplicates"
```

### Task 4: Build labels, footnotes, annotations, finance colors, theme, and dual panel options

**Files:**
- Modify: `backend/app/agents/chart_generator/builders.py`
- Modify: `backend/app/agents/chart_generator/service.py`
- Modify: `backend/tests/agents/chart_generator/test_builders.py`
- Modify: `backend/tests/agents/chart_generator/test_chart_capability_mvp.py`

**Interfaces:**
- Produces: ECharts option with `footnotes`, `markLine`, `markArea`, `markPoint`, per-point `itemStyle`, and two-grid `dual_panel` layout.
- Produces: `build_dual_panel_option(title, dataset, theme) -> dict[str, Any]`.
- Consumes: Task 1 models/constants and Task 3 route decisions.

- [ ] **Step 1: Add failing option-structure tests**

```python
def test_labels_units_theme_colors_and_annotations() -> None:
    twelve = build_line_option("同比增长20%", dataset_with_n_points(12), "broker_thin")
    thirteen = build_line_option("同比增长20%", dataset_with_n_points(13), "broker_thin")
    placeholder = build_line_option("同比增长20%", dataset_with_unit("未提供"))
    assert twelve["series"][0]["label"]["show"] is True
    assert thirteen["series"][0]["label"]["show"] is False
    assert placeholder["yAxis"]["name"] == ""
    assert "[需核实:货币单位]" in placeholder["footnotes"]
    assert twelve["xAxis"]["splitLine"]["show"] is False
    assert twelve["series"][0]["lineStyle"]["width"] == 1.5
    assert twelve["series"][0]["showSymbol"] is False

def test_dual_panel_and_all_annotation_types() -> None:
    option = build_dual_panel_option("量增价稳", annotated_panel_dataset(), "broker_thin")
    assert len(option["grid"]) == 2
    assert [series["xAxisIndex"] for series in option["series"]] == [0, 1]
    payload = json.dumps(option, ensure_ascii=False)
    assert all(key in payload for key in ("markLine", "markArea", "markPoint"))
```

- [ ] **Step 2: Run builder tests and verify RED**

Run: `cd backend && .venv/bin/python -m pytest tests/agents/chart_generator/test_builders.py tests/agents/chart_generator/test_chart_capability_mvp.py -k 'label or unit or theme or color or annotation or panel or truncated' -q`

Expected: option helpers and dual-panel builder are absent or return old structures.

- [ ] **Step 3: Implement shared option helpers and builders**

```python
def _auto_datalabel(point_count: int) -> dict[str, Any]:
    return {"show": point_count <= DATALABEL_MAX_POINTS, "position": "top"}

def _unit_text(unit: str | None) -> str:
    return "" if (unit or "").strip() in UNIT_PLACEHOLDERS else str(unit).strip()

def _point_item_style(value: float | None, dataset: ChartDataset) -> dict[str, Any] | None:
    if not _is_updown_dataset(dataset) or value is None:
        return None
    return {"color": UP_COLOR if value >= 0 else DOWN_COLOR}

def _annotation_marks(dataset: ChartDataset) -> dict[str, dict[str, Any]]:
    marks: dict[str, dict[str, Any]] = {}
    for item in dataset.annotations or []:
        target = item.series or "*"
        bucket = marks.setdefault(target, {})
        if item.annotation_type == "reference_line" and item.value is not None:
            bucket["markLine"] = {
                "silent": True,
                "symbol": "none",
                "data": [{"yAxis": item.value, "name": item.label}],
            }
        elif item.annotation_type == "shaded_region" and item.start and item.end:
            bucket["markArea"] = {
                "silent": True,
                "data": [[{"xAxis": item.start, "name": item.label}, {"xAxis": item.end}]],
            }
        elif item.annotation_type == "callout" and item.start and item.value is not None:
            bucket["markPoint"] = {
                "symbol": "pin",
                "data": [{"coord": [item.start, item.value], "name": item.label}],
            }
    return marks
```

Set `yAxis.scale` footnotes to `纵轴未从 0 开始`; apply label logic to visible data points; set two grids/x-axes/y-axes for left/right panels; preserve evidence IDs in data payloads.

- [ ] **Step 4: Run all builder and Agent 3 tests**

Run: `cd backend && .venv/bin/python -m pytest tests/agents/chart_generator -q`

Expected: all pass.

- [ ] **Step 5: Commit chart construction features**

```bash
git add backend/app/agents/chart_generator/builders.py backend/app/agents/chart_generator/service.py backend/tests/agents/chart_generator
git commit -m "feat(chart): add research-grade option rendering"
```

### Task 5: Match SVG/PDF semantics to ECharts

**Files:**
- Modify: `backend/app/reporting/svg.py`
- Create: `backend/tests/reporting/test_chart_delivery.py`
- Modify: `backend/tests/reporting/test_svg.py`

**Interfaces:**
- Produces: `render_chart_svg(spec) -> str` with the same labels, colors, annotations, footnotes, axis bindings, and left/right panels as `spec.option`.
- Produces: `_svg_mark_areas(mark: dict[str, Any], labels: list[str], x_positions: list[float], plot_top: float, plot_height: float) -> list[str]`, `_svg_mark_lines(mark: dict[str, Any], low: float, high: float, plot_left: float, plot_width: float, plot_top: float, plot_height: float) -> list[str]`, and `_svg_mark_points(mark: dict[str, Any], low: float, high: float, labels: list[str], x_positions: list[float], plot_top: float, plot_height: float) -> list[str]` returning escaped SVG fragments.
- Produces: `_render_panel_series(series: list[dict[str, Any]], *, x: float, width: float) -> str` for one horizontal panel.
- Consumes: `ChartSpec.option`, `ChartSpec.panels`, and expanded variant contract.

- [ ] **Step 1: Add failing semantic-parity tests**

```python
def rich_chart_spec_with_labels_marks_colors_and_footnote() -> ChartSpec:
    return ChartSpec(
        chart_id="CHART-RICH",
        title="增速同比提升20%",
        chart_type="line",
        variant="line",
        option={
            "color": ["#C0392B", "#1E8449"],
            "xAxis": {"data": ["2024", "2025"]},
            "yAxis": {"scale": True},
            "footnotes": ["纵轴未从 0 开始"],
            "series": [{
                "name": "同比增速",
                "type": "line",
                "label": {"show": True},
                "data": [
                    {"value": -2, "itemStyle": {"color": "#1E8449"}},
                    {"value": 12, "itemStyle": {"color": "#C0392B"}},
                ],
                "markLine": {"label": {"formatter": "目标价 8.0"}, "data": [{"yAxis": 8}]},
                "markArea": {"label": {"formatter": "政策窗口"}, "data": [[{"xAxis": "2024"}, {"xAxis": "2025"}]]},
                "markPoint": {"label": {"formatter": "年内低点"}, "data": [{"coord": ["2024", -2]}]},
            }],
        },
        evidence_ids=["E-1"],
        footnotes=["纵轴未从 0 开始"],
        data_fingerprint="b" * 64,
        dedupe_key="trend:rich",
    )

def dual_panel_spec() -> ChartSpec:
    return ChartSpec(
        chart_id="CHART-PANEL",
        title="销量增长20%且增速回升",
        chart_type="combo",
        variant="dual_panel",
        option={
            "xAxis": [{"data": ["2024", "2025"]}, {"data": ["2024", "2025"]}],
            "yAxis": [{"name": "万吨"}, {"name": "%"}],
            "series": [
                {"name": "销量", "type": "bar", "data": [100, 120]},
                {"name": "增速", "type": "line", "data": [10, 20]},
            ],
        },
        panels=[
            ChartPanel(panel_id="volume", position="left", series=["销量"], axis_name="万吨"),
            ChartPanel(panel_id="rate", position="right", series=["增速"], axis_name="%"),
        ],
        evidence_ids=["E-1"],
        data_fingerprint="c" * 64,
        dedupe_key="combo:panel",
    )

def test_svg_preserves_option_semantics_for_new_features() -> None:
    spec = rich_chart_spec_with_labels_marks_colors_and_footnote()
    svg = render_chart_svg(spec)
    assert "12.0" in svg
    assert "目标价 8.0" in svg
    assert "政策窗口" in svg
    assert "年内低点" in svg
    assert "纵轴未从 0 开始" in svg
    assert '#C0392B' in svg and '#1E8449' in svg

def test_svg_dual_panel_is_left_right_and_keeps_series_separate() -> None:
    svg = render_chart_svg(dual_panel_spec())
    assert "绝对量" in svg and "相对率" in svg
    assert svg.index("绝对量") < svg.index("相对率")
    assert "销量" in svg and "增速" in svg
```

- [ ] **Step 2: Run SVG tests and verify RED**

Run: `cd backend && .venv/bin/python -m pytest tests/reporting/test_svg.py tests/reporting/test_chart_delivery.py -q`

Expected: new annotation, color, footnote, and dual-panel assertions fail.

- [ ] **Step 3: Implement option-driven SVG rendering**

```python
def _render_series_marks(
    item: dict[str, Any],
    low: float,
    high: float,
    labels: list[str],
    x_positions: list[float],
    *,
    plot_top: float = PLOT_TOP,
    plot_height: float = HEIGHT - PLOT_TOP - PLOT_BOTTOM,
    plot_left: float = PLOT_LEFT,
    plot_width: float = WIDTH - PLOT_LEFT - PLOT_RIGHT,
) -> list[str]:
    parts: list[str] = []
    mark_line = item.get("markLine", {})
    mark_area = item.get("markArea", {})
    mark_point = item.get("markPoint", {})
    parts.extend(_svg_mark_areas(mark_area, labels, x_positions, plot_top, plot_height))
    parts.extend(_svg_mark_lines(mark_line, low, high, plot_left, plot_width, plot_top, plot_height))
    parts.extend(_svg_mark_points(mark_point, low, high, labels, x_positions, plot_top, plot_height))
    return parts

def _render_dual_panel(spec: ChartSpec) -> str:
    series = list(spec.option.get("series", []))
    panels = list(spec.panels or [])
    left_names = set(panels[0].series)
    right_names = set(panels[1].series)
    left_series = [item for item in series if item.get("name") in left_names]
    right_series = [item for item in series if item.get("name") in right_names]
    body = _render_panel_series(left_series, x=60, width=330)
    body += _render_panel_series(right_series, x=430, width=330)
    return _shell(spec, body)
```

Escape all annotation text, reuse explicit option colors, render label values only when option label `show` is true, and append option/spec footnotes below the plot.

- [ ] **Step 4: Run SVG, PDF renderer, and report-fusion rendering tests**

Run: `cd backend && .venv/bin/python -m pytest tests/reporting tests/agents/report_fusion/test_render_contract.py -q`

Expected: all pass.

- [ ] **Step 5: Commit renderer parity**

```bash
git add backend/app/reporting/svg.py backend/tests/reporting/test_svg.py backend/tests/reporting/test_chart_delivery.py
git commit -m "feat(report): synchronize SVG chart semantics"
```

### Task 6: Add named sources, chart directory, and continuous numbering

**Files:**
- Modify: `backend/app/agents/report_fusion/evidence.py`
- Modify: `backend/app/agents/report_fusion/quality.py`
- Modify: `backend/app/agents/report_fusion/visual.py`
- Modify: `backend/app/reporting/html.py`
- Modify: `backend/app/reporting/templates/report.html.j2`
- Modify: `backend/tests/agents/report_fusion/test_render_contract.py`
- Modify: `backend/tests/reporting/test_chart_delivery.py`

**Interfaces:**
- Produces: a stable final chart-number map and chart-directory rows `{number, title, chapter}`.
- Produces: named source strings derived from catalog title/publisher/domain, never bare `[1][2]` only.
- Consumes: final report chart order and evidence catalog.

- [ ] **Step 1: Add failing HTML and source tests**

```python
def _report_view(report_analysis, report_charts, report_chapters) -> ReportViewModel:
    return build_report_view(
        run_id="run-chart-delivery",
        revision=1,
        analysis=report_analysis,
        chart_result=report_charts,
        chapter_result=report_chapters,
        tone="professional",
    )

def test_html_has_chart_directory_and_continuous_numbers(
    report_analysis, report_charts, report_chapters
) -> None:
    html = render_html(_report_view(report_analysis, report_charts, report_chapters))
    assert "图表目录" in html
    for number in range(1, 6):
        assert html.count(f"图{number}") == 2
    assert "所属章节" in html

def test_chart_sources_are_named(report_analysis, report_charts, report_chapters) -> None:
    html = render_html(_report_view(report_analysis, report_charts, report_chapters))
    assert "中国光伏行业协会月度报告" in html
    assert "资料来源：[1]" not in html
```

- [ ] **Step 2: Run report tests and verify RED**

Run: `cd backend && .venv/bin/python -m pytest tests/agents/report_fusion/test_render_contract.py tests/reporting/test_chart_delivery.py -k 'directory or number or source' -q`

Expected: chart directory and named-source assertions fail.

- [ ] **Step 3: Implement two-pass numbering and named source fallback**

```python
def _continuous_chart_toc(
    report: ReportViewModel,
    charts_by_section: dict[str, list[dict[str, object]]],
    unplaced: list[dict[str, object]],
) -> list[dict[str, object]]:
    ordered: list[dict[str, object]] = []
    for chapter in report.chapters:
        for section in chapter.sections:
            ordered.extend(charts_by_section.get(section.section_id, []))
    ordered.extend(unplaced)
    toc: list[dict[str, object]] = []
    for number, item in enumerate(ordered, 1):
        item["display_number"] = f"图{number}"
        toc.append({
            "number": item["display_number"],
            "title": item["title"],
            "section": item.get("placement_section_id") or "附录",
        })
    return toc

def _named_source_label(number: int, items: list[EvidenceCatalogItem]) -> str:
    first = items[0]
    source_name = _truncate(first.source_name, 30)
    named_publishers = "，".join(
        publisher
        for publisher in _unique(item.publisher or "" for item in items)
        if publisher and publisher != "未提供"
    )
    if named_publishers and source_name:
        return f"来源{number}：{source_name}，{named_publishers}整理"
    if source_name:
        return f"来源{number}：{source_name}"
    return f"来源{number}：[需核实:数据来源]"
```

Set `render_html(report, *, continuous_numbering=True)` so the default delivery uses `_continuous_chart_toc`; pass the same mutated chart items to directory and body rendering. Update report quality to flag a ready chart with no resolvable source name. Import density boundaries from `chart_generator.constants` instead of duplicating numbers.

- [ ] **Step 4: Run report-fusion and reporting tests**

Run: `cd backend && .venv/bin/python -m pytest tests/agents/report_fusion tests/reporting -q`

Expected: all pass.

- [ ] **Step 5: Commit report delivery features**

```bash
git add backend/app/agents/report_fusion backend/app/reporting/html.py backend/app/reporting/templates/report.html.j2 backend/tests/agents/report_fusion backend/tests/reporting/test_chart_delivery.py
git commit -m "feat(report): add chart index numbering and named sources"
```

### Task 7: Synchronize JSON Schema, TypeScript, and frontend consumption

**Files:**
- Modify: `contracts/schemas/chart-generation-result.schema.json`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/components/ChartGallery.vue`
- Modify: `backend/tests/test_contracts.py`
- Test: `frontend/src/components/ChartGallery.vue`

**Interfaces:**
- Produces: identical `dual_panel`, `panels`, `annotations`, and quality-checklist field names in Pydantic, JSON Schema, and TypeScript.
- Consumes: runtime contract from Task 1 and ECharts option from Task 4.

- [ ] **Step 1: Add a failing real-model JSON Schema test**

```python
def test_expanded_chart_result_matches_public_schema() -> None:
    spec = ChartSpec(
        chart_id="CHART-CONTRACT",
        title="销量增长20%且增速回升",
        chart_type="combo",
        variant="dual_panel",
        option={
            "xAxis": [{"data": ["2024", "2025"]}, {"data": ["2024", "2025"]}],
            "yAxis": [{"name": "万吨"}, {"name": "%"}],
            "series": [
                {"name": "销量", "type": "bar", "data": [100, 120]},
                {"name": "增速", "type": "line", "data": [10, 20]},
            ],
        },
        panels=[
            ChartPanel(panel_id="volume", position="left", series=["销量"], axis_name="万吨"),
            ChartPanel(panel_id="rate", position="right", series=["增速"], axis_name="%"),
        ],
        evidence_ids=["E-1"],
        data_fingerprint="d" * 64,
        dedupe_key="combo:contract",
    )
    result = ChartGenerationResult(
        chart_specs=[spec],
        quality=ChartQualityReport(
            passed=True,
            ready_count=0,
            suppressed_count=0,
            review_checklist={
                "five_second_readable": True,
                "axis_not_misleading": True,
                "key_point_highlighted": True,
            },
        ),
    )
    payload = result.model_dump(mode="json")
    schema = load_schema("chart-generation-result.schema.json")
    errors = list(Draft202012Validator(schema).iter_errors(payload))
    assert errors == []
    chart = payload["chart_specs"][0]
    assert chart["variant"] == "dual_panel"
    assert len(chart["panels"]) == 2
```

- [ ] **Step 2: Run contract tests and verify RED**

Run: `cd backend && .venv/bin/python -m pytest tests/test_contracts.py::test_expanded_chart_result_matches_public_schema -q`

Expected: JSON Schema rejects `dual_panel`, `panels`, annotations, or expanded quality fields.

- [ ] **Step 3: Update all three contract representations**

```ts
export type ChartVariant =
  | 'line' | 'vertical' | 'horizontal' | 'grouped' | 'stacked'
  | 'pie' | 'radar' | 'graph' | 'combo' | 'area' | 'scatter'
  | 'bubble' | 'heatmap' | 'boxplot' | 'treemap' | 'dual_panel'

export interface ChartPanel {
  panel_id: string
  position: 'left' | 'right'
  series: string[]
  axis_name?: string | null
}

export interface ChartAnnotation {
  annotation_type: 'reference_line' | 'shaded_region' | 'callout'
  label: string
  value?: number | null
  start?: string | null
  end?: string | null
  series?: string | null
}
```

Mirror these shapes in JSON Schema with `additionalProperties` matching the existing contract policy. Ensure `ChartGallery.vue` passes the full option to ECharts and displays footnotes without reinterpreting panel or annotation data.

- [ ] **Step 4: Run backend contracts and frontend static verification**

Run: `cd backend && .venv/bin/python -m pytest tests/test_contracts.py -q`

Run: `cd frontend && npm run lint && npm run build`

Expected: both commands pass with no TypeScript contract errors.

- [ ] **Step 5: Commit cross-end contract synchronization**

```bash
git add contracts/schemas/chart-generation-result.schema.json frontend/src/api/types.ts frontend/src/components/ChartGallery.vue backend/tests/test_contracts.py
git commit -m "feat(chart): synchronize public and frontend contracts"
```

### Task 8: Diagnose regressions, prove all 16 requirements, document, and push

**Files:**
- Modify: only files implicated by reproducible regression failures.
- Create: `docs/changes/2026-09-15-agent3-chart-mvp-sync.md`
- Test: all backend and frontend suites.

**Interfaces:**
- Produces: a clean, tested, documented branch pushed to `origin/agent/chart-mvp-sync`.
- Consumes: all prior task outputs and the 16-row acceptance matrix in the design spec.

- [ ] **Step 1: Run focused and full regression suites**

Run: `cd backend && .venv/bin/python -m pytest tests/agents/chart_generator tests/agents/report_fusion tests/reporting tests/test_contracts.py -q`

Run: `cd backend && .venv/bin/python -m pytest -q`

Run: `cd frontend && npm run lint && npm run build`

Expected: all commands exit 0. Warnings that do not affect exit status are recorded verbatim in the change report.

- [ ] **Step 2: If any regression appears, use systematic debugging before editing**

```text
1. Re-run the smallest failing node with -vv.
2. Compare its output to current main and identify the first divergent field.
3. Write a focused regression test for that field.
4. Make the minimum fix without weakening the 16 feature assertions.
5. Re-run the focused test, its owning suite, then the full suite.
```

Expected: no existing main behavior is traded away to make the new tests green.

- [ ] **Step 3: Audit each numbered requirement against executable evidence**

```text
For requirements 1 through 16, record:
- production file and symbol;
- exact test node proving the behavior;
- PASS command output;
- any intentional scope boundary.
Missing evidence means the requirement is incomplete and implementation continues.
```

- [ ] **Step 4: Write the user-facing change report**

```markdown
# Agent 3 图表能力同步变更报告

## 交付范围
按 1–16 编号逐项列出实现、文件、测试和结果。

## 问财参考
记录实测的柱折图、双轴、图例、单位、时间维度与结论摘要；说明未复制第三方 bundle。

## 验证结果
记录后端全量、前端 lint/build、契约和 SVG/PDF 测试的命令、通过数与日期。

## 已知限制
仅记录设计规格明确排除的 3D、地图、平滑、交易行情和动态 PDF 播放。
```

- [ ] **Step 5: Run completion and repository-hygiene checks**

Run: `git diff --check origin/main..HEAD`

Run: `git status --short && git ls-files | rg '(^|/)(__pycache__|node_modules|dist|\.venv|artifacts|chart_audit)(/|$)'`

Run: `git diff --name-only origin/main..HEAD`

Expected: clean worktree after committing; forbidden-path search has no output; changed files are only scoped production, tests, contract, spec, plan, and change-report files.

- [ ] **Step 6: Commit the verified report and any regression fixes**

```bash
git add docs/changes/2026-09-15-agent3-chart-mvp-sync.md
git commit -m "docs: report Agent 3 chart capability delivery"
```

If regression fixes exist, stage their exact source and test paths in a separate `fix(chart): preserve workflow regressions` commit before the documentation commit.

- [ ] **Step 7: Push and verify the remote branch**

Run: `git push -u origin agent/chart-mvp-sync`

Run: `git ls-remote --heads origin agent/chart-mvp-sync && gh api repos/ABSkknnkl/a17-industry-research-agent/branches/agent/chart-mvp-sync --jq '.name + " " + .commit.sha'`

Expected: both commands report `agent/chart-mvp-sync` at the same local `HEAD` commit.
