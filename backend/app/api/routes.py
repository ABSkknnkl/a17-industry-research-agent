from __future__ import annotations
import asyncio
import json
import logging
import os
import re
import mimetypes
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

logger = logging.getLogger("api_routes")

from backend.app.core.event_hub import event_hub
from backend.app.core.storage import storage
from backend.app.engine.state_machine import engine
from backend.app.schemas.workflow import (
    AgentTraceEvent,
    RevisionListResponse,
    ReviewRequest,
    RunCreateRequest,
    RunListResponse,
    StageName,
    WorkflowState,
)

router = APIRouter(prefix="/api/v1")


@router.post("/runs", response_model=WorkflowState, status_code=status.HTTP_201_CREATED)
async def create_run_endpoint(req: RunCreateRequest) -> WorkflowState:
    """创建并启动研报任务（首阶段异步推进，返回初始状态）"""
    return await engine.create_run(req)


@router.get("/runs", response_model=RunListResponse)
async def list_runs_endpoint(
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> RunListResponse:
    """分页获取历史任务列表"""
    return storage.list_runs(offset=offset, limit=limit)


@router.get("/runs/{run_id}", response_model=WorkflowState)
async def get_run_endpoint(run_id: str) -> WorkflowState:
    """获取指定任务的最新完整状态"""
    state = storage.load_state(run_id)
    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"未找到研报任务: {run_id}",
        )
    return state


@router.get("/runs/{run_id}/revisions", response_model=RevisionListResponse)
async def list_revisions_endpoint(run_id: str) -> RevisionListResponse:
    """获取指定任务的所有历史修订版本快照索引"""
    return storage.list_revisions(run_id)


@router.get("/runs/{run_id}/revisions/{revision}", response_model=WorkflowState)
async def get_revision_endpoint(run_id: str, revision: int) -> WorkflowState:
    """获取指定任务的某个历史版本快照详情"""
    state = storage.load_revision(run_id, revision)
    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"未找到版本快照: run_id={run_id}, revision={revision}",
        )
@router.get("/runs/{run_id}/feedback-history")
async def get_feedback_history_endpoint(run_id: str):
    """获取指定任务的人机协同反馈与优化历史记录"""
    history_file = storage.get_run_dir(run_id) / "feedback_history.json"
    if not history_file.exists():
        return []
    try:
        return json.loads(history_file.read_text(encoding="utf-8"))
    except Exception:
        return []


@router.post("/runs/{run_id}/reviews", response_model=WorkflowState)
async def submit_review_endpoint(run_id: str, req: ReviewRequest) -> WorkflowState:
    """提交人工协同审核意见（批准通过、修改重跑、原条件重跑或风险放行）"""
    if req.run_id != run_id:
        req.run_id = run_id
    try:
        return await engine.handle_review(req)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/runs/{run_id}/cancel", response_model=WorkflowState)
async def cancel_run_endpoint(run_id: str) -> WorkflowState:
    """中途强行中断并取消运行中或等待审核的任务"""
    try:
        return await engine.cancel_run(run_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.exception(f"取消任务失败: {run_id} - {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@router.post("/runs/{run_id}/resume", response_model=WorkflowState)
async def resume_run_endpoint(
    run_id: str,
    from_stage: StageName | None = Query(default=None, description="指定断点恢复的起始阶段（可选，默认自动检测未完成阶段）"),
) -> WorkflowState:
    """断点恢复执行：从中断/失败阶段或指定阶段一键继续推进流水线"""
    try:
        return await engine.resume_run(run_id, from_stage=from_stage)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception(f"恢复任务失败: {run_id} - {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@router.get("/runs/{run_id}/events", response_model=list[AgentTraceEvent])
async def get_run_events_endpoint(
    run_id: str, limit: int = Query(default=150, ge=1, le=500)
) -> list[AgentTraceEvent]:
    """获取指定任务的智能体微观执行动线与工具调用事件列表（在做什么、用了什么工具）"""
    return event_hub.get_events(run_id, limit=limit)


@router.get("/runs/{run_id}/events/stream")
async def stream_run_events_endpoint(run_id: str):
    """基于 SSE (Server-Sent Events) 实时流式下发智能体执行动线与工具调用事件"""
    async def sse_generator():
        try:
            async for event in event_hub.subscribe(run_id):
                payload = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
                yield f"data: {payload}\n\n"
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        sse_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.delete("/runs")
async def clear_all_runs_endpoint():
    """彻底清空所有历史研报任务与本地全量产物数据"""
    cancelled_count = engine.cancel_all_tasks()
    deleted_count = storage.clear_all_runs()
    event_hub.clear_all()
    return {
        "status": "ok",
        "message": f"已成功彻底清空所有历史任务与后端产物数据（清理 {deleted_count} 个任务）",
        "deleted_count": deleted_count,
        "cancelled_tasks": cancelled_count,
    }


@router.delete("/runs/{run_id}")
async def delete_run_endpoint(run_id: str):
    """删除指定历史任务及其所有本地产物数据"""
    run_dir = storage.base_dir / run_id
    output_run_dir = settings.PROJECT_ROOT / "output" / "runs" / run_id
    if not run_dir.exists() and not output_run_dir.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"任务不存在: {run_id}",
        )
    # 中断该任务的运行协程（若正在运行）
    running_task = engine._running_tasks.pop(run_id, None)
    if running_task and not running_task.done():
        running_task.cancel()
    event_hub.clear_run(run_id)
    storage.delete_run(run_id)
    return {"status": "ok", "message": f"任务 {run_id} 已成功删除"}


@router.get("/runs/{run_id}/artifacts/{artifact_id}")
async def download_artifact_endpoint(run_id: str, artifact_id: str):
    """下载研报产物文件流（Markdown / HTML / PDF / 结构化 JSON 数据）"""
    run_dir = storage.get_run_dir(run_id)
    artifacts_dir = run_dir / "artifacts"

    # 1. 常见固定 ID 映射
    id_map = {
        "report_markdown": "report.md",
        "report_html": "report.html",
        "report_pdf": "report.pdf",
        "dataset_json": "dataset.json",
        "interpretation_report_json": "interpretation_report.json",
        "chart_result_json": "chart_result.json",
        "chapter_result_json": "chapter_result.json",
        "artifact_manifest": "manifest.json",
        "report_view_json": "report_view.json",
        "consistency_report_json": "consistency_report.json",
    }
    file_name = id_map.get(artifact_id, artifact_id)
    target_path = artifacts_dir / file_name

    # 2. 尝试精确或模糊查找
    if not target_path.exists():
        found = storage.get_artifact_path(run_id, artifact_id)
        if found and found.exists():
            target_path = found

    if not target_path.exists() or not target_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"产物文件不存在: run_id={run_id}, artifact_id={artifact_id}",
        )

    mime_type, _ = mimetypes.guess_type(str(target_path))
    if not mime_type:
        if target_path.suffix == ".md":
            mime_type = "text/markdown"
        elif target_path.suffix == ".html":
            mime_type = "text/html"
        elif target_path.suffix == ".pdf":
            mime_type = "application/pdf"
        elif target_path.suffix == ".json":
            mime_type = "application/json"
        elif target_path.suffix == ".svg":
            mime_type = "image/svg+xml"
        else:
            mime_type = "application/octet-stream"

    return FileResponse(
        path=str(target_path),
        media_type=mime_type,
        filename=target_path.name,
    )


# ── 问财 SkillHub 技能生态库端点 ──────────────────────────────────────────
from backend.app.core.skills_hub import skills_hub
from backend.app.schemas.workflow import SkillCatalogResponse, SkillItem


@router.get("/skills", response_model=SkillCatalogResponse)
async def list_skills_catalog(refresh: bool = False) -> SkillCatalogResponse:
    """获取同花顺问财与五智能体协同技能全景目录"""
    return skills_hub.get_catalog(force_reload=refresh)


@router.get("/skills/{stage_id}/{skill_id}", response_model=SkillItem)
async def get_skill_detail_endpoint(stage_id: str, skill_id: str) -> SkillItem:
    """获取指定智能体阶段下单个技能的完整文档与参数定义"""
    item = skills_hub.get_skill_detail(stage_id=stage_id, skill_id=skill_id)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"未找到指定的智能体技能: {stage_id}/{skill_id}",
        )
    return item


# ── 系统与模型 Key 设置端点 ──────────────────────────────────────────
from pydantic import BaseModel
import httpx
import time
from backend.app.core.config import settings


class SettingsConfigRequest(BaseModel):
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    iwencai_api_key: str | None = None


class TestLlmRequest(BaseModel):
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None


class TestIwencaiRequest(BaseModel):
    iwencai_api_key: str | None = None


@router.get("/settings/config")
async def get_settings_config():
    """获取当前大模型与问财 Key 配置"""
    return {
        "llm_api_key": settings.LLM_API_KEY,
        "llm_base_url": settings.LLM_BASE_URL,
        "llm_model": settings.LLM_MODEL,
        "iwencai_api_key": settings.IWENCAI_API_KEY,
        "has_custom_settings": settings.user_settings_file.exists(),
    }


@router.post("/settings/config")
async def update_settings_config(req: SettingsConfigRequest):
    """更新并持久化配置，热更新环境变量"""
    update_data = {}
    if req.llm_api_key is not None:
        update_data["LLM_API_KEY"] = req.llm_api_key.strip()
    if req.llm_base_url is not None:
        update_data["LLM_BASE_URL"] = req.llm_base_url.strip().rstrip("/")
    if req.llm_model is not None:
        update_data["LLM_MODEL"] = req.llm_model.strip()
    if req.iwencai_api_key is not None:
        update_data["IWENCAI_API_KEY"] = req.iwencai_api_key.strip()

    settings.save_user_settings(update_data)
    logger.info("用户成功更新系统模型与接口配置")
    return {
        "status": "ok",
        "message": "配置保存成功并已实时生效",
        "data": {
            "llm_api_key": settings.LLM_API_KEY,
            "llm_base_url": settings.LLM_BASE_URL,
            "llm_model": settings.LLM_MODEL,
            "iwencai_api_key": settings.IWENCAI_API_KEY,
            "has_custom_settings": settings.user_settings_file.exists(),
        },
    }


@router.post("/settings/reset")
async def reset_settings_config():
    """恢复系统预置默认配置"""
    if settings.user_settings_file.exists():
        try:
            settings.user_settings_file.unlink()
        except Exception:
            pass

    settings.LLM_API_KEY = os.getenv("DEFAULT_LLM_API_KEY", "")
    settings.LLM_BASE_URL = "https://ark.cn-beijing.volces.com/api/plan/v3"
    settings.LLM_MODEL = "deepseek-v4-flash"
    settings.IWENCAI_API_KEY = os.getenv("DEFAULT_IWENCAI_API_KEY", "")
    settings.apply_to_env()
    return {
        "status": "ok",
        "message": "已恢复系统预置默认配置",
        "data": {
            "llm_api_key": settings.LLM_API_KEY,
            "llm_base_url": settings.LLM_BASE_URL,
            "llm_model": settings.LLM_MODEL,
            "iwencai_api_key": settings.IWENCAI_API_KEY,
            "has_custom_settings": False,
        },
    }


@router.post("/settings/test-llm")
async def test_llm_connectivity(req: TestLlmRequest):
    """测试大模型基座接口连通性"""
    api_key = (req.llm_api_key or settings.LLM_API_KEY).strip()
    base_url = (req.llm_base_url or settings.LLM_BASE_URL).strip().rstrip("/")
    model = (req.llm_model or settings.LLM_MODEL).strip()

    if not api_key:
        return {"success": False, "message": "API Key 不能为空"}
    if not base_url:
        return {"success": False, "message": "Base URL 不能为空"}

    endpoint = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 5,
    }

    start_t = time.time()
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(endpoint, headers=headers, json=payload)
            elapsed_ms = int((time.time() - start_t) * 1000)
            if resp.status_code == 200:
                return {
                    "success": True,
                    "message": f"连接成功！模型响应正常（耗时 {elapsed_ms}ms）",
                    "latency_ms": elapsed_ms,
                    "model": model,
                }
            else:
                return {
                    "success": False,
                    "message": f"接口返回异常 (HTTP {resp.status_code}): {resp.text[:200]}",
                    "latency_ms": elapsed_ms,
                }
    except Exception as e:
        elapsed_ms = int((time.time() - start_t) * 1000)
        return {
            "success": False,
            "message": f"连通测试失败: {str(e)}",
            "latency_ms": elapsed_ms,
        }


@router.post("/settings/test-iwencai")
async def test_iwencai_connectivity(req: TestIwencaiRequest):
    """测试问财金融数据接口连通性（支持单 Key 或多 Key 逗号分隔配置）"""
    raw_api_key = (req.iwencai_api_key or settings.IWENCAI_API_KEY).strip()
    if not raw_api_key:
        return {"success": False, "message": "问财 API Key 不能为空"}

    # 支持逗号、分号、换行分隔的多 Key 配置，提取所有有效 Key
    keys = [k.strip() for k in re.split(r"[,;\n]+", raw_api_key) if k.strip()]
    if not keys:
        return {"success": False, "message": "问财 API Key 不能为空"}

    api_key = keys[0]
    start_t = time.time()
    try:
        url = "https://openapi.iwencai.com/v1/query2data"
        import secrets
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-Claw-Call-Type": "normal",
            "X-Claw-Skill-Id": "hithink-astock-selector",
            "X-Claw-Skill-Version": "1.0.0",
            "X-Claw-Plugin-Id": "none",
            "X-Claw-Plugin-Version": "none",
            "X-Claw-Trace-Id": secrets.token_hex(32),
        }
        payload = {
            "query": "平安银行",
            "page": "1",
            "limit": "1",
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            elapsed_ms = int((time.time() - start_t) * 1000)
            key_count_hint = f"（已识别 {len(keys)} 个 Key，首个 Key 耗时 {elapsed_ms}ms）" if len(keys) > 1 else f"（耗时 {elapsed_ms}ms）"
            if resp.status_code == 200:
                return {
                    "success": True,
                    "message": f"问财官方 SkillHub 接口验证通过！{key_count_hint}",
                    "latency_ms": elapsed_ms,
                }
            elif resp.status_code in (401, 403):
                return {
                    "success": False,
                    "message": f"问财 Token 鉴权失败 (HTTP {resp.status_code})，请检查 Key 是否有效",
                    "latency_ms": elapsed_ms,
                }
            else:
                return {
                    "success": True,
                    "message": f"问财接口鉴权通过（响应码 {resp.status_code}，{key_count_hint}）",
                    "latency_ms": elapsed_ms,
                }
    except Exception as e:
        elapsed_ms = int((time.time() - start_t) * 1000)
        return {
            "success": False,
            "message": f"网络连通异常: {str(e)}",
            "latency_ms": elapsed_ms,
        }

