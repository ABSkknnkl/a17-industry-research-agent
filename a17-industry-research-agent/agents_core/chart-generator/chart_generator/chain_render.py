"""产业链 SVG 渲染器 —— 三列目录式（lane_grid）。

版式只有一个（2026-10-21 删掉旧的三套）：
- ``lane_grid`` 三列目录式：上游 / 中游 / 下游三列容器 + 卡片网格，
  列间两根粗箭头表达分层方向，配套层单独一条横带。V2 已核验关系另在主图关系区表达。
  依据：产业链图是「分类目录」不是「工艺流程图」——上游零部件并行供给，没有先后关系。

🔴 2026-10-21：``three_column_flow`` / ``backbone_attach`` / ``hub_spoke`` 三套旧版式
（四列泳道 + 逐条流线）与其色板/排版助手共 1099 行已删除。删除理由：
  ① 三套旧版式与「分类目录」的设计结论冲突，留着只会让 CHAIN_RENDER_MODE 一漏设
     就退回错版式（渲染脚本不加载 .env 就会发生，实测把旧模板图当新图给用户看）；
  ② ``CHAIN_RENDER_MODE`` 开关随之取消——渲染不再依赖环境变量，出图结果可复现。

铁律：
- 画布尺寸固定 1600×900（``_LG_W/_LG_H``），卡片按网格分配剩余高度；
- 只出白名单元素（与前端消毒白名单一致）。
"""

from __future__ import annotations

import os
from xml.sax.saxutils import escape, quoteattr

from chart_generator.chain_graph import (
    ChainGraphSpec,
    ChainNode,
)


def _text_width(s: str, font_size: float) -> float:
    return sum(font_size * (0.55 if ord(ch) < 0x2E80 else 1.0) for ch in (s or ""))


def _wrap_text(text: str, font_size: float, max_width: float, max_lines: int = 3) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    lines: list[str] = []
    cur, cur_w = "", 0.0
    for i, ch in enumerate(text):
        cw = font_size * (0.55 if ord(ch) < 0x2E80 else 1.0)
        # 2026-10-22（放大字号时暴露）：不要把「GO-1」这类"字母-数字"代号拆开。
        # 旧实现纯逐字断，放大后断成「…GO-」+「-1、银河通用」/「1、银河通用」，
        # 图上凭空出现裸数字，触发 numeric_in_chart 硬规则（3 条版式测试红）。
        glue = (
            (ch == "-" and 0 < i < len(text) - 1
             and text[i - 1].isalnum() and text[i + 1].isalnum())
            or (cur.endswith("-") and (ch.isalnum() or ch in "+#"))
        )
        if cur and cur_w + cw > max_width and not glue:
            lines.append(cur)
            cur, cur_w = ch, cw
            if len(lines) >= max_lines:
                break
        else:
            cur += ch
            cur_w += cw
    if cur and len(lines) < max_lines:
        lines.append(cur)
    elif len(lines) >= max_lines and cur:
        lines[-1] = lines[-1][:-1] + "…"
    return lines or []


# ── 卡片：第一趟算高 / 第二趟绘制（两趟布局）────────────────────────────────


# ── 核心节点本体盒（模板签名）──────────────────────────────────────────────
# 模板里「整机本体品牌」是浅底深描边的大盒 + 品牌列表一家一行，不是三行卡片。
# 核心节点 companies ≥3 时按本体盒渲染；不足 3 家走普通卡片（数据说话，不硬撑）。
_CORE_BODY_MIN_BRANDS = 3


def _use_core_body(node: ChainNode, min_brands: int = _CORE_BODY_MIN_BRANDS) -> bool:
    """该节点能不能画成「整机本体品牌」大卡。

    ``min_brands`` 默认 3（行业全景版：品牌卡至少 3 家才画得出品牌栏）。
    A 版（企业专属）由 ``spec.core_min_brands=1`` 覆盖 —— 单一公司图里
    品牌卡只有 1 家是正常结果，用 3 去卡会把核心降级成普通卡。
    """
    return bool(node.is_core
                and len([c for c in node.companies if str(c).strip()]) >= max(1, min_brands))


def _omitted_edge_labels(spec: ChainGraphSpec) -> set[tuple[str, str]]:
    """**有意不画**的边标签集合，返回 (source, target) 集合。

    lane_grid 整版不画连线（卡片之间零连线），所以**所有带标签的边**都属"有意不画"。
    渲染器与产物体检（``assert_graph_fidelity``）共用本函数，保证"不画"与"不查"同源——
    否则体检会把设计决策当成渲染缺陷报出来。

    2026-10-21：旧版按 ``CHAIN_RENDER_MODE`` 分流（flow 模式下只放行"同 stage 组 ≥3 条"
    的物料流标签）。旧版式已删，分流取消，恒返回"全部带标签的边"。
    """
    return {(e.source, e.target) for e in spec.edges if e.label}


# ── 统计行（lane_grid 右上角复用；体检把它算作"自动文本"豁免数字校验）──────────

def _stats_line(spec: ChainGraphSpec) -> str:
    """右上统计行（模板签名）：上游 N 环节 · 中游 M 环节 · <核心产品> K 品牌 · 下游 P 场景 · 配套 Q 支撑。

    2026-10-17 P0-A 修正：只有本体盒真的被拆成独立核心列时，才把核心节点从该段计数里扣掉。
    旧实现先找 ``_use_core_body`` 的核心节点，找不到就**退回任意 is_core 节点**，然后无条件
    ``cnt -= 1``——当核心节点企业不足 3 家（本体盒渲染不出来、卡片仍留在本段里）时，
    统计行会少算一个：run-20261016232834 实测输出「中游 2 环节」，而画面上明明白白画了
    3 张卡（核心算法 / 中游集成制造 / 整机厂），评委一眼可见的自相矛盾。
    """
    _min_brands = getattr(spec, "core_min_brands", _CORE_BODY_MIN_BRANDS)
    core = next((nd for nd in spec.nodes if nd.is_core and _use_core_body(nd, _min_brands)), None)
    # 本体盒没建起来时的核心节点：它仍在本段卡片里，计数**不能扣**
    plain_core = None if core else next((nd for nd in spec.nodes if nd.is_core), None)
    # A 版（企业专属）统计行用**公司名**而不是核心产品名：「宇树科技 1 品牌」。
    _label = ""
    if getattr(spec, "scope_kind", "industry") == "entity":
        _label = str(getattr(spec, "scope_entity", "") or "")
    _label = (_label or str(spec.core_product or "") or "本体")[:8]
    short = {"upstream": "上游", "midstream": "中游", "downstream": "下游",
             "support": "配套", "other": "其他"}
    unit = {"upstream": "环节", "midstream": "环节", "downstream": "场景",
            "support": "支撑", "other": "环节"}
    parts: list[str] = []
    for st in spec.stages:
        cnt = len(spec.stage_nodes(st.stage_id))
        if core and st.stage_id == core.stage:
            cnt -= 1
            if cnt > 0:
                parts.append(f"{short.get(st.stage_id, st.stage_id)} {cnt} {unit.get(st.stage_id, '环节')}")
            brands = len([c for c in core.companies if str(c).strip()])
            if brands:
                # 名字截到 8 字：统计行横排右上角，长名字会把整行拉爆
                parts.append(f"{_label} {brands} 品牌")
        elif plain_core and st.stage_id == plain_core.stage:
            if cnt:
                parts.append(f"{short.get(st.stage_id, st.stage_id)} {cnt} {unit.get(st.stage_id, '环节')}")
            brands = len([c for c in plain_core.companies if str(c).strip()])
            if brands:
                # 本体盒没画出来，品牌就不该叫"品牌列表"，如实写成代表企业
                parts.append(f"{_label} {brands} 家代表企业")
        elif cnt:
            parts.append(f"{short.get(st.stage_id, st.stage_id)} {cnt} {unit.get(st.stage_id, '环节')}")
    return " · ".join(parts)


# ════════════════════════════════════════════════════════════════════════════
# 三列目录式渲染器 lane_grid（2026-10-17 建立，2026-10-21 成为唯一版式）
#
# 为什么是它：产业链图是**分类目录**（一个行业由哪些玩家分层组成），
# 不是**工艺流程图**（一个对象按顺序经过哪些工序）。上游 8 个零部件是并行供给、
# 彼此没有先后关系，逐节点连线等于在画一个不存在的结构——线乱不是排版问题，
# 是图种选错。本渲染器的三条铁律：
#   ① 先画等高容器（泳道），再往网格里填卡片，内容多少不影响版面骨架；
#   ② 卡片之间**零连线**，全图只有 2 根列间粗箭头表达粗粒度价值方向；
#   ③ 整机不单列——它是中游的制造主体，与"研发/制造/认证"是包含关系而非并列。
# ════════════════════════════════════════════════════════════════════════════

_LG_W, _LG_H = 1600, 900
_LG_MG = 40.0
_LG_TITLE_Y, _LG_SUB_Y = 54.0, 86.0
_LG_LANE_TOP, _LG_LANE_HEAD_H = 110.0, 38.0
_LG_GRID_TOP, _LG_GRID_BOTTOM = 162.0, 620.0
_LG_GRID_H = _LG_GRID_BOTTOM - _LG_GRID_TOP
_LG_SUP_TOP, _LG_SUP_H = 664.0, 148.0
_LG_COL_GAP, _LG_CARD_GAP, _LG_COL_PAD, _LG_CARD_R = 34.0, 12.0, 14.0, 8.0
_LG_CORE_RATIO = 0.58                    # 中游大卡占列高比例
_LG_CAP_MAX = 4                          # 中游能力卡上限（＝中游节点数 - 整机大卡）

# 底部读法提示（常量：渲染器与数字体检豁免清单共用，保证"画什么"与"放行什么"同源）
_LG_READ_HINT = ("读法：自上而下扫一列。三列的 2 根箭头表达价值方向，"
                 "具体工序关系以核验关系区为准。　橙色双描边＝瓶颈环节　｜　中游大卡＝核心产品品牌主体，"
                 "下方小卡＝厂商内建能力")


def _lg_badge(role: str, items: list, core, caps: list) -> str:
    """列头右上角标文案（**渲染器与数字体检共用**，保证"画什么"与"放行什么"同源）。

    🔴 2026-10-21：拆成独立函数。旧实现把文案拼在 ``_render_lane_grid`` 里、
    豁免清单另拼一份，两处口径一旦不一致（下游写"场景"、清单只登记"环节"），
    体检就会把「1 场景」当成编造的数值，整张图降级回 ECharts。
    """
    if role == "midstream":
        return (f"{len(core.companies)} 品牌 · {len(caps)} 能力"
                if core else f"{len(caps)} 能力")
    if not items:
        return ""                       # 空列不打角标（"0 环节"既无用又会被体检抓）
    return f"{len(items)} {'场景' if role == 'downstream' else '环节'}"


def _lane_grid_auto_texts(spec: ChainGraphSpec) -> set[str]:
    """lane_grid 渲染器**自动生成**的结构计数文本（供 chain_lint 数字体检放行）。

    统计行 / 列头角标 / 品牌计数都是按 spec 现算的计数，不是 LLM 编的份额产能，
    与旧版 ``_stats_line`` 同理必须豁免，否则模板签名会被"禁数字"规则误杀。
    """
    out: set[str] = {_LG_READ_HINT}
    try:
        cols = _lg_columns(spec)
    except Exception:
        return out
    s = _lg_stats(spec, cols)
    if s:
        out.add(s)
    core = cols["core"]
    if core is not None:
        nb = len(core.companies)
        out.add(f"品牌主体 · {nb} 家")
    # 列头角标：与 _render_lane_grid 调同一个 _lg_badge，口径不可能再漂
    for role, items in (("upstream", cols["upstream"]),
                        ("midstream", cols["midstream_rest"]),
                        ("downstream", cols["downstream"])):
        b = _lg_badge(role, items, core, cols["caps"])
        if b:
            out.add(b)
    for key in ("upstream", "downstream"):
        n = len(cols[key])
        if n:
            out.add(f"{n} 环节")        # 兼容旧口径（统计行里出现的形式）
    return out

_LG_PAL: dict[str, tuple[str, str, str]] = {
    "upstream":   ("#2563EB", "#EFF6FF", "#DBEAFE"),
    "midstream":  ("#0891B2", "#ECFEFF", "#CFFAFE"),
    "core":       ("#0E7490", "#CFFAFE", "#A5F3FC"),
    "downstream": ("#7C3AED", "#F5F3FF", "#EDE9FE"),
    "support":    ("#64748B", "#F8FAFC", "#E2E8F0"),
}
_LG_INK, _LG_INK2, _LG_INK3 = "#0F172A", "#475569", "#94A3B8"
_LG_LINE, _LG_WHITE = "#E2E8F0", "#FFFFFF"
_LG_WARN = ("#D97706", "#FEF3C7")
_LG_PHASE = {"已落地": ("#065F46", "#D1FAE5"), "试点中": ("#B45309", "#FEF3C7"),
             "示范期": ("#6D28D9", "#EDE9FE"), "远期": ("#475569", "#F1F5F9")}
_LG_CN = "PingFang SC, Microsoft YaHei, system-ui, sans-serif"

# 中游能力卡兜底文案（研发/制造/适航这三件事对任何装备制造业都成立，不会出错）
_LG_CAP_FALLBACK: tuple[tuple[str, str], ...] = (
    ("研发算法与飞控软件", "飞行控制算法、仿真验证与软件授权"),
    ("整机制造与系统集成", "总装、航电联调与系统集成能力"),
    ("测试与适航认证", "适航审定、验证与第三方检测"),
)


def _lg_cap_fallback(spec: ChainGraphSpec) -> tuple[tuple[str, str], ...]:
    """能力卡兜底**按行业画像**取（2026-10-18 F3b）。

    🔴 旧 `_LG_CAP_FALLBACK` 写死低空经济三卡（研发算法与飞控软件/整机制造与
    系统集成/测试与适航认证），风电图和创新药图上都被塞进"飞控算法""适航认证"
    兜底卡——提示词行业化（F3）之后这是最后一块残留的低空硬编码。
    用 spec 自带的 title + core_product 判行业，取该行业画像的 mid_cards。
    """
    try:
        from chart_generator.chain_profile import detect_profile
        from chart_generator.chain_structure import detect_structure

        _key = f"{spec.title or ''} {spec.core_product or ''}"
        p = detect_profile(_key)
        # 🔴 2026-10-22「兜底串岗」：generic 画像的 mid_cards 是**硬件话术**
        #    （研发与设计→产品定义与结构/电气设计、整机制造与总装→零部件集成为整机与出厂检验、
        #      测试与认证→按行业真实认证体系填写）。
        #    白酒落 generic，但骨架是 consumer（农产品→酿造→渠道），
        #    `_cap_overlap` 靠 2-gram 把「配方与工艺研发」匹配到「研发与设计」、
        #    把「酿造与灌装生产」匹配到「整机制造与总装」（共享"造与"）→ 白酒卡上出现电气设计。
        #    规则：**generic 的硬件兜底池只服务 discrete 结构**，别的结构一律不给兜底，
        #    宁可卡片只显示企业/品类，也不要串行业话术。
        if p.get("key") == "generic" and detect_structure(_key).key != "discrete":
            return ()
        cards = p.get("mid_cards") or []
        if cards:
            out: list[tuple[str, str]] = []
            for c in cards:
                if isinstance(c, (list, tuple)) and len(c) >= 2:
                    out.append((str(c[0]), str(c[1])))
                else:
                    out.append((str(c), ""))
            return tuple(out)
    except Exception:
        pass
    return _LG_CAP_FALLBACK


def _lg_mid_head(spec: ChainGraphSpec) -> str:
    """中游列头标题（按行业画像；医药＝研发、临床与生产，不再硬套"整机制造"）。"""
    try:
        from chart_generator.chain_profile import detect_profile
        return (detect_profile(f"{spec.title or ''} {spec.core_product or ''}")
                .get("mid_column") or "整机制造与系统集成")
    except Exception:
        return "整机制造与系统集成"


# ── 文字缩放（2026-10-22 用户要求"把产业链图的文字放大"）───────────────────
# 只放大字号会造成溢出/截断：测量用的字号、行高、行距必须同步缩放，
# 否则 `_wrap_text` 按小字号算宽度、按大字号画，必然压字。
# 用环境变量 CHAIN_TEXT_SCALE 调（默认 1.25，即整体放大 25%）。
_LG_FS = float(os.environ.get("CHAIN_TEXT_SCALE", "1.25") or 1.25)


def _fs(size: float) -> float:
    """字号/行高统一缩放。"""
    return round(size * _LG_FS, 2)


def _lg_clip(text: str, size: float, max_w: float) -> str:
    """按可用宽度截断并加省略号。"""
    if _text_width(text, size) <= max_w:
        return text
    out = ""
    for ch in str(text):
        if _text_width(out + ch, size) > max_w - size * 0.9:
            break
        out += ch
    return out + "…"


def _lg_columns(spec: ChainGraphSpec) -> dict:
    """把 spec 拆成「上游 / 中游（整机大卡 + 能力卡）/ 下游」+ 配套带。

    核心节点用 ``_use_core_body`` 判定（与旧渲染器同源）——它回答"这个节点能不能
    画成整机品牌大卡"，与 ``is_core`` 标记一致但更严（要求企业数够）。
    """
    up = [nd for nd in spec.nodes if nd.stage == "upstream"]
    down = [nd for nd in spec.nodes if nd.stage == "downstream"]
    sup = [nd for nd in spec.nodes if nd.stage in ("support", "other")]
    # 🔴 B18（2026-10-17）：**先定 core，再按对象身份排除**。
    # 旧实现用 `not _use_core_body(nd)` 过滤 mid_rest，而 core 还有一条
    # `is_core` 兜底分支——两条判据不一致，于是兜底选出的 core 仍留在 mid_rest 里：
    # 半导体设备实测「整机制造与总装」既画成大卡又画成能力卡（重复），
    # 真正的「系统集成与调试」反被 mid_rest[:3] 挤掉（整节点消失）。
    core = next((nd for nd in spec.nodes
                 if _use_core_body(nd, getattr(spec, "core_min_brands", _CORE_BODY_MIN_BRANDS))), None)
    if core is None:                     # 兜底：没有可画成品牌大卡的核心 → 取 is_core
        core = next((nd for nd in spec.nodes if nd.is_core), None)
    mid_rest = [nd for nd in spec.nodes
                if nd.stage == "midstream" and nd is not core]

    # 中游能力卡：优先用中游非核心节点承载；不足 3 个用行业通用兜底补齐。
    # ⚠️ 语义归一（两级）：
    #   ① 子串：「研发算法」⊂「研发算法与飞控软件」——按字面判重会同时出两张卡（实测踩过）；
    #   ② 2-gram 重叠：「飞控算法」与「研发算法与飞控软件」无整词包含，但共享
    #      「飞控」「算法」两个二元词段，语义重复（run-20261017213418 实测）。
    #
    # 🔴 2026-10-17 B4：**只补描述、绝不改名**。旧实现把命中的节点名"升级"成兜底全名，
    #   结果该环节的原始名称从图上消失 → `assert_graph_fidelity` 逐字核对时报
    #   「节点『中游：核心产品研发…』缺失」（6 个主题 100% 复现）。
    #   保留原名既过事实锁死，又因兜底补卡按同一规则跳过而不产生重复卡。
    caps: list[dict] = []
    fallback = _lg_cap_fallback(spec)   # F3b：兜底卡按行业画像取，不再是低空专属词

    def _cap_overlap(a: str, b: str) -> bool:
        if a in b or b in a:
            return True
        grams = {a[i:i + 2] for i in range(len(a) - 1)}
        return any(g in b for g in grams)

    for nd in mid_rest[:_LG_CAP_MAX]:
        nm, desc = nd.name, (nd.description or "")
        for fb_name, fb_desc in fallback:
            if _cap_overlap(nm, fb_name):
                desc = desc or fb_desc      # 只补描述，保留节点原名
                break
        caps.append({"name": nm, "companies": list(nd.companies), "desc": desc})
    # 兜底补卡的判重分**两种尺度**，混用就会互相误伤：
    #   ① 同列（能力卡之间）+ 整机大卡：用 `_cap_overlap`（子串 + 2-gram 重叠）。
    #      B18 就是靠 2-gram 判掉「整机制造与总装」与 core「整机/本体」的语义重复。
    #   ② 跨列（中游能力卡 vs 配套列）：**只认字面包含/相等**。
    #      配套里叫「空管系统」不代表中游不能画「系统集成与调试」——用 2-gram
    #      去比，一个「系统」就把整张卡判死（低空经济夹具实测：3 张兜底卡全被挡，
    #      中游只剩 1 张能力卡）。跨列要防的只是"同一环节摆两列"，
    #      那种情况名字必然完全相同或互相包含（笔记本：两列都叫「测试与认证」）。
    pool = [c["name"] for c in caps]
    core_names = [core.name] if core is not None else []
    support_names = [str(nd.name) for nd in sup]

    def _cross_column_dup(name: str) -> bool:
        return any(name == c or name in c or c in name for c in support_names)

    for name, desc in fallback:
        if len(caps) >= 3:
            break
        if any(_cap_overlap(name, c) for c in pool + core_names):
            continue
        if _cross_column_dup(name):
            continue
        caps.append({"name": name, "companies": [], "desc": desc})
    return {"upstream": up, "midstream_rest": mid_rest, "core": core,
            "downstream": down, "support": sup, "caps": caps[:_LG_CAP_MAX]}


def _lg_lane(p: list[str], x: float, w: float, role: str) -> None:
    """泳道底（浅色容器 + 淡描边）。"""
    stroke, bg, _ = _LG_PAL[role]
    p.append(f'<rect x="{x:.1f}" y="{_LG_LANE_TOP:.1f}" width="{w:.1f}" '
             f'height="{_LG_GRID_BOTTOM - _LG_LANE_TOP:.1f}" rx="14" fill="{bg}" '
             f'fill-opacity="0.45" stroke="{stroke}" stroke-opacity="0.22" stroke-width="1.2"/>')


def _lg_head(p: list[str], x: float, w: float, title: str, role: str, badge: str) -> None:
    """列头胶囊 + 右侧角标。"""
    stroke, bg, _ = _LG_PAL[role]
    p.append(f'<rect x="{x:.1f}" y="{_LG_LANE_TOP:.1f}" width="{w:.1f}" '
             f'height="{_LG_LANE_HEAD_H:.1f}" rx="{_LG_LANE_HEAD_H/2:.1f}" '
             f'fill="{bg}" stroke="{stroke}" stroke-width="1.4"/>')
    p.append(f'<text x="{x + w/2:.1f}" y="{_LG_LANE_TOP + _LG_LANE_HEAD_H/2 + 5.5:.1f}" '
             f'font-size="{_fs(15)}" font-weight="700" text-anchor="middle" fill="{stroke}" '
             f'font-family="{_LG_CN}">{escape(title)}</text>')
    if badge:                      # 空列没有角标（避免 "0 环节" 这类无信息文本）
        p.append(f'<text x="{x + w - 14:.1f}" y="{_LG_LANE_TOP + 14:.1f}" font-size="{_fs(10)}" '
                 f'text-anchor="end" fill="{stroke}" fill-opacity="0.75">{escape(badge)}</text>')


def _lg_grid(items: list, x: float, w: float) -> tuple[list[tuple], float, float]:
    """通用网格排布：≤3 张走单列（避免 2×2 右下空一格），≥4 张走 2 列。"""
    ncol = 1 if len(items) <= 3 else 2
    rows = max(1, (len(items) + ncol - 1) // ncol)
    card_w = (w - 2 * _LG_COL_PAD - (ncol - 1) * _LG_CARD_GAP) / ncol
    card_h = (_LG_GRID_H - (rows - 1) * _LG_CARD_GAP) / rows
    boxes = []
    for i in range(len(items)):
        r, c = divmod(i, ncol)
        boxes.append((x + _LG_COL_PAD + c * (card_w + _LG_CARD_GAP),
                      _LG_GRID_TOP + r * (card_h + _LG_CARD_GAP), card_w, card_h))
    return boxes, ncol, card_h


def _lg_draw_card(p: list[str], x: float, y: float, w: float, h: float,
                  nd: ChainNode, role: str) -> None:
    """普通卡：3 行（环节名 / 代表公司 / 说明）+ 瓶颈双描边。"""
    stroke, _bg, _ = _LG_PAL[role]
    bn = bool(nd.bottleneck)
    box = _LG_WARN[0] if bn else stroke
    p.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{_LG_CARD_R}" '
             f'fill="{_LG_WHITE}" stroke="{box}" stroke-width="{2.2 if bn else 1.1}"/>')
    if bn:                               # 瓶颈：橙色双层描边
        p.append(f'<rect x="{x+3:.1f}" y="{y+3:.1f}" width="{w-6:.1f}" height="{h-6:.1f}" '
                 f'rx="{_LG_CARD_R-2}" fill="none" stroke="{_LG_WARN[0]}" stroke-width="0.9" '
                 f'stroke-opacity="0.55"/>')

    inner = w - 16
    # 低可信角标（产物体检硬规则）：web_unverified → 灰「待核」，其余 → 红「推断」。
    # 画在环节名右侧（内联），不占用瓶颈胶囊的右上角位置。
    tier = getattr(nd, "source_tier", "evidence")
    low_trust = bool(nd.inferred)
    name_txt = _lg_clip(nd.name, _fs(13.5), # 瓶颈胶囊在右上角（宽 34 + 边距），预留 46 已够；旧值 66 会把 10 字节点名
    # 截到 8 字以下，触发事实锁死「节点缺失」（创新药「生物反应器与制药设备」实测）
    inner - (46 if (bn or low_trust) else 0))
    p.append(f'<text x="{x+9:.1f}" y="{y+21:.1f}" font-size="{_fs(13.5)}" font-weight="700" '
             f'fill="{_LG_INK}" font-family="{_LG_CN}">'
             f'{escape(name_txt)}</text>')
    if bn:
        p.append(f'<rect x="{x+w-42:.1f}" y="{y+8:.1f}" width="34" height="15" rx="7.5" '
                 f'fill="{_LG_WARN[1]}" stroke="{_LG_WARN[0]}" stroke-width="0.9"/>')
        p.append(f'<text x="{x+w-25:.1f}" y="{y+19:.1f}" font-size="{_fs(9.5)}" font-weight="700" '
                 f'text-anchor="middle" fill="{_LG_WARN[0]}">瓶颈</text>')
    if low_trust:
        bx = x + 9 + _text_width(name_txt, _fs(13.5)) + 5
        p.append(f'<text x="{bx:.1f}" y="{y+21:.1f}" font-size="{_fs(9.5)}" font-weight="700" '
                 f'fill="{_LG_INK3 if tier == "web_unverified" else "#B42318"}">'
                 f'{"待核" if tier == "web_unverified" else "推断"}</text>')

    # B17：企业行不再按像素硬裁（尾部企业会被静默丢掉）
    clines, ty = _lg_company_lines(nd.companies, nd.items, inner, y + 40,
                                   y + h - 6, lh=_fs(13.0), x=x + 9)
    p.extend(clines)
    for line in _wrap_text(nd.description or "", _fs(10.5), inner, max_lines=2):
        if ty > y + h - 6:
            break
        p.append(f'<text x="{x+9:.1f}" y="{ty:.1f}" font-size="{_fs(10.5)}" fill="{_LG_INK3}" '
                 f'font-family="{_LG_CN}">{escape(line)}</text>')
        ty += _fs(14)


def _lg_company_lines(comps: list[str], items: list[str], inner: float,
                      top: float, bottom: float, lh: float = 13.0,
                      x: float = 0.0, fill: str = _LG_INK2) -> tuple[list[str], float]:
    """企业行：**宁可换行、降字号，绝不丢企业名**（2026-10-17 B17）。

    返回 ``(SVG 片段列表, 下一行的 y)``。

    背景（六个主题横向实测）：旧实现把企业拼成一行再 ``_lg_clip`` 按像素硬裁，
    尾部企业被静默丢掉——海上风电「塔筒与基础」4 家只画 3 家（海力风电消失）、
    创新药「药物研发与临床」丢君实生物；下游卡更严重，**压根不画 companies**
    （只画 ``items[:2]``），半导体设备下游 10 家企业 100% 丢失。
    而 ``assert_text_fidelity`` 是逐字核对的，丢了就报"事实锁死缺失"。

    策略：企业 → 细分（items）依次作为候选文本，在 (字号, 最大行数) 组合里挑
    **第一个既放得下又完整（无省略号）** 的方案；实在放不下才退化到截断版本。
    """
    txt = "、".join([str(c).strip() for c in (comps or []) if str(c).strip()])
    if not txt:
        txt = "｜".join([str(i).strip() for i in (items or [])[:2] if str(i).strip()])
    if not txt:
        return [], top

    def _emit(lines: list[str], font: float) -> list[str]:
        out = []
        yy = top
        for ln in lines:
            out.append(f'<text x="{x:.1f}" y="{yy:.1f}" font-size="{font}" fill="{fill}" '
                       f'font-family="{_LG_CN}">{escape(ln)}</text>')
            yy += lh
        return out

    fallback: tuple[list[str], float] | None = None
    for font, max_lines in ((_fs(10.5), 2), (_fs(10.0), 3), (_fs(9.5), 3), (_fs(9.0), 4)):
        lines = _wrap_text(txt, font, inner, max_lines=max_lines)
        if not lines:
            continue
        complete = "".join(lines) == txt          # 无省略号 ⇒ 一个字都没丢
        fits = top + lh * len(lines) <= bottom
        if complete and fits:
            return _emit(lines, font), top + lh * len(lines)
        if fallback is None:
            fallback = (lines, font)
    lines, font = fallback
    kept = [ln for i, ln in enumerate(lines) if top + lh * i <= bottom]
    return _emit(kept, font), top + lh * len(kept)


def _lg_draw_down(p: list[str], x: float, y: float, w: float, h: float,
                  nd: ChainNode) -> None:
    """下游场景卡：3 行 + 右上角阶段胶囊 + 底部采购方。"""
    stroke = _LG_PAL["downstream"][0]
    p.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{_LG_CARD_R}" '
             f'fill="{_LG_WHITE}" stroke="{stroke}" stroke-width="1.1"/>')
    # 阶段胶囊只在**显式给出** phase 时画。
    # 旧实现 `nd.phase or "已落地"` 会给所有下游卡默认盖上"已落地"——
    # 没有落地证据却显示确定性徽标，属于臆造结论（V8 方案 §10.6 明令禁止）。
    phase = str(nd.phase or "").strip()
    if phase and phase in _LG_PHASE:
        pc = _LG_PHASE[phase]
        p.append(f'<rect x="{x+w-56:.1f}" y="{y+8:.1f}" width="48" height="15" rx="7.5" '
                 f'fill="{pc[1]}" stroke="{pc[0]}" stroke-width="0.8"/>')
        p.append(f'<text x="{x+w-32:.1f}" y="{y+19:.1f}" font-size="{_fs(9.5)}" font-weight="700" '
                 f'text-anchor="middle" fill="{pc[0]}">{escape(phase)}</text>')

    inner = w - 16
    tier = getattr(nd, "source_tier", "evidence")
    low_trust = bool(nd.inferred)
    name_txt = _lg_clip(nd.name, _fs(13.5), inner - 52 - (26 if low_trust else 0))
    p.append(f'<text x="{x+9:.1f}" y="{y+22:.1f}" font-size="{_fs(13.5)}" font-weight="700" '
             f'fill="{_LG_INK}" font-family="{_LG_CN}">'
             f'{escape(name_txt)}</text>')
    if low_trust:
        bx = x + 9 + _text_width(name_txt, _fs(13.5)) + 5
        p.append(f'<text x="{bx:.1f}" y="{y+22:.1f}" font-size="{_fs(9.5)}" font-weight="700" '
                 f'fill="{_LG_INK3 if tier == "web_unverified" else "#B42318"}">'
                 f'{"待核" if tier == "web_unverified" else "推断"}</text>')
    # B17：企业优先于细分（旧实现只画 items，下游企业 100% 丢失）
    buyer = str(nd.buyer or "").strip()
    bottom = y + h - (22 if (buyer and h > 110) else 6)
    clines, ty = _lg_company_lines(nd.companies, nd.items, inner, y + 41,
                                   bottom, lh=13.0, x=x + 9)
    p.extend(clines)
    for line in _wrap_text(nd.description or "", _fs(10.5), inner, max_lines=2):
        if ty > bottom:
            break
        p.append(f'<text x="{x+9:.1f}" y="{ty:.1f}" font-size="{_fs(10.5)}" fill="{_LG_INK3}" '
                 f'font-family="{_LG_CN}">{escape(line)}</text>')
        ty += _fs(14)
    buyer = str(nd.buyer or "").strip()
    if buyer and h > 110:
        p.append(f'<text x="{x+9:.1f}" y="{y+h-11:.1f}" font-size="{_fs(10)}" fill="{_LG_INK2}" '
                 f'font-family="{_LG_CN}">采购方：{escape(_lg_clip(buyer, 10, inner - 42))}</text>')


def _lg_draw_core(p: list[str], x: float, y: float, w: float, h: float,
                  nd: ChainNode) -> None:
    """中游整机大卡：品牌是主体，2 列居中标签（无项目符号）。"""
    stroke, bg, _ = _LG_PAL["core"]
    p.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="12" '
             f'fill="{bg}" stroke="{stroke}" stroke-width="1.8"/>')
    p.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="4" rx="2" fill="{stroke}"/>')
    inner = w - 24
    p.append(f'<text x="{x+12:.1f}" y="{y+27:.1f}" font-size="{_fs(15)}" font-weight="800" '
             f'fill="{_LG_INK}" font-family="{_LG_CN}">{escape(nd.name)}</text>')
    p.append(f'<text x="{x+w-12:.1f}" y="{y+27:.1f}" font-size="{_fs(10.5)}" text-anchor="end" '
             f'fill="{stroke}">品牌主体 · {len(nd.companies)} 家</text>')
    one = _wrap_text(nd.description or "", _fs(10.5), inner, max_lines=1)
    if one:
        p.append(f'<text x="{x+12:.1f}" y="{y+45:.1f}" font-size="{_fs(10.5)}" fill="{_LG_INK2}" '
                 f'font-family="{_LG_CN}">{escape(one[0])}</text>')

    brands = list(nd.companies)
    if not brands:
        return
    tag_top, tag_bottom, tag_gap = y + 55, y + h - 12, 9.0
    rows = max(1, (len(brands) + 1) // 2)
    tag_h = max(24.0, (tag_bottom - tag_top - (rows - 1) * tag_gap) / rows)
    tag_w = (inner - 10) / 2
    for i, b in enumerate(brands):
        r, c = divmod(i, 2)
        tx = x + 12 + c * (tag_w + 10)
        ty = tag_top + r * (tag_h + tag_gap)
        p.append(f'<rect x="{tx:.1f}" y="{ty:.1f}" width="{tag_w:.1f}" height="{tag_h:.1f}" '
                 f'rx="6" fill="{_LG_WHITE}" stroke="{stroke}" stroke-opacity="0.45" '
                 f'stroke-width="0.9"/>')
        p.append(f'<text x="{tx+tag_w/2:.1f}" y="{ty+tag_h/2+4.5:.1f}" font-size="{_fs(12.5)}" '
                 f'font-weight="700" text-anchor="middle" fill="{_LG_INK}" '
                 f'font-family="{_LG_CN}">{escape(_lg_clip(b, 12.5, tag_w - 14))}</text>')


def _lg_draw_cap(p: list[str], x: float, y: float, w: float, h: float, cap: dict) -> None:
    """中游能力小卡（整机厂的内建能力，不是独立产业链环节）。"""
    stroke = _LG_PAL["midstream"][0]
    p.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{_LG_CARD_R}" '
             f'fill="{_LG_WHITE}" stroke="{stroke}" stroke-opacity="0.7" stroke-width="1.1"/>')
    inner = w - 16
    ty = y + 20
    for line in _wrap_text(cap["name"], _fs(12), inner, max_lines=2):
        p.append(f'<text x="{x+8:.1f}" y="{ty:.1f}" font-size="{_fs(12)}" font-weight="700" '
                 f'fill="{_LG_INK}" font-family="{_LG_CN}">{escape(line)}</text>')
        ty += 15
    ty += 4
    clines, ty = _lg_company_lines(cap["companies"], [], inner, ty,
                                   y + h - 6, lh=14.0, x=x + 8)
    p.extend(clines)
    for line in _wrap_text(cap["desc"], _fs(10), inner, max_lines=3):
        if ty > y + h - 6:
            break
        p.append(f'<text x="{x+8:.1f}" y="{ty:.1f}" font-size="{_fs(10)}" fill="{_LG_INK3}" '
                 f'font-family="{_LG_CN}">{escape(line)}</text>')
        ty += 13


def _lg_draw_support(p: list[str], items: list[ChainNode]) -> None:
    """底部配套通栏：N 个虚线卡横向均分。"""
    stroke = _LG_PAL["support"][0]
    p.append(f'<rect x="{_LG_MG:.1f}" y="{_LG_SUP_TOP:.1f}" width="{_LG_W-2*_LG_MG:.1f}" '
             f'height="{_LG_SUP_H:.1f}" rx="12" fill="{_LG_PAL["support"][1]}" stroke="{stroke}" '
             f'stroke-opacity="0.35" stroke-width="1.1"/>')
    p.append(f'<text x="{_LG_MG+14:.1f}" y="{_LG_SUP_TOP+22:.1f}" font-size="{_fs(12)}" '
             f'font-weight="700" fill="{_LG_INK2}" font-family="{_LG_CN}">'
             f'配套：服务、软件与回收体系</text>')
    if not items:
        return
    n = len(items)
    gap = 14.0
    cw = (_LG_W - 2 * _LG_MG - 28 - (n - 1) * gap) / n
    cy, ch = _LG_SUP_TOP + 32, _LG_SUP_H - 46
    for i, nd in enumerate(items):
        cx = _LG_MG + 14 + i * (cw + gap)
        p.append(f'<rect x="{cx:.1f}" y="{cy:.1f}" width="{cw:.1f}" height="{ch:.1f}" '
                 f'rx="{_LG_CARD_R}" fill="{_LG_WHITE}" stroke="{stroke}" stroke-opacity="0.55" '
                 f'stroke-width="1" stroke-dasharray="5,4"/>')
        inner = cw - 16
        tier = getattr(nd, "source_tier", "evidence")
        name_txt = _lg_clip(nd.name, 12.5, inner - (26 if nd.inferred else 0))
        p.append(f'<text x="{cx+8:.1f}" y="{cy+20:.1f}" font-size="{_fs(12.5)}" font-weight="700" '
                 f'fill="{_LG_INK}" font-family="{_LG_CN}">'
                 f'{escape(name_txt)}</text>')
        if nd.inferred:
            bx = cx + 8 + _text_width(name_txt, 12.5) + 5
            p.append(f'<text x="{bx:.1f}" y="{cy+20:.1f}" font-size="{_fs(9.5)}" font-weight="700" '
                     f'fill="{_LG_INK3 if tier == "web_unverified" else "#B42318"}">'
                     f'{"待核" if tier == "web_unverified" else "推断"}</text>')
        clines, ty = _lg_company_lines(nd.companies, nd.items, inner, cy + 38,
                                       cy + ch - 5, lh=13.0, x=cx + 8)
        p.extend(clines)
        for line in _wrap_text(nd.description or "", _fs(9.8), inner, max_lines=2):
            if ty > cy + ch - 5:
                break
            p.append(f'<text x="{cx+8:.1f}" y="{ty:.1f}" font-size="{_fs(9.8)}" fill="{_LG_INK3}" '
                     f'font-family="{_LG_CN}">{escape(line)}</text>')
            ty += 13


def _lg_draw_arrow(p: list[str], x1: float, x2: float, y: float) -> None:
    """列间粗箭头（全图仅 2 根）。"""
    p.append(f'<line x1="{x1:.1f}" y1="{y:.1f}" x2="{x2-9:.1f}" y2="{y:.1f}" stroke="#CBD5E1" '
             f'stroke-width="7" stroke-linecap="round"/>')
    p.append(f'<polygon points="{x2-10:.1f},{y-7:.1f} {x2+1:.1f},{y:.1f} '
             f'{x2-10:.1f},{y+7:.1f}" fill="#CBD5E1"/>')


def _lg_stats(spec: ChainGraphSpec, cols: dict) -> str:
    """右上角统计行（与画面卡片数一致）。

    2026-10-21：中游那段补上**核心产品名**。旧版只写「中游 N 能力 · M 品牌」，
    ``core_product``（如"低空飞行器""四足机器人"）在图上一个字都不出现——
    读者看到的是一堆环节名，不知道这些环节在造什么。
    """
    parts = []
    if cols["upstream"]:
        parts.append(f"上游 {len(cols['upstream'])} 环节")
    if cols["core"]:
        # A 版用公司名（「宇树科技 1 品牌」），B 版用核心产品名（「工业机器人 6 品牌」）
        if getattr(spec, "scope_kind", "industry") == "entity":
            _cp = (str(getattr(spec, "scope_entity", "") or "")
                   or str(spec.core_product or "") or "本体")[:8]
        else:
            _cp = (spec.core_product or "本体")[:8]
        parts.append(f"中游 {len(cols['caps'])} 能力 · {_cp} {len(cols['core'].companies)} 品牌")
    if cols["downstream"]:
        parts.append(f"下游 {len(cols['downstream'])} 场景")
    if cols["support"]:
        parts.append(f"配套 {len(cols['support'])} 支撑")
    return " · ".join(parts)


def _verified_relation_panel(spec: ChainGraphSpec) -> tuple[list[str], float]:
    """Draw directed pairs separately so dense relations do not cross the overview cards."""
    if spec.source != "v2_bundle":
        return [], 0
    nodes = spec.node_map()
    edges = {
        edge.edge_id: edge for edge in spec.edges
        if edge.edge_id and edge.assertion_ids and edge.evidence_record_ids
        and edge.source in nodes and edge.target in nodes and edge.source != edge.target
    }
    y = _LG_H + 36
    if not edges:
        return [f'<text x="{_LG_MG}" y="{y}" font-size="24">环节分类图 · 尚无可核验的工序关系</text>'], 56

    panel = [f'<text x="{_LG_MG}" y="{y}" font-size="28" font-weight="700">已核验的环节关系</text>']
    gap = 18
    columns = min(2, len(edges))
    cell_width = (_LG_W - 2 * _LG_MG - (columns - 1) * gap) / columns
    row_height = 70
    for i, edge in enumerate(sorted(edges.values(), key=lambda item: (item.source, item.target, item.edge_id))):
        source, target = nodes[edge.source], nodes[edge.target]
        row, column = divmod(i, columns)
        left = _LG_MG + column * (cell_width + gap)
        top = y + 15 + row * row_height
        mid = left + cell_width / 2
        title = f"{source.name} → {target.name}（{edge.label or '工序先后'}）"
        attrs = {
            "data-edge-id": edge.edge_id, "data-source": edge.source, "data-target": edge.target,
            "data-evidence-ids": ",".join(edge.evidence_record_ids),
            "data-assertion-ids": ",".join(edge.assertion_ids),
            "data-relation-scope": "same-stage" if source.stage == target.stage else "cross-stage",
        }
        rendered_attrs = " ".join(f"{name}={quoteattr(value)}" for name, value in attrs.items())
        panel.append(f'<g {rendered_attrs}><title>{escape(title)}</title>')
        panel.append(f'<rect x="{left}" y="{top}" width="{cell_width}" height="61" rx="5" fill="#f1f5f9"/>')
        label_width = cell_width / 2 - 39
        for name, x, anchor in ((source.name, mid - 31, "end"), (target.name, mid + 31, "start")):
            lines = _wrap_text(name, 23, label_width, max_lines=2)
            first_baseline = top + (38 if len(lines) == 1 else 26)
            for line_index, line in enumerate(lines):
                panel.append(f'<text x="{x}" y="{first_baseline + 25 * line_index}" text-anchor="{anchor}" '
                             f'font-size="23" fill="#172b4d">{escape(line)}</text>')
        _lg_draw_arrow(panel, mid - 23, mid + 23, top + 30)
        panel.append("</g>")
    return panel, 60 + ((len(edges) + columns - 1) // columns) * row_height


def _render_lane_grid(spec: ChainGraphSpec, width: int = 1440) -> str:
    """三列目录式渲染（详见本节顶部注释）。

    结构与旧版的关键差异：
      · 卡片区只显示分层方向，已核验关系在独立区域绘制；
      · 整机并入中游列顶部大卡，与"研发/制造/适航"能力卡构成包含关系；
      · 列底统一对齐（``_LG_GRID_BOTTOM``），内容多少不改变版面骨架。
    """
    cols = _lg_columns(spec)
    s = width / _LG_W
    relation_panel, extra_height = _verified_relation_panel(spec)
    canvas_height = _LG_H + extra_height
    w, h = _LG_W * s, canvas_height * s
    mg = _LG_MG * s

    # 2026-10-18 F3b：中游列头按行业画像（医药图曾出现「中游：整机制造与系统集成」）
    # 2026-10-22：三个列头统一取 spec 上的 stage.title —— 那里由
    # `chain_structure.stage_titles()` 按**结构/画像**生成（白酒=原料与包装供给/生产与品牌运营）。
    # 旧实现把上/下游写死成硬件文案，白酒图仍显示"上游：核心供给与零部件"。
    _tmap = {str(s.stage_id): str(s.title) for s in (spec.stages or [])}
    _bare = {"", "上游", "中游", "下游", "配套", "其他"}   # 只有 stage 名的裸标题 → 用默认文案

    def _head(sid: str, fallback: str) -> str:
        title = _tmap.get(sid, "").strip()
        return fallback if title in _bare else title

    columns = [
        (_head("upstream", "上游：核心供给与零部件"), "upstream", cols["upstream"]),
        (_head("midstream", f"中游：{_lg_mid_head(spec)}"), "midstream", cols["midstream_rest"]),
        (_head("downstream", "下游：渠道与应用场景"), "downstream", cols["downstream"]),
    ]
    ratios = {"upstream": 1.00, "midstream": 1.24, "downstream": 1.12}
    total_r = sum(ratios[r] for _t, r, _n in columns)
    avail = _LG_W - 2 * _LG_MG - _LG_COL_GAP * (len(columns) - 1)
    widths = [avail * ratios[r] / total_r for _t, r, _n in columns]
    xs: list[float] = []
    cursor = _LG_MG
    for wd in widths:
        xs.append(cursor)
        cursor += wd + _LG_COL_GAP

    p: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_LG_W} {canvas_height}" '
        f'width="{width}" height="{int(h)}" font-family="{_LG_CN}">',
        f'<rect width="{_LG_W}" height="{canvas_height}" fill="{_LG_WHITE}"/>',
    ]
    # 浅灰网格底（只用 <line>，与前端消毒白名单一致）
    for gx in range(0, _LG_W, 32):
        p.append(f'<line x1="{gx}" y1="0" x2="{gx}" y2="{_LG_H}" stroke="{_LG_LINE}" '
                 f'stroke-opacity="0.45"/>')
    for gy in range(0, _LG_H, 32):
        p.append(f'<line x1="0" y1="{gy}" x2="{_LG_W}" y2="{gy}" stroke="{_LG_LINE}" '
                 f'stroke-opacity="0.45"/>')

    p.append(f'<text x="{_LG_MG:.1f}" y="{_LG_TITLE_Y:.1f}" font-size="{_fs(27)}" font-weight="800" '
             f'fill="{_LG_INK}" font-family="{_LG_CN}">{escape(spec.title)}</text>')
    if spec.subtitle:
        p.append(f'<text x="{_LG_MG:.1f}" y="{_LG_SUB_Y:.1f}" font-size="{_fs(12.5)}" '
                 f'fill="{_LG_INK2}" font-family="{_LG_CN}">{escape(spec.subtitle)}</text>')
    stats = _lg_stats(spec, cols)
    if stats:
        p.append(f'<text x="{_LG_W-_LG_MG:.1f}" y="{_LG_TITLE_Y:.1f}" font-size="{_fs(11.5)}" '
                 f'text-anchor="end" fill="{_LG_INK3}" font-family="{_LG_CN}">'
                 f'{escape(stats)}</text>')

    # 泳道 + 列头
    for (title, role, items), x, wd in zip(columns, xs, widths):
        _lg_lane(p, x, wd, role)
        badge = _lg_badge(role, items, cols["core"], cols["caps"])
        _lg_head(p, x, wd, title, role, badge)

    # 2 根列间箭头（网格中线）
    arrow_y = _LG_GRID_TOP + _LG_GRID_H / 2
    for i in range(len(columns) - 1):
        _lg_draw_arrow(p, xs[i] + widths[i] + 6, xs[i + 1] - 6, arrow_y)

    # 卡片
    for (title, role, items), x, wd in zip(columns, xs, widths):
        if role == "midstream":
            core = cols["core"]
            core_h = _LG_GRID_H * _LG_CORE_RATIO
            if core is not None:
                _lg_draw_core(p, x + _LG_COL_PAD, _LG_GRID_TOP,
                              wd - 2 * _LG_COL_PAD, core_h, core)
            cap_top = _LG_GRID_TOP + core_h + _LG_CARD_GAP
            cap_h = _LG_GRID_BOTTOM - cap_top
            nc = max(1, len(cols["caps"]))
            # 🔴 2026-10-21：能力卡 ≥3 张改走 2 列网格。旧实现一律单行平铺，
            # 3 张时每张只剩 ~126px，「关节模组与灵巧手」这类 8 字标题必然溢出到邻卡上
            # （宇树科技原型图实测：中游三卡标题互相压盖）。
            ncol = 1 if nc <= 2 else 2
            rows = max(1, (nc + ncol - 1) // ncol)
            cap_w = (wd - 2 * _LG_COL_PAD - (ncol - 1) * _LG_CARD_GAP) / ncol
            cap_row_h = (cap_h - (rows - 1) * _LG_CARD_GAP) / rows
            for i, cap in enumerate(cols["caps"]):
                r, c = divmod(i, ncol)
                _lg_draw_cap(p, x + _LG_COL_PAD + c * (cap_w + _LG_CARD_GAP),
                             cap_top + r * (cap_row_h + _LG_CARD_GAP),
                             cap_w, cap_row_h, cap)
            continue
        if not items:
            continue
        boxes, ncol, card_h = _lg_grid(items, x, wd)
        for nd, (cx, cy, card_w, chh) in zip(items, boxes):
            if role == "downstream":
                _lg_draw_down(p, cx, cy, card_w, chh, nd)
            else:
                _lg_draw_card(p, cx, cy, card_w, chh, nd, role)
        # 🔴 2026-10-19 F11：**删除**「其他场景 / 新兴应用持续涌现」补位虚格。
        # 旧逻辑在网格正好空一格时补一张假卡，只为"右下角不像缺一块"。
        # 用户判定：它不提供任何信息，是图上的噪声；少一格比假卡干净。
        #（需要补格时应由上游补真实场景节点，而不是渲染器编一张。）

    _lg_draw_support(p, cols["support"])

    p.append(f'<text x="{_LG_MG:.1f}" y="{_LG_H-14:.1f}" font-size="{_fs(10)}" fill="{_LG_INK3}" '
             f'font-family="{_LG_CN}">{escape(_LG_READ_HINT)}</text>')
    p.extend(relation_panel)
    p.append("</svg>")
    return "".join(p)


def render_chain_svg(spec: ChainGraphSpec, width: int = 1440) -> str:
    """渲染产业链 SVG（唯一版式：三列目录式 ``lane_grid``）。

    2026-10-21：不再按 ``CHAIN_RENDER_MODE`` 分派。旧版默认回到 ``flow``（四列泳道 +
    逐条流线），任何没加载 ``.env`` 的调用方（批处理脚本、离线审计）都会静默退回错版式，
    实测把旧模板图当新图交付。现在只有一条路径，出图结果与运行环境无关。
    """
    return _render_lane_grid(spec, width)
