"""产业链图产物级校验（2026-10-08，移植老项目 chain_designer 的两处收口机制）。

老项目有两道"产物出口"检查，本模块把它们从"生图提示词场景"翻译到"SVG 场景"：

1. ``check_facts``（老项目：节点/企业/连线标签必须逐字命中提示词）
   → ``assert_graph_fidelity``：拓扑里的每个节点名/企业名/连线标签必须逐字出现在 SVG 文本中。
   理由：拓扑是"事实底稿"，渲染必须忠实；缺一个节点名就是**口径事故**（环节凭空消失）。

2. ``REVIEW_SYSTEM`` 六项清单中的「负面约束 / 版式 / 卡片质量」
   → ``lint_chain_svg``：确定性检查，不调 LLM——
     · 禁数字（需求3：产业链图只要结构与文字，出现数值即口径风险）
     · 禁占位符（XX/示例/TODO/待补…）
     · 流线语义一致（material 必须实线、其余必须虚线）
     · 三行卡片齐备（有企业/细分行、有环节说明行）
     · 推断节点必须有「推断」角标

用法：渲染后调用；``lint_chain_svg`` 出现 ``error`` 级问题 → 降级不发布该图；
``assert_graph_fidelity`` 失败 → 说明渲染管线有 bug，必须抛（属代码缺陷，不是数据问题）。
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

_SVG_NS = "{http://www.w3.org/2000/svg}"

# 数字：允许出现在 viewBox/坐标等属性里，只查「文本节点内容」
_NUM_RE = re.compile(r"\d+(?:\.\d+)?%?")
# 数字白名单：少数环节名本身含数字（如"碳纤维 T800"、"三代半导体"），长度≤4 视为型号
_ALLOWED_NUM_CONTEXT = ("第", "代", "T", "V", "A", "nm", "G", "M", "系", "型")
# 型号/缩写粘连判定（2026-10-16 校准）：数字与拉丁字母粘在一起（3C / 5G / T800 / GO-1 / 1X / HBM3）
# 视为产品型号或行业缩写，放行；"25%" "1200亿" 这类真数值不粘连，照样拦。
_MODEL_TOKEN_RE = re.compile(r"[A-Za-z]+-?\d+[A-Za-z]*|\d+[A-Za-z]+")
# 财务/经营口径词：片段命中这些词就**不可能是型号代号**，禁数字规则照旧生效。
# （用于 sanitize 的型号豁免兜底，防止「净利润 YoY+35%」这类因为字母数字粘连被放行。）
_FINANCE_NUM_WORDS = ("%", "％", "亿", "万", "元", "同比", "环比", "份额", "毛利", "净利",
                      "增速", "占比", "规模", "价格", "产能", "出货", "装机", "产量",
                      "渗透率", "复合", "CAGR", "YoY", "yoy", "YoY")
_PLACEHOLDER_WORDS = ("XX", "xx", "示例", "例示", "TODO", "待补", "待定", "占位", "???", "…")


def _auto_texts_to_exempt(spec) -> set[str]:
    """渲染器**自动生成**的文本白名单（2026-10-16）。

    右上统计行（"上游 7 环节 · 中游 3 环节 · 新能源汽车 6 品牌 …"）是渲染器按 spec 现算的
    结构计数，不是 LLM 编的份额/产能/营收数值——必须放行，否则模板签名会被"禁数字"规则误杀。
    做法是直接复用渲染器的 `_stats_line` 拿精确字符串，不用正则去猜格式
    （猜格式踩过坑：core_product 带括号斜杠就会漏）。
    """
    out: set[str] = set()
    try:
        from chart_generator.chain_render import _stats_line
        s = _stats_line(spec)
        if s:
            out.add(s)
    except Exception:      # 渲染器不可用时退回空集合，不影响其它检查
        pass
    try:
        # lane_grid（三列目录式）的统计行/角标/读法提示同样含结构计数数字
        from chart_generator.chain_render import _lane_grid_auto_texts
        out |= _lane_grid_auto_texts(spec)
    except Exception:
        pass
    return out


def is_finance_number(clause: str) -> bool:
    """该子句里的数字是**真数值**（份额/产能/营收）而非型号/等级代号。

    🔴 2026-10-19（诊断引擎首次跑真实数据发现）：F17 用「长度 ≤12 字」做型号豁免，
    ``L2+级智驾感知核心传感器``（14 字）仍然整段被删 → 车载激光雷达「ADAS智驾」卡的
    描述直接消失，而 ``lint_chain_texts`` 看不到被删的内容、报 0 问题。

    改用"数字是否被型号 token 完全覆盖"判定，与长度无关：

    - 含财务口径词（%/亿/毛利/产能/出货…）→ **真数值**；
    - 剥掉全部型号 token 后仍有数字 → **真数值**；
    - 其余 → 型号代号（L2+ / 3D / 5G / T800 / HBM3 / V2X）。

    单一实现：``chain_lint`` 与 ``chain_diag`` 共用本函数，避免 F17 那类"两处口径不一致"。
    """
    if any(w in clause for w in _FINANCE_NUM_WORDS):
        return True
    stripped = _MODEL_TOKEN_RE.sub("", clause)
    return bool(_NUM_RE.search(stripped))


def sanitize_text_no_numbers(text: str, *, max_len: int = 60) -> str:
    """剔除含数值/占位符的句子片段（需求3：产业链图只要结构与文字）。

    实测来源：A2 的 LLM 会把别处的数值塞进环节说明（如「毛利率区间25%-45%」），
    提示词约束不住，必须在**渲染边界做确定性清洗**——整句丢弃而不是删掉数字，
    避免留下「毛利率区间-」这种残句。
    """
    text = (text or "").strip()
    if not text:
        return ""
    clauses = [c.strip() for c in re.split(r"[，。；;,.]", text)]
    kept: list[str] = []
    for c in clauses:
        if not c:
            continue
        if any(w in c for w in _PLACEHOLDER_WORDS):
            continue
        if _NUM_RE.search(c):
            # 型号类短数字放行（T800 / 三代 / 5G）
            stripped = _NUM_RE.sub("", c)
            # 纯数值判定：剩余不足 2 字**且数字不是型号代号的一部分**才删。
            # 旧实现不看型号，`3C` 剥掉「3」只剩「C」（1 字）→ 被整段删掉，
            # 消费无人机「3C认证」卡因此丢词（2026-10-19 诊断引擎实测）。
            if (_NUM_RE.search(c) and len(stripped.strip()) < 2
                    and not _MODEL_TOKEN_RE.search(c)):
                continue
            if any(a in c for a in _ALLOWED_NUM_CONTEXT) and len(c) <= 12:
                kept.append(c)
                continue
            # 🔴 2026-10-19 F17：与体检器 `lint_chain_texts` 对齐——**字母与数字粘连**
            # 视为型号/等级代号放行（L2+ / L4级 / 3D / 5G / T800 / HBM3）。
            # 两处口径不一致的实测代价（run-20261019124137 车载激光雷达）：
            # A2 给的细分词是「L2+辅助驾驶」「L4级自动驾驶」「工业3D检测」，
            # 体检器放行、清洗器却把它们整段删掉 → 3 张下游卡画成「—」。
            # 兜底：命中财务/经营口径词的片段一律不豁免（那才是真数值）。
            # 2026-10-19 二次修正：不再用「≤12 字」做阈值——长句里的型号
            # （L2+级智驾感知核心传感器）会被误删，改由 `is_finance_number` 精确判定。
            if _MODEL_TOKEN_RE.search(c) and not is_finance_number(c):
                kept.append(c)
                continue
            continue
        kept.append(c)
    return "，".join(kept)[:max_len]


def _texts(svg: str) -> list[str]:
    root = ET.fromstring(svg)
    return [
        "".join(el.itertext()).strip()
        for el in root.iter(f"{_SVG_NS}text")
        if "".join(el.itertext()).strip()
    ]


def lint_chain_texts(spec, texts: list[str]) -> list[dict[str, str]]:
    """文本级体检（2026-10-17 抽出，供 SVG 与 HTML 两条出图路径共用）。

    此前这套检查硬绑在 SVG 的 ``<text>`` 解析上；新增「LLM 排 HTML → 截图」路径后，
    门禁必须同口径，否则同一张拓扑在两条路径下的准入标准会不一致。
    调用方负责把各自的产物抽成可见文本片段列表。
    """
    issues: list[dict[str, str]] = []

    # ① 负面约束：禁占位符
    # ⚠️ 2026-10-17 B16：渲染器按卡片宽度截断文本时会补「…」（``_lg_clip`` /
    # ``_tpl_clip``），这是**排版行为**不是 LLM 编的占位符。旧实现一律判 error，
    # 实测创新药图因「百济神州、恒瑞医药、百利…」被判占位符 → 整图降级 ECharts，
    # 恰好把博查补漏的成果抵消掉。
    # 判据：以「…」结尾且去掉省略号后是某个已知名称（环节/企业/品类）的前缀
    # → 认定为渲染截断，放行；否则仍按占位符拦。
    _known_stems: set[str] = set()
    for _n in getattr(spec, "nodes", []):
        for _v in (_n.name, *(_n.companies or []), *(_n.items or [])):
            if _v and len(str(_v).strip()) >= 2:
                _known_stems.add(str(_v).strip())

    def _is_render_truncation(t: str) -> bool:
        if not t.endswith("…"):
            return False
        stem = t[:-1].strip()
        if len(stem) < 2:
            return False
        # 单名截断：如「国轩…」
        if any(k.startswith(stem) for k in _known_stems if len(k) > len(stem)):
            return True
        # 多名拼接截断：如「宁德时代、国轩…」——前面各段须为已知名，
        # 末段须为某个已知名的前缀（最后一家被截断）。
        for sep in ("、", "｜", "|", "，", ",", "/"):
            if sep not in stem:
                continue
            parts = [p.strip() for p in stem.split(sep) if p.strip()]
            if len(parts) < 2:
                continue
            head, tail = parts[:-1], parts[-1]
            if all(h in _known_stems for h in head) and any(
                    k.startswith(tail) for k in _known_stems if len(k) >= len(tail)):
                return True
        return False

    for t in texts:
        if "…" in t and _is_render_truncation(t):
            continue
        for w in _PLACEHOLDER_WORDS:
            if w in t:
                issues.append({"level": "error", "code": "placeholder",
                               "message": f"文本含占位符「{w}」：{t[:20]}"})

    # ② 负面约束：禁数字（型号类短数字 + 已知企业名 + 渲染器自动文本放行）
    # 2026-10-16 校准：企业名本身可以含型号数字（1X Technologies / 智元 GO-1 / 碳纤维 T800），
    # 逐字禁数字会把合法品牌名打掉。做法：先把 spec 里已知的企业名整段掩蔽、再扫数值——
    # 精准豁免"名字里的数字"，不放开"份额/产能/营收里的数字"。
    known_names = [str(c) for n in getattr(spec, "nodes", []) for c in (n.companies or []) if c]
    auto_exempt = _auto_texts_to_exempt(spec)
    for t in texts:
        if t in auto_exempt:
            continue
        masked = t
        for name in sorted(known_names, key=len, reverse=True):
            if name and name in masked:
                masked = masked.replace(name, "◇" * len(name))
        for m in _NUM_RE.finditer(masked):
            ctx = masked[max(0, m.start() - 1): m.end() + 1]
            if len(m.group()) <= 4 and any(a in ctx for a in _ALLOWED_NUM_CONTEXT):
                continue
            # 与字母粘连 → 型号/缩写（3C / GO-1 / 1X / T800），放行
            if any(tok for tok in _MODEL_TOKEN_RE.findall(masked) if m.group() in tok):
                continue
            issues.append({"level": "error", "code": "numeric_in_chart",
                           "message": f"产业链图不应出现数值「{m.group()}」：{t[:24]}"})
            break

    # ④ 卡片质量：有企业/细分的节点应在图上出现该行
    # 注意：必须**无分隔**拼接——卡片文字会按栏宽换行（如采购方拆成两行），
    # 用空格 join 会把换行处切断，导致"内容明明在图上了却判缺失"（2026-10-16 实测）。
    blob = "".join(texts)
    for node in spec.nodes:
        if node.inferred and "推断" not in blob:
            issues.append({"level": "error", "code": "missing_inferred_mark",
                           "message": f"推断节点「{node.name}」缺少「推断」角标"})
            break
    # ⑤ 模板字段体检（2026-10-16）：瓶颈必须有角标、下游阶段/采购方必须上图
    if any(n.bottleneck for n in spec.nodes) and "瓶颈" not in blob:
        issues.append({"level": "error", "code": "missing_bottleneck_mark",
                       "message": "存在瓶颈节点但图上没有「瓶颈」角标"})
    for node in spec.nodes:
        if node.phase and node.phase not in blob:
            issues.append({"level": "error", "code": "missing_phase",
                           "message": f"节点「{node.name}」的落地阶段「{node.phase}」未上图"})
        if node.buyer and node.buyer not in blob:
            issues.append({"level": "error", "code": "missing_buyer",
                           "message": f"节点「{node.name}」的采购方「{node.buyer}」未上图"})
    return issues


def lint_company_grounding(spec) -> list[dict[str, str]]:
    """归属与命名的**体检统计**（2026-10-25，方案 §4）。

    两项都是 **warning**，绝不阻断出图：
      ① 泛词环节名（核心部件/关键材料/…）——修复层 0.15 步应该已经改名，
         剩下的都是"没有具体品类可依据"的卡，需要人工补内容；
      ② 归属无 KB 依据比例——KB 只覆盖 A 股，境外/未上市（联想/大疆/宇树）
         恒为无记录，比例高≠错。它衡量的是"这张图有多少内容落在底座之外"，
         用来判断该不该补画像/联网，而不是用来删人。
    """
    issues: list[dict[str, str]] = []
    try:
        from chart_generator.chain_ontology import is_generic_label  # noqa: PLC0415

        generic = [n.name for n in spec.nodes if is_generic_label(n.name)]
        if generic:
            issues.append({"level": "warning", "code": "generic_slot_label",
                           "message": f"环节名仍是泛词：{generic}（需人工补具体品类）"})
    except Exception:                                  # pragma: no cover
        pass

    try:
        from chart_generator import chain_kb             # noqa: PLC0415

        names = [c for n in spec.nodes for c in (n.companies or []) if str(c).strip()]
        if names and chain_kb.available():
            backed = sum(1 for c in names if chain_kb.company_profile(c) is not None)
            ratio = backed / len(names)
            if ratio < 0.5:
                issues.append({
                    "level": "warning", "code": "kb_coverage_low",
                    "message": (f"归属无 KB 依据比例偏高：{len(names) - backed}/{len(names)} "
                                f"家企业在底座外（KB 仅覆盖 A 股，境外/未上市属正常）")})
    except Exception:                                  # pragma: no cover
        pass
    return issues


def lint_chain_svg(spec, svg: str) -> list[dict[str, str]]:
    """确定性体检。返回 [{level, code, message}]；level=error 需降级，warning 仅提示。"""
    try:
        texts = _texts(svg)
    except ET.ParseError as exc:
        return [{"level": "error", "code": "svg_parse", "message": f"SVG 不合法：{exc}"}]

    issues = lint_chain_texts(spec, texts)

    # ③ 流线语义（仅 SVG 可查）：material 实线、technical/service/recycle 虚线。
    # 2026-10-16 起边色改为「源段色」（对齐模板：上游边蓝、中游边青、配套边灰），
    # 不能再按颜色判定，改为读渲染器写的 data-flow 属性。
    root = ET.fromstring(svg)
    for el in root.iter(f"{_SVG_NS}polyline"):
        flow = el.attrib.get("data-flow")
        if not flow or not el.attrib.get("marker-end"):
            continue
        dashed = "stroke-dasharray" in el.attrib
        if flow == "material" and dashed:
            issues.append({"level": "warning", "code": "flow_style",
                           "message": "实物流（material）不应为虚线"})
        if flow != "material" and not dashed:
            issues.append({"level": "warning", "code": "flow_style",
                           "message": f"{flow} 流应为虚线"})
    # ⑤ 命名与归属统计（warning，不阻断）
    issues.extend(lint_company_grounding(spec))
    return issues


def assert_text_fidelity(spec, blob: str, *,
                         omit_unrendered_edges: bool = True) -> list[str]:
    """事实锁死（文本层）：节点名/企业名/连线标签必须逐字出现。

    抽出为公共层的原因同 `lint_chain_texts`：HTML 截图路径也要走同一套"一个字都不能少"的审计。
    注意 blob 必须**无分隔**拼接（见 lint_chain_texts ④ 的踩坑注记）。

    ``omit_unrendered_edges``：是否豁免"版式上本就不画"的连线标签。
      · SVG 三列目录式（lane_grid）卡片之间零连线 → True，否则每条边都会被误报；
      · HTML 排版版仍画连线（``.flowtag``），其提示词也要求"一个标签都不能少"
        → False，漏写必须报出来交给 ``ensure_edge_labels`` 补。
    两条路径版式不同，豁免口径必须分开——2026-10-21 删旧渲染器时踩过：
    一刀切 True 会让 HTML 路径的连线检查形同虚设。
    """
    missing: list[str] = []
    omitted: set[tuple[str, str]] = set()
    if omit_unrendered_edges:
        try:
            from chart_generator.chain_render import _omitted_edge_labels
            omitted = _omitted_edge_labels(spec)
        except Exception:
            omitted = set()
    for node in spec.nodes:
        head = node.name[:8]
        if head and head not in blob:
            missing.append(f"节点「{node.name}」")
            continue
        for comp in node.companies:
            if comp and comp not in blob:
                missing.append(f"企业「{comp}」（{node.name}）")
        # 2026-10-16 模板字段同样锁死：瓶颈角标/落地阶段/采购方丢失即渲染缺陷
        if node.bottleneck and "瓶颈" not in blob:
            missing.append(f"瓶颈角标（{node.name}）")
        if node.phase and node.phase not in blob:
            missing.append(f"落地阶段「{node.phase}」（{node.name}）")
        if node.buyer and node.buyer not in blob:
            missing.append(f"采购方「{node.buyer}」（{node.name}）")
    for e in spec.edges:
        if e.label and e.label not in blob and (e.source, e.target) not in omitted:
            missing.append(f"连线「{e.label}」")
    return missing


def assert_graph_fidelity(spec, svg: str) -> list[str]:
    """事实锁死：拓扑里的节点名/企业名/连线标签必须逐字出现在 SVG 中。

    返回缺失清单（空 = 通过）。与老项目 check_facts 同义，区别是老项目仅告警，
    这里把缺失视为**必须拦截**（环节凭空消失是口径事故）。

    例外（2026-10-16）：物料流多线汇聚时渲染器**有意**不贴边标签（7-8 个标签挤在同一条
    gutter 会互相压盖），由 `_omitted_edge_labels` 给出同源清单——"不画"与"不查"必须同源，
    否则体检会把设计决策当成渲染缺陷。
    """
    try:
        texts = _texts(svg)
    except ET.ParseError:
        return ["<SVG 解析失败>"]
    return assert_text_fidelity(spec, "".join(texts))
