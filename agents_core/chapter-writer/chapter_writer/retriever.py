"""Dynamic evidence and context retriever for chapter writing."""

from __future__ import annotations

from collections import Counter
import math
import re
from typing import Any

from chapter_writer.models import ChapterWritingRequest, OutlineChapter

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

    def retrieve(self, chapter_id: str, outline_chapter: OutlineChapter) -> dict[str, Any]:
        # 1. Build chapter semantic query profile
        query_text = f"{outline_chapter.title} " + " ".join(
            f"{sec.title} {sec.purpose}" for sec in outline_chapter.sections
        )
        query_tokens = Counter(_tokenize(query_text))

        # 2. Direct chart and evidence routing (100% fidelity)
        # Charts explicitly assigned to this chapter
        recommended_charts = [
            c for c in self.charts
            if c.status == "ready" and c.recommended_chapter_id == chapter_id
        ]
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
            if set(ins_dict.get("evidence_record_ids", [])) & direct_evidence_ids:
                score += 5.0
            scored_insights.append((score, ins_dict))
        scored_insights.sort(key=lambda x: x[0], reverse=True)
        top_insights = [item for _, item in scored_insights[:8]]

        # 4. Score content outlines
        scored_outlines: list[tuple[float, dict[str, Any]]] = []
        for sec in self.report.content_outline:
            sec_dict = _dump(sec)
            text = f"{sec_dict.get('heading', '')} {sec_dict.get('purpose', '')} {' '.join(sec_dict.get('key_points', []))}"
            score = self._score_text(text, query_tokens)
            scored_outlines.append((score, sec_dict))
        scored_outlines.sort(key=lambda x: x[0], reverse=True)
        top_outlines = [item for _, item in scored_outlines[:5]]

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
            if eids & direct_evidence_ids:
                score += 4.0
            scored_findings.append((score, f_dict))
        scored_findings.sort(key=lambda x: x[0], reverse=True)
        top_findings = [item for _, item in scored_findings[:25]]

        # 6. Assemble candidate evidence IDs
        is_macro_relevant = chapter_id in ("CH-01", "CH-06")
        collected_eids: list[str] = list(direct_evidence_ids)

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

        scored_evidence.sort(key=lambda x: x[0], reverse=True)
        for _, eid in scored_evidence[:40]:
            collected_eids.append(eid)

        # Global shared baseline: ensure top 10 overall key metrics evidence is accessible (excluding macro in non-macro chapters)
        for km in self.report.key_metrics[:10]:
            km_dict = _dump(km)
            for eid in km_dict.get("evidence_record_ids", []):
                if not is_macro_relevant:
                    eref = self.report.evidence_index.get(eid)
                    if eref:
                        domain = getattr(eref, "domain", None) or (_dump(eref).get("domain"))
                        if domain == "macro":
                            continue
                collected_eids.append(eid)

        # Deduplicate and limit to valid evidence IDs
        final_eids = list(dict.fromkeys(
            eid for eid in collected_eids if eid in self.report.evidence_index
        ))[:60]

        # If somehow empty (e.g. synthetic test with no overlaps), take first 25
        if not final_eids:
            final_eids = list(self.report.evidence_index)[:25]

        evidence_dict = {
            eid: _dump(self.report.evidence_index[eid])
            for eid in final_eids
        }

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
                matched_charts.append(_dump(c))

        # Only if a chart has NO recommended_chapter_id at all, allow fallback matching via evidence overlap (max 1 chart)
        unassigned_charts = [
            c for c in ready_charts
            if not (getattr(c, "recommended_chapter_id", None) or (isinstance(c, dict) and c.get("recommended_chapter_id")))
        ]
        for c in unassigned_charts:
            c_eids = set(getattr(c, "evidence_ids", []) or (c.get("evidence_ids", []) if isinstance(c, dict) else []))
            if c_eids & set(final_eids):
                matched_charts.append(_dump(c))
                break

        return {
            "insights": top_insights,
            "outline_hints": top_outlines,
            "findings": top_findings,
            "evidence": evidence_dict,
            "charts": matched_charts,
            "comps_matrix": getattr(self.report, "comps_matrix", None),
            "industry_chain_segments": getattr(self.report, "industry_chain_segments", []),
            "financial_ratios": getattr(self.report, "financial_ratios", []),
            "data_quality": self.report.data_quality,
            "warnings": self.report.warnings,
        }

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
