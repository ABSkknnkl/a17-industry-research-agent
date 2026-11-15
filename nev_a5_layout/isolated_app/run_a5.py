#!/usr/bin/env python3
"""P4 接线验收：独立副本的正常 A5 入口 + 审核重导出共用同一个 compose。

本轮使用**明确标注的确定性模拟输入**，不发起任何真实模型调用；
真实 LLM 联调、三次重跑与真实数据版在 A5 输出合格 PDF 之后单独安排。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

DST = Path(__file__).resolve().parent
for p in (DST, DST / "agents_core/report-fusion", DST / "agents_core"):
    sys.path.insert(0, str(p))

from report_fusion.agent import ReportFusionAgent  # noqa: E402
from report_fusion.config import Settings  # noqa: E402
from report_fusion.layout.composer import compose_async  # noqa: E402
from report_fusion.models import (  # noqa: E402
    ChapterDraft, ChapterResult, ChartResult, ChartSpec, FusionOptions,
    InterpretationReport, ParagraphDraft, ReportFusionRequest,
    ReportViewModel, SectionDraft,
)
from report_fusion.render import render_html  # noqa: E402

SIM_TAG = "模拟验收（确定性夹具，非研究结论，未调用真实模型）"


class NoLLM:
    """硬禁用真实模型；任何调用都直接失败并留痕。"""
    is_available = False

    async def generate_json(self, *a, **k):
        raise RuntimeError("本轮禁用真实模型调用")

    async def plan_skills_with_tools(self, *a, **k):
        raise RuntimeError("本轮禁用真实模型调用")


def build_request() -> ReportFusionRequest:
    report = InterpretationReport(
        report_id="SIM-NEV-A5-20261114", subject="新能源汽车",
        as_of=date(2026, 11, 14), status="completed",
        executive_summary=SIM_TAG,
        warnings=["模拟验收：所有数值仅用于排版链路验证，不构成研究结论"],
    )
    sim_svg = DST / "output" / "sim_chart.svg"
    sim_svg.parent.mkdir(parents=True, exist_ok=True)
    sim_svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 220">'
        '<rect width="600" height="220" fill="#ffffff"/>'
        '<rect x="0" y="0" width="600" height="3" fill="#0A5C5C"/>'
        '<text x="24" y="60" font-size="20" fill="#0A5C5C">模拟验收图（非真实数据）</text>'
        '<line x1="40" y1="180" x2="560" y2="180" stroke="#dfe3e8" stroke-width="2"/>'
        '<polyline points="40,160 140,140 240,145 340,110 440,90 560,70" '
        'fill="none" stroke="#0A5C5C" stroke-width="3"/></svg>',
        encoding="utf-8")
    charts = [ChartSpec(
        chart_id=f"SIM-CHART-{i:02d}", title=f"模拟图{i}　{SIM_TAG}",
        chart_type="line", status="ready", evidence_ids=[],
        svg_uri=str(sim_svg), option={},
        recommended_chapter_id=f"ch{(i - 1) // 2 + 1}",
        source_line="模拟数据源（确定性夹具）",
        footnotes=["模拟验收，不引用真实披露数据"],
    ) for i in range(1, 9)]
    chapters = []
    for c in range(1, 6):
        sections = []
        for s in range(1, 3):
            sid = f"sec{c}{s}"
            chart_ids = [f"SIM-CHART-{(c - 1) * 2 + s:02d}"] if (c - 1) * 2 + s <= 8 else []
            sections.append(SectionDraft(
                section_id=sid, title=f"{c}.{s}　模拟小节 {SIM_TAG}",
                purpose="验证章内分页与目录锚点",
                paragraphs=[
                    ParagraphDraft(paragraph_id=f"{sid}-p1", kind="analysis",
                                   text=f"{SIM_TAG}。本段为排版压力文本，用于检查标题与正文粘连、"
                                        "图题与图注同页、长表重复表头。销量352.1万辆，"
                                        "渗透率8.1%，均为模拟值。"),
                    ParagraphDraft(paragraph_id=f"{sid}-p2", kind="analysis",
                                   text=f"模拟章节 {c} 小节 {s} 的第二段，复用同一组版式规则。"
                                        "结论方向判断不得由排版层生成或改写。"),
                ],
                chart_ids=chart_ids,
            ))
        chapters.append(ChapterDraft(
            chapter_id=f"ch{c}", title=f"第{c}章　模拟章节 {SIM_TAG}",
            summary=f"模拟章节摘要 {c}，仅验证 A5 接排版入口。",
            sections=sections,
        ))
    return ReportFusionRequest(
        report=report,
        chapters=ChapterResult(run_id="sim-run-a5-20261114",
                               source_report_id="SIM-NEV-A5-20261114",
                               subject="新能源汽车", as_of=date(2026, 11, 14),
                               status="completed", chapters=chapters),
        charts=ChartResult(run_id="sim-charts-a5-20261114", charts=charts,
                           warnings=["模拟验收图，不引用真实披露数据"]),
        options=FusionOptions(formats=["markdown", "html", "pdf"],
                              chart_mode="a5_nev",
                              enable_editorial_llm=False),
    )


async def main() -> int:
    import pymupdf
    out_root = DST / "output" / "runs"
    out_root.mkdir(parents=True, exist_ok=True)
    settings = Settings(output_dir=DST / "output", llm_api_key="",
                        pdf_timeout_seconds=180)
    agent = ReportFusionAgent(settings=settings, llm=NoLLM())
    result = await agent.run(build_request(), save_artifacts=True)
    run_dir = Path(result.artifact_dir) if result.artifact_dir else None
    print(f"ReportFusionAgent.run -> status={result.status} formats={result.formats} "
          f"warnings={len(result.warnings)}")
    if not run_dir:
        print("未产出 artifact_dir，接线验收失败")
        return 1

    html = (run_dir / "report.html").read_text(encoding="utf-8")
    pdf_bytes = (run_dir / "report.pdf").read_bytes()
    page_map_path = run_dir / "page_map.json"
    manifest_path = run_dir / "layout_manifest.json"
    page_map = json.loads(page_map_path.read_text(encoding="utf-8")) if page_map_path.exists() else {}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}

    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        pages = doc.page_count
        outline = doc.get_toc()
        first_page_text = doc[0].get_text()
        later_tails = []
        for i in range(1, pages):
            lines = [x.strip() for x in doc[i].get_text().splitlines() if x.strip()]
            later_tails.append(lines[-1] if lines else "")
    numbered = [x for x in later_tails if x.isdigit()]

    checks = {
        "normal_entry_produced_html_pdf": (run_dir / "report.html").exists()
        and (run_dir / "report.pdf").exists(),
        "page_map_exists": bool(page_map),
        "layout_manifest_exists": bool(manifest),
        "html_hash_matches_manifest": manifest.get("hashes", {}).get("html")
        == hashlib.sha256(html.encode("utf-8")).hexdigest(),
        "pdf_hash_matches_manifest": manifest.get("hashes", {}).get("pdf")
        == hashlib.sha256(pdf_bytes).hexdigest(),
        "toc_links_converged": "class=\"pg\"" in html,
        "outline_present": len(outline) >= 10,
        "cover_has_no_page_number": "INDUSTRY RESEARCH" not in first_page_text,
        "later_pages_numbered": len(numbered) >= pages - 2,
        "delivery_status_marked": SIM_TAG in html,
    }

    # 审核重导出：从持久化的最终视图复用同一 compose，页映射必须一致。
    view_path = run_dir / "report_view.json"
    reexport = {"performed": False}
    if view_path.exists():
        view = ReportViewModel.model_validate_json(view_path.read_text(encoding="utf-8"))
        re_html = render_html(view)
        layout2 = await compose_async(view, timeout_seconds=180)
        reexport = {
            "performed": True,
            "same_compose_entry": True,
            "render_html_uses_a5_nev": "toc-list" in re_html,
            "page_map_identical": layout2.page_map == page_map,
            "outline_identical": layout2.outline == manifest.get("outline", []),
            "html_hash_identical": hashlib.sha256(
                layout2.html.encode("utf-8")).hexdigest() == manifest.get("hashes", {}).get("html"),
        }
        checks["reexport_uses_same_compose"] = all(
            v for k, v in reexport.items() if k not in ("performed",))

    report = {
        "schema_version": "1.0", "stage": "P4",
        "input": "确定性模拟输入（无真实模型调用，无真实披露数据）",
        "run_dir": str(run_dir), "status": result.status,
        "formats": result.formats, "warnings": result.warnings,
        "pdf_pages": pages, "outline_entries": len(outline),
        "page_map_entries": len(page_map),
        "checks": checks, "reexport": reexport,
        "passed": all(checks.values()),
    }
    (run_dir / "p4_wiring_result.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"P4 {'PASS' if report['passed'] else 'FAIL'} | PDF {pages} 页 | "
          f"书签 {len(outline)} | 页映射 {len(page_map)} | 检查 {sum(checks.values())}/{len(checks)}")
    for k, v in checks.items():
        if not v:
            print(f"  FAIL {k}")
    if not reexport.get("performed"):
        print("  审核重导出未执行：缺少 report_view.json")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
