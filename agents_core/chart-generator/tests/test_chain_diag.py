"""诊断引擎契约测试（P1，2026-10-19）。

守四件事：

1. **真实拓扑基线**：6 个定稿主题 repair 后必须 0 P0（诊断不能把好图判成坏图）；
2. **规则不漏报**：每条 P0 规则注入一个已知缺陷，必须命中对应 `rule_id`
   （这是"AI 能快速定位"的前提——报错要能精确到规则）；
3. **Finding 可消费**：`rule_id` 必须在注册表、`code_ref`/`hint` 非空、
   `to_dict()` 能被 JSON 序列化；
4. **确定性**：同一输入跑两次结果完全一致（无随机、无时间依赖）。
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from chart_generator.chain_diag import RULE_REGISTRY, diagnose
from chart_generator.chain_render import render_chain_svg
from chart_generator.chain_topology import (
    hoist_leading_to_brand_card,
    repair_topology,
    topology_to_spec,
)

ROOT = Path(__file__).resolve().parents[3]
RUNS = ROOT / "data" / "runs"

# 第三轮复查定稿的六个主题（与 scratch/verify_f8_f14_offline.py 同源）
TARGETS = [
    ("海上风电", "run-20261019123544-c4c98d"),
    ("工业机器人", "run-20261019123544-6449d0"),
    ("创新药", "run-20261019125108-f84de2"),
    ("半导体设备（刻蚀/沉积）", "run-20261019124137-542817"),
    ("消费级无人机", "run-20261019130155-9ff867"),
    ("车载激光雷达", "run-20261019125531-1b6ab6"),
]


def _load_fixed(topic: str, rid: str) -> dict:
    fp = RUNS / rid / "artifacts" / "interpretation_report.json"
    if not fp.exists():
        pytest.skip(f"缺少运行产物：{fp}")
    raw = json.loads(fp.read_text(encoding="utf-8"))["industry_chain_topology"]
    hoisted, _ = hoist_leading_to_brand_card(raw, topic)
    fixed, _ = repair_topology(hoisted, allowed_companies=None)
    return fixed


def _minimal_topo() -> dict:
    """一个结构上尽量合法的最小拓扑（只用于注入测试，不追求 0 finding）。"""
    return {
        "title": "测试产业链",
        "subtitle": "上游 → 整机 → 下游",
        "core_product": "整机",
        "nodes": [
            {"id": "U1", "label": "核心部件", "companies": ["甲公司"], "key_products": ["部件"],
             "description": "提供核心部件", "stage": "upstream", "is_core": False,
             "bottleneck": True, "evidence_ids": []},
            {"id": "U2", "label": "原材料", "companies": ["乙公司"], "key_products": ["材料"],
             "description": "提供原材料", "stage": "upstream", "is_core": False,
             "bottleneck": False, "evidence_ids": []},
            {"id": "M1", "label": "整机制造与总装", "companies": ["丙公司", "丁公司"],
             "key_products": ["整机"], "description": "集成制造", "stage": "midstream",
             "is_core": True, "bottleneck": False, "evidence_ids": []},
            {"id": "M2", "label": "研发与设计", "companies": ["戊公司"], "key_products": ["设计"],
             "description": "出图纸", "stage": "midstream", "is_core": False,
             "bottleneck": False, "evidence_ids": []},
            {"id": "D1", "label": "工业应用", "companies": [], "key_products": ["场景"],
             "description": "工业场景", "stage": "downstream", "is_core": False,
             "bottleneck": False, "phase": "已落地", "buyer": "工业客户", "evidence_ids": []},
            {"id": "D2", "label": "消费应用", "companies": [], "key_products": ["场景"],
             "description": "消费场景", "stage": "downstream", "is_core": False,
             "bottleneck": False, "phase": "试点中", "buyer": "个人用户", "evidence_ids": []},
            {"id": "S1", "label": "运维服务", "companies": ["己公司"], "key_products": ["运维"],
             "description": "后市场", "stage": "support", "is_core": False,
             "bottleneck": False, "evidence_ids": []},
        ],
        "edges": [
            {"source": "U1", "target": "M1", "label": "部件供应", "flow": "material"},
            {"source": "U2", "target": "M1", "label": "材料供应", "flow": "material"},
            {"source": "M2", "target": "M1", "label": "设计方案", "flow": "technical"},
            {"source": "M1", "target": "D1", "label": "整机交付", "flow": "material"},
            {"source": "M1", "target": "D2", "label": "整机交付", "flow": "material"},
            {"source": "M1", "target": "S1", "label": "售后支持", "flow": "service"},
        ],
    }


def _rules(report) -> set[str]:
    return {f.rule_id for f in report.findings}


def _core(topo: dict) -> dict:
    return next(n for n in topo["nodes"] if n.get("is_core"))


# ── 1. 真实拓扑基线 ───────────────────────────────────────────────────────

@pytest.mark.parametrize("topic,rid", TARGETS)
def test_fixed_real_topology_has_no_p0(topic, rid):
    """6 个定稿主题 repair 后必须 0 P0 —— 诊断引擎不能把好图判成坏图。"""
    fixed = _load_fixed(topic, rid)
    svg = render_chain_svg(topology_to_spec(fixed, fallback_title=topic))
    rep = diagnose(fixed, subject=topic, svg=svg)
    p0 = [f for f in rep.findings if f.severity == "P0"]
    detail = "\n".join(f"  {f.rule_id} {f.message}" for f in p0)
    assert not p0, f"{topic} 定稿图出现 P0（若为真缺陷请修代码，若是误报请修规则）：\n{detail}"


@pytest.mark.parametrize("topic,rid", TARGETS)
def test_fixed_real_topology_profile_level(topic, rid):
    """6 个主题都应有 L1/L2 画像（不是 L0 兜底）。"""
    fixed = _load_fixed(topic, rid)
    rep = diagnose(fixed, subject=topic)
    assert rep.level in ("L1", "L2"), f"{topic} 落到 {rep.level}"


# ── 2. 规则不漏报（每条 P0 一个注入用例） ─────────────────────────────────

def test_brand02_flags_unknown_company_as_p1_pending():
    """名单外公司是 **P1 待核**，不是 P0。

    口径来自生产链路 `classify_company_traceability`：真名降级 industry_common、
    画「待核」角标、**不删除**。诊断若报 P0 并建议删除，就会误杀名单不全的真龙头
    （实测：北京君正＝存储芯片厂商，被旧名单判成"非本行业"）。
    """
    topo = _minimal_topo()
    _core(topo)["companies"].append("某某贸易")
    rep = diagnose(topo, subject="海上风电")
    hits = [f for f in rep.findings if f.rule_id == "CHAIN-BRAND-02"]
    assert hits, "名单外公司应被标记（待核）"
    assert all(f.severity == "P1" for f in hits), "不得升级为 P0（会误删真名）"
    assert "待核" in hits[0].message


def test_brand03_rejects_upstream_leader_on_brand_card():
    topo = _minimal_topo()
    _core(topo)["companies"].append("东方电缆")      # 海缆厂，leading_upstream
    rep = diagnose(topo, subject="海上风电")
    assert "CHAIN-BRAND-03" in _rules(rep)


def test_brand05_flags_company_in_both_brand_and_upstream():
    topo = _minimal_topo()
    brand_name = _core(topo)["companies"][0]
    topo["nodes"][0]["companies"].append(brand_name)   # 同一家同时在上游
    rep = diagnose(topo, subject="海上风电")
    assert "CHAIN-BRAND-05" in _rules(rep)


def test_struct02_flags_missing_core():
    topo = _minimal_topo()
    for n in topo["nodes"]:
        n["is_core"] = False
    rep = diagnose(topo, subject="海上风电")
    assert "CHAIN-STRUCT-02" in _rules(rep)


def test_struct02_flags_multiple_cores():
    topo = _minimal_topo()
    topo["nodes"][3]["is_core"] = True                 # 研发节点也标 core
    rep = diagnose(topo, subject="海上风电")
    assert "CHAIN-STRUCT-02" in _rules(rep)


def test_struct04_flags_material_flow_to_rd_node():
    topo = _minimal_topo()
    topo["edges"].append({"source": "U1", "target": "M2", "label": "部件直送",
                          "flow": "material"})
    rep = diagnose(topo, subject="海上风电")
    assert "CHAIN-STRUCT-04" in _rules(rep)


def test_struct08_flags_duplicate_company():
    topo = _minimal_topo()
    topo["nodes"][1]["companies"].append(topo["nodes"][0]["companies"][0])
    rep = diagnose(topo, subject="海上风电")
    assert "CHAIN-STRUCT-08" in _rules(rep)


def test_struct05_flags_bottleneck_on_midstream():
    topo = _minimal_topo()
    _core(topo)["bottleneck"] = True
    rep = diagnose(topo, subject="海上风电")
    assert "CHAIN-STRUCT-05" in _rules(rep)


def test_text01_flags_financial_number_in_description():
    topo = _minimal_topo()
    topo["nodes"][0]["description"] = "本条环节毛利率区间25%-45%"
    rep = diagnose(topo, subject="海上风电")
    assert "CHAIN-TEXT-01" in _rules(rep)


def test_text01_allows_model_tokens():
    """型号/等级代号不应误报（L2+ / 3D / 5G / T800）。"""
    topo = _minimal_topo()
    topo["nodes"][0]["key_products"] = ["L2+辅助驾驶", "工业3D检测", "5G通信模组"]
    rep = diagnose(topo, subject="海上风电")
    text01 = [f for f in rep.findings if f.rule_id == "CHAIN-TEXT-01"]
    assert not text01, f"型号被误判：{[f.message for f in text01]}"


def test_text02_flags_placeholder():
    topo = _minimal_topo()
    topo["nodes"][0]["description"] = "代表企业待补"
    rep = diagnose(topo, subject="海上风电")
    assert "CHAIN-TEXT-02" in _rules(rep)


def test_sem01_flags_wrong_fit():
    """创新药：把 CRO 写进监管卡是典型错配（F12 实测案例）。"""
    topo = _minimal_topo()
    topo["nodes"].append({
        "id": "S2", "label": "监管与注册服务", "companies": ["泰格医药"],
        "key_products": ["注册"], "description": "监管", "stage": "support",
        "is_core": False, "bottleneck": False, "evidence_ids": [],
    })
    rep = diagnose(topo, subject="创新药")
    assert "CHAIN-SEM-01" in _rules(rep)


def test_sem02_flags_banned_company():
    """消费无人机：亿航智能属载人 eVTOL，出现在消费级图里应被全局拦截。"""
    topo = _minimal_topo()
    topo["nodes"][0]["companies"].append("亿航智能")
    rep = diagnose(topo, subject="消费级无人机")
    assert "CHAIN-SEM-02" in _rules(rep)


# ── 3. Finding 结构可消费 ─────────────────────────────────────────────────

def test_every_finding_is_actionable():
    topo = _minimal_topo()
    _core(topo)["companies"].append("某某贸易")
    rep = diagnose(topo, subject="海上风电")
    assert rep.findings
    for f in rep.findings:
        assert f.rule_id in RULE_REGISTRY, f"未注册的规则：{f.rule_id}"
        assert f.severity in ("P0", "P1", "P2")
        assert f.message.strip()
        d = f.to_dict()
        assert d["rule_id"] and d["severity"] and d["message"]
        assert "code_ref" in d
        json.dumps(d, ensure_ascii=False)       # 必须可序列化


def test_p0_findings_carry_hint():
    """P0 必须给修复动作——这是"AI 能直接改代码"的前提。"""
    topo = _minimal_topo()
    _core(topo)["companies"].append("某某贸易")
    rep = diagnose(topo, subject="海上风电")
    for f in rep.findings:
        if f.severity == "P0":
            assert f.hint, f"{f.rule_id} 缺 hint"


def test_report_to_dict_has_stage_and_metrics():
    rep = diagnose(_minimal_topo(), subject="海上风电", stage="pre_repair")
    d = rep.to_dict()
    assert d["stage"] == "pre_repair"
    assert "metrics" in d and "node_count" in d["metrics"]
    assert d["verdict"] in ("pass", "warn", "fail")


# ── 4. 确定性 ─────────────────────────────────────────────────────────────

def test_diagnose_is_deterministic():
    topo = _minimal_topo()
    _core(topo)["companies"].append("某某贸易")
    a = diagnose(topo, subject="海上风电").to_dict()
    b = diagnose(topo, subject="海上风电").to_dict()
    assert a == b


# ── 5. 覆盖度与阶段 ───────────────────────────────────────────────────────

def test_l0_profile_reports_coverage_gap():
    topo = _minimal_topo()
    rep = diagnose(topo, subject="人造草坪")
    assert "CHAIN-COVER-01" in _rules(rep)
    assert rep.level == "L0"


def test_l2_profile_does_not_report_coverage_gap():
    rep = diagnose(_minimal_topo(), subject="海上风电")
    assert rep.level in ("L1", "L2")
    assert "CHAIN-COVER-01" not in _rules(rep)


def test_pre_repair_flags_duplicates_that_repair_fixes():
    """A2 原始产出有重复 → repair 后消失（证明 stage 语义正确）。"""
    fixed = _load_fixed("海上风电", "run-20261019123544-c4c98d")
    # 人为制造一个重复，模拟 A2 原始产出
    raw = copy.deepcopy(fixed)
    core = _core(raw)
    up = next(n for n in raw["nodes"] if n.get("stage") == "upstream" and n.get("companies"))
    up["companies"].append(core["companies"][0])
    pre = diagnose(raw, subject="海上风电", stage="pre_repair")
    assert "CHAIN-STRUCT-08" in _rules(pre)
