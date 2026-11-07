"""Map requirements to actual output citations without claiming question coverage."""
from typing import Any


def link_requirement_outputs(matrix: list[dict[str, Any]], chapters: list[Any], charts: list[Any]) -> list[dict[str, Any]]:
    paragraphs = [(p.paragraph_id, set(p.evidence_ids)) for c in chapters for s in c.sections for p in s.paragraphs]
    figures = [(c.chart_id, set(c.evidence_ids)) for c in charts]
    result = []
    for row in matrix:
        requirement = row.get('requirement') or {}
        coverage = row.get('coverage') or {}
        ids = set(coverage.get('evidence_record_ids') or [])
        pids = [pid for pid, refs in paragraphs if ids & refs]
        cids = [cid for cid, refs in figures if ids & refs]
        cited = set().union(*(refs & ids for _, refs in paragraphs + figures)) if ids else set()
        result.append({'requirement_id': requirement.get('requirement_id'), 'label': requirement.get('label'),
            'hard': requirement.get('hard', True), 'evidence_record_ids': sorted(ids),
            'cited_evidence_record_ids': sorted(cited), 'uncited_evidence_record_ids': sorted(ids - cited),
            'citation_coverage': 'none' if not cited else 'complete' if cited == ids else 'partial',
            'paragraph_ids': pids, 'chart_ids': cids,
            'status': 'missing_data' if not coverage.get('passed') else 'cited' if pids or cids else 'not_cited'})
    return result
