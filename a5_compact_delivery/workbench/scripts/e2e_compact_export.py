"""工作台紧凑包端到端：真实 Chromium 渲染，验证权限、ZIP 内容、PDF 与旧路线。

覆盖方案第 3 步验收表：正式 / 受限草稿 / 跨行业 / 编辑后新版本 / 重跑新版本 /
拒绝场景 / 渲染中修改 / 产物与旧路线 / 失败与并发。

运行（从 a17-industry-research-agent/ 或任意目录均可）：
    env -u PYTHONPATH /Users/Zhuanz1/miniconda3/bin/python3 \
      ../a5_compact_delivery/workbench/scripts/e2e_compact_export.py \
      > ../a5_compact_delivery/workbench/reports/e2e_run.log 2>&1
"""
from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import shutil
import sys
import time
import zipfile
from datetime import date  # noqa: F401  (与单测夹具保持同款依赖)
from pathlib import Path
from unittest.mock import patch

import fitz
from fastapi import FastAPI
from fastapi.testclient import TestClient

APP = Path("/Users/Zhuanz1/Downloads/同花顺赛题-T3交接/a17-industry-research-agent")
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP / "backend"))
sys.path.insert(0, str(APP / "agents_core" / "report-fusion"))

from backend.app.api.routes import router  # noqa: E402
from backend.app.core.storage import storage  # noqa: E402
from backend.app.schemas.workflow import ArtifactRef, StageResult, WorkflowState  # noqa: E402
from report_fusion.render import EVIDENCE_CSV_HEADER, restore_csv_text  # noqa: E402

ROOT = Path("/Users/Zhuanz1/Downloads/同花顺赛题-T3交接/a5_compact_delivery/workbench")
OUT = ROOT / "artifacts"
OUT.mkdir(parents=True, exist_ok=True)

NEV_VIEW = APP / "output/nev_template_quality/verified_front_reviewed/a5/runs/report-20261115093420-014bbb5b/report_view.json"
BAIJIU_VIEW = ROOT.parent / "baseline" / "baijiu_fixture_rich.json"
EXPECTED_MEMBERS = ["evidence_index.csv", "report.html", "report.md", "report.pdf"]


def make_run(
    tmp: Path,
    run_id: str,
    view_path: Path,
    *,
    mode: str,
    revision: int = 3,
    extra_view: dict | None = None,
    extra_data: dict | None = None,
    run_status: str = "completed",
    fusion_status: str = "approved",
    with_pdf: bool = True,
    artifacts: list[ArtifactRef] | None = None,
):
    root = storage.get_run_dir(run_id)
    art = root / "artifacts"
    art.mkdir(parents=True, exist_ok=True)
    if with_pdf:
        (art / "report.pdf").write_bytes(b"%PDF-current-placeholder")

    raw = json.loads(view_path.read_text(encoding="utf-8"))
    raw["delivery_status"] = "ready" if mode == "formal" else "ready_with_limits"
    raw.update(extra_view or {})
    (art / "report_view.json").write_text(
        json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    data = {
        "report_id": raw["report_id"],
        "built_at_revision": revision,
        "quality": {"passed": True} if mode == "formal" else {"passed": False},
        "agent_status": "completed" if mode == "formal" else "partial",
        "delivery_status": raw["delivery_status"],
    }
    if mode == "draft":
        data.update(hard_blocked=True, draft_available=True, draft_sanitized=True)
    data.update(extra_data or {})

    pdf_ref = ArtifactRef(
        artifact_id="report_pdf", kind="report_pdf",
        uri=str((art / "report.pdf").resolve()), revision=revision,
    )
    state = WorkflowState(
        project_id="p", run_id=run_id, status=run_status,
        current_stage="report_fusion", revision=revision,
        created_at="2026-11-15", updated_at="2026-11-15",
        stage_results={"report_fusion": StageResult(
            stage="report_fusion", status=fusion_status, revision=revision,
            data=data, artifacts=artifacts if artifacts is not None else [pdf_ref],
        )},
    )
    storage.save_state(state)
    return root, art, raw


def snapshot_tree(run_dir: Path) -> dict[str, str]:
    """制包前后逐文件 SHA-256 对账：state.json / 修订快照 / 产物清单全在里面。"""
    return {
        str(p.relative_to(run_dir)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(run_dir.rglob("*")) if p.is_file()
    }


def check_zip(data: bytes, view_raw: dict, label: str, must_contain: str | None = None) -> dict:
    zf = zipfile.ZipFile(io.BytesIO(data))
    names = sorted(zf.namelist())
    assert names == EXPECTED_MEMBERS, names
    md = zf.read("report.md").decode("utf-8")
    html = zf.read("report.html").decode("utf-8")
    csv_bytes = zf.read("evidence_index.csv")
    pdf_bytes = zf.read("report.pdf")

    # 相对附件链接：MD 与 HTML 都指向包内 CSV，不带绝对路径/外部地址。
    assert "[下载完整证据索引](evidence_index.csv)" in md
    assert "evidence_index.csv" in html and "source-number-cloud" in html
    assert "evidence_index.csv" in html and not 'href="/' in html
    if must_contain:
        assert must_contain in md and must_contain in html, must_contain

    # CSV：固定 14 列 + (number, record_id) 与视图目录全量逐行映射。
    rows = list(csv.reader(io.StringIO(csv_bytes.decode("utf-8-sig"), newline="")))
    assert list(rows[0]) == list(EVIDENCE_CSV_HEADER), rows[0]
    catalog = view_raw["evidence_catalog"]
    assert len(rows) - 1 == len(catalog) == 223, (len(rows) - 1, len(catalog))
    actual = [(restore_csv_text(r[0]), restore_csv_text(r[1])) for r in rows[1:]]
    expected = [(str(c["number"]), c["record_id"]) for c in catalog]
    assert actual == expected, "CSV (number, record_id) 与视图目录不一致"
    # 已脱敏的紧凑版不在正文重新铺开逐条证据；明细只在 CSV。
    assert catalog[0]["record_id"] not in md

    # 真实 Chromium PDF：附录二存在，且内部跳转命中附录页。
    assert pdf_bytes.startswith(b"%PDF")
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    appendix = [i + 1 for i, p in enumerate(doc) if "附录二：原始数据穿透与事实证据索引" in p.get_text()]
    links = [l for p in doc for l in p.get_links() if l.get("kind") == 4]
    evidence = [l for l in links if str(l.get("nameddest") or "").startswith(("source-", "src-"))]
    hits = sum(1 for l in evidence if l.get("page", -1) + 1 in set(appendix))
    pages = doc.page_count
    doc.close()
    assert appendix, "PDF 缺少附录二"
    assert evidence and hits > 0, (len(evidence), hits)

    return {
        "label": label,
        "bytes": len(data),
        "members": names,
        "csv_rows": len(rows) - 1,
        "csv_mapping_full_match": True,
        "pdf_pages": pages,
        "appendix_pages": appendix,
        "pdf_evidence_links": len(evidence),
        "pdf_links_hit_appendix": hits,
        "sha256": hashlib.sha256(data).hexdigest()[:16],
    }


def fake_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("report.md", "# fake")
    return buf.getvalue()


def post(client, run_id: str, mode: str = "formal", revision: int = 3):
    return client.post(
        f"/api/v1/runs/{run_id}/exports/compact",
        json={"mode": mode, "expected_revision": revision},
    )


def concurrency_case(app: FastAPI, run_id: str, revision: int) -> dict:
    """同一事件循环内两路真实并发 POST：第一路占住渲染位，第二路必须 429。"""
    import httpx

    from backend.app.engine.state_machine import engine

    async def run() -> tuple[int, int]:
        # 该案例单独起事件循环，先重置进程内 run 锁字典，避免跨循环绑定。
        if hasattr(engine, "_run_locks"):
            engine._run_locks = {}
        started = asyncio.Event()
        release = asyncio.Event()

        async def blocking(view, mode, *, pdf_timeout_seconds=None):
            started.set()
            await asyncio.wait_for(release.wait(), timeout=15)
            return fake_zip()

        with patch("report_fusion.export_view.build_package_bytes", blocking):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as ac:
                url = f"/api/v1/runs/{run_id}/exports/compact"
                body = {"mode": "formal", "expected_revision": revision}
                first = asyncio.create_task(ac.post(url, json=body))
                await asyncio.wait_for(started.wait(), timeout=10)
                second = await ac.post(url, json=body)
                release.set()
                first_resp = await first
        return first_resp.status_code, second.status_code

    a, b = asyncio.run(run())
    assert a == 200 and b == 429, (a, b)
    return {"first_status": a, "second_status": b, "busy_hint": "紧凑交付包正在生成，请稍后手动重试"}


def main() -> int:
    import tempfile

    app = FastAPI()
    app.include_router(router)
    results, rejections, races, failures = [], [], [], []
    with tempfile.TemporaryDirectory(prefix="a5_workbench_e2e_") as td:
        storage.base_dir = Path(td)
        client = TestClient(app)

        # ── 1. 真实 Chromium 制包：正式 / 受限草稿 / 跨行业 ──────────────
        scenarios = [
            ("nev_formal", NEV_VIEW, "formal", 3, None),
            ("nev_draft", NEV_VIEW, "draft", 3, None),
            ("baijiu_formal", BAIJIU_VIEW, "formal", 3, None),
            ("edited_revision", NEV_VIEW, "formal", 4,
             {"quality": {"ignored": True}, "quality_notice": "人工编辑后重新融合"}),
            ("rerun_new_revision", NEV_VIEW, "formal", 5,
             {"title": "重跑后新版本标题"}),
        ]
        for label, view, mode, revision, extra_view in scenarios:
            run_id = f"run-{label}"
            root, art, raw = make_run(Path(td), run_id, view, mode=mode,
                                      revision=revision, extra_view=extra_view)
            before = snapshot_tree(root)
            started = time.monotonic()
            resp = client.post(
                f"/api/v1/runs/{run_id}/exports/compact",
                json={"mode": mode, "expected_revision": revision},
            )
            elapsed = round(time.monotonic() - started, 2)
            print(f"[{label}] status={resp.status_code} elapsed={elapsed}s bytes={len(resp.content)}")
            assert resp.status_code == 200, resp.text[:300]
            expected_name = ("draft-" if mode == "draft" else "") + f"report-compact-r{revision}.zip"
            assert f'filename="{expected_name}"' in resp.headers["content-disposition"]
            assert resp.headers["content-type"].startswith("application/zip")
            assert resp.headers["cache-control"] == "private, no-store"

            (OUT / f"{label}.zip").write_bytes(resp.content)
            must = "重跑后新版本标题" if label == "rerun_new_revision" else None
            info = check_zip(resp.content, raw, label, must_contain=must)
            info.update({
                "mode": mode, "revision": revision, "elapsed_seconds": elapsed,
                "chart_mode": raw.get("chart_mode"),
                "report_id": raw.get("report_id"),
                "headers": {
                    "content_disposition": resp.headers.get("content-disposition"),
                    "cache_control": resp.headers.get("cache-control"),
                    "x_report_mode": resp.headers.get("x-report-mode"),
                    "x_report_release_mode": resp.headers.get("x-report-release-mode"),
                },
            })
            results.append(info)

            # 产物与旧路线：制包前后逐文件字节完全一致（state.json / revisions / manifest / artifacts）。
            after = snapshot_tree(root)
            assert before == after, {
                k: (before.get(k), after.get(k))
                for k in set(before) | set(after) if before.get(k) != after.get(k)
            }
            info["state_unchanged"] = True
            info["artifacts_files"] = sorted(p.name for p in art.iterdir())

            # 旧 GET 路线：正式报告默认 formal 可下；受限草稿必须显式 ?mode=draft。
            if mode == "draft":
                assert client.get(f"/api/v1/runs/{run_id}/artifacts/report_pdf?mode=draft").status_code == 200
                assert client.get(f"/api/v1/runs/{run_id}/artifacts/report_pdf").status_code == 409
            else:
                assert client.get(f"/api/v1/runs/{run_id}/artifacts/report_pdf").status_code == 200
            info["old_get_downloadable"] = True

            # ZIP / CSV 不落盘：按固定 ID、规范 ID、文件名查找均无结果。
            for aid in ("report_compact_zip", "evidence_index_csv", "report-compact-r3.zip",
                        "evidence_index.csv", "draft-report-compact-r3.zip", expected_name):
                assert client.get(f"/api/v1/runs/{run_id}/artifacts/{aid}").status_code == 404, aid
                found = storage.get_artifact_path(run_id, aid)
                assert found is None or not found.exists(), (aid, found)
            info["no_registered_artifacts"] = True

        # ── 2. 拒绝场景 ────────────────────────────────────────────────
        def reject(case, run_id, status, *, mode="formal", revision=3,
                   skip_setup=False, **kwargs):
            if not skip_setup:
                make_run(Path(td), run_id, NEV_VIEW, mode=kwargs.pop("view_mode", "formal"),
                         revision=kwargs.pop("run_revision", 3), **kwargs)
            r = post(client, run_id, mode=mode, revision=revision)
            print(f"[reject] {case} -> {r.status_code}")
            assert r.status_code == status, (case, r.status_code, r.text[:200])
            rejections.append({"case": case, "status": r.status_code,
                               "detail": r.json().get("detail") if r.status_code != 200 else None})

        reject("ready_with_limits 请求正式包", "run-limited-formal", 409,
               view_mode="draft")
        reject("草稿但无明确授权", "run-draft-no-flag", 409, mode="draft",
               view_mode="draft", extra_data={"draft_available": False})
        reject("版本已更新（expected_revision 落后）", "run-stale", 409, revision=2)
        reject("当前 PDF 不可用", "run-no-pdf", 409, with_pdf=False)
        reject("exports_stale 需重导出", "run-exports-stale", 409,
               extra_data={"exports_stale": True})
        reject("needs_reexport 需重导出", "run-needs-reexport", 409,
               extra_data={"needs_reexport": True})
        reject("delivery_blocked", "run-delivery-blocked", 409,
               extra_data={"delivery_blocked": True})
        reject("视图与状态交付级别不一致", "run-view-mismatch", 409,
               extra_data={"delivery_status": "ready_with_limits"})
        reject("取消状态禁止出包", "run-cancelled", 409, run_status="cancelled")

        md_ref = ArtifactRef(artifact_id="report_markdown", kind="report_markdown",
                             uri=str(Path(td) / "run-edit-preview" / "artifacts" / "report.md"),
                             revision=3)
        reject("只有 MD/HTML 的编辑预览", "run-edit-preview", 409,
               artifacts=[md_ref], fusion_status="waiting_review",
               extra_data={"quality_notice": "已编辑"})
        reject("任务不存在", "run-never", 404, skip_setup=True)

        for payload in ({"mode": None}, {"mode": "bogus"}, {"expected_revision": "3"},
                        {"expected_revision": None}, {"expected_revision": -1}):
            body = {"mode": "formal", "expected_revision": 3, **payload}
            r = client.post("/api/v1/runs/any/exports/compact", json=body)
            assert r.status_code == 422, (payload, r.status_code)
            rejections.append({"case": f"参数非法 {payload}", "status": 422, "detail": None})
        assert client.post("/api/v1/runs/any/exports/compact", json={}).status_code == 422
        rejections.append({"case": "请求体缺失", "status": 422, "detail": None})

        # ── 3. 渲染中修改：可控等待点放行后，回锁复核必须丢弃内存 ZIP ──
        def race(case, mutate, expected=(409,)):
            run_id = f"run-race-{len(races)}"
            root, art, _ = make_run(Path(td), run_id, NEV_VIEW, mode="formal")

            async def build_then_mutate(view, mode, *, pdf_timeout_seconds=None):
                mutate(root, art, run_id)
                return fake_zip()

            with patch("report_fusion.export_view.build_package_bytes", build_then_mutate):
                r = post(client, run_id)
            assert r.status_code in expected, (case, r.status_code, r.text[:200])
            races.append({"case": case, "status": r.status_code})
            print(f"[race] {case} -> {r.status_code}")

        def change_revision(root, art, run_id):
            state = storage.load_state(run_id)
            state.revision = 4
            storage.save_state(state)

        def change_view_bytes(root, art, run_id):
            p = art / "report_view.json"
            raw = json.loads(p.read_text(encoding="utf-8"))
            raw["title"] = "渲染期间被改写"
            p.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

        def change_eligibility(root, art, run_id):
            state = storage.load_state(run_id)
            state.stage_results["report_fusion"].data["delivery_blocked"] = True
            storage.save_state(state)

        def delete_run(root, art, run_id):
            shutil.rmtree(root)

        race("渲染中构建代次变更", change_revision)
        race("渲染中同版本视图字节变化", change_view_bytes)
        race("渲染中下载资格失效", change_eligibility)
        race("渲染中任务删除", delete_run, expected=(404,))

        # ── 4. 失败可重试 / 超时 / 并发忙碌 ─────────────────────────────
        run_id = "run-retry"
        make_run(Path(td), run_id, NEV_VIEW, mode="formal")
        calls = []

        async def broken_then_ok(view, mode, *, pdf_timeout_seconds=None):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("chromium down")
            return fake_zip()

        with patch("report_fusion.export_view.build_package_bytes", broken_then_ok):
            first = post(client, run_id)
            second = post(client, run_id)
        assert first.status_code == 500 and second.status_code == 200, (first.status_code, second.status_code)
        failures.append({"case": "渲染失败 500 后可重试成功", "first": 500, "retry": 200})

        async def timed_out(view, mode, *, pdf_timeout_seconds=None):
            raise asyncio.TimeoutError()

        with patch("report_fusion.export_view.build_package_bytes", timed_out):
            r = post(client, run_id)
        assert r.status_code == 504, r.status_code
        failures.append({"case": "PDF 渲染超时", "status": 504})

        make_run(Path(td), "run-concurrent", NEV_VIEW, mode="formal")
        busy = concurrency_case(app, "run-concurrent", 3)
        failures.append({"case": "并发点击", **busy})

        # ── 5. 汇总 ────────────────────────────────────────────────────
        summary = {
            "generated_at": "2026-11-15",
            "renderer": "真实 Chromium（Playwright，PDF 内链接可解析）",
            "scenarios": results,
            "rejections": rejections,
            "render_races": races,
            "failures_and_concurrency": failures,
            "counts": {
                "scenarios": len(results), "rejections": len(rejections),
                "races": len(races), "failure_cases": len(failures),
            },
        }
        (ROOT / "reports" / "e2e_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(summary["counts"], ensure_ascii=False))
        print("E2E OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
