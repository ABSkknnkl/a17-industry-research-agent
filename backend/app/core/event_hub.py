from __future__ import annotations
import asyncio
from datetime import datetime
import json
import logging
from pathlib import Path
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
            message=message,
            tool=tool,
            details=details or {},
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

        logger.info(f"[{run_id}][{stage_label}][{tool or 'agent'}] {message}")
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
                                events.append(evt)
                            else:
                                events.append(AgentTraceEvent.model_validate(raw))
                        except Exception:
                            continue
            except Exception as e:
                logger.warning(f"读取 events.jsonl 失败: {e}")

        # 回填到内存
        self._cache[run_id] = events[-500:]
        return events[-limit:]

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


event_hub = EventHub()
