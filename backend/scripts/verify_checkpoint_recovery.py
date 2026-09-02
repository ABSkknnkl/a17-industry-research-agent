"""BUG-5 验证：全库 checkpoint 快照反序列化兼容性检查。

背景（2026-09-01）：PipelineGraphState 的 current_stage/status 通道存
StageName/StageStatus 枚举实例，msgpack 按类型路径编码。langgraph 对
unregistered type 先告警（未来版本将阻断恢复）。生产 checkpointer 已
显式传入 allowed_msgpack_modules 白名单（见
app/infrastructure/checkpoint/sqlite.py）。

本脚本用**与生产完全相同的白名单 serde** 对 checkpoint 库做两层验证：
1. 原始层：直接扫 checkpoint_blobs 表，逐条 serde.loads；
2. 端到端层：AsyncSqliteSaver.alist 遍历全部 thread 的全部快照并访问
   channel_values / pending_writes（真实恢复路径）。

任何白名单外的类型会被 langgraph 阻断并告警（显式白名单 = 严格语义：
SAFE 内置类型 + 白名单放行，其余阻断）。输出 PASS/FAIL 与类型清单。

用法：
    python scripts/verify_checkpoint_recovery.py [db_path]
    # 默认 data/checkpoints.sqlite
"""

from __future__ import annotations

import asyncio
import sys
import warnings
from collections import Counter
from pathlib import Path

import aiosqlite
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

# 与 app/infrastructure/checkpoint/sqlite.py 保持同一白名单（单一事实源
# 的替代方案：直接导入常量，避免两处漂移）。
from app.infrastructure.checkpoint.sqlite import _MSGPACK_ALLOWLIST  # noqa: E402


def build_serde() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=[*_MSGPACK_ALLOWLIST])


async def scan_blobs(db_path: Path) -> tuple[int, Counter, list[str]]:
    """原始层：逐条反序列化 langgraph 3.1.x schema 的所有 BLOB。

    表结构（BaseSqliteSaver.setup）：checkpoints(checkpoint, metadata) +
    writes(value)。业务表（如 chapter_checkpoints）存 JSON 文本，
    不在 msgpack 验证范围。
    """

    types: Counter = Counter()
    errors: list[str] = []
    total = 0
    queries = (
        (
            "checkpoints.checkpoint",
            "SELECT thread_id, checkpoint_id, type, checkpoint FROM checkpoints WHERE checkpoint IS NOT NULL",
        ),
        (
            "checkpoints.metadata",
            "SELECT thread_id, checkpoint_id, type, metadata FROM checkpoints WHERE metadata IS NOT NULL",
        ),
        (
            "writes.value",
            "SELECT thread_id, checkpoint_id, type, value FROM writes WHERE value IS NOT NULL",
        ),
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        conn = await aiosqlite.connect(str(db_path))
        try:
            for label, sql in queries:
                async with conn.execute(sql) as cursor:
                    async for thread_id, checkpoint_id, type_str, blob in cursor:
                        if blob is None:
                            continue
                        total += 1
                        try:
                            serde = build_serde()
                            value = serde.loads_typed((str(type_str or "msgpack"), blob))
                            types[f"{label} -> {type(value).__module__}.{type(value).__qualname__}"] += 1
                        except Exception as exc:  # noqa: BLE001 - 需要完整暴露失败类型
                            errors.append(
                                f"{label} thread={thread_id} checkpoint={checkpoint_id}: "
                                f"{type(exc).__name__}: {exc}"
                            )
        finally:
            await conn.close()
        for warning in caught:
            text = str(warning.message)
            if "unregistered" in text or "Blocked" in text or "blocked" in text:
                errors.append(f"WARNING: {text}")
    return total, types, errors


async def scan_snapshots(db_path: Path) -> tuple[int, Counter, list[str]]:
    """端到端层：走 AsyncSqliteSaver 恢复路径遍历全部快照。"""

    snapshot_count = 0
    thread_ids: set[str] = set()
    errors: list[str] = []
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        # 只读打开：验证过程不写库、不触发 WAL 回放，不影响运行中的 run。
        conn = await aiosqlite.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            checkpointer = AsyncSqliteSaver(conn, serde=build_serde())
            async for snapshot in checkpointer.alist(None):
                snapshot_count += 1
                thread_ids.add(snapshot.config.get("configurable", {}).get("thread_id", "?"))
                # CheckpointTuple.checkpoint 内含 channel_values /
                # pending_sends；访问即触发真实反序列化路径。
                try:
                    checkpoint = snapshot.checkpoint
                    values = checkpoint.get("channel_values") or {}
                    if isinstance(values, dict):
                        from app.schemas.workflow import StageName, StageStatus

                        if "current_stage" in values:
                            assert values["current_stage"] in list(StageName), values[
                                "current_stage"
                            ]
                        if "status" in values:
                            assert values["status"] in list(StageStatus), values["status"]
                    _ = checkpoint.get("pending_sends")
                    _ = snapshot.metadata
                    _ = snapshot.pending_writes
                except AssertionError as exc:
                    errors.append(f"thread={snapshot.config} 通道值语义漂移: {exc}")
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"快照恢复失败: {type(exc).__name__}: {exc}")
        finally:
            await conn.close()
        for warning in caught:
            text = str(warning.message)
            if "unregistered" in text or "Blocked" in text or "blocked" in text:
                errors.append(f"WARNING: {text}")
    return snapshot_count, Counter({"threads": len(thread_ids)}), errors


async def main() -> int:
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        BACKEND_ROOT / "data" / "checkpoints.sqlite"
    )
    if not db_path.exists():
        print(f"[SKIP] 数据库不存在: {db_path}")
        return 0

    print(f"[DB] {db_path} size={db_path.stat().st_size / 1024 / 1024:.1f}MB")

    blob_total, blob_types, blob_errors = await scan_blobs(db_path)
    print(f"[LAYER1] blobs={blob_total} deserialized_types={dict(blob_types)}")
    if blob_errors:
        print(f"[LAYER1] errors={len(blob_errors)}")
        for line in blob_errors[:20]:
            print("   ", line[:300])

    snapshot_total, stats, snap_errors = await scan_snapshots(db_path)
    print(
        f"[LAYER2] snapshots={snapshot_total} threads={stats.get('threads', 0)}"
    )
    if snap_errors:
        print(f"[LAYER2] errors={len(snap_errors)}")
        for line in snap_errors[:20]:
            print("   ", line[:300])

    all_errors = blob_errors + snap_errors
    if all_errors:
        print(f"\n[FAIL] 白名单外类型或反序列化失败共 {len(all_errors)} 条——")
        print("       需把它们加入 _MSGPACK_ALLOWLIST 后重新验证。")
        return 1
    print(
        f"\n[PASS] 全库 {snapshot_total} 个快照 / {blob_total} 个 blob 均可在"
        "白名单 serde 下正常恢复，无未注册类型。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
