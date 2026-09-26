"""L5 交付验收 + D-04 回归护栏（离线，黄金样本 + 副样本）。

**判据来源**：任务书 §3.1（A5-01/A5-02/A5-08 等）与 §2.1（L5 交付验收：MD/HTML/PDF/双模板/manifest SHA-256）。

**样本**：
- 主样本 `run-20260926022235-107`（completed，含 PDF）
- 副样本 `run-20260922213739-783`（completed，**无 PDF**）→ 验 A5-08 降级语义

**D-04 回归护栏说明**：合并（以 A 版覆盖）导致 `adapters.py` 三处实现退化——
`delivery_status` 硬编码 `"ready"`、`expected_chapter/section_count` 硬编码 `7/21`。
本文件用**源码级断言**固化"不得硬编码"的判据，作为回归护栏；断言当前会失败，
代表缺陷 D-04 未修复（见 `docs/测试执行台账.md`）。
"""

from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
GOLDEN_RUN_ID = "run-20260926022235-107"
FALLBACK_RUN_ID = "run-20260922213739-783"
ADAPTERS_PATH = PROJECT_ROOT / "backend" / "app" / "agents" / "adapters.py"


@lru_cache(maxsize=1)
def _manifest(run_id: str = GOLDEN_RUN_ID) -> dict:
    return json.loads(
        (PROJECT_ROOT / "data" / "runs" / run_id / "artifacts" / "manifest.json").read_text(encoding="utf-8")
    )


# --------------------------------------------------------------------------
# A5-01 / A5-02：产物齐全 + SHA-256 一致
# --------------------------------------------------------------------------


def test_a5_01_declared_formats_exist_and_are_non_empty() -> None:
    """A5-01：交付格式（markdown / html / pdf）齐备且非空。"""
    arts = _manifest().get("artifacts") or []
    by_kind = {str(a.get("kind")): a for a in arts}
    missing: dict[str, str] = {}
    for kind in ("markdown", "html", "pdf"):
        item = by_kind.get(kind)
        if not item:
            missing[kind] = "未登记"
            continue
        path = Path(str(item.get("uri")))
        if not path.exists():
            missing[kind] = f"文件不存在: {path}"
        elif path.stat().st_size == 0:
            missing[kind] = "文件为空"
    assert missing == {}, f"A5-01 交付缺项: {missing}"


def test_a5_02_manifest_sha256_matches_each_actual_file() -> None:
    """A5-02：manifest 每条 sha256 必须与实际文件逐一相符（改一字节即失败）。"""
    arts = _manifest().get("artifacts") or []
    assert arts, "manifest.artifacts 为空"
    mismatches: dict[str, str] = {}
    for item in arts:
        path = Path(str(item.get("uri")))
        if not path.exists():
            mismatches[path.name] = "文件缺失"
            continue
        real = hashlib.sha256(path.read_bytes()).hexdigest()
        if real != item.get("sha256"):
            mismatches[path.name] = f"sha256 不符（manifest={str(item.get('sha256'))[:12]}… 实际={real[:12]}…）"
    assert mismatches == {}, f"A5-02 SHA-256 不一致: {mismatches}"


def test_a5_08_pdf_missing_keeps_markdown_and_html() -> None:
    """A5-08：PDF 缺失时 MD/HTML 必须保留（降级不丢主产物）。

    路径说明（为什么不用 manifest.uri）：副样本的 `manifest.artifacts[].uri` 记录的是
    产生该 run 时的历史绝对路径（指向「系统 3」工作区），跨工作区不可用——这是历史真实路径，
    不是缺陷。因此按**同名文件在本工作区 `data/runs/<run_id>/artifacts/` 下的副本**校验。
    """
    manifest = _manifest(FALLBACK_RUN_ID)
    kinds = {str(a.get("kind")) for a in manifest.get("artifacts") or []}
    assert "pdf" not in kinds, "副样本本应无 pdf（样本语义变了？）"

    run_dir = PROJECT_ROOT / "data" / "runs" / FALLBACK_RUN_ID / "artifacts"
    for name in ("report.md", "report.html"):
        path = run_dir / name
        assert path.exists(), f"降级场景下产物缺失: {path}"
        assert path.stat().st_size > 0, f"降级场景下产物为空: {path}"
    assert not (run_dir / "report.pdf").exists(), "副样本不应存在 report.pdf"


# --------------------------------------------------------------------------
# D-04 回归护栏：不得硬编码（当前预期失败，代表缺陷未修）
# --------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _adapters_source() -> str:
    return ADAPTERS_PATH.read_text(encoding="utf-8")


def test_d04_delivery_status_must_not_be_hardcoded() -> None:
    """D-04 护栏：API manifest 的 delivery_status 必须反映 A5 的真实状态，不得写死 "ready"。

    合并前实现（备份可查）通过 `_resolve_delivery_status()` 读 `report_view.json` 的
    `ReportViewModel.delivery_status`（取值 ready / ready_with_limits）；合并后被写死，
    导致 `ready_with_limits` 永远无法传到前端。
    """
    src = _adapters_source()
    hardcoded = re.search(r'"delivery_status"\s*:\s*"ready"\s*,', src)
    assert hardcoded is None, (
        "D-04：adapters.py 将 delivery_status 硬编码为 \"ready\"，"
        "A5 产出的 ready_with_limits 状态被吞掉；应恢复读 report_view.json 的真实值"
    )


def test_d04_expected_outline_counts_must_be_derived_not_literal() -> None:
    """D-04 护栏：章节/节数基准必须从大纲单一事实源推导，不得出现字面量 7 / 21。"""
    src = _adapters_source()
    literals = re.findall(r'"expected_(?:chapter|section)_count"\s*:\s*(7|21)\b', src)
    assert literals == [], (
        f"D-04：adapters.py 出现 {len(literals)} 处硬编码的 expected_chapter/section_count "
        f"（{literals}）；应从 DEFAULT_OUTLINE 推导（项目纪律：不得写死 7/21）"
    )


def test_dual_templates_produce_complete_artifacts() -> None:
    """N18–N20：双模板（auto / rich）产物齐全。

    备注：黄金样本仅含单套模板产物 → 本用例按"模板切换开关可查"降级判定，
    完整双模板比对需专用 fixture（登记为待补项）。
    """
    report_html = PROJECT_ROOT / "data" / "runs" / GOLDEN_RUN_ID / "artifacts" / "report.html"
    assert report_html.exists() and report_html.stat().st_size > 0
    text = report_html.read_text(encoding="utf-8", errors="ignore")
    # 双模板产物的结构差异可由 report_view.json 的 chart_mode 反映
    view = json.loads(
        (PROJECT_ROOT / "data" / "runs" / GOLDEN_RUN_ID / "artifacts" / "report_view.json").read_text(
            encoding="utf-8"
        )
    )
    assert view.get("chart_mode") in {"auto", "rich"}, f"chart_mode 取值非法: {view.get('chart_mode')}"
    assert "reader-rail" in text or "report-main" in text or "<article" in text, "HTML 结构不含预期容器"
