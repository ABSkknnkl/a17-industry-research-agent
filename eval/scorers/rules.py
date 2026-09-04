"""L1 原子通过判定项库（EVALUATION_PLAN §4）。

按 strands 分类：
- output 类：C1/C2/C3、R1/R2、G4
- trajectory 类：D1–D4、P1–P4
- tool 类：G1–G3、G5
- planning 类（V3）：T1–T8
- arbitration 类（2026-09-01 方案）：ARB1–ARB4 由 ``scorers.arbitration``
  在计划层判分；ARB1 为一票否决项（静默误判）。

每个判定项输出 ``CheckResult(passed, reason)``，对应 grades.jsonl 的一行。
语义类（T2 释义匹配、M1–M3）在 L1 只做可规则化部分，其余交 L2 judge。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

# 一票否决项（与 §4.6 末尾及 §4 各处同列）：对应 D2/P2/R2/C1 + T1/T2/T6；
# ARB1（无静默误判）为 2026-09-01 方案新增的 arbitration 组一票否决项。
VETO_CHECKS = frozenset({"D2", "P2", "R2", "C1", "T1", "T2", "T6", "ARB1"})


@dataclass
class CheckResult:
    check_id: str
    passed: bool
    reason: str

    def as_json(self) -> dict[str, Any]:
        return {"check_id": self.check_id, "passed": self.passed, "reason": self.reason}


# ---------------------------------------------------------------------------
# 通用辅助
# ---------------------------------------------------------------------------
def _skills_from_plan(tasks: list[dict[str, Any]]) -> set[str]:
    return {t.get("skill_name", "") for t in tasks if t.get("skill_name")}


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


# ---------------------------------------------------------------------------
# 4.1 数据准确性（D）
# ---------------------------------------------------------------------------
def check_d1(artifacts: dict[str, Any], case: dict[str, Any]) -> CheckResult:
    """标的主体匹配正确：evidence 实体 ∈ 用户提及实体；模糊实体须消歧/WAITING_REVIEW。"""
    evidence = artifacts.get("fetch_result", {}).get("evidence_items", []) or []
    target = set(case.get("required_entities", [])) or set(
        case.get("research_brief", {}).get("focus_companies", [])
    )
    if not target:
        return CheckResult("D1", True, "未声明目标实体，跳过主体匹配")
    entities = {
        e.get("entity_name") or e.get("metric_name") or ""
        for e in evidence
    }
    matched = any(t in "".join(entities) for t in target)
    status = artifacts.get("fetch_result", {}).get("status", "")
    return CheckResult(
        "D1",
        matched or status == "WAITING_REVIEW",
        "证据主体命中目标实体" if matched else f"主体未命中 {target} 且未转 WAITING_REVIEW",
    )


def check_d2(artifacts: dict[str, Any], case: dict[str, Any]) -> CheckResult:
    """数据与原始接口一致：raw_sha256 与快照一致，无篡改/估算。"""
    evidence = artifacts.get("fetch_result", {}).get("evidence_items", []) or []
    baseline = case.get("baseline_sha256", {})
    for item in evidence:
        raw = item.get("raw_sha256", "")
        eid = item.get("evidence_id", "")
        if eid in baseline and baseline[eid] != raw:
            return CheckResult("D2", False, f"{eid} raw_sha256 与快照不一致")
    return CheckResult("D2", True, "证据 raw_sha256 与快照一致")


def check_d3(artifacts: dict[str, Any], case: dict[str, Any]) -> CheckResult:
    """时间范围符合要求：period_end 全部落在 time_range 内；无年度/季度混用。"""
    evidence = artifacts.get("fetch_result", {}).get("evidence_items", []) or []
    lo, hi = case.get("time_range", [None, None])
    if lo is None and hi is None:
        return CheckResult("D3", True, "未声明时间范围，跳过")
    for item in evidence:
        pe = item.get("period_end") or item.get("报告期") or ""
        if pe and lo and str(pe) < str(lo):
            return CheckResult("D3", False, f"{item.get('evidence_id')} period_end 早于下限")
        if pe and hi and str(pe) > str(hi):
            return CheckResult("D3", False, f"{item.get('evidence_id')} period_end 晚于上限")
    return CheckResult("D3", True, "period_end 均落在时间范围内")


def check_d4(artifacts: dict[str, Any], case: dict[str, Any]) -> CheckResult:
    """单位完整：unit 非「未提供」比例 ≥ 阈值（回归 BUG-005）。"""
    evidence = artifacts.get("fetch_result", {}).get("evidence_items", []) or []
    if not evidence:
        return CheckResult("D4", True, "无证据，跳过")
    missing = sum(1 for e in evidence if not (e.get("unit") or e.get("单位")))
    ratio = missing / len(evidence)
    threshold = case.get("unit_completeness_threshold", 0.2)
    return CheckResult(
        "D4", ratio <= threshold, f"单位缺失比例 {ratio:.2%}（阈值 {threshold:.0%}）"
    )


# ---------------------------------------------------------------------------
# 4.2 计算正确性（C）
# ---------------------------------------------------------------------------
def check_c1(artifacts: dict[str, Any], case: dict[str, Any]) -> CheckResult:
    """公式结果误差 ≤0.01%：用基准值重算对比（杜邦/CRn/同比/周转率/产能利用率）。"""
    calculated = artifacts.get("analysis", {}).get("calculated_metrics", []) or []
    baseline = case.get("baseline_metrics", {})
    if not baseline:
        return CheckResult("C1", True, "无基准值，跳过公式核对")
    for metric in calculated:
        name = metric.get("metric_name", "")
        if name in baseline:
            expected = baseline[name]
            actual = metric.get("value", 0.0)
            if expected == 0:
                ok = abs(actual) < 1e-9
            else:
                ok = abs(actual - expected) / abs(expected) <= 0.0001
            if not ok:
                return CheckResult("C1", False, f"{name} 误差超出 0.01%（期望 {expected}，实际 {actual}）")
    return CheckResult("C1", True, "公式误差 ≤0.01%")


def check_c2(artifacts: dict[str, Any], case: dict[str, Any]) -> CheckResult:
    """单位统一：计算输入单位一致或已归一；不一致时不得产出数值。"""
    issues = artifacts.get("analysis", {}).get("calculation_issues", []) or []
    for issue in issues:
        if "单位" in (issue.get("reason", "") or ""):
            return CheckResult("C2", False, f"存在单位不一致未拦截：{issue.get('reason')}")
    return CheckResult("C2", True, "单位一致或已归一")


def check_c3(artifacts: dict[str, Any], case: dict[str, Any]) -> CheckResult:
    """异常正确拦截：缺字段/分母0/周期混用/样本不足 → WAITING_REVIEW + issues 非空。"""
    issues = artifacts.get("analysis", {}).get("calculation_issues", []) or []
    status = artifacts.get("analysis", {}).get("status", "")
    expects_intercept = case.get("expect_intercept", False)
    if expects_intercept:
        return CheckResult(
            "C3", bool(issues) or status == "WAITING_REVIEW", "异常已被正确拦截"
        )
    return CheckResult("C3", not issues, "无异常或已正确放行")


# ---------------------------------------------------------------------------
# 4.3 图表合规性（G）
# ---------------------------------------------------------------------------
def check_g1(artifacts: dict[str, Any], case: dict[str, Any]) -> CheckResult:
    """同数据集默认单图：同一 evidence_ids 集合的 chart ≤1。"""
    charts = artifacts.get("charts", []) or []
    seen: dict[tuple, int] = {}
    for chart in charts:
        key = tuple(sorted(chart.get("evidence_ids", [])))
        if key:
            seen[key] = seen.get(key, 0) + 1
    dupes = [k for k, v in seen.items() if v > 1]
    return CheckResult("G1", not dupes, f"同数据集重复图 {len(dupes)} 组" if dupes else "同数据集单图")


def check_g2(artifacts: dict[str, Any], case: dict[str, Any]) -> CheckResult:
    """用户多图豁免正确：user_requested=True 且生成数=指定数。"""
    charts = artifacts.get("charts", []) or []
    requested = case.get("requested_chart_count")
    if requested is None:
        return CheckResult("G2", True, "未显式指定多图，跳过")
    user_requested = [c for c in charts if c.get("user_requested")]
    return CheckResult("G2", len(user_requested) == requested, f"豁免图数 {len(user_requested)}/{requested}")


def check_g3(artifacts: dict[str, Any], case: dict[str, Any]) -> CheckResult:
    """产业链图 ≤1：chart_type=industry_chain 计数 ≤1。"""
    charts = artifacts.get("charts", []) or []
    count = sum(1 for c in charts if c.get("chart_type") == "industry_chain")
    return CheckResult("G3", count <= 1, f"产业链图 {count} 张")


def check_g4(artifacts: dict[str, Any], case: dict[str, Any]) -> CheckResult:
    """图表数值与计算一致：chart spec 数据点 == calculated_metrics 输出。"""
    charts = artifacts.get("charts", []) or []
    calculated = {
        m.get("metric_name"): m.get("value") for m in artifacts.get("analysis", {}).get("calculated_metrics", []) or []
    }
    for chart in charts:
        data_points = chart.get("data_points") or chart.get("points") or []
        for pt in data_points:
            name = pt.get("metric_name") or pt.get("label")
            if name in calculated and pt.get("value") != calculated[name]:
                return CheckResult("G4", False, f"图 {chart.get('title')} 数据点与计算不一致")
    return CheckResult("G4", True, "图表数值与计算一致")


def check_g5(artifacts: dict[str, Any], case: dict[str, Any]) -> CheckResult:
    """无数据不绘图：evidence 为空或全被隔离时 chart=0 且 WAITING_REVIEW。"""
    evidence = artifacts.get("fetch_result", {}).get("evidence_items", []) or []
    charts = artifacts.get("charts", []) or []
    if evidence:
        return CheckResult("G5", True, "有证据，可绘图")
    status = artifacts.get("fetch_result", {}).get("status", "")
    return CheckResult("G5", not charts and status == "WAITING_REVIEW", "无数据时未绘图")


# ---------------------------------------------------------------------------
# 4.4 报告规范性（R）
# ---------------------------------------------------------------------------
def check_r1(artifacts: dict[str, Any], case: dict[str, Any]) -> CheckResult:
    """7 章 21 节结构：章节骨架校验。"""
    chapters = artifacts.get("report", {}).get("chapters", []) or []
    if not chapters:
        return CheckResult("R1", True, "非全链路用例，跳过 7 章校验")
    ok = len(chapters) == 7 and all(len(ch.get("sections", [])) == 3 for ch in chapters)
    return CheckResult("R1", ok, f"章节 {len(chapters)} 章" if ok else "7章21节结构不完整")


_DISALLOWED_TERMS = ("投资建议", "收益承诺", "买入", "卖出", "目标价", "稳赚")


def check_r2(artifacts: dict[str, Any], case: dict[str, Any]) -> CheckResult:
    """无违规表述：禁词正则。

    只扫描系统生成的产物（报告/摘要），不扫描用户输入——注入类负向用例
    （如 E-34/E-38）的输入本身就携带禁词，那是攻击载荷而非系统违规。
    """
    text = artifacts.get("report", {}).get("executive_summary", {}).get("headline", "") or ""
    for term in _DISALLOWED_TERMS:
        if term in text:
            return CheckResult("R2", False, f"产物出现禁词：{term}")
    return CheckResult("R2", True, "产物无违规表述")


def check_r3(artifacts: dict[str, Any], case: dict[str, Any]) -> CheckResult:
    """数据有溯源：每个数值 claim 的 evidence_ids 非空且 ∈ 证据池。"""
    evidence_pool = {
        e.get("evidence_id") for e in artifacts.get("fetch_result", {}).get("evidence_items", []) or []
    }
    claims = artifacts.get("analysis", {}).get("claims", []) or []
    for claim in claims:
        ids = claim.get("evidence_ids", [])
        if not ids:
            return CheckResult("R3", False, f"claim {claim.get('claim_id')} 无证据引用")
        if evidence_pool and not set(ids) <= evidence_pool:
            return CheckResult("R3", False, f"claim {claim.get('claim_id')} 引用未知证据")
    return CheckResult("R3", True, "数值 claim 均有溯源")


# ---------------------------------------------------------------------------
# 4.5 流程正确性（P）
# ---------------------------------------------------------------------------
def check_p1(artifacts: dict[str, Any], case: dict[str, Any]) -> CheckResult:
    """数据不足停 WAITING_REVIEW：核心取数失败/证据<阈值 → 状态正确。"""
    status = artifacts.get("fetch_result", {}).get("status", "")
    evidence = artifacts.get("fetch_result", {}).get("evidence_items", []) or []
    critical_failed = any(
        g.get("blocking") for g in artifacts.get("fetch_result", {}).get("data_gaps", []) or []
    )
    if critical_failed or not evidence:
        return CheckResult("P1", status in {"WAITING_REVIEW", "WAITING_APPROVAL"}, f"数据不足状态 {status}")
    return CheckResult("P1", True, "核心数据充足")


def check_p2(artifacts: dict[str, Any], case: dict[str, Any]) -> CheckResult:
    """不伪造不补数：产物中实体/数值/证据ID 全部可在 transcript 溯源。"""
    evidence_pool = {
        e.get("evidence_id") for e in artifacts.get("fetch_result", {}).get("evidence_items", []) or []
    }
    for claim in artifacts.get("analysis", {}).get("claims", []) or []:
        for eid in claim.get("evidence_ids", []):
            if evidence_pool and eid not in evidence_pool:
                return CheckResult("P2", False, f"伪造/无来源证据 {eid}")
    return CheckResult("P2", True, "全部可溯源")


def check_p3(artifacts: dict[str, Any], case: dict[str, Any]) -> CheckResult:
    """异常提示清晰：message 含风险编码+处置方式+受影响ID。"""
    collabs = artifacts.get("fetch_result", {}).get("collaboration_requests", []) or []
    if not collabs:
        return CheckResult("P3", True, "无异常拦截，跳过")
    question = collabs[0].get("question", "")
    has_code = any(code in question for code in ("REQUESTED-DATA", "DATA-QUALITY", "INTENT-CLARIFY"))
    has_action = any(a in question for a in ("重新提交", "调整", "确认", "修改"))
    return CheckResult("P3", has_code or has_action, "拦截提示是否清晰")


def check_p4(artifacts: dict[str, Any], case: dict[str, Any]) -> CheckResult:
    """前视偏差合理：available_at 略晚于 research_as_of（≤容忍窗口）不得硬阻断。"""
    issues = artifacts.get("analysis", {}).get("data_quality_issues", []) or []
    for issue in issues:
        if "前视" in (issue.get("description", "") or ""):
            return CheckResult("P4", False, "前视偏差被硬阻断（应容忍）")
    return CheckResult("P4", True, "前视偏差处理合理")


# ---------------------------------------------------------------------------
# 4.6 工具规划与调用合规（T）
# ---------------------------------------------------------------------------
def check_t1(artifacts: dict[str, Any], case: dict[str, Any]) -> CheckResult:
    """应调尽调：required_skills ⊆ plan.skills。"""
    tasks = artifacts.get("retrieval_plan", {}).get("tasks", []) or []
    actual = _skills_from_plan(tasks)
    required = set(case.get("required_skills", []))
    if not required:
        return CheckResult("T1", True, "未声明 required_skills")
    missing = required - actual
    return CheckResult("T1", not missing, f"漏调 {sorted(missing)}" if missing else "应调尽调")


def check_t2(artifacts: dict[str, Any], case: dict[str, Any]) -> CheckResult:
    """无错调：plan.skills ∩ forbidden_skills = ∅。"""
    tasks = artifacts.get("retrieval_plan", {}).get("tasks", []) or []
    actual = _skills_from_plan(tasks)
    forbidden = set(case.get("forbidden_skills", []))
    overlap = actual & forbidden
    return CheckResult("T2", not overlap, f"错调 {sorted(overlap)}" if overlap else "无错调")


def check_t3(artifacts: dict[str, Any], case: dict[str, Any]) -> CheckResult:
    """无重复无效调用：无重复 (skill, canonical_query)；任务数 ≤30。"""
    tasks = artifacts.get("retrieval_plan", {}).get("tasks", []) or []
    if len(tasks) > 30:
        return CheckResult("T3", False, f"任务数 {len(tasks)} 超 30 上限")
    seen: set[tuple[str, str]] = set()
    for task in tasks:
        key = (task.get("skill_name", ""), "".join((task.get("query") or "").split()))
        if key in seen:
            return CheckResult("T3", False, f"重复任务 {key[0]}::{key[1][:30]}")
        seen.add(key)
    return CheckResult("T3", True, "无重复、任务数合规")


def check_t4(artifacts: dict[str, Any], case: dict[str, Any]) -> CheckResult:
    """参数完整正确：time_range 非空、max_pages∈[1,5]、priority∈[0,100]。"""
    tasks = artifacts.get("retrieval_plan", {}).get("tasks", []) or []
    for task in tasks:
        mp = task.get("max_pages", 1)
        pr = task.get("priority", 0)
        tr = task.get("time_range", "")
        if not (1 <= mp <= 5):
            return CheckResult("T4", False, f"{task.get('skill_name')} max_pages 越界 {mp}")
        if not (0 <= pr <= 100):
            return CheckResult("T4", False, f"{task.get('skill_name')} priority 越界 {pr}")
        if not tr:
            return CheckResult("T4", False, f"{task.get('skill_name')} time_range 为空")
    return CheckResult("T4", True, "参数完整正确")


def check_t5(artifacts: dict[str, Any], case: dict[str, Any]) -> CheckResult:
    """工具能力复用：同义指标归一而非新开任务（规则化：无 fallback 兜底图与需求无关）。"""
    charts = artifacts.get("charts", []) or []
    for chart in charts:
        if chart.get("is_fallback") and not chart.get("evidence_ids"):
            return CheckResult("T5", False, "兜底图无关联证据（应与需求有关）")
    return CheckResult("T5", True, "能力复用正常")


def check_t6(artifacts: dict[str, Any], case: dict[str, Any]) -> CheckResult:
    """失败降级正确：P0 失败=阻断 WAITING_REVIEW；P1 失败=记录 issue 继续。"""
    gaps = artifacts.get("fetch_result", {}).get("data_gaps", []) or []
    status = artifacts.get("fetch_result", {}).get("status", "")
    for gap in gaps:
        if gap.get("blocking") and status != "WAITING_REVIEW":
            return CheckResult("T6", False, "P0 失败未阻断")
    return CheckResult("T6", True, "失败降级正确")


def check_t7(artifacts: dict[str, Any], case: dict[str, Any]) -> CheckResult:
    """调用路径最优：任务数 ≤ expected_task_range 上界。"""
    tasks = artifacts.get("retrieval_plan", {}).get("tasks", []) or []
    upper = case.get("expected_task_range", [0, 999])[1] if case.get("expected_task_range") else 999
    return CheckResult("T7", len(tasks) <= upper, f"任务数 {len(tasks)} ≤ 上界 {upper}")


def check_t8(artifacts: dict[str, Any], case: dict[str, Any]) -> CheckResult:
    """新 skill 路由正确：FUTURES 与 MACRO 互斥（商品词/宏观词不混写 query）。"""
    tasks = artifacts.get("retrieval_plan", {}).get("tasks", []) or []
    for task in tasks:
        q = task.get("query", "")
        if "期货" in q and ("社融" in q or "pmi" in q or "gdp" in q):
            return CheckResult("T8", False, "FUTURES 与 MACRO 词混写 query")
    return CheckResult("T8", True, "商品词/宏观词未混写")


# ---------------------------------------------------------------------------
# 分发
# ---------------------------------------------------------------------------
_CHECK_REGISTRY: dict[str, Callable[[dict, dict], CheckResult]] = {
    "D1": check_d1, "D2": check_d2, "D3": check_d3, "D4": check_d4,
    "C1": check_c1, "C2": check_c2, "C3": check_c3,
    "G1": check_g1, "G2": check_g2, "G3": check_g3, "G4": check_g4, "G5": check_g5,
    "R1": check_r1, "R2": check_r2, "R3": check_r3,
    "P1": check_p1, "P2": check_p2, "P3": check_p3, "P4": check_p4,
    "T1": check_t1, "T2": check_t2, "T3": check_t3, "T4": check_t4,
    "T5": check_t5, "T6": check_t6, "T7": check_t7, "T8": check_t8,
}


def registered_check_ids() -> frozenset[str]:
    """Return every check id owned by the complete evaluator stack.

    I1-I8 are evaluated by ``scorers.intent``, M1-M3 by the semantic
    methodology scorer, and ARB1-ARB4 by ``scorers.arbitration``
    (2026-09-01 方案 §4.3).  Keeping the global declaration here lets the
    case schema fail closed before a run starts without pretending that
    these checks are handled by the L1 rule registry.
    """
    return frozenset(_CHECK_REGISTRY) | frozenset(
        {*(f"I{i}" for i in range(1, 9)), "M1", "M2", "M3", *(f"ARB{i}" for i in range(1, 5))}
    )


def run_l1_checks(
    artifacts: dict[str, Any],
    case: dict[str, Any],
    *,
    checks: list[str] | None = None,
) -> list[CheckResult]:
    """按用例声明的 checks 跑 L1 判定，返回结果列表。

    ``checks=None`` 表示未声明（跑全部）；``checks=[]`` 表示该用例没有 L1
    规则检查项（返回空），两者语义不同，不能互相回退。
    """
    selected = list(_CHECK_REGISTRY) if checks is None else checks
    results: list[CheckResult] = []
    for check_id in selected:
        fn = _CHECK_REGISTRY.get(check_id)
        if fn is None:
            results.append(CheckResult(check_id, False, "未注册或未实现的判定项（fail-closed）"))
            continue
        results.append(fn(artifacts, case))
    return results
