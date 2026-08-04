"""Lifecycle-managed SQLite checkpointer for the LangGraph workflow."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


@asynccontextmanager
async def open_sqlite_checkpointer(path: Path) -> AsyncIterator[AsyncSqliteSaver]:
    """Open, initialize, and close one SQLite saver for an application lifespan."""

    resolved_path = path.expanduser().resolve()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(resolved_path)) as checkpointer:
        await checkpointer.setup()
        yield checkpointer
