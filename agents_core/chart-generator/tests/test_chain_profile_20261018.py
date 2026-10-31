"""产业链行业画像 + F1/F2 修复回归（2026-10-18）。

六主题横向评审暴露的三类内容错误，对应修复：
  · F1 repair 不再删企业名（白名单未命中 → 降级行业通识，照画）；
  · F2 品牌卡归属由「本体词」主导，不再由「企业数最多」决定；
  · F3/F4 提示词按行业注入画像（中游卡名/认证词/上下游清单/禁用词/龙头基准）。
"""

from __future__ import annotations

from chart_generator.chain_profile import (
    brand_card_rule,
    detect_profile,
    forbidden_words,
    industry_profile_block,
    leading_companies,
)
from chart_generator.chain_topology import (
    _has_body_hint,
    build_topology_prompt,
    core_misplacement,
    repair_topology,
)

# ── F3：行业画像 ──────────────────────────────────────────────────────────

def test_pharma_profile_forbids_hardware_words():
    """医药类：禁用整机/系统集成/适航，认证词用 NMPA/GMP。"""
    p = detect_profile("创新药（生物药）")
    assert p["key"] == "pharma"
    for bad in ("整机", "系统集成", "适航", "零部件"):
        assert bad in p["forbid"], f"医药类应禁用「{bad}」"
    assert "NMPA" in p["cert"] and "GMP" in p["cert"]
    assert any("临床" in (c[0] if isinstance(c, (list, tuple)) else c)
               for c in p["mid_cards"]), p["mid_cards"]


def test_robot_profile_uses_cr_not_airworthiness():
    """机器人类：CR/CE 认证，禁用适航与飞控算法。"""
    p = detect_profile("工业机器人（六轴机械臂）")
    assert p["key"] == "robot"
    assert "CR" in p["cert"]
    assert "适航" in p["forbid"] and "飞控算法" in p["forbid"]


def test_power_equipment_cert_is_type_approval():
    """发电装备类：型式认证/并网检测，不是适航。"""
    p = detect_profile("海上风电")
    assert p["key"] == "power_equipment"
    assert "型式认证" in p["cert"]
    assert "适航" in forbidden_words("海上风电")


def test_consumer_drone_downstream_is_toc_only():
    """消费级：下游不得写巡检/vertiport 这类 toG 基础设施。"""
    p = detect_profile("消费无人机")
    assert p["key"] == "aircraft"
    for bad in ("巡检", "vertiport", "通导监", "空管"):
        assert bad in p["forbid"], f"消费级应禁用「{bad}」"


def test_aircraft_profile_still_keeps_airworthiness():
    """飞行器类保留适航（不能被画像改革误伤）。"""
    p = detect_profile("低空经济")
    assert "适航" in p["cert"]
    assert "适航" not in p["forbid"]


def test_leading_benchmark_is_industry_first_tier():
    """龙头基准表 = 品牌卡回归断言的数据源。"""
    assert "金风科技" in leading_companies("海上风电")
    assert "中微公司" in leading_companies("半导体设备")
    assert "埃斯顿" in leading_companies("工业机器人")
    assert "恒瑞医药" in leading_companies("创新药")
    assert "大疆" in leading_companies("消费无人机")


def test_topology_prompt_injects_profile_and_brand_rule():
    """A3 提示词必须带上本行业画像与品牌卡规则，且不得残留其它行业的举例。"""
    sys_prompt, _ = build_topology_prompt("创新药（生物药）", [], None)
    assert "恒瑞医药" in sys_prompt, "品牌卡规则/龙头基准未注入"
    assert "NMPA" in sys_prompt
    assert "飞控算法与软件 / 整机制造与总装 / 系统集成与调试" not in sys_prompt, \
        "仍残留飞行器中游卡名举例"


# ── F1：不可追溯企业名不再被删除 ───────────────────────────────────────────

def test_repair_downgrades_instead_of_deleting_companies():
    """F1：白名单未命中 → 降级 industry_common，**一个名字都不许删**。

    旧行为（海上风电实测）：整机节点 8 家正确龙头被摘成 0 家，
    品牌卡随后漂到「海工装备与安装」。
    """
    top = {"nodes": [
        {"id": "M1", "label": "整机制造与总装", "stage": "midstream", "is_core": True,
         "companies": ["金风科技", "明阳智能", "远景能源", "运达股份"],
         "evidence_ids": []},        # 环节无证据编号 → 旧逻辑直接摘除
    ], "edges": []}
    fixed, notes = repair_topology(top, allowed_companies={"许继电气"})
    node = fixed["nodes"][0]
    assert node["companies"] == ["金风科技", "明阳智能", "远景能源", "运达股份"], \
        f"企业名被删了：{node['companies']}"
    assert node.get("source_tier") == "industry_common"
    assert any("降级" in n for n in notes), notes


def test_repair_still_removes_obvious_placeholder_names():
    """F1 分级：明显占位/编造名仍要摘除（不能借"不删名"之名放过硬伤）。"""
    top = {"nodes": [
        {"id": "M1", "label": "整机制造与总装", "stage": "midstream", "is_core": True,
         "companies": ["金风科技", "某整机厂", "凭空编造的公司"], "evidence_ids": []},
    ], "edges": []}
    fixed, notes = repair_topology(top, allowed_companies={"白名单里的其它公司"})
    assert fixed["nodes"][0]["companies"] == ["金风科技"], fixed["nodes"][0]["companies"]
    assert fixed["nodes"][0]["source_tier"] == "industry_common"
    assert any("摘除" in n for n in notes), notes


# ── F5：龙头上移品牌卡（确定性兜底）───────────────────────────────────────

from chart_generator.chain_topology import hoist_leading_to_brand_card  # noqa: E402


def test_leading_companies_hoisted_to_brand_card():
    """F5：龙头被拆到同 stage 小卡时，确定性搬回品牌卡。

    海上风电实测：金风/明阳/电气风电被写进「机组设计与仿真」，
    品牌卡「整机制造与总装」只剩运达/三一，命中率 2/7。
    """
    top = {"nodes": [
        {"id": "M1", "label": "机组设计与仿真", "stage": "midstream",
         "companies": ["金风科技", "明阳智能", "电气风电"]},
        {"id": "M2", "label": "整机制造与总装", "stage": "midstream", "is_core": True,
         "companies": ["运达股份", "三一重能"]},
    ], "edges": []}
    fixed, notes = hoist_leading_to_brand_card(top, "海上风电")
    core = next(n for n in fixed["nodes"] if n.get("is_core"))
    other = next(n for n in fixed["nodes"] if not n.get("is_core"))
    assert set(core["companies"]) >= {"金风科技", "明阳智能", "电气风电", "运达股份"}, core["companies"]
    assert "金风科技" not in other["companies"], "搬走的不该留在小卡"
    assert notes, "上移必须留痕"


def test_hoist_is_noop_when_brand_card_already_strong():
    """F5：品牌卡已达标（≥60%）时不折腾。"""
    top = {"nodes": [
        {"id": "M1", "label": "整机制造与总装", "stage": "midstream", "is_core": True,
         "companies": ["金风科技", "明阳智能", "运达股份", "三一重能", "东方电缆"]},
        {"id": "M2", "label": "机组设计与仿真", "stage": "midstream",
         "companies": ["某仿真公司"]},
    ], "edges": []}
    fixed, notes = hoist_leading_to_brand_card(top, "海上风电")
    assert notes == [], "已达标时不应改动"
    assert fixed is top, "已达标时应原样返回（无拷贝）"


def test_hoist_never_lifts_from_upstream():
    """F5：**上游**龙头不得跨层上移（同集团上游业务真实存在：比亚迪既造车也供电池）。

    注意本用例的 `东方电缆` 属 `leading_upstream`，本就不在 `leading_brand` 基准里，
    所以即使放宽也不会被搬——它的价值是**锁住 upstream 层的 companies 不被改写**。
    """
    top = {"nodes": [
        {"id": "U1", "label": "海缆", "stage": "upstream",
         "companies": ["东方电缆", "中天科技"]},      # 基准里的上游龙头
        {"id": "M1", "label": "整机制造与总装", "stage": "midstream", "is_core": True,
         "companies": ["运达股份"]},
    ], "edges": []}
    fixed, notes = hoist_leading_to_brand_card(top, "海上风电")
    core = next(n for n in fixed["nodes"] if n.get("is_core"))
    up = next(n for n in fixed["nodes"] if n.get("stage") == "upstream")
    assert "东方电缆" not in core["companies"], "上游龙头不得跨 stage 上移到中游品牌卡"
    assert up["companies"] == ["东方电缆", "中天科技"], "上游节点不得被改动"


def test_hoist_lifts_from_support_and_downstream():
    """F5（2026-10-25 放宽）：基准龙头被放进配套层/下游卡时要能搬回品牌卡。

    实测 run-20261025220602 白酒：品牌卡「品牌与产品运营」在 midstream，
    6 家基准龙头全被 LLM 塞进 support 层的「品牌营销与数字直销」→ 品牌卡只剩剑南春。
    当时 hoist 只搬同 stage，而 `strengthen_brand_card` 又认为"已在别处的交由 hoist 搬运"
    → 两头落空，龙头永远进不了品牌卡。
    """
    top = {"nodes": [
        {"id": "M1", "label": "品牌与产品运营", "stage": "midstream", "is_core": True,
         "companies": ["剑南春"]},
        {"id": "S1", "label": "品牌营销与数字直销", "stage": "support",
         "companies": ["贵州茅台", "五粮液", "山西汾酒"]},
        {"id": "D1", "label": "经销商与批发代理", "stage": "downstream",
         "companies": ["泸州老窖", "某经销商"]},
    ], "edges": []}
    fixed, notes = hoist_leading_to_brand_card(top, "白酒产业链")
    core = next(n for n in fixed["nodes"] if n.get("is_core"))
    sup = next(n for n in fixed["nodes"] if n.get("stage") == "support")
    down = next(n for n in fixed["nodes"] if n.get("stage") == "downstream")
    assert set(core["companies"]) >= {"剑南春", "贵州茅台", "五粮液", "山西汾酒", "泸州老窖"}, \
        core["companies"]
    assert sup["companies"] == [], "营销卡该放营销服务商，酒企应全部搬走"
    assert down["companies"] == ["某经销商"], "只搬基准龙头，非基准的渠道商留在原卡"
    assert notes, "上移必须留痕"


def test_hoist_skips_topics_without_benchmark():
    """F5：没有龙头基准表的主题原样返回。"""
    top = {"nodes": [{"id": "M1", "label": "整机制造与总装", "stage": "midstream",
                      "is_core": True, "companies": ["甲公司"]}], "edges": []}
    fixed, notes = hoist_leading_to_brand_card(top, "某无基准行业")
    assert fixed is top and notes == []


# ── F6：企业唯一化不得把龙头从品牌卡挤走 ──────────────────────────────────

from chart_generator.chain_topology import repair_topology, validate_topology  # noqa: E402


def test_duplicate_leader_stays_on_brand_card():
    """F6：龙头在品牌卡与小卡重复时，必须保留在品牌卡。

    半导体设备实测：A2 写对（品牌卡＝中微/北方华创/拓荆/屹唐/微导/盛美/华海清科 7/7），
    但这些名字在 3-5 个节点重复，旧唯一化规则按"企业数更少"把它们全搬去
    「设备维保与改造」等小卡 → 品牌卡只剩微导纳米，命中率 7/7 → 1/7。
    """
    top = {
        "title": "半导体设备（刻蚀/沉积）产业链图谱", "core_product": "刻蚀/沉积设备",
        "nodes": [
            {"id": "U1", "label": "射频与电源", "stage": "upstream",
             "companies": ["北方华创", "英杰电气"], "evidence_ids": []},
            {"id": "M1", "label": "设备研发", "stage": "midstream",
             "companies": ["中微公司", "拓荆科技"], "evidence_ids": []},
            {"id": "S1", "label": "设备维保与改造", "stage": "support",
             "companies": ["北方华创", "盛美上海"], "evidence_ids": []},
            {"id": "M2", "label": "整机设备制造", "stage": "midstream", "is_core": True,
             "companies": ["中微公司", "北方华创", "拓荆科技", "屹唐股份",
                           "微导纳米", "盛美上海", "华海清科"], "evidence_ids": []},
        ], "edges": [],
    }
    fixed, notes = repair_topology(top, allowed_companies={"北方华创"})
    core = next(n for n in fixed["nodes"] if n.get("is_core"))
    # 🔴 2026-10-19 F14：标题限定「刻蚀/沉积」→ 品牌卡基准表收窄到该细分，
    # 清洗设备商（盛美上海）与 CMP 设备商（华海清科）**不再享受**"龙头优先留品牌卡"待遇。
    for leader in ("中微公司", "北方华创", "拓荆科技", "屹唐股份", "微导纳米"):
        assert leader in core["companies"], f"细分龙头「{leader}」被挤出了品牌卡：{core['companies']}"
    others = [n for n in fixed["nodes"] if not n.get("is_core")]
    for n in others:
        for leader in ("中微公司", "北方华创", "拓荆科技", "屹唐股份", "微导纳米"):
            assert leader not in (n.get("companies") or []), \
                f"细分龙头「{leader}」仍留在小卡「{n.get('label')}」"


def test_unscoped_semiconductor_keeps_all_seven_leaders():
    """F14 反向守卫：标题**没**限定细分时，7 家设备龙头仍全部留在品牌卡。

    防止"细分收窄"误伤泛主题——上一版 7/7 全中的行为必须在泛主题下保持。
    """
    top = {
        "title": "半导体设备产业链图谱", "core_product": "半导体设备",
        "nodes": [
            {"id": "S1", "label": "设备维保与改造", "stage": "support",
             "companies": ["北方华创", "盛美上海"], "evidence_ids": []},
            {"id": "M1", "label": "设备研发", "stage": "midstream",
             "companies": ["中微公司", "拓荆科技"], "evidence_ids": []},
            {"id": "M2", "label": "整机设备制造", "stage": "midstream", "is_core": True,
             "companies": ["中微公司", "北方华创", "拓荆科技", "屹唐股份",
                           "微导纳米", "盛美上海", "华海清科"], "evidence_ids": []},
        ], "edges": [],
    }
    fixed, _ = repair_topology(top, allowed_companies={"北方华创"})
    core = next(n for n in fixed["nodes"] if n.get("is_core"))
    for leader in ("中微公司", "北方华创", "拓荆科技", "屹唐股份",
                   "微导纳米", "盛美上海", "华海清科"):
        assert leader in core["companies"], f"泛主题下龙头「{leader}」不该被移出：{core['companies']}"


def test_non_leader_dup_still_follows_stage_rank():
    """F6 只保护龙头：非龙头公司重复时仍按 support > midstream 的专精规则。"""
    top = {
        "title": "低空经济产业链图谱", "core_product": "低空飞行器",
        "nodes": [
            {"id": "S1", "label": "通导监", "stage": "support",
             "companies": ["华测导航"], "evidence_ids": []},
            {"id": "M1", "label": "整机制造与总装", "stage": "midstream", "is_core": True,
             "companies": ["华测导航", "亿航智能"], "evidence_ids": []},
        ], "edges": [],
    }
    fixed, notes = repair_topology(top, allowed_companies={"华测导航"})
    support = next(n for n in fixed["nodes"] if n.get("stage") == "support")
    core = next(n for n in fixed["nodes"] if n.get("is_core"))
    assert "华测导航" in support["companies"], "非龙头仍应留在配套专精节点"
    assert "华测导航" not in core["companies"]


# ── F7：证据补企业不得重新制造跨节点重复 ──────────────────────────────────

def test_evidence_fill_does_not_reintroduce_duplicates():
    """F7：规则 5 补企业必须看全局占用表，否则刚唯一化完又被补出重复。

    半导体设备实测（run-20261019003007-677f0e）：「功率半导体」「第三代半导体」
    两个下游节点都被补上「半导体」（白名单 entity 是节点 label 的子串），
    唯一化清完后重复被重新制造 → validate 仍报 1 项 → 整张拓扑被弃 → 空壳图。
    """
    top = {
        "title": "半导体设备产业链图谱", "core_product": "刻蚀设备",
        "nodes": [
            {"id": "D1", "label": "功率半导体", "stage": "downstream",
             "companies": [], "evidence_ids": ["R1"], "phase": "已落地", "buyer": "晶圆厂"},
            {"id": "D2", "label": "第三代半导体", "stage": "downstream",
             "companies": [], "evidence_ids": ["R2"], "phase": "已落地", "buyer": "晶圆厂"},
            {"id": "M1", "label": "整机制造", "stage": "midstream", "is_core": True,
             "companies": ["中微公司", "北方华创"], "evidence_ids": []},
        ], "edges": [{"source": "M1", "target": "D1", "label": "供货", "flow": "material"}],
    }
    fixed, notes = repair_topology(top, allowed_companies={"半导体", "中微公司", "北方华创"})
    filled = [n for n in fixed["nodes"] if n.get("companies")]
    assert len(filled) <= 2, f"补企业补出多个节点同企业：{[n['label'] for n in filled]}"
    errs = validate_topology(fixed, allowed_companies={"半导体", "中微公司", "北方华创"})
    assert [e for e in errs if "重复" in e] == [], f"补企业后不得存在企业重复：{errs}"
    assert any("补企业" in x for x in notes), notes


# ── F2：品牌卡归属由本体词主导 ─────────────────────────────────────────────

def test_core_stays_on_body_node_even_if_others_have_more_companies():
    """F2：企业数更多的杂牌节点不能抢走品牌卡。

    实测原型：海上风电 core 漂到「海工装备与安装」(3家)，
    而真正的「整机制造与总装」只有 2 家但名字命中本体词。
    """
    assert _has_body_hint({"label": "整机制造与总装"})
    assert not _has_body_hint({"label": "海工装备与安装"})
    top = {"core_product": "海上风电机组", "nodes": [
        {"id": "M1", "label": "整机制造与总装", "stage": "midstream", "is_core": True,
         "companies": ["金风科技", "明阳智能"]},                  # 2 家 < 下限 3
        {"id": "M2", "label": "海工装备与安装", "stage": "midstream",
         "companies": ["振华重工", "润邦股份", "华电科工"]},      # 3 家但非本体
        {"id": "M3", "label": "总装调试", "stage": "midstream",
         "companies": ["徐工机械", "中联重科", "柳工", "三一重工"]},  # 4 家
    ], "edges": []}
    move = core_misplacement(top)
    assert move is not None, "应判定 core 挂错（2 家 < 本体盒下限）"
    _cur, want = move
    assert want == "M3", f"应把 core 给名字像本体的「总装调试」，实际给了 {want}"


# ── 白酒画像（2026-10-25 补）：此前落 generic，F5 无基准可搬 ──────────────────

def test_liquor_profile_registered_and_used():
    """白酒必须有专属画像：没有它 `leading_brand` 为空，F5 就搬不动龙头。

    实测 run-20261025220602：「品牌与产品运营」只剩剑南春 1 家，
    茅台/五粮液/汾酒/老窖/洋河/古井 6 家全被塞进 support 层的「品牌营销与数字直销」。
    """
    from chart_generator import chain_profile as cp

    prof = cp.detect_profile("白酒产业链")
    assert prof.get("key") == "liquor", f"白酒应命中 liquor 画像，实际 {prof.get('key')}"
    brands = cp.leading_companies("白酒产业链")
    assert len(brands) >= 6, brands
    for must in ("贵州茅台", "五粮液", "洋河股份", "山西汾酒", "泸州老窖", "古井贡酒"):
        assert must in brands, f"{must} 应是白酒品牌龙头：{brands}"


def test_liquor_profile_exists_in_builtin_fallback():
    """外置 JSON 目录缺失时会回退内置表——白酒必须两边都有，否则功能静默退化。"""
    from chart_generator import chain_profile as cp

    builtin_keys = [p.get("key") for p in cp._BUILTIN_PROFILES]
    assert "liquor" in builtin_keys, f"内置画像表缺 liquor：{builtin_keys}"
    # 顺序约束：外置 order 与内置表必须同序（detect_profile 是首个命中优先）
    data_keys = [p.get("key") for p in cp._PROFILES]
    assert data_keys[:len(builtin_keys)] == builtin_keys or set(builtin_keys) <= set(data_keys), \
        f"内置与外置画像 key 集合不一致：{builtin_keys} vs {data_keys}"


def test_liquor_profile_does_not_steal_other_industries():
    """阴性对照：白酒画像不得抢走黄酒/啤酒/笔记本/风电。"""
    from chart_generator import chain_profile as cp

    assert cp.detect_profile("黄酒产业链").get("key") == "generic"
    assert cp.detect_profile("啤酒产业链").get("key") == "generic"
    assert cp.detect_profile("笔记本电脑产业链").get("key") == "generic"
    assert cp.detect_profile("海上风电产业链").get("key") == "power_equipment"
