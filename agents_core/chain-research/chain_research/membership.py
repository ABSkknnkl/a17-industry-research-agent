"""Deterministic admission under a versioned policy, not a truth oracle."""
import re

from .models import ChainAssertion, MembershipDecision, Predicate, Qualifiers, Verification, stable_id


def norm(text):
    return re.sub(r'\s+', '', text).casefold()


def contains_term(text, term):
    if re.fullmatch(r'[a-zA-Z0-9 -]+', term):
        return bool(re.search(r'(?<![a-z0-9])' + re.escape(term.casefold()) + r'(?![a-z0-9])', text.casefold()))
    return norm(term) in norm(text)


def activity_id(profile, scope, key):
    return stable_id('activity', scope.scope_id, profile.profile_id, key)


def decide_memberships(profile, scope, entities, assertions, evidence):
    by_entity = {e.entity_id: e for e in entities}
    by_evidence = {e.evidence_id: e for e in evidence}
    categories = {c.category_id: c for c in profile.categories}
    decisions = []
    for org in [e for e in entities if e.entity_type == 'organization']:
        offers = [a for a in assertions if a.subject_id == org.entity_id and a.predicate == Predicate.OFFERS]
        for activity in profile.activities:
            if activity.company_display_policy in ('process', 'scenario'):
                continue
            accepted, rejected, taxonomy, reasons = [], [], [], []
            for claim in offers:
                if claim.status != 'supported':
                    continue
                product = by_entity[claim.object_id]
                matching = [categories[c] for c in activity.category_ids
                            if norm(product.canonical_name) in {norm(x) for x in categories[c].aliases}]
                if not matching:
                    continue
                for category in matching:
                    # Same source span must support application; unrelated quotes cannot supply it.
                    quotes = [by_evidence[e].quote for e in claim.evidence_ids if e in by_evidence]
                    if any(any(contains_term(q, t) for t in category.excluded_terms) for q in quotes):
                        rejected.append(claim.assertion_id)
                        reasons.append('explicit_application_exclusion')
                        continue
                    if org.identity_status in ('ambiguous', 'merged'):
                        reasons.append('identity_unresolved')
                        continue
                    if claim.qualifiers.org_role not in activity.allowed_roles:
                        reasons.append('role_not_admitted')
                        continue
                    if category.application_terms and not any(
                            any(contains_term(q, t) for t in category.application_terms) for q in quotes):
                        reasons.append('application_unconfirmed')
                        continue
                    accepted.append(claim.assertion_id)
                    taxonomy.extend([profile.profile_id + '/' + category.category_id, *category.source_refs])
            status = 'rejected' if rejected else 'accepted' if accepted else 'unknown'
            decisions.append(MembershipDecision(
                decision_id=stable_id('membership', scope.scope_id, profile.profile_id, profile.version,
                                      org.entity_id, activity.activity_key),
                organization_id=org.entity_id, activity_key=activity.activity_key, status=status,
                profile_version=profile.version,
                input_assertion_ids=sorted(set(accepted + rejected)), taxonomy_refs=sorted(set(taxonomy)),
                reason_codes=sorted(set(reasons)) or [
                    'product_application_role_match' if accepted else 'product_mapping_or_evidence_missing']))
    return decisions


def apply_memberships(profile, scope, entities, assertions, evidence):
    decisions = decide_memberships(profile, scope, entities, assertions, evidence)
    by_assertion = {a.assertion_id: a for a in assertions}
    by_entity = {e.entity_id: e for e in entities}
    result = []
    # Source product facts survive. Direct model-proposed memberships cannot bypass admission.
    for claim in assertions:
        if (by_entity[claim.subject_id].entity_type == 'organization'
                and by_entity[claim.object_id].entity_type == 'activity'
                and claim.status == 'supported'):
            claim = claim.model_copy(update={'status': 'unresolved', 'verification': Verification(
                rationale='Direct activity assertion retained for review; product/scope/role admission required.')})
        result.append(claim)
    for decision in decisions:
        if decision.status != 'accepted':
            continue
        inputs = [by_assertion[i] for i in decision.input_assertion_ids]
        evidence_ids = sorted({eid for a in inputs for eid in a.evidence_ids})
        result.append(ChainAssertion(assertion_id=stable_id('participation', decision.decision_id),
            subject_id=decision.organization_id, predicate=Predicate.PARTICIPATES_IN,
            object_id=activity_id(profile, scope, decision.activity_key), status='supported',
            evidence_ids=evidence_ids,
            qualifiers=Qualifiers(org_role=inputs[0].qualifiers.org_role,
                extra={'membership_decision_id': decision.decision_id, 'profile_version': profile.version}),
            verification=Verification(method='code_rule', verifier_version=decision.rule_version,
                rationale='Versioned product/application/role policy admission; source semantics remain model-assisted.',
                supporting_evidence_ids=evidence_ids)))
    return result, decisions
