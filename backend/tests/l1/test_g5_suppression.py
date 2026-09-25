"""G5 · 无数据不绘图 + 抑制语义（黄金样本离线回放）。

**判据来源**：任务书 §3.1「G5 无数据不绘图：evidence 为空/全隔离 → chart=0 且转审核」。

**本文件的判据拆解（把不可直接观测的判据落到可判事实上）**：
1. 每张**已出图**的图表必须带非空 `evidence_ids`（无证据不得出图）；
2. 每条**被抑制**的候选必须带 `reason_code` + 可读 `reason` + `evidence_ids`（抑制必须留痕，不能静默丢弃）；
3. **抑制与出图不得同时成立**：被抑制的图表类型/标题不得出现在最终 charts 中；
4. **抑制理由与数据事实自洽**（关键）：凡以 `insufficient_time_points` 为由抑制时间序列图的，
   数据集中该组实体的可用时间点必须确实稀疏——这条把"图表选型"与 A1 的时间元数据质量
   绑定起来（与台账缺陷 D-05 互为印证）。
"""

from __future__ import annotations

import json
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
GOLDEN_RUN_ID = "run-20260923094843-353"
ARTIFACTS = PROJECT_ROOT / "data" / "runs" / GOLDEN_RUN_ID / "artifacts"
DOMAINS = ("industry", "companies", "financials", "macro", "industry_chain", "reports", "news")

# 时间序列类图表类型（这些图被"缺连续时间点"抑制时，须核对数据事实）
TIME_SERIES_TYPES = {"line", "area", "candlestick"}


@lru_cache(maxsize=1)
def _chart_result() -> dict:
    return json.loads((ARTIFACTS / "chart_result.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _dataset() -> dict:
    return json.loads((ARTIFACTS / "dataset.json").read_text(encoding="utf-8"))


def test_g5_every_chart_has_evidence() -> None:
    """G5：无数据不绘图——每张已出图必须带非空 evidence_ids。"""
    charts = _chart_result().get("charts") or []
    assert charts, "样本无图表，无法判定"
    naked = [str(c.get("chart_id")) for c in charts if not (c.get("evidence_ids") or [])]
    assert naked == [], f"G5 存在无证据支撑的图表: {naked}"


def test_g5_suppressed_candidates_are_traceable() -> None:
    """G5：被抑制的候选必须留痕（reason_code + reason + evidence_ids），不得静默丢弃。"""
    suppressed = _chart_result().get("suppressed_charts") or []
    problems: dict[str, list[str]] = {}
    for idx, item in enumerate(suppressed):
        issues: list[str] = []
        if not str(item.get("reason_code") or "").strip():
            issues.append("缺 reason_code")
        if len(str(item.get("reason") or "").strip()) < 10:
            issues.append("reason 过短（无法审计）")
        if not (item.get("evidence_ids") or []):
            issues.append("缺 evidence_ids")
        if issues:
            problems[str(item.get("title") or f"#{idx}")] = issues
    assert problems == {}, f"G5 抑制记录不可审计: {problems}"


def test_g5_suppressed_types_do_not_appear_in_final_charts() -> None:
    """G5：抑制与出图互斥——被抑制的图表类型不得在最终 charts 中出现同名/同类产物。"""
    charts = _chart_result().get("charts") or []
    suppressed = _chart_result().get("suppressed_charts") or []
    final_titles = {str(c.get("title")) for c in charts}
    conflicts = sorted(
        str(s.get("title")) for s in suppressed if str(s.get("title")) in final_titles
    )
    assert conflicts == [], f"G5 同一标题既被抑制又已出图: {conflicts}"


def test_g5_time_series_suppression_matches_data_reality() -> None:
    """G5（关键）：以「缺少连续时间点」为由抑制时间序列图时，数据事实必须支持该理由。

    判据：`insufficient_time_points` 出现的次数若 > 0，则数据集中**有 period_end 的财务类记录**
    其（实体 × 指标）组合的时间点分布必须确实稀疏（中位时间点数 < 3）。
    若数据实际充足却抑制折线图 → 属**误杀**（图表能力被数据元数据问题掩盖）。
    """
    suppressed = _chart_result().get("suppressed_charts") or []
    reason_codes = {str(s.get("reason_code")) for s in suppressed}
    if "insufficient_time_points" not in reason_codes:
        return  # 本样本未出现该理由，判据不适用（不构成失败）

    dataset = _dataset()
    points: dict[tuple[str, str], set[str]] = defaultdict(set)
    for dom in DOMAINS:
        for record in dataset.get(dom) or []:
            period = record.get("period_end")
            entity = record.get("entity_name") or record.get("entity_code")
            if period and entity:
                points[(str(entity), str(record.get("metric")))].add(str(period))

    if not points:
        raise AssertionError(
            "G5：以 insufficient_time_points 抑制了时间序列图，但数据集中**没有任何** (实体, 指标) 带 period_end —— "
            "抑制理由与数据事实不符（或时间元数据未落盘，见台账缺陷 D-05）"
        )

    counts = sorted(len(v) for v in points.values())
    median_points = counts[len(counts) // 2]
    assert median_points < 3, (
        f"G5 疑似误杀：数据集里 (实体,指标) 组合的时间点中位数为 {median_points}（≥3 可视作充足），"
        f"却以 insufficient_time_points 抑制了折线图；组合数={len(points)}"
    )
