from __future__ import annotations
import asyncio
import hashlib
import json
import logging
import os
import re
import threading
import time
import mimetypes
from dataclasses import dataclass
from typing import Any, Literal
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("api_routes")

from backend.app.core.event_hub import event_hub
from backend.app.core.report_delivery import (
    report_download_eligibility as _report_download_eligibility,
    report_download_options,
)
from backend.app.core.storage import storage
from backend.app.engine.state_machine import (
    ReviewConflictError,
    RevisionConflictError,
    UnsupportedChainCertificationError,
    engine,
    expose_current_review,
)
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


def _current_state_response(state: WorkflowState) -> WorkflowState:
    directory = storage.get_run_dir(state.run_id) / "artifacts"
    state.report_download = report_download_options(state, directory)
    return expose_current_review(state)


@router.post("/runs", response_model=WorkflowState, status_code=status.HTTP_201_CREATED)
async def create_run_endpoint(req: RunCreateRequest) -> WorkflowState:
    """创建并启动研报任务（首阶段异步推进，返回初始状态）"""
    try:
        return _current_state_response(await engine.create_run(req))
    except ReviewConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


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
    return _current_state_response(state)


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
    return state


@router.post("/runs/{run_id}/revisions/{revision}/restore", response_model=WorkflowState)
async def restore_revision_endpoint(run_id: str, revision: int) -> WorkflowState:
    """从指定的历史版本快照回滚并恢复为新版本"""
    try:
        return _current_state_response(await engine.restore_revision(run_id, revision))
    except ValueError as e:
        err_msg = str(e)
        if "未找到" in err_msg or "不存在" in err_msg:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=err_msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err_msg)
    except Exception as e:
        logger.exception(f"版本回滚恢复失败: run_id={run_id}, revision={revision} - {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


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
        return _current_state_response(await engine.handle_review(req))
    except UnsupportedChainCertificationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except (ReviewConflictError, RevisionConflictError) as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/runs/{run_id}/cancel", response_model=WorkflowState)
async def cancel_run_endpoint(run_id: str) -> WorkflowState:
    """中途强行中断并取消运行中或等待审核的任务"""
    try:
        return _current_state_response(await engine.cancel_run(run_id))
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
        return _current_state_response(await engine.resume_run(run_id, from_stage=from_stage))
    except ReviewConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
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


@router.get("/runs/{run_id}/events/summary")
async def get_call_summary_endpoint(run_id: str):
    """Summarize distinct logical calls and actual requests from the full event history."""
    return event_hub.get_call_summary(run_id)


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
    deleted_count, cancelled_count = await engine.clear_all_runs()
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
    await engine.delete_run(run_id)
    return {"status": "ok", "message": f"任务 {run_id} 已成功删除"}


@router.get("/runs/{run_id}/report-preview", response_class=FileResponse)
async def preview_report_endpoint(run_id: str):
    """Serve current HTML for review without enabling formal downloads."""
    state = storage.load_state(run_id)
    if not state:
        raise HTTPException(404, "未找到研报任务")
    directory = storage.get_run_dir(run_id) / "artifacts"
    if not report_download_options(state, directory).preview_available:
        raise HTTPException(409, "当前版本没有可预览的报告")
    headers = {"Cache-Control": "private, no-store", "Content-Security-Policy": "sandbox"}
    fusion = state.stage_results["report_fusion"]
    if not fusion.data.get("quality_notice") and (directory / "report_view.json").is_file():
        from report_fusion.render import render_html

        try:
            view, _, _ = _read_report_view(directory)
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            logger.warning("任务 %s 的历史视图无法按当前结构渲染，使用已保存的报告预览", run_id)
        else:
            if not fusion.data.get("report_id") or fusion.data["report_id"] == view.report_id:
                content = render_html(view, source_index_mode="compact", embedded_preview=True)
                return Response(content, media_type="text/html", headers=headers)
    return FileResponse(directory / "report.html", media_type="text/html", headers=headers)


@router.get("/runs/{run_id}/artifacts/{artifact_id}")
async def download_artifact_endpoint(run_id: str, artifact_id: str, mode: Literal["formal", "draft"] = "formal"):
    """下载研报产物文件流（Markdown / HTML / PDF / 结构化 JSON 数据）"""
    run_dir = storage.get_run_dir(run_id)
    artifacts_dir = run_dir / "artifacts"

    # 0. S-02：报告类产物必须先通过「当前版本资格」检查，
    #    不能只判断文件存在——编辑后旧 PDF 仍留在磁盘上供历史查阅，
    #    但不得再从固定 ID / 原文件名入口当作当前版本返回。
    _REPORT_ARTIFACT_IDS = {
        "report_markdown": ".md",
        "report_html": ".html",
        "report_pdf": ".pdf",
    }
    is_report_artifact = artifact_id in _REPORT_ARTIFACT_IDS or artifact_id in (
        "report.md",
        "report.html",
        "report.pdf",
    )
    draft_download = False
    if is_report_artifact:
        # 资格判定已抽为共享函数，GET 的历史兼容与错误响应保持原样。
        state = storage.load_state(run_id)
        decision = _report_download_eligibility(state, artifact_id, mode)
        draft_download = decision.draft_download
        if not decision.eligible:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="当前报告产物已失效（内容已编辑待重建，或融合未获批），请重建后再下载",
            )

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

    if not target_path.resolve().is_relative_to(artifacts_dir.resolve()):
        raise HTTPException(status_code=400, detail="产物文件不得位于任务目录之外")
    canonical_report = {"report.md": "report_markdown", "report.html": "report_html", "report.pdf": "report_pdf"}.get(target_path.resolve().name)
    if canonical_report and not is_report_artifact:
        return await download_artifact_endpoint(run_id, canonical_report, mode)
    if target_path.suffix.lower() in {".md", ".html", ".pdf"}:
        state = storage.load_state(run_id)
        fusion = state.stage_results.get("report_fusion") if state else None
        if fusion and fusion.data.get("exports_stale"):
            raise HTTPException(status_code=409, detail="报告已修改，当前导出版本需要重新生成")

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
        filename=("draft-" + target_path.name) if draft_download else target_path.name,
        headers={"X-Report-Mode": "draft" if draft_download else "formal", "X-Report-Release-Mode": "draft_with_warnings" if draft_download else "formal"},
    )


class CompactExportRequest(BaseModel):
    """工作台紧凑交付包请求：模式必填，版本号用于拦住渲染期间的并发修改。"""

    mode: Literal["formal", "draft"]
    expected_revision: int = Field(ge=0, strict=True)


@dataclass(frozen=True)
class CompactSnapshot:
    view: Any
    view_sha256: str
    revision: int
    report_id: str
    mode: str
    view_path: Any


# 单进程只允许一个紧凑包渲染位：避免一键连点启动多个 Chromium。
_COMPACT_EXPORT_SLOT = threading.Lock()
_COMPACT_EXPORT_TIMEOUT = float(os.getenv("A5_COMPACT_EXPORT_TIMEOUT_SECONDS", "190"))


def _read_report_view(artifacts_dir):
    from report_fusion.models import ReportViewModel

    view_path = artifacts_dir / "report_view.json"
    if not view_path.is_file():
        raise HTTPException(409, "缺少当前报告视图，请重新生成")
    if not view_path.resolve().is_relative_to(artifacts_dir.resolve()):
        raise HTTPException(400, "报告视图不得位于任务目录之外")

    raw_bytes = view_path.read_bytes()
    try:
        raw = json.loads(raw_bytes.decode("utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("报告视图必须是 JSON 对象")
        # 编辑导出会在视图里混入工作流附加字段；按声明字段投影后再校验。
        canonical = {k: v for k, v in raw.items() if k in ReportViewModel.model_fields}
        view = ReportViewModel.model_validate(canonical)
    except (ValueError, TypeError, UnicodeDecodeError) as exc:
        raise HTTPException(409, f"当前报告视图无法解析，请重新生成：{exc}") from exc

    return view, raw_bytes, view_path


def _compact_snapshot(state, artifacts_dir, body: CompactExportRequest) -> CompactSnapshot:
    """锁内执行：版本、资格、文件可用性与视图一致性；只返回制包所需快照。"""
    if state.revision != body.expected_revision:
        raise HTTPException(409, "报告版本已更新，请刷新页面后重新下载")
    if state.status in ("cancelled", "rejected", "failed", "running", "pending"):
        raise HTTPException(409, "当前任务状态不允许导出交付包")
    fusion = state.stage_results.get("report_fusion")
    fusion_data = fusion.data if (fusion and isinstance(fusion.data, dict)) else {}
    decision = _report_download_eligibility(state, "report_pdf", body.mode)
    if not decision.eligible or not decision.generation_ok:
        raise HTTPException(409, "当前报告产物已失效，请刷新或重新生成当前报告")
    if decision.built_at_revision is None or decision.built_at_revision != body.expected_revision:
        raise HTTPException(409, "历史报告缺少构建代次，请先重建当前报告")
    if any(fusion_data.get(k) for k in ("exports_stale", "needs_reexport", "delivery_blocked")):
        raise HTTPException(409, "当前导出文件需要重新生成，请刷新后重试")
    if body.mode == "draft" and not decision.explicit_draft:
        raise HTTPException(409, "当前版本未获明确的受限草稿下载资格")

    pdf_path = artifacts_dir / "report.pdf"
    if not pdf_path.is_file() or pdf_path.stat().st_size == 0:
        raise HTTPException(409, "当前 PDF 不可用，请重新生成后再导出")
    view, raw_bytes, view_path = _read_report_view(artifacts_dir)

    fused_report_id = fusion_data.get("report_id")
    if fused_report_id and str(fused_report_id) != view.report_id:
        raise HTTPException(409, "报告视图与融合结果不一致，请重新生成")
    fused_delivery = fusion_data.get("delivery_status")
    if fused_delivery and fused_delivery != view.delivery_status:
        raise HTTPException(409, "报告视图与交付级别不一致，请重新生成")
    if body.mode == "formal" and view.delivery_status != "ready":
        raise HTTPException(409, "正式交付要求报告状态为 ready；受限草稿请改用草稿下载")
    if body.mode == "draft" and view.delivery_status != "ready_with_limits":
        raise HTTPException(409, "草稿视图缺少受限标识，请重新生成当前报告")

    return CompactSnapshot(
        view=view,
        view_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        revision=state.revision,
        report_id=view.report_id,
        mode=body.mode,
        view_path=view_path,
    )


@router.get("/runs/{run_id}/exports/evidence-index")
async def download_evidence_index(
    run_id: str, expected_revision: int = Query(ge=0), mode: Literal["formal", "draft"] = "formal",
):
    """Download the current delivery's full evidence catalog without rendering the PDF."""
    from report_fusion.render import EVIDENCE_CSV_NAME, render_evidence_csv

    try:
        async with engine._run_lock(run_id):
            engine._ensure_not_clearing()
            state = storage.load_state(run_id)
            if state is None:
                raise HTTPException(404, "未找到研报任务")
            directory = storage.get_run_dir(run_id) / "artifacts"
            body = CompactExportRequest(mode=mode, expected_revision=expected_revision)
            snapshot = _compact_snapshot(state, directory, body)
            content = render_evidence_csv(snapshot.view)
    except ReviewConflictError as exc:
        raise HTTPException(409, "报告已更新或正在清理，请刷新后重试") from exc

    filename = ("draft-" if mode == "draft" else "") + EVIDENCE_CSV_NAME
    return Response(content=content, media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "private, no-store",
        "X-Report-Mode": mode,
    })


@router.post("/runs/{run_id}/exports/compact")
async def export_compact_report(run_id: str, body: CompactExportRequest):
    """工作台一次性紧凑交付包：锁内取快照 → 锁外渲染 → 回锁复核，ZIP 只在内存中。"""
    from report_fusion.export_view import build_package_bytes

    run_dir = storage.get_run_dir(run_id)
    artifacts_dir = (run_dir / "artifacts").resolve()
    if not run_dir.is_dir():
        raise HTTPException(404, f"任务不存在: {run_id}")

    # 1) 短时持锁取快照
    try:
        async with engine._run_lock(run_id):
            engine._ensure_not_clearing()
            state = storage.load_state(run_id)
            if state is None:
                raise HTTPException(404, f"任务不存在: {run_id}")
            snapshot = _compact_snapshot(state, artifacts_dir, body)
    except ReviewConflictError as exc:
        raise HTTPException(409, "正在清空任务，请稍后重试") from exc

    # 2) 释放 run 锁后再渲染，编辑与取消可正常提交；仅本端点受单渲染位限制
    if not _COMPACT_EXPORT_SLOT.acquire(blocking=False):
        raise HTTPException(429, "紧凑交付包正在生成，请稍后手动重试")
    started = time.monotonic()
    try:
        try:
            data = await asyncio.wait_for(
                build_package_bytes(
                    snapshot.view, "compact",
                    pdf_timeout_seconds=max(10.0, _COMPACT_EXPORT_TIMEOUT - 10),
                ),
                timeout=_COMPACT_EXPORT_TIMEOUT,
            )
        except (asyncio.TimeoutError, TimeoutError) as exc:
            raise HTTPException(504, "PDF 渲染超时，请稍后重试") from exc
        except Exception as exc:
            logger.exception("紧凑交付包生成失败 run_id=%s", run_id)
            raise HTTPException(500, f"紧凑交付包生成失败：{type(exc).__name__}") from exc
    finally:
        _COMPACT_EXPORT_SLOT.release()

    # 3) 回锁复核：版本、资格、视图字节或报告标识变化一律丢弃内存 ZIP
    try:
        async with engine._run_lock(run_id):
            fresh = storage.load_state(run_id)
            if fresh is None:
                raise HTTPException(404, f"任务不存在: {run_id}")
            if fresh.revision != snapshot.revision:
                raise HTTPException(409, "渲染期间报告版本已变化，请刷新后重新下载")
            try:
                current = snapshot.view_path.read_bytes()
            except OSError as exc:
                raise HTTPException(409, "渲染期间报告视图已变化，请刷新后重新下载") from exc
            if hashlib.sha256(current).hexdigest() != snapshot.view_sha256:
                raise HTTPException(409, "渲染期间报告内容已变化，请刷新后重新下载")
            decision = _report_download_eligibility(fresh, "report_pdf", snapshot.mode)
            if not decision.eligible or not decision.generation_ok:
                raise HTTPException(409, "渲染期间下载资格已变化，请刷新后重新下载")
            fusion = fresh.stage_results.get("report_fusion")
            fdata = fusion.data if (fusion and isinstance(fusion.data, dict)) else {}
            if fdata.get("report_id") and str(fdata["report_id"]) != snapshot.report_id:
                raise HTTPException(409, "渲染期间报告标识已变化，请刷新后重新下载")
    except ReviewConflictError as exc:
        raise HTTPException(409, "正在清空任务，请稍后重试") from exc

    filename = (
        ("draft-" if snapshot.mode == "draft" else "")
        + f"report-compact-r{snapshot.revision}.zip"
    )
    logger.info(
        "紧凑交付包 run_id=%s revision=%s mode=%s bytes=%d elapsed=%.2fs",
        run_id, snapshot.revision, snapshot.mode, len(data), time.monotonic() - started,
    )
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
            "X-Report-Mode": snapshot.mode,
            "X-Report-Release-Mode": "draft_with_warnings" if snapshot.mode == "draft" else "formal",
        },
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

