"""P3 · 图表、表格与证据注册。

方案 §3-P3：每项记录 id/number/kind/title/source/note/unit/coverage/
provenance/data_ref/placement_section_id；按块的最终阅读顺序编号，图、表
各自连续；正文引用、图表目录和书签只认注册表 ID。provenance 至少记录 A3
run、图 ID、资产哈希、是否已验收、是否在 A3 中适配编译及转换说明。
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0"

PERIOD_RE = re.compile(r"[（(](\d{4}-\d{2}-\d{2})至(\d{4}-\d{2}-\d{2})[）)]")
MOTHER_FIG_RE = re.compile(r"^图\s*([A-Z]?\d+)")
MOTHER_TAB_RE = re.compile(r"^表\s*([A-Z]?\d+)")
KNOWN_ORIGINS = {"accepted_a3_chart", "a3_compiled", "a3_standalone_chain_panorama"}


def sha256_file(path: Path) -> str | None:
    if not path or not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _norm(title: str) -> str:
    return re.sub(r"[\s　]+", "", title or "")


def _months_between(start: str, end: str) -> int:
    y1, m1 = int(start[:4]), int(start[5:7])
    y2, m2 = int(end[:4]), int(end[5:7])
    return (y2 - y1) * 12 + (m2 - m1) + 1


@dataclass
class CoverageVerdict:
    allowed: bool
    coverage_warning: bool
    code: str
    detail: str
    missing_points: list[str] = field(default_factory=list)


@dataclass
class RegistryEntry:
    id: str
    number: str
    kind: str                      # figure | table
    title: str
    source: str = ""
    note: str = ""
    unit: str | None = None
    coverage: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    data_ref: str | None = None
    placement_section_id: str | None = None
    include_in_outline: bool = False
    mother_number: str | None = None
    reading_order_number: str | None = None
    publish_allowed: bool = True
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChartRegistry:
    schema_version: str = SCHEMA_VERSION
    theme: str = "a5_nev"
    content_sha256: str = ""
    entries: list[RegistryEntry] = field(default_factory=list)
    outline: list[dict[str, Any]] = field(default_factory=list)
    outline_only_count: int = 0
    # 冻结夹具必须复现母本语义编号（表4/表1/表2/…）；生产新报告才按阅读顺序编号。
    numbering_mode: str = "preserve_mother"
    blocking_gaps: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @property
    def figures(self) -> list[RegistryEntry]:
        return [e for e in self.entries if e.kind == "figure"]

    @property
    def tables(self) -> list[RegistryEntry]:
        return [e for e in self.entries if e.kind == "table"]

    @property
    def publish_blockers(self) -> list[dict[str, Any]]:
        out = []
        for e in self.entries:
            for code in e.blockers:
                out.append({"entry_id": e.id, "number": e.number, "code": code})
        return out

    def validate(self) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        ids = [e.id for e in self.entries]
        if len(ids) != len(set(ids)):
            issues.append({"code": "DUPLICATE_REGISTRY_ID", "severity": "blocker",
                           "detail": "注册表 ID 重复"})
        for kind, prefix in (("figure", "图"), ("table", "表")):
            group = [e for e in self.entries if e.kind == kind]
            if self.numbering_mode == "reading_order":
                expected = [f"{prefix}{i}" for i in range(1, len(group) + 1)]
            else:
                expected = [f"{prefix}{e.mother_number}" if e.mother_number else None
                            for e in group]
            actual = [e.number for e in group]
            if actual != expected:
                issues.append({"code": "NUMBERING_MISMATCH", "severity": "blocker",
                               "detail": f"{kind} 编号({self.numbering_mode}) "
                                         f"不符: {actual} != {expected}"})
        for e in self.entries:
            if not e.title:
                issues.append({"code": "TITLE_MISSING", "severity": "blocker",
                               "entry_id": e.id, "detail": "注册表条目缺标题"})
            if not e.provenance:
                issues.append({"code": "PROVENANCE_MISSING", "severity": "blocker",
                               "entry_id": e.id, "detail": "注册表条目缺 provenance"})
        outline_count = sum(1 for e in self.entries if e.include_in_outline)
        if self.outline and outline_count != len(self.outline):
            issues.append({"code": "OUTLINE_COUNT_MISMATCH", "severity": "blocker",
                           "detail": f"include_in_outline 条目 {outline_count} "
                                     f"!= 书签总数 {len(self.outline)}"})
        for e in self.entries:
            if e.include_in_outline and not e.title:
                issues.append({"code": "OUTLINE_TITLE_MISSING", "severity": "blocker",
                               "entry_id": e.id, "detail": "进入书签的条目缺标题"})
        return issues


def make_penetration_coverage(points: int) -> dict[str, Any]:
    """C5 两张基准图：旧 10 点 / 新版 59 点。"""
    if points == 10:
        start, end, missing = "2025-03", "2025-12", []
    elif points == 59:
        start, end, missing = "2021-02", "2025-12", ["2021-01"]
    else:
        raise ValueError("仅支持 10 点或 59 点 C5 基准")
    return {
        "entities": ["国内新能源乘用车"],
        "metric": "零售渗透率当月值",
        "period_start": start,
        "period_end": end,
        "period_status": "known",
        "frequency": "monthly",
        "points": points,
        "expected_points": _months_between(start, end),
        "missing_points": missing,
        "unit": "%",
    }


def evaluate_coverage(coverage: dict[str, Any], claim_start: str, claim_end: str,
                      *, full_assertion: bool = True) -> CoverageVerdict:
    """比对正文声称的覆盖区间；超范围或缺失点会出 coverage_warning。"""
    status = coverage.get("period_status")
    if status == "unknown":
        return CoverageVerdict(
            False, True, "UNKNOWN_PERIOD",
            "期间不可确认，照实标注，不得充当年度/全区间或产业链证据。")
    start, end = coverage.get("period_start"), coverage.get("period_end")
    if not start or not end:
        return CoverageVerdict(False, True, "NO_PERIOD",
                               "注册表未记录可复算的覆盖区间。")
    if claim_start < start or claim_end > end:
        return CoverageVerdict(
            False, True, "COVERAGE_OVERFLOW",
            f"正文声称 {claim_start}—{claim_end} 超出证据覆盖 {start}—{end}；"
            "阻断对应全量断言发布，交回 A4 缩口径或补图。")
    missing = [p for p in coverage.get("missing_points", [])
               if claim_start <= p <= claim_end]
    if missing and full_assertion:
        return CoverageVerdict(
            False, True, "MISSING_POINTS",
            "声称区间含缺失点，禁止写成连续全区间断言。", missing)
    if missing:
        return CoverageVerdict(True, True, "PARTIAL_WITH_DISCLOSURE",
                               "允许发布，但必须显式声明缺失点。", missing)
    return CoverageVerdict(True, False, "OK", "覆盖区间可由证据支撑。")


def _figure_coverage(title: str, data_contract: dict[str, Any] | None,
                     *, standalone: bool) -> dict[str, Any]:
    if standalone:
        return {
            "entities": ["行业全景（非五家财务样本）"], "metric": "产业链关系",
            "period_status": "not_applicable", "frequency": None,
            "missing_points": [], "points": None,
            "note": "图注必须区分行业全景与本报告五家财务样本；不为它伪造关系证据。",
        }
    m = PERIOD_RE.search(title or "")
    cov: dict[str, Any] = {
        "entities": list((data_contract or {}).get("entities", []) or []),
        "metric": (data_contract or {}).get("metric"),
        "period_start": m.group(1)[:7] if m else None,
        "period_end": m.group(2)[:7] if m else None,
        "period_status": "known" if m else "unknown",
        "frequency": (data_contract or {}).get("frequency"),
        "points": (data_contract or {}).get("points"),
        "missing_points": [],
        "unit": (data_contract or {}).get("unit"),
    }
    # 月度零售渗透率是唯一已知带固定缺口的序列。
    if "零售渗透率" in (title or "") and cov["period_start"]:
        cov["frequency"] = "monthly"
        cov["unit"] = "%"
        cov["points"] = cov["points"] or _months_between(cov["period_start"], cov["period_end"])
        cov["expected_points"] = _months_between(cov["period_start"], cov["period_end"])
        if cov["period_start"] <= "2021-01" <= cov["period_end"]:
            cov["missing_points"] = ["2021-01"]
    return cov


def build_registry(
    structure: dict[str, Any],
    toc_map: dict[str, Any],
    a3_audit: dict[str, Any],
    a3_charts: dict[str, Any],
    outline: list[dict[str, Any]] | None = None,
    *,
    asset_root: Path | None = None,
    figure_asset_root: Path | None = None,
    source_bindings: dict[str, Any] | None = None,
    numbering_mode: str = "preserve_mother",
    theme: str = "a5_nev",
) -> ChartRegistry:
    """从冻结夹具 + A3 绑定清单构造注册表。只读，不重绘任何图。"""
    entries: list[RegistryEntry] = []
    a3_figures = a3_audit.get("figures", {})
    a3_specs = (a3_charts or {}).get("figures", {})
    run_id = a3_audit.get("a3_reference_run_id")
    artifact_present = bool(a3_audit.get("run_artifact_dirs_present"))
    run = a3_audit.get("run", {})
    pv = a3_audit.get("point_verification", {})
    new_c5 = a3_audit.get("new_c5", {})
    fig8_audit = a3_audit.get("figure8", {})
    bindings = source_bindings or {}
    alignment = toc_map.get("outline_alignment", {})
    outline_keys = {x["toc_key"] for x in alignment.get("matched", [])}
    only_outline = alignment.get("expected_outline_only", [])
    toc_items = toc_map.get("toc_items", [])

    def toc_key_for(kind: str, number: str | None) -> str | None:
        if not number:
            return None
        key = _norm(("表" if kind == "table" else "图") + number)
        return next((x["key"] for x in toc_items
                     if _norm(x["label"]).startswith(key)), None)

    def _entry_common(number: str, kind: str, title: str, source: str,
                      note: str, idx: int, cover: dict[str, Any],
                      prov: dict[str, Any], mother: str | None,
                      placement: str | None = None,
                      reading_number: str | None = None,
                      **extra) -> RegistryEntry:
        toc_key = toc_key_for(kind, mother)
        entry = RegistryEntry(
            id=f"{'fig' if kind == 'figure' else 'tab'}-{idx:02d}",
            number=number, kind=kind, title=title, source=source, note=note,
            coverage=cover, provenance=prov,
            data_ref=f"a3://{run_id}/figures/{idx}" if kind == "figure" else None,
            placement_section_id=placement,
            include_in_outline=(toc_key in outline_keys) if toc_key else False,
            mother_number=mother,
            meta={"toc_key": toc_key, **extra},
        )
        # 五项发布硬门禁只作用于承载数据的图/表条目。
        if kind in ("figure", "table"):
            if not source:
                entry.blockers.append("SOURCE_MISSING")
            if cover.get("coverage_warning"):
                entry.blockers.append("COVERAGE_OVERFLOW_UNHANDLED")
        if kind == "figure":
            if not prov.get("asset_sha256"):
                entry.blockers.append("ASSET_HASH_MISSING")
            if prov.get("hash_mismatch"):
                entry.blockers.append("ASSET_HASH_MISMATCH")
            if not prov.get("asset_exists"):
                entry.blockers.append("ASSET_MISSING")
            if prov.get("origin") not in KNOWN_ORIGINS:
                entry.blockers.append("UNREGISTERED_REDRAW")
            if not artifact_present:
                entry.warnings.append("A3_RUN_ARTIFACT_MISSING: provenance 仅引用级")
        for gap in extra.get("source_gaps", []):
            entry.warnings.append(f"SOURCE_GAP:{gap.get('id')}")
        entry.reading_order_number = reading_number
        entry.publish_allowed = not entry.blockers
        return entry

    for idx, fig in enumerate(structure.get("figures", []), 1):
        key = f"fig{idx}"
        spec = a3_figures.get(key, {})
        raw = a3_specs.get(key, {})
        chart = (raw.get("charts") or [{}])[0]
        origin = spec.get("origin") or raw.get("origin")
        standalone = origin == "a3_standalone_chain_panorama"
        heading = fig.get("heading") or ""
        mother = MOTHER_FIG_RE.match(heading)
        declared = a3_audit.get("figure8", {}).get("declared_sha256") if standalone else None
        asset_rel = ("产业链图_单跑/新能源汽车产业链图.svg" if standalone
                     else fig.get("asset") or "")
        base = asset_root if standalone else (figure_asset_root or asset_root)
        asset_path = (base / asset_rel) if base else Path(asset_rel)
        actual = sha256_file(asset_path) if asset_path.exists() else None
        prov = {
            "a3_run_id": run_id,
            "a3_run_artifact_present": artifact_present,
            "a3_artifact_dir": run.get("artifact_dir"),
            "a3_chart_result_sha256": run.get("chart_result_sha256"),
            "a3_quality": run.get("quality"),
            "a3_point_checks": pv.get("target_point_checks"),
            "a3_point_errors": pv.get("target_point_errors"),
            "a3_real_model_participated": pv.get("real_model_participated"),
            "chart_ids": spec.get("chart_ids", []),
            # 母本图 8 是三栏结构图，与方案指定的 A3 全景 SVG 不是同一资产；
            # 两条路径分别登记，重构成品时才替换，不把旧图的题注挂到新图哈希上。
            "mother_asset": fig.get("asset"),
            "asset_replaced_pending": bool(
                standalone and fig.get("asset") and fig.get("asset") != asset_rel),
            "asset_path": asset_rel,
            "asset_sha256": actual or declared,
            "asset_hash_declared": declared,
            "asset_exists": bool(actual),
            "hash_mismatch": bool(declared and actual and declared != actual),
            "origin": origin,
            "accepted": bool(origin == "accepted_a3_chart" and artifact_present),
            "acceptance_level": (
                "artifact_verified" if origin == "accepted_a3_chart" and artifact_present
                else "reference_only" if origin == "accepted_a3_chart"
                else "standalone_asset" if standalone else "compiled_in_a3"
            ),
            "a3_compiled": origin == "a3_compiled",
            "conversion_note": (
                "用户确认的 A3 全景原图，图注区分行业全景与五家财务样本；"
                "A3 未提供供货关系边，不伪造关系证据。" if standalone
                else "A3 已验收图，按原图位挂接，未重绘。" if origin == "accepted_a3_chart"
                else "在 A3 中适配编译的图，保留 A3 侧剔除点记录。" if origin == "a3_compiled"
                else "来源未登记，需交回 A3 复核。"
            ),
        }
        if standalone:
            prov["role"] = fig8_audit.get("role")
            prov["caption_scope"] = fig8_audit.get("caption_scope")
            prov["a3_note"] = fig8_audit.get("a3_note")
            prov["acceptance_level"] = "artifact_verified_standalone"
        cover = _figure_coverage(chart.get("title") or heading,
                                 chart.get("data_contract") or {},
                                 standalone=standalone)
        # 新版 C-05 用真实 A3 验收图（59 点）替换旧 10 点描述；母本原文保留。
        if "零售渗透率" in (chart.get("title") or heading) and new_c5.get("chart_id"):
            cover.update({
                "chart_id": new_c5["chart_id"],
                "period_start": (new_c5.get("start") or "")[:7] or cover.get("period_start"),
                "period_end": (new_c5.get("end") or "")[:7] or cover.get("period_end"),
                "period_status": "known", "frequency": "monthly",
                "points": new_c5.get("points"), "expected_points": 59,
                "missing_points": new_c5.get("missing_points", []),
                "verified_by": "point_verification.json（77 点 / 0 错）",
            })
        mother_num = mother.group(1) if mother else str(idx)
        number = (f"图{mother_num}" if numbering_mode == "preserve_mother"
                  else f"图{idx}")
        entries.append(_entry_common(
            number, "figure", heading, fig.get("source", ""),
            fig.get("note", ""), idx, cover, prov, mother_num,
            reading_number=f"图{idx}",
            placement=(chart.get("placement_section_id") or None),
            a3_title=chart.get("title"), origin=origin,
            asset_sha256=actual or declared,
        ))

    for idx, tab in enumerate(structure.get("tables", []), 1):
        caption = tab.get("caption") or ""
        mother = MOTHER_TAB_RE.match(caption)
        unknown = "期间不可确认" in (tab.get("note", "") + caption) or "主营构成" in caption
        cover = {
            "entities": [], "metric": None,
            "period_start": None, "period_end": None,
            "period_status": "unknown" if unknown else "not_declared",
            "frequency": None, "points": None, "missing_points": [],
            "note": "C6 主营构成记录期间 unknown，照实标注，不充当产业链证据。"
                    if unknown else "表内期间与单位以表头及表注为准。",
        }
        prov = {
            "a3_run_id": run_id,
            "a3_run_artifact_present": artifact_present,
            "chart_ids": [], "asset_sha256": None,
            "asset_exists": True, "hash_mismatch": False,
            "origin": "mother_html_table",
            "accepted": False, "acceptance_level": "content_layer",
            "a3_compiled": False,
            "conversion_note": "表格数据/单位/来源由内容层提供，排版层不生成。",
        }
        mother_num = mother.group(1) if mother else str(idx)
        number = (f"表{mother_num}" if numbering_mode == "preserve_mother"
                  else f"表{idx}")
        source = tab.get("source", "")
        extra: dict[str, Any] = {
            "headers": tab.get("headers", []),
            "row_count": tab.get("row_count", 0),
        }
        if mother_num == "A2" and bindings:
            # 母本该表只有「注」没有「资料来源」；由注册表按 5 行逐行绑定
            # 生成汇总来源，不手写一句来源，找不到的行单独标缺口。
            source = bindings.get("aggregate_source_generated_by_registry") or source
            extra.update({
                "source_origin": "generated_by_registry_from_row_bindings",
                "source_bindings": bindings.get("rows", []),
                "source_gaps": bindings.get("source_gaps", []),
                "c5_c6_update": bindings.get("c5_c6_update", {}),
                "figure8": bindings.get("figure8", {}),
            })
        entries.append(_entry_common(
            number, "table", caption, source,
            tab.get("note", ""), idx, cover, prov, mother_num,
            reading_number=f"表{idx}", **extra,
        ))

    # 正文引用、图表目录和书签只认注册表 ID：42 个目录键全部登记，
    # 章节条目与图表条目共用同一 ID 空间。
    for item in toc_items:
        if item.get("kind") != "section":
            continue
        key = item["key"]
        entries.append(RegistryEntry(
            id=f"toc-{key}", number=key, kind="section", title=item["label"],
            coverage={"period_status": "not_applicable"},
            provenance={"origin": "content_layer", "a3_run_id": run_id,
                        "accepted": False, "a3_compiled": False,
                        "conversion_note": "章节标题来自冻结视图，不承载图表数据。"},
            data_ref=f"toc://{key}", placement_section_id=key,
            include_in_outline=(key in outline_keys), mother_number=key,
            meta={"toc_key": key, "page": item["page"], "level": item["level"]},
        ))

    # 6 条「仅在 PDF 书签出现」的母本条目，显式 include_in_outline。
    for i, title in enumerate(only_outline, 1):
        entries.append(RegistryEntry(
            id=f"outline-only-{i:02d}", number=f"outline-{i:02d}",
            kind="outline_only", title=title,
            coverage={"period_status": "not_applicable"},
            provenance={"origin": "mother_outline", "a3_run_id": None,
                        "accepted": False, "a3_compiled": False,
                        "conversion_note": "母本冻结清单中只在书签出现，不进 HTML 目录。"},
            data_ref=None, include_in_outline=True,
            meta={"toc_key": None, "outline_only": True},
        ))

    blocking_gaps: list[dict[str, Any]] = []
    if not artifact_present:
        blocking_gaps.append({
            "id": "GAP-A3-RUN-ARTIFACT", "severity": "blocking_for_P3_provenance",
            "detail": f"A3 验收 run {run_id} 物理产物缺失；8 个图位的 provenance "
                      "只能回填引用级证据，不得标记为已验收产物。",
        })
    registry = ChartRegistry(
        theme=theme, entries=entries, outline=outline or [],
        outline_only_count=len(only_outline),
        numbering_mode=numbering_mode,
        blocking_gaps=blocking_gaps,
    )
    registry.content_sha256 = hashlib.sha256(
        json.dumps(registry.to_dict(), ensure_ascii=False,
                   sort_keys=True).encode("utf-8")).hexdigest()
    return registry
