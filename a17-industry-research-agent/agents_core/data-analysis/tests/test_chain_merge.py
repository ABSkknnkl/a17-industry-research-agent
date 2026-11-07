"""A2 产业链双通道并集合并测试（2026-10-07）。

修复前：LLM 归纳整体覆盖确定性抽取（`industry_chain_segments = chain_segments`）。
修复后：`_merge_chain_segments` 并集——同名段合并、stage 冲突留痕、无证据段标 inferred。
"""
from data_interpreter.agent import DataInterpreterAgent
from data_interpreter.models import IndustryChainSegment


def _seg(name, stage, companies=None, products=None, eids=None, desc=""):
    return IndustryChainSegment(
        segment_name=name, stage=stage, description=desc or f"{name}描述",
        representative_companies=companies or [], key_products=products or [],
        evidence_record_ids=eids or [],
    )


def test_disjoint_segments_union():
    det = [_seg("上游材料", "upstream", companies=["公司甲"], eids=["R1"])]
    llm = [_seg("中游制造", "midstream", companies=["公司乙"], eids=["R2"])]
    merged = DataInterpreterAgent._merge_chain_segments(det, llm)
    assert len(merged) == 2
    names = {s.segment_name for s in merged}
    assert names == {"上游材料", "中游制造"}


def test_same_name_merges_items_not_duplicates():
    det = [_seg("上游", "upstream", companies=["甲"], products=["硅料"], eids=["R1"])]
    llm = [_seg("上游", "upstream", companies=["乙"], products=["硅料", "硅片"], eids=["R2"])]
    merged = DataInterpreterAgent._merge_chain_segments(det, llm)
    assert len(merged) == 1
    seg = merged[0]
    assert set(seg.representative_companies) == {"甲", "乙"}
    assert set(seg.key_products) == {"硅料", "硅片"}
    assert set(seg.evidence_record_ids) == {"R1", "R2"}


def test_stage_conflict_prefers_llm_and_keeps_both_channels_data():
    det = [_seg("整机", "downstream", companies=["甲"], eids=["R1"])]   # 确定性误判
    llm = [_seg("整机", "midstream", companies=["乙"], eids=["R2"])]    # LLM 纠正
    merged = DataInterpreterAgent._merge_chain_segments(det, llm)
    assert len(merged) == 1
    assert merged[0].stage == "midstream"          # 以 LLM 为准
    assert set(merged[0].representative_companies) == {"甲", "乙"}   # 数据不丢


def test_no_evidence_marked_inferred_not_dropped():
    det = [_seg("有证据", "upstream", eids=["R1"])]
    llm = [_seg("无证据推断段", "downstream")]   # 挂不上证据
    merged = DataInterpreterAgent._merge_chain_segments(det, llm)
    assert len(merged) == 2   # 不丢弃
    by_name = {s.segment_name: s for s in merged}
    assert getattr(by_name["无证据推断段"], "inferred", False) is True
    assert getattr(by_name["有证据"], "inferred", False) is False


def test_ordering_upstream_to_downstream():
    det = [_seg("下游", "downstream", eids=["R3"])]
    llm = [_seg("上游", "upstream", eids=["R1"]), _seg("中游", "midstream", eids=["R2"])]
    merged = DataInterpreterAgent._merge_chain_segments(det, llm)
    assert [s.stage for s in merged] == ["upstream", "midstream", "downstream"]


def test_empty_llm_keeps_deterministic():
    det = [_seg("上游", "upstream", eids=["R1"])]
    merged = DataInterpreterAgent._merge_chain_segments(det, [])
    assert len(merged) == 1 and merged[0].segment_name == "上游"


def test_empty_both_returns_empty():
    assert DataInterpreterAgent._merge_chain_segments([], []) == []
