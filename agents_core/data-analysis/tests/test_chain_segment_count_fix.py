"""di/agent.py:1157 产业链段数硬编码修复回归（2026-10-07）。

修复前：`chain_segments if len(chain_segments) == 3 else None`
—— LLM 归纳出的产业链不是恰好 3 段就整体丢弃（4 段半导体、5 段光伏全丢）。
修复后：≥2 段即采用；不足 2 段保留确定性抽取结果并留痕。
"""
from data_interpreter.agent import DataInterpreterAgent


def _validate(response: dict, allowed: set[str] | None = None):
    # 显式解包：末位是 chain_topology（2026-10-08 新增），用 *_ 会静默取错值
    out = DataInterpreterAgent._validate_semantic(
        response,
        allowed_record_ids=allowed or set(),
        allowed_metric_ids=set(),
        allowed_trend_ids=set(),
        allowed_anomaly_ids=set(),
        max_insights=5,
        fallback=("摘要", [], [], []),
    )
    assert len(out) == 6, f"_validate_semantic 应返回 6 元组，实际 {len(out)}"
    return out


def _seg(name: str, stage: str, eids: list[str] | None = None) -> dict:
    return {
        "segment_name": name,
        "stage": stage,
        "description": f"{name}环节",
        "representative_companies": ["公司甲"],
        "key_products": ["产品A"],
        "evidence_record_ids": eids or [],
    }


def test_four_segments_now_adopted():
    """4 段产业链（半导体式）修复前被整体丢弃，修复后采用。"""
    response = {
        "industry_chain_segments": [
            _seg("上游材料", "upstream"), _seg("上游设备", "upstream"),
            _seg("中游制造", "midstream"), _seg("下游应用", "downstream"),
        ],
    }
    *_, chain, _topo = _validate(response)
    assert chain is not None and len(chain) == 4
    assert [s.segment_name for s in chain] == ["上游材料", "上游设备", "中游制造", "下游应用"]


def test_five_segments_now_adopted():
    """5 段产业链（光伏式）修复前被整体丢弃，修复后采用。"""
    response = {
        "industry_chain_segments": [
            _seg("硅料", "upstream"), _seg("硅片", "upstream"), _seg("电池片", "midstream"),
            _seg("组件", "midstream"), _seg("电站", "downstream"),
        ],
    }
    *_, chain, _topo = _validate(response)
    assert chain is not None and len(chain) == 5


def test_two_segments_adopted():
    """2 段（极简产业链）也采用。"""
    response = {"industry_chain_segments": [_seg("供给端", "upstream"), _seg("需求端", "downstream")]}
    *_, chain, _topo = _validate(response)
    assert chain is not None and len(chain) == 2


def test_one_segment_still_rejected():
    """仅 1 段不足以构成产业链，保留 None（沿用确定性抽取结果）。"""
    response = {"industry_chain_segments": [_seg("唯一环节", "other")]}
    *_, chain, _topo = _validate(response)
    assert chain is None


def test_three_segments_still_adopted():
    """3 段行为不变（向后兼容）。"""
    response = {
        "industry_chain_segments": [
            _seg("上游", "upstream"), _seg("中游", "midstream"), _seg("下游", "downstream"),
        ],
    }
    *_, chain, _topo = _validate(response)
    assert chain is not None and len(chain) == 3


def test_segments_evidence_binding_still_enforced():
    """段数放宽不削弱证据绑定：挂不上证据的 eid 仍被剥掉。"""
    response = {
        "industry_chain_segments": [
            _seg("上游", "upstream", ["R1", "FAKE"]), _seg("中游", "midstream", ["R2"]),
            _seg("下游", "downstream", ["GHOST"]),
        ],
    }
    *_, chain, _topo = _validate(response, allowed={"R1", "R2"})
    assert chain is not None
    assert chain[0].evidence_record_ids == ["R1"]
    assert chain[1].evidence_record_ids == ["R2"]
    assert chain[2].evidence_record_ids == []
