from __future__ import annotations
import asyncio
from datetime import datetime
import json
import logging
import re
from typing import Any, AsyncGenerator
import uuid

from backend.app.core.storage import storage
from backend.app.schemas.workflow import AgentTraceEvent, StageName

logger = logging.getLogger("event_hub")

STAGE_NAME_MAP: dict[str, str] = {
    "data_fetch": "数据采集",
    "data_interpret": "数据解读",
    "chart_generate": "图表生成",
    "chapter_write": "章节撰写",
    "report_fusion": "报告融合",
}

_EVENT_MESSAGES = {'agent_start':'阶段开始', 'agent_decision':'阶段决策已更新', 'llm_thought':'模型分析已更新',
    'tool_call':'技能调用已开始', 'tool_result':'技能调用已结束', 'tool_request':'外部请求已结束',
    'model_call':'模型调用已结束', 'model_request':'模型请求已结束', 'warn':'执行出现提示',
    'error':'执行失败', 'artifact_created':'产物已生成', 'stage_completed':'阶段已完成', 'info':'阶段进度已更新'}
from agents_core.event_safety import safe_event_details as _safe_event_details


class EventHub:
    """全系统统一的智能体实时执行动线与事件流管理器"""

    def __init__(self) -> None:
        # run_id -> list of subscriber Queues
        self._subscribers: dict[str, list[asyncio.Queue[AgentTraceEvent]]] = {}
        # run_id -> in-memory cache of recent events
        self._cache: dict[str, list[AgentTraceEvent]] = {}

    def emit(
        self,
        run_id: str,
        stage: StageName,
        event_type: str,
        message: str,
        tool: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> AgentTraceEvent:
        stage_label = STAGE_NAME_MAP.get(stage, stage)
        event = AgentTraceEvent(
            id=f"evt-{uuid.uuid4().hex[:8]}",
            timestamp=datetime.now().isoformat(),
            stage=stage,
            stage_label=stage_label,
            event_type=event_type,
            message=_EVENT_MESSAGES.get(event_type, '阶段进度已更新'),
            tool=tool if tool and re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', tool) else None,
            details=_safe_event_details(details or {}),
        )

        # 1. 缓存到内存
        if run_id not in self._cache:
            self._cache[run_id] = []
        self._cache[run_id].append(event)
        if len(self._cache[run_id]) > 500:
            self._cache[run_id] = self._cache[run_id][-500:]

        # 2. 持久化到 events.jsonl
        try:
            run_dir = storage.get_run_dir(run_id)
            artifacts_dir = run_dir / "artifacts"
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            events_file = artifacts_dir / "events.jsonl"
            with open(events_file, "a", encoding="utf-8") as f:
                f.write(event.model_dump_json() + "\n")
        except Exception as e:
            logger.warning(f"[{run_id}] 写入 events.jsonl 失败: {e}")

        # 3. 广播给 SSE 订阅者
        subs = self._subscribers.get(run_id, [])
        for queue in subs:
            try:
                queue.put_nowait(event)
            except Exception:
                pass

        logger.info("[%s][%s] %s", run_id, stage_label, event.message)
        return event

    def get_events(self, run_id: str, limit: int = 150) -> list[AgentTraceEvent]:
        """获取指定任务的事件列表（优先内存缓存，没有则从磁盘读取）"""
        if run_id in self._cache and self._cache[run_id]:
            return self._cache[run_id][-limit:]

        events: list[AgentTraceEvent] = []
        run_dir = storage.get_run_dir(run_id)
        events_file = run_dir / "artifacts" / "events.jsonl"
        if events_file.exists():
            try:
                with open(events_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            raw = json.loads(line)
                            # 兼容老版 events 格式
                            if "event_type" not in raw and "event" in raw:
                                raw_details = raw.get("details", {})
                                raw_tool = raw_details.get("skill") or raw_details.get("format")
                                evt = AgentTraceEvent(
                                    id=f"evt-{uuid.uuid4().hex[:8]}",
                                    timestamp=raw.get("timestamp", datetime.now().isoformat()),
                                    stage="report_fusion",
                                    stage_label="报告融合",
                                    event_type="tool_call" if raw_tool else "info",
                                    message=raw.get("event", "智能体执行事件"),
                                    tool=raw_tool,
                                    details=raw_details,
                                )
                                events.append(evt.model_copy(update={
                                    'message': _EVENT_MESSAGES.get(evt.event_type, '阶段进度已更新'),
                                    'details': _safe_event_details(evt.details),
                                    'tool': evt.tool if evt.tool and re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', evt.tool) else None}))
                            else:
                                evt = AgentTraceEvent.model_validate(raw)
                                events.append(evt.model_copy(update={
                                    'message': _EVENT_MESSAGES.get(evt.event_type, '阶段进度已更新'),
                                    'details': _safe_event_details(evt.details),
                                    'tool': evt.tool if evt.tool and re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', evt.tool) else None}))
                        except Exception:
                            continue
            except Exception as e:
                logger.warning(f"读取 events.jsonl 失败: {e}")

        # 回填到内存
        self._cache[run_id] = events[-500:]
        return events[-limit:]

    def get_call_summary(self, run_id: str) -> dict[str, Any]:
        from agents_core.call_ledger import summarize_events
        path = storage.get_run_dir(run_id) / 'artifacts' / 'events.jsonl'
        if not path.exists():
            return summarize_events(self._cache.get(run_id, []))
        events = []
        with path.open(encoding='utf-8') as stream:
            for line in stream:
                try:
                    events.append(json.loads(line))
                except (ValueError, TypeError):
                    continue
        return summarize_events(events)

    async def subscribe(self, run_id: str) -> AsyncGenerator[AgentTraceEvent, None]:
        """为客户端提供 SSE 实时推流订阅"""
        queue: asyncio.Queue[AgentTraceEvent] = asyncio.Queue()
        if run_id not in self._subscribers:
            self._subscribers[run_id] = []
        self._subscribers[run_id].append(queue)

        try:
            # 先发送已有历史事件
            history = self.get_events(run_id, limit=50)
            for evt in history:
                yield evt

            # 持续监听新事件
            while True:
                evt = await queue.get()
                yield evt
        finally:
            if run_id in self._subscribers and queue in self._subscribers[run_id]:
                self._subscribers[run_id].remove(queue)

    def clear_run(self, run_id: str) -> None:
        """清理特定任务的事件缓存与订阅者队列"""
        self._cache.pop(run_id, None)
        self._subscribers.pop(run_id, None)

    def clear_all(self) -> None:
        """清空全系统事件缓存与所有订阅者"""
        self._cache.clear()
        self._subscribers.clear()


event_hub = EventHub()
