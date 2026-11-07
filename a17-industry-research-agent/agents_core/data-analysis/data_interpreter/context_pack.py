"""Prepare compact, evidence-bounded analysis inputs without hiding required cells."""
from typing import Any
from agents_core.context_budget import ContextBudgetExceeded, serialize_context


def compact_requirement_matrix(matrix: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for item in matrix:
        requirement = item.get('requirement') or {}
        coverage = item.get('coverage') or {}
        rows.append({
            'requirement': {key: requirement[key] for key in ('requirement_id', 'label', 'domain', 'hard', 'entity_names', 'period_ends', 'metric_families') if key in requirement},
            'coverage': {key: coverage[key] for key in ('passed', 'evidence_record_ids', 'missing') if key in coverage},
        })
    return rows


def compact_analysis_facts(facts: dict[str, Any], allowed_ids: set[str]) -> dict[str, Any]:
    result = {}
    for category, rows in facts.items():
        if not isinstance(rows, list):
            result[category] = rows
            continue
        kept = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            ids = set(row.get('evidence_record_ids') or [])
            ids.update(row[key] for key in ('record_id', 'from_record_id', 'to_record_id') if row.get(key))
            if ids and ids <= allowed_ids:
                kept.append(row)
        result[category] = kept
    return result


def compact_findings(findings: dict[str, Any], allowed_ids: set[str]) -> dict[str, Any]:
    result = dict(findings)
    if 'requirement_evidence_matrix' in result:
        result['requirement_evidence_matrix'] = compact_requirement_matrix(result['requirement_evidence_matrix'])
    if 'analysis_facts' in result:
        result['analysis_facts'] = compact_analysis_facts(result['analysis_facts'], allowed_ids)
    if isinstance(result.get('sensitivity_results'), list):
        result['sensitivity_results'] = [row for row in result['sensitivity_results']
            if isinstance(row, dict) and len(row.get('input_record_ids') or []) == 2
            and set(row['input_record_ids']) <= allowed_ids]
    for name in ('key_metrics', 'trends', 'anomalies', 'cross_validations', 'industry_chain'):
        rows = result.get(name)
        if isinstance(rows, list):
            result[name] = [row for row in rows if isinstance(row, dict)
                and row.get('evidence_record_ids')
                and set(row['evidence_record_ids']) <= allowed_ids]
    matrix = result.get('comps_matrix')
    if isinstance(matrix, dict):
        entries = [entry for entry in matrix.get('entries', []) if isinstance(entry, dict)
            and entry.get('evidence_record_ids') and set(entry['evidence_record_ids']) <= allowed_ids]
        result['comps_matrix'] = {'entries': entries, 'partial': len(entries) != len(matrix.get('entries', []))}
    return result


def prepare_analysis_context(payload: dict[str, Any], system: str) -> tuple[str, dict[str, Any]]:
    """Fit optional findings while keeping user request, requirements and evidence intact."""
    packet = dict(payload)
    original = payload.get('deterministic_findings') or {}
    packet['deterministic_findings'] = compact_findings(original, set(payload.get('evidence_index') or {}))
    details: dict[str, Any] = {'omitted_sections': [], 'evidence_count': len(payload.get('evidence_index') or {})}
    packet['context_packing'] = details
    candidates = ('comps_matrix', 'financial_ratios', 'anomalies', 'cross_validations', 'industry_chain', 'trends', 'key_metrics', 'analysis_facts')
    for name in (*candidates, 'skill_results.details', 'skill_results.summary', None):
        try:
            text, size, budget = serialize_context(packet, system=system)
            details.update(bytes=size, budget_bytes=budget)
            # Size metadata itself slightly changes serialization; verify again.
            text, size, budget = serialize_context(packet, system=system)
            details.update(bytes=size, budget_bytes=budget)
            return text, details
        except ContextBudgetExceeded:
            if name is None:
                raise
            if name == 'skill_results.summary':
                results = packet.get('skill_results') or []
                if any('summary' in result for result in results):
                    packet['skill_results'] = [{key: value for key, value in result.items() if key != 'summary'} for result in results]
                    details['omitted_sections'].append(name)
                continue
            if name == 'skill_results.details':
                results = packet.get('skill_results')
                if results:
                    allowed = set(payload.get('evidence_index') or {})
                    compacted = []
                    for result in results:
                        ids = result.get('evidence_record_ids') or []
                        row = {key: result[key] for key in ('skill_name', 'task_id', 'status') if key in result}
                        row['evidence_record_ids'] = [rid for rid in ids if rid in allowed]
                        if ids and set(ids) <= allowed:
                            row['summary'] = result.get('summary', '')
                        compacted.append(row)
                    packet['skill_results'] = compacted
                    details['omitted_sections'].append(name)
                continue
            value = packet['deterministic_findings'].get(name)
            if value:
                details['omitted_sections'].append(name)
                packet['deterministic_findings'][name] = None if isinstance(value, dict) else []
    raise AssertionError('unreachable')
