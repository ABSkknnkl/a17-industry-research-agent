"""第三轮复查修复回归：F8~F14（2026-10-19）。

六图复查暴露的 5 类问题里，**3 类是上一轮 F4/F5/F6 自己引入的回归**：
  · F8  龙头基准表把上游公司列为"品牌卡必填" → 拆成 leading_brand / leading_upstream；
  · F9  提示词写死"品牌卡必须给 5-8 个" → 改为 2-8 + 整机厂判定问句；
  · F13 消费级无人机用通用航空基准表 → 新增 drone_consumer 细分画像；
  · F10 能力卡只有细分没有公司 → 认证机构表 + 角色锚点精确兜底；
  · F11 渲染器补「其他场景」虚格 → 删除；
  · F12 缺"这家公司是不是干这个环节"的校验 → wrong_fit 语义禁配表；
  · F14 标题细分与品牌卡范围不一致 → scope 收窄 + 告警。

每个用例都绑定一条**实测证据**，避免再次退化成"凭感觉改参数"。
"""
from __future__ import annotations

from pathlib import Path

from chart_generator.chain_profile import (
    capability_pool,
    cert_bodies,
    detect_profile,
    forbidden_words,
    industry_profile_block,
    leading_companies,
    mid_card_pool,
    upstream_anchor,
    upstream_leaders,
    wrong_fit_map,
)
from chart_generator.chain_topology import (  # noqa: E402
    BRAND_MIN_COMPANIES,
    apply_wrong_fit,
    core_misplacement,
    fill_empty_capability_cards,
    rehome_brand_card_outliers,
    repair_topology,
    strengthen_brand_card,
    topology_system,
    validate_topology,
)
from chart_generator.chain_render import render_chain_svg  # noqa: E402
from chart_generator.chain_lint import sanitize_text_no_numbers  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
A2_PROMPT = ROOT / "agents_core" / "data-analysis" / "data_interpreter" / "agent.py"


# ── F8：龙头基准表按角色拆分 ───────────────────────────────────────────────

def test_leading_brand_excludes_upstream_suppliers():
    """F8 核心：品牌卡基准表里**绝不能**出现零部件/材料供应商。

    上一版实测：海上风电 leading 含东方电缆/中天科技（海缆）、
    工业机器人含绿的谐波/双环传动（减速器）→ 模型照单全收写进 ★品牌卡。
    """
    for bad in ("东方电缆", "中天科技", "亨通光电", "日月股份"):
        assert bad not in leading_companies("海上风电"), f"海缆/铸锻件商「{bad}」不该在品牌卡基准表"
        assert bad in upstream_leaders("海上风电"), f"「{bad}」应归到上游龙头表"
    for bad in ("绿的谐波", "双环传动", "中大力德"):
        assert bad not in leading_companies("工业机器人")
        assert bad in upstream_leaders("工业机器人")
    for good in ("金风科技", "明阳智能", "运达股份", "三一重能"):
        assert good in leading_companies("海上风电"), f"整机厂「{good}」必须在品牌卡基准表"
    for good in ("埃斯顿", "汇川技术", "新松"):
        assert good in leading_companies("工业机器人")


def test_profile_block_separates_two_rosters():
    """F8 配套：提示词必须**分两行、分角色**列出，否则模型照旧混填。"""
    block = industry_profile_block("海上风电")
    assert "✅ **品牌卡**" in block and "⛔ **上游零部件/材料**" in block
    assert "绝不允许出现在品牌卡" in block
    # 旧版是一行"品牌卡必须填本行业第一梯队：…（含东方电缆）"——必须消失
    assert "必须填本行业第一梯队：金风科技、明阳智能、电气风电、运达股份、三一重能、东方电缆" \
        not in block


def test_upstream_leader_on_brand_card_is_rehomed_not_deleted():
    """F8：品牌卡上的上游角色公司**归位**到对应上游卡，不是删掉。

    实测：海上风电 ★品牌卡 = 金风/明阳/电气风电/运达/三一 + 东方电缆/中天科技；
    删掉会让本来就只剩亨通光电的海缆卡更空，归位才同时修好两边。
    """
    top = {"title": "海上风电产业链图谱", "core_product": "海上风电机组", "nodes": [
        {"id": "U1", "label": "海缆/电缆", "stage": "upstream",
         "companies": ["亨通光电"], "evidence_ids": []},
        {"id": "M1", "label": "整机制造与总装", "stage": "midstream", "is_core": True,
         "companies": ["金风科技", "明阳智能", "运达股份", "东方电缆", "中天科技"],
         "evidence_ids": []},
    ], "edges": []}
    fixed, notes = rehome_brand_card_outliers(top, "海上风电")
    core = next(n for n in fixed["nodes"] if n.get("is_core"))
    up = next(n for n in fixed["nodes"] if n.get("stage") == "upstream")
    assert core["companies"] == ["金风科技", "明阳智能", "运达股份"], core["companies"]
    assert "东方电缆" in up["companies"] and "中天科技" in up["companies"], up["companies"]
    assert any("归位" in x for x in notes), notes


def test_brand_card_violations_detector_is_clean_after_repair():
    """F8 验收口径：修复后品牌卡不得再出现上游角色公司（六图 6 家越界 → 0）。"""
    top = {"title": "工业机器人产业链图谱", "core_product": "工业机器人本体", "nodes": [
        {"id": "U1", "label": "谐波减速器", "stage": "upstream",
         "companies": [], "evidence_ids": []},
        {"id": "M1", "label": "本体制造与总装", "stage": "midstream", "is_core": True,
         "companies": ["埃斯顿", "汇川技术", "绿的谐波", "双环传动"], "evidence_ids": []},
    ], "edges": []}
    fixed, _ = repair_topology(top, allowed_companies=set())
    core = next(n for n in fixed["nodes"] if n.get("is_core"))
    ups = set(upstream_leaders("工业机器人"))
    assert [c for c in core["companies"] if c in ups] == [], \
        f"品牌卡仍有上游角色公司：{core['companies']}"


# ── F9：品牌卡数量弹性（两处提示词副本同源）──────────────────────────────

def test_prompt_no_longer_demands_five_to_eight():
    """F9：A3 提示词不再写死"必须给 5-8 个"，改为 2-8 + 整机厂判定问句。"""
    sys_prompt = topology_system("海上风电")
    assert "必须给 5-8 个真实企业" not in sys_prompt
    assert "2-8" in sys_prompt
    assert "采购零部件、集成后以自有品牌卖整机/终端" in sys_prompt


def test_a2_prompt_copy_is_in_sync():
    """F9 同源约束：A2 侧提示词副本必须同步（两份提示词都会驱动生成）。"""
    src = A2_PROMPT.read_text(encoding="utf-8")
    assert "必须给 5-8 个真实企业" not in src, "A2 提示词仍写死 5-8 家（双通道强化会继续驱动凑数）"
    assert "2-8 家" in src


def test_brand_card_rule_states_membership_question():
    """F9：品牌卡规则要给出**可执行的判定问句**，不能只说"别抓上游"。"""
    sys_prompt = topology_system("海上风电")
    assert "成员资格判定问句" in sys_prompt
    assert "东方电缆（海缆）" in sys_prompt, "判定问句必须带本行业的反面案例"


# ── F10：能力卡必填 + 认证机构兜底 ─────────────────────────────────────────

def test_cert_node_filled_with_real_certification_bodies():
    """F10：认证/检测类卡 companies 为空 → 填本行业真实认证机构。

    实测：海上风电「型式认证与并网检测」、机器人「CR/CE 认证与可靠性测试」都是空卡。
    """
    top = {"title": "海上风电产业链图谱", "core_product": "海上风电机组", "nodes": [
        {"id": "M1", "label": "型式认证与并网检测", "stage": "midstream",
         "companies": [], "evidence_ids": []},
    ], "edges": []}
    fixed, notes = fill_empty_capability_cards(top, "海上风电")
    assert fixed["nodes"][0]["companies"], "认证类卡不该继续留空"
    assert any("认证" in c or "CGC" in c or "CCS" in c
               for c in fixed["nodes"][0]["companies"]), fixed["nodes"][0]["companies"]
    assert fixed["nodes"][0].get("source_tier") == "industry_common"
    assert any("认证机构" in x for x in notes), notes


def test_no_blind_fill_of_unrelated_upstream_leaders():
    """F10 反向守卫：**没有角色锚点命中就留空**，绝不错配。

    本次实现踩的坑：首版把上游空卡一律抓 leading_upstream，
    于是低空经济「飞控/导航」被填成 卧龙电驱/宗申动力/光威复材（电机/发动机/碳纤维）。
    """
    top = {"title": "低空经济产业链图谱", "core_product": "低空飞行器", "nodes": [
        {"id": "U1", "label": "飞控/导航", "stage": "upstream",
         "companies": [], "evidence_ids": []},
    ], "edges": []}
    fixed, notes = fill_empty_capability_cards(top, "低空经济")
    comps = fixed["nodes"][0]["companies"]
    for wrong in ("卧龙电驱", "宗申动力", "光威复材", "中简科技"):
        assert wrong not in comps, f"「飞控/导航」被错配成 {comps}"
    # 留空必须留痕，方便排查而不是静默消失
    assert any("保持留空" in x for x in notes) or comps, notes


def test_mid_card_pool_fills_canonical_capability_card():
    """F10：中游 canonical 能力卡（「运动控制与算法」这类）按卡名给专业公司。"""
    top = {"title": "工业机器人产业链图谱", "core_product": "工业机器人本体", "nodes": [
        {"id": "M1", "label": "运动控制与算法", "stage": "midstream",
         "companies": [], "evidence_ids": []},
    ], "edges": []}
    fixed, notes = fill_empty_capability_cards(top, "工业机器人")
    comps = fixed["nodes"][0]["companies"]
    assert "固高科技" in comps, f"运动控制卡应填控制器/伺服专业公司：{comps}"
    assert "金风科技" not in comps and "东方电缆" not in comps, "跨行业填错"


def test_empty_brand_card_is_filled_with_leaders_not_cap_pool():
    """F10 守卫：品牌卡为空时补**整机龙头**，不能用能力卡候选池凑。"""
    top = {"title": "创新药产业链图谱", "core_product": "创新药", "nodes": [
        {"id": "M1", "label": "GMP 生产与商业化", "stage": "midstream", "is_core": True,
         "companies": [], "evidence_ids": []},
    ], "edges": []}
    fixed, _ = fill_empty_capability_cards(top, "创新药")
    comps = fixed["nodes"][0]["companies"]
    assert "恒瑞医药" in comps, f"品牌卡应补整机/终端龙头：{comps}"
    assert "昭衍新药" not in comps, "能力卡候选池不得进入品牌卡"


def test_capability_pool_never_overlaps_brand_leaders():
    """F10 数据口径：候选池与品牌卡龙头必须互斥，否则会与品牌卡抢人。"""
    for subj in ("海上风电", "工业机器人", "创新药", "车载激光雷达", "消费无人机"):
        overlap = set(capability_pool(subj)) & set(leading_companies(subj))
        assert overlap == set(), f"{subj} 候选池与品牌卡龙头重叠：{overlap}"


# ── F11：删除「其他场景」虚格 ──────────────────────────────────────────────

def test_no_placeholder_card_in_rendered_svg():
    """F11：SVG 里不得出现「其他场景 / 新兴应用持续涌现」这类补位假卡。"""
    top = {"title": "消费无人机产业链图谱", "core_product": "消费无人机",
           "nodes": [
               {"id": "M1", "label": "整机制造与总装", "stage": "midstream", "is_core": True,
                "companies": ["大疆", "道通智能", "臻迪"], "evidence_ids": []},
           ] + [
               {"id": f"D{i}", "label": f"场景{i}", "stage": "downstream",
                "companies": [], "phase": "已落地", "buyer": "个人消费者",
                "evidence_ids": []}
               for i in range(1, 8)
           ], "edges": []}
    from chart_generator.chain_topology import topology_to_spec
    spec = topology_to_spec(top, fallback_title="消费无人机")
    svg = render_chain_svg(spec)
    assert "其他场景" not in svg, "渲染器仍在补「其他场景」虚格"
    assert "新兴应用持续涌现" not in svg


# ── F12：环节—公司语义禁配 ─────────────────────────────────────────────────

def test_wrong_fit_removes_mismatched_company():
    """F12：激光雷达「芯片代工」不该出现长鑫科技（存储 IDM，不是代工厂）。"""
    top = {"title": "车载激光雷达产业链图谱", "core_product": "车载激光雷达", "nodes": [
        {"id": "S1", "label": "芯片代工", "stage": "support",
         "companies": ["长鑫科技", "中芯国际"], "evidence_ids": []},
    ], "edges": []}
    fixed, notes = apply_wrong_fit(top, "车载激光雷达")
    assert fixed["nodes"][0]["companies"] == ["中芯国际"], fixed["nodes"][0]["companies"]
    assert any("主业不符" in x for x in notes), notes


def test_wrong_fit_is_reported_by_validator():
    """F12：裁判（validate）也要能报出来——repair 没修干净的不能悄悄过关。"""
    top = {"title": "创新药产业链图谱", "core_product": "创新药", "nodes": [
        {"id": "S1", "label": "监管与注册服务", "stage": "support",
         "companies": ["泰格医药"], "evidence_ids": []},
    ], "edges": []}
    errs = validate_topology(top)
    assert any("泰格医药" in e and "不符" in e for e in errs), f"语义错配未被裁判拦下：{errs}"


def test_wrong_fit_does_not_touch_in_scope_brand_leaders():
    """F12/F8 不得互拆：本细分的品牌卡龙头对语义禁配**免疫**。"""
    top = {"title": "海上风电产业链图谱", "core_product": "海上风电机组", "nodes": [
        {"id": "M1", "label": "整机制造与总装", "stage": "midstream", "is_core": True,
         "companies": ["金风科技", "明阳智能"], "evidence_ids": []},
    ], "edges": []}
    fixed, notes = apply_wrong_fit(top, "海上风电")
    assert fixed["nodes"][0]["companies"] == ["金风科技", "明阳智能"], notes


# ── F13：消费级无人机细分画像 ──────────────────────────────────────────────

def test_consumer_drone_brand_list_is_consumer_only():
    """F13：消费级品牌卡基准表只能有消费级整机厂。

    上一版用通用航空表（大疆/亿航智能/纵横股份/中航成飞）→
    载人 eVTOL、工业固定翼、军机全被塞进消费级品牌卡。
    """
    brand = leading_companies("消费无人机")
    assert "大疆" in brand
    for wrong in ("亿航智能", "纵横股份", "中航成飞"):
        assert wrong not in brand, f"「{wrong}」不该出现在消费级品牌卡基准表"


def test_consumer_drone_forbids_evtol_and_auto_parts():
    """F13：消费级禁用词覆盖载人/工业/军工/汽车件（问财概念股噪声实测名单）。"""
    forbid = forbidden_words("消费无人机")
    for bad in ("亿航智能", "纵横股份", "中航成飞", "中联重科", "国轩高科", "英搏尔"):
        assert bad in forbid, f"消费级应禁用「{bad}」"


def test_consumer_drone_brand_card_rejects_evtol_company():
    """F13 端到端：即便模型把亿航写进消费级品牌卡，代码也要拦下来。"""
    top = {"title": "消费无人机产业链图谱", "core_product": "消费级无人机", "nodes": [
        {"id": "M1", "label": "整机制造与总装", "stage": "midstream", "is_core": True,
         "companies": ["大疆", "亿航智能", "纵横股份"], "evidence_ids": []},
    ], "edges": []}
    fixed, notes = apply_wrong_fit(top, "消费无人机")
    comps = fixed["nodes"][0]["companies"]
    assert comps == ["大疆"], f"消费级品牌卡仍有非消费级厂商：{comps}"
    assert any("主业不符" in x for x in notes), notes


def test_consumer_drone_upstream_is_not_aerospace_generic():
    """F13：消费级上游清单换成电池/电机/CMOS/图传，不是航空通用的起落架/任务载荷。"""
    p = detect_profile("消费无人机")
    up = "、".join(p["upstream"])
    assert "起落架" not in up, "消费级上游不该是航空件"
    assert any(k in up for k in ("电池", "电机", "CMOS", "图传")), up


def test_generic_aircraft_still_keeps_its_own_brand_list():
    """F13 反向守卫：通用飞行器主题不能被消费级画像误伤。"""
    brand = leading_companies("低空经济")
    assert "亿航智能" in brand, "低空经济（载人+工业）仍应保留亿航智能"
    assert detect_profile("低空经济")["scope_key"] == ""


# ── F14：标题细分与品牌卡范围一致 ──────────────────────────────────────────

def test_scope_narrows_brand_list_for_etch_deposit():
    """F14：标题限定「刻蚀/沉积」时，清洗（盛美）与 CMP（华海清科）退出基准表。"""
    scoped = leading_companies("半导体设备（刻蚀/沉积）")
    assert "中微公司" in scoped and "北方华创" in scoped
    assert "盛美上海" not in scoped and "华海清科" not in scoped
    generic = leading_companies("半导体设备")
    assert "盛美上海" in generic and "华海清科" in generic, "泛主题不该被收窄"


def test_out_of_scope_brand_member_raises_warning():
    """F14：品牌卡出现细分之外的厂商时**告警**（不阻断，交人工核对）。"""
    top = {"title": "半导体设备（刻蚀/沉积）产业链图谱", "core_product": "刻蚀/沉积设备",
           "nodes": [
               {"id": "M1", "label": "整机设备制造", "stage": "midstream", "is_core": True,
                "companies": ["中微公司", "北方华创", "盛美上海"], "evidence_ids": []},
           ], "edges": []}
    _, notes = repair_topology(top, allowed_companies={"中微公司"})
    assert any("不属于本细分范围" in x for x in notes), f"越界未告警：{notes}"


# ── 数据表自检（防止手写表再次写错）────────────────────────────────────────

def test_no_profile_puts_same_company_in_brand_and_upstream():
    """F8 数据口径自检：任何行业都不得把同一家公司同时列为整机龙头与上游龙头。"""
    for subj in ("海上风电", "工业机器人", "半导体设备", "创新药", "消费无人机",
                 "车载激光雷达", "低空经济", "新能源汽车"):
        overlap = set(leading_companies(subj)) & set(upstream_leaders(subj))
        assert overlap == set(), f"{subj} 角色冲突：{overlap}"


def test_wrong_fit_never_bans_in_scope_brand_leaders():
    """F12 数据口径自检：禁配表**在品牌卡自己的环节名上**不得封杀本细分龙头。

    只查"像品牌卡"的键（整机/本体/总装/品牌/整车/终端）——
    「海缆: 金风科技」这类是**正确**的反向禁配（整机厂不该出现在海缆卡），不在本断言范围。
    """
    body_keys = ("整机", "本体", "总装", "组装", "品牌", "整车", "终端")
    for subj in ("海上风电", "工业机器人", "创新药", "消费无人机", "车载激光雷达"):
        brand = set(leading_companies(subj))
        for kw, banned in wrong_fit_map(subj).items():
            if not any(k in kw for k in body_keys):
                continue
            for name in banned:
                for leader in brand:
                    assert not (leader in name or name in leader), \
                        f"{subj} 禁配表「{kw}: {name}」误伤品牌卡龙头「{leader}」"


def test_upstream_anchor_covers_every_upstream_leader():
    """F8 归位完整性：每个上游龙头都要有归位锚点，否则只能"删"而不能"归位"。"""
    for subj in ("海上风电", "工业机器人", "半导体设备", "创新药",
                 "车载激光雷达", "新能源汽车", "低空经济"):
        anchors = upstream_anchor(subj)
        missing = [c for c in upstream_leaders(subj) if c not in anchors]
        assert missing == [], f"{subj} 上游龙头缺归位锚点：{missing}"


def test_cert_bodies_defined_for_every_mapped_industry():
    """F10 数据口径：有画像的行业都要有认证机构名单（认证卡兜底依赖它）。"""
    for subj in ("海上风电", "工业机器人", "半导体设备", "创新药",
                 "车载激光雷达", "低空经济", "新能源汽车"):
        assert cert_bodies(subj), f"{subj} 缺认证机构名单"


def test_mid_card_pool_never_overlaps_brand_leaders():
    """F10 数据口径：能力卡兜底名单不得含整机龙头（会与品牌卡抢人 → 跨节点重复）。"""
    for subj in ("海上风电", "工业机器人", "创新药", "消费无人机", "车载激光雷达"):
        brand = set(leading_companies(subj))
        for title, names in mid_card_pool(subj).items():
            overlap = set(names) & brand
            assert overlap == set(), f"{subj} 能力卡「{title}」与品牌卡龙头重叠：{overlap}"


# ── F15：品牌卡必须挂在中游 ────────────────────────────────────────────────

def _node(nid, label, stage, companies, core=False):
    return {"id": nid, "label": label, "companies": list(companies),
            "key_products": [], "description": "", "stage": stage,
            "is_core": core, "evidence_ids": []}


def test_brand_card_must_sit_on_midstream_node():
    """F15：is_core 在非中游节点 = 结构性错误，无条件纠偏到中游。

    实测（创新药 run-20261019121206）：A2 把 is_core 标在 support 的
    「监管与注册服务」上，企业名是 NMPA／CDE／NIFDC 三个**机构**——
    数量 ≥3 让旧判定第一行「企业够多就不动」直接放行，品牌卡变成监管机构卡。
    三列目录式版式里品牌卡恒在中游列，所以这里不看企业数，只看 stage。
    """
    topo = {"core_product": "创新药",
            "nodes": [_node("M1", "创新药研发与生产", "midstream", ["恒瑞医药"]),
                      _node("S1", "监管与注册服务", "support",
                            ["NMPA", "CDE", "NIFDC"], core=True)],
            "edges": []}
    move = core_misplacement(topo)
    assert move is not None, "非中游持有品牌卡必须纠偏"
    assert move == ("S1", "M1"), move
    errs = validate_topology(topo, allowed_companies={"恒瑞医药"},
                             allowed_evidence=set())
    assert any("is_core 挂错了节点" in e for e in errs), errs


def test_rd_node_in_midstream_keeps_core_when_no_better_candidate():
    """契约守卫：中游研发节点持 is_core 时**仍走「更优才改判」**口径。

    2026-10-19 曾把"研发节点"也改成无条件纠偏，导致所有节点都 <3 家时乱改核心
    （打破 test_core_misplacement_no_move_when_no_node_reaches_threshold）。
    研发类节点的纠偏由原有的「企业数 ≥ 下限且得分更高」规则负责，这里钉住不越权。
    """
    topo = {"core_product": "低空飞行器",
            "nodes": [_node("M1", "核心算法", "midstream", ["A"], core=True),
                      _node("M2", "整机厂", "midstream", ["B"])],
            "edges": []}
    assert core_misplacement(topo) is None


def test_strengthen_brand_card_fills_real_leaders_and_downgrades_tier():
    """品牌卡不足 3 家时用**整机/终端龙头**补足，且必须降级为 industry_common。

    实测（创新药 run-20261019121206）：品牌卡只剩 恒瑞／百济 2 家 < 3 →
    本体盒渲染不出来，全图最重要的视觉锚点整列消失。
    补进来的名字不在证据白名单里，若不降级会被 validate 报成"编造"（GOOD_TOPO 实测）。
    """
    topo = {"title": "创新药产业链全景图", "core_product": "创新药",
            "nodes": [_node("M1", "创新药企", "midstream",
                            ["恒瑞医药", "百济神州"], core=True)],
            "edges": []}
    topo["nodes"][0]["source_tier"] = "evidence"
    out, notes = strengthen_brand_card(topo, "创新药")
    comps = out["nodes"][0]["companies"]
    assert len(comps) >= BRAND_MIN_COMPANIES, comps
    assert out["nodes"][0]["source_tier"] == "industry_common"
    for c in comps[2:]:
        assert c in leading_companies("创新药"), f"补的不是本行业龙头：{c}"
    assert notes and "补本行业整机/终端龙头" in notes[0]


# ── F17：禁数字清洗器与体检器口径对齐 ─────────────────────────────────────

def test_sanitizer_keeps_model_grade_tokens():
    """F17：字母与数字粘连的**型号/等级代号**必须放行（与体检器同口径）。

    实测（run-20261019124137 车载激光雷达）：A2 给的细分词是
    「L2+辅助驾驶」「L4级自动驾驶」「工业3D检测」——体检器 `_MODEL_TOKEN_RE` 放行，
    清洗器 `sanitize_text_no_numbers` 却把它们整段删掉（两处口径不一致），
    结果 3 张下游场景卡画成「—」。上一轮同主题这三个词是「智能驾驶系统」等无数字写法，
    所以问题只在这一轮冒头，是**静默丢数据**不是模型退步。
    """
    for keep in ("L2+辅助驾驶", "L4级自动驾驶", "工业3D检测", "5G通信模组",
                 "碳纤维 T800", "HBM3", "V2X路侧感知", "AEC-Q100车规", "第3代半导体"):
        assert sanitize_text_no_numbers(keep) == keep, f"型号/等级词被误删：{keep}"


def test_sanitizer_still_drops_real_financial_numbers():
    """F17 兜底：真数值照旧删除——型号豁免不得成为财务数字的后门。

    特别注意「YoY+35%」这类**字母与数字粘连但确实是数值**的写法，
    靠 `_FINANCE_NUM_WORDS` 拦住（否则豁免条件会被它命中）。
    """
    for drop in ("毛利率区间25%-45%", "1200亿", "净利润 YoY+35%", "市场份额30%",
                 "2025年出货10万台", "营收同比增长25%"):
        assert sanitize_text_no_numbers(drop) == "", f"真数值未被拦下：{drop}"


def test_no_mid_card_title_carries_regulatory_function():
    """F16 数据口径：中游卡标题不得带监管职能词（审批/监管/许可/备案/审评）。

    🔴 根因在**画像自己**：pharma 的 mid_cards 原本写着「NMPA 审批与 GMP 生产」，
    它经 industry_profile_block 喂给 A2 → A2 照抄 → 这张卡又被代码判成品牌卡
    → 品牌卡标题写着"审批"、里面却是 恒瑞/百济/信达（run-20261019123544 实测）。
    「认证/检测/测试」不算监管职能（那是认证卡，各行业的正常中游环节），不在此列。
    """
    ban = ("审批", "监管", "许可", "备案", "审评")
    for subj in ("创新药", "海上风电", "工业机器人", "半导体设备",
                 "车载激光雷达", "消费无人机", "低空经济", "新能源汽车"):
        prof = detect_profile(subj)
        for card in (prof.get("mid_cards") or []):
            title = card[0] if isinstance(card, (list, tuple)) else str(card)
            assert not any(b in title for b in ban), \
                f"{subj} 中游卡标题「{title}」含监管职能词（审批属配套层）"


def test_strengthen_brand_card_noop_when_all_leaders_present():
    """品牌卡已包含画像**全部**龙头时不动（2026-10-21 行为更新）。

    旧规则：够 3 家就 noop。新规则：只要 leading_brand 有成员**完全缺失**
    （不在品牌卡、也不在其他节点）就补——用户点名的公司（如宇树科技）
    可能被 LLM 漏写，"已达标"不能成为它缺席的理由。上限仍是 MAX_BRANDS。
    """
    # 创新药画像的 leading_brand 全部在场 → noop
    from chart_generator.chain_profile import leading_companies
    leaders = leading_companies("创新药")
    assert leaders, "创新药画像应有龙头基准"
    topo = {"core_product": "创新药",
            "nodes": [_node("M1", "创新药企", "midstream", list(leaders), core=True)],
            "edges": []}
    out, notes = strengthen_brand_card(topo, "创新药")
    assert out["nodes"][0]["companies"] == list(leaders)
    assert notes == []


def test_strengthen_brand_card_entity_keeps_only_subject_company():
    """A 版（企业专属）：品牌卡只留主题公司，竞品移到配套层「同业对标」卡。

    2026-10-21 用户裁定：主题点名一家公司时，品牌卡**只有它一家是正确结果**。
    旧实现在这里把 `["宇树科技"]` 补成 6 家竞品（云深处/波士顿动力…），
    等于把竞品当成宇树的供应链 —— 本节用例锁死新口径。
    """
    from chart_generator.chain_profile import leading_companies

    leaders = leading_companies("宇树科技机器人")
    assert "宇树科技" in leaders, "quadruped 画像应含宇树科技"
    rivals = [c for c in leaders if c != "宇树科技"][:3]
    topo = {"core_product": "四足机器人",
            "nodes": [_node("M1", "本体制造与总装", "midstream", rivals, core=True)],
            "edges": []}
    out, notes = strengthen_brand_card(topo, "宇树科技机器人")
    comps = out["nodes"][0]["companies"]
    assert comps == ["宇树科技"], f"A 版品牌卡只能是主题公司：{comps}"
    peer = [n for n in out["nodes"] if "同业对标" in n["label"]]
    assert peer, "竞品不能凭空消失，必须落到配套层「同业对标」卡"
    assert set(peer[0]["companies"]) == set(rivals)
    assert any("竞品" in x for x in notes), notes


def test_strengthen_brand_card_industry_still_fills_leaders():
    """B 版（行业全景）行为不变：品牌卡不足 3 家时补画像龙头。

    A 版改动不得误伤 B 版 —— 行业主题下"品牌卡只 1 家"仍然是缺陷，
    因为一个行业本来就有多家整机厂。
    """
    topo = {"core_product": "工业机器人",
            "nodes": [_node("M1", "本体制造与总装", "midstream", ["埃斯顿"], core=True)],
            "edges": []}
    out, notes = strengthen_brand_card(topo, "工业机器人")
    comps = out["nodes"][0]["companies"]
    assert len(comps) >= 3, f"B 版品牌卡应补到 3 家以上：{comps}"
    assert "宇树科技" not in comps, "工业机械臂全景图的品牌卡不该混入四足厂"
    assert any("品牌卡不足" in x for x in notes), notes
