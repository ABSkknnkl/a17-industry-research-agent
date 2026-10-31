"""产业链拓扑设计链路测试（2026-10-07）：LLM 出拓扑 + 代码裁判 + 回灌重写 + spec 落地。

用桩 LLM 驱动 design_topology 的完整状态机，不消耗真实 token。
"""
import asyncio
import json

from chart_generator.chain_graph import ChainGraphSpec
from chart_generator.chain_topology import (
    design_topology,
    extract_json,
    topology_to_spec,
    validate_topology,
)

EVIDENCE = [
    "[R1] (industry_chain) 某上游材料 主营构成:碳纤维 铝合金",
    "[R2] (industry_chain) 某整机厂 产业链环节:整机设计",
    "[R3] (industry_chain) 某运营平台 产业链环节:低空运营",
]

GOOD_TOPO = {
    "title": "低空经济产业链全景图",
    "subtitle": "价值传导：材料 → 整机 → 运营",
    "core_product": "低空飞行器",
    "nodes": [
        {"id": "U1", "label": "上游材料", "companies": ["某上游材料"], "key_products": ["碳纤维"],
         "description": "提供结构材料", "stage": "upstream", "is_core": False, "evidence_ids": ["R1"]},
        {"id": "M1", "label": "整机设计研发", "companies": ["某整机厂"], "key_products": ["总体设计"],
         "description": "完成总体设计与技术方案", "stage": "midstream", "is_core": True, "evidence_ids": ["R2"]},
        {"id": "M2", "label": "整机制造集成", "companies": ["某制造基地"], "key_products": ["无人机整机"],
         "description": "承接设计并完成制造集成", "stage": "midstream", "is_core": False, "evidence_ids": ["R2"]},
        {"id": "D1", "label": "低空运营", "companies": ["某运营平台"], "key_products": ["物流配送"],
         "description": "提供运营服务", "stage": "downstream", "is_core": False, "evidence_ids": ["R3"]},
        {"id": "S1", "label": "维修回收", "companies": [], "key_products": ["机体维修"],
         "description": "形成闭环成本控制", "stage": "support", "is_core": False, "evidence_ids": []},
    ],
    "edges": [
        {"source": "U1", "target": "M2", "label": "材料供应", "flow": "material"},
        {"source": "M1", "target": "M2", "label": "技术方案下达", "flow": "technical"},
        {"source": "M2", "target": "D1", "label": "整机交付", "flow": "material"},
        {"source": "S1", "target": "U1", "label": "材料回收", "flow": "recycle"},
    ],
}


def _errors(topo: dict) -> list[str]:
    return validate_topology(
        topo,
        allowed_companies={"某上游材料", "某整机厂", "某制造基地", "某运营平台"},
        allowed_evidence={"R1", "R2", "R3"},
    )


# ── 裁判规则 ────────────────────────────────────────────────────────────────

def test_good_topology_passes():
    assert _errors(GOOD_TOPO) == []


def test_material_edge_cannot_target_core_design():
    t = json.loads(json.dumps(GOOD_TOPO))
    t["edges"][0]["target"] = "M1"  # 改为指向 is_core 的设计研发节点
    t["nodes"][1]["is_core"] = True
    errs = _errors(t)
    assert any("实物流" in e for e in errs)


def test_recycle_target_must_be_support_or_upstream():
    t = json.loads(json.dumps(GOOD_TOPO))
    t["edges"].append({"source": "S1", "target": "D1", "label": "错误回流", "flow": "recycle"})
    errs = _errors(t)
    assert any("逆向物流" in e for e in errs)


def test_technical_edge_source_rule():
    t = json.loads(json.dumps(GOOD_TOPO))
    t["nodes"].append({"id": "U9", "label": "某个中游加工厂", "companies": ["某整机厂"],
                       "key_products": [], "description": "", "stage": "midstream",
                       "is_core": False, "evidence_ids": ["R2"]})
    t["edges"].append({"source": "U9", "target": "D1", "label": "非法技术流", "flow": "technical"})
    errs = _errors(t)
    assert any("技术流" in e for e in errs)


def test_fabricated_company_rejected():
    t = json.loads(json.dumps(GOOD_TOPO))
    t["nodes"][0]["companies"] = ["某上游材料", "不存在科技有限公司"]
    errs = _errors(t)
    assert any("不在证据白名单" in e for e in errs)


def test_fake_evidence_id_rejected():
    t = json.loads(json.dumps(GOOD_TOPO))
    t["nodes"][0]["evidence_ids"] = ["R1", "R999"]
    assert any("不存在的证据编号" in e for e in _errors(t))


def test_missing_core_node_rejected():
    t = json.loads(json.dumps(GOOD_TOPO))
    t["nodes"][1]["is_core"] = False
    assert any("is_core" in e for e in _errors(t))


def test_degree_limit_enforced():
    t = json.loads(json.dumps(GOOD_TOPO))
    # 17 条技术流灌入核心设计节点 M1（整机/本体核心上限 16）→ 必触发超限
    for i in range(17):
        t["nodes"].append({"id": f"E{i}", "label": f"上游配套{i}", "companies": ["某上游材料"],
                           "key_products": [], "description": "", "stage": "upstream",
                           "is_core": False, "evidence_ids": ["R1"]})
        t["edges"].append({"source": f"E{i}", "target": "M1", "label": f"技术授权{i}", "flow": "technical"})
    errs = _errors(t)
    assert any("超过上限" in e for e in errs)


def test_numbers_in_text_flagged_by_prompt_only_not_code():
    """硬规则第 8 条（禁数字）是提示词约束：代码不因数字判违规，但企业/拓扑违规必拦。"""
    t = json.loads(json.dumps(GOOD_TOPO))
    t["nodes"][0]["key_products"] = ["碳纤维 30%"]
    assert _errors(t) == []   # 不误伤


# ── 回灌重写状态机 ────────────────────────────────────────────────────────────

def test_repair_loop_second_round_passes():
    bad = json.loads(json.dumps(GOOD_TOPO))
    bad["nodes"][0]["companies"] = ["编造公司"]          # 第 1 轮违规
    responses = [json.dumps(bad, ensure_ascii=False), json.dumps(GOOD_TOPO, ensure_ascii=False)]

    async def stub(system: str, user: str) -> str:
        return responses.pop(0)

    spec, diag = asyncio.run(design_topology(
        subject="低空经济", evidence_lines=EVIDENCE,
        company_whitelist=["某上游材料", "某整机厂", "某制造基地", "某运营平台"],
        call_llm=stub, max_repair_rounds=2,
    ))
    assert spec is not None
    assert len(diag["rounds"]) == 2 and diag["rounds"][0]["errors"] > 0 and diag["rounds"][1]["errors"] == 0
    assert isinstance(spec, ChainGraphSpec)


def test_all_rounds_fail_returns_none():
    """裁判始终不过 → 返回 None（宁可不画，不带违规拓扑出图）。

    2026-10-16 换用例：原用例用「企业不在白名单」当不可修复违规，但该违规现已被
    repair 修复（摘除不可追溯企业、保住拓扑）。这里改用 repair 真的修不了的结构性错误
    ——边指向不存在的节点。
    """
    bad = json.loads(json.dumps(GOOD_TOPO))
    bad["edges"].append({"source": bad["nodes"][0]["id"], "target": "GHOST",
                         "label": "断链", "flow": "material"})

    async def stub(system: str, user: str) -> str:
        return json.dumps(bad, ensure_ascii=False)

    spec, diag = asyncio.run(design_topology(
        subject="低空经济", evidence_lines=EVIDENCE,
        company_whitelist=["某上游材料"], call_llm=stub, max_repair_rounds=1,
    ))
    assert spec is None, "裁判不过必须返回 None（宁可不画，不带违规拓扑出图）"
    assert diag["final_errors"]


def test_unbound_company_is_repaired_not_fatal():
    """2026-10-16：企业不在白名单从「致命」改为「可修复」——摘除企业、保住整张拓扑。"""
    bad = json.loads(json.dumps(GOOD_TOPO))
    bad["nodes"][0]["companies"] = ["某上游材料", "凭空编造的公司"]

    async def stub(system: str, user: str) -> str:
        return json.dumps(bad, ensure_ascii=False)

    spec, diag = asyncio.run(design_topology(
        subject="低空经济", evidence_lines=EVIDENCE,
        company_whitelist=["某上游材料"], call_llm=stub, max_repair_rounds=1,
    ))
    assert spec is not None, "只有一个不可追溯企业名，不该废掉整张拓扑"
    kept = [c for n in spec.nodes for c in n.companies]
    assert "凭空编造的公司" not in kept and "某上游材料" in kept, kept


def test_llm_exception_isolated():
    async def boom(system: str, user: str) -> str:
        raise RuntimeError("timeout")

    spec, diag = asyncio.run(design_topology(
        subject="低空经济", evidence_lines=EVIDENCE,
        company_whitelist=["某上游材料"], call_llm=boom, max_repair_rounds=1,
    ))
    assert spec is None
    assert diag["llm_errors"]


# ── spec 落地 ───────────────────────────────────────────────────────────────

def test_topology_to_spec_maps_all_fields():
    spec = topology_to_spec(GOOD_TOPO, fallback_title="兜底标题")
    assert spec.title == "低空经济产业链全景图"
    assert spec.subtitle.startswith("价值传导")
    assert spec.core_product == "低空飞行器"
    assert [s.stage_id for s in spec.stages] == ["upstream", "midstream", "downstream", "support"]
    assert len(spec.nodes) == 5 and len(spec.edges) == 4
    core = [n for n in spec.nodes if n.is_core]
    assert len(core) == 1 and core[0].name == "整机设计研发"
    # 证据为空 → 旧口径 inferred=True；2026-10-17 修1 改为「证据/企业/细分品类三项全空」
    # 才算推断。「维修回收」有细分品类「机体维修」，属标准必选环节 → 不再标推断。
    inferred = [n for n in spec.nodes if n.inferred]
    assert inferred == [], inferred
    # 但 source_tier 仍如实记录"无问财证据"
    assert next(n for n in spec.nodes if n.name == "维修回收").source_tier == "industry_common"
    # 2026-10-21：template_hint 已随旧版式删除，改为校验口径字段（渲染层只读这三个）
    assert spec.scope_kind in ("entity", "industry")
    assert spec.core_min_brands >= 1


def test_inferred_requires_all_three_empty():
    """三项全空才标推断；有任一项（证据/企业/细分品类）即不算（2026-10-17 修1）。

    实测背景：起降装置/感知传感器是无人机/eVTOL 的**标准确定部件**（起落架/刹车系统、
    激光雷达/视觉模组），只因 evidence_ids 为空就被画成虚线+红色「推断」，
    等于在正式图上告诉读者"这条我没查准"。
    """
    base = {"id": "X", "label": "某环节", "stage": "upstream",
            "companies": [], "key_products": [], "description": "", "evidence_ids": []}
    spec = topology_to_spec({"nodes": [base], "edges": []})
    assert spec.nodes[0].inferred is True

    for field, value in (("companies", ["某公司"]), ("key_products", ["某品类"]),
                         ("evidence_ids", ["R1"])):
        node = dict(base)
        node[field] = value
        out = topology_to_spec({"nodes": [node], "edges": []}).nodes[0]
        assert out.inferred is False, f"{field} 有值时不应判推断"
        assert out.source_tier == ("evidence" if field == "evidence_ids" else "industry_common")


def test_topology_to_spec_ids_remapped_and_edges_follow():
    spec = topology_to_spec(GOOD_TOPO)
    names = {n.name: n.node_id for n in spec.nodes}
    by_id = {n.node_id: n for n in spec.nodes}
    e0 = spec.edges[0]
    assert by_id[e0.source].name == "上游材料" and by_id[e0.target].name == "整机制造集成"
    assert e0.flow == "material" and e0.label == "材料供应"


def test_extract_json_strips_fence():
    text = "```json\n" + json.dumps(GOOD_TOPO, ensure_ascii=False) + "\n```"
    assert extract_json(text)["title"] == GOOD_TOPO["title"]
