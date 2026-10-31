"""产业链图「核心栏不塌陷」修复 + 博查 L3 受控补漏通道测试（2026-10-17）。

对应评审意见里的 7 个问题中由**上游数据与模板判定**引起的 3 个：
  · 品牌列消失        → P0-B 核心节点确定性判定
  · 中游三张卡各吐一行 → P0-A 统计行计数
  · 缺低空基础设施层   → P1 提示词易漏环节清单 / P3 联网补漏
另含 P3 的范围红线测试（博查**只允许**用于产业链图）。
"""
import asyncio
import copy
import json
import os
import re

import pytest

import httpx

from chart_generator.chain_graph import ChainGraphSpec, ChainNode, ChainStage
from chart_generator.chain_render import (
    _stats_line,
    _use_core_body,
    render_chain_svg,
)
from chart_generator.chain_topology import (
    CORE_BODY_MIN_COMPANIES,
    COMPANY_ALIAS,
    classify_company_traceability,
    core_misplacement,
    degree_limit,
    normalize_company_name,
    normalize_core_node,
    repair_topology,
    validate_topology,
)
from chart_generator.websearch import (
    ALLOWED_SCOPES,
    DEFAULT_DOMAIN_ALLOWLIST,
    WebSearchClient,
    WebSearchConfig,
    WebHit,
    _PUNCT_RE,
    _QUERY_MAX_TERMS,
    apply_gap_hits,
    build_gap_queries,
    detect_chain_gaps,
    extract_segment_terms,
    extract_with_llm,
    fill_chain_gaps,
    resolve_web_search_config,
)

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures_real_topology.json")


def _node(nid, name, stage, *, core=False, companies=None, items=None, desc="", tier="evidence"):
    return ChainNode(
        node_id=nid, name=name, stage=stage,
        companies=list(companies or []), items=list(items or []), description=desc,
        is_core=core, emphasis=core,
        evidence_record_ids=["R1"] if tier == "evidence" else [],
        # 三项全空才 inferred（2026-10-17 修1）；industry_common 有企业/品类 → 不算。
        # web_unverified 也是"无问财证据"，照样进 inferred 分支，只是角标换成中性「待核」。
        inferred=(tier in ("inferred", "web_unverified")), source_tier=tier,
    )


def _spec(nodes, edges=None, core_product="eVTOL/低空飞行器"):
    stages = []
    for n in nodes:
        if n.stage not in [s.stage_id for s in stages]:
            stages.append(ChainStage(stage_id=n.stage, title=n.stage))
    return ChainGraphSpec(
        title="低空经济产业链全景图", subtitle="", core_product=core_product,
        stages=stages, nodes=nodes, edges=list(edges or []), source="llm",
    )


# ════════════════════════════════════════════════════════════════════════════
# P0-A 渲染层
# ════════════════════════════════════════════════════════════════════════════

def test_stats_line_full_count_when_no_core_column():
    """核心节点企业不足 3 家 → 卡片仍留在本段内，统计行**不能**扣 1。

    旧实现：先找 `_use_core_body` 的核心，找不到就退回任意 is_core 节点，
    再无条件 cnt -= 1 → 实测输出「中游 2 环节」而画面上画了 3 张卡。
    修正后：中游 3 个节点全算在中游。
    """
    nodes = [
        _node("CH1", "电池", "upstream", companies=["宁德时代"]),
        _node("CH2", "核心算法", "midstream", core=True, companies=["优刻得"]),
        _node("CH3", "整机厂", "midstream", companies=["亿航"]),
        _node("CH4", "总装集成", "midstream", companies=["富士康"]),
        _node("CH5", "物流配送", "downstream"),
    ]
    spec = _spec(nodes)
    assert _use_core_body(nodes[1]) is False
    line = _stats_line(spec)
    assert "中游 3 环节" in line, line
    assert "1 家代表企业" in line, line


def test_stats_line_subtracts_only_when_core_column_built():
    """核心企业 ≥3 → 本体盒拆成独立列，此时统计行扣 1 并补「K 品牌」。"""
    nodes = [
        _node("CH1", "电池", "upstream", companies=["宁德时代"]),
        _node("CH2", "整机厂", "midstream", core=True,
              companies=["亿航", "小鹏汇天", "峰飞航空"]),
        _node("CH3", "物流配送", "downstream"),
    ]
    spec = _spec(nodes)
    assert _use_core_body(nodes[1]) is True
    line = _stats_line(spec)
    # 核心被拆成独立列 → 中游不再计入该节点（1-1=0，整段不出现）
    assert "中游" not in line, line
    assert "3 品牌" in line, line


# 2026-10-21 删除 ``test_card_kind_for_marks_core_card_when_body_box_unavailable``：
# 被测函数 ``_card_kind_for`` 属旧四列版式的卡片分档，已随旧渲染器一起删除；
# 三列目录式里中游整机由 ``_lg_draw_core`` 直接画大卡，没有这层分派。


def test_core_card_renders_neutral_pending_badge_not_red_inferred():
    """联网补漏来源画中性「待核」；其余无证据节点仍画红色「推断」。

    区别只体现在角标文案与颜色上，卡片都保持虚线描边。
    """
    web_node = _node("CH1", "起降场建设", "support", tier="web_unverified")
    inf_node = _node("CH2", "保险服务", "support", tier="inferred")
    svg_web = render_chain_svg(_spec([web_node]))
    svg_inf = render_chain_svg(_spec([inf_node]))
    assert "待核" in svg_web and "推断" not in svg_web
    assert "推断" in svg_inf and "待核" not in svg_inf


# ════════════════════════════════════════════════════════════════════════════
# P0-B 拓扑裁判：核心节点确定性判定
# ════════════════════════════════════════════════════════════════════════════

def _raw(nid, label, stage, *, core=False, companies=None, eids=None):
    return {"id": nid, "label": label, "stage": stage, "is_core": core,
            "companies": list(companies or []), "key_products": [], "description": "",
            "evidence_ids": list(eids or [])}


def test_core_misplacement_moves_core_to_brand_heavy_midstream_node():
    """run-20261016232834 真实场景：核心算法(2 家) → 整机厂(7 家)。"""
    topo = {"core_product": "eVTOL/低空飞行器",
            "nodes": [_raw("n8", "核心算法", "midstream", core=True,
                           companies=["优刻得", "北纬科技"]),
                      _raw("n10", "整机厂", "midstream",
                           companies=["纵横股份", "万丰奥威", "沃飞长空",
                                      "亿航", "小鹏汇天", "峰飞航空", "绿的谐波"])],
            "edges": [{"source": "n8", "target": "n10", "label": "算法授权",
                       "flow": "technical"}]}
    move = core_misplacement(topo)
    assert move == ("n8", "n10")
    out, notes = normalize_core_node(topo)
    cores = [n["label"] for n in out["nodes"] if n.get("is_core")]
    assert cores == ["整机厂"]
    assert any("重指派" in n for n in notes)


def test_core_misplacement_leaves_correct_topology_alone():
    """核心已经是企业最多的整机/本体节点 → 不动（不制造无谓改动）。"""
    topo = {"core_product": "机器人",
            "nodes": [_raw("M1", "整机厂", "midstream", core=True,
                           companies=["A", "B", "C", "D"]),
                      _raw("M2", "组装产线", "midstream", companies=["E"])],
            "edges": []}
    assert core_misplacement(topo) is None
    out, notes = normalize_core_node(topo)
    assert notes == []
    assert [n["label"] for n in out["nodes"] if n.get("is_core")] == ["整机厂"]


def test_core_misplacement_no_move_when_no_node_reaches_threshold():
    """所有节点企业数都 <3 → 无从判定更优，保持原样（宁可不改，也不乱改）。"""
    topo = {"core_product": "低空飞行器",
            "nodes": [_raw("M1", "核心算法", "midstream", core=True, companies=["A"]),
                      _raw("M2", "整机厂", "midstream", companies=["B"])],
            "edges": []}
    assert core_misplacement(topo) is None
    out, notes = normalize_core_node(topo)
    assert notes == []


def test_core_misplacement_ignores_multi_or_missing_core():
    """无核心 / 多核心 交给既有规则处理，本函数不越权。"""
    assert core_misplacement({"nodes": [_raw("M1", "整机厂", "midstream")]}) is None
    assert core_misplacement(
        {"nodes": [_raw("M1", "整机厂", "midstream", core=True, companies=["A", "B", "C"]),
                _raw("M2", "组装", "midstream", core=True, companies=["D", "E", "F"])]}
    ) is None


def test_normalize_core_node_is_idempotent():
    topo = {"core_product": "eVTOL",
            "nodes": [_raw("n8", "核心算法", "midstream", core=True, companies=["A", "B"]),
                    _raw("n10", "整机厂", "midstream", companies=["C", "D", "E"])],
            "edges": []}
    once, _ = normalize_core_node(copy.deepcopy(topo))
    twice, notes2 = normalize_core_node(copy.deepcopy(once))
    assert [n["label"] for n in once["nodes"] if n.get("is_core")] == \
           [n["label"] for n in twice["nodes"] if n.get("is_core")]
    assert notes2 == [], notes2


def test_rd_named_node_never_keeps_core():
    """研发/算法类节点即使企业不多，也不该长期占位核心。"""
    topo = {"core_product": "飞行器",
            "nodes": [_raw("M1", "飞控算法研发", "midstream", core=True, companies=["A", "B"]),
                    _raw("M2", "整机总装", "midstream", companies=["C", "D", "E", "F"])],
            "edges": []}
    move = core_misplacement(topo)
    assert move is not None and move[1] == "M2"


# ── 流线规则：口径改为「类型」而非「是否核心」────────────────────────────────

def test_material_may_target_core_body_node():
    """整机/本体核心节点**可以**接收物料流——它就是把零部件装成整机的那一环。"""
    topo = {"core_product": "eVTOL",
            "nodes": [_raw("U1", "电池", "upstream", companies=["宁德时代"]),
                      _raw("M1", "整机厂", "midstream", core=True,
                           companies=["亿航", "小鹏汇天", "峰飞"])],
            "edges": [{"source": "U1", "target": "M1", "label": "电池包",
                       "flow": "material"}]}
    errs = validate_topology(topo)
    assert not any("实物流" in e for e in errs), errs


def test_material_cannot_target_rd_node():
    """物料流不得指向研发/算法/仿真类节点（只出图纸与授权）。"""
    topo = {"core_product": "eVTOL",
            "nodes": [_raw("U1", "电池", "upstream", companies=["宁德时代"]),
                      _raw("M1", "飞控算法研发", "midstream", companies=["X"])],
            "edges": [{"source": "U1", "target": "M1", "label": "电池包",
                       "flow": "material"}]}
    errs = validate_topology(topo)
    assert any("实物流" in e for e in errs), errs


def test_recycle_from_support_downgrades_to_service_not_redirect():
    """配套节点发出的「运维/回收」边 = 服务挂接，降级 service，**不要**改指另一个配套节点。

    旧实现会把它重定向到另一个 support 节点（实测：运维回收 → 数据服务），语义被改掉。
    """
    topo = {"core_product": "eVTOL",
            "nodes": [_raw("U1", "电池", "upstream", companies=["宁德时代"]),
                      _raw("M1", "整机厂", "midstream", core=True,
                           companies=["亿航", "小鹏汇天", "峰飞"]),
                      _raw("S1", "运维回收", "support", companies=["海特高新"]),
                      _raw("S2", "数据服务", "support", companies=["优刻得"])],
            "edges": [{"source": "U1", "target": "M1", "label": "电池包", "flow": "material"},
                     {"source": "S1", "target": "M1", "label": "维护回收", "flow": "recycle"}]}
    fixed, repairs = repair_topology(topo)
    edge = next(e for e in fixed["edges"] if e["label"] == "维护回收")
    assert edge["flow"] == "service", edge
    assert edge["target"] == "M1", "不得改指另一个配套节点"
    assert any("降级为 service" in r for r in repairs)


def test_core_degree_limit_is_generous():
    """整机/本体是价值汇聚枢纽，连线上限放宽到 16（实测整机厂有 14 条）。"""
    assert degree_limit("midstream", True) == 16
    assert degree_limit("midstream", False) == 12
    assert degree_limit("upstream", False) == 8


def test_real_topology_keeps_all_main_edges_after_repair():
    """真实拓扑修复后：核心迁到整机厂，且主链路连线**一条都不能少**。"""
    if not os.path.exists(FIXTURE):
        pytest.skip("真实拓扑 fixture 未生成")
    topo = json.loads(open(FIXTURE, encoding="utf-8").read())
    fixed, _ = repair_topology(topo, allowed_companies=None, allowed_evidence=None)
    labels = [e["label"] for e in fixed["edges"]]
    # 夹具里所有原始连线标签都必须保留（度数超限不得再删主链路）
    original = [e["label"] for e in topo["edges"]]
    missing = [l for l in original if l not in labels]
    assert not missing, f"修复后丢失连线：{missing}"


# ════════════════════════════════════════════════════════════════════════════
# P2 实体归一
# ════════════════════════════════════════════════════════════════════════════

def test_company_alias_corrects_known_typo():
    """实测错字「四川九州」→「四川九洲」。"""
    assert normalize_company_name("四川九州") == "四川九洲"
    assert "四川九州" in COMPANY_ALIAS


def test_company_alias_is_conservative():
    """不在别名表里的名字必须原样返回（首尾空白除外），绝不模糊改写。"""
    for name in ("宁德时代", "亿航智能", "四川九洲", ""):
        assert normalize_company_name(name) == name


# ════════════════════════════════════════════════════════════════════════════
# 行业通识企业通道（2026-10-17 修2）：问财只覆盖 A 股，不能逼着图用概念股
# ════════════════════════════════════════════════════════════════════════════

def test_industry_common_companies_bypass_whitelist():
    """eVTOL 三强/低空基建龙头不在问财白名单 → 行业通识 tier 放行，不判"编造"。"""
    topo = {"core_product": "eVTOL",
            "nodes": [_raw("U1", "电池", "upstream", companies=["宁德时代"]),
                      _raw("M1", "整机厂", "midstream", core=True,
                           companies=["亿航智能", "小鹏汇天", "峰飞航空"], eids=["R1"])],
            "edges": [{"source": "U1", "target": "M1", "label": "电池包", "flow": "material"}]}
    topo["nodes"][1]["evidence_ids"] = []          # 整机厂取不到问财证据
    # 证据状态定下来之后再打 tier（顺序反了会被误判成 evidence）
    for n in topo["nodes"]:
        n["source_tier"] = ("evidence" if n.get("evidence_ids")
                            else ("industry_common" if n.get("companies") else "inferred"))
    errs = validate_topology(topo, allowed_companies={"宁德时代"})
    assert not any("不在证据白名单" in e for e in errs), errs


def test_repair_keeps_industry_common_companies():
    """repair 不得摘除行业通识企业（旧实现会当成不可追溯企业清掉）。"""
    topo = {"core_product": "eVTOL",
            "nodes": [_raw("M1", "整机厂", "midstream", core=True,
                           companies=["亿航智能", "小鹏汇天", "峰飞航空"], eids=["R1"])],
            "edges": []}
    topo["nodes"][0]["evidence_ids"] = []
    topo["nodes"][0]["source_tier"] = "industry_common"
    fixed, repairs = repair_topology(topo, allowed_companies={"宁德时代", "亿纬锂能"})
    comps = fixed["nodes"][0]["companies"]
    # 2026-10-21：repair 现在会**补齐**完全缺失的画像龙头（沃飞长空/时的科技），
    # 但原 3 家通识企业必须原样保留、不得摘除。
    assert [c for c in comps if c in {"亿航智能", "小鹏汇天", "峰飞航空"}] == \
        ["亿航智能", "小鹏汇天", "峰飞航空"]
    assert not any("摘除不可追溯企业" in r for r in repairs)


def test_evidence_tier_companies_still_checked():
    """有证据节点的企业名仍走白名单强校验（不能借 industry_common 通道放水）。"""
    topo = {"core_product": "eVTOL",
            "nodes": [_raw("M1", "整机厂", "midstream", core=True,
                           companies=["亿航智能", "凭空编造的公司"], eids=["R1"])],
            "edges": []}
    topo["nodes"][0]["source_tier"] = "evidence"
    errs = validate_topology(topo, allowed_companies={"宁德时代"})
    assert any("不在证据白名单" in e for e in errs), errs


# ── 企业名可追溯性分层：行业龙头不许被当编造摘掉（2026-10-17）────────────────

def test_classify_keeps_industry_leaders():
    """节点有证据但企业名超出 A 股 → tier 降 industry_common、名字保留。

    实测背景（run-20261017150633）：A2 把整机厂写成 8 家（亿航/小鹏汇天/峰飞/沃飞长空/
    大疆/纵横/极飞/中航成飞），问财只覆盖 A 股 → 后 6 家被 repair 当"编造"摘掉，
    品牌列从 8 家砍到 2 家，行业代表性归零。
    """
    topo = {"core_product": "eVTOL",
            "nodes": [_raw("M1", "整机厂", "midstream", core=True,
                           companies=["纵横股份", "亿航智能", "大疆", "极飞"],
                           eids=["R1"])],
            "edges": []}
    tiered, notes = classify_company_traceability(
        topo, allowed_companies={"纵横股份"}, evidence_text="纵横股份 主营无人机")
    node = tiered["nodes"][0]
    assert node["source_tier"] == "industry_common"
    assert node["companies"] == ["纵横股份", "亿航智能", "大疆", "极飞"], "名字必须全保留"
    assert any("保留行业通识企业" in n for n in notes), notes


def test_classify_skips_nodes_without_evidence():
    """节点本身无证据 → 不动，仍交给 repair 按旧规则摘除（防全面放水）。"""
    topo = {"core_product": "eVTOL",
            "nodes": [_raw("M1", "整机厂", "midstream", core=True,
                           companies=["亿航智能"], eids=[])],
            "edges": []}
    tiered, notes = classify_company_traceability(
        topo, allowed_companies={"宁德时代"}, evidence_text="")
    assert tiered["nodes"][0].get("source_tier") != "industry_common"
    assert notes == []


def test_classify_noop_when_all_traceable():
    topo = {"core_product": "eVTOL",
            "nodes": [_raw("M1", "整机厂", "midstream", core=True,
                           companies=["纵横股份"], eids=["R1"])],
            "edges": []}
    tiered, notes = classify_company_traceability(
        topo, allowed_companies={"纵横股份"}, evidence_text="")
    assert tiered["nodes"][0].get("source_tier") != "industry_common"
    assert notes == []


def test_repair_keeps_leaders_after_classification():
    """端到端：分层后 repair 不再摘除龙头，品牌列完整保留。"""
    topo = {"core_product": "eVTOL",
            "nodes": [_raw("U1", "电池", "upstream", companies=["宁德时代"], eids=["R1"]),
                      _raw("M1", "整机厂", "midstream", core=True,
                           companies=["纵横股份", "亿航智能", "小鹏汇天", "峰飞航空",
                                      "沃飞长空", "大疆", "极飞", "中航成飞"],
                           eids=["R1"])],
            "edges": [{"source": "U1", "target": "M1", "label": "电池包", "flow": "material"}]}
    tiered, _ = classify_company_traceability(
        topo, allowed_companies={"宁德时代", "纵横股份"}, evidence_text="纵横股份")
    fixed, repairs = repair_topology(tiered, allowed_companies={"宁德时代", "纵横股份"},
                                     allowed_evidence={"R1"}, evidence_text="纵横股份")
    core = next(n for n in fixed["nodes"] if n.get("is_core"))
    # 2026-10-21：补齐缺失龙头后可能 ≥8 家（MAX_BRANDS 截断），原有 8 家必须全保留。
    assert len(core["companies"]) >= 8, core["companies"]
    assert "亿航智能" in core["companies"] and "大疆" in core["companies"]
    assert not any("摘除不可追溯企业" in r for r in repairs), repairs


def test_industry_common_node_renders_without_inferred_badge():
    """行业通识节点：正常实线卡片，不画红色「推断」角标。"""
    node = _node("CH1", "起降装置", "upstream", tier="industry_common",
                 items=["起落架", "刹车系统"])
    svg = render_chain_svg(_spec([node]))
    assert "推断" not in svg
    assert "起落架" in svg


def test_three_empty_still_flagged_inferred():
    """证据/企业/细分品类三项全空 → 红色「推断」仍在（防幻觉底线不放宽）。"""
    node = _node("CH1", "某无据环节", "upstream", tier="inferred")
    svg = render_chain_svg(_spec([node]))
    assert "推断" in svg


# ════════════════════════════════════════════════════════════════════════════
# P3 博查 L3 受控补漏：范围红线
# ════════════════════════════════════════════════════════════════════════════

def test_web_search_disabled_by_default():
    """默认关闭；没配 key 一律关闭（哪怕开关位被置真）。"""
    assert resolve_web_search_config({}).enabled is False
    assert resolve_web_search_config({"ENABLE_WEB_SEARCH_FOR_CHAIN": "1"}).enabled is False
    assert WebSearchConfig(enabled=False, api_key="k").enabled is False


def test_web_search_scope_is_chain_only():
    """作用域枚举里只有 industry_chain 一个合法值。"""
    assert ALLOWED_SCOPES == ("industry_chain",)
    cfg = WebSearchConfig(enabled=True, api_key="k")
    cfg.require_scope("industry_chain")          # 合法，不抛
    with pytest.raises(ValueError, match="仅限产业链图"):
        cfg.require_scope("financials")
    with pytest.raises(ValueError, match="仅限产业链图"):
        cfg.require_scope("market_quote")


def test_web_search_client_rejects_non_chain_scope():
    """客户端层再拦一道：非产业链作用域直接 ValueError，不发请求。"""
    client = WebSearchClient(WebSearchConfig(enabled=True, api_key="k"))
    with pytest.raises(ValueError):
        asyncio.run(client.search("某公司 营业收入", scope="financials"))  # type: ignore[arg-type]
    assert client.calls_used == 0


def test_web_search_when_disabled_makes_no_call():
    cfg = WebSearchConfig(enabled=False, api_key="k")
    client = WebSearchClient(cfg)
    assert asyncio.run(client.search("低空经济 整机厂 代表公司", scope="industry_chain")) == []
    assert client.calls_used == 0


def test_web_search_call_budget_is_capped():
    """额度封顶：用完即停，不重试。"""
    cfg = WebSearchConfig(enabled=True, api_key="k", call_budget=2, timeout_seconds=0.01)
    client = WebSearchClient(cfg, transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"code": 200})))
    assert cfg.call_budget == 2
    assert client.exhausted is False


# ── 缺口检测 ────────────────────────────────────────────────────────────────

COMPLETE_TOPO = {
    "core_product": "eVTOL",
    "nodes": [_raw(f"U{i}", f"零部件{i}", "upstream", companies=[f"公司{i}"]) for i in range(1, 8)]
    + [_raw("M1", "整机厂", "midstream", core=True,
            companies=["亿航", "小鹏汇天", "峰飞", "沃飞长空", "大疆", "极飞"]),
       _raw("D1", "物流配送", "downstream"),
       _raw("S1", "起降场与空管平台", "support", companies=["深城交"])],
    "edges": [{"source": "U1", "target": "M1", "label": "电池包", "flow": "material"},
              {"source": "M1", "target": "D1", "label": "整机交付", "flow": "material"},
              {"source": "S1", "target": "U1", "label": "维护回收", "flow": "recycle"}],
}


def test_gap_detection_silent_on_complete_topology():
    """结构完整 → 0 结构缺口（品牌列偏薄另有 thin_brand_list 口径，见下）。"""
    gaps = detect_chain_gaps(COMPLETE_TOPO)
    assert [g.kind for g in gaps] == [], [g.kind for g in gaps]


def test_gap_detection_flags_missing_core_body():
    """核心节点企业不足 → 判定为缺口（这就是"品牌列消失"的根因信号）。"""
    gaps = detect_chain_gaps({
        "core_product": "eVTOL",
        "nodes": [_raw("U1", "电池", "upstream", companies=["宁德时代"]),
                  _raw("M1", "整机厂", "midstream", core=True, companies=["亿航"])],
        "edges": [],
    })
    assert any(g.kind == "missing_core_body" for g in gaps)


def test_gap_detection_flags_thin_brand_list():
    """品牌列够渲染但不够研报级 → thin_brand_list（把亿航/大疆/极飞拉进来的入口）。"""
    gaps = detect_chain_gaps({
        "core_product": "eVTOL",
        "nodes": [_raw("U1", "电池", "upstream", companies=["宁德时代"]),
                  _raw("M1", "整机厂", "midstream", core=True,
                       companies=["A", "B", "C"])],        # 3 家：能渲染但偏薄
        "edges": [],
    })
    kinds = [g.kind for g in gaps]
    assert "thin_brand_list" in kinds, kinds
    assert "missing_core_body" not in kinds, kinds


def test_gap_detection_no_thin_flag_when_brands_rich():
    """品牌列已达研报级（≥6）→ 不再报 thin_brand_list。"""
    gaps = detect_chain_gaps({
        "core_product": "eVTOL",
        "nodes": [_raw("U1", "电池", "upstream", companies=["宁德时代"]),
                  _raw("M1", "整机厂", "midstream", core=True,
                       companies=["A", "B", "C", "D", "E", "F"])],
        "edges": [],
    })
    assert "thin_brand_list" not in [g.kind for g in gaps]


def test_gap_queries_are_targeted_and_clean():
    """query 必须定向（带实体+主题词），词数 ≤7，且不含标点。"""
    gaps = detect_chain_gaps({
        "core_product": "eVTOL",
        "nodes": [_raw("U1", "电池", "upstream", companies=["宁德时代"]),
                  _raw("M1", "整机厂", "midstream", core=True, companies=["亿航"]),
                  _raw("D1", "物流配送", "downstream")],
        "edges": [],
    })
    queries = build_gap_queries("低空经济", gaps)
    assert queries, "有缺口就应产出 query"
    for q in queries:
        assert len(q.split()) <= _QUERY_MAX_TERMS
        assert not _PUNCT_RE.search(q)
        assert "低空经济" in q or "低空" in q


def test_gap_queries_empty_when_no_gap():
    assert build_gap_queries("低空经济", []) == []


# ── 回填：只补缺、不覆盖、不带数字 ──────────────────────────────────────────

def _hits():
    return [
        WebHit(title="低空经济整机厂商名单", url="https://www.stcn.com/a/1",
               source_org="证券时报", snippet="亿航智能、小鹏汇天、峰飞航空等整机厂商",
               published_at="2026-09-01", retrieved_at="2026-10-17"),
        WebHit(title="排名", url="https://www.stcn.com/a/2",
               source_org="证券时报", snippet="2025年营收增长30%的公司",
               published_at="2026-09-02", retrieved_at="2026-10-17"),
    ]


def test_apply_gap_hits_only_fills_empty_slots():
    """已有企业/品类的节点**不得**被联网内容覆盖（避免联网污染已确证数据）。"""
    topo = {"core_product": "eVTOL",
            "nodes": [_raw("M1", "整机厂", "midstream", core=True, companies=["已有公司A"])],
            "edges": []}
    fixed, notes = asyncio.run(apply_gap_hits(topo, _hits()))
    assert fixed["nodes"][0]["companies"] == ["已有公司A"]
    assert not any("补入代表企业候选" in n for n in notes), notes


def test_apply_gap_hits_drops_numeric_fragments():
    """含数字的片段一律丢弃——联网内容永不进数值计算链（红线 C-10）。"""
    hits = _hits()
    terms = extract_segment_terms(hits)
    assert all(not re.search(r"\d", t) for t in terms)


def test_apply_gap_hits_never_adds_nodes():
    """结构由 LLM 负责，联网**只补内容、不新增节点**。"""
    topo = {"core_product": "eVTOL",
            "nodes": [_raw("U1", "电池", "upstream"),
                      _raw("M1", "整机厂", "midstream", core=True)],
            "edges": []}
    fixed, _ = asyncio.run(apply_gap_hits(topo, _hits()))
    assert len(fixed["nodes"]) == len(topo["nodes"])


def test_fill_chain_gaps_noop_when_client_missing():
    topo = copy.deepcopy(COMPLETE_TOPO)
    out, diag = asyncio.run(fill_chain_gaps(topo, subject="低空经济", client=None))
    assert out == topo
    assert diag["enabled"] is False
    assert diag["hits"] == 0


def test_web_hit_tier_is_always_web_unverified():
    hit = _hits()[0]
    assert hit.tier == "web_unverified"
    assert hit.qualitative_only is True
    assert hit.acquisition_level == 3


# ── LLM 归纳抽取（2026-10-17 接入博查 key 后升级）───────────────────────────

_STUB_LLM_REPLY = ('```json\n{"segments": ["eVTOL整机", "工业无人机"], '
                   '"companies": {"整机厂": ["亿航智能", "小鹏汇天", "峰飞航空", "大疆"]}}\n```')


async def _stub_llm(system: str, user: str) -> str:
    return _STUB_LLM_REPLY


def test_extract_with_llm_parses_json_and_drops_numbers():
    segs, grouped = asyncio.run(extract_with_llm(
        _hits(), subject="低空经济", call_llm=_stub_llm))
    assert grouped == {"整机厂": ["亿航智能", "小鹏汇天", "峰飞航空", "大疆"]}
    assert segs == ["eVTOL整机", "工业无人机"]


def test_extract_with_llm_discards_numeric_fragments():
    """LLM 违反铁律 5 时，代码层仍要把数字片段拦掉（红线 C-10 双保险）。"""
    async def bad(_s, _u):
        return '{"segments": ["营收增长30%"], "companies": {"整机厂": ["某公司", "增长20%企业"]}}'
    segs, grouped = asyncio.run(extract_with_llm(_hits(), subject="x", call_llm=bad))
    assert segs == []
    assert grouped == {"整机厂": ["某公司"]}, grouped


def test_extract_with_llm_failure_returns_empty():
    async def boom(_s, _u):
        raise RuntimeError("timeout")
    segs, grouped = asyncio.run(extract_with_llm(_hits(), subject="x", call_llm=boom))
    assert segs == [] and grouped == {}


def test_extract_with_llm_fills_each_gap_node_by_label():
    """按环节名分组：整机厂的企业不能张冠李戴到零部件环节（实测踩坑）。"""
    async def llm(_s, _u):
        return ('{"segments": [], "companies": {'
                '"整机厂": ["亿航智能", "小鹏汇天"], '
                '"起降装置": ["万丰奥威"], '
                '"感知传感器": ["睿创微纳"]}}')
    topo = {"core_product": "eVTOL",
            "nodes": [_raw("M1", "整机厂", "midstream", core=True),
                      _raw("U1", "起降装置", "upstream"),
                      _raw("U2", "感知传感器", "upstream")],
            "edges": []}
    fixed, notes = asyncio.run(apply_gap_hits(
        topo, _hits(), whitelist={"宁德时代"}, subject="低空经济", call_llm=llm))
    by = {n["label"]: n for n in fixed["nodes"]}
    assert by["整机厂"]["companies"] == ["亿航智能", "小鹏汇天"]
    assert by["起降装置"]["companies"] == ["万丰奥威"]
    assert by["感知传感器"]["companies"] == ["睿创微纳"]
    # 未过问财白名单 → 全部 web_unverified（图上中性「待核」）
    assert all(n["source_tier"] == "web_unverified" for n in fixed["nodes"])


def test_apply_gap_hits_prefers_llm_extraction():
    """提供了 call_llm 时优先用 LLM 归纳结果，不用正则兜底。"""
    topo = {"core_product": "eVTOL",
            "nodes": [_raw("M1", "整机厂", "midstream", core=True, eids=["R1"])],
            "edges": []}
    topo["nodes"][0]["evidence_ids"] = []
    fixed, notes = asyncio.run(apply_gap_hits(
        topo, _hits(), whitelist={"宁德时代"}, subject="低空经济", call_llm=_stub_llm))
    assert fixed["nodes"][0]["companies"] == ["亿航智能", "小鹏汇天", "峰飞航空", "大疆"]
    # 未过问财白名单 → web_unverified（图上中性「待核」）
    assert fixed["nodes"][0]["source_tier"] == "web_unverified"
    assert any("LLM 归纳" in n for n in notes)


def test_apply_gap_hits_marks_evidence_when_whitelist_confirms():
    """企业名过问财白名单 → evidence tier（不画「待核」）。"""
    topo = {"core_product": "eVTOL",
            "nodes": [_raw("M1", "整机厂", "midstream", core=True, eids=["R1"])],
            "edges": []}
    topo["nodes"][0]["evidence_ids"] = []
    fixed, _ = asyncio.run(apply_gap_hits(
        topo, _hits(), whitelist={"亿航智能", "小鹏汇天", "峰飞航空", "大疆"},
        subject="低空经济", call_llm=_stub_llm))
    assert fixed["nodes"][0]["source_tier"] == "evidence"


def test_apply_gap_hits_flat_array_still_allocated():
    """LLM 返回扁平数组（未分组）时仍按顺序分配，不丢内容。"""
    async def llm(_s, _u):
        return '{"segments": [], "companies": ["亿航智能", "小鹏汇天", "峰飞航空"]}'
    topo = {"core_product": "eVTOL",
            "nodes": [_raw("M1", "整机厂", "midstream", core=True)],
            "edges": []}
    fixed, _ = asyncio.run(apply_gap_hits(
        topo, _hits(), whitelist=set(), subject="低空经济", call_llm=llm))
    assert fixed["nodes"][0]["companies"] == ["亿航智能", "小鹏汇天", "峰飞航空"]


def test_fill_chain_gaps_passes_llm_through():
    """编排入口把 call_llm 一路传到 apply_gap_hits。"""

    class _FakeClient:
        def __init__(self, always=True):
            self._config = WebSearchConfig(enabled=True, api_key="k", always_search=always)
            self.exhausted = False

        async def search(self, q, *, scope="industry_chain", known_companies=(), required_terms=()):
            return _hits()

    topo = {"core_product": "eVTOL",
            "nodes": [_raw("M1", "整机厂", "midstream", core=True, eids=["R1"])],
            "edges": []}
    topo["nodes"][0]["evidence_ids"] = []
    out, diag = asyncio.run(fill_chain_gaps(
        topo, subject="低空经济", whitelist={"宁德时代"},
        client=_FakeClient(), call_llm=_stub_llm))
    assert diag["hits"] == 6          # 2 条 query × 3 条命中（预算 3，第二条后停止）
    assert out["nodes"][0]["companies"] == ["亿航智能", "小鹏汇天", "峰飞航空", "大疆"]
    assert diag["queries"], "有缺口就应产出定向 query"


# ── always_search：产业链图每次都要检索（2026-10-17 用户要求）────────────────

def test_always_search_fires_when_no_gap():
    """无结构缺口时也必须检索一次（用户要求"每次都要去博查搜索信息"）。"""

    class _FakeClient:
        def __init__(self):
            self._config = WebSearchConfig(enabled=True, api_key="k", always_search=True)
            self.exhausted = False
            self.calls = 0

        async def search(self, q, *, scope="industry_chain", known_companies=(), required_terms=()):
            self.calls += 1
            return _hits()

    client = _FakeClient()
    out, diag = asyncio.run(fill_chain_gaps(
        copy.deepcopy(COMPLETE_TOPO), subject="低空经济", whitelist=set(),
        client=client, call_llm=_stub_llm))
    assert client.calls >= 1, "always_search 开启时无缺口也要检索"
    assert diag["queries"], "应产出保底 query"
    assert diag["hits"] > 0
    assert any("always_search" in n for n in diag["notes"]), diag["notes"]


def test_always_search_false_skips_when_no_gap():
    """显式关闭 always_search 后恢复旧行为：无缺口不检索。"""

    class _FakeClient:
        def __init__(self):
            self._config = WebSearchConfig(enabled=True, api_key="k", always_search=False)
            self.exhausted = False
            self.calls = 0

        async def search(self, q, *, scope="industry_chain", known_companies=(), required_terms=()):
            self.calls += 1
            return _hits()

    client = _FakeClient()
    out, diag = asyncio.run(fill_chain_gaps(
        copy.deepcopy(COMPLETE_TOPO), subject="低空经济", whitelist=set(), client=client))
    assert client.calls == 0
    assert diag["queries"] == []


def test_always_search_backfill_query_is_targeted():
    """保底 query 也要定向（带主题 + 核心产品 + 行业标准检索词），不能是泛化整句。"""
    from chart_generator.websearch import ALWAYS_QUERY_TEMPLATE

    q = ALWAYS_QUERY_TEMPLATE.format(subject="低空经济", core_product="eVTOL")
    assert "低空经济" in q and "eVTOL" in q
    assert "整机厂商" in q and "龙头企业" in q
    assert len(q.split()) <= 7
    assert "/" not in q


def test_brand_list_augmented_not_overwritten():
    """品牌列偏薄 → 增补（已有名保留在前、新名去重追加），不覆盖已确证数据。"""

    async def llm(_s, _u):
        return ('{"segments": [], "companies": {"整机厂": '
                '["亿航智能", "小鹏汇天", "峰飞航空", "大疆"]}}')

    topo = {"core_product": "eVTOL",
            "nodes": [_raw("M1", "整机厂", "midstream", core=True,
                           companies=["纵横股份", "万丰奥威"])],
            "edges": []}
    fixed, notes = asyncio.run(apply_gap_hits(
        topo, _hits(), whitelist=set(), subject="低空经济", call_llm=llm))
    comps = fixed["nodes"][0]["companies"]
    assert comps[:2] == ["纵横股份", "万丰奥威"], "已有企业必须保留在前"
    assert "亿航智能" in comps and "大疆" in comps
    assert len(comps) == len(set(comps)), "不得重复"
    assert any("品牌列增补" in n for n in notes), notes


def test_resolve_config_always_search_default_on():
    cfg = resolve_web_search_config({"BOCHA_API_KEY": "k", "ENABLE_WEB_SEARCH_FOR_CHAIN": "1"})
    assert cfg.enabled is True and cfg.always_search is True
    off = resolve_web_search_config({"BOCHA_API_KEY": "k", "ENABLE_WEB_SEARCH_FOR_CHAIN": "1",
                                     "WEB_SEARCH_ALWAYS": "0"})
    assert off.always_search is False


# ── 方案 C：问财未收录主题时，博查兜底整条链（2026-10-17）──────────────────

MOUSE_TOPO = {
    "core_product": "鼠标",
    "nodes": [_raw("U1", "微动开关", "upstream"),
              _raw("U2", "光学传感器", "upstream"),
              _raw("M1", "鼠标整机", "midstream", core=True),
              _raw("D1", "电竞外设", "downstream")],
    "edges": [{"source": "U1", "target": "M1", "label": "微动", "flow": "material"},
              {"source": "M1", "target": "D1", "label": "成品", "flow": "material"}],
}


def test_uncovered_topic_detected_when_zero_evidence():
    """industry_chain 域 0 条 → uncovered_topic 缺口（最高优先级）。"""
    gaps = detect_chain_gaps(MOUSE_TOPO, evidence_count=0)
    assert any(g.kind == "uncovered_topic" for g in gaps), [g.kind for g in gaps]
    # 不传 evidence_count 或非 0 → 不误报
    assert not any(g.kind == "uncovered_topic" for g in detect_chain_gaps(MOUSE_TOPO))
    assert not any(g.kind == "uncovered_topic"
                   for g in detect_chain_gaps(MOUSE_TOPO, evidence_count=12))


def test_uncovered_topic_query_covers_whole_chain():
    """未收录时的 query 要带**具体部件词**，而不是「产业链/上游/龙头」这类通用词。

    实测教训：`鼠标 产业链 上中下游 环节 代表企业` 的 20 条原始召回里 19 条是
    医疗/服装/半导体泛化文章——搜索引擎就是按通用词在匹配。改成部件词后
    （`鼠标 微动开关 光学传感器 供应商 厂商`）才召回出 Logitech(罗技) 与
    「电磁微动鼠标」这类正确内容。
    """
    gaps = detect_chain_gaps(MOUSE_TOPO, evidence_count=0)
    queries = build_gap_queries("鼠标", gaps, core_product="鼠标")
    assert queries
    joined = " ".join(queries)
    # 必须含主题词
    for q in queries:
        assert "鼠标" in q
        assert len(q.split()) <= 7
        assert "/" not in q
    # 必须含具体部件词（来自拓扑节点名），不能只有通用词
    assert any("微动" in q or "光学" in q for q in queries), queries
    # 通用词堆砌的旧 query 不得出现
    assert "上中下游" not in joined and "全景" not in joined, joined


def test_uncovered_topic_fills_all_nodes_not_just_empty():
    """未收录时全部节点都要补企业（只补"缺的"等于大半张图还是空的）。"""
    async def llm(_s, user):
        # 断言 LLM 被要求给出全部 4 个环节
        for label in ("微动开关", "光学传感器", "鼠标整机", "电竞外设"):
            assert label in user, f"提示词里缺环节 {label}"
        return ('{"segments": ["光学引擎", "微动开关"], "companies": {'
                '"微动开关": ["欧姆龙"], "光学传感器": ["原相科技"], '
                '"鼠标整机": ["罗技", "雷蛇", "雷柏科技"], "电竞外设": ["雷蛇"]}}')

    class _FakeClient:
        def __init__(self):
            self._config = WebSearchConfig(enabled=True, api_key="k", always_search=True)
            self.exhausted = False

        async def search(self, q, *, scope="industry_chain", known_companies=(), required_terms=()):
            return _hits()

    out, diag = asyncio.run(fill_chain_gaps(
        copy.deepcopy(MOUSE_TOPO), subject="鼠标", whitelist=set(),
        client=_FakeClient(), call_llm=llm, evidence_count=0))
    assert diag["topic_uncovered"] is True
    by = {n["label"]: n for n in out["nodes"]}
    assert by["鼠标整机"]["companies"] == ["罗技", "雷蛇", "雷柏科技"]
    assert by["微动开关"]["companies"] == ["欧姆龙"]
    assert by["光学传感器"]["companies"] == ["原相科技"]
    assert by["电竞外设"]["companies"] == ["雷蛇"]
    # 全部 web_unverified（问财复核不了）→ 图上中性「待核」
    assert all(n.get("source_tier") == "web_unverified"
               for n in out["nodes"] if n.get("companies"))


def test_uncovered_topic_false_when_evidence_present():
    """有证据时 topic_uncovered=False，走原缺口逻辑。"""
    class _FakeClient:
        def __init__(self):
            self._config = WebSearchConfig(enabled=True, api_key="k", always_search=True)
            self.exhausted = False

        async def search(self, q, *, scope="industry_chain", known_companies=(), required_terms=()):
            return _hits()

    out, diag = asyncio.run(fill_chain_gaps(
        copy.deepcopy(COMPLETE_TOPO), subject="低空经济", whitelist=set(),
        client=_FakeClient(), call_llm=_stub_llm, evidence_count=20))
    assert diag["topic_uncovered"] is False


def test_uncovered_topic_no_new_nodes():
    """兜底补企业不新增节点——结构仍是 LLM 的职责（红线不变）。"""
    async def llm(_s, _u):
        return ('{"segments": [], "companies": {"微动开关": ["欧姆龙"], '
                '"新增的假环节": ["某公司"]}}')

    class _FakeClient:
        def __init__(self):
            self._config = WebSearchConfig(enabled=True, api_key="k", always_search=True)
            self.exhausted = False

        async def search(self, q, *, scope="industry_chain", known_companies=(), required_terms=()):
            return _hits()

    out, _ = asyncio.run(fill_chain_gaps(
        copy.deepcopy(MOUSE_TOPO), subject="鼠标", whitelist=set(),
        client=_FakeClient(), call_llm=llm, evidence_count=0))
    assert len(out["nodes"]) == len(MOUSE_TOPO["nodes"]), "不得新增节点"
    assert "新增的假环节" not in [n["label"] for n in out["nodes"]]


# ── 相关性关卡：通用词不能当相关性证据（2026-10-17 实测踩坑）──────────────

def test_generic_terms_excluded_from_relevance():
    """「产业链/环节/代表企业」是通用词，不能单独作为相关性证据。

    实测：query「鼠标 产业链 上中下游 环节 代表企业」的 20 条原始召回里 19 条是
    医疗/服装/半导体泛化文章，只因为含「产业链」就被判相关 →
    LLM 归纳出「医用原材料／高值医用耗材」，被填进「微动开关」的品类栏。
    """
    from chart_generator.websearch import _relevance_tokens

    specific, generic = _relevance_tokens("鼠标 产业链 上中下游 环节 代表企业")
    assert specific == ["鼠标"], specific
    assert "产业链" in generic and "环节" in generic and "代表企业" in generic

    specific2, _ = _relevance_tokens("低空经济 eVTOL 整机厂商 代表企业")
    assert specific2 == ["低空经济", "eVTOL", "整机厂商"], specific2


def test_relevance_requires_specific_token():
    """相关性判定只认实义词：只有通用词命中的文章必须被丢弃。"""
    payload = {"code": 200, "data": {"webPages": {"value": [
        {"name": "医疗器械产业链分析_上下游企业名录", "url": "https://www.qianzhan.com/a",
         "snippet": "医疗器械产业链上下游企业名录与代表企业梳理",
         "siteName": "前瞻产业研究院", "datePublished": "2026-09-01"},
        {"name": "鼠标产业链全景：微动开关与光学引擎供应商", "url": "https://www.qianzhan.com/b",
         "snippet": "鼠标上游微动开关、光学传感器供应商与整机品牌厂商梳理",
         "siteName": "前瞻产业研究院", "datePublished": "2026-09-02"},
    ]}}}

    cfg = WebSearchConfig(enabled=True, api_key="k")
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=payload))
    client = WebSearchClient(cfg, transport=transport)

    hits = asyncio.run(client.search("鼠标 产业链 上中下游 环节 代表企业",
                                     scope="industry_chain"))
    titles = [h.title for h in hits]
    assert any("鼠标" in t for t in titles), titles
    assert not any("医疗器械" in t for t in titles), f"医疗文章不该通过：{titles}"


# ── 品类词按环节分配，不许三张卡塞同一批词 ────────────────────────────────

def test_segment_terms_matched_per_node():
    """品类词只填给"词里含该环节关键词"的节点，不做无差别铺开。

    实测踩坑：旧实现取前 3 个空节点各填同一批词，把「触觉感应触发系统」
    同时塞给「微动开关／光学传感器／主控芯片」——三张卡内容一模一样且都不准。
    """
    async def llm(_s, _u):
        return ('{"segments": ["电磁微动鼠标", "触觉感应触发系统", "光学引擎"], '
                '"companies": {}}')

    topo = {"core_product": "鼠标",
            "nodes": [_raw("U1", "微动开关", "upstream"),
                      _raw("U2", "光学传感器", "upstream"),
                      _raw("U3", "主控芯片", "upstream"),
                      _raw("M1", "鼠标整机", "midstream", core=True)],
            "edges": []}
    fixed, notes = asyncio.run(apply_gap_hits(
        topo, _hits(), whitelist=set(), subject="鼠标", call_llm=llm))
    by = {n["label"]: n.get("key_products") or [] for n in fixed["nodes"]}
    # 微动开关只拿含"微动"的词
    assert by["微动开关"] == ["电磁微动鼠标"], by
    # 光学传感器只拿含"光学"的词
    assert by["光学传感器"] == ["光学引擎"], by
    # 主控芯片没有匹配词 → 保持空，不许乱塞
    assert by["主控芯片"] == [], by
    assert any("细分品类词" in n for n in notes), notes


# ════════════════════════════════════════════════════════════════════════════
# 企业跨节点唯一性（2026-10-17 硬规则）：一家公司只能出现在一个环节
# ════════════════════════════════════════════════════════════════════════════

def test_duplicate_company_rejected_by_validator():
    """同一家企业出现在两个节点 → 裁判必须报错。

    实测（run-20261017180913）：华测导航/北斗星通同时在「飞控导航」与「通导监」，
    超图软件/川大智胜同时在「飞控算法」与「仿真训练」；旧实现只查节点 id 重复，
    从未查过企业，所以三层（提示词/裁判/修复）全漏。
    """
    topo = {"core_product": "eVTOL",
            "nodes": [_raw("U1", "飞控/导航", "upstream", companies=["华测导航", "北斗星通"]),
                      _raw("S1", "通导监", "support", companies=["华测导航", "北斗星通"]),
                      _raw("M1", "整机厂", "midstream", core=True, companies=["亿航"])],
            "edges": []}
    errs = validate_topology(topo)
    dup = [e for e in errs if "重复出现" in e]
    assert len(dup) == 2, dup
    assert all("华测导航" in e or "北斗星通" in e for e in dup)


def test_repair_keeps_duplicate_in_support_layer():
    """去重时保留在 support（专精环节）——符合用户裁定：
    华测导航/北斗星通 → 通导监；超图软件/川大智胜 → 仿真训练。"""
    topo = {"core_product": "eVTOL",
            "nodes": [_raw("U1", "飞控/导航", "upstream", companies=["华测导航", "北斗星通"]),
                      _raw("S1", "通导监", "support", companies=["华测导航", "北斗星通"]),
                      _raw("M1", "整机厂", "midstream", core=True, companies=["亿航"])],
            "edges": []}
    fixed, repairs = repair_topology(topo)
    by = {n["label"]: n["companies"] for n in fixed["nodes"]}
    assert by["通导监"] == ["华测导航", "北斗星通"], by
    # 🔴 2026-10-19 F10：被抽空的卡不再留空——按角色锚点补**该环节的专业公司**。
    # 「飞控/导航」应补航电/惯导类（航天电子、晨曦航空），而不是电机/发动机类
    # （首版实现就填成了 卧龙电驱/宗申动力，见 test_chain_profile_20261019）。
    fill = by["飞控/导航"]
    for wrong in ("卧龙电驱", "宗申动力", "光威复材", "中简科技"):
        assert wrong not in fill, f"「飞控/导航」被错配：{fill}"
    for ok in ("航天电子", "晨曦航空"):
        assert ok in fill, f"「飞控/导航」缺航电/惯导专业公司：{fill}"
    assert len([r for r in repairs if "重复出现" in r]) == 2


def test_repair_prefers_scarcer_node_within_same_stage():
    """同 stage 内 → 保留在企业数更少的节点（那里更需要它撑门面）。"""
    topo = {"core_product": "eVTOL",
            "nodes": [_raw("M1", "整机厂", "midstream", core=True,
                           companies=["亿航", "航天电子"]),
                      _raw("M2", "飞控算法", "midstream", companies=["航天电子"]),
                      _raw("M3", "系统集成", "midstream",
                           companies=["航天电子", "中航西飞", "中直股份"])],
            "edges": []}
    fixed, repairs = repair_topology(topo)
    by = {n["label"]: n["companies"] for n in fixed["nodes"]}
    assert by["飞控算法"] == ["航天电子"], by          # 1 家，最稀缺
    assert "航天电子" not in by["整机厂"], by
    assert "航天电子" not in by["系统集成"], by
    assert any("航天电子" in r and "重复出现" in r for r in repairs), repairs


def test_repair_dedup_is_idempotent():
    """去重后再跑一次不应产生新动作（幂等）。"""
    topo = {"core_product": "eVTOL",
            "nodes": [_raw("U1", "感知传感器", "upstream", companies=["华测导航"]),
                      _raw("S1", "通导监", "support", companies=["华测导航"]),
                      _raw("M1", "整机厂", "midstream", core=True, companies=["亿航"])],
            "edges": []}
    once, _ = repair_topology(topo)
    twice, repairs2 = repair_topology(once)
    assert not [r for r in repairs2 if "重复出现" in r], repairs2
    by = {n["label"]: n["companies"] for n in twice["nodes"]}
    assert by["通导监"] == ["华测导航"]


def test_validator_passes_when_no_duplicate():
    """无重复时不误报（阴性对照）。"""
    topo = {"core_product": "eVTOL",
            "nodes": [_raw("U1", "动力电池", "upstream", companies=["宁德时代"]),
                      _raw("S1", "通导监", "support", companies=["华测导航"]),
                      _raw("M1", "整机厂", "midstream", core=True, companies=["亿航"])],
            "edges": []}
    errs = validate_topology(topo)
    assert not [e for e in errs if "重复出现" in e], errs


# ── 定向 query 生成（2026-10-17 重写：不复述节点名）────────────────────────

def test_gap_queries_use_industry_terms_not_node_labels():
    """query 必须是行业流通说法，不能复述 LLM 概括的节点名。"""
    gaps = detect_chain_gaps({
        "core_product": "eVTOL/低空飞行器",
        "nodes": [_raw("M1", "核心算法", "midstream", core=True, companies=["A", "B"]),
                  _raw("M2", "整机厂", "midstream", companies=["C"])],
        "edges": [],
    })
    queries = build_gap_queries("低空经济", gaps)
    assert queries
    for q in queries:
        assert "核心算法" not in q, f"不该复述节点名：{q}"
        assert "低空经济" in q
        assert len(q.split()) <= 7
        assert "/" not in q, f"query 不应含斜杠（会毁掉相关性匹配）：{q}"
    assert any("整机厂商" in q or "龙头企业" in q for q in queries), queries


def test_relevance_matches_core_substring_not_exact_phrase():
    """2026-10-19 回归：query「半导体存储芯片 品牌 厂商 龙头企业」必须能匹配「存储芯片…」。

    旧口径要求实义词**完整短语**出现，而博查返回的标题写的是「存储芯片」
    （不带「半导体」前缀）、「品牌/厂商」也不出现（行业习惯写「龙头/榜单/企业」）——
    实测 10 条**全部相关**的结果被 `not_relevant` 100% 丢弃，补漏通道恒定 0 条。
    """
    from chart_generator.websearch import _relevance_hits, _relevance_tokens

    specific, generic = _relevance_tokens("半导体存储芯片 品牌 厂商 龙头企业")
    assert specific == ["半导体存储芯片"], f"品牌/厂商/龙头企业 应归入通用词，实际：{specific}"
    assert set(generic) == {"品牌", "厂商", "龙头企业"}

    # 正例：核心词的 ≥3 字子串命中即可
    assert _relevance_hits("存储芯片产业链龙头公司梳理", specific)
    assert _relevance_hits("第 82 篇:存储芯片 TOP10 榜单", specific)
    assert _relevance_hits("半导体龙头公司业绩亮点速揽", specific)

    # 反例：只有泛词、无核心词的标题不能通过
    assert not _relevance_hits("白酒品牌排行榜", specific)
    assert not _relevance_hits("今日天气晴朗", specific)


def test_generic_query_terms_include_brand_and_vendor():
    """品牌/厂商 属于泛词——否则「白酒品牌榜」会通过「半导体存储芯片」的检索。"""
    from chart_generator.websearch import _GENERIC_QUERY_TERMS

    for w in ("品牌", "厂商", "龙头企业", "代表企业", "上市公司"):
        assert w in _GENERIC_QUERY_TERMS, f"{w} 应属于通用词"


def test_search_diagnostics_capture_discarded_samples():
    """S0（2026-10-20）：检索诊断必须带出「原始条数 / 可用条数 / 丢弃明细 / 样本」。

    这是排查「博查明明能查到却返回无数据」的唯一手段——旧实现只记计数，
    看不到被丢了什么，只能靠猜（家用电器 0 条查了很久才发现是 query 跑偏）。
    """
    from chart_generator.websearch import SearchDiagnostics

    d = SearchDiagnostics(
        query="家用电器 整机 代表企业",
        raw_count=10,
        kept=0,
        discarded={"domain_not_allowed": 7, "not_relevant": 3},
        samples=[
            {"title": "洗衣机高级搜索-ZOL中关村在线", "domain": "detail.zol.com.cn",
             "reason": "domain_not_allowed"},
            {"title": "电动机企业大全", "domain": "www.in-en.com", "reason": "not_relevant"},
        ],
        allowlist_size=123,
    )
    summary = d.summary()
    assert "原始 10" in summary and "可用 0" in summary
    assert "domain_not_allowed" in summary

    out = d.to_dict()
    assert out["raw_count"] == 10 and out["kept"] == 0
    assert out["discarded"]["domain_not_allowed"] == 7
    assert out["samples"][0]["reason"] == "domain_not_allowed"
    assert out["samples"][0]["domain"] == "detail.zol.com.cn"
