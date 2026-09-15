# Task 3 report — semantic dedupe and combo routing

## Implementation

- `backend/app/agents/chart_generator/router.py`
  - Normalizes `趋势`/`变化`/`走势` into the shared `trend` intent slot for dedupe keys while retaining the data fingerprint, so distinct metrics or evidence remain distinct.
  - Normalizes placeholder units, accepts business-linked two-series same-unit and two-unit combos, rejects unknown units and incomplete/unaligned data, and routes valid three/four-series data with exact left/right panel coverage to `dual_panel`.
- `backend/app/agents/chart_generator/datasets.py`
  - Keeps merged time-series covers to four series, carries `series_meta` for same- as well as mixed-unit merges, and applies combo-only completeness/alignment checks.
- `backend/tests/agents/chart_generator/test_router.py`
  - Covers unit normalization, same/mixed/empty combo routing, three-series panel requirements, synonym dedupe, and the data-fingerprint anti-collapse guard.
- `backend/tests/agents/chart_generator/test_datasets.py`
  - Verifies a same-unit merge preserves per-series metadata.

## RED

Command:

```bash
cd backend && .venv/bin/python -m pytest tests/agents/chart_generator/test_router.py tests/agents/chart_generator/test_planner.py tests/agents/chart_generator/test_chart_capability_mvp.py -k 'combo or dedupe or synonym' -q
```

Output: `FFF.` — expected failures: same-unit combo rejected, three-series panel route rejected, and `build_dedupe_key(..., purpose=...)` unsupported.

## GREEN

Commands and output:

```bash
cd backend && .venv/bin/python -m pytest tests/agents/chart_generator/test_router.py tests/agents/chart_generator/test_planner.py tests/agents/chart_generator/test_chart_capability_mvp.py -k 'combo or dedupe or synonym' -q
# 4 passed

cd backend && .venv/bin/python -m pytest tests/agents/chart_generator/test_router.py tests/agents/chart_generator/test_planner.py tests/agents/chart_generator/test_datasets.py tests/agents/chart_generator/test_chart_capability_mvp.py -q
# 30 passed

cd backend && .venv/bin/python -m pytest tests/agents/chart_generator/test_p1_trend.py -q
# 2 passed
```

`git diff --check` also completed with no output.

## Self-review

- Verified exact series-to-meta coverage, non-null aligned periods, unique reporting periods, one/two normalized unit groups, and a two-panel left/right partition without duplicate series.
- Verified that the dedupe key still includes the full data fingerprint; semantic normalization cannot merge different underlying metrics or evidence.
- Verified merged metadata uses the existing non-empty schema contract, retaining `未提供` only as the internal placeholder that router normalization rejects.

## Concern / ownership split

`build_combo_option` currently emits one axis per series. The required same-unit one-axis and mixed-unit two-axis option assertions are intentionally deferred to Task 4, which owns builder/option styling; this task proves the corresponding route acceptance, normalized units, and `dual_panel` selection only.
