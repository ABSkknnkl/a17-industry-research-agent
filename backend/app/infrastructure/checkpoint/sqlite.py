"""Lifecycle-managed SQLite checkpointer for the LangGraph workflow."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


# BUG-5（2026-09-01）：PipelineGraphState 的 current_stage/status 通道直接
# 存 StageName/StageStatus 枚举实例，msgpack 按类型路径编码；解码端无白
# 名单时按 unregistered type 告警（langgraph 未来版本会升级为阻断恢复）。
# 显式白名单不影响内置 SAFE_MSGPACK_TYPES（先查 SAFE 再查白名单），旧快
# 照的兼容读路径不变。
_MSGPACK_ALLOWLIST = (
    ("app.schemas.workflow", "StageName"),
    ("app.schemas.workflow", "StageStatus"),
)


@asynccontextmanager
async def open_sqlite_checkpointer(path: Path) -> AsyncIterator[AsyncSqliteSaver]:
    """Open, initialize, and close one SQLite saver for an application lifespan."""

    # from_conn_string() 不接受 serde 参数，这里保持等价的连接生命周期
    # （aiosqlite.connect 上下文退出即关闭），改为自持连接以注入白名单。
    resolved_path = path.expanduser().resolve()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(str(resolved_path)) as conn:
        checkpointer = AsyncSqliteSaver(
            conn,
            serde=JsonPlusSerializer(
                allowed_msgpack_modules=[*_MSGPACK_ALLOWLIST],
            ),
        )
        await checkpointer.setup()
        yield checkpointer
