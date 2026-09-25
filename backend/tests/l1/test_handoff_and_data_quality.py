"""H 类交接契约（H4–H7）+ D 类数据质量（D1/D3/D4）——黄金样本离线回放。

**判据来源**：任务书 §3.1（H4/H5/H7、D1/D3/D4）与 §3.4（判据变更）。
**样本矩阵**：
- H4/H5/D1/D3/D4 → `run-20260923094843-353`（completed 全链路）
- H6 审核恢复 → `run-20260922201207-576`（含多 revision，发生过后置重跑）
- H7 失败语义 → `run-20260922225329-084`（cancelled @ data_interpret）

**判据纪律**：
- D3 的时间合规用「证据 period_end ≤ 检索时点（retrieved_at）」判，不依赖未落盘的 `as_of`；
- D4 的"单位完整"按记录**顶层 `unit` 字段**判（结构化契约字段），`raw_fields` 里的单位痕迹不计入，
  因下游聚合（`peer_comps_matrix` 的单位归一）只读顶层字段。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
GOLDEN_RUN_ID = "run-20260923094843-353"
REVISION_RUN_ID = "run-20260922201207-576"
CANCELLED_RUN_ID = "run-20260922225329-084"
DOMAINS = ("industry", "companies", "financials", "macro", "industry_chain", "reports", "news")

# D4 阈值：结构化记录中顶层 unit 非空率下限（任务书 §3.1 D4「unit 非"未提供"比例达阈值」）
UNIT_COVERAGE_THRESHOLD = 0.60


def _artifact(run_id: str, name: str) -> dict:
    path = PROJECT_ROOT / "data" / "runs" / run_id / "artifacts" / name
    assert path.exists(), f"样本产物缺失: {path}"
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _records() -> list[dict]:
    dataset = _artifact(GOLDEN_RUN_ID, "dataset.json")
    return [r for dom in DOMAINS for r in (dataset.get(dom) or [])]


# --------------------------------------------------------------------------
# H 类：交接契约
# --------------------------------------------------------------------------


def test_h4_chapter_chart_references_are_valid() -> None:
    """H4：A3→A4 图表交接——章节引用的每个 chart_id 必须真实存在于 chart_result。"""
    chapter_res = _artifact(GOLDEN_RUN_ID, "chapter_result.json")
    chart_res = _artifact(GOLDEN_RUN_ID, "chart_result.json")
    available = {str(c.get("chart_id")) for c in chart_res.get("charts") or []}
    referenced: set[str] = set()
    for ch in chapter_res.get("chapters") or []:
        referenced |= {str(i) for i in (ch.get("chart_ids") or [])}
    dangling = sorted(referenced - available)
    assert dangling == [], f"H4 章节引用了不存在的图表: {dangling}"


def test_h5_report_view_carries_all_upstream_payloads() -> None:
    """H5：A2/3/4→A5 全部进入报告产物（章节、图表、证据目录、风险附录）。"""
    view = _artifact(GOLDEN_RUN_ID, "report_view.json")
    assert len(view.get("chapters") or []) > 0, "报告缺章节"
    assert len(view.get("charts") or []) > 0, "报告缺图表"
    assert len(view.get("evidence_catalog") or []) > 0, "报告缺证据目录"
    appendix = view.get("data_quality_appendix") or {}
    assert appendix, "报告缺数据质量/风险附录"
    # 冲突与离群是"风险附录"的实质内容，必须随报告交付
    assert "conflict_items" in appendix and "outlier_items" in appendix, (
        f"风险附录缺关键字段，实际键={sorted(appendix)}"
    )


def test_h6_revision_history_advances_without_pollution() -> None:
    """H6：审核恢复——revision 递增且旧结果不被新结果污染。"""
    run_dir = PROJECT_ROOT / "data" / "runs" / REVISION_RUN_ID
    rev_files = sorted((run_dir / "revisions").glob("*.json"), key=lambda p: int(p.stem))
    assert len(rev_files) >= 2, f"H6 样本应含多版本 revision，实际 {[p.name for p in rev_files]}"

    numbers = [int(p.stem) for p in rev_files]
    assert numbers == sorted(numbers), f"H6 revision 编号未单调递增: {numbers}"
    assert numbers == list(range(1, len(numbers) + 1)), (
        f"H6 revision 编号不连续（存在空洞即历史丢失）: {numbers}"
    )

    latest = json.loads(rev_files[-1].read_text(encoding="utf-8"))
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert int(latest.get("revision", -1)) == int(state.get("revision", -2)), (
        "H6 最新 revision 快照与 state.revision 不一致（版本链断裂）"
    )


def test_h7_cancelled_run_never_fabricates_downstream_success() -> None:
    """H7（关键）：任一阶段失败/取消时，下游不得把空数据包装成成功。"""
    run_dir = PROJECT_ROOT / "data" / "runs" / CANCELLED_RUN_ID
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state.get("status") != "completed", "取消样本不应为 completed"

    stage = str(state.get("current_stage") or "")
    # 停在 data_interpret → 其后所有阶段产物都不得存在
    downstream = {"chart_result.json", "chapter_result.json", "report.md", "report.html", "manifest.json"}
    present = sorted(name for name in downstream if (run_dir / "artifacts" / name).exists())
    assert present == [], (
        f"H7 中断于 {stage}，却存在下游产物 {present}（等于把空数据包装成成功）"
    )


# --------------------------------------------------------------------------
# D 类：数据质量
# --------------------------------------------------------------------------


def test_d1_evidence_entities_are_identifiable() -> None:
    """D1：标的主体匹配——**实体域**记录的主体必须可识别。

    域豁免说明（用例判据修正，§7.4 第②类）：`reports` / `news` 的记录是**资料条目**
    （metric=channel/id/title/summary…），其主体是"某份研报/某条新闻"而非公司，
    本就无 `entity_name`/`entity_code`——实测这两域 227/227 全无实体，属设计如此，非缺陷。
    故本判据只对 industry / companies / financials / macro / industry_chain 五个实体域生效。
    """
    entity_domains = {"industry", "companies", "financials", "macro", "industry_chain"}
    scoped = [r for r in _records() if r.get("domain") in entity_domains]
    assert scoped, "实体域记录为空"
    unresolved = [r.get("record_id") for r in scoped if not (r.get("entity_name") or r.get("entity_code"))]
    ratio = len(unresolved) / len(scoped)
    assert ratio <= 0.05, (
        f"D1 实体域中 {len(unresolved)}/{len(scoped)}（{ratio:.1%}）记录既无 entity_name 也无 entity_code"
    )


def test_d3_evidence_periods_do_not_exceed_retrieval_time() -> None:
    """D3：时间范围符合——证据的报告期不得晚于其检索时点（无前视数据）。"""
    violations: list[tuple[str, str, str]] = []
    for r in _records():
        period = r.get("period_end")
        retrieved = str((r.get("source") or {}).get("retrieved_at") or "")
        if period and retrieved:
            if str(period) > retrieved[:10]:
                violations.append((str(r.get("record_id")), str(period), retrieved[:10]))
    assert violations == [], f"D3 存在报告期晚于检索时点的记录（前视数据）: {violations[:5]}"


def test_d3_period_coverage_in_time_sensitive_domains() -> None:
    """D3 覆盖度：时间敏感域（reports / news）的记录必须带报告期或发布时点。

    判据采用**缺失率阈值**而非零容忍：实测 `reports` 79/79 均有 `published_at`（合规），
    而 `news` 有 17/148（11.5%）既无 `period_end` 也无 `published_at` ——
    这类记录无法判定时效性，属数据获取/落盘缺陷（见台账缺陷 D-05）。
    阈值取 5%：允许少量源侧无时间的条目，但不得成规模。
    """
    max_missing_ratio = 0.05
    records = _records()
    bad: dict[str, dict[str, float]] = {}
    for dom in ("reports", "news"):
        items = [r for r in records if r.get("domain") == dom]
        if not items:
            continue
        missing = [r for r in items if not r.get("period_end") and not r.get("published_at")]
        ratio = len(missing) / len(items)
        if ratio > max_missing_ratio:
            bad[dom] = {"missing": len(missing), "total": len(items), "ratio": round(ratio, 4)}
    assert bad == {}, (
        f"D3 时间敏感域缺时间字段超过 {max_missing_ratio:.0%} 阈值: {bad}"
        f"（无时间的记录无法判定时效性，下游时间轴/同比均受影响）"
    )


def test_d4_unit_coverage_meets_threshold() -> None:
    """D4：单位完整——顶层 `unit` 非空率必须达到阈值（下游单位归一依赖该字段）。"""
    records = _records()
    with_unit = [r for r in records if str(r.get("unit") or "").strip() not in ("", "未提供", "-")]
    ratio = len(with_unit) / len(records)
    assert ratio >= UNIT_COVERAGE_THRESHOLD, (
        f"D4 顶层 unit 覆盖率 {ratio:.1%} 低于阈值 {UNIT_COVERAGE_THRESHOLD:.0%}"
        f"（{len(with_unit)}/{len(records)}）；下游 peer_comps 单位归一将退化为无序数比较"
    )
