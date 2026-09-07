"""Bounded parallel execution of an Agent 1 retrieval plan through ToolGateway.

2026-09-04 文档通道降级链 → 2026-09-06 三层级联降级（方案 §1–§9）：

    L1 主技能（同花顺，query 变体 ≤3，可并发）
      → L2 备选技能（2a 结构化替代 + 2b 文档通道，串行）
      → L3 联网插件（博查，单 task 仅 1 次、不重试）
      → 兜底：判缺口 all_tiers_exhausted，如实披露，绝不编造

三条硬约束：① 单向——L3→L2→L1 反向升级永久禁止；② 不递归——降级任务自身
``fallback_skills`` 恒空，失败不再触发新降级；③ L1 可并发（semaphore），降级
调用一律串行，避免失败风暴放大外部调用量。

L1 有效判定（§2.2）= 无错误 AND rows>0 AND 字段相关 AND 可用性预检通过。后两项
分别治两种"看起来成功"的假阳性：字段相关性治 P0-6 静默回退行情（列名不对），
可用性预检治空壳数据（列名对得上但业务列全空）。
"""

import asyncio
from dataclasses import dataclass, replace
from time import monotonic
from typing import Any, Callable

from app.agents.data_fetcher.field_relevance import (
    GENERIC_PROFILE_FIELDS,
    _field_relevance_check,
    _rows_usable_precheck,
    _semantic_metric_tokens,
)
from app.runtime.tool_gateway import ToolCall, ToolGateway
from app.schemas.acquisition import (
    DataGap,
    RetrievalPlan,
    SkillCallRecord,
    SkillName,
    SkillPayload,
    SkillQueryTask,
)

# 文档通道（定性）技能集合。降级证据打 document 层级、只补定性。
DOCUMENT_CHANNEL_SKILLS = frozenset(
    {SkillName.REPORT, SkillName.ANNOUNCEMENT, SkillName.NEWS}
)

# 构造降级 query 时需剔除的元数据/泛型字段（非指标语义）。2026-09-06
# 并入 GENERIC_PROFILE_FIELDS：意图任务的 expected_fields 前段是技能
# profile 泛型列（指标名称/指标值/单位…），不剔除会把“指标名称 指标值”
# 当检索词发给博查，显著拉低 L3 召回质量。
_FALLBACK_QUERY_META_FIELDS = frozenset(
    {"标题", "发布日期", "链接", "机构", "发布主体"}
) | GENERIC_PROFILE_FIELDS

# S9 全局熔断（§8.3）：同一 Key 必然同样失败，不做熔断则每个失败任务都要
# 白跑 2-3 次无效降级。命中即跳过全部 L2 同花顺候选，直达 L3/兜底。
_AUTH_ERROR_CODES = frozenset({"auth_required", "permission_denied"})

# C-07 安全红线（§8.2）：护栏拦截后降级 = 绕过护栏 = 安全事件，禁止任何降级。
_GUARD_BLOCKED_ERROR_CODES = frozenset({"tool_call_blocked"})

# L3 供应商自身不可用（鉴权/配额/对端故障）→ 后续所有 task 不再调 L3，
# 只记 DataGap，不允许静默失败也不允许超额扣费（§8.4）。
_WEB_PROVIDER_FATAL_CODES = frozenset(
    {"auth_required", "permission_denied", "rate_limited", "provider_unavailable", "quota_exceeded"}
)


@dataclass(frozen=True)
class ExecutedTask:
    task: SkillQueryTask
    payloads: list[SkillPayload]
    record: SkillCallRecord
    gap: DataGap | None = None


def _fields_relevance_reason(
    payloads: list[SkillPayload], task: SkillQueryTask
) -> str | None:
    """字段相关性失败原因（None = 相关或无行）。

    fail-open：任何异常一律放行，交由下游清洗隔离。2026-09-06 起把
    task_origin 传入判定——意图任务启用语义相关性校验（碳酸锂价格 →
    CPI 宏观占位数据的静默回退靠它识别），基线任务维持原语义。
    """
    rows = [row for payload in payloads for row in payload.rows]
    if not rows:
        return None
    try:
        _, reason = _field_relevance_check(
            rows=rows,
            requested_metrics=task.expected_fields,
            skill=task.skill_name,
            task_origin=getattr(task, "task_origin", None),
        )
    except Exception:
        return None
    return reason


def _fields_relevant(payloads: list[SkillPayload], task: SkillQueryTask) -> bool:
    """字段相关性判定（fail-open：任何异常一律放行，交由下游清洗隔离）。"""
    return _fields_relevance_reason(payloads, task) is None


def fallback_query_for(main_task: SkillQueryTask, fallback_skill: SkillName) -> str:
    """降级专用 query：保留目标实体与指标关键词，剥离结构化措辞。

    研报/公告/新闻与联网搜索都是关键词召回，沿用针对结构化技能的原 query
    （含“从高到低”“市盈率 市净率”之类措辞）会显著降低召回质量。
    """
    del fallback_skill  # 各降级通道共用同一关键词构造，无需按技能分化
    entities = " ".join(main_task.target_entities[:3])
    metrics = " ".join(
        field
        for field in main_task.expected_fields[:4]
        if field not in _FALLBACK_QUERY_META_FIELDS
    )
    return f"{entities} {metrics}".strip() or main_task.query[:120]


def fallback_main_metric(main_task: SkillQueryTask) -> str:
    """主任务诉求的主指标名，用作降级证据的 ``substitute_for`` 溯源标记。"""
    for field in main_task.expected_fields:
        if field not in _FALLBACK_QUERY_META_FIELDS:
            return field
    if main_task.target_entities:
        return main_task.target_entities[0]
    return main_task.query[:120]


class RetrievalExecutor:
    def __init__(
        self,
        gateway: ToolGateway,
        *,
        concurrency: int = 4,
        page_size: int = 20,
        fallback_chain_enabled: bool = False,
        max_fallback_depth: int = 2,
        fallback_call_budget: int = 15,
        web_fallback_enabled: bool = False,
        web_call_budget: int = 20,
        web_provider: str = "bocha",
        degradation_time_budget: float = 20.0,
    ) -> None:
        self._gateway = gateway
        self._concurrency = concurrency
        self._page_size = page_size
        self._fallback_chain_enabled = fallback_chain_enabled
        self._max_fallback_depth = max(0, min(2, max_fallback_depth))
        self._fallback_call_budget = max(0, fallback_call_budget)
        # L3 联网插件层（S6/S9）。搜索经同一个 ToolGateway 走 WEB_SEARCH 工具，
        # 因此自动继承超时、总预算、hooks 与遥测，executor 只负责触发时机与配额。
        self._web_fallback_enabled = web_fallback_enabled
        self._web_call_budget = max(0, web_call_budget)
        self._web_provider = web_provider
        self._degradation_time_budget = max(0.0, degradation_time_budget)
        self._reset_run_state()

    def _reset_run_state(self) -> None:
        """每轮 execute() 重置熔断与配额状态（口径是"单轮 run 内"）。"""

        self._provider_auth_failed = False
        self._web_provider_failed = False
        self._web_calls_used = 0
        self._web_attempted_task_ids: set[str] = set()

    def _time_box_exceeded(self, started: float) -> bool:
        """单 task 降级总时间盒（§8.1）：超出即停止后续层级，直接兜底。"""

        return (monotonic() - started) >= self._degradation_time_budget

    async def execute(
        self, plan: RetrievalPlan
    ) -> tuple[list[ExecutedTask], set[str], set[str]]:
        """Execute the plan; returns (tasks, fallback_task_ids, rescued_task_ids).

        ``fallback_task_ids`` 是本轮产生的全部降级调用（含 L2/L3 未命中，供留痕
        与遥测）；``rescued_task_ids`` 是被降级成功挽救的主任务 task_id（其结果
        已被替换为降级命中的证据，层级记在 record.acquisition_level）。
        """
        self._reset_run_state()
        semaphore = asyncio.Semaphore(self._concurrency)

        async def run(task: SkillQueryTask) -> ExecutedTask:
            async with semaphore:
                return await self._execute_task(task)

        main_results = list(await asyncio.gather(*(run(task) for task in plan.tasks)))

        if not self._fallback_chain_enabled and not self._web_fallback_enabled:
            return main_results, set(), set()

        # S9 全局熔断：主调用阶段任一技能鉴权失败 → 同 Key 必同失败，
        # 本轮所有 L2 同花顺候选直接跳过（§8.3）。
        if any(result.record.error_code in _AUTH_ERROR_CODES for result in main_results):
            self._provider_auth_failed = True

        budget = self._fallback_call_budget
        fallback_task_ids: set[str] = set()
        rescued_task_ids: set[str] = set()
        final_results: list[ExecutedTask] = []
        for main in main_results:
            replaced = main
            path: list[str] = [main.task.skill_name.value]
            # C-07：护栏拦截禁止任何降级（绕过护栏 = 安全事件）。
            guard_blocked = main.record.error_code in _GUARD_BLOCKED_ERROR_CODES
            can_degrade = (
                main.record.status != "succeeded"
                and main.task.task_origin != "fallback"  # 禁递归：降级任务不再降级
                and not guard_blocked
            )
            l2_attempts = 0
            l2_rescued_doc_only = False
            started = monotonic()
            if can_degrade:
                # ---- L2：同花顺域内降级（鉴权熔断时整体跳过，直达 L3）----
                if (
                    self._fallback_chain_enabled
                    and not self._provider_auth_failed
                    and main.task.fallback_skills
                    and budget > 0
                ):
                    for depth, fallback_skill in enumerate(
                        main.task.fallback_skills[: self._max_fallback_depth], start=1
                    ):
                        if budget <= 0 or self._time_box_exceeded(started):
                            break
                        budget -= 1
                        l2_attempts += 1
                        fallback_executed, fallback_task = await self._run_fallback(
                            main.task, fallback_skill, depth
                        )
                        fallback_task_ids.add(fallback_task.task_id)
                        path.append(fallback_skill.value)
                        if fallback_executed.record.status == "succeeded":
                            # 降级命中：以 L2 结果替换主任务结果，原缺口视为被挽救。
                            replaced = fallback_executed
                            rescued_task_ids.add(main.task.task_id)
                            # 2026-09-06 L3 根因修复：文档通道（定性）对「指标
                            # 型诉求」只是部分覆盖（D2：doc 命中封顶 partial）——
                            # 碳酸锂价格被 NEWS 定性新闻接住后数值维度仍缺口。
                            # 此时不停在 L2，继续尝试 L3 补数值：L3 命中则替换
                            # （数值可授权参与计算+带来源），失败则保留文档挽救。
                            if fallback_skill in DOCUMENT_CHANNEL_SKILLS and _semantic_metric_tokens(
                                main.task.expected_fields
                            ):
                                l2_rescued_doc_only = True
                            break
                # ---- L3：联网插件（L2 全败、或被鉴权熔断跳过时）----
                if (
                    (replaced is main or l2_rescued_doc_only)
                    and self._web_fallback_enabled
                    and not self._web_provider_failed
                    and self._web_calls_used < self._web_call_budget
                    and main.task.task_id not in self._web_attempted_task_ids
                    and not self._time_box_exceeded(started)
                ):
                    self._web_calls_used += 1
                    self._web_attempted_task_ids.add(main.task.task_id)
                    web_executed, web_task = await self._run_web_fallback(
                        main.task, l2_attempts=l2_attempts
                    )
                    fallback_task_ids.add(web_task.task_id)
                    path.append(SkillName.WEB_SEARCH.value)
                    if web_executed.record.status == "succeeded":
                        replaced = web_executed
                        rescued_task_ids.add(main.task.task_id)
                    elif web_executed.record.error_code in _WEB_PROVIDER_FATAL_CODES:
                        # 供应商级故障：后续 task 不再调 L3（§8.4 熔断后只记缺口）。
                        self._web_provider_failed = True
            if replaced is main and len(path) > 1:
                # 三级全败：如实写缺口，绝不补造数值（§5 绝对红线）。
                replaced = replace(
                    main,
                    gap=DataGap(
                        gap_id=(
                            main.gap.gap_id
                            if main.gap is not None
                            else f"GAP-{main.task.task_id.removeprefix('Q-')}"
                        ),
                        skill_name=main.task.skill_name,
                        task_id=main.task.task_id,
                        reason_code="all_tiers_exhausted",
                        description=(
                            "该指标各通道均无数据，已列入研究边界，未编造。尝试轨迹："
                            + " → ".join(path)
                        ),
                        blocking=False,
                    ),
                )
            final_results.append(replaced)
        return final_results, fallback_task_ids, rescued_task_ids

    async def fetch_sector_constituents(
        self,
        industry_topic: str,
        *,
        top_n: int = 5,
    ) -> list[str]:
        """P0-3（2026-08-31 方案）：经 hithink_sector_selector 解析板块成分。

        用于把“主要企业/龙头/头部公司”等泛称展开为具体公司名单。板块成
        分为空或调用失败时返回空列表——调用方必须走澄清门，绝不静默降级
        为泛称查询。解析源限定本 plan 的行业主题（方案风险控制：解析错
        行业的代价高于不解析）。
        """

        try:
            result = await self._gateway.execute(
                ToolCall(
                    call_id="SECTOR-RESOLVE-1",
                    name=SkillName.SECTOR.value,
                    arguments={
                        "query": f"{industry_topic}板块成分股 市值排名 龙头",
                        "page": 1,
                        "limit": max(10, top_n * 2),
                        "call_type": "normal",
                    },
                )
            )
        except Exception:
            return []
        if result.is_error:
            return []
        try:
            payload = SkillPayload.model_validate(result.content)
        except Exception:
            return []
        names: list[str] = []
        for row in payload.rows:
            for key in ("股票简称", "股票名称", "公司名称", "名称"):
                value = row.get(key) if isinstance(row, dict) else None
                if isinstance(value, str) and value.strip():
                    name = value.strip()
                    if name not in names:
                        names.append(name)
                    break
        return names[:top_n]

    async def _run_fallback(
        self,
        main_task: SkillQueryTask,
        fallback_skill: SkillName,
        depth: int,
    ) -> tuple[ExecutedTask, SkillQueryTask]:
        """串行执行一次 L2 降级调用并留痕（``fallback_from``/``fallback_depth``）。"""
        fallback_task = main_task.model_copy(
            update={
                "task_id": f"{main_task.task_id}-FB{depth}",
                "skill_name": fallback_skill,
                "query": fallback_query_for(main_task, fallback_skill),
                "fallback_queries": [],
                # 降级任务自身不再降级（禁递归）；origin 标记供下游打标。
                "fallback_skills": [],
                "task_origin": "fallback",
            }
        )
        executed = await self._execute_task(
            fallback_task,
            fallback_from=main_task.task_id,
            fallback_depth=depth,
            acquisition_level=2,
            degraded_from_skill=main_task.skill_name,
        )
        return executed, fallback_task

    async def _run_web_fallback(
        self,
        main_task: SkillQueryTask,
        *,
        l2_attempts: int,
    ) -> tuple[ExecutedTask, SkillQueryTask]:
        """串行执行一次 L3 联网调用（单 task 仅 1 次、不重试、不递归）。

        ``max_pages=1`` + ``fallback_queries=[]`` 共同保证"不重试"：换措辞与
        翻页都会让额度翻倍、延迟叠加（§4.4）。
        """
        web_task = main_task.model_copy(
            update={
                "task_id": f"{main_task.task_id}-WEB",
                "skill_name": SkillName.WEB_SEARCH,
                "query": fallback_query_for(main_task, SkillName.WEB_SEARCH),
                "fallback_queries": [],
                "fallback_skills": [],
                "task_origin": "fallback",
                "max_pages": 1,
            }
        )
        executed = await self._execute_task(
            web_task,
            fallback_from=main_task.task_id,
            fallback_depth=min(2, l2_attempts),
            acquisition_level=3,
            degraded_from_skill=main_task.skill_name,
            web_provider=self._web_provider,
        )
        return executed, web_task

    async def _execute_task(
        self,
        task: SkillQueryTask,
        *,
        fallback_from: str | None = None,
        fallback_depth: int = 0,
        acquisition_level: int = 1,
        degraded_from_skill: SkillName | None = None,
        web_provider: str | None = None,
    ) -> ExecutedTask:
        started = monotonic()
        payloads: list[SkillPayload] = []
        trace_ids: list[str] = []
        attempts = 0
        error_code: str | None = None
        retryable = False
        query_candidates = [task.query, *task.fallback_queries]
        selected_query = task.query
        for query_index, query in enumerate(query_candidates):
            selected_query = query
            payloads = []
            for page in range(1, task.max_pages + 1):
                attempts += 1
                result = await self._gateway.execute(
                    ToolCall(
                        call_id=f"{task.task_id}-{query_index + 1}-{page}",
                        name=task.skill_name.value,
                        arguments={
                            "query": query,
                            "page": page,
                            "limit": self._page_size,
                            "call_type": "retry" if query_index else "normal",
                        },
                    )
                )
                if result.is_error:
                    error_code = result.error_code or "tool_execution_failed"
                    retryable = result.retryable
                    payloads = []
                    break
                try:
                    payload = SkillPayload.model_validate(result.content)
                except Exception:
                    error_code = "invalid_tool_payload"
                    retryable = False
                    payloads = []
                    break
                error_code = None
                retryable = False
                payloads.append(payload)
                trace_ids.append(payload.trace_id)
                if (
                    len(payload.rows) < self._page_size
                    or payload.total_count <= page * self._page_size
                ):
                    break
            # query 变体重试保持原语义：有行即停止换措辞。字段相关性不在这里
            # 触发同技能重试——否则静默回退的行情数据会借换措辞拿到无关数据
            # 冒充成功（P0-6 回归）。相关性在循环后统一判定并决定降级。
            if any(payload.rows for payload in payloads):
                break
            if error_code and not retryable:
                break
        rows = sum(len(payload.rows) for payload in payloads)
        # 字段校验前移（2026-09-04）：有行 且 字段相关 才算成功。有行但字段
        # 不相关（静默回退行情）按失败处理 → 交由降级兜底，缺口如实披露。
        # 2026-09-06：失败原因细分为 market_quote_fallback / field_mismatch
        # （碳酸锂价格 → CPI 宏观占位根因），供遥测与缺口归因使用。
        fields_reason = _fields_relevance_reason(payloads, task)
        fields_ok = bool(rows) and fields_reason is None
        # S5 可用性预检（2026-09-06）：列名相关但业务列全空的"空壳"同样判失败。
        usable_ok = fields_ok and _rows_usable_precheck(payloads, task)
        if rows and usable_ok:
            status = "succeeded"
        elif error_code:
            status = "failed"
        else:
            status = "empty"
        if rows and error_code is None:
            if not fields_ok:
                error_code = fields_reason or "market_quote_fallback"
            elif not usable_ok:
                error_code = "empty_business_columns"
        record = SkillCallRecord(
            call_id=f"CALL-{task.task_id.removeprefix('Q-')}",
            task_id=task.task_id,
            skill_name=task.skill_name,
            tier=task.tier,
            query=selected_query,
            status=status,
            row_count=rows,
            pages_fetched=len(payloads),
            attempts=attempts,
            duration_ms=max(0, round((monotonic() - started) * 1000)),
            trace_ids=trace_ids,
            error_code=error_code,
            retryable=retryable,
            fallback_from=fallback_from,
            fallback_depth=fallback_depth,
            acquisition_level=acquisition_level,
            degraded_from_skill=degraded_from_skill,
            web_provider=web_provider,
        )
        gap = None
        if status != "succeeded":
            reason = error_code or "empty_result"
            gap = DataGap(
                gap_id=f"GAP-{task.task_id.removeprefix('Q-')}",
                skill_name=task.skill_name,
                task_id=task.task_id,
                reason_code=reason,
                description=f"{task.skill_name.value}未取得可用数据：{reason}",
                # One failed call cannot decide whether acquisition as a whole
                # is blocked. The quality gate evaluates substitutable core
                # capabilities after cleaning has produced usable evidence.
                blocking=False,
            )
        return ExecutedTask(task=task, payloads=payloads, record=record, gap=gap)
