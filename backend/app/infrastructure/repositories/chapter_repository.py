"""SQLite-backed chapter persistence for incremental writing and recovery."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import settings

CHAPTER_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS chapter_checkpoints (
    run_id TEXT NOT NULL,
    chapter_id TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'generating',
    content_json TEXT,
    quality_json TEXT,
    model_name TEXT,
    prompt_version TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (run_id, chapter_id, revision)
)
"""

import aiosqlite


class ChapterRepository:
    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = str(db_path or settings.CHECKPOINT_DATABASE_PATH)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

    async def initialize(self) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(CHAPTER_TABLE_SQL)
            await db.commit()

    async def save_chapter(
        self,
        *,
        run_id: str,
        chapter_id: str,
        revision: int,
        status: str,
        content_json: dict[str, Any] | None = None,
        quality_json: dict[str, Any] | None = None,
        model_name: str | None = None,
        prompt_version: str | None = None,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """INSERT OR REPLACE INTO chapter_checkpoints
                   (run_id, chapter_id, revision, status, content_json, quality_json,
                    model_name, prompt_version, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    chapter_id,
                    revision,
                    status,
                    json.dumps(content_json, ensure_ascii=False) if content_json else None,
                    json.dumps(quality_json, ensure_ascii=False) if quality_json else None,
                    model_name,
                    prompt_version,
                    now,
                    now,
                ),
            )
            await db.commit()

    async def get_completed_chapters(self, run_id: str, revision: int) -> list[str]:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                """SELECT chapter_id FROM chapter_checkpoints
                   WHERE run_id = ? AND revision = ? AND status = 'quality_passed'""",
                (run_id, revision),
            )
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

    async def get_chapter(
        self, run_id: str, chapter_id: str, revision: int
    ) -> dict[str, Any] | None:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                """SELECT content_json, status FROM chapter_checkpoints
                   WHERE run_id = ? AND chapter_id = ? AND revision = ?""",
                (run_id, chapter_id, revision),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return {"content": json.loads(row[0]) if row[0] else None, "status": row[1]}
