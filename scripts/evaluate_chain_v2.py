"""Audit an actual v2 bundle. No synthetic precision or completeness score."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'agents_core'/'chain-research'))
from chain_research.models import ChainKnowledgeBundle
from chain_research.service import named_organization, current_fact_issue


def audit(path):
    bundle = ChainKnowledgeBundle.model_validate_json(path.read_text(encoding='utf-8'))
    entities = {e.entity_id: e for e in bundle.entities}
    evidence = {e.evidence_id: e for e in bundle.evidence}
    issues, organizations, activities = [], set(), set()
    for claim in bundle.supported_assertions():
        subject, obj = entities[claim.subject_id], entities[claim.object_id]
        if not claim.endpoint_ok(subject.entity_type, obj.entity_type):
            issues.append({'claim': claim.assertion_id, 'error': 'endpoint_type'})
        for ent in (subject, obj):
            if ent.entity_type == 'organization':
                organizations.add(ent.entity_id)
                if not named_organization(ent.canonical_name):
                    issues.append({'claim': claim.assertion_id, 'error': 'organization_identity'})
        if subject.entity_type == 'organization' and obj.entity_type == 'activity':
            activities.add(obj.entity_id)
        for eid in claim.evidence_ids:
            ev = evidence[eid]
            docpath = path.parent/'documents'/f'{ev.document_id}.raw'
            if not docpath.exists():
                issues.append({'claim': claim.assertion_id, 'error': 'source_snapshot_missing'})
                continue
            raw = docpath.read_bytes()
            text = raw.decode('utf-8')
            if hashlib.sha256(raw).hexdigest()[:32] != ev.content_hash:
                issues.append({'claim': claim.assertion_id, 'error': 'hash_mismatch'})
            if not ev.locator.startswith('chars:'):
                issues.append({'claim': claim.assertion_id, 'error': 'span_missing'})
            else:
                _, start, end = ev.locator.split(':')
                if text[int(start):int(end)] != ev.quote:
                    issues.append({'claim': claim.assertion_id, 'error': 'span_mismatch'})
            if current_fact_issue(ev.quote, bundle.scope.as_of):
                issues.append({'claim': claim.assertion_id, 'error': 'not_a_current_fact'})
    return {'run_id': bundle.run_id, 'release_status': bundle.quality.release_status,
        'dedicated_profile_used': False, 'activities_proposed': len(bundle.structure.activity_ids),
        'activities_with_supported_organizations': len(activities),
        'supported_assertions': len(bundle.supported_assertions()),
        'unresolved_assertions': sum(a.status == 'unresolved' for a in bundle.assertions),
        'supported_organizations': len(organizations), 'source_snapshots': len({e.document_id for e in bundle.evidence}),
        'critical_issues': issues, 'human_precision': 'not_evaluated',
        'golden_structure_recall': 'not_evaluated', 'business_acceptance_passed': False,
        'acceptance_reason': 'manual golden and full coverage not established',
        'budget': bundle.manifest.budget_snapshot.used.model_dump()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('bundle', type=Path)
    parser.add_argument('--write-report', action='store_true')
    parser.add_argument('--require-verified', action='store_true')
    args = parser.parse_args()
    result = audit(args.bundle)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.write_report:
        (args.bundle.parent/'audit.json').write_text(text, encoding='utf-8')
    sys.exit(1 if result['critical_issues'] or (args.require_verified and not result['business_acceptance_passed']) else 0)
