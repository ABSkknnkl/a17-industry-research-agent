"""A/B 双版口径（企业专属 / 行业全景）回归测试（2026-10-21）。

用户裁定：**主题点名一家公司 → A 版（品牌卡恰好 1 家 = 该公司）；没指定 → B 版（2-8 家龙头）**。

本文件锁死三件事：
  ① 判定：26 个真实主题的 A/B 归类（含"新能源汽车""恒瑞医药"这类易混项）
  ② A 版三层机制都按新口径走：缺口检测 / 核心改判 / 品牌卡补强
  ③ B 版行为一字不改（A 版改动不得误伤行业全景图）
"""

import re
from pathlib import Path

import pytest

from chart_generator.chain_scope import (
    BRAND_MIN_ENTITY,
    BRAND_MIN_INDUSTRY,
    detect_subject_kind,
    entity_brand_rule,
)
from chart_generator.chain_topology import (
    core_misplacement,
    repair_topology,
    strengthen_brand_card,
    validate_topology,
)
from chart_generator.websearch import detect_chain_gaps

# ── ① 判定矩阵 ────────────────────────────────────────────────────────────

ENTITY_CASES = [
    "宇树科技机器人", "宁德时代产业链", "贵州茅台", "比亚迪", "宝钢股份",
    "恒瑞医药", "金山办公", "顺丰控股", "宇树科技人形机器人", "复星医药",
    "比亚迪半导体",
]
INDUSTRY_CASES = [
    "工业机器人", "四足机器人", "人形机器人", "手机", "白酒", "创新药",
    "钢铁", "快递", "SaaS", "海上风电", "低空经济", "新能源汽车",
    "半导体设备（刻蚀/沉积）", "机器人", "消费无人机",
]


@pytest.mark.parametrize("subject", ENTITY_CASES)
def test_entity_subjects_are_detected(subject):
    scope = detect_subject_kind(subject)
    assert scope.is_entity, f"「{subject}」应判为企业专属版（{scope.reason}）"
    assert scope.entity, "A 版必须抽出主题公司"
    assert scope.brand_min == BRAND_MIN_ENTITY == 1


@pytest.mark.parametrize("subject", INDUSTRY_CASES)
def test_industry_subjects_are_detected(subject):
    scope = detect_subject_kind(subject)
    assert not scope.is_entity, f"「{subject}」应判为行业全景版（{scope.reason}）"
    assert scope.brand_min == BRAND_MIN_INDUSTRY == 3


def test_explicit_override_wins():
    assert detect_subject_kind("工业机器人", explicit="entity").is_entity
    assert not detect_subject_kind("宇树科技机器人", explicit="industry").is_entity


def test_known_entities_signal_beats_heuristics():
    """无公司后缀的主题（贵州茅台型）靠 A1 实体名单兜底。"""
    scope = detect_subject_kind("茅台", known_entities=("贵州茅台", "五粮液"))
    assert scope.is_entity and scope.entity == "茅台"


def test_graph_title_with_bracket_suffix_still_resolves():
    """从图标题反推口径：A2 会追加「（企业专属版）」括注，必须能剥掉。

    run-20261021203735 实测：标题 = 「宇树科技机器人产业链图谱（企业专属版）」，
    旧版只剥一轮（末尾是「）」）→ 主体抽空 → 判成 industry →
    A2 的核心归一照跑，is_core 被搬到凑了 3 家企业的能力卡上。
    """
    scope = detect_subject_kind("宇树科技机器人产业链图谱（企业专属版）")
    assert scope.is_entity and scope.entity == "宇树科技", scope

    from chart_generator.chain_scope import resolve_scope

    topo = {"title": "宇树科技机器人产业链图谱（企业专属版）"}
    assert resolve_scope(topology=topo).is_entity


# ── ② A 版三层机制 ────────────────────────────────────────────────────────

def _topo(companies, *, label="本体制造与总装", core_product="四足机器人",
          extra_nodes=None):
    nodes = [{"id": "M1", "label": label, "stage": "midstream", "is_core": True,
              "companies": list(companies), "evidence_ids": []}]
    nodes.extend(extra_nodes or [])
    return {"title": "宇树科技机器人产业链图谱", "core_product": core_product,
            "nodes": nodes, "edges": []}


def test_entity_brand_card_keeps_only_subject_and_moves_rivals():
    topo = _topo(["云深处科技", "蔚蓝科技", "波士顿动力"])
    out, notes = strengthen_brand_card(topo, "宇树科技机器人")
    assert out["nodes"][0]["companies"] == ["宇树科技"]
    peers = [n for n in out["nodes"] if "同业对标" in str(n["label"])]
    assert peers, "竞品要落到配套层「同业对标」卡，不能凭空消失"
    assert set(peers[0]["companies"]) == {"云深处科技", "蔚蓝科技", "波士顿动力"}
    assert peers[0]["stage"] == "support"
    assert any("竞品" in n for n in notes), notes


def test_entity_brand_card_noop_when_already_only_subject():
    out, notes = strengthen_brand_card(_topo(["宇树科技"]), "宇树科技机器人")
    assert out["nodes"][0]["companies"] == ["宇树科技"]
    assert notes == []


def test_industry_brand_card_not_regressed():
    """B 版：品牌卡 1 家仍是缺陷，要补行业龙头。"""
    topo = _topo(["埃斯顿"], label="本体制造与总装", core_product="工业机器人")
    topo["title"] = "工业机器人产业链图谱"
    out, notes = strengthen_brand_card(topo, "工业机器人")
    comps = out["nodes"][0]["companies"]
    assert len(comps) >= BRAND_MIN_INDUSTRY, comps
    assert any("品牌卡不足" in n for n in notes), notes


def test_gaps_entity_disables_brand_gaps():
    """A 版：品牌卡 1 家不得再触发 missing_core_body / thin_brand_list。

    这两条缺口会把检索引向「整机厂商 龙头企业 上市公司」——实测就是这么把
    5 家竞品灌进宇树品牌卡的。
    """
    topo = _topo(["宇树科技"])
    gaps = detect_chain_gaps(topo)
    kinds = {g.kind for g in gaps}
    assert "missing_core_body" not in kinds, gaps
    assert "thin_brand_list" not in kinds, gaps


def test_gaps_industry_still_reports_brand_gaps():
    topo = _topo(["埃斯顿"], core_product="工业机器人")
    topo["title"] = "工业机器人产业链图谱"
    kinds = {g.kind for g in detect_chain_gaps(topo)}
    assert "missing_core_body" in kinds, "B 版品牌卡 <3 家必须报缺口"


def test_core_misplacement_locks_entity():
    """A 版核心锁定：旁边有一张 3 家企业的能力卡也不许抢。"""
    topo = _topo(["宇树科技"], extra_nodes=[
        {"id": "M2", "label": "关节模组与结构件", "stage": "midstream",
         "companies": ["兆威机电", "鼎智科技", "长盈精密"], "evidence_ids": []},
    ])
    assert core_misplacement(topo, subject="宇树科技机器人") is None


def test_core_misplacement_still_works_for_industry():
    topo = _topo(["某小厂"], core_product="工业机器人", extra_nodes=[
        {"id": "M2", "label": "整机制造与总装", "stage": "midstream",
         "companies": ["埃斯顿", "汇川技术", "新松"], "evidence_ids": []},
    ])
    topo["title"] = "工业机器人产业链图谱"
    assert core_misplacement(topo, subject="工业机器人") is not None


def test_validate_flags_brand_card_without_entity():
    topo = _topo(["云深处科技", "蔚蓝科技", "波士顿动力"], label="本体制造与总装")
    # 主题公司出现在上游（在图上但没在品牌卡）→ 必须报错
    topo["nodes"].append({"id": "U1", "label": "关节电机与驱动器", "stage": "upstream",
                          "companies": ["宇树科技"], "evidence_ids": []})
    errs = validate_topology(topo, subject="宇树科技机器人")
    assert any("宇树科技" in e and "品牌卡" in e for e in errs), errs


def test_validate_quiet_when_entity_not_in_graph():
    """主题公司压根没被写进任何节点 → 不报"品牌卡挂错"（repair 修不出来）。"""
    topo = _topo(["云深处科技"])
    errs = validate_topology(topo, subject="宇树科技机器人")
    assert not any("品牌卡" in e for e in errs), errs


def test_repair_end_to_end_entity():
    """完整修复链：品牌卡只 1 家 + 核心仍是主题公司。"""
    topo = _topo(["埃斯顿", "汇川技术", "新松"], label="本体制造与总装")
    fixed, notes = repair_topology(topo, subject="宇树科技机器人")
    core = next(n for n in fixed["nodes"] if n.get("is_core"))
    assert core["companies"] == ["宇树科技"], core["companies"]
    # 只看与品牌卡相关的错误（本用例刻意不造边，"edges 为空"是另一条无关规则）
    assert not [e for e in validate_topology(fixed, subject="宇树科技机器人")
                if "品牌卡" in e]
    assert notes


# ── ③ 提示词与渲染口径 ────────────────────────────────────────────────────

def test_topology_prompt_is_scope_aware():
    from chart_generator.chain_topology import topology_system

    entity_prompt = topology_system("宇树科技机器人")
    industry_prompt = topology_system("工业机器人")
    assert "企业专属版" in entity_prompt
    assert "恰好 1 家" in entity_prompt
    assert entity_brand_rule() in entity_prompt
    assert "企业专属版" not in industry_prompt, "行业主题不该出现 A 版条款"


def test_render_spec_carries_scope_and_lowered_core_threshold():
    from chart_generator.chain_topology import topology_to_spec

    topo = _topo(["宇树科技"])
    spec = topology_to_spec(topo, fallback_title="宇树科技机器人产业链图谱")
    assert spec.scope_kind == "entity"
    assert spec.scope_entity == "宇树科技"
    assert spec.core_min_brands == 1, "A 版本体盒下限必须是 1，否则唯一品牌被判成画不出来"

    from chart_generator.chain_render import _stats_line

    line = _stats_line(spec)
    assert "宇树科技 1 品牌" in line, line


# ── ⑤ 字段语义与产业链纯度（v3 的 P2' 两条）──────────────────────────────

def test_downstream_customer_types_move_to_buyer():
    """下游 companies 里放"个人消费者/高校"是必然的，代码要归位到 buyer。"""
    topo = _topo(["宇树科技"], extra_nodes=[
        {"id": "D1", "label": "科研教育", "stage": "downstream",
         "companies": ["高校", "科研机构", "个人消费者"], "evidence_ids": []},
    ])
    fixed, notes = repair_topology(topo, subject="宇树科技机器人")
    d1 = next(n for n in fixed["nodes"] if n["id"] == "D1")
    assert d1["companies"] == [], d1["companies"]
    assert d1["buyer"] == "高校、科研机构、个人消费者"
    assert any("客户类型" in n for n in notes), notes


def test_real_customers_are_not_mistaken_for_customer_types():
    """真实企业名（国家电网/京东）必须留在 companies 位，不能被当类别名搬走。"""
    topo = _topo(["宇树科技"], extra_nodes=[
        {"id": "D1", "label": "电力与园区巡检", "stage": "downstream",
         "companies": ["国家电网", "南方电网"], "evidence_ids": []},
    ])
    fixed, _ = repair_topology(topo, subject="宇树科技机器人")
    d1 = next(n for n in fixed["nodes"] if n["id"] == "D1")
    assert d1["companies"] == ["国家电网", "南方电网"]


def test_support_certification_bodies_are_not_touched():
    """配套层的 SGS/TÜV 是机构名，但在认证卡里是正确内容，不按客户类型规则搬走。"""
    topo = _topo(["宇树科技"], extra_nodes=[
        {"id": "S1", "label": "检测认证与标准", "stage": "support",
         "companies": ["中检集团CCIC", "SGS", "TÜV"], "evidence_ids": []},
    ])
    fixed, _ = repair_topology(topo, subject="宇树科技机器人")
    s1 = next(n for n in fixed["nodes"] if n["id"] == "S1")
    assert s1["companies"] == ["中检集团CCIC", "SGS", "TÜV"]


def test_equity_holding_node_is_dropped_with_its_edges():
    """「股权投资」是股东关系不是产业链环节，连同边一起剔；概念股不能借这张卡上图。"""
    topo = {"title": "宇树科技机器人产业链图谱", "core_product": "四足机器人",
            "nodes": [
                {"id": "M1", "label": "本体制造与总装", "stage": "midstream",
                 "is_core": True, "companies": ["宇树科技"], "evidence_ids": []},
                {"id": "S1", "label": "股权投资", "stage": "support",
                 "companies": ["景兴纸业", "荣晟环保"], "evidence_ids": []},
            ],
            "edges": [{"source": "S1", "target": "M1", "label": "资本支持",
                       "flow": "service"}]}
    fixed, notes = repair_topology(topo, subject="宇树科技机器人")
    assert [n["id"] for n in fixed["nodes"]] == ["M1"]
    assert fixed["edges"] == [], "被删节点的边必须一起清掉，否则渲染器拿到悬空引用"
    assert any("股权投资" in n for n in notes), notes


def test_legal_name_and_short_name_collapse_to_one_seat():
    """工商全称带省份前缀时，`_is_same_company` 的「短名+后缀」规则匹配不上，
    必须靠别名表把两个写法并成一个座位（B 版真跑实测）。

    与 A/B 无关的既有瑕疵，顺手锁住：品牌卡里同一家公司占两格，读者第一眼就发现。
    """
    from chart_generator.chain_topology import (
        _dedupe_company_names,
        normalize_company_name,
    )

    assert normalize_company_name("安徽埃夫特智能装备股份有限公司") == "埃夫特"
    merged = _dedupe_company_names(
        ["埃夫特", "安徽埃夫特智能装备股份有限公司", "汇川技术"])
    assert merged == ["埃夫特", "汇川技术"], merged


def test_peer_vendors_are_not_customers_in_scene_nodes():
    """下游"场景"卡填同行整机厂 = 把竞争对手当客户（run-20261021235458 实测）。

    「科研与教育」被联网补漏填成 乐聚机器人/智元机器人/银河通用 —— 三家都是
    机器人整机厂，不是科研教育的采购方。宁空勿错：名字以产品类别结尾的直接摘掉。
    """
    topo = _topo(["宇树科技"], extra_nodes=[
        {"id": "D1", "label": "科研与教育", "stage": "downstream",
         "companies": ["乐聚机器人", "智元机器人", "银河通用"], "evidence_ids": []},
    ])
    fixed, notes = repair_topology(topo, subject="宇树科技机器人")
    d1 = next(n for n in fixed["nodes"] if n["id"] == "D1")
    assert d1["companies"] == [], d1["companies"]
    assert any("同行" in n for n in notes), notes


def test_real_customer_in_scene_node_survives_vendor_rule():
    """真客户（山东三源电力）没有厂商尾巴，必须留下。"""
    topo = _topo(["宇树科技"], extra_nodes=[
        {"id": "D1", "label": "电力与园区巡检", "stage": "downstream",
         "companies": ["山东三源电力科技有限公司"], "evidence_ids": []},
    ])
    fixed, _ = repair_topology(topo, subject="宇树科技机器人")
    d1 = next(n for n in fixed["nodes"] if n["id"] == "D1")
    assert d1["companies"] == ["山东三源电力科技有限公司"]


def test_empty_support_nodes_gap_and_query_semantics():
    """配套带空卡 ≥2 要触发检索，且 query 必须是「服务商」语义（2026-10-22）。

    A 版真跑 5 张配套卡只有认证卡有企业 —— 图上是一排空壳卡。
    检索词套「供应商」会搜回零部件厂，套「客户」会搜回终端用户，都不对。
    """
    from chart_generator.websearch import build_gap_queries

    topo = _topo(["宇树科技"], extra_nodes=[
        {"id": "S1", "label": "步态仿真与训练平台", "stage": "support",
         "companies": [], "key_products": ["仿真训练软件"], "evidence_ids": []},
        {"id": "S2", "label": "运维与备件", "stage": "support",
         "companies": [], "key_products": ["运维服务"], "evidence_ids": []},
    ])
    gaps = detect_chain_gaps(topo)
    kinds = {g.kind for g in gaps}
    assert "empty_support_nodes" in kinds, kinds
    queries = build_gap_queries("宇树科技机器人", gaps, core_product="四足机器人",
                                max_queries=4)
    support_q = [q for q in queries if "服务商" in q]
    assert support_q, queries
    assert not any("零部件" in q and "服务商" in q for q in queries), queries


def test_single_empty_support_card_does_not_spend_a_query():
    """只空 1 张配套卡不报缺口：配套带 3-5 张，单张空很常见，不值一次额度。"""
    topo = _topo(["宇树科技"], extra_nodes=[
        {"id": "S1", "label": "步态仿真与训练平台", "stage": "support",
         "companies": [], "evidence_ids": []},
    ])
    assert "empty_support_nodes" not in {g.kind for g in detect_chain_gaps(topo)}


def test_category_words_never_sit_in_company_slot():
    """companies 不得等于同节点的品类词（2026-10-22）。

    实测配套卡「运维与备件」的 companies 被填成 ["运维服务","备件供应"] ——
    那正是这张卡自己的 key_products，等于把品类词抄进企业位。
    """
    topo = _topo(["宇树科技"], extra_nodes=[
        {"id": "S2", "label": "运维与备件", "stage": "support",
         "companies": ["运维服务", "备件供应"],
         "key_products": ["运维服务", "备件供应"], "evidence_ids": []},
    ])
    fixed, notes = repair_topology(topo, subject="宇树科技机器人")
    s2 = next(n for n in fixed["nodes"] if n["id"] == "S2")
    assert s2["companies"] == [], s2["companies"]
    assert any("品类词" in n for n in notes), notes


# ── ④ 契约双份的绊线 ──────────────────────────────────────────────────────

def test_a2_and_a3_share_the_same_core_body_threshold():
    """A2 里躺着一份 `CORE_BODY_MIN_COMPANIES = 3` 副本，改一处必踩。

    不能直接 import A2（跨包），用文本断言做绊线：两处数字必须相等。
    """
    from chart_generator.chain_topology import CORE_BODY_MIN_COMPANIES

    a2 = (Path(__file__).resolve().parents[2]
          / "data-analysis" / "data_interpreter" / "agent.py")
    if not a2.exists():                       # 单包分发场景跳过
        pytest.skip("A2 源码不在当前包内")
    txt = a2.read_text(encoding="utf-8")
    m = re.search(r"CORE_BODY_MIN_COMPANIES\s*=\s*(\d+)", txt)
    assert m, "A2 里找不到 CORE_BODY_MIN_COMPANIES 定义（契约副本被改名？）"
    assert int(m.group(1)) == CORE_BODY_MIN_COMPANIES, (
        f"A2={m.group(1)} 与 A3={CORE_BODY_MIN_COMPANIES} 不一致：")
