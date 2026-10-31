from chain_research.models import ChainAssertion, ChainEntity, ChainEvidence, Verification
from chain_research.identity import normalize_identities


def fixture(quote):
    entities = [ChainEntity(entity_id='zh', entity_type='organization', canonical_name='甲科技'),
                ChainEntity(entity_id='en', entity_type='organization', canonical_name='Acme'),
                ChainEntity(entity_id='p', entity_type='product', canonical_name='笔记本电脑')]
    ev = ChainEvidence(evidence_id='e', document_id='d', title='夹具', content_hash='h',
                       source_family='fixture', locator='chars:0:20', quote=quote)
    claims = [ChainAssertion(assertion_id='a'+org, subject_id=org, predicate='offers', object_id='p',
        status='supported', evidence_ids=['e'], verification=Verification(
            method='model_assisted', rationale='夹具', supporting_evidence_ids=['e'])) for org in ('zh','en')]
    return entities, claims, [ev]


def test_explicit_bilingual_alias_merges_identity_and_rewrites_all_references():
    e,a,ev = fixture('甲科技（Acme）提供笔记本电脑。')
    merged, claims, log = normalize_identities(e,a,ev)
    orgs = [x for x in merged if x.entity_type == 'organization']
    assert len(orgs) == 1 and log
    assert {c.subject_id for c in claims} == {orgs[0].entity_id}
    assert {'甲科技','Acme'} == {orgs[0].canonical_name, *orgs[0].aliases}


def test_colisted_or_parent_subsidiary_names_do_not_merge():
    for quote in ('甲科技、Acme均提供笔记本电脑。', '甲科技旗下子公司Acme提供笔记本电脑。'):
        e,a,ev = fixture(quote)
        result,_,log = normalize_identities(e,a,ev)
        assert len(result) == 3 and not log
