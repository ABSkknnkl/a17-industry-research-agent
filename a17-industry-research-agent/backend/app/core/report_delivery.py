"""Report download eligibility shared by the workbench and download routes."""

from dataclasses import dataclass
from pathlib import Path

from backend.app.schemas.workflow import ReportDownloadOptions, WorkflowState


@dataclass(frozen=True)
class ReportDownloadEligibility:
    """报告类产物的当前版本与正式/草稿下载资格结论。"""

    eligible: bool
    draft_download: bool
    explicit_draft: bool
    generation_ok: bool
    built_at_revision: int | None


def report_download_eligibility(
    state: WorkflowState | None, artifact_id: str, mode: str
) -> ReportDownloadEligibility:
    """S-02 / R1 / P4 资格计算，由下载 GET 与紧凑交付包 POST 共用。

    这段逻辑原样来自 download_artifact_endpoint，抽函数时不改变任何判据：
    GET 的历史兼容、别名与错误响应仍按原行为执行。
    """
    fusion = state.stage_results.get("report_fusion") if state else None
    fusion_data = fusion.data if (fusion and isinstance(fusion.data, dict)) else {}
    built_at = fusion_data.get("built_at_revision")
    status_ok = bool(fusion and fusion.status in ("approved", "completed"))
    generation_ok = False
    built_at_revision: int | None = None
    if built_at is not None:
        try:
            built_at_revision = int(built_at)
            generation_ok = bool(state) and built_at_revision == state.revision
        except (TypeError, ValueError):
            generation_ok = False
        eligible = status_ok and generation_ok and not fusion_data.get("delivery_blocked")
    else:
        stale_any = any(
            (sr.data or {}).get("downstream_stale")
            for sr in (state.stage_results.values() if state else [])
            if isinstance(sr.data, dict)
        )
        eligible = status_ok and not stale_any and not fusion_data.get("delivery_blocked")

    draft_download = mode == "draft"
    if built_at is not None:
        quality = fusion_data.get("quality") or {}
        content_ok = not fusion_data.get("hard_blocked")
        formal_ok = (fusion_data.get("agent_status") != "partial"
                     and quality.get("passed") is not False)
        chain = fusion_data.get("chain_delivery") or {}
        if chain.get("requested") and chain.get("status") != "complete":
            formal_ok = False
        eligible = eligible and content_ok and (draft_download or formal_ok)

    # 编辑预览仅对本地重渲染的 MD/HTML 生效；PDF 仍受门禁约束。
    preview_kind = {
        "report_markdown": "report_markdown", "report.md": "report_markdown",
        "report_html": "report_html", "report.html": "report_html",
    }.get(artifact_id)
    edited_preview = bool(
        preview_kind and fusion and state
        and fusion.status == "waiting_review"
        and fusion_data.get("quality_notice")
        and not fusion_data.get("exports_stale")
        and not fusion_data.get("delivery_blocked")
        and any(a.kind == preview_kind and a.revision == state.revision for a in fusion.artifacts)
    )
    explicit_draft = bool(
        mode == "draft" and fusion and state and generation_ok
        and fusion_data.get("draft_available") and fusion_data.get("draft_sanitized")
        and not fusion_data.get("exports_stale") and not fusion_data.get("delivery_blocked")
        and any(a.artifact_id == {"report.md": "report_markdown", "report.html": "report_html",
                                  "report.pdf": "report_pdf"}.get(artifact_id, artifact_id)
                and a.revision == state.revision for a in fusion.artifacts)
    ) if built_at is not None else False
    eligible = eligible or explicit_draft or (edited_preview and mode == "draft")
    return ReportDownloadEligibility(
        eligible=bool(eligible),
        draft_download=draft_download,
        explicit_draft=explicit_draft,
        generation_ok=generation_ok,
        built_at_revision=built_at_revision,
    )


REPORT_FILES = {
    "report_markdown": "report.md",
    "report_html": "report.html",
    "report_pdf": "report.pdf",
    "artifact_manifest": "manifest.json",
}


def report_download_options(state: WorkflowState, directory: Path) -> ReportDownloadOptions:
    options = ReportDownloadOptions()
    fusion = state.stage_results.get("report_fusion")
    if not fusion or state.status not in ("waiting_review", "completed", "approved"):
        return options
    data = fusion.data
    if data.get("exports_stale") or data.get("delivery_blocked"):
        return options
    quality = data.get("quality")
    quality_passed = quality.get("passed") if isinstance(quality, dict) else None
    for artifact in fusion.artifacts:
        artifact_id = artifact.artifact_id
        file_name = REPORT_FILES.get(artifact_id)
        if not file_name:
            continue
        path = directory / file_name
        if artifact_id == "artifact_manifest" or not path.resolve().is_relative_to(directory.resolve()):
            continue
        try:
            if not path.is_file() or path.stat().st_size == 0:
                continue
        except OSError:
            continue
        formal = report_download_eligibility(state, artifact_id, "formal")
        draft = report_download_eligibility(state, artifact_id, "draft")
        can_share_formal = (
            state.status in ("completed", "approved") and formal.eligible
            and quality_passed is not False and not data.get("hard_blocked")
            and data.get("delivery_status") not in ("blocked", "ready_with_limits")
        )
        if artifact_id == "report_html":
            waiting_review = (
                state.status == fusion.status == "waiting_review"
                and artifact.revision == state.revision and formal.generation_ok
                and quality_passed is True and not data.get("hard_blocked")
                and data.get("delivery_status") == "ready"
            )
            options.preview_available = can_share_formal or draft.explicit_draft or (
                draft.eligible and bool(data.get("quality_notice"))
            ) or waiting_review
        if can_share_formal:
            options.formal_artifact_ids.append(artifact_id)
        elif draft.explicit_draft or (draft.eligible and data.get("quality_notice")):
            options.draft_artifact_ids.append(artifact_id)

    if options.formal_artifact_ids and any(
        artifact.artifact_id == "artifact_manifest" for artifact in fusion.artifacts
    ) and (directory / "manifest.json").is_file():
        options.formal_artifact_ids.append("artifact_manifest")

    if data.get("needs_reexport") or not (directory / "report_view.json").is_file():
        return options
    pdf = report_download_eligibility(state, "report_pdf", "formal")
    if (pdf.generation_ok and data.get("delivery_status") == "ready"
            and "report_pdf" in options.formal_artifact_ids):
        options.compact_mode = "formal"
    elif (pdf.generation_ok and data.get("delivery_status") == "ready_with_limits"
            and "report_pdf" in options.draft_artifact_ids):
        options.compact_mode = "draft"
    return options
