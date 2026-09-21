"""报告质量评分器 Q 类原子判定项（EVALUATION_PLAN §4.11，2026-09-19 方案 §3）。

定位（§1 MUST NOT 对齐）：**生产分数是唯一权威**，本模块只「重算校验」生产
评分对象（ReportQualityReport dump）的内部一致性与不变量，**不复制 5 维评分
算法**（避免双实现漂移）。维度 key 直接从生产模块导入，单一来源。

输入 = transcript 提取的标准评分对象，兼容三种挂载位置：
  artifacts["report_quality"]                    （预提取，首选）
  artifacts["fusion_result"]["quality"]          （完整 fusion payload）
  artifacts["report_fusion"]["data"]["quality"]  （原始阶段结果）

每个判定项输出 ``CheckResult(check_id, passed, reason)``，对应 grades.jsonl 一行。
一票否决项：Q1（总分一致性）、Q2（分项加和/边界）、Q5（缺口必扣）。
（Q6 LLM 隔离 / Q7 表达软分范围随表达维一并移除，2026-09-19。）
"""

from __future__ import annotations

from typing import Any

# 维度 key 单一来源：直接复用生产常量，杜绝评测层与生产层 key 漂移。
from app.agents.report_fusion.quality import (
    DIM_CITATION,
    DIM_DIMENSION,
    DIM_EVIDENCE,
    DIM_RISK,
    DIM_STRUCTURE,
)
from eval.scorers.rules import CheckResult

# Q 类判定项全集（Q6/Q7 随表达维移除后收缩为 Q1-Q5）。
QUALITY_CHECK_IDS = frozenset({"Q1", "Q2", "Q3", "Q4", "Q5"})

# 一票否决项（Q6 移除后收缩）。
QUALITY_VETO_CHECKS = frozenset({"Q1", "Q2", "Q5"})


def _quality_obj(artifacts: dict[str, Any]) -> dict[str, Any] | None:
    """从 artifacts 提取生产评分对象，兼容三种挂载位置。"""
    if not isinstance(artifacts, dict):
        return None
    direct = artifacts.get("report_quality")
    if isinstance(direct, dict):
        return direct
    fusion = artifacts.get("fusion_result")
    if isinstance(fusion, dict) and isinstance(fusion.get("quality"), dict):
        return fusion["quality"]
    stage = artifacts.get("report_fusion")
    if isinstance(stage, dict):
        data = stage.get("data")
        if isinstance(data, dict) and isinstance(data.get("quality"), dict):
            return data["quality"]
    return None


def _by_dim(breakdown: list[Any], dimension: str) -> dict[str, Any] | None:
    for item in breakdown:
        if isinstance(item, dict) and item.get("dimension") == dimension:
            return item
    return None


def _breakdown(quality: dict[str, Any]) -> list[Any]:
    breakdown = quality.get("score_breakdown")
    return breakdown if isinstance(breakdown, list) else []


def _missing(check_id: str) -> CheckResult:
    """评分对象缺失 → fail-closed（绝不静默作 0 通过，§6 F0-12 同义）。"""
    return CheckResult(check_id, False, "缺少报告质量评分对象或 total_score 缺字段（fail-closed）")


# ---------------------------------------------------------------------------
# Q1 总分一致性（veto）：重算 Σ分项 == 生产 total_score，防漂移
# ---------------------------------------------------------------------------
def check_q1(artifacts: dict[str, Any], case: dict[str, Any]) -> CheckResult:
    quality = _quality_obj(artifacts)
    if quality is None or quality.get("total_score") is None:
        return _missing("Q1")
    total = quality["total_score"]
    recomputed = sum(int(item.get("score", 0)) for item in _breakdown(quality) if isinstance(item, dict))
    ok = recomputed == total
    return CheckResult(
        "Q1",
        ok,
        f"重算总分 {recomputed} == 生产 total_score {total}"
        if ok
        else f"重算 {recomputed} != 生产 {total}（总分漂移）",
    )


# ---------------------------------------------------------------------------
# Q2 分项加和/边界（veto）：无负分、各自 ≤ max_score、weight==max_score、Σ==total
# ---------------------------------------------------------------------------
def check_q2(artifacts: dict[str, Any], case: dict[str, Any]) -> CheckResult:
    quality = _quality_obj(artifacts)
    if quality is None or quality.get("total_score") is None:
        return _missing("Q2")
    breakdown = _breakdown(quality)
    total = quality["total_score"]
    problems: list[str] = []
    for item in breakdown:
        if not isinstance(item, dict):
            problems.append("分项非对象")
            continue
        dim = item.get("dimension")
        score = item.get("score")
        max_score = item.get("max_score")
        weight = item.get("weight")
        if not isinstance(score, int) or score < 0:
            problems.append(f"{dim} 负分或缺失")
        if isinstance(max_score, int) and isinstance(score, int) and score > max_score:
            problems.append(f"{dim} 超上限（{score}>{max_score}）")
        if weight != max_score:
            problems.append(f"{dim} weight({weight})!=max_score({max_score})")
    if sum(int(i.get("score", 0)) for i in breakdown if isinstance(i, dict)) != total:
        problems.append("分项加和 != total_score")
    return CheckResult("Q2", not problems, "；".join(problems) or "分项边界与加和合法")


# ---------------------------------------------------------------------------
# Q3 结构扣分正确：章节/小节缺 → 结构项按公式扣至 < 满分；完整 → == 满分
# ---------------------------------------------------------------------------
def check_q3(artifacts: dict[str, Any], case: dict[str, Any]) -> CheckResult:
    quality = _quality_obj(artifacts)
    if quality is None:
        return _missing("Q3")
    item = _by_dim(_breakdown(quality), DIM_STRUCTURE)
    if item is None:
        return CheckResult("Q3", False, "缺少 structure 分项")
    complete = (
        quality.get("chapter_count") == quality.get("expected_chapter_count")
        and quality.get("section_count") == quality.get("expected_section_count")
    )
    score = int(item.get("score", 0))
    max_score = int(item.get("max_score", 0))
    if complete:
        ok = score == max_score
        reason = f"结构完整，结构分 {score}=={max_score}"
    else:
        ok = score < max_score
        reason = (
            f"结构不完整（{quality.get('chapter_count')}/{quality.get('expected_chapter_count')} 章，"
            f"{quality.get('section_count')}/{quality.get('expected_section_count')} 节），"
            f"结构分 {score}<{max_score}"
        )
    return CheckResult("Q3", ok, reason)


# ---------------------------------------------------------------------------
# Q4 引用扣分正确：未知 claim/evidence/chart 命中 → 引用项扣至 < 满分
# ---------------------------------------------------------------------------
def check_q4(artifacts: dict[str, Any], case: dict[str, Any]) -> CheckResult:
    quality = _quality_obj(artifacts)
    if quality is None:
        return _missing("Q4")
    item = _by_dim(_breakdown(quality), DIM_CITATION)
    if item is None:
        return CheckResult("Q4", False, "缺少 citation_consistency 分项")
    issues_text = " ".join(str(i) for i in (quality.get("issues") or []))
    reason_text = str(item.get("reason", ""))
    unknown_markers = ("未知结论", "未知证据", "未就绪图表", "未知图表")
    has_unknown = any(marker in issues_text or marker in reason_text for marker in unknown_markers)
    score = int(item.get("score", 0))
    max_score = int(item.get("max_score", 0))
    if has_unknown:
        ok = score < max_score
        reason = f"存在未知引用，引用分 {score}<{max_score}"
    else:
        ok = score == max_score
        reason = f"无未知引用，引用分 {score}=={max_score}"
    return CheckResult("Q4", ok, reason)


# ---------------------------------------------------------------------------
# Q5 缺口必扣（veto）：used 空 / dimension 缺字段 / 风险未披露 → 对应项扣分 + reason 非空
# ---------------------------------------------------------------------------
def check_q5(artifacts: dict[str, Any], case: dict[str, Any]) -> CheckResult:
    quality = _quality_obj(artifacts)
    if quality is None:
        return _missing("Q5")
    breakdown = {
        item.get("dimension"): item
        for item in _breakdown(quality)
        if isinstance(item, dict)
    }
    problems: list[str] = []

    evidence = breakdown.get(DIM_EVIDENCE)
    if evidence and "used 为空" in str(evidence.get("reason", "")):
        if int(evidence.get("score", -1)) != 0:
            problems.append("证据 used 空但未记 0")
        if not str(evidence.get("reason", "")).strip():
            problems.append("证据缺口 reason 为空")

    dimension = breakdown.get(DIM_DIMENSION)
    if dimension and "缺少 dimension_coverage" in str(dimension.get("reason", "")):
        if int(dimension.get("score", -1)) != 0:
            problems.append("维度缺字段但未记 0")
        if not str(dimension.get("reason", "")).strip():
            problems.append("维度缺口 reason 为空")

    risk = breakdown.get(DIM_RISK)
    if risk and "未披露" in str(risk.get("reason", "")):
        if int(risk.get("score", 0)) >= int(risk.get("max_score", 0)):
            problems.append("风险未披露但未扣分")
        if not str(risk.get("reason", "")).strip():
            problems.append("风险缺口 reason 为空")

    return CheckResult("Q5", not problems, "；".join(problems) or "缺口必扣已生效")


# ---------------------------------------------------------------------------
# 分发（与 rules.run_l1_checks 同构；Q 类独立注册，不混入 L1 规则表）
# ---------------------------------------------------------------------------
_QUALITY_REGISTRY = {
    "Q1": check_q1,
    "Q2": check_q2,
    "Q3": check_q3,
    "Q4": check_q4,
    "Q5": check_q5,
}


def run_quality_checks(
    artifacts: dict[str, Any],
    case: dict[str, Any],
    *,
    checks: list[str] | None = None,
) -> list[CheckResult]:
    """按用例声明的 Q 类 checks 跑判定；``checks=None`` 时优先用 case.checks
    （仅取 Q*），再否则跑全部；``[]`` 返回空。

    未注册的 check_id → fail-closed（与 rules.run_l1_checks 语义一致）。
    """
    if checks is not None:
        selected = list(checks)
    else:
        declared = case.get("checks") if isinstance(case, dict) else None
        if isinstance(declared, (list, tuple)) and len(declared) > 0:
            selected = [cid for cid in declared if str(cid).startswith("Q")]
        else:
            selected = list(_QUALITY_REGISTRY)
    results: list[CheckResult] = []
    for check_id in selected:
        check_id = str(check_id)
        if not check_id.startswith("Q"):
            continue
        fn = _QUALITY_REGISTRY.get(check_id)
        if fn is None:
            results.append(CheckResult(check_id, False, "未注册或未实现的判定项（fail-closed）"))
            continue
        results.append(fn(artifacts, case))
    return results
