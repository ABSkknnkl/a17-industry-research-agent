"""Build deterministic, Chinese evidence citations without touching Agent 1."""

from collections.abc import Iterable

from app.schemas.analysis import AnalysisResult, EvidenceCatalogItem
from app.schemas.chapter import ChapterWritingResult
from app.schemas.chart import ChartGenerationResult
from app.schemas.report import EvidenceSourceEntry

_GRADE_LABELS = {
    "A": "一级证据（监管或审计披露）",
    "B": "二级证据（官方或高可信资料）",
    "C": "三级证据（行业研究资料）",
    "D": "四级证据（辅助参考资料）",
    "E": "待核验证据",
}
_AUDIT_LABELS = {
    "audited": "已审计",
    "reviewed": "已审阅",
    "unaudited": "未经审计",
    "not_applicable": "不适用",
    "unknown": "未提供",
}


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _referenced_ids(
    analysis: AnalysisResult,
    charts: ChartGenerationResult,
    chapters: ChapterWritingResult,
    included_chart_ids: set[str] | None,
) -> list[str]:
    """Use first appearance order so citation numbers follow the reading flow."""

    ids: list[str] = []
    for claim in analysis.claims:
        if claim.status != "rejected":
            ids.extend(claim.evidence_ids)
            ids.extend(claim.counter_evidence_ids)
    for chapter in chapters.chapters:
        for section in chapter.sections:
            for paragraph in section.paragraphs:
                ids.extend(paragraph.evidence_ids)
    for chart in charts.chart_specs:
        if included_chart_ids is None or chart.chart_id in included_chart_ids:
            ids.extend(chart.evidence_ids)
    for issue in analysis.data_quality_issues:
        ids.extend(issue.evidence_ids)
    for check in analysis.financial_consistency_checks:
        ids.extend(check.evidence_ids)
    for coverage in analysis.dimension_coverage:
        ids.extend(coverage.evidence_ids)
    return _unique(ids)


def _source_key(item: EvidenceCatalogItem) -> str:
    # One material may support many metrics.  Grouping by its declared title
    # removes repetitive rows while individual evidence IDs remain traceable.
    return " ".join(item.source_name.split()).casefold()


def build_evidence_catalog(
    analysis: AnalysisResult,
    charts: ChartGenerationResult,
    chapters: ChapterWritingResult,
    *,
    included_chart_ids: set[str] | None = None,
) -> list[EvidenceSourceEntry]:
    metadata_by_id = {item.evidence_id: item for item in analysis.evidence_catalog}
    groups: dict[str, list[EvidenceCatalogItem]] = {}
    group_order: list[str] = []
    missing_ids: list[str] = []

    for evidence_id in _referenced_ids(
        analysis,
        charts,
        chapters,
        included_chart_ids,
    ):
        item = metadata_by_id.get(evidence_id)
        if item is None:
            missing_ids.append(evidence_id)
            continue
        key = _source_key(item)
        if key not in groups:
            groups[key] = []
            group_order.append(key)
        groups[key].append(item)

    entries: list[EvidenceSourceEntry] = []
    for key in group_order:
        items = groups[key]
        first = items[0]
        number = len(entries) + 1
        entries.append(
            EvidenceSourceEntry(
                citation_number=number,
                display_label=f"来源{number}：{first.source_name}",
                material_title=first.source_name,
                metric_names=_unique(item.metric_name for item in items),
                available_dates=_unique(
                    item.available_at.isoformat() if item.available_at else "未提供"
                    for item in items
                ),
                reporting_periods=_unique(
                    item.period_end.isoformat() if item.period_end else "未提供" for item in items
                ),
                locators=_unique(item.source_locator or "未提供" for item in items),
                source_levels=_unique(_GRADE_LABELS[item.grade.value] for item in items),
                audit_labels=_unique(_AUDIT_LABELS[item.audit_status.value] for item in items),
                scopes=_unique(item.scope for item in items),
                evidence_ids=_unique(item.evidence_id for item in items),
            )
        )

    # Old/imported Agent 2 results may not yet contain the catalog.  Never leak
    # their machine IDs into a formal report; make the metadata gap explicit.
    for _evidence_id in missing_ids:
        number = len(entries) + 1
        entries.append(
            EvidenceSourceEntry(
                citation_number=number,
                display_label=f"来源{number}：来源信息待补充",
                material_title="来源信息待补充",
                metric_names=["相关指标待补充"],
                available_dates=["未提供"],
                reporting_periods=["未提供"],
                locators=["未提供"],
                source_levels=["待核验证据"],
                audit_labels=["未提供"],
                scopes=["当前结果仅保留内部追溯关系，正式来源元数据尚未补充。"],
                evidence_ids=[_evidence_id],
            )
        )
    return entries
