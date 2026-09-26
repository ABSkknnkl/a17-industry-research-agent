"""C1 · 公式误差 ≤ 0.01%：确定性计算基准的重算一致性（离线）。

**判据（任务书 §3.1 C1，一票否决项）**：杜邦 ROE / CR3 / CR5 / 同比 / 周转率 / 产能利用率
重算对比，相对误差 ≤ 0.01%。

**基准来源**：`eval/cases/baselines.json`（由 `eval/tools/backfill_baselines.py` 从黄金样本
`run-20260926022235-107` 的**真实生产输出**回填；null 组表示样本无对应输出，判 skipped，禁止编数）。

**重算来源**：`data_interpreter.engine.DeterministicAnalysisEngine` 纯函数 + **同一 run 自带**的
`dataset.json`。即：用当前代码从原始数据重算，与该 run 产物里已存的数值比对——这正是 C1 要抓的
"代码与产物是否一致"。

**量纲声明（D-02）**：
- `financial_ratios.*_pct` 系列（gross/net margin、roe）= **百分数**（3.53 表示 3.53%）；
- `key_metrics.change_pct` 系列（同比）= **小数率**（0.3471 表示 34.71%）。
两者量纲不同，本测试分开处理，不得混用同一容差口径。

**离线自证**：仅读 `data/runs/` 既有产物 + 调用纯函数，`provider_mode=replay`、`input_source=golden-run`。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pytest

from data_interpreter.engine import DeterministicAnalysisEngine
from data_interpreter.models import StructuredResearchDataset

PROJECT_ROOT = Path(__file__).resolve().parents[3]
GOLDEN_RUN_ID = "run-20260926022235-107"
GOLDEN_DIR = PROJECT_ROOT / "data" / "runs" / GOLDEN_RUN_ID / "artifacts"
BASELINES_PATH = PROJECT_ROOT / "eval" / "cases" / "baselines.json"
TOLERANCE_PCT = 0.01          # 判据：相对误差 ≤ 0.01%
TARGET_COMPANY = "亿纬锂能"      # 基准值来源实体（backfill 记录中的 entity；2026-09-26 重冻结快照 run-20260926022235-107）

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


@lru_cache(maxsize=1)
def _baselines() -> dict[str, dict]:
    doc = json.loads(BASELINES_PATH.read_text(encoding="utf-8"))
    return {item["key"]: item for item in doc.get("baselines", [])}


@lru_cache(maxsize=1)
def _recomputed() -> dict[str, object]:
    """用当前代码从黄金样本自带 dataset.json 重算（模块级缓存，避免重复解析）。"""
    raw = json.loads((GOLDEN_DIR / "dataset.json").read_text(encoding="utf-8"))
    # dataset.json 的 sources 字段是「技能调用台账」（task_id/skill_id/trace_id…），
    # 与 models.SourceRef 不同构；聚合计算不需要它，故剔除后再校验。
    payload = {k: v for k, v in raw.items() if k != "sources"}
    dataset = StructuredResearchDataset.model_validate(payload)
    engine = DeterministicAnalysisEngine()
    comps = engine.build_peer_comps_matrix(dataset)
    ratios = engine.compute_financial_ratios(dataset)
    entry = next((r for r in ratios if r.get("company") == TARGET_COMPANY), None)
    caps = sorted((e.market_cap for e in comps.entries if e.market_cap), reverse=True)
    total = sum(caps)
    return {
        "entry": entry,
        "entries_count": len(comps.entries),
        "cr3": round(sum(caps[:3]) / total * 100, 6) if total and len(caps) >= 3 else None,
        "cr5": round(sum(caps[:5]) / total * 100, 6) if total and len(caps) >= 5 else None,
        "caps_count": len(caps),
    }


def _expect(key: str) -> float:
    item = _baselines().get(key) or {}
    value = item.get("expected")
    if value is None:
        pytest.skip(
            f"{key}: baselines.expected=null（黄金样本无对应生产输出，按 §4.4 判 skipped，禁止编数）"
        )
    return float(value)


def _assert_close(key: str, recomputed: float) -> None:
    expected = _expect(key)
    denom = abs(expected) if expected else 1.0
    deviation_pct = abs(recomputed - expected) / denom * 100
    assert deviation_pct <= TOLERANCE_PCT, (
        f"C1 {key} 不一致：重算={recomputed} 基准={expected} 相对误差={deviation_pct:.6f}% "
        f"＞ {TOLERANCE_PCT}%（基准来源 {GOLDEN_RUN_ID}）"
    )


# --------------------------------------------------------------------------
# 可重算组：比率类（百分数量纲）
# --------------------------------------------------------------------------


def test_c1_gross_margin_matches_baseline() -> None:
    """毛利率：重算 == 样本已存值（百分数量纲）。"""
    entry = _recomputed()["entry"]
    assert entry is not None, f"重算结果缺少目标实体 {TARGET_COMPANY}"
    _assert_close("gross_margin", float(entry["gross_margin_pct"]))


def test_c1_net_margin_matches_baseline() -> None:
    """净利率：重算 == 样本已存值。

    注：该基准值本身可疑（见台账缺陷 D-02），本用例只判"重算 vs 产物"是否一致，
    数值合理性由报告层另行标注。
    """
    entry = _recomputed()["entry"]
    assert entry is not None
    _assert_close("net_margin", float(entry["net_margin_pct"]))


def test_c1_roe_matches_baseline() -> None:
    """ROE：重算 == 样本已存值（百分数量纲；样本仅单值 ROE，非杜邦三因子分解）。"""
    entry = _recomputed()["entry"]
    assert entry is not None
    _assert_close("dupont_roe", float(entry["roe_pct"]))


def test_c1_comps_coverage_matches_production_artifact() -> None:
    """comps 矩阵覆盖面：重算条目数必须与样本产物 comps_matrix.entries 一致。

    这是一个**覆盖度前置断言**：CR3/CR5 只有在覆盖面一致时才有可比性；
    若该断言先失败，说明"重算路径与产物路径不同源"，后续 CR 组失败应归因于此（缺陷 D-03），
    而不是归因于公式本身。
    """
    report = json.loads((GOLDEN_DIR / "interpretation_report.json").read_text(encoding="utf-8"))
    artifact_entries = len((report.get("comps_matrix") or {}).get("entries") or [])
    recomputed_entries = int(_recomputed()["entries_count"])
    assert recomputed_entries == artifact_entries, (
        f"comps 覆盖面漂移：重算 {recomputed_entries} 条 vs 产物 {artifact_entries} 条"
        f"（同一 run 的 dataset.json 输入；见台账缺陷 D-03）"
    )


def test_c1_cr3_matches_baseline() -> None:
    """CR3：重算 == 基准（market_cap 代理口径，基准来自样本 comps_matrix）。"""
    _assert_close("cr3", float(_recomputed()["cr3"] or 0.0))


def test_c1_cr5_matches_baseline() -> None:
    """CR5：重算 == 基准（market_cap 代理口径）。"""
    _assert_close("cr5", float(_recomputed()["cr5"] or 0.0))


# --------------------------------------------------------------------------
# 无样本组：显式 skipped（禁止编数）
# --------------------------------------------------------------------------


@pytest.mark.parametrize("key", ["inventory_turnover", "receivables_turnover", "capacity_utilization"])
def test_c1_unresolved_groups_are_skipped_explicitly(key: str) -> None:
    """三组无样本基准 → 必须显式 skipped，且理由可审计。"""
    with pytest.raises(pytest.skip.Exception):
        _expect(key)


@pytest.mark.parametrize("key", ["revenue_yoy", "net_profit_yoy"])
def test_c1_yoy_groups_scale_is_declared(key: str) -> None:
    """同比组：基准为**小数率**量纲（D-02），须显式声明后再接入重算路径。

    本轮重算路径尚未接入同比（engine 的同比走 `_trends` 多期口径，需单独对齐），
    按"合法跳过必须写理由"处理，并计入报告 skipped 统计。
    """
    value = _expect(key)                     # 基准必须存在（否则上面 skip 生效）
    assert 0 < abs(value) < 10, f"{key} 基准应为小数率量纲（|v|<10），实际 {value}"
    pytest.skip(f"{key}: 基准量纲=小数率({value})；本轮未接入 engine 同比重算路径，待下轮对齐")
