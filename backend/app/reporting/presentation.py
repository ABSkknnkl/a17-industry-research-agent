"""Shared Chinese presentation helpers for Markdown, HTML and PDF."""

import re
from collections.abc import Iterable
from datetime import date

from app.schemas.report import EvidenceSourceEntry

CONFIDENCE_LABELS = {"high": "高", "medium": "中", "low": "低"}
REPORT_DEPTH_LABELS = {"brief": "简版", "standard": "标准版", "deep": "深度版"}
DELIVERY_STATUS_LABELS = {
    "ready": "可交付",
    "ready_with_limits": "附限制条件可交付",
    "blocked": "暂不可交付",
}
DIMENSION_LABELS = {
    "competition": "竞争格局",
    "growth": "行业增长",
    "macro_policy": "宏观与政策",
    "industry_chain": "产业链",
    "risk": "风险",
}
COVERAGE_STATUS_LABELS = {
    "supported": "证据充分",
    "partial": "部分支持",
    "insufficient": "证据不足",
}
IMPACT_LABELS = {"low": "低", "medium": "中", "high": "高"}
CHECK_STATUS_LABELS = {
    "passed": "通过",
    "warning": "需要复核",
    "unavailable": "资料不足",
    "not_applicable": "不适用",
}
CHART_TYPE_LABELS = {
    "line": "折线图",
    "bar": "柱状图",
    "pie": "饼图",
    "radar": "雷达图",
    "industry_chain": "产业链图",
    "combo": "组合图",
    "area": "面积图",
    "scatter": "散点图",
    "bubble": "气泡图",
    "heatmap": "热力图",
    "boxplot": "箱线图",
    "treemap": "矩形树图",
}

_CN_NUMBERS = ("零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十")


def chapter_label(chapter_id: str) -> str:
    try:
        number = int(chapter_id.rsplit("-", 1)[1])
    except (IndexError, ValueError):
        return "章节"
    value = _CN_NUMBERS[number] if 0 <= number < len(_CN_NUMBERS) else str(number)
    return f"第{value}章"


def section_label(section_id: str) -> str:
    try:
        _, chapter, section = section_id.split("-")
        return f"第{int(chapter)}章第{int(section)}节"
    except (ValueError, IndexError):
        return "小节"


def humanize_internal_ids(value: str) -> str:
    """Remove machine identifiers from user-facing prose and warning strings."""

    replacements = (
        (r"SEC-\d{2}-\d{2}", "相关小节"),
        (r"CHART-[A-Za-z0-9_-]+", "相关图表"),
        (r"REPORT-[A-Za-z0-9_-]+", "本报告"),
        (r"DQ-[A-Za-z0-9_-]+", "数据质量问题"),
        (r"FC-[A-Za-z0-9_-]+", "财务一致性检查"),
        (r"CH-\d{2}", "相关章节"),
        (r"C-[A-Za-z0-9_-]+", "相关结论"),
        (r"E-[A-Za-z0-9_-]+", "相关证据"),
    )
    result = value
    for pattern, replacement in replacements:
        result = re.sub(pattern, replacement, result)
    return result


def citation_lookup(entries: Iterable[EvidenceSourceEntry]) -> dict[str, EvidenceSourceEntry]:
    return {evidence_id: entry for entry in entries for evidence_id in entry.evidence_ids}


def citation_text(
    evidence_ids: Iterable[str],
    lookup: dict[str, EvidenceSourceEntry],
    *,
    detailed: bool = False,
) -> str:
    entries: list[EvidenceSourceEntry] = []
    seen: set[int] = set()
    for evidence_id in evidence_ids:
        entry = lookup.get(evidence_id)
        if entry is not None and entry.citation_number not in seen:
            seen.add(entry.citation_number)
            entries.append(entry)
    if not entries:
        return "〔来源信息待补充〕"
    if detailed:
        return "〔" + "；".join(entry.display_label for entry in entries) + "〕"
    return "〔" + "、".join(f"来源{entry.citation_number}" for entry in entries) + "〕"


def _compact_text(value: str, limit: int) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def _compact_values(values: Iterable[str], limit: int) -> str:
    unique = list(dict.fromkeys(value for value in values if value and value != "未提供"))
    if not unique:
        return "未提供"
    first = _compact_text(unique[0], limit)
    return first if len(unique) == 1 else f"{first}等{len(unique)}项"


def _compact_dates(values: Iterable[str]) -> str:
    unique = list(dict.fromkeys(value for value in values if value and value != "未提供"))
    if not unique:
        return "未提供"
    parsed: list[date] = []
    for value in unique:
        try:
            parsed.append(date.fromisoformat(value))
        except ValueError:
            return _compact_values(unique, 15)
    parsed.sort()
    if len(parsed) == 1:
        return parsed[0].isoformat()
    if parsed[0].year == parsed[-1].year:
        return f"{parsed[0].year}年（{len(parsed)}期）"
    return f"{parsed[0].year}—{parsed[-1].year}年（{len(parsed)}期）"


def _compact_locator(values: Iterable[str]) -> str:
    unique = list(dict.fromkeys(value for value in values if value and value != "未提供"))
    if not unique:
        return "未提供"
    labels: list[str] = []
    for value in unique:
        lowered = value.lower()
        if lowered.startswith("fixture://"):
            label = "流程测试定位"
        elif lowered.startswith(("http://", "https://")):
            label = "网页原文"
        else:
            label = _compact_text(value, 20)
        if label not in labels:
            labels.append(label)
    first = labels[0]
    return first if len(labels) == 1 else f"{first}等{len(labels)}处"


def source_table_rows(entries: Iterable[EvidenceSourceEntry]) -> list[dict[str, str | int]]:
    """Build the same compact, presentation-safe source rows for HTML/PDF/Markdown."""

    rows: list[dict[str, str | int]] = []
    for entry in entries:
        level = _compact_values(
            (re.sub(r"（.*?）", "", value) for value in entry.source_levels),
            8,
        )
        audit = _compact_values(
            (value for value in entry.audit_labels if value not in {"不适用", "未提供"}),
            8,
        )
        method = _compact_values(entry.retrieval_methods, 16)
        method_level = f"{method} / {level}"
        if audit != "未提供":
            method_level += f" · {audit}"
        rows.append(
            {
                "citation_number": entry.citation_number,
                "material": _compact_text(entry.material_title, 30),
                "publisher": _compact_values(entry.publishers, 16),
                "available_date": _compact_dates(entry.available_dates),
                "reporting_period": _compact_dates(entry.reporting_periods),
                "locator": _compact_locator(entry.locators),
                "method_level": _compact_text(method_level, 30),
            }
        )
    return rows
