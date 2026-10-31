"""Only explicit bilingual parenthetical aliases in supported spans are merged."""
import re


def normalize_identities(entities, assertions, evidence):
    by_id = {e.entity_id: e for e in entities}
    by_ev = {e.evidence_id: e for e in evidence}
    organizations = [e for e in entities if e.entity_type == 'organization'
                     and e.identity_status not in ('ambiguous', 'merged')]
    roots = {e.entity_id: e.entity_id for e in organizations}
    log = []

    def root(eid):
        while roots[eid] != eid:
            eid = roots[eid]
        return eid

    for a in organizations:
        for b in organizations:
            if a.entity_id >= b.entity_id or root(a.entity_id) == root(b.entity_id):
                continue
            # Cross-language aliases only; no parent/subsidiary or brand/legal-name guesses.
            if bool(re.search('[\u4e00-\u9fff]', a.canonical_name)) == bool(re.search('[\u4e00-\u9fff]', b.canonical_name)):
                continue
            patterns = [re.escape(x)+r'\s*[（(]\s*'+re.escape(y)+r'\s*[）)]'
                        for x,y in ((a.canonical_name,b.canonical_name),(b.canonical_name,a.canonical_name))]
            supporting = [c for c in assertions if c.status == 'supported' and c.subject_id in (a.entity_id,b.entity_id)
                          and any(any(re.search(p, by_ev[eid].quote) for p in patterns)
                                  for eid in c.evidence_ids if eid in by_ev)]
            if not supporting:
                continue
            survivor, merged = sorted((root(a.entity_id),root(b.entity_id)))
            roots[merged] = survivor
            log.append({'survivor_id': survivor, 'merged_id': merged,
                        'assertion_ids': [c.assertion_id for c in supporting], 'method': 'explicit_bilingual_parenthesis'})
    result = []
    for entity in entities:
        if entity.entity_id not in roots:
            result.append(entity)
            continue
        if root(entity.entity_id) != entity.entity_id:
            continue
        names = {e.canonical_name for e in organizations if root(e.entity_id) == entity.entity_id}
        aliases = set(entity.aliases) | names
        result.append(entity.model_copy(update={'aliases': sorted(aliases - {entity.canonical_name})}))
    claims = [c.model_copy(update={'subject_id': root(c.subject_id) if c.subject_id in roots else c.subject_id,
                                   'object_id': root(c.object_id) if c.object_id in roots else c.object_id}) for c in assertions]
    return result, claims, log
