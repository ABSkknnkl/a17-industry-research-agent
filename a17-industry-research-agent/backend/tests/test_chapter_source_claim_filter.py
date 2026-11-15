from chapter_writer import retriever


def test_upstream_unsupported_numbers_are_not_sent_as_findings():
    evidence={'R1':{'record_id':'R1','entity':'甲公司','metric':'revenue','value':1000000000,
      'unit':'元','period':'2023-12-31','period_start':'2023-01-01','period_type':'annual','scope':'consolidated','currency':'CNY'}}
    findings=[{'subject':'甲公司','predicate':'营业收入','object_summary':'2023年营业收入为10亿元','evidence_record_ids':['R1']},
      {'subject':'动力电池','predicate':'装机量','object_summary':'2023年装机量达387.7GWh','evidence_record_ids':['R1']}]
    kept,removed=retriever.filter_unverified_findings(findings,evidence)
    # P2：字段结构与有据子句保留；只删除无据数字所在的句子，不再整条丢弃。
    assert len(kept)==2 and '10亿元' in kept[0]['object_summary']
    assert kept[1]['subject']=='动力电池' and kept[1]['predicate']=='装机量'
    assert kept[1]['object_summary']==''
    assert '387.7' not in str(kept)
    assert removed==1
