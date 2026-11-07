"""Agent 1 层间仲裁判分（2026-09-01 方案 §4.3，ARB1-ARB4）。

与 ``scorers.intent`` 并列的判分模块：对 ``build_intent_plan`` 产出的
``ResearchIntentPlan`` 做仲裁金标准断言。输入 ``case`` 为 dict（由
``cases/intent_routing_61.yaml`` 的 ``arbitration`` 组反序列化）。

- ARB1 无静默误判（一票否决）：金标准禁锁指标不得被确定性层以
  conf=1.0 锁定并路由，除非计划整体走澄清/标记低置信；
- ARB2 advisory 不阻塞：有技能可接的澄清不得以 hard block 形态出现；
- ARB3 派生词不锁定：输入含否定表派生词时，禁锁指标不得以确定性
  锁定形态出现在可执行子需求中；
- ARB4 否决留痕：显式否决必须落 ``llm_veto`` 警告（遥测同源），
  且否决后不再补回 locked。

判分只读计划结构；遥测文件核对由 replay 层（transport 快照）负责。
"""

from __future__ import annotations

from typing import Any

_VETO_WARNING_PREFIX = "llm_veto:"


def _subs(plan: Any) -> list[Any]:
    if isinstance(plan, dict):
        return plan.get("sub_requirements", []) or []
    return getattr(plan, "sub_requirements", []) or []


def _attr(sub: Any, name: str, default: Any = None) -> Any:
    if isinstance(sub, dict):
        return sub.get(name, default)
    return getattr(sub, name, default)


def _metric_names(sub: Any) -> set[str]:
    names: set[str] = set()
    for metric in _attr(sub, "metrics", []) or []:
        name = (
            metric.get("normalized_name") or metric.get("original_name")
            if isinstance(metric, dict)
            else (metric.normalized_name or metric.original_name)
        )
        if name:
            names.add(name)
    return names


def _routed_subs(plan: Any) -> list[Any]:
    return [sub for sub in _subs(plan) if _attr(sub, "candidate_skills")]


def _clarified(plan: Any) -> bool:
    if isinstance(plan, dict):
        return bool(plan.get("requires_clarification"))
    return bool(getattr(plan, "requires_clarification", False))


def _warnings(plan: Any) -> list[str]:
    if isinstance(plan, dict):
        return [str(item) for item in plan.get("warnings", []) or []]
    return [str(item) for item in getattr(plan, "warnings", []) or []]


def _analysis_notes(plan: Any) -> list[str]:
    if isinstance(plan, dict):
        return [str(item) for item in plan.get("analysis_notes", []) or []]
    return [str(item) for item in getattr(plan, "analysis_notes", []) or []]


def _deterministic_locked_hits(plan: Any, metric_name: str) -> list[Any]:
    """确定性来源、conf=1.0、带技能的子需求中出现该指标 = 锁定命中。"""

    hits: list[Any] = []
    for sub in _routed_subs(plan):
        if _attr(sub, "source") != "deterministic":
            continue
        if float(_attr(sub, "confidence", 0.0) or 0.0) < 1.0:
            continue
        if metric_name in _metric_names(sub):
            hits.append(sub)
    return hits


def check_arb1_no_silent_misroute(plan: Any, case: dict[str, Any]) -> bool:
    """静默误判一票否决：禁锁指标被确定性锁定路由，且计划既未澄清也未
    标记低置信 → fail。"""

    intent = case.get("intent", {}) or {}
    forbidden_metrics = intent.get("not_locked_metrics", []) or []
    if not forbidden_metrics:
        return True
    if _clarified(plan):
        return True
    for metric_name in forbidden_metrics:
        if _deterministic_locked_hits(plan, metric_name):
            return False
    return True


def check_arb2_advisory_not_blocking(plan: Any, case: dict[str, Any]) -> bool:
    """有技能可接却整体 hard 阻塞 = 过度阻塞（口径见方案 §3）。"""

    if not _clarified(plan):
        return True
    return not _routed_subs(plan)


def check_arb3_derivative_not_locked(plan: Any, case: dict[str, Any]) -> bool:
    """派生词输入：禁锁指标不得以确定性锁定形态进入可执行子需求
    （与 ARB1 的区别：这里不豁免澄清——否定表命中必须降级或否决）。"""

    intent = case.get("intent", {}) or {}
    forbidden_metrics = intent.get("not_locked_metrics", []) or []
    for metric_name in forbidden_metrics:
        if _deterministic_locked_hits(plan, metric_name):
            return False
    return True


def check_arb4_veto_recorded(plan: Any, case: dict[str, Any]) -> bool:
    """期望否决的用例：必须出现 llm_veto 留痕，且否决后无 locked 复活。"""

    intent = case.get("intent", {}) or {}
    if not (
        intent.get("expect_analysis_only_or_clarification")
        or intent.get("expect_veto")
    ):
        return True
    vetoed = any(warning.startswith(_VETO_WARNING_PREFIX) for warning in _warnings(plan))
    if vetoed:
        forbidden_metrics = intent.get("not_locked_metrics", []) or []
        for metric_name in forbidden_metrics:
            if _deterministic_locked_hits(plan, metric_name):
                return False
        return True
    # 未否决时：走澄清门也算对（二选一都算对，见方案 §4.3 R-E02）。
    return _clarified(plan) or bool(_analysis_notes(plan))


def evaluate_arbitration_case(plan: Any, case: dict[str, Any]) -> dict[str, bool]:
    """返回 ARB1-ARB4 判定结果；用例未声明 checks 时全跑。"""

    declared = case.get("checks")
    results = {
        "ARB1": check_arb1_no_silent_misroute(plan, case),
        "ARB2": check_arb2_advisory_not_blocking(plan, case),
        "ARB3": check_arb3_derivative_not_locked(plan, case),
        "ARB4": check_arb4_veto_recorded(plan, case),
    }
    if declared is None:
        return results
    declared_ids = {check_id for check_id in declared if str(check_id).startswith("ARB")}
    return {check_id: passed for check_id, passed in results.items() if check_id in declared_ids}


def summarize_arbitration_results(results: list[dict[str, bool]]) -> dict[str, float]:
    """按判定项汇总通过率（门禁矩阵 §4.5 使用）。"""

    if not results:
        return {}
    summary: dict[str, float] = {}
    for check_id in ("ARB1", "ARB2", "ARB3", "ARB4"):
        values = [result[check_id] for result in results if check_id in result]
        if values:
            summary[check_id] = round(sum(1 for value in values if value) / len(values), 4)
    return summary
