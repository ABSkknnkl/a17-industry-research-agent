from __future__ import annotations
import json
import shutil
from pathlib import Path
from typing import Any
from backend.app.core.config import settings
from backend.app.schemas.workflow import (
    WorkflowState,
    RunSummary,
    RunListResponse,
    RevisionSummary,
    RevisionListResponse,
)


class StorageManager:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or settings.DATA_DIR
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def get_run_dir(self, run_id: str) -> Path:
        run_dir = self.base_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "revisions").mkdir(exist_ok=True)
        (run_dir / "artifacts").mkdir(exist_ok=True)
        return run_dir

    def save_state(self, state: WorkflowState) -> None:
        run_dir = self.get_run_dir(state.run_id)
        state_file = run_dir / "state.json"
        data = state.model_dump(mode="json")
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)

        # 同时归档当前 revision
        rev_file = run_dir / "revisions" / f"{state.revision}.json"
        with open(rev_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)

    def load_state(self, run_id: str) -> WorkflowState | None:
        state_file = self.get_run_dir(run_id) / "state.json"
        if not state_file.exists():
            return None
        with open(state_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return WorkflowState.model_validate(data)

    def load_revision(self, run_id: str, revision: int) -> WorkflowState | None:
        rev_file = self.get_run_dir(run_id) / "revisions" / f"{revision}.json"
        if not rev_file.exists():
            return None
        with open(rev_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return WorkflowState.model_validate(data)

    def list_revisions(self, run_id: str) -> RevisionListResponse:
        state = self.load_state(run_id)
        if not state:
            return RevisionListResponse(run_id=run_id, current_revision=1, revisions=[])

        rev_dir = self.get_run_dir(run_id) / "revisions"
        revisions: list[RevisionSummary] = []
        for file in sorted(rev_dir.glob("*.json"), key=lambda p: int(p.stem)):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    d = json.load(f)
                revisions.append(
                    RevisionSummary(
                        revision=d.get("revision", int(file.stem)),
                        status=d.get("status", "pending"),
                        current_stage=d.get("current_stage", "data_fetch"),
                        updated_at=d.get("updated_at", ""),
                    )
                )
            except Exception:
                continue

        return RevisionListResponse(
            run_id=run_id,
            current_revision=state.revision,
            revisions=revisions,
        )

    def list_runs(self, offset: int = 0, limit: int = 20) -> RunListResponse:
        runs: list[RunSummary] = []
        for run_dir in self.base_dir.iterdir():
            if not run_dir.is_dir():
                continue
            state_file = run_dir / "state.json"
            if not state_file.exists():
                continue
            try:
                with open(state_file, "r", encoding="utf-8") as f:
                    d = json.load(f)
                # 统计产物数量与最终报告是否可用
                art_count = 0
                for sr in d.get("stage_results", {}).values():
                    art_count += len(sr.get("artifacts", []))

                fusion_res = d.get("stage_results", {}).get("report_fusion")
                report_available = bool(
                    fusion_res
                    and fusion_res.get("status") in ["approved", "completed"]
                )

                # 提取标题
                title = f"研报任务: {d.get('run_id')}"
                req_input = d.get("input_data") or {}
                if isinstance(req_input, dict) and req_input.get("industry_topic"):
                    title = f"《{req_input['industry_topic']}》行业研究报告"

                runs.append(
                    RunSummary(
                        run_id=d.get("run_id", run_dir.name),
                        project_id=d.get("project_id", "default"),
                        title=title,
                        current_stage=d.get("current_stage", "data_fetch"),
                        status=d.get("status", "pending"),
                        revision=d.get("revision", 1),
                        created_at=d.get("created_at", ""),
                        updated_at=d.get("updated_at", ""),
                        artifact_count=art_count,
                        report_available=report_available,
                    )
                )
            except Exception:
                continue

        # 按创建时间降序排序
        runs.sort(key=lambda r: r.created_at, reverse=True)
        total = len(runs)
        paged_items = runs[offset : offset + limit]
        return RunListResponse(total=total, offset=offset, limit=limit, items=paged_items)

    def save_artifact_file(self, run_id: str, filename: str, content: bytes | str) -> Path:
        run_dir = self.get_run_dir(run_id)
        target = run_dir / "artifacts" / filename
        if isinstance(content, str):
            target.write_text(content, encoding="utf-8")
        else:
            target.write_bytes(content)
        return target

    def get_artifact_path(self, run_id: str, artifact_id: str) -> Path | None:
        run_dir = self.get_run_dir(run_id)
        art_dir = run_dir / "artifacts"
        if not art_dir.exists():
            return None
        # 1. 常见固定产物 ID 快速精确匹配
        id_map = {
            "report_markdown": "report.md",
            "report_html": "report.html",
            "report_pdf": "report.pdf",
            "dataset_json": "dataset.json",
            "interpretation_report_json": "interpretation_report.json",
            "chart_result_json": "chart_result.json",
            "chapter_result_json": "chapter_result.json",
        }
        mapped_name = id_map.get(artifact_id)
        if mapped_name and (art_dir / mapped_name).is_file():
            return art_dir / mapped_name

        # 2. 检查 artifacts 目录下是否有同名文件或匹配 ID
        for p in art_dir.iterdir():
            if p.is_file() and (p.name == artifact_id or p.stem == artifact_id or artifact_id in p.name):
                return p
        # 2. 检查 charts 子目录
        charts_dir = art_dir / "charts"
        if charts_dir.exists():
            clean_id = artifact_id[:-4] if artifact_id.endswith("_svg") else artifact_id
            for p in charts_dir.iterdir():
                if p.is_file() and (p.name == artifact_id or p.stem == artifact_id or p.stem == clean_id or clean_id in p.name):
                    return p
        return None

    def delete_run(self, run_id: str) -> bool:
        run_dir = self.base_dir / run_id
        if run_dir.exists():
            shutil.rmtree(run_dir, ignore_errors=True)
            return True
        return False


storage = StorageManager()
