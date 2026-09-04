"""Bounded parallel execution of an Agent 1 retrieval plan through ToolGateway.

2026-09-04 文档通道降级链：结构化技能失败（零行，或静默回退行情垃圾数据）
时，按 ``SkillQueryTask.fallback_skills`` 串行回补研报/公告/新闻通道。
关键改动是把字段相关性校验前移进成功判定——“有行且字段相关才算成功”，
从而让两类失败统一进入同一条降级路径。降级受护栏约束：单任务深度 ≤
``max_fallback_depth``、单轮全局调用数 ≤ ``fallback_call_budget``、
降级任务自身不再降级（``fallback_skills`` 恒为空，天然禁递归）。
"""

import asyncio
from dataclasses import dataclass
from time import monotonic
from typing import Any, Callable

from app.agents.data_fetcher.field_relevance import _field_relevance_check
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

# 构造降级 query 时需剔除的元数据字段（非指标语义）。
_FALLBACK_QUERY_META_FIELDS = frozenset({"标题", "发布日期", "链接", "机构", "发布主体"})


@dataclass(frozen=True)
class ExecutedTask:
    task: SkillQueryTask
    payloads: list[SkillPayload]
    record: SkillCallRecord
    gap: DataGap | None = None


def _fields_relevant(payloads: list[SkillPayload], task: SkillQueryTask) -> bool:
    """字段相关性判定（fail-open：任何异常一律放行，交由下游清洗隔离）。"""
    rows = [row for payload in payloads for row in payload.rows]
    if not rows:
        return False
    try:
        _, reason = _field_relevance_check(
            rows=rows,
            requested_metrics=task.expected_fields,
            skill=task.skill_name,
        )
    except Exception:
        return True
    return reason is None


def fallback_query_for(main_task: SkillQueryTask, fallback_skill: SkillName) -> str:
    """降级专用 query：保留目标实体与指标关键词，剥离结构化措辞。

    研报/公告/新闻检索是关键词召回，沿用针对结构化技能的原 query（含
    “从高到低”“市盈率 市净率”之类措辞）会显著降低召回质量。
    """
    del fallback_skill  # 文档通道共用同一关键词构造，无需按技能分化
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
    ) -> None:
        self._gateway = gateway
        self._concurrency = concurrency
        self._page_size = page_size
        self._fallback_chain_enabled = fallback_chain_enabled
        self._max_fallback_depth = max(0, min(2, max_fallback_depth))
        self._fallback_call_budget = max(0, fallback_call_budget)

    async def execute(
        self, plan: RetrievalPlan
    ) -> tuple[list[ExecutedTask], set[str], set[str]]:
        """Execute the plan; returns (tasks, fallback_task_ids, rescued_task_ids).

        ``fallback_task_ids`` 是本轮产生的全部降级调用（含未命中，供留痕/遥测）；
        ``rescued_task_ids`` 是被降级成功挽救的主任务 task_id（其结果已被替换
        为降级命中的文档通道证据）。
        """
        semaphore = asyncio.Semaphore(self._concurrency)

        async def run(task: SkillQueryTask) -> ExecutedTask:
            async with semaphore:
                return await self._execute_task(task)

        main_results = list(await asyncio.gather(*(run(task) for task in plan.tasks)))

        if not self._fallback_chain_enabled:
            return main_results, set(), set()

        budget = self._fallback_call_budget
        fallback_task_ids: set[str] = set()
        rescued_task_ids: set[str] = set()
        final_results: list[ExecutedTask] = []
        for main in main_results:
            replaced = main
            if (
                main.record.status != "succeeded"
                and main.task.fallback_skills
                and main.task.task_origin != "fallback"  # 禁递归：降级任务不再降级
                and budget > 0
            ):
                for depth, fallback_skill in enumerate(
                    main.task.fallback_skills[: self._max_fallback_depth], start=1
                ):
                    if budget <= 0:
                        break
                    budget -= 1
                    fallback_executed, fallback_task = await self._run_fallback(
                        main.task, fallback_skill, depth
                    )
                    fallback_task_ids.add(fallback_task.task_id)
                    if fallback_executed.record.status == "succeeded":
                        # 降级命中：以文档通道结果替换主任务结果，原缺口视为被挽救。
                        replaced = fallback_executed
                        rescued_task_ids.add(main.task.task_id)
                        break
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
        """串行执行一次降级调用并留痕（``fallback_from``/``fallback_depth``）。"""
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
        )
        return executed, fallback_task

    async def _execute_task(
        self,
        task: SkillQueryTask,
        *,
        fallback_from: str | None = None,
        fallback_depth: int = 0,
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
        # 不相关（静默回退行情）按失败处理 → 交由文档通道降级兜底，缺口如实披露。
        fields_ok = bool(rows) and _fields_relevant(payloads, task)
        if rows and fields_ok:
            status = "succeeded"
        elif error_code:
            status = "failed"
        else:
            status = "empty"
        if rows and not fields_ok and error_code is None:
            error_code = "market_quote_fallback"
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
