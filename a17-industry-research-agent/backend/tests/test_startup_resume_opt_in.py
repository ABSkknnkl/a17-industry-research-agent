import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import backend.app.main as main
import backend.app.core.storage as storage_mod
import backend.app.engine.state_machine as engine_mod


def test_restart_does_not_resume_paid_work_by_default(monkeypatch):
    monkeypatch.delenv('AUTO_RESUME_INTERRUPTED_RUNS',raising=False)
    monkeypatch.setattr(storage_mod,'StorageManager',lambda:SimpleNamespace(list_runs=lambda **kw:SimpleNamespace(items=[SimpleNamespace(status='running',run_id='r1',current_stage='data_fetch')])))
    resume=AsyncMock();monkeypatch.setattr(engine_mod.engine,'resume_run',resume)
    async def work():
        async with main.lifespan(main.app): await asyncio.sleep(0)
    asyncio.run(work());resume.assert_not_awaited()


def test_restart_can_opt_in_to_resumption(monkeypatch):
    monkeypatch.setenv('AUTO_RESUME_INTERRUPTED_RUNS','1')
    monkeypatch.setattr(storage_mod,'StorageManager',lambda:SimpleNamespace(list_runs=lambda **kw:SimpleNamespace(items=[SimpleNamespace(status='running',run_id='r1',current_stage='data_fetch')])))
    resume=AsyncMock();monkeypatch.setattr(engine_mod.engine,'resume_run',resume)
    async def work():
        async with main.lifespan(main.app): await asyncio.sleep(0)
    asyncio.run(work());resume.assert_awaited_once_with('r1')
