"""从已选定的 report_view.json 打包一份离线交付 ZIP。

这是独立于线上工作流的交付命令：只有本模块解析 A5_SOURCE_INDEX_MODE。
线上生成、编辑预览、审批重导出继续走现有 full 路径，契约不受影响。

用法（从 a17-industry-research-agent/ 执行）：
    A5_SOURCE_INDEX_MODE=compact \
    PYTHONPATH="$PWD/agents_core/report-fusion" \
    python3 -m report_fusion.export_view \
      --view /abs/report_view.json --output /abs/report-compact.zip

--output 必须是尚不存在的路径；失败时命令退出非零，不会覆盖任何已有交付包。
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

from report_fusion.models import ReportViewModel
from report_fusion.pdf import render_pdf
from report_fusion.render import (
    EVIDENCE_CSV_HEADER,
    EVIDENCE_CSV_NAME,
    normalize_source_index_mode,
    render_evidence_csv,
    render_html,
    render_markdown,
    restore_csv_text,
)

EXPECTED_FILES_FULL = ("report.md", "report.html", "report.pdf")
EXPECTED_FILES_COMPACT = (*EXPECTED_FILES_FULL, EVIDENCE_CSV_NAME)


def load_view(path: Path) -> ReportViewModel:
    """一次读取并校验视图；不修改任何字段、顺序或取值。"""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return ReportViewModel.model_validate(raw)


async def _render_all(
    view: ReportViewModel, mode: str, pdf_timeout_seconds: float | None = None
) -> dict[str, bytes]:
    md = render_markdown(view, source_index_mode=mode).encode("utf-8")
    html = render_html(view, source_index_mode=mode).encode("utf-8")
    if not md.strip() or not html.strip():
        raise ValueError("Markdown 或 HTML 渲染结果为空")
    pdf_kwargs = {"timeout_seconds": pdf_timeout_seconds} if pdf_timeout_seconds is not None else {}
    pdf = await render_pdf(html.decode("utf-8"), **pdf_kwargs)
    if not pdf.startswith(b"%PDF"):
        raise ValueError("PDF 渲染结果不是合法 PDF")
    files: dict[str, bytes] = {
        "report.md": md,
        "report.html": html,
        "report.pdf": pdf,
    }
    if mode == "compact":
        files[EVIDENCE_CSV_NAME] = render_evidence_csv(view)
    return files


def _verify_csv(data: bytes, view: ReportViewModel) -> None:
    """回读 CSV，逐行对账 number / record_id / value_json。"""
    rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig"), newline="")))
    if not rows or list(rows[0]) != list(EVIDENCE_CSV_HEADER):
        raise ValueError("CSV 表头与固定 14 列契约不一致")
    if len(rows) - 1 != len(view.evidence_catalog):
        raise ValueError(
            f"CSV 行数 {len(rows) - 1} 与证据目录 {len(view.evidence_catalog)} 不一致"
        )
    for line_no, (row, source) in enumerate(zip(rows[1:], view.evidence_catalog), start=2):
        if len(row) != len(EVIDENCE_CSV_HEADER):
            raise ValueError(f"CSV 第 {line_no} 行列数异常")
        if restore_csv_text(row[0]) != str(source.number):
            raise ValueError(f"CSV 第 {line_no} 行 number 与目录不一致")
        if restore_csv_text(row[1]) != source.record_id:
            raise ValueError(f"CSV 第 {line_no} 行 record_id 与目录不一致")
        try:
            json.loads(row[6])
        except (ValueError, TypeError) as exc:
            raise ValueError(f"CSV 第 {line_no} 行 value_json 不可解析: {exc}") from exc


def _verify_zip_bytes(data: bytes, files: dict[str, bytes], mode: str, view: ReportViewModel) -> None:
    """解压回读全部文件并逐字节对账，再单独校验 CSV（内存版本）。"""
    expected = EXPECTED_FILES_COMPACT if mode == "compact" else EXPECTED_FILES_FULL
    with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
        names = sorted(zf.namelist())
        if names != sorted(expected):
            raise ValueError(f"ZIP 内容不符：{names}，预期 {sorted(expected)}")
        for name in expected:
            if zf.read(name) != files[name]:
                raise ValueError(f"ZIP 内 {name} 与渲染结果字节不一致")
        if mode == "compact":
            _verify_csv(zf.read(EVIDENCE_CSV_NAME), view)


def _verify_zip(path: Path, files: dict[str, bytes], mode: str, view: ReportViewModel) -> None:
    """落盘后再回读一次，确认原子发布没有损坏字节。"""
    _verify_zip_bytes(path.read_bytes(), files, mode, view)


async def _build_package_bytes(
    view: ReportViewModel, mode: str, pdf_timeout_seconds: float | None = None
) -> tuple[bytes, dict[str, bytes]]:
    files = await _render_all(view, mode, pdf_timeout_seconds)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in (EXPECTED_FILES_COMPACT if mode == "compact" else EXPECTED_FILES_FULL):
            zf.writestr(name, files[name])
    data = buf.getvalue()
    _verify_zip_bytes(data, files, mode, view)
    return data, files


async def build_package_bytes(
    view: ReportViewModel, mode: str, *, pdf_timeout_seconds: float | None = None
) -> bytes:
    """异步制包：供 FastAPI 端点直接返回内存 ZIP；CLI 与端点共用同一条验包路径。"""
    mode = normalize_source_index_mode(mode)
    data, _ = await _build_package_bytes(view, mode, pdf_timeout_seconds)
    return data


def build_package(view_path: Path, output: Path, mode: str) -> dict:
    """生成、校验、原子发布；output 必须不存在。CLI 的同步边界只在这里调用 asyncio.run。"""
    if output.exists():
        raise FileExistsError(f"输出路径已存在，请换一个新路径重试：{output}")
    if not output.parent.is_dir():
        raise FileNotFoundError(f"输出目录不存在：{output.parent}")

    view = load_view(view_path)
    data, files = asyncio.run(_build_package_bytes(view, mode))

    # 先在临时目录成包并完整校验，再原子发布；任何一步失败都不会留下半包。
    with tempfile.TemporaryDirectory(prefix="a5_export_") as tmp:
        tmp_zip = Path(tmp) / "package.zip"
        tmp_zip.write_bytes(data)
        _verify_zip(tmp_zip, files, mode, view)
        os.replace(str(tmp_zip), str(output))

    return {
        "view": str(view_path.resolve()),
        "output": str(output.resolve()),
        "mode": mode,
        "report_id": view.report_id,
        "subject": view.subject,
        "chart_mode": view.chart_mode,
        "delivery_status": view.delivery_status,
        "catalog_size": len(view.evidence_catalog),
        "files": {name: len(data) for name, data in files.items()},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="打包一份 A5 离线交付 ZIP")
    parser.add_argument("--view", required=True, type=Path, help="待交付版本的 report_view.json")
    parser.add_argument("--output", required=True, type=Path, help="尚不存在的目标 ZIP 路径")
    args = parser.parse_args(argv)

    mode = normalize_source_index_mode(os.getenv("A5_SOURCE_INDEX_MODE"))
    try:
        summary = build_package(args.view, args.output, mode)
    except Exception as exc:
        print(f"导出失败（{type(exc).__name__}）：{exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
