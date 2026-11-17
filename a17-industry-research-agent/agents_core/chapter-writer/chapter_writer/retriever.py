"""Dynamic evidence and context retriever for chapter writing."""

from __future__ import annotations

from collections import Counter
import math
import re
from typing import Any
from agents_core.financial_semantics import quantity_issues, retain_supported_claims

from chapter_writer.assignment import (
    AssignmentTable,
    assignment_rows_for_context,
    assignments_for_section,
    build_assignment_guidance,
    build_assignment_table,
)
from chapter_writer.models import ChapterWritingRequest, OutlineChapter
from chapter_writer.outline import DEFAULT_OUTLINE

# Stopwords to filter out trivial grammatical tokens
STOPWORDS = {
    "的", "了", "和", "与", "及", "或", "在", "对", "为", "等", "从", "由", "向",
    "并", "以", "按", "其", "各", "该", "本", "此", "这", "那", "有", "无", "中",
    "上", "下", "内", "外", "于", "个", "项", "类", "条", "者", "进行", "说明",
    "呈现", "分析", "概括", "结合", "要求",
}

DOMAIN_AFFINITY: dict[str, set[str]] = {
    "CH-01": {"industry", "reports", "news"},
    "CH-02": {"industry", "financials"},
    "CH-03": {"industry_chain", "companies", "financials", "industry"},
    "CH-04": {"companies", "industry", "financials"},
    "CH-05": {"financials", "companies", "industry"},
    "CH-06": {"macro", "reports", "news", "industry"},
    "CH-07": {"financials", "industry", "reports"},
}

# First-release intent-to-requirement pairing for coverage rows that carry no
# ``requirement_id`` (the A3 contract exposes ``intent_id``). The mapping is
# deliberately narrow: metric family and period shape are re-checked against
# the A2 requirement before it is allowed to route a gap to a section.
_COVERAGE_INTENT_REQUIREMENT: dict[str, tuple[str, str, str]] = {
    "nev.q1.annual_penetration": (
        "penetration_rate_series", "nev_penetration", "annual",
    ),
}


def _coverage_chart_ids(row: dict[str, Any]) -> set[str]:
    raw = row.get("chart_ids")
    if not isinstance(raw, (list, tuple)):
        return set()
    return {str(item) for item in raw if isinstance(item, (str, int, float))}


def _coverage_intent_requirement(
    row: dict[str, Any],
    requirements_by_id: dict[str, dict[str, Any]],
) -> str:
    """Resolve the narrow annual-penetration pair and re-check its contract."""
    intent_id = str(row.get("intent_id") or "").strip()
    target = _COVERAGE_INTENT_REQUIREMENT.get(intent_id)
    if not target:
        return ""
    requirement_id, family, period_kind = target
    requirement = requirements_by_id.get(requirement_id)
    if not requirement:
        return ""
    families = {
        str(item) for item in (requirement.get("metric_families") or [])
        if isinstance(item, (str, int, float))
    }
    if family not in families:
        return ""
    period_ends = [
        str(item) for item in (requirement.get("period_ends") or [])
        if isinstance(item, (str, int, float))
    ]
    if period_kind == "annual":
        # The annual series must really describe year ends, not a single
        # monthly observation borrowed from the revised A1 record.
        if len(period_ends) < 3 or not all(p.endswith("-12-31") for p in period_ends):
            return ""
    return requirement_id


def _coverage_row_belongs_to_chapter(
    row: dict[str, Any],
    *,
    chapter_requirement_ids: set[str],
    owned_requirement_ids: set[str],
    chapter_chart_ids: set[str],
    requirements_by_id: dict[str, dict[str, Any]],
) -> bool:
    """Route coverage by requirement ownership first, chart placement second.

    ``chart_ids`` alone cannot carry a gap whose ``chart_ids`` is empty, so an
    explicitly paired intent may route through its owning requirement. A row
    with a chart id only belongs to the chapter where that chart is placed.
    """
    requirement_id = str(row.get("requirement_id") or "").strip()
    if requirement_id and (
        requirement_id in chapter_requirement_ids
        or requirement_id in owned_requirement_ids
    ):
        return True
    if _coverage_chart_ids(row) & chapter_chart_ids:
        return True
    mapped_id = _coverage_intent_requirement(row, requirements_by_id)
    return bool(mapped_id and mapped_id in owned_requirement_ids)


_CLAIM_FIELDS = (
    'subject', 'predicate', 'object_summary', 'title', 'conclusion',
    'significance', 'claim', 'explanation',
)


def _clause_count(text: str) -> int:
    return len([part for part in re.split(r"[。；;\n！？!?]", text or "") if part.strip()])


def filter_unverified_findings(rows: list[dict[str, Any]], evidence: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    """Keep evidence-backed clauses instead of dropping the whole finding.

    Upstream prose is only context, not a verified fact. A finding may mix a
    supported sentence with an unsupported number; the former stays, the latter
    is removed, and the field shape is preserved. Numeric comparison is still
    conservative: clauses are checked against the finding's own evidence plus
    the full evidence universe.
    """
    kept = []
    removed_clauses = 0
    universe = list(evidence.values())
    for row in rows:
        if not isinstance(row, dict):
            continue
        refs = [evidence[rid] for rid in row.get('evidence_record_ids', []) if rid in evidence]
        clean = dict(row)
        for key in _CLAIM_FIELDS:
            value = row.get(key)
            if not isinstance(value, str) or not value.strip():
                continue
            retained = retain_supported_claims(
                value,
                lambda clause: not quantity_issues(
                    clause, refs, universe=universe
                ),
            )
            removed_clauses += _clause_count(value) - _clause_count(retained)
            clean[key] = retained
        points = row.get('key_points')
        if isinstance(points, list):
            retained_points = []
            for point in points:
                if not isinstance(point, str) or not point.strip():
                    continue
                retained = retain_supported_claims(
                    point,
                    lambda clause: not quantity_issues(
                        clause, refs, universe=universe
                    ),
                )
                removed_clauses += _clause_count(point) - _clause_count(retained)
                if retained:
                    retained_points.append(retained)
            clean['key_points'] = retained_points
        if any(str(clean.get(key) or '').strip() for key in _CLAIM_FIELDS) or clean.get('key_points'):
            kept.append(clean)
    return kept, removed_clauses


VERDICT_VALUES = {"sequence_consistent", "partially_supported", "insufficient_evidence", "supported", "unknown"}


def _verdict_context(report: Any, query_tokens: Counter[str], final_eids: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """A2 假设判定：只带判定和覆盖提示，不带未经核验的因果结论。"""
    analysis = getattr(report, "chain_analysis", None) or {}
    rows = analysis.get("hypothesis_verdicts") if isinstance(analysis, dict) else None
    if not isinstance(rows, list):
        return [], []
    kept, diagnostics = [], []
    for row in rows:
        if not isinstance(row, dict):
            continue
        statement = str(row.get("statement") or "")
        verdict = str(row.get("verdict") or "unknown")
        score = DynamicEvidenceRetriever._score_text(
            " ".join([statement, *[str(v) for v in row.get("covered_evidence", [])]]), query_tokens)
        raw_ids = [str(v) for v in row.get("evidence_record_ids", []) if str(v).strip()]
        valid_ids = [eid for eid in raw_ids if eid in final_eids]
        item = {
            "hypothesis_id": str(row.get("hypothesis_id") or ""),
            "statement": statement,
            "verdict": verdict,
            "basis": str(row.get("basis") or ""),
            "required_evidence": [str(v) for v in row.get("required_evidence", []) if str(v).strip()],
            # 覆盖说明只作提示，不是 record_id 白名单。
            "covered_evidence": [str(v) for v in row.get("covered_evidence", []) if str(v).strip()],
            "evidence_record_ids": valid_ids,
        }
        if verdict not in VERDICT_VALUES or not item["hypothesis_id"]:
            diagnostics.append(dict(
                hypothesis_id=item["hypothesis_id"], verdict=verdict,
                reason="判定值无法核验，按待核处理",
            ))
        elif raw_ids and len(valid_ids) != len(raw_ids):
            diagnostics.append(dict(
                hypothesis_id=item["hypothesis_id"], verdict=verdict,
                reason="判定引用的 record_id 不在本章证据包，已从引用中移除",
            ))
        kept.append((score, item))
    kept.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in kept[:8]], diagnostics


def _analysis_fact_context(report: Any, final_eids: set[str]) -> dict[str, Any]:
    """只保留与本章提示包证据相交的事实/对照，避免把别章口径带进写作。"""
    facts = getattr(report, "analysis_facts", None) or {}
    if not isinstance(facts, dict):
        return {}
    observations = [o for o in facts.get("observations", [])
                    if isinstance(o, dict) and o.get("record_id") in final_eids]
    comparisons = [c for c in facts.get("comparisons", [])
                   if isinstance(c, dict)
                   and {c.get("from_record_id"), c.get("to_record_id")} <= final_eids]
    coverage = [c for c in facts.get("coverage", [])
                if isinstance(c, dict) and set(c.get("evidence_record_ids", [])) & final_eids]
    conflicts = [c for c in facts.get("conflicts", [])
                 if isinstance(c, dict) and set(c.get("evidence_record_ids", [])) & final_eids]
    return dict(observations=observations[:12], comparisons=comparisons[:8],
                coverage=coverage[:4], conflicts=conflicts[:4])


def _semantic_check_context(report: Any, final_eids: set[str]) -> list[dict[str, Any]]:
    """审计记录只保留状态与可引用结论；原始错误句不进入写作素材。"""
    rows = getattr(report, "semantic_checks", None) or []
    kept = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        ids = {str(v) for v in row.get("evidence_record_ids", [])}
        if ids and not (ids & final_eids):
            continue
        kept.append({
            "location": str(row.get("location") or ""),
            "status": str(row.get("status") or ""),
            "metrics": [str(v) for v in row.get("metrics", [])][:6],
            "replacement": str(row.get("replacement") or "")[:240],
            "evidence_record_ids": sorted(ids & final_eids),
        })
    return kept[:8]


def _chart_context(chart: Any, final_eids: set[str]) -> dict[str, Any]:
    """逐图保留单位、期间、范围、来源与脚注；只保留实际进入提示包的图点。"""
    item = _dump(chart)
    contract = item.get("data_contract")
    if isinstance(contract, dict) and isinstance(contract.get("points"), list):
        points = [p for p in contract["points"] if isinstance(p, dict) and (
            p.get("record_id") in final_eids
            or set(p.get("source_record_ids") or []) & final_eids
        )]
        if points and len(points) != len(contract["points"]):
            contract = {**contract, "points": points,
                        "points_omitted": len(contract["points"]) - len(points)}
        elif not points:
            contract = {**contract, "points": [],
                        "points_omitted": len(contract["points"])}
    item["data_contract"] = contract if isinstance(contract, dict) else {}
    item["footnotes"] = [str(v) for v in (item.get("footnotes") or [])][:4]
    item["point_evidence_ids"] = [str(v) for v in (item.get("point_evidence_ids") or []) if str(v) in final_eids]
    return item


def _tokenize(text: str) -> list[str]:
    """Tokenize mixed Chinese and English text into word tokens and 2-grams."""
    if not text:
        return []
    cleaned = re.sub(r"[^\w\u4e00-\u9fff]+", " ", text.lower())
    words = [w for w in cleaned.split() if len(w) >= 2 and w not in STOPWORDS]

    # Character n-grams for Chinese compound concepts
    chinese_chars = [ch for ch in text if "\u4e00" <= ch <= "\u9fff"]
    bigrams = [
        "".join(chinese_chars[i : i + 2])
        for i in range(len(chinese_chars) - 1)
        if "".join(chinese_chars[i : i + 2]) not in STOPWORDS
    ]
    return words + bigrams


def _dump(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    if hasattr(item, "model_dump"):
        return item.model_dump(mode="json")
    return dict(item)


class DynamicEvidenceRetriever:
    """Retrieves relevant evidence, insights, findings, and charts dynamically per chapter."""

    def __init__(self, request: ChapterWritingRequest) -> None:
        self.request = request
        self.report = request.report
        self.charts = request.charts.charts if request.charts else []
        # Computed once from the effective outline so full-run and targeted
        # rewrites of the same input always see the same allocation.
        self.assignment_table: AssignmentTable = build_assignment_table(request)
        self.assignment_diagnostics: list[str] = list(self.assignment_table.diagnostics)
        self.question_assignments = self._assign_questions()

    def _assign_questions(self) -> list[dict[str, Any]]:
        outline = self.request.outline or DEFAULT_OUTLINE
        sections = [section for chapter in outline for section in chapter.sections]
        section_ids = {section.section_id for section in sections}
        requirements = {entry.requirement_id: entry for entry in self.assignment_table.entries}
        result = []
        for question in self.request.questions:
            linked = [requirements[rid] for rid in question.requirement_ids if rid in requirements]
            tags = set(question.relation_tags)
            owners = Counter(entry.owner_section_id for entry in linked if entry.owner_section_id in section_ids)
            chart_chapters = Counter(
                chart.recommended_chapter_id for chart in self.charts
                if chart.status == "ready" and chart.chart_id in question.chart_ids and chart.recommended_chapter_id
            )
            if question.primary_section_id in section_ids:
                section_id = question.primary_section_id
            elif chart_chapters:
                chapter_id = chart_chapters.most_common(1)[0][0]
                candidates = [section for chapter in outline if chapter.chapter_id == chapter_id for section in chapter.sections]
                query = Counter(_tokenize(question.text))
                section_id = max(candidates or sections, key=lambda section: (
                    owners[section.section_id], self._score_text(f"{section.title} {section.purpose}", query),
                )).section_id
            elif owners:
                section_id = owners.most_common(1)[0][0]
            else:
                section_id = max(
                    sections, key=lambda section: self._score_text(
                        question.text, Counter(_tokenize(f"{section.title} {section.purpose}")),
                    ),
                ).section_id
            if section_id not in section_ids:
                section_id = sections[-1].section_id
            result.append({
                **question.model_dump(exclude={"relation_tags", "requirement_ids", "primary_section_id"}),
                "section_id": section_id,
                "requirements": [
                    {"requirement_id": entry.requirement_id, "label": entry.label,
                     "status": entry.coverage_state, "evidence_record_ids": list(entry.evidence_record_ids)}
                    for entry in linked
                ],
            })
        return result

    def summarize_question_answers(self, chapters) -> list[dict[str, Any]]:
        sections = {section.section_id: section for chapter in chapters for section in chapter.sections}
        answers = []
        for question in self.question_assignments:
            section = sections.get(question["section_id"])
            relevant_ids = {rid for row in question["requirements"] for rid in row["evidence_record_ids"]}
            if self.request.charts:
                relevant_ids.update(
                    rid for chart in self.charts if chart.chart_id in question["chart_ids"]
                    for rid in chart.evidence_ids if rid in self.report.evidence_index
                )
            linked_paragraphs = [
                paragraph for paragraph in section.paragraphs if relevant_ids.intersection(paragraph.evidence_ids)
            ] if section else []
            answers.append({
                "question_id": question["question_id"],
                "text": question["text"],
                "section_id": question["section_id"],
                "paragraph_ids": [paragraph.paragraph_id for paragraph in linked_paragraphs],
                "evidence_record_ids": sorted(relevant_ids.intersection(
                    rid for paragraph in linked_paragraphs for rid in paragraph.evidence_ids
                )),
                "chart_ids": [chart.chart_id for chart in self.charts
                              if chart.status == "ready" and chart.chart_id in question["chart_ids"]],
                "unmet_requirement_ids": [
                    row["requirement_id"] for row in question["requirements"] if row["status"] == "missing_data"
                ],
                "chart_gaps": question["chart_gaps"],
            })
        return answers

    def retrieve(self, chapter_id: str, outline_chapter: OutlineChapter) -> dict[str, Any]:
        # 1. Build chapter semantic query profile
        section_ids = {section.section_id for section in outline_chapter.sections}
        questions = [question for question in self.question_assignments if question["section_id"] in section_ids]
        question_evidence = {
            eid for question in questions for row in question["requirements"] for eid in row["evidence_record_ids"]
        }
        question_chart_ids = {cid for question in questions for cid in question["chart_ids"]}
        question_evidence.update(eid for chart in self.charts
                                 if chart.status == "ready" and chart.chart_id in question_chart_ids
                                 for eid in chart.evidence_ids)
        query_text = f"{outline_chapter.title} " + " ".join(
            f"{sec.title} {sec.purpose}" for sec in outline_chapter.sections
        )
        if questions:
            query_text += " " + " ".join(question["text"] for question in questions)
        query_tokens = Counter(_tokenize(query_text))

        # 2. Direct chart and evidence routing (100% fidelity)
        # Charts explicitly assigned to this chapter
        recommended_charts = [
            c for c in self.charts
            if c.status == "ready" and c.recommended_chapter_id == chapter_id
        ]
        chapter_chart_ids = {c.chart_id for c in recommended_charts}
        direct_evidence_ids: set[str] = set()
        for chart in recommended_charts:
            direct_evidence_ids.update(chart.evidence_ids)

        # 3. Score all insights dynamically
        scored_insights: list[tuple[float, dict[str, Any]]] = []
        for ins in self.report.insights:
            ins_dict = _dump(ins)
            text = f"{ins_dict.get('title', '')} {ins_dict.get('conclusion', '')} {ins_dict.get('significance', '')}"
            score = self._score_text(text, query_tokens)
            # Bonus if insight cites direct chart evidence
            if set(ins_dict.get("evidence_record_ids", [])) & (direct_evidence_ids | question_evidence):
                score += 5.0
            scored_insights.append((score, ins_dict))
        scored_insights.sort(key=lambda x: x[0], reverse=True)
        top_insights = [item for score, item in scored_insights[:8] if score > 0]

        # 4. Score content outlines
        scored_outlines: list[tuple[float, dict[str, Any]]] = []
        for sec in self.report.content_outline:
            sec_dict = _dump(sec)
            text = f"{sec_dict.get('heading', '')} {sec_dict.get('purpose', '')} {' '.join(sec_dict.get('key_points', []))}"
            score = self._score_text(text, query_tokens)
            scored_outlines.append((score, sec_dict))
        scored_outlines.sort(key=lambda x: x[0], reverse=True)
        top_outlines = [item for score, item in scored_outlines[:5] if score > 0]

        # 5. Score findings (key_metrics, trends, anomalies, cross_validations, knowledge_facts)
        candidate_findings: list[Any] = []
        for group in (
            self.report.key_metrics,
            self.report.trends,
            self.report.anomalies,
            self.report.cross_validations,
            self.report.knowledge_facts,
        ):
            candidate_findings.extend(group)

        scored_findings: list[tuple[float, dict[str, Any]]] = []
        for finding in candidate_findings:
            f_dict = _dump(finding)
            text = " ".join(str(v) for v in f_dict.values() if isinstance(v, (str, int, float)))
            score = self._score_text(text, query_tokens)
            eids = set(f_dict.get("evidence_record_ids", []))
            if eids & (direct_evidence_ids | question_evidence):
                score += 4.0
            scored_findings.append((score, f_dict))
        scored_findings.sort(key=lambda x: x[0], reverse=True)
        top_findings = [item for score, item in scored_findings[:25] if score > 0]

        top_insights, rejected_insights = filter_unverified_findings(top_insights, self.report.evidence_index)
        top_outlines, rejected_outlines = filter_unverified_findings(top_outlines, self.report.evidence_index)
        top_findings, rejected_findings = filter_unverified_findings(top_findings, self.report.evidence_index)

        # 6. Assemble candidate evidence IDs
        is_macro_relevant = chapter_id in ("CH-01", "CH-06")
        matrix = (self.report.data_quality_appendix or {}).get("requirement_evidence_matrix") or []
        chapter_domains = DOMAIN_AFFINITY.get(chapter_id, set())
        owner_by_requirement = {
            entry.requirement_id: entry.owner_section_id
            for entry in self.assignment_table.entries
        }
        owned_requirement_ids = {
            requirement_id
            for requirement_id, owner in owner_by_requirement.items()
            if owner in section_ids
        }
        # Requirement ownership is the primary router; unmapped requirements
        # keep the historical domain affinity fallback. A mapped requirement
        # owned by another chapter is intentionally not duplicated here.
        chapter_requirements: list[dict[str, Any]] = []
        requirements_by_id: dict[str, dict[str, Any]] = {}
        for row in matrix:
            if not isinstance(row, dict):
                continue
            requirement = row.get("requirement") or {}
            if not isinstance(requirement, dict):
                continue
            requirement_id = str(requirement.get("requirement_id") or "").strip()
            if not requirement_id:
                continue
            owner = owner_by_requirement.get(requirement_id)
            if owner is not None and owner not in section_ids:
                continue
            if owner is None and requirement.get("domain") not in chapter_domains:
                continue
            copied = dict(row)
            if owner is not None:
                copied["section_id"] = owner
            chapter_requirements.append(copied)
            requirements_by_id.setdefault(requirement_id, requirement)
        required_ids = {eid for row in chapter_requirements if row.get("requirement", {}).get("hard")
            for eid in row.get("coverage", {}).get("evidence_record_ids", [])}
        collected_eids: list[str] = sorted(direct_evidence_ids | required_ids | question_evidence)

        def _add_eids(eids: list[str]):
            for eid in eids:
                if not is_macro_relevant:
                    eref = self.report.evidence_index.get(eid)
                    if eref:
                        domain = getattr(eref, "domain", None) or (_dump(eref).get("domain"))
                        if domain == "macro":
                            continue
                collected_eids.append(eid)

        # Add evidence referenced by top insights, outlines, and findings
        for item in top_insights:
            _add_eids(item.get("evidence_record_ids", []))
        for item in top_outlines:
            _add_eids(item.get("evidence_record_ids", []))
        for item in top_findings:
            _add_eids(item.get("evidence_record_ids", []))

        # 7. Score all remaining evidence in evidence_index
        affinity_domains = DOMAIN_AFFINITY.get(chapter_id, set())
        scored_evidence: list[tuple[float, str]] = []
        for eid, eref in self.report.evidence_index.items():
            eref_dict = _dump(eref)
            domain = eref_dict.get("domain")
            # In non-macro chapters, skip irrelevant macro domain evidence unless directly cited by charts
            if domain == "macro" and not is_macro_relevant and eid not in direct_evidence_ids:
                continue

            text = f"{eref_dict.get('entity') or ''} {eref_dict.get('metric', '')} {eref_dict.get('value', '')} {eref_dict.get('domain', '')}"
            score = self._score_text(text, query_tokens)
            if domain in affinity_domains:
                score += 3.0
            if eid in direct_evidence_ids:
                score += 10.0
            scored_evidence.append((score, eid))

        scored_evidence.sort(key=lambda x: (-x[0], x[1]))
        for score, eid in scored_evidence[:40]:
            if score <= 0:
                continue
            collected_eids.append(eid)

        # Global shared baseline: ensure top 10 overall key metrics evidence is accessible (excluding macro in non-macro chapters)
        # Deduplicate and limit to valid evidence IDs
        candidates = list(dict.fromkeys(
            eid for eid in collected_eids if eid in self.report.evidence_index
        ))
        protected_ids = direct_evidence_ids | required_ids | question_evidence
        mandatory = [eid for eid in candidates if eid in protected_ids]
        optional = [eid for eid in candidates if eid not in protected_ids]
        final_eids = mandatory + optional[:max(0, 60 - len(mandatory))]
        retrieval_warnings = []
        rejected = rejected_insights + rejected_outlines + rejected_findings
        if rejected:
            retrieval_warnings.append(f"{chapter_id} 有 {rejected} 处上游叙述未通过证据审校，已从写作上下文移除")
        if not final_eids:
            retrieval_warnings.append(f"{chapter_id} 未检索到相关证据，需补充资料")
        if len(final_eids) < len(candidates):
            retrieval_warnings.append(f"{chapter_id} 证据候选超出预算，已省略 {len(candidates) - len(final_eids)} 条")

        evidence_dict = {
            eid: _dump(self.report.evidence_index[eid])
            for eid in final_eids
        }
        final_eid_set = set(final_eids)
        verdicts, verdict_diagnostics = _verdict_context(self.report, query_tokens, final_eid_set)
        analysis_facts = _analysis_fact_context(self.report, final_eid_set)
        semantic_checks = _semantic_check_context(self.report, final_eid_set)
        requirement_ids = {
            str(row.get("requirement", {}).get("requirement_id") or "")
            for row in chapter_requirements
        }
        question_coverage = [
            row for row in (getattr(self.request.charts, "question_coverage", None) or [])
            if isinstance(row, dict)
            and _coverage_row_belongs_to_chapter(
                row,
                chapter_requirement_ids=requirement_ids,
                owned_requirement_ids=owned_requirement_ids,
                chapter_chart_ids=chapter_chart_ids,
                requirements_by_id=requirements_by_id,
            )
        ][:4]
        suppressed_charts = [
            dict(
                title=str(row.get("title") or ""),
                requested_type=row.get("requested_type"),
                reason_code=str(row.get("reason_code") or ""),
                reason=str(row.get("reason") or "")[:120],
                evidence_ids=[eid for eid in row.get("evidence_ids", []) if eid in final_eid_set],
            )
            for row in (getattr(self.request.charts, "suppressed_charts", None) or [])
            if isinstance(row, dict) and (
                not row.get("evidence_ids")
                or set(row.get("evidence_ids", [])) & final_eid_set
            )
        ][:4]

        # 8. Filter charts: strictly prioritize recommended_chapter_id (Single-Placement Lock)
        ready_charts = [
            c for c in self.charts
            if (getattr(c, "status", None) == "ready" or (isinstance(c, dict) and c.get("status") == "ready"))
        ]
        matched_charts: list[dict[str, Any]] = []

        # Charts specifically recommended for this chapter
        for c in ready_charts:
            rec_id = getattr(c, "recommended_chapter_id", None) or (c.get("recommended_chapter_id") if isinstance(c, dict) else None)
            if rec_id == chapter_id:
                matched_charts.append(_chart_context(c, final_eid_set))

        # Only if a chart has NO recommended_chapter_id at all, allow fallback matching via evidence overlap (max 1 chart)
        unassigned_charts = [
            c for c in ready_charts
            if not (getattr(c, "recommended_chapter_id", None) or (isinstance(c, dict) and c.get("recommended_chapter_id")))
        ]
        for c in unassigned_charts:
            c_eids = set(getattr(c, "evidence_ids", []) or (c.get("evidence_ids", []) if isinstance(c, dict) else []))
            if c_eids & final_eid_set:
                matched_charts.append(_chart_context(c, final_eid_set))
                break

        result: dict[str, Any] = {
            "insights": top_insights,
            "outline_hints": top_outlines,
            "findings": top_findings,
            "evidence": evidence_dict,
            "charts": matched_charts,
            "hypothesis_verdicts": verdicts,
            "verdict_diagnostics": verdict_diagnostics,
            "analysis_facts": analysis_facts,
            "semantic_checks": semantic_checks,
            "question_coverage": question_coverage,
            "suppressed_charts": suppressed_charts,
            "comps_matrix": getattr(self.report, "comps_matrix", None),
            "industry_chain_segments": getattr(self.report, "industry_chain_segments", []),
            "financial_ratios": getattr(self.report, "financial_ratios", []),
            "data_quality": self.report.data_quality,
            "warnings": retrieval_warnings,
            "requirement_evidence_matrix": chapter_requirements,
        }
        if questions:
            available_charts = {chart["chart_id"] for chart in matched_charts}
            result["question_assignments"] = [
                {**question,
                 "chart_ids": [cid for cid in question["chart_ids"] if cid in available_charts],
                 "supporting_chart_sections": {
                     chart.chart_id: chart.recommended_chapter_id for chart in self.charts
                     if chart.chart_id in question["chart_ids"] and chart.status == "ready"
                     and chart.chart_id not in available_charts and chart.recommended_chapter_id
                 }}
                for question in questions
            ]
            if len(self.question_assignments) > len(questions):
                owned_ids = {question["question_id"] for question in questions}
                result["related_question_sections"] = {
                    question["question_id"]: question["section_id"]
                    for question in self.question_assignments if question["question_id"] not in owned_ids
                }
        if self.assignment_table.mode == "apply":
            section_rows = [
                row
                for section in outline_chapter.sections
                for row in assignments_for_section(self.assignment_table, section.section_id)
            ]
            hint, hint_diagnostics = build_assignment_guidance(section_rows)
            self.assignment_diagnostics.extend(hint_diagnostics)
            if hint:
                primary_eids = {eid for row in section_rows for eid in row.evidence_record_ids}

                def _relevance(item: dict[str, Any]) -> int:
                    return len(primary_eids.intersection(item.get("evidence_record_ids") or []))

                result["primary_requirements"] = assignment_rows_for_context(section_rows)
                result["assignment_hints"] = hint
                # Only the ordering of optional arguments changes. Mandatory
                # evidence, chart-bound evidence and requirement rows stay intact.
                result["insights"] = sorted(top_insights, key=lambda item: -_relevance(item))
                result["outline_hints"] = sorted(top_outlines, key=lambda item: -_relevance(item))
                result["findings"] = sorted(top_findings, key=lambda item: -_relevance(item))
        return result

    @staticmethod
    def _score_text(text: str, query_tokens: Counter[str]) -> float:
        """Compute relevance score between a target text and query tokens."""
        if not text or not query_tokens:
            return 0.0
        target_tokens = Counter(_tokenize(text))
        score = 0.0
        for token, q_count in query_tokens.items():
            t_count = target_tokens.get(token, 0)
            if t_count > 0:
                # TF weighting with saturation
                score += math.sqrt(q_count * t_count) * (1.5 if len(token) >= 3 else 1.0)
        return score
