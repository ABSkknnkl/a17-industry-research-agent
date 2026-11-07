"""Keep locally edited report views and their downloadable versions consistent."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from html import escape
from pathlib import Path
from typing import Any

from backend.app.schemas.workflow import ArtifactRef, WorkflowState

logger = logging.getLogger(__name__)


def _replace(path: Path, content: str) -> None:
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=".report-", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
        Path(name).replace(path)
    finally:
        Path(name).unlink(missing_ok=True)


def refresh_edited_exports(state: WorkflowState, run_dir: Path, edits: dict[str, Any]) -> None:
    """Render current Markdown/HTML locally; never retain an obsolete PDF."""
    from pydantic import ValidationError
    from report_fusion.models import ReportViewModel
    from report_fusion.render import render_html, render_markdown

    result = state.stage_results["report_fusion"]
    art = run_dir / "artifacts"
    view_path = art / "report_view.json"
    # Fail closed before rendering: old artifacts cannot masquerade as this revision.
    result.data["exports_stale"] = True
    result.data["formats"] = []
    result.artifacts = []
    result.data["quality"] = {}
    quality_notice = "报告经人工编辑，原质检结论已失效，请重新融合后核验。"
    result.data["quality_notice"] = quality_notice
    result.data["delivery_status"] = "ready_with_limits"
    raw: dict[str, Any] | None = None
    for name in ("report.md", "report.html", "report.pdf", "manifest.json", "consistency_report.json"):
        (art / name).unlink(missing_ok=True)
    try:
        raw = json.loads(view_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("报告视图必须为对象")
        prior_summary = raw.get("executive_summary")
        raw.update(edits)
        raw["quality"] = {}
        raw["quality_notice"] = quality_notice
        raw["delivery_status"] = "ready_with_limits"
        warnings = raw.get("warnings") or []
        raw["warnings"] = list(dict.fromkeys([*warnings, quality_notice]))
        summary = raw.get("executive_summary")
        if isinstance(summary, str):
            summary = {**(prior_summary if isinstance(prior_summary, dict) else {}), "headline": summary}
            raw["executive_summary"] = summary
        if "key_metrics" in edits and isinstance(summary, dict):
            summary["metric_cards"] = [
                {
                    "label": str(card.get("label") or card.get("name") or "指标"),
                    "value": str(card.get("value", "")), "unit": card.get("unit"),
                    "evidence_ids": card.get("evidence_ids") or card.get("evidence_record_ids") or [],
                }
                for card in edits["key_metrics"] if isinstance(card, dict)
            ]
        canonical = {k: v for k, v in raw.items() if k in ReportViewModel.model_fields}
        view = ReportViewModel.model_validate(canonical)
        markdown, html = render_markdown(view), render_html(view)
        rating = str(raw.get("investment_rating") or "").strip()
        if rating:
            markdown += f"\n\n## 人工确认评级\n\n{rating}\n"
            html = html.replace("</body>", f"<section><h2>人工确认评级</h2><p>{escape(rating)}</p></section></body>")
        _replace(art / "report.md", markdown)
        _replace(art / "report.html", html)
        raw.update(view.model_dump(mode="json"))
        raw["formats"] = ["markdown", "html"]
        raw["exports_stale"] = False
        _replace(view_path, json.dumps(raw, ensure_ascii=False, indent=2))
        entries = []
        revision = state.revision + 1
        for kind, name in (("report_markdown", "report.md"), ("report_html", "report.html"), ("report_view_json", "report_view.json")):
            path = art / name
            content = path.read_bytes()
            checksum = hashlib.sha256(content).hexdigest()
            entries.append({"kind": kind, "uri": str(path), "size_bytes": len(content), "sha256": checksum})
            result.artifacts.append(ArtifactRef(artifact_id=kind, kind=kind, uri=str(path), checksum=checksum, revision=revision))
        manifest_path = art / "manifest.json"
        _replace(manifest_path, json.dumps({"report_id": view.report_id, "revision": revision, "artifacts": entries}, ensure_ascii=False, indent=2))
        result.artifacts.append(ArtifactRef(artifact_id="artifact_manifest", kind="artifact_manifest", uri=str(manifest_path), revision=revision))
        result.data.update(exports_stale=False, formats=["markdown", "html"],
                           artifacts=[a.model_dump(mode="json") for a in result.artifacts],
                           export_notice="Markdown 与 HTML 已更新；PDF 需重新融合后生成。")
    except (OSError, ValueError, TypeError, ValidationError) as exc:
        logger.warning("编辑后的报告无法本地导出: %s", exc)
        result.data.update(exports_stale=True, formats=[], artifacts=[],
                           export_notice="此历史报告缺少完整渲染数据，请重新融合后再下载或定稿。")
        if isinstance(raw, dict):
            raw["exports_stale"] = True
            raw["formats"] = []
            _replace(view_path, json.dumps(raw, ensure_ascii=False, indent=2))
