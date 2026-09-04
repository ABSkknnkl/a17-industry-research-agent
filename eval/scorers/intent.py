"""Agent 1 意图识别与拆解判分（EVALUATION_PLAN §5.0，I1–I8）。

对 ``build_intent_plan`` 产出的 ``ResearchIntentPlan`` 做金标准断言。
输入 ``case`` 为 dict（由 cases/intent_golden.yaml 反序列化，字段见 §5.0.3）。
``plan`` 可为 ``ResearchIntentPlan`` 对象或其 ``model_dump()`` 结果。
"""

from __future__ import annotations

from typing import Any


def _subs(plan: Any) -> list[Any]:
    if isinstance(plan, dict):
        return plan.get("sub_requirements", []) or []
    return getattr(plan, "sub_requirements", []) or []


def _locked(plan: Any) -> set[str]:
    if isinstance(plan, dict):
        return set(plan.get("locked_skills", []) or [])
    return set(getattr(plan, "locked_skills", []) or [])


def _skill_set(plan: Any) -> set[str]:
    skills = {s for sub in _subs(plan) for s in (sub.get("candidate_skills", []) or [] if isinstance(sub, dict) else sub.candidate_skills)}
    return skills | _locked(plan)


def _metrics(plan: Any) -> set[str]:
    out: set[str] = set()
    for sub in _subs(plan):
        items = sub.get("metrics", []) if isinstance(sub, dict) else sub.metrics
        for m in items or []:
            name = m.get("normalized_name") or m.get("original_name") if isinstance(m, dict) else (m.normalized_name or m.original_name)
            if name:
                out.add(name)
    return out


def _entities(plan: Any) -> set[str]:
    out: set[str] = set()
    for sub in _subs(plan):
        items = sub.get("entities", []) if isinstance(sub, dict) else sub.entities
        for e in items or []:
            name = e.get("name") if isinstance(e, dict) else e.name
            if name:
                out.add(name)
    return out


def _time_texts(plan: Any) -> list[str | None]:
    out: list[str | None] = []
    for sub in _subs(plan):
        tr = sub.get("time_range") if isinstance(sub, dict) else sub.time_range
        if tr:
            raw = tr.get("raw_text") if isinstance(tr, dict) else tr.raw_text
            out.append(raw)
    return out


def _parser_mode(plan: Any) -> str:
    return plan.get("parser_mode", "") if isinstance(plan, dict) else getattr(plan, "parser_mode", "")


# 指标别名归一（§5.0.1「含别名归一」）：金标准可能用别名，代码产出 display_name。
_METRIC_ALIASES = {
    "市占率": "市场份额",
    "市场占有率": "市场份额",
    "厂商份额": "市场份额",
    "营收": "营业收入",
    "销售收入": "营业收入",
}


def _metric_alias(name: str) -> str:
    return _METRIC_ALIASES.get(name, name)


def evaluate_intent_case(plan: Any, case: dict[str, Any]) -> dict[str, bool]:
    """返回 I1–I8 的逐项判定（I7/I8 由调用侧按 mode 单独处理，这里兜底）。"""
    # 兼容：用例的意图期望字段可能嵌套在 "intent" 键下（§5.0.3 schema），先展平。
    if isinstance(case, dict) and "intent" in case:
        case = {**case, **case.get("intent", {})}

    required = set(case.get("required_skills", []) or [])
    forbidden = set(case.get("forbidden_skills", []) or [])
    expect_metrics = set(case.get("metrics_in", []) or [])
    expect_entities = set(case.get("entities", []) or [])
    expect_time = tuple(case.get("expect_time_tokens", []) or [])
    min_subs = case.get("min_sub_requirements", 1) or 1
    expect_complexity = case.get("complexity", "")
    expect_clarify = bool(case.get("expect_clarification", False))
    no_redundancy = bool(case.get("expect_no_redundancy", False))
    parser_mode_in = set(case.get("parser_mode_in", []) or [])

    all_skills = _skill_set(plan)
    time_joined = " ".join(t for t in _time_texts(plan) if t)

    results: dict[str, bool] = {}
    results["I1"] = (
        bool(expect_complexity and _complexity(plan) == expect_complexity)
        and len(_subs(plan)) >= min_subs
    )
    actual_norm = {_metric_alias(m) for m in _metrics(plan)}
    results["I2"] = (
        all(_metric_alias(m) in actual_norm for m in expect_metrics) if expect_metrics else True
    )
    results["I3_required"] = all(s in all_skills for s in required)
    results["I3_forbidden"] = not (all_skills & forbidden)
    results["I4_entity"] = all(e in _entities(plan) for e in expect_entities) if expect_entities else True
    results["I4_time"] = all(t in time_joined for t in expect_time) if expect_time else True
    results["I5"] = (all_skills == required) if no_redundancy else True
    results["I6"] = (_clarify(plan) == expect_clarify)
    results["I7_mode"] = (not parser_mode_in) or (_parser_mode(plan) in parser_mode_in)
    results["I8_stable_signature_available"] = True  # I8 由连续运行测试单独判定
    return results


def _complexity(plan: Any) -> str:
    return plan.get("complexity", "") if isinstance(plan, dict) else getattr(plan, "complexity", "")


def _clarify(plan: Any) -> bool:
    return bool(plan.get("requires_clarification", False) if isinstance(plan, dict) else plan.requires_clarification)


def summarize_intent_results(results: list[dict[str, bool]]) -> dict[str, float]:
    """聚合多条 I 类用例的逐项通过率，产出 §8 I 类意图指标。"""
    if not results:
        return {}
    keys = set().union(*(r.keys() for r in results))
    return {
        key: sum(1 for r in results if r.get(key)) / len(results)
        for key in keys
    }