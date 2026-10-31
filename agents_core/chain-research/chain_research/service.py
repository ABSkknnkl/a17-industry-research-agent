"""Evidence-first research. Provider/model transports are injected, not agents."""
from __future__ import annotations

import hashlib
import json
import time
import re
from urllib.parse import urlparse

from .models import (
    BundleManifest, ChainAssertion, ChainEntity, ChainEvidence,
    ChainKnowledgeBundle, ChainQualityReport, ChainResearchRequest, ChainStructure,
    Predicate, Qualifiers, Verification, stable_id,
)
from .providers import RunContext


def json_object(raw):
    if isinstance(raw, dict):
        return raw
    text = str(raw).strip().removeprefix('```json').removeprefix('```').removesuffix('```')
    return json.loads(text[text.index('{'):text.rindex('}') + 1])


def named_organization(name):
    """Reject explicit lists and generic actor classes, not unfamiliar companies."""
    return bool(name.strip()) and not any(s in name for s in ('、', '等企业', '等厂商', '等公司')) and not re.search(
        r'(?:行业|产业链|生产企业|生产厂商|销售渠道|整机厂商|零部件供应商)$', name)


def current_fact_issue(quote, as_of):
    year = int(str(as_of)[:4])
    if any(int(y) > year for y in re.findall(r'(?<!\d)(20\d{2})\s*年', quote)):
        return 'future_period'
    if any(w in quote for w in ('据称', '计划于', '拟于', '预计将', '打算', '将在')):
        return 'unconfirmed_or_planned'
    return None


class ChainResearchService:
    def __init__(self, search, fetch, llm, store):
        self.search, self.fetch, self.llm, self.store = search, fetch, llm, store

    async def research(self, request: ChainResearchRequest, *, emit=None):
        from .profiles import resolve_profile
        from .membership import activity_id, apply_memberships
        from .providers import ProviderError
        from .document_text import relevant_context
        started = time.monotonic()
        ctx = RunContext(request.run_id, request.scope, request.budget.model_copy(deep=True))
        profile = resolve_profile(request.scope, strategy=request.research_strategy, profile_id=request.profile_id)
        strategy = 'profile_guided' if profile else 'explore'
        documents, snippets, errors, attempted = {}, [], [], set()
        assertions, evidence, entities, activities, stages = {}, {}, {}, {}, {}
        processed = set()
        decisions = []
        # Reserve actual fetch attempts for each purpose, including failures.
        limit = request.budget.max_document_fetches
        quotas = {'structure': limit // 4, 'company': limit // 2}
        quotas['gap'] = limit - sum(quotas.values())
        spent = dict.fromkeys(quotas, 0)
        search_limit = request.budget.max_search_requests
        search_quotas = {'structure': search_limit // 4, 'company': search_limit // 2}
        search_quotas['gap'] = search_limit - sum(search_quotas.values())
        searches = dict.fromkeys(quotas, 0)

        async def event(name, **details):
            self.store.append_transformation({'event': name, **details})
            if emit:
                await emit({'event': name, 'details': details})

        async def ask(task, payload):
            ctx.budget.used.wall_seconds = time.monotonic() - started
            ctx.charge_llm()
            result = json_object(await self.llm(task, payload))
            self.store.append_transformation({'event': 'model_output', 'task': task, 'output': result})
            return result

        async def retrieve(queries, purpose):
            for query in queries:
                if spent[purpose] >= quotas[purpose] or searches[purpose] >= search_quotas[purpose]:
                    break
                ctx.budget.used.wall_seconds = time.monotonic() - started
                try:
                    searches[purpose] += 1
                    res = await self.search.search_raw(query, ctx, count=6)
                    self.store.append_query_log({'query': query, 'purpose': purpose, 'hits': res.hits})
                    await event('chain_search', query=query, purpose=purpose, hits=len(res.hits))
                    for hit in res.hits:
                        snippets.append(hit)
                        url = hit.get('url')
                        if not url or url in attempted or spent[purpose] >= quotas[purpose]:
                            continue
                        attempted.add(url)
                        spent[purpose] += 1
                        try:
                            doc = await self.fetch.fetch(url, ctx)
                            text = doc.text
                            if len(text.strip()) < 150:
                                continue
                            did = stable_id('doc', url)
                            digest = hashlib.sha256(text.encode()).hexdigest()[:32]
                            ev = ChainEvidence(evidence_id=stable_id('document', url), document_id=did,
                                url=url, title=hit.get('title') or url, document_kind='other',
                                content_hash=digest, source_family=urlparse(url).hostname or url,
                                locator='document', quote=text[:200])
                            self.store.save_document(did, text.encode(), evidence=ev,
                                scope_subject=request.scope.subject, as_of=request.scope.as_of,
                                source_policy=ctx.source_policy)
                            documents[url] = {'id': did, 'title': ev.title, 'url': url,
                                              'text': text, 'hash': digest}
                            await event('chain_document', url=url, purpose=purpose, characters=len(text))
                        except Exception as exc:
                            errors.append({'step': 'fetch', 'url': url, 'error': str(exc)[:250]})
                except Exception as exc:
                    errors.append({'step': 'search', 'query': query, 'error': str(exc)[:250]})

        topic = request.scope.subject
        await retrieve([f'{topic} 产业链 产品构成 制造工艺 研究报告'], 'structure')
        structure = {}
        if profile:
            for policy in profile.activities:
                eid = activity_id(profile, request.scope, policy.activity_key)
                entities[eid] = ChainEntity(entity_id=eid, entity_type='activity', canonical_name=policy.name)
                activities[policy.name] = eid
                stages[eid] = policy.stage
            # Interleave stages so upstream cannot consume every initial search.
            groups = [[q for a in profile.activities if a.stage == stage
                       and a.company_display_policy not in ('process', 'scenario') for q in a.search_terms]
                      for stage in ('upstream', 'midstream', 'downstream', 'support')]
            queries = [group[i] for i in range(max(map(len, groups), default=0)) for group in groups if i < len(group)]
        else:
            structure = await ask('discover', {'scope': request.scope.model_dump(),
                'sources': [{'id': d['id'], 'title': d['title'], 'text': d['text'][:14000]}
                            for d in documents.values()], 'search_leads_only': snippets[:12]})
            for row in structure.get('activities', []):
                name = str(row.get('name', '')).strip()
                if not name:
                    continue
                eid = stable_id('activity', request.scope.scope_id, name)
                entities[eid] = ChainEntity(entity_id=eid, entity_type='activity', canonical_name=name)
                activities[name] = eid
                stages[eid] = row.get('stage') if row.get('stage') in (
                    'upstream', 'midstream', 'downstream', 'support') else 'support'
            queries = [str(q) for q in structure.get('queries', []) if str(q).strip()][:4]
        await retrieve(queries, 'company')

        async def process_documents():
            for doc in list(documents.values()):
                if doc['id'] in processed:
                    continue
                try:
                    terms = list(activities)
                    if profile:
                        terms += [x for c in profile.categories for x in c.aliases]
                    extracted = await ask('extract', {'scope': request.scope.model_dump(),
                        'activities': list(activities),
                        'allowed_roles': sorted({r for a in profile.activities for r in a.allowed_roles}) if profile else [],
                        'document': {'id': doc['id'], 'title': doc['title'], 'url': doc['url'],
                                     'text': relevant_context(doc['text'], terms)}})
                    candidates = []
                    for row in extracted.get('claims', []):
                        quote = str(row.get('quote', ''))
                        pos = doc['text'].find(quote) if quote.strip() else -1
                        if pos < 0:
                            continue
                        try:
                            pred = Predicate(row['predicate'])
                            refs = []
                            for name, kind in zip((row['subject'], row['object']),
                                                  (row['subject_type'], row['object_type'])):
                                if kind == 'organization' and not named_organization(name):
                                    raise ValueError('not a single named organization')
                                if kind == 'product' and name.strip() in ('轻薄设计', '硬核电竞', '轻薄', '高性能'):
                                    raise ValueError('marketing attribute is not an independent product')
                                eid = activities.get(name) if kind == 'activity' else None
                                if kind == 'activity' and not eid:
                                    raise ValueError('unknown activity')
                                eid = eid or stable_id(kind, request.scope.scope_id, name)
                                refs.append(ChainEntity(entity_id=eid, entity_type=kind, canonical_name=name))
                            qualifier = Qualifiers(org_role=row.get('role'),
                                applicable_products=row.get('applicable_products') or [],
                                valid_period=row.get('valid_period'))
                            ev_id = stable_id('ev', doc['id'], str(pos), quote)
                            claim = ChainAssertion(assertion_id=stable_id('claim', refs[0].entity_id,
                                pred.value, refs[1].entity_id, qualifier.model_dump_json()),
                                subject_id=refs[0].entity_id, predicate=pred, object_id=refs[1].entity_id,
                                qualifiers=qualifier, evidence_ids=[ev_id])
                            if not claim.endpoint_ok(refs[0].entity_type, refs[1].entity_type):
                                continue
                            ev = ChainEvidence(evidence_id=ev_id, document_id=doc['id'], url=doc['url'],
                                title=doc['title'], content_hash=doc['hash'],
                                source_family=urlparse(doc['url']).hostname or doc['url'],
                                locator=f'chars:{pos}:{pos+len(quote)}', quote=quote)
                            candidates.append((claim, refs, ev, row))
                        except (KeyError, ValueError, TypeError):
                            continue
                    if candidates:
                        checked = await ask('verify', {'scope': request.scope.model_dump(),
                            'document_url': doc['url'], 'document_title': doc['title'],
                            'checks': [{'id': c.assertion_id, 'claim': row, 'context': doc['text'][
                                max(0, doc['text'].find(ev.quote)-300):doc['text'].find(ev.quote)+len(ev.quote)+300]}
                                for c, refs, ev, row in candidates]})
                        verdicts = {v.get('id'): v for v in checked.get('checks', [])}
                        for claim, refs, ev, row in candidates:
                            verdict = verdicts.get(claim.assertion_id, {})
                            issue = current_fact_issue(ev.quote, request.scope.as_of)
                            ok = (verdict.get('supported') is True and bool(verdict.get('reason'))
                                  and verdict.get('primary_source') is True and verdict.get('in_scope') is True
                                  and not issue)
                            if claim.predicate == Predicate.SUPPLIES_TO and not claim.qualifiers.applicable_products:
                                ok = False
                            # Model-proposed taxonomy never becomes an accepted policy mapping.
                            if claim.predicate in (Predicate.IS_A, Predicate.PART_OF):
                                ok = False
                            claim = claim.model_copy(update={'status': 'supported' if ok else 'unresolved',
                                'verification': Verification(method='model_assisted' if ok else 'unverified',
                                    verifier_version='primary_scope_v4', rationale=issue or verdict.get('reason') or 'not confirmed',
                                    supporting_evidence_ids=[ev.evidence_id] if ok else [])})
                            for entity in refs:
                                entities[entity.entity_id] = entity
                            evidence[ev.evidence_id] = ev
                            assertions[claim.assertion_id] = claim
                    processed.add(doc['id'])
                except ProviderError as exc:
                    errors.append({'step': 'process', 'error': str(exc)[:250]})
                    break

        await process_documents()
        # Verification happens BEFORE gap selection; do not spend all reads on initial reviews.
        if profile:
            _, decisions = apply_memberships(profile, request.scope, list(entities.values()),
                                              list(assertions.values()), list(evidence.values()))
            admitted = {d.activity_key for d in decisions if d.status == 'accepted'}
            gaps = [a for a in profile.activities if a.required and a.category_ids and a.activity_key not in admitted]
            # Reverse stage order gives downstream/support a turn after upstream-heavy first pass.
            gap_queries = [q for a in reversed(gaps) for q in a.search_terms]
        else:
            try:
                questions = await ask('gap_queries', {'scope': request.scope.model_dump(),
                    'activities': list(activities), 'leads': snippets[:36]})
                gap_queries = [str(q) for q in questions.get('queries', [])][:4]
            except ProviderError as exc:
                errors.append({'step': 'gap_queries', 'error': str(exc)[:250]})
                gap_queries = []
        before = len(documents)
        if request.budget.max_rounds > 1:
            await retrieve(gap_queries, 'gap')
            if len(documents) > before:
                await process_documents()
        if profile:
            from .identity import normalize_identities
            normalized, source_claims, merges = normalize_identities(
                list(entities.values()), list(assertions.values()), list(evidence.values()))
            entities = {e.entity_id: e for e in normalized}
            assertions = {a.assertion_id: a for a in source_claims}
            if merges:
                await event('chain_identity_normalization', merges=merges)
            final, decisions = apply_memberships(profile, request.scope, list(entities.values()),
                                                 list(assertions.values()), list(evidence.values()))
            assertions = {a.assertion_id: a for a in final}
        supported = [a for a in assertions.values() if a.status == 'supported']
        covered = {r for a in supported for r in (a.subject_id, a.object_id) if r in stages}
        company_covered = {a.object_id for a in supported if a.object_id in stages
                           and entities[a.subject_id].entity_type == 'organization'}
        required = ([activity_id(profile, request.scope, a.activity_key) for a in profile.activities if a.required]
                    if profile else list(activities.values()))
        eligible = ([a.activity_key for a in profile.activities if a.company_display_policy in ('representative', 'executor')]
                    if profile else [])
        accepted = {d.activity_key for d in decisions if d.status == 'accepted'}
        coverage = len(accepted & set(eligible))/len(eligible) if eligible else None
        ctx.budget.used.wall_seconds = time.monotonic() - started
        ctx.budget.used.rounds = min(2, request.budget.max_rounds)
        basis = 'profile_policy' if profile else 'llm_candidate_only'
        unresolved = ['画像及结构尚未独立审定' if profile else '行业结构完整性尚未独立确认']
        unresolved += [f'{a.assertion_id}:关系未获支持' for a in assertions.values() if a.status != 'supported']
        unresolved += [f'{d.activity_key}:{d.reason_codes}' for d in decisions if d.status != 'accepted']
        quality = ChainQualityReport(release_status='partial' if (covered or (profile and supported)) else 'draft',
            coverage_basis=basis, evidence_trace_rate=1.0 if supported else None,
            coverage_values={'activities': len(activities), 'activities_with_supported_facts': len(covered),
                'supported_assertions': len(supported), 'documents': len(documents),
                'activities_with_supported_organizations': len(company_covered),
                'view_stages': stages, 'provider_errors': errors, 'fetch_quota': quotas, 'fetch_spent': spent,
                'search_quota': search_quotas, 'search_spent': searches,
                'company_eligible_activity_count': len(eligible), 'company_activity_coverage': coverage,
                'presentation_ready': False,
                'presentation_candidate': bool(coverage is not None and coverage >= .8 and not errors),
                'profile_review_status': profile.status if profile else None},
            unresolved=unresolved, reason_codes=['completeness_not_certified'])
        bundle = ChainKnowledgeBundle(run_id=request.run_id, scope=request.scope,
            entities=list(entities.values()), assertions=list(assertions.values()), evidence=list(evidence.values()),
            profile_snapshot=profile, membership_decisions=decisions,
            structure=ChainStructure(structure_id=stable_id('structure', request.scope.scope_id),
                scope_id=request.scope.scope_id, activity_ids=list(activities.values()),
                required_activity_ids=required, coverage_basis=basis, unresolved=unresolved[:1]),
            quality=quality, manifest=BundleManifest(run_id=request.run_id, scope_subject=topic,
                research_strategy=strategy, profile_id=profile.profile_id if profile else None,
                profile_version=profile.version if profile else None, budget_snapshot=ctx.budget,
                source_policy_version=ctx.source_policy,
                prompt_versions={'research': 'competition-profile-v1'},
                notes=['Policy admission is deterministic; source semantics are model-assisted; no human certification.',
                       'Source and profile content need review before competition use.']))
        self.store.save_bundle(bundle)
        await event('chain_research_completed', quality=quality.model_dump())
        return bundle

async def reverify_bundle(path, llm, store, *, emit=None):
    """A1 incremental source recheck; preserves the original run and raw snapshots."""
    from pathlib import Path
    path = Path(path)
    bundle = ChainKnowledgeBundle.model_validate_json(path.read_text(encoding='utf-8'))
    (path.parent/f'bundle.revision-{bundle.revision}.json').write_text(
        bundle.model_dump_json(indent=2), encoding='utf-8')
    by_entity = {e.entity_id: e for e in bundle.entities}
    by_ev = {e.evidence_id: e for e in bundle.evidence}
    groups = {}
    for claim in bundle.supported_assertions():
        if claim.qualifiers.extra.get('membership_decision_id'):
            continue
        ev = by_ev[claim.evidence_ids[0]]
        groups.setdefault(ev.document_id, []).append(claim)
    ctx = RunContext(bundle.run_id, bundle.scope, bundle.manifest.budget_snapshot.model_copy(deep=True))
    decisions = {}
    for did, claims in groups.items():
        text = (path.parent/'documents'/f'{did}.raw').read_text(encoding='utf-8')
        checks = []
        for c in claims:
            ev = by_ev[c.evidence_ids[0]]
            checks.append({'id': c.assertion_id, 'claim': {
                'subject': by_entity[c.subject_id].canonical_name,
                'predicate': c.predicate.value, 'object': by_entity[c.object_id].canonical_name,
                'quote': ev.quote}, 'context': text[max(0,text.find(ev.quote)-300):text.find(ev.quote)+len(ev.quote)+300]})
        ctx.charge_llm()
        ev = by_ev[claims[0].evidence_ids[0]]
        response = json_object(await llm('verify', {'scope': bundle.scope.model_dump(),
            'document_url': ev.url, 'document_title': ev.title, 'checks': checks}))
        store.append_transformation({'event': 'scope_reverification', 'document_id': did, 'output': response})
        decisions.update({v['id']: v for v in response.get('checks', []) if 'id' in v})
    updated = []
    for c in bundle.assertions:
        if c.qualifiers.extra.get('membership_decision_id'):
            continue
        if c.status != 'supported':
            updated.append(c)
            continue
        verdict = decisions.get(c.assertion_id, {})
        ev = by_ev[c.evidence_ids[0]]
        keep = (verdict.get('supported') is True and verdict.get('in_scope') is True
                and verdict.get('primary_source') is True and not current_fact_issue(ev.quote, bundle.scope.as_of))
        updated.append(c.model_copy(update={'status': 'supported' if keep else 'unresolved',
            'verification': Verification(method='model_assisted' if keep else 'unverified',
                verifier_version='scope_primary_v3', rationale=verdict.get('reason') or 'scope/primary confirmation absent',
                supporting_evidence_ids=c.evidence_ids if keep else [])}))
    revision = bundle.revision + 1
    manifest = bundle.manifest.model_copy(update={'revision': revision,
        'budget_snapshot': ctx.budget, 'notes': bundle.manifest.notes+[
            'Incremental real-LLM scope recheck using original retrieved documents; no new web search.']})
    membership_decisions = []
    if bundle.profile_snapshot:
        from .membership import apply_memberships
        updated, membership_decisions = apply_memberships(bundle.profile_snapshot, bundle.scope,
            bundle.entities, updated, bundle.evidence)
    supported = [a for a in updated if a.status == 'supported']
    cov = dict(bundle.quality.coverage_values)
    cov['supported_assertions'] = len(supported)
    cov['activities_with_supported_facts'] = len({eid for a in supported
        for eid in (a.subject_id, a.object_id) if eid in bundle.structure.activity_ids})
    cov['activities_with_supported_organizations'] = len({a.object_id for a in supported
        if by_entity[a.subject_id].entity_type == 'organization' and by_entity[a.object_id].entity_type == 'activity'})
    if bundle.profile_snapshot:
        eligible = {a.activity_key for a in bundle.profile_snapshot.activities
                    if a.company_display_policy in ('representative', 'executor')}
        accepted = {d.activity_key for d in membership_decisions if d.status == 'accepted'}
        cov['company_activity_coverage'] = len(accepted & eligible)/len(eligible) if eligible else None
        cov['presentation_ready'] = False  # Incremental fact recheck does not certify visual review.
    quality = bundle.quality.model_copy(update={'coverage_values': cov,
        'release_status': 'partial' if supported else 'draft',
        'evidence_trace_rate': 1.0 if supported else None,
        'unresolved': ['结构完整性尚未认证']+[a.assertion_id for a in updated if a.status == 'unresolved']})
    bundle = ChainKnowledgeBundle.model_validate(bundle.model_copy(update={
        'revision': revision, 'manifest': manifest, 'quality': quality, 'assertions': updated,
        'membership_decisions': membership_decisions}).model_dump())
    store.save_bundle(bundle)
    return bundle
