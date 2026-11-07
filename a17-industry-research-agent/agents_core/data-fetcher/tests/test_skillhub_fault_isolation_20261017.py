"""取数故障隔离与遥测可写回归（2026-10-17）。

背景（六主题横向测试发现的 P0）：
- **B12**：`execute_plan` 的 `asyncio.gather` 无 `return_exceptions=True`，且
  `IwencaiAuthenticationError`（问财 401）在 `execute_task` 里直接 raise。
  结果：**一条 401 带走整批 12 个任务**，事件流 0 条 tool_result / 0 条 warn，
  A1 只报「执行问财技能调度 0 次」——取数失败完全静默。
- **B14**：`skillhub.py` 缺 `import json` → `record_query_telemetry` 的 `json.dumps`
  抛 NameError 被 `except Exception: pass` 吞掉 → 遥测账本恒空 → 失败语句不可查。

验收：
- 一批任务里单个任务抛鉴权异常，**其余任务结果必须保留**，且失败任务转成
  `success=False` 的 SkillResult 并触发 on_result（可观测）；
- 遥测必须真的落一行（否则以后取数失败仍然查不到原因）。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from data_fetcher.models import Domain, SkillResult, SkillTask
from data_fetcher.skillhub import (
    IwencaiAuthenticationError,
    SkillHub,
    record_query_telemetry,
)

SKILL = "hithink-business-query"


def _task(idx: int, query: str) -> SkillTask:
    return SkillTask(
        task_id=f"t{idx}",
        skill_name=SKILL,
        arguments={"query": query, "limit": 5, "size": 5},
        purpose="故障隔离测试",
    )


def _ok_result(task: SkillTask) -> SkillResult:
    return SkillResult(
        task_id=task.task_id,
        skill_name=task.skill_name,
        skill_id="sid",
        skill_version="1.0",
        domain=Domain.INDUSTRY_CHAIN,
        query=str(task.arguments.get("query", "")),
        trace_id="tr",
        attempt_trace_ids=["tr"],
        retrieved_at=datetime.now(timezone.utc),
        success=True,
        attempts=1,
        records=[{"股票代码": "000001.SZ", "股票简称": "样本"}],
    )


def test_single_auth_failure_does_not_kill_the_batch(monkeypatch):
    """B12：一条 401 不得带走整批；其余任务结果必须保留并回调 on_result。"""
    hub = SkillHub()

    async def fake_execute(self, task, *a, **kw):                  # type: ignore[no-untyped-def]
        if "BOOM" in str(task.arguments.get("query", "")):
            raise IwencaiAuthenticationError("Iwencai authentication/quota failed: HTTP 401")
        return _ok_result(task)

    monkeypatch.setattr(SkillHub, "execute_task", fake_execute)

    tasks = [_task(0, "正常语句A"), _task(1, "BOOM 触发401"), _task(2, "正常语句B")]
    seen: list[SkillResult] = []

    async def on_result(res: SkillResult) -> None:
        seen.append(res)

    results = asyncio.run(hub.execute_plan(tasks, on_result=on_result))

    assert len(results) == 3, "整批任务不得因单条失败而丢失"
    assert len(seen) == 3, "失败任务也必须回调 on_result（否则事件流静默）"
    ok = [r for r in results if r.success]
    bad = [r for r in results if not r.success]
    assert len(ok) == 2, f"其余任务结果应保留，实际 {len(ok)}"
    assert len(bad) == 1
    assert "401" in (bad[0].error or "") or "IwencaiAuthenticationError" in (bad[0].error or ""), \
        f"失败原因必须写进 error 字段，实际 {bad[0].error!r}"
    assert bad[0].task_id == "t1"


def test_auth_failure_batch_still_reports_partial_records(monkeypatch):
    """B12 边界：全部任务都 401 时，仍返回同等数量的失败结果（不抛异常到上层）。"""
    hub = SkillHub()

    async def fake_execute(self, task, *a, **kw):                  # type: ignore[no-untyped-def]
        raise IwencaiAuthenticationError("HTTP 401")

    monkeypatch.setattr(SkillHub, "execute_task", fake_execute)
    tasks = [_task(i, f"语句{i}") for i in range(12)]     # 复现 A1 首轮 12 任务
    results = asyncio.run(hub.execute_plan(tasks))
    assert len(results) == 12, "12 个任务应产出 12 份结果（含失败），不是整批消失"
    assert all(not r.success for r in results)
    assert all("401" in (r.error or "") for r in results)


def test_query_telemetry_is_actually_written():
    """B14：遥测必须真落盘——缺 import json 时 json.dumps 抛 NameError 被吞，账本恒空。"""
    ledger = Path(__file__).resolve().parents[3] / "scratch" / "iwencai_query_telemetry.jsonl"

    def _count() -> int:
        if not ledger.exists():
            return 0
        return len([x for x in ledger.read_text(encoding="utf-8").splitlines() if x.strip()])

    before = _count()
    record_query_telemetry(
        task_id="telemetry-regression",
        skill_name=SKILL,
        domain="industry_chain",
        original_query="测试 语句 应被记录",
        relaxed_query=None,
        success=False,
        row_count=0,
        stage="failed",
        error="HTTP 401",
    )
    after = _count()
    assert after == before + 1, f"遥测账本应新增 1 行（{before} → {after}）"
    last = json.loads([x for x in ledger.read_text(encoding="utf-8").splitlines() if x.strip()][-1])
    assert "original_query" not in last and "error" not in last
    assert last["error_present"] is True
    assert last["success"] is False
