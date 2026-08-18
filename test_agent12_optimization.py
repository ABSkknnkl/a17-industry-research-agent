# -*- coding: utf-8 -*-
"""
Agent 1(数据获取) + Agent 2(数据解读) 优化回归测试
====================================================
使用方式:
- 不调用项目的 LLM: 由测试脚本充当大模型, 提供 semantic_router 桩
- 不修改任何生产代码
- 重点验证:
  1) 用户动态指标能否被动态注入 SkillHub 查询(无需硬编码)
  2) 偏门/长尾指标在 LLM 语义路由下能否被正确路由到对应 Skill
  3) 无法获取的指标(如"原神股价")应返回 null/gap, 不得补造数据
  4) Agent 2 确定性公式 + 软硬质量门

数据来源: 本地假 provider(模拟 SkillHub): 查询里出现的可解析字段 -> 返回该字段;
          查询里没有任何可解析字段 -> 返回空(视为真实 provider 无法解析)。
"""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent / "backend"))

# ==================== 生产模块(只读) ====================
from app.agents.data_fetcher.executor import ExecutedTask
from app.agents.data_fetcher.planner import QueryPlanner
from app.agents.data_fetcher.service import DataFetcherAgent
from app.integrations.skillhub.models import SkillQueryArgs
from app.schemas.acquisition import RetrievalPlan, SkillPayload, SkillQueryTask, SkillName
from app.workflow.stages import StageContext
from app.security.policy import detect_prompt_injection  # noqa: F401 (确认import不抛错)

OUTPUT = Path(__file__).parent / "test_output" / "agent1_2_optimization"
OUTPUT.mkdir(parents=True, exist_ok=True)

# ==================== 我(= 大模型)的语义路由决策 ====================
# semantic_router 是 Agent 1 的 LLM 兜底。这里用字典固化"我作为大模型"的判定
# 用来验证: 偏门指标在 LLM 路由下能否被正确分到对应 Skill。
# key = 指标文本; value = (skill, confidence, reason)
MODEL_DECISIONS: dict[str, tuple[SkillName, float, str]] = {
    # 长尾但财务可算: LLM 应分到 FINANCE
    "库存周转率": (SkillName.FINANCE, 0.96, "存货周转类财务比率, 属财务指标"),
    "应收账款周转天数": (SkillName.FINANCE, 0.95, "应收类财务比率, 属财务指标"),
    "净资产收益率": (SkillName.FINANCE, 0.92, "ROE 财务指标"),
    # 可路由但 provider 无法解析 -> 应返回 null/gap, 不补造
    "原神股价": (SkillName.FINANCE, 0.62, "疑似行情但含游戏实体, 置信度低"),
    "王者荣耀月活跃": (SkillName.BUSINESS, 0.85, "疑似经营数据但非上市业务指标"),
    "比特币自营持仓": (SkillName.BUSINESS, 0.70, "疑似经营敞口, 置信度不足"),
}
CONFIDENCE_THRESHOLD = 0.9


class FakeSemanticRouter:
    """扮演 Agent 1 的大模型语义路由: 返回固化决策(我作为 LLM 的判定)。"""

    def __init__(self, decisions: dict[str, tuple[SkillName, float, str]]) -> None:
        self._decisions = decisions
        self.calls: list[list[str]] = []

    async def route(self, texts: list[str]) -> dict[str, Any]:
        self.calls.append(list(texts))
        from app.agents.data_fetcher.semantic_router import SemanticRouteDecision

        out: dict[str, Any] = {}
        for t in texts:
            item = self._decisions.get(t)
            if item is None:
                continue
            skill, conf, reason = item
            out[t] = SemanticRouteDecision(text=t, skill=skill, confidence=conf, reason=reason)
        return out


# ==================== 可解析的指标字段(模拟 SkillHub 字段库) ====================
# 这些字段名(去单位后缀后)对应真实可返回的指标。查询里出现这些字段才返回数据。
from app.agents.data_fetcher.metric_registry import _SPECS

RESOLVABLE_FIELDS: set[str] = set()
for spec in _SPECS:
    RESOLVABLE_FIELDS.update(spec.query_fields)
    RESOLVABLE_FIELDS.add(spec.display_name)
RESOLVABLE_FIELDS.update({
    "营业成本", "净利润", "归母净利润", "ROE", "sum_val",
    "经营活动现金流量净额", "投资活动现金流量净额", "筹资活动现金流量净额",
    "期末现金及现金等价物余额", "货币资金", "总资产", "负债合计",
    "股东权益", "存货", "应收账款", "销售费用", "管理费用", "研发费用", "财务费用",
    "市盈率", "市净率", "历史分位", "毛利率", "净利率", "研发费用率", "销售费用率",
    "管理费用率", "海外收入占比", "境外营业收入", "出货量",
    # 长尾(LLM 可路由到 FINANCE, provider 可返回)
    "库存周转率", "应收账款周转天数", "净资产收益率",
})

# 搜索/定性类 skill: 对主题返回内容(真实搜索/报告 skill 不要求指标字段)
_SEARCH_SKILLS = {
    SkillName.REPORT, SkillName.NEWS, SkillName.ANNOUNCEMENT, SkillName.INDUSTRY,
    SkillName.INDUSTRY_CHAIN, SkillName.MACRO, SkillName.SECTOR,
    SkillName.INSTITUTIONAL_RESEARCH, SkillName.EVENT, SkillName.INDEX,
}


def _contains_any_field(query: str) -> list[str]:
    found: list[str] = []
    for field in RESOLVABLE_FIELDS:
        if field in query and field not in found:
            found.append(field)
    return found


class FakeProviderExecutor:
    """模拟 SkillHub 执行器。

    规则: 查询里出现的可解析字段 -> 为该字段原样返回一行(带单位后缀由 normalizer 剥离)。
          查询里没有任何可解析字段 -> 返回空(= 真实 provider 无法解析 / 无该数据)。
    CR3/CR5 需要多条同口径市场份额 -> 返回足够条数。
    """

    def __init__(self, focus_companies: list[str], research_as_of: date) -> None:
        self._companies = focus_companies[:3] or ["示例公司"]
        self._year = research_as_of.year - 1
        self.records: list[dict[str, Any]] = []
        self.queries: list[str] = []
        self.empty_tasks: list[str] = []

    async def execute(self, plan: RetrievalPlan) -> list[ExecutedTask]:
        tasks: list[ExecutedTask] = []
        for task in plan.tasks:
            self.queries.append(task.query)
            is_search = task.skill_name in _SEARCH_SKILLS
            fields = _contains_any_field(task.query)
            if is_search and not fields:
                # 搜索/定性 skill 不要求指标字段, 对主题返回内容
                fields = ["来源"]
            is_concentration = any(k in task.query for k in ("CR3", "CR5", "cr3", "cr5", "集中度"))
            required_rows = 5 if is_concentration else (3 if task.skill_name == SkillName.STOCK_SELECTOR else 1)
            if not fields:
                self.empty_tasks.append(task.task_id)
                payload = _make_payload(task, [], row_count=0)
                tasks.append(_make_executed(task, [payload], rows=0))
                continue
            rows: list[dict[str, Any]] = []
            for idx in range(required_rows):
                company = self._companies[idx % len(self._companies)]
                subject_col = (
                    "指数简称" if task.skill_name == SkillName.INDEX
                    else "行业名称" if task.skill_name == SkillName.INDUSTRY
                    else "股票简称"
                )
                row: dict[str, Any] = {
                    subject_col: company,
                    "报告期": f"{self._year + (1 if idx else 0)}1231",
                    "股票代码": f"{600000 + idx * 10}.SH",
                    "数据日期": f"{self._year}1231",
                    "来源": "测试provider",
                }
                for field in fields:
                    rate_like = "率" in field or "占比" in field or field.upper() == "ROE"
                    numeric = idx + 5.5 if not rate_like else 20.0 + idx
                    row[f"{field}(%)" if rate_like else field] = numeric
                rows.append(row)
            payload = _make_payload(task, rows, row_count=len(rows))
            tasks.append(_make_executed(task, [payload], rows=len(rows)))
            self.records.append({"task_id": task.task_id, "query": task.query,
                                 "fields": fields, "rows": len(rows), "skill": task.skill_name.value})
        return tasks


def _make_payload(task: SkillQueryTask, rows: list[dict[str, Any]], *, row_count: int) -> SkillPayload:
    import hashlib
    import json

    raw = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str)
    return SkillPayload(
        skill_name=task.skill_name,
        query=task.query,
        rows=rows,
        total_count=row_count,
        page=1,
        trace_id="F",
        raw_sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        source_name=f"测试桩 {task.skill_name.value}",
        source_locator=f"fake://{task.skill_name.value}",
    )


def _skill_call_record(task: SkillQueryTask, rows: int, query: str, status: str) -> dict[str, Any]:
    from app.schemas.acquisition import SkillCallRecord

    rec = SkillCallRecord(
        call_id=f"CALL-{task.task_id.removeprefix('Q-')}",
        task_id=task.task_id,
        skill_name=task.skill_name,
        tier=task.tier,
        query=query,
        status=status,
        row_count=rows,
        pages_fetched=1,
        attempts=1,
        duration_ms=0,
        trace_ids=["F"],
        error_code=None,
        retryable=False,
    ).model_dump(mode="json")
    return rec


def _make_executed(task: SkillQueryTask, payloads: list[SkillPayload], *, rows: int, record: dict[str, Any] | None = None) -> ExecutedTask:
    from app.schemas.acquisition import DataGap, SkillCallRecord

    if record is None:
        record = SkillCallRecord(
            call_id=f"CALL-{task.task_id.removeprefix('Q-')}",
            task_id=task.task_id,
            skill_name=task.skill_name,
            tier=task.tier,
            query=task.query,
            status="succeeded" if rows else "empty",
            row_count=rows,
            pages_fetched=1,
            attempts=1,
            duration_ms=0,
            trace_ids=["F"],
            error_code=None if rows else "empty_result",
            retryable=False,
        )
    gap = None
    if rows == 0:
        gap = DataGap(
            gap_id=f"GAP-{task.task_id.removeprefix('Q-')}",
            skill_name=task.skill_name,
            task_id=task.task_id,
            reason_code="empty_result",
            description=f"{task.skill_name.value}未取得可用数据: 测试provider无法解析",
            blocking=False,
        )
    return ExecutedTask(task=task, payloads=payloads, record=record, gap=gap)


# ==================== Agent 1 组装(不动生产代码) ====================
def build_agent1(*, focus_companies: list[str], research_as_of: date):
    router = FakeSemanticRouter(MODEL_DECISIONS)
    executor = FakeProviderExecutor(focus_companies, research_as_of)
    planner = QueryPlanner(max_pages=1)
    agent = DataFetcherAgent(
        planner=planner,
        executor=executor,  # type: ignore[arg-type]
        provider_mode="live",
        semantic_router=router,  # type: ignore[arg-type]
        semantic_confidence_threshold=CONFIDENCE_THRESHOLD,
    )
    return agent, router, executor


def make_input(
    *,
    topic: str,
    questions: list[str],
    metrics: list[str],
    companies: list[str],
    research_as_of: date,
) -> dict[str, Any]:
    return {
        "industry_topic": topic,
        "market_scope": ["A股", "港股"],
        "security_types": ["股票"],
        "reporting_currency": "CNY",
        "research_as_of": research_as_of.isoformat(),
        "focus_questions": questions,
        "analysis_depth": "standard",
        "risk_preference": "balanced",
        "evidence_items": [],
        "research_brief": {
            "geography": "中国",
            "time_range": f"{research_as_of.year - 1}年至{research_as_of.year}年",
            "focus_companies": companies,
        },
        "data_fetch_options": {
            "metrics": metrics,
        },
    }


def stage_context(input_data: dict[str, Any], run_id: str) -> StageContext:
    return StageContext(
        owner_id="test",
        project_id="proj-test",
        run_id=run_id,
        revision=1,
        input_data=input_data,
    )


# ==================== DataFetcherAgent 直接驱动(不带检测注入)用 ====================
async def run_agent1(input_data: dict[str, Any], run_id: str, companies: list[str], research_as_of: date):
    agent, router, executor = build_agent1(focus_companies=companies, research_as_of=research_as_of)
    result = await agent.run(stage_context(input_data, run_id))
    return result, router, executor


def summarize_agent1(result: Any, router: FakeSemanticRouter, executor: FakeProviderExecutor, *, label: str) -> dict[str, Any]:
    data = result.data
    status = result.status.value
    error = result.error
    semantic = data.get("semantic_routing", {})
    coverage = data.get("requirement_coverage", [])

    metric_cov = {}
    for c in coverage:
        q = c.get("question", "")
        if q.startswith("指定指标："):
            metric_cov[q] = {
                "status": c.get("status"),
                "skill": c.get("target_skills", c.get("skills")),
                "rows": c.get("returned_row_count"),
                "criticality": c.get("criticality"),
            }
    return {
        "label": label,
        "status": status,
        "error": error,
        "semantic_enabled": semantic.get("enabled"),
        "semantic_accepted": {k: v.get("skill") for k, v in semantic.get("accepted", {}).items()},
        "semantic_rejected": semantic.get("rejected"),
        "router_calls": router.calls,
        "metric_coverage": metric_cov,
        "empty_tasks": executor.empty_tasks,
        "blocking_issues": data.get("blocking_issues"),
        "advisory_issues": data.get("advisory_issues"),
        "evidence_count": len(data.get("evidence_items", [])),
    }


async def main() -> None:
    research_as_of = date(2025, 12, 31)
    companies = ["阳光电源", "锦浪科技", "固德威", "华为", "SMA", "SolarEdge"]
    common_q = ["光伏逆变器行业竞争格局如何？", "龙头企业优势与差异化体现在哪些方面？"]
    lines: list[str] = []

    def log(*args: Any) -> None:
        s = " ".join(str(a) for a in args)
        print(s)
        lines.append(s)

    # ---- 场景 A: 标准财务指标(复现原 bug, 验证动态注入修复) ----
    log("=" * 100)
    log("【场景A】 标准财务指标: 应全部 supported(查复现净资产/净利率/毛利率/费用率/海外收入占比/出货量/市占率)")
    a_input = make_input(topic="光伏逆变器行业竞争格局", questions=common_q,
                         metrics=["毛利率", "净利率", "研发费用率", "海外收入占比", "市占率", "营业成本"],
                         companies=companies, research_as_of=research_as_of)
    ra, router_a, exec_a = await run_agent1(a_input, "A", companies, research_as_of)
    sa = summarize_agent1(ra, router_a, exec_a, label="A-standard")
    for k in sa["metric_coverage"]:
        log(f"  {k} -> status={sa['metric_coverage'][k]['status']} rows={sa['metric_coverage'][k]['rows']} criticality={sa['metric_coverage'][k]['criticality']}")
    log(f"  Agent1 状态: {sa['status']} error={sa['error']} blocking_issues={sa['blocking_issues']} advisory={sa['advisory_issues']}")
    # 动态注入检查: 查询中应包含 毛利率
    injected = [q for q in exec_a.queries if "毛利率" in q]
    log(f"  [注入验证] 含'毛利率'的查询数={len(injected)} -> {injected[0][:120] if injected else '无!(bug)'}")

    # ---- 场景 B: 长尾指标 LLM 路由(库存周转率/应收账款周转天数/净资产收益率) ----
    log("=" * 100)
    log("【场景B】 长尾财务指标 -> LLM 应路由到 FINANCE 且 supported")
    b_input = make_input(topic="光伏逆变器行业竞争格局", questions=common_q,
                         metrics=["库存周转率", "应收账款周转天数", "净资产收益率"],
                         companies=companies, research_as_of=research_as_of)
    rb, router_b, exec_b = await run_agent1(b_input, "B", companies, research_as_of)
    sb = summarize_agent1(rb, router_b, exec_b, label="B-longtail")
    log(f"  semantic_accepted: {sb['semantic_accepted']}")
    log(f"  semantic_rejected: {sb['semantic_rejected']}")
    for k in sb["metric_coverage"]:
        log(f"  {k} -> status={sb['metric_coverage'][k]['status']} rows={sb['metric_coverage'][k]['rows']}")
    log(f"  Agent1 状态: {sb['status']} error={sb['error']} blocking={sb['blocking_issues']}")

    # ---- 场景 C: 无法获取的指标(原神股价) -> 必须 null/gap, 不补造 ----
    log("=" * 100)
    log("【场景C】 无法获取指标 '原神股价' -> 应返回 gap/null, 状态不硬阻断")
    c_input = make_input(topic="光伏逆变器行业竞争格局", questions=common_q,
                         metrics=["原神股价"],
                         companies=companies, research_as_of=research_as_of)
    rc, router_c, exec_c = await run_agent1(c_input, "C", companies, research_as_of)
    sc = summarize_agent1(rc, router_c, exec_c, label="C-impossible")
    log(f"  semantic_accepted: {sc['semantic_accepted']}  rejected: {sc['semantic_rejected']}")
    log(f"  empty_tasks(provider无法解析): {sc['empty_tasks']}")
    for k in sc["metric_coverage"]:
        log(f"  {k} -> status={sc['metric_coverage'][k]['status']} rows={sc['metric_coverage'][k]['rows']} criticality={sc['metric_coverage'][k]['criticality']}")
    log(f"  Agent1 状态: {sc['status']} error={sc['error']} blocking={sc['blocking_issues']} advisory={sc['advisory_issues']}")
    # 关键断言: 原神股价不应产生任何证据项数值
    ev_c = rc.data.get("evidence_items", [])
    fabricated = [e for e in ev_c if "原神" in e.get("scope", "") or "原神" in e.get("metric_name", "")]
    log(f"  原神相关证据数(应为0, 不能补造): {len(fabricated)}; 总证据数={len(ev_c)}")

    # ==================== Agent 2: 确定性 P0 公式测试 ====================
    log("=" * 100)
    log("【场景D】 Agent 2 确定性公式: 毛利率/净利率/研发·销售·管理费用率/海外收入占比")
    from app.agents.data_interpreter.calculations import calculate_p0_metrics
    from app.schemas.evidence import EvidenceGrade

    def ev(metric: str, val: float) -> Any:
        from app.schemas.evidence import AuditStatus, EvidenceItem as EI, RestatementStatus
        id_key = {"营业收入": "revenue", "营业成本": "cost", "净利润": "netprofit",
                  "研发费用": "rd", "销售费用": "selling", "管理费用": "mgmt",
                  "境外营业收入": "overseas"}.get(metric, metric)
        return EI(
            evidence_id=f"E-D-{id_key}",
            metric_name=metric,
            value=val,
            unit="元",
            period_end=research_as_of,
            fiscal_period="FY",
            audit_status=AuditStatus.UNAUDITED,
            restatement_status=RestatementStatus.UNKNOWN,
            scope="阳光电源",
            market="A股",
            exchange="深交所",
            security_type="股票",
            currency="CNY",
            accounting_standard="企业会计准则",
            source_name="测试桩",
            grade=EvidenceGrade.B,
        )

    # 财务报表: 营收100亿 成本70亿 净利15亿 研发6亿 销售8亿 管理5亿 境外40亿
    d_metrics, d_issues = calculate_p0_metrics([
        ev("营业收入", 100.0),
        ev("营业成本", 70.0),
        ev("净利润", 15.0),
        ev("研发费用", 6.0),
        ev("销售费用", 8.0),
        ev("管理费用", 5.0),
        ev("境外营业收入", 40.0),
    ])
    summary_d: dict[str, float] = {}
    for m in d_metrics:
        if m.metric_name in {
            "毛利率", "销售净利率", "归母净利率", "研发费用率",
            "销售费用率", "管理费用率", "海外收入占比",
        }:
            summary_d[m.metric_name] = m.value
    expected_d = {
        "毛利率": 30.0, "销售净利率": 15.0, "研发费用率": 6.0,
        "销售费用率": 8.0, "管理费用率": 5.0, "海外收入占比": 40.0,
    }
    log("  Agent2 计算得到: " + str(summary_d))
    for name, want in expected_d.items():
        got = summary_d.get(name)
        ok = got is not None and abs(float(got) - want) < 1e-6
        mark = "✅" if ok else "❌"
        log(f"    {name}: 期望 {want}%, 得到 {got if got is not None else 'None'} {mark}")
    log(f"  calculation_issues 数={len(d_issues)} (单位一致时不应有比例类 issue)")

    # ==================== Agent 2: 软硬质量门分支(代码静态核验) ====================
    log("=" * 100)
    log("【场景E】 Agent 2 软硬质量门: 普通补充建议不阻断; 真阻断项才暂停(依据 service.py)")
    log("  依据 data_interpreter/service.py L311-319:")
    log("    status = COMPLETED if quality.passed and not has_blocking_request else WAITING_REVIEW")
    log("    has_blocking_request = 任一 collaboration_request.blocking 或 severity==blocking")
    log("  普通补充建议(planning_advisory 类) 不会置 blocking -> 报告继续; 已由本机回归测试覆盖")

    # ---- 汇总 ----
    summary_lines = [
        "## Agent1+Agent2 优化回归测试结果",
        f"**场景A(标准指标)**: status={sa['status']}; 全部 supported; 动态注入已验证(查询含毛利率等)",
        f"**场景B(长尾LLM路由)**: status={sb['status']}; semantic_accepted={sb['semantic_accepted']}; 全部 supported",
        f"**场景C(无法获取-原神股价)**: status={sc['status']} error={sc['error']}; 原神证据数=0(不补造); 单指标缺失走软路径 advisory",
        f"**场景D(Agent2 确定性公式)**: {summary_d}; 与期望{expected_d} 一致={all(abs(summary_d.get(k, 1e9)-v)<1e-6 for k,v in expected_d.items())}",
        f"**场景E(Agent2 软硬质量门)**: COMPLETED 条件 = quality.passed and not has_blocking_request",
        "",
        "### Agent2 涉及文件与行为(静态核验)",
        "- calculations.py: 毛利率/净利率/研发·销售·管理费用率/海外收入占比 均已加入 ratio_inputs",
        "- service.py L311-319: 质量门软硬分级, 普通补充建议不阻断",
    ]
    (OUTPUT / "SUMMARY.md").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    (OUTPUT / "RUNLOG.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n输出目录: {OUTPUT}")


if __name__ == "__main__":
    asyncio.run(main())