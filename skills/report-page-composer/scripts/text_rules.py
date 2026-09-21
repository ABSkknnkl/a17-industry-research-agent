#!/usr/bin/env python3
"""report-page-composer 的正文净化规则（**全仓库唯一来源**）。

## 为什么必须集中在这里

机器字段、内部状态码、证据 ID、超精度数值这四类污染会反复出现在同一份上游内容里。
如果渲染器、渲染前检查、渲染后审计各写一套词表，三者一定会漂移，审计就会
**放过渲染器没清掉的东西，或者误报渲染器已处理的东西**。

因此：

    * 渲染器必须 `from text_rules import sanitize_public` 后清洗正文；
    * scripts/text_hygiene.py（渲染前）与 scripts/audit_render.py（渲染后）共用同一份词表；
    * report-style-benchmark/scripts/text_rules.py 是本文件的**转发壳**，不得再存副本；
    * 后端经 `backend/app/reporting/text_rules_loader.py` 加载本文件；
    * 需要扩展词表时只改本文件，不要在各脚本里另加分支。

## 2026-09-18 收敛记录（三份词表 → 一份）

收敛前存在三份互不相同的词表：

    ① skills/report-page-composer/scripts/text_rules.py   —— 本文件（含 sanitize_public）
    ② skills/report-style-benchmark/scripts/text_rules.py —— ① 的精简副本，靠注释"上游更新时同步"
    ③ backend/app/reporting/html.py::_PUBLIC_TEXT_RULES   —— 23 条独立正则，措辞与 ① 不同

③ 与 ① 的冲突导致**同一段文字在 HTML 与 Markdown 里被净化成不同结果**，
且 ③ 缺少 ① 的状态码与精度处理 —— 交付 PDF 里因此残留了
`competition · partial` 这类内部状态码与 81 处 3 位以上小数。

本次合并原则：**保留渲染端（③）已被验证的措辞，补上 ① 中 ③ 缺失的规则**。
逐条冲突的裁决记在下面各表的上方注释里。

纯标准库实现，无第三方依赖。
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata

# ---------------------------------------------------------------------------
# 1. 内部工件名 → 读者可读表述
#    key 用普通字符串替换；key 越长越先匹配（见 sanitize_public 的排序）。
#
#    注意：这里用 replace 而非正则，因为 CJK 字符在 Python re 里也算 \w，
#    `\bscope\b` 这类边界在中文句子里不会命中（"与scope、" 中 scope 两侧都不是 \b）。
#    html.py 曾用 (?<![A-Za-z])...(?![A-Za-z]) 绕开，但那只能覆盖 ASCII 邻接。
# ---------------------------------------------------------------------------
MACHINE_FIELD_MAP: dict[str, str] = {
    # 上游数据契约字段
    # missing_inputs 的落点统一为「数据限制清单」：html.py 曾映射为「数据缺口」，
    # 但同一文件的另一条规则又把「数据缺口清单」改写为「数据限制清单」，
    # 两条规则因顺序互相抵消，同一个概念出现两种措辞。现统一。
    "missing_inputs": "数据限制清单",
    "dimension_coverage": "维度覆盖记录",
    "period_end": "数据截止日",
    "available_at": "数据可用日",
    "scope": "统计口径",
    "fact_id": "事实编号",
    "claim_id": "结论编号",
    "citation_id": "引用编号",
    # 生成管线与 skill 自身
    "report-page-composer": "本报告编辑规范",
    "report-style-benchmark": "本报告对照规范",
    "page_composition_plan": "页面编排蓝图",
    "PageCompositionPlan": "页面编排蓝图",
    # 研究请求与证据契约字段（2026-09-18 补齐）
    #
    # 交付 HTML 实测残留：`focus_question要求的近四年营业收入`、
    # `唯一company_level的完整财务序列`、`restatement_status为unknown`、
    # `accounting_standard未提供`、`audit_status均为unaudited`、
    # `该证据grade为C、caliber为company_level`、`unit字段为“未提供”`。
    # 这些是证据台账的字段名与 scope 取值，属于硬约束 #5 禁止暴露的机器标识。
    # 长的必须排在短的前面（_FIELD_KEYS_SORTED 已按长度降序处理）。
    "focus_questions": "用户核心问题",
    "focus_question": "用户核心问题",
    "focus_companies": "重点关注企业",
    "restatement_status": "追溯调整状态",
    "accounting_standard": "会计准则",
    "audit_status": "审计状态",
    "company_level": "公司级",
    "industry_level": "行业级",
    "caliber": "口径标注",
    # 编排智能体编号（具体编号优于泛称，故先于 PIPELINE_PHRASE_RES 的兜底规则生效）
    "Agent 4": "章节质量门",
    "Agent 3": "图表质量门",
    "Agent 2": "证据质量门",
    "Agent 1": "研究质量门",
}

# ---------------------------------------------------------------------------
# 2. 生成管线描述 → 读者可读表述
#    顺序敏感：长句式必须排在短词之前。
#
#    冲突裁决（① vs ③）：环节名采用 ③ 的措辞。
#      ① 数据解读智能体 → "研究报告"  会得到"研究报告的结构化结论"，语义不通；
#      ③ 数据解读智能体 → "研究结论生成环节" 准确。图表/章节两个同理。
# ---------------------------------------------------------------------------
PIPELINE_PHRASE_RES: tuple[tuple[re.Pattern[str], str], ...] = (
    # 整段自述（最长，必须最先）
    (
        re.compile(r"报告由数据解读智能体的结构化结论、图表智能体的已校验图表与章节撰写智能体的[^；;]*正文确定性组装"),
        "本报告由结构化研究结论、已校验图表与分章正文组装而成",
    ),
    (re.compile(r"报告融合智能体不新增事实、不改写数据结论"), "不新增事实、不改写数据结论"),
    (re.compile(r"本章由[^。；]*智能体[^。；]*生成"), "本章结论基于已校验的结构化证据"),
    # 单个环节名
    (re.compile(r"数据解读智能体"), "研究结论生成环节"),
    (re.compile(r"图表智能体"), "图表校验环节"),
    (re.compile(r"章节撰写智能体"), "正文撰写环节"),
    (re.compile(r"融合智能体|编排智能体"), "编辑环节"),
    # 兜底：MACHINE_FIELD_MAP 只列了 Agent 1–4，其余编号走这里
    (re.compile(r"Agent\s*\d+"), "上游环节"),
)

# ---------------------------------------------------------------------------
# 3. 流程语言与残留措辞（迁移自 backend/app/reporting/html.py::_PUBLIC_TEXT_RULES）
#    这些规则原先只存在于渲染端，skill 的 text_hygiene/audit 看不见，
#    因此渲染器改了措辞而审计无从校验。现并入唯一词表。
# ---------------------------------------------------------------------------
PROSE_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    # 长句在前：先整句改写，再处理残片
    #
    # 「编号 + 环节名」指的是同一件事，必须一次折叠掉。
    # 否则 MACHINE_FIELD_MAP 先把 "Agent 4" 换成「章节质量门」，紧随其后的
    # 「质量门 → 质量校验」再把后半句也换掉，同一句里出现两次「章节质量校验」。
    # 2026-09-18 交付 PDF 实测原文：「章节质量校验 章节质量校验未通过」
    # （上游原文 "Agent 4 章节质量门未通过"）。放在 PROSE_RULES 最前，
    # 早于下面的「质量门」单字规则。
    (re.compile(r"(章节|图表|证据|研究)质量门[\s　]+\1质量门"), r"\1质量校验"),
    # 「质量门校验」本身就把同一个词写了两遍，先折叠再走单字规则。
    (re.compile(r"质量门校验"), "质量校验"),
    (re.compile(r"[，,]?\s*本节保留研究位置[，,]?\s*待补充数据后复核"), "，待数据补齐后再行评估"),
    (re.compile(r"保留研究位置"), "暂缓判断"),
    (re.compile(r"待补充数据后复核"), "待数据补齐后再行评估"),
    (re.compile(r"质量门"), "质量校验"),
    (re.compile(r"回填校验"), "复核"),
    (re.compile(r"证据索引一致"), "证据一致"),
    (re.compile(r"内部审计层"), "质量附录"),
    (re.compile(r"不依赖其内容"), "仅供参考"),
    # 内部处置语（Agent 2 的对账决定 + 处理建议）不得出现在图注里。
    # 2026-09-18 实测交付图注原文：
    #   「…已择优保留E-07（法定审计与信息丰富度优先），本条被降级；
    #     处理：核实两来源口径差异后保留其一或单独说明。」
    # 这既是内部语言泄漏，也把图注撑到两行以上、直接触发 CAPTION_OVERLOAD。
    # 体裁判据（editorial-density-rules.md）：图注只保留「短来源 + 必要口径」，
    # 分析目的与长说明移入正文或附录。
    (re.compile(r"[；;，,]?\s*处理：\s*[^。]*。?"), ""),
    (re.compile(r"同数据点多条证据值不一致[，,]?[^。；;]*?本条被降级"), "多来源口径不一致，已择一采用"),
    (re.compile(r"已择优保留"), "已择一采用"),
    (re.compile(r"本条被降级"), ""),
    (re.compile(r"法定审计与信息丰富度优先"), ""),
    (re.compile(r"信息丰富度优先"), ""),
    # 兼容历史措辞（旧版 missing_inputs 的落点）
    (re.compile(r"数据缺口清单"), "数据限制清单"),
    # 裸 ASCII 字段词（2026-09-18 补齐）。
    #
    # 这三个走 PROSE_RULES 而不是 MACHINE_FIELD_MAP：后者是 str.replace 无边界，
    # 把 `unit` 放进表里会切进 `unit_price`、把 `grade` 放进表里会切进 `upgrade`。
    # 这里用 ASCII lookaround（与状态码同一套写法，见 _ASCII_ID_LEFT 注释）。
    # 整句形态必须排在裸词之前，否则先被裸词拆碎。
    # 替换成「单位未标注」而不是「未标注单位」：实测上下文是
    # `动力电池销量当月同比数据的unit字段为“未提供”。`，名词已经在前，
    # 用「未标注单位」会得到「数据的未标注单位」这种不成句的中文。
    (re.compile(r"(?<![A-Za-z0-9_])unit字段为\s*[“\"]?未提供[”\"]?"), "单位未标注"),
    (re.compile(r"(?<![A-Za-z0-9_])grade(?![A-Za-z0-9_])"), "数据质量等级"),
    (re.compile(r"(?<![A-Za-z0-9_])unit(?![A-Za-z0-9_])"), "单位"),
    # 同一个字段被写了两遍：正文里已经有中文标签，紧随其后的英文字段名又被映射成
    # 同一个标签。2026-09-18 实测 `数据质量等级grade为C` → 「数据质量等级数据质量等级为C」、
    # `口径标注caliber缺失` → 「口径标注口径标注缺失」。
    # 与上面「质量门」折叠同一类缺陷（中文标签 + 对应的英文字段名指的是同一个字段）。
    # ⚠️ **必须排在 `grade`/`unit` 之后** —— 重复是那两条规则制造出来的，
    # 放在前面就看不见。
    (
        re.compile(r"(数据质量等级|追溯调整状态|审计状态|会计准则|口径标注)[\s　]*\1"),
        r"\1",
    ),
)

# ---------------------------------------------------------------------------
# 4. 内部状态码 → 中文可读状态
#
#    ⚠️ 这张表是 2026-09-18 之前**渲染端完全没有接上**的一张表。
#    后果：交付 PDF 正文里残留 "代表项：competition · partial、growth · partial、
#    macro_policy · partial" 与 "代表项：unavailable、warning"。
#    genre 审计的 INTERNAL_PROCESS_LANGUAGE 只查 MACHINE_FIELD_MAP +
#    PIPELINE_PHRASE_RES，查不到状态码，所以这些残留一路通过了所有门禁。
#
#    ⚠️ 措辞一致性（2026-09-18 第二次收敛）：
#    backend/app/reporting/presentation.py 的 COVERAGE_STATUS_LABELS /
#    CHECK_STATUS_LABELS 早已为同一批状态码定了中文，且已经在 MD 与 HTML 的
#    结构化表格里发出去了。本表若另起一套措辞，同一份报告会出现
#    「部分支持」与「部分覆盖」并存 —— 实测交付 PDF 里 5 : 6 并存。
#    因此本表**对齐 presentation.py 的既有措辞**：一个状态码，全文一个说法。
#    tests/reporting/test_text_rules_parity.py 把这条一致性钉成断言。
# ---------------------------------------------------------------------------
STATUS_CODE_MAP: dict[str, str] = {
    # 证据覆盖状态（对齐 COVERAGE_STATUS_LABELS）
    "supported": "证据充分",
    "partial": "部分支持",
    "insufficient": "证据不足",
    # 检查/交付状态（对齐 CHECK_STATUS_LABELS）
    "passed": "通过",
    "warning": "需要复核",
    "unavailable": "资料不足",
    "failed": "未通过",
    "not_applicable": "不适用",
    # 上游工具与管线状态
    "UNSUPPORTED-METRICS": "指标口径不受支持",
    "data_fetch": "数据获取",
    # 审计与质量状态取值（2026-09-18 补齐）。
    # 这三个值此前完全没有映射，交付 HTML 实测 24 处 `unaudited`、
    # 15 处 `unknown`、1 处 `pending_review` —— 全部以英文原样出现在读者面前。
    "unaudited": "未经审计",
    "unknown": "未说明",
    "pending_review": "待复核",
    # 研究维度（对齐 DIMENSION_LABELS）
    "competition": "竞争格局",
    "growth": "行业增长",
    "macro_policy": "宏观与政策",
    "industry_chain": "产业链",
    "risk": "风险",
    "profitability": "盈利能力",
}

# ---------------------------------------------------------------------------
# 5. 内部标识：无论是否在括号内都要从阅读层清除
# ---------------------------------------------------------------------------
BARE_CODE_RE = re.compile(
    r"(?:E-[0-9a-f]{8,}"
    r"|CALC-[A-Za-z0-9]{6,}"
    r"|C-[A-Z0-9]{6,}"
    r"|CI-[A-Z0-9]{4,}"
    r"|CHART-[0-9A-F]{6,})"
)
# 完整括号包裹的标识组（连同括号一起删）
PAREN_CODE_RE = re.compile(
    r"[（(]\s*(?:E-[0-9a-f]{8,}|C-[A-Z0-9\-]+|CI-[A-Z0-9]+|DQ-\d+|CHART-[0-9A-F]{6,}"
    r"|P-\d{2}-\d{2}-\d{2})"
    r"(?:\s*[、,，]\s*(?:E-[0-9a-f]{8,}|C-[A-Z0-9\-]+|CI-[A-Z0-9]+|DQ-\d+))*\s*[)）]"
)

# ---------------------------------------------------------------------------
# 6. 数值精度降档
#    正文统一到业务精度；审计级精度只允许留在内部附录。
# ---------------------------------------------------------------------------
HIGH_PRECISION_PCT_RE = re.compile(r"(-?\d+)\.(\d{3,})(\s*[%％])")
YUAN_AMOUNT_RE = re.compile(r"(?<![\d.])(-?)(\d{9,})(?:\.(\d+))?\s*元")
# 无单位的高位裸数（10 位以上）一定是原始金额
BIG_BARE_NUMBER_RE = re.compile(r"(?<![\d.,])(-?)(\d{10,})(?:\.(\d+))?(?![\d.,])")
DECIMALS_3PLUS_RE = re.compile(r"(?<![\d.])(\d+)\.(\d{3,})(?![\d])")

# ---------------------------------------------------------------------------
# 7. 空话模板：同一“无数据可判”句式全文只保留一次
# ---------------------------------------------------------------------------
FILLER_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"当前可用证据不足以对.{0,40}?形成可靠事实判断[，,]?本节保留研究位置[，,]?待补充数据后复核。?"),
    re.compile(r"当前证据台账无法支撑.{0,40}?。"),
    re.compile(r"本节保留研究位置[，,]?待补充数据后复核"),
    re.compile(r"资料不足[，,]?不补造事实或数字"),
)


def is_filler(text: str) -> bool:
    return any(rx.search(text) for rx in FILLER_RES)


def filler_pattern_index(text: str) -> int | None:
    """返回命中的空话模板下标。

    同一句式的第 2 次及以后出现才是缺陷；用下标而非原文做归并键，
    才能把「当前可用证据不足以对 A 形成…」与「…对 B 形成…」识别为同一句式。
    """
    for index, rx in enumerate(FILLER_RES):
        if rx.search(text):
            return index
    return None


# ---------------------------------------------------------------------------
# 文本规范化与相似度（去重用）
# ---------------------------------------------------------------------------
_WS_RE = re.compile(r"\s+")
HTML_DANGEROUS_BLOCK_RE = re.compile(
    r"<\s*(script|style)\b[^>]*>.*?<\s*/\s*\1\s*>",
    re.IGNORECASE | re.DOTALL,
)
# Only remove known lower-case HTML presentation tags.  A broad ``<...>``
# pattern would corrupt legitimate research prose such as ``A<B>C`` or
# threshold expressions.  Upper-case/unknown tags remain plain text and are
# escaped by the Markdown/Jinja output layer; executable script/style blocks
# are removed separately above, case-insensitively.
HTML_TAG_RE = re.compile(
    r"</?(?:a|abbr|b|blockquote|br|code|div|em|h[1-6]|i|li|ol|p|pre|small|span|strong|sub|sup|table|tbody|td|th|thead|tr|u|ul)(?:\s[^>]*)?/?>"
)


def normalize_text(text: str) -> str:
    """去空白、NFKC 归一，用于重复段落比对。"""
    return _WS_RE.sub("", unicodedata.normalize("NFKC", text or ""))


def shingles(text: str, size: int = 4) -> set[str]:
    if len(text) <= size:
        return {text} if text else set()
    return {text[i : i + size] for i in range(len(text) - size + 1)}


def similarity(a: str, b: str) -> float:
    """Jaccard 相似度，对中文长句的重排与轻微改写足够敏感。"""
    if a == b:
        return 1.0
    sa, sb = shingles(a), shingles(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


# ---------------------------------------------------------------------------
# 净化主函数
# ---------------------------------------------------------------------------
_STATUS_ALT = "|".join(re.escape(code) for code in sorted(STATUS_CODE_MAP, key=len, reverse=True))
# 状态码全是 ASCII 标识符，必须用「ASCII 邻接」而非 \b 做边界：
#   * \b 在 CJK 语境不可靠（见 MACHINE_FIELD_MAP 上方注释）；
#   * 没有边界时 `supported` 会命中 `unsupported` 内部（→ "un证据充分"），
#     `risk` 会命中 `asterisk`，`growth` 会命中 `growth_rate`。
# 这两个断言式 lookaround 只在 ASCII 标识符字符旁才拦截，中文标点、空格、
# 行首行尾一律放行，因此 `：competition · partial、growth` 仍然正常命中。
_ASCII_ID_LEFT = r"(?<![A-Za-z0-9_\-])"
_ASCII_ID_RIGHT = r"(?![A-Za-z0-9_\-])"
STATUS_CHAIN_RE = re.compile(
    rf"{_ASCII_ID_LEFT}(?:{_STATUS_ALT})(?:\s*·\s*(?:{_STATUS_ALT}))*{_ASCII_ID_RIGHT}"
)
_FIELD_KEYS_SORTED = tuple(sorted(MACHINE_FIELD_MAP, key=len, reverse=True))


def humanize_status(text: str) -> str:
    """把「competition · partial」这类内部状态串改写为「竞争格局 · 部分支持」。

    支持两种出现形态：
      * 链式（`a · b`）—— 整串一次映射；
      * 孤立（`unavailable、warning`）—— 正则只要求单个码，`、` 分隔也能各自命中。

    边界用 ASCII lookaround（见上方 `_ASCII_ID_LEFT` 注释），
    因此 `unsupported`/`asterisk`/`growth_rate` 这类更长的标识符不会被误切。
    """
    def repl(match: re.Match[str]) -> str:
        parts = [p.strip() for p in re.split(r"\s*·\s*", match.group(0))]
        return " · ".join(STATUS_CODE_MAP.get(p, p) for p in parts)

    return STATUS_CHAIN_RE.sub(repl, text)


def _collapse_amount(match: re.Match[str]) -> str:
    """把 9 位以上的原始金额降档为亿元表达。"""
    sign = "-" if match.group(1) == "-" else ""
    digits = match.group(2)
    frac = match.group(3) or "0"
    return f"{sign}{float(f'{digits}.{frac}') / 1e8:,.2f}亿元"


def _cap_decimals(match: re.Match[str]) -> str:
    integral, frac = match.group(1), match.group(2)
    trimmed = frac[:2].rstrip("0")
    return f"{integral}.{trimmed}" if trimmed else integral


def sanitize_public(text: str) -> str:
    """对外正文的唯一净化入口。

    依次处理：
        内部工件名 → 管线描述 → 流程语言 → 状态码 → 内部标识 → 数值精度 → 空白清理

    不做任何事实增删；只把“机器表达”改写为“读者表达”。
    幂等：对已净化文本再跑一次结果不变（词表内的替换目标不会命中任何规则）。
    """
    if not text:
        return text
    # Upstream text may contain escaped or literal markup probes.  Removing
    # executable blocks and presentation tags keeps the reader-facing report
    # clean while preserving ordinary comparison symbols such as "<5%".
    text = HTML_DANGEROUS_BLOCK_RE.sub("", text)
    text = HTML_TAG_RE.sub("", text)
    for token in _FIELD_KEYS_SORTED:
        text = text.replace(token, MACHINE_FIELD_MAP[token])
    for pattern, replacement in PIPELINE_PHRASE_RES:
        text = pattern.sub(replacement, text)
    for pattern, replacement in PROSE_RULES:
        text = pattern.sub(replacement, text)
    text = humanize_status(text)
    text = PAREN_CODE_RE.sub("", text)
    text = BARE_CODE_RE.sub("", text)
    text = HIGH_PRECISION_PCT_RE.sub(lambda m: f"{m.group(1)}.{m.group(2)[:2]}{m.group(3)}", text)
    text = YUAN_AMOUNT_RE.sub(_collapse_amount, text)
    text = BIG_BARE_NUMBER_RE.sub(_collapse_amount, text)
    text = DECIMALS_3PLUS_RE.sub(_cap_decimals, text)
    # 清理删除标识后留下的空括号与孤立标点
    text = re.sub(r"[（(]\s*[)）]", "", text)
    text = re.sub(r"（\s*[；;、,，]", "（", text)
    text = re.sub(r"([；;、,，])\s*[)）]", "）", text)
    text = _WS_RE.sub(" ", text).replace("；。", "。").replace(" 。", "。")
    return text.strip()


# ---------------------------------------------------------------------------
# 词表指纹：供跨模块一致性校验
#
# 后端经 text_rules_loader 加载本文件，skill 脚本直接 import 本文件。
# 双方各自算一次指纹并比对，就能确定「渲染器用的词表」与「审计用的词表」
# 是同一份 —— 这是 2026-09-18 三份词表漂移事故的机械化防线。
# 改任何词表都必须让指纹变化，因此指纹只覆盖表内容，不覆盖函数实现。
# ---------------------------------------------------------------------------
def _table_signature():
    return {
        "MACHINE_FIELD_MAP": dict(sorted(MACHINE_FIELD_MAP.items())),
        "PIPELINE_PHRASE_RES": [[p.pattern, r] for p, r in PIPELINE_PHRASE_RES],
        "PROSE_RULES": [[p.pattern, r] for p, r in PROSE_RULES],
        "STATUS_CODE_MAP": dict(sorted(STATUS_CODE_MAP.items())),
        "FILLER_RES": [p.pattern for p in FILLER_RES],
        "BARE_CODE_RE": BARE_CODE_RE.pattern,
        "PAREN_CODE_RE": PAREN_CODE_RE.pattern,
        "HIGH_PRECISION_PCT_RE": HIGH_PRECISION_PCT_RE.pattern,
        "YUAN_AMOUNT_RE": YUAN_AMOUNT_RE.pattern,
        "BIG_BARE_NUMBER_RE": BIG_BARE_NUMBER_RE.pattern,
        "DECIMALS_3PLUS_RE": DECIMALS_3PLUS_RE.pattern,
        "HTML_DANGEROUS_BLOCK_RE": HTML_DANGEROUS_BLOCK_RE.pattern,
        "HTML_TAG_RE": HTML_TAG_RE.pattern,
    }


RULES_FINGERPRINT: str = hashlib.sha256(
    json.dumps(_table_signature(), ensure_ascii=False, sort_keys=True).encode("utf-8")
).hexdigest()

__all__ = [
    "BARE_CODE_RE",
    "FILLER_RES",
    "HIGH_PRECISION_PCT_RE",
    "HTML_DANGEROUS_BLOCK_RE",
    "HTML_TAG_RE",
    "MACHINE_FIELD_MAP",
    "PAREN_CODE_RE",
    "PIPELINE_PHRASE_RES",
    "PROSE_RULES",
    "RULES_FINGERPRINT",
    "STATUS_CODE_MAP",
    "STATUS_CHAIN_RE",
    "DECIMALS_3PLUS_RE",
    "filler_pattern_index",
    "humanize_status",
    "is_filler",
    "normalize_text",
    "sanitize_public",
    "shingles",
    "similarity",
]


if __name__ == "__main__":  # 自检
    samples = [
        "组件出口均价period_end晚于available_at，存在前视偏差风险。",
        "相关缺口见missing_inputs。",
        "本章dimension_coverage中macro_policy维度为partial的状态一致。",
        "该证据（E-f4a2fbacfb02b33e仅覆盖2023-11-15单点）无法支撑结论。",
        "已披露净利润为-12423798001.78，毛利率5.1848%。",
        "报告由数据解读智能体的结构化结论、图表智能体的已校验图表与章节撰写智能体的七章二十一节正文确定性组装；报告融合智能体不新增事实、不改写数据结论。",
        "研究维度共 5 项；代表项：competition · partial、growth · partial、macro_policy · partial",
        "财务一致性共 4 项，完整明细见质量附录；代表项：unavailable、warning",
        "组件出口均价为2.5534美元/个。",
        "Agent 2 复核后本节保留研究位置，待补充数据后复核。",
        "Agent 7 的输出未通过回填校验。",
        # 边界反例：更长的 ASCII 标识符不得被误切
        "该指标标注为 unsupported，字段 growth_rate 与 asterisk 仅作占位。",
        # 2026-09-18 补齐的字段名与状态取值（交付 HTML 实测原文）
        "不确定性：全部为unaudited、restatement_status为unknown、accounting_standard未提供。",
        "唯一company_level的完整财务序列属于富奥股份，与focus_question指向的发行人不同。",
        "该证据grade为C、caliber为company_level但统计口径写作行业名，结论状态为pending_review。",
        "动力电池销量当月同比数据的unit字段为“未提供”。",
        # 边界反例：`unit`/`grade` 不得切进更长的英文单词
        "字段 upgrade 与 unit_price 仅作占位，community 不受影响。",
        # 同一个字段被写了两遍：中文标签已经在了，英文字段名又被映射成同一个标签。
        # 期望输出里 `数据质量等级` 与 `口径标注` 各只出现一次。
        "数据质量等级grade为C，caliber口径标注缺失。",
    ]
    print(f"RULES_FINGERPRINT = {RULES_FINGERPRINT}\n")
    for s in samples:
        out = sanitize_public(s)
        again = sanitize_public(out)
        flag = "" if again == out else "   ⚠️ 非幂等！"
        print(f"IN : {s}")
        print(f"OUT: {out}{flag}\n")
