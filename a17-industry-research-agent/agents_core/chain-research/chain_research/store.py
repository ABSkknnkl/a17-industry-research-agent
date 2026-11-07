"""证据存储与恢复（T2，方案 §9-T2）。

═════════════════════════════════════════════════════════════════════════════
职责（方案 §7.1 落盘布局 + T2 验收）
═════════════════════════════════════════════════════════════════════════════

run 目录布局（``<run_dir>/artifacts/chain/v2/``）::

    bundle.json             # 完整版本化语义交接包
    quality.json            # 发布判断与未决项
    queries.jsonl           # 查询、目标、计数、丢弃原因
    documents/              # 原文/定位映射及内容哈希
    transformations.jsonl   # 结构、断言状态变更及理由
    manifest.json           # 代码/模型/提示词/范围/预算/来源策略版本
    view_mapping.json       # A3 编译后写入（T7，本模块预留路径）

关键行为：
- **原子写**：所有落盘先写 ``*.tmp`` 再 ``os.replace``，取消/中断后磁盘上
  永远是上一个一致快照。
- **SQLite 索引**：跨 run 的证据/文档缓存索引；缓存键必须含
  scope + 来源策略 + as_of（§5.1），不得只按主题字符串命中。
- **同源转载不充数**：``source_family`` 相同的文档在去重时算一家。
- **恢复**：从 manifest.json 可重建 ChainStore 并读回 bundle。
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from chain_research.models import (
    ChainEvidence,
    ChainKnowledgeBundle,
    ChainQualityReport,
)

_CHAIN_V2_SUBDIR = Path("artifacts") / "chain" / "v2"


def chain_v2_dir(run_dir: Path) -> Path:
    """run 目录下的 v2 落盘根路径。"""
    return run_dir / _CHAIN_V2_SUBDIR


def _atomic_write_text(path: Path, text: str) -> None:
    """原子写：同目录 tmp 文件 + os.replace。中断后保留旧快照。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):   # replace 成功后 tmp 已不存在；失败时清理
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


# ── SQLite 跨 run 证据缓存索引 ─────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS document_cache (
    cache_key     TEXT PRIMARY KEY,
    document_id   TEXT NOT NULL,
    url           TEXT,
    title         TEXT NOT NULL,
    document_kind TEXT NOT NULL,
    source_family TEXT NOT NULL,
    content_hash  TEXT NOT NULL,
    published_at  TEXT,
    fetched_at    TEXT NOT NULL,
    scope_subject TEXT NOT NULL,
    as_of         TEXT NOT NULL,
    source_policy TEXT NOT NULL,
    raw_path      TEXT
);
CREATE TABLE IF NOT EXISTS bundle_revisions (
    run_id        TEXT NOT NULL,
    revision      INTEGER NOT NULL,
    bundle_path   TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    PRIMARY KEY (run_id, revision)
);
CREATE INDEX IF NOT EXISTS idx_doc_scope ON document_cache(scope_subject, as_of, source_policy);
"""


def document_cache_key(url: str, scope_subject: str, as_of: str, source_policy: str) -> str:
    """缓存键必须包含 scope 与来源策略（§5.1：不能只按主题字符串缓存）。"""
    return "|".join((url, scope_subject, as_of, source_policy))


class ChainStore:
    """单 run 的落盘仓库 + 跨 run 的 SQLite 缓存索引。

    :param run_dir: 该 run 的根目录（storage.get_run_dir(run_id)）。
    :param cache_db: 跨 run 缓存库路径（如 ``data/chain_v2_cache.sqlite``）。
                    None 则禁用跨 run 缓存（纯落盘模式）。
    """

    def __init__(self, run_dir: Path, *, cache_db: Path | None = None) -> None:
        self.run_dir = Path(run_dir)
        self.v2_dir = chain_v2_dir(self.run_dir)
        self.documents_dir = self.v2_dir / "documents"
        self._cache_db = Path(cache_db) if cache_db else None
        if self._cache_db is not None:
            self._cache_db.parent.mkdir(parents=True, exist_ok=True)
            with self._conn() as conn:
                conn.executescript(_SCHEMA)

    # ── SQLite 连接 ─────────────────────────────────────────────────────
    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        assert self._cache_db is not None
        conn = sqlite3.connect(str(self._cache_db))
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ── bundle 落盘与恢复 ───────────────────────────────────────────────
    def save_bundle(self, bundle: ChainKnowledgeBundle) -> Path:
        """bundle.json 原子落盘 + SQLite revision 登记。"""
        path = self.v2_dir / "bundle.json"
        _atomic_write_text(path, bundle.model_dump_json(indent=2, ensure_ascii=False))
        quality_path = self.v2_dir / "quality.json"
        _atomic_write_text(
            quality_path,
            bundle.quality.model_dump_json(indent=2, ensure_ascii=False))
        manifest_path = self.v2_dir / "manifest.json"
        _atomic_write_text(
            manifest_path,
            bundle.manifest.model_dump_json(indent=2, ensure_ascii=False))
        if self._cache_db is not None:
            with self._conn() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO bundle_revisions "
                    "(run_id, revision, bundle_path, created_at) VALUES (?,?,?,?)",
                    (bundle.run_id, bundle.revision, str(path), bundle.manifest.created_at))
        return path

    def load_bundle(self) -> ChainKnowledgeBundle | None:
        """读回最近落盘的 bundle（重启恢复入口）。"""
        path = self.v2_dir / "bundle.json"
        if not path.exists():
            return None
        return ChainKnowledgeBundle.model_validate_json(path.read_text(encoding="utf-8"))

    def load_latest_revision(self) -> int:
        """恢复时读 manifest 的 revision（无 bundle 返回 0）。"""
        mpath = self.v2_dir / "manifest.json"
        if not mpath.exists():
            return 0
        data = json.loads(mpath.read_text(encoding="utf-8"))
        return int(data.get("revision", 0))

    # ── 文档原文快照 ────────────────────────────────────────────────────
    def save_document(self, document_id: str, content: bytes, *,
                      evidence: ChainEvidence, scope_subject: str,
                      as_of: str, source_policy: str) -> Path:
        """原文快照 + 缓存索引登记。content_hash 不匹配时拒绝写入。"""
        import hashlib
        actual = hashlib.sha256(content).hexdigest()[:32]
        if actual != evidence.content_hash and evidence.content_hash != actual:
            # content_hash 约定 32 位 hex；调用方需用同一算法生成
            if evidence.content_hash != actual[:len(evidence.content_hash)]:
                raise ValueError(
                    f"文档 {document_id} 内容哈希不匹配："
                    f"声明 {evidence.content_hash} vs 实际 {actual}")
        raw_path = self.documents_dir / f"{document_id}.raw"
        _atomic_write_bytes(raw_path, content)
        if self._cache_db is not None:
            key = document_cache_key(
                evidence.url or document_id, scope_subject, as_of, source_policy)
            with self._conn() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO document_cache "
                    "(cache_key, document_id, url, title, document_kind, source_family,"
                    " content_hash, published_at, fetched_at, scope_subject, as_of,"
                    " source_policy, raw_path) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (key, document_id, evidence.url, evidence.title,
                     evidence.document_kind, evidence.source_family,
                     evidence.content_hash, evidence.published_at,
                     evidence.fetched_at, scope_subject, as_of, source_policy,
                     str(raw_path)))
        return raw_path

    def find_cached_document(self, url: str, *, scope_subject: str,
                             as_of: str, source_policy: str) -> dict[str, Any] | None:
        """按完整缓存键查缓存。scope/时间/来源策略不同不误命中（T2 验收）。"""
        if self._cache_db is None:
            return None
        key = document_cache_key(url, scope_subject, as_of, source_policy)
        with self._conn() as conn:
            row = conn.execute(
                "SELECT document_id, title, document_kind, source_family,"
                " content_hash, raw_path FROM document_cache WHERE cache_key=?",
                (key,)).fetchone()
        if row is None:
            return None
        return {
            "document_id": row[0], "title": row[1], "document_kind": row[2],
            "source_family": row[3], "content_hash": row[4], "raw_path": row[5],
        }

    def same_family_count(self, source_family: str, *,
                          scope_subject: str, as_of: str) -> int:
        """同 source_family（同源转载）已收录文档数——去重时算一家不充数。"""
        if self._cache_db is None:
            return 0
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(DISTINCT content_hash) FROM document_cache "
                "WHERE source_family=? AND scope_subject=? AND as_of=?",
                (source_family, scope_subject, as_of)).fetchone()
        return int(row[0]) if row else 0

    # ── append-only 日志（queries / transformations）───────────────────
    def append_query_log(self, entry: dict[str, Any]) -> None:
        path = self.v2_dir / "queries.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def append_transformation(self, entry: dict[str, Any]) -> None:
        path = self.v2_dir / "transformations.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def read_query_log(self) -> list[dict[str, Any]]:
        return self._read_jsonl(self.v2_dir / "queries.jsonl")

    def read_transformations(self) -> list[dict[str, Any]]:
        return self._read_jsonl(self.v2_dir / "transformations.jsonl")

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out
