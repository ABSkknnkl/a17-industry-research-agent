"""Deterministic readability linting for chapter paragraphs.

Pure, dependency-free rules that flag objectively poor readability. This is the
rule-verifier "anchor" in the 9:1 judge design: it only emits findings and never
decides quality.passed or stage status, so it is safe to run on any paragraph.

Rules map onto the prompt.md v1.3.0 writing rules: R1 <-> rule 16 (double
subject), R2 <-> rule 15 (sentence length), R3 <-> rule 21 (self praise),
R4 <-> rule 20 (jargon stacking), R5 <-> rule 17 (bare-label splicing).
R6/R7 guard against data-pipeline leakage (field names, placeholders, QA logs
leaking into prose); they have no prompt-rule counterpart and are pure detectors.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 句末标点：R4 术语堆砌判断的"单句"边界（一个句号句子）
_SENTENCE_SPLIT = re.compile(r"[。！？；!?]")
# 全部标点：R2 句长判断的"小句"边界（一个标点即一个句子的片段边界）
_CLAUSE_SPLIT = re.compile(r"[。！？；，、：…,.!?;:]")
# 单句（两个标点之间的片段）长度上限。2026-09 用 791 条真实研报句按"一个标点=一个句子"口径重新标定：
# 研报正文小句 87% 落在 30 字以内（其中 78% ≤20 字），30 字是"一口气读完"的自然拐点；
# 超过 30 字且中间无任何标点的片段，读起来即明显费力，报 suggest 提示拆分。
MAX_SENTENCE_CHARS = 30

# R1 双主语 / 句式杂粹
_DOUBLE_SUBJECT_PATTERNS = (
    re.compile(r"由于[^。！？；]{0,30}使其"),
    re.compile(r"由于[^。！？；]{0,30}让"),
    re.compile(r"通过[^。！？；]{0,30}从而"),
    re.compile(r"随着[^。！？；]{0,30}使得"),
    re.compile(r"经过[^。！？；]{0,30}使得"),
    re.compile(r"受到[^。！？；]{0,30}使其"),
    re.compile(r"受到[^。！？；]{0,30}从而"),
)

# R3 自我评价 / 自夸
_SELF_PRAISE = ("本报告深入", "本文严谨", "我们严谨地", "深入剖析")
# R3 句法泛化（红蓝对抗 R2 蓝防，防词表逃逸）："本报告/本文/我们 + 积极修饰
# + 认知动词"的句法模式——自夸换措辞（如"本报告基于严谨方法系统地重构"）
# 绕过词表时由句法模式兜住。逗号允许出现在模式内部（自夸常跨小句）。
_SELF_PRAISE_SYNTAX = re.compile(
    r"(本报告|本文|笔者|我们)[^。！？；]{0,14}"
    r"(严谨|深入|系统|全面|深刻|独家)[^。！？；]{0,10}"
    r"(剖析|解读|梳理|重构|论证|研判|解构|洞察|揭示)"
)

# R4 金融术语词表（堆瘆检测）
_JARGON = (
    "估值锚",
    "利润池",
    "景气度",
    "咽喉节点",
    "护城河",
    "议价权",
    "信用利差",
    "久期",
    "贝塔",
    "阿尔法",
    # 红蓝对抗 R2 蓝防（防术语稀释）：补充电池/材料链高频术语，
    # 使"词表外术语堆砌"攻击面收窄；判定以比例为主、词表为辅。
    "正极",
    "负极",
    "隔膜",
    "电解质",
    "电解液",
    "界面阻抗",
    "离子电导率",
    "干房露点",
    "等静压",
    "固态路线",
    "致密化",
    "量产爬坡",
)
_JARGON_THRESHOLD = 3
# 术语密度比例判定（红蓝对抗 R2 蓝防）：单句术语字数/句长 ≥ 该比例且
# 命中 ≥2 个术语 → 堆砌。比例判定不依赖词表全集，是词表逃逸的兜底。
_JARGON_RATIO_THRESHOLD = 0.25
_JARGON_MIN_HITS_FOR_RATIO = 2

# R5 裸标签拼接：句号后紧跟 2~6 字中文标签 + 冒号
_BARE_LABEL = re.compile(r"。[\u4e00-\u9fa5]{2,6}：")

# R6 字段/占位符泄漏：数据字段名、空值占位符、模板占位符直接透传进正文，未清洗成自然语言。
_FIELD_LEAK_TOKENS = (
    "@值",  # 内部字段后缀（指标@值）
    "@id",  # 内部字段后缀（指标@id）
    "证据编号相关证据",  # 模板占位符未替换
    "未提供",  # 空值占位符
)
# 结构化数组裸贴：Python 列表字面量 ['…'] 直接 dump 进正文（方括号紧跟引号）
_ARRAY_LITERAL = re.compile(r"\['[^\]]*\]")

# R7 内部质检信息泄漏：shift 异常检测等内部质检日志透传进正文，非正文内容。
_QA_LEAK_TOKENS = (
    "shift异常检测",
    "超出突变阈值",
    "基线区间",
    "CRITICAL",
)

# R8 假靶子/空泛因果句式：先立一个"不必立"的前提再强调，或堆砌"极其显著"式空泛因果强调。
# 借鉴"不是A而是B"三毒 + 高频堆叠副词，剔除外延到研报客观文体。命中即必须改写为直接陈述。
_FALSE_TARGET_PATTERNS = (
    re.compile(r"值得强调的是"),
    re.compile(r"值得注意的是"),
    re.compile(r"毋庸置疑"),
    re.compile(r"显而易见"),
    re.compile(r"毋庸置疑的是"),
    re.compile(r"真正的(重点|关键|本质)在于"),
)

# R9 空泛结论/修饰堆叠词表：空洞积极结论、重要性膨胀、三段式排比无实义。
# 借鉴 Humanizer"空泛积极结论/重要性膨胀/三段式列举"，只保留研报里无信息量的高频空话。
_EMPTY_CONCLUSION_TOKENS = (
    "未来可期",
    "前景广阔",
    "意义重大",
    "影响深远",
    "发展迅猛",
    "势头强劲",
    "值得期待",
    "持续向好",
)

# R10 自问自答老师腔 + 空泛连接词：研报不该用"这说明什么？"制造悬念，也不该堆"此外/然而/因此"。
# 借鉴"自问自答老师腔" + "连接词过度"。只报 suggest，交由 LLM 软分综合判断。
_RHETORICAL_QUESTION = re.compile(r"(这说明|这意味着|这意味着什么|这说明什么)[？?]")
_EMPTY_CONNECTORS = ("此外", "综上所述", "总的来说", "总而言之", "由此可见")
_CONNECTOR_THRESHOLD = 2  # 单段空泛连接词 ≥2 报堆叠

# R11 数字洪水（红蓝对抗 R2 蓝防，新增规则；R6 已被字段泄漏占用）：
# 单句堆 ≥5 个数值且无任何解读词，读者只见数字不见结论。
_NUMERIC_TOKEN = re.compile(
    r"\d+(?:\.\d+)?\s*(?:%|‰|亿|万|千|元|吨|GW|MW|GWh|TWh|家|个|台|次|k)?"
)
_NUMERIC_FLOOD_COUNT = 5
_NUMERIC_INTERPRET_WORDS = (
    "表明", "说明", "意味着", "反映", "其中", "分别",
    "带动", "驱动", "同比", "环比", "增速", "占比",
)


@dataclass(frozen=True, slots=True)
class LintFinding:
    rule_id: str
    dimension: str  # 通顺度 / 俗通度 / 连贯性 / 客观性
    severity: str  # must_fix / suggest
    reason: str
    snippet: str


def lint_paragraph(text: str, *, kind: str = "analysis") -> list[LintFinding]:
    findings: list[LintFinding] = []
    findings.extend(_check_double_subject(text))
    findings.extend(_check_sentence_length(text))
    findings.extend(_check_self_praise(text))
    findings.extend(_check_jargon_stack(text))
    findings.extend(_check_bare_label(text))
    findings.extend(_check_field_leak(text))
    findings.extend(_check_qa_leak(text))
    findings.extend(_check_false_target(text))
    findings.extend(_check_empty_conclusion(text))
    findings.extend(_check_ai_rhetoric(text))
    findings.extend(_check_numeric_flood(text))
    return findings


def _check_double_subject(text: str) -> list[LintFinding]:
    for pattern in _DOUBLE_SUBJECT_PATTERNS:
        match = pattern.search(text)
        if match:
            return [
                LintFinding(
                    rule_id="R1_DOUBLE_SUBJECT",
                    dimension="通顺度",
                    severity="must_fix",
                    reason="双主语/句式杂粹，主谓搭配混乱",
                    snippet=match.group(0),
                )
            ]
    return []


def _check_sentence_length(text: str) -> list[LintFinding]:
    for sentence in _CLAUSE_SPLIT.split(text):
        sentence = sentence.strip()
        if len(sentence) > MAX_SENTENCE_CHARS:
            return [
                LintFinding(
                    rule_id="R2_SENTENCE_TOO_LONG",
                    dimension="通顺度",
                    severity="suggest",
                    reason=f"单句超过{MAX_SENTENCE_CHARS}字，应拆分",
                    snippet=sentence[:20] + "…",
                )
            ]
    # 注：红蓝对抗 R2 曾尝试"去重字比例"信息密度规则防重复填充垃圾句，
    # 实测被数据否决——真实研报枚举句（负极材料包括碳基和非碳基材料…）
    # 的密度（0.45~0.55）反而低于对抗样本（0.705），该代理指标会误杀
    # 合法文体。重复填充按方案 §4.1 分流原则移交 judge 软判（prompt 指引）。
    return []


def _check_self_praise(text: str) -> list[LintFinding]:
    for phrase in _SELF_PRAISE:
        if phrase in text:
            return [
                LintFinding(
                    rule_id="R3_SELF_PRAISE",
                    dimension="客观性",
                    severity="must_fix",
                    reason="包含自我评价/自夸语句",
                    snippet=phrase,
                )
            ]
    # R3 句法泛化（红蓝对抗 R2 蓝防）：自夸换措辞绕过词表时由句法模式兜住。
    match = _SELF_PRAISE_SYNTAX.search(text)
    if match:
        return [
            LintFinding(
                rule_id="R3_SELF_PRAISE",
                dimension="客观性",
                severity="must_fix",
                reason="自我评价/自夸句法模式（报告主体+积极修饰+认知动词）",
                snippet=match.group(0)[:30],
            )
        ]
    return []


def _check_jargon_stack(text: str) -> list[LintFinding]:
    for sentence in _SENTENCE_SPLIT.split(text):
        hits = [term for term in _JARGON if term in sentence]
        if len(hits) >= _JARGON_THRESHOLD:
            return [
                LintFinding(
                    rule_id="R4_JARGON_STACK",
                    dimension="俗通度",
                    severity="suggest",
                    reason=f"单句堆瘆{len(hits)}个专业术语且未解释",
                    snippet="、".join(hits),
                )
            ]
        # R4 比例判定（红蓝对抗 R2 蓝防，防术语稀释）：术语字数占句长比例
        # 过高即堆砌——不依赖词表全集，词表外术语密集也由密度兜住。
        if len(hits) >= _JARGON_MIN_HITS_FOR_RATIO and len(sentence) > 0:
            jargon_chars = sum(sentence.count(term) * len(term) for term in hits)
            ratio = jargon_chars / len(sentence)
            if ratio >= _JARGON_RATIO_THRESHOLD:
                return [
                    LintFinding(
                        rule_id="R4_JARGON_STACK",
                        dimension="俗通度",
                        severity="suggest",
                        reason=f"单句术语密度{ratio:.0%}（{len(hits)}个术语），堆砌且未解释",
                        snippet="、".join(hits),
                    )
                ]
    return []


def _check_bare_label(text: str) -> list[LintFinding]:
    match = _BARE_LABEL.search(text)
    if match:
        return [
            LintFinding(
                rule_id="R5_BARE_LABEL",
                dimension="连贯性",
                severity="suggest",
                reason="用裸标签机械拼接句子，缺少逻辑衔接",
                snippet=match.group(0),
            )
        ]
    return []


def _check_field_leak(text: str) -> list[LintFinding]:
    for token in _FIELD_LEAK_TOKENS:
        if token in text:
            return [
                LintFinding(
                    rule_id="R6_FIELD_LEAK",
                    dimension="连贯性",
                    severity="must_fix",
                    reason=f"数据字段名/占位符泄漏进正文（{token}），未清洗成自然语言",
                    snippet=token,
                )
            ]
    match = _ARRAY_LITERAL.search(text)
    if match:
        return [
            LintFinding(
                rule_id="R6_FIELD_LEAK",
                dimension="连贯性",
                severity="must_fix",
                reason="结构化数组裸贴进正文（['…']），未转成自然语言",
                snippet=match.group(0)[:20] + "…",
            )
        ]
    return []


def _check_qa_leak(text: str) -> list[LintFinding]:
    for token in _QA_LEAK_TOKENS:
        if token in text:
            return [
                LintFinding(
                    rule_id="R7_QA_LEAK",
                    dimension="客观性",
                    severity="must_fix",
                    reason=f"内部质检信息泄漏进正文（{token}），非正文内容",
                    snippet=token,
                )
            ]
    return []


def _check_false_target(text: str) -> list[LintFinding]:
    for pattern in _FALSE_TARGET_PATTERNS:
        match = pattern.search(text)
        if match:
            return [
                LintFinding(
                    rule_id="R8_FALSE_TARGET",
                    dimension="客观性",
                    severity="must_fix",
                    reason="空泛强调/假靶子句式，缺少实质信息，应改为直接陈述",
                    snippet=match.group(0),
                )
            ]
    return []


def _check_empty_conclusion(text: str) -> list[LintFinding]:
    hits = [token for token in _EMPTY_CONCLUSION_TOKENS if token in text]
    if hits:
        return [
            LintFinding(
                rule_id="R9_EMPTY_CONCLUSION",
                dimension="客观性",
                severity="suggest",
                reason="空泛结论/修饰堆叠，无量化或事实支撑，应给出具体依据",
                snippet="、".join(hits),
            )
        ]
    return []


def _check_ai_rhetoric(text: str) -> list[LintFinding]:
    q_match = _RHETORICAL_QUESTION.search(text)
    if q_match:
        return [
            LintFinding(
                rule_id="R10_AI_RHETORIC",
                dimension="客观性",
                severity="suggest",
                reason="自问自答老师腔，制造悬念但无实质信息，应直接陈述",
                snippet=q_match.group(0),
            )
        ]
    connector_hits = [c for c in _EMPTY_CONNECTORS if c in text]
    if len(connector_hits) >= _CONNECTOR_THRESHOLD:
        return [
            LintFinding(
                rule_id="R10_AI_RHETORIC",
                dimension="连贯性",
                severity="suggest",
                reason="空泛连接词堆叠，读感机械",
                snippet="、".join(connector_hits),
            )
        ]
    return []


def _check_numeric_flood(text: str) -> list[LintFinding]:
    """R11 数字洪水（红蓝对抗 R2 蓝防新增）：单句堆 ≥5 个数值且无解读词。"""

    for sentence in _SENTENCE_SPLIT.split(text):
        sentence = sentence.strip()
        if not sentence:
            continue
        numbers = _NUMERIC_TOKEN.findall(sentence)
        if len(numbers) < _NUMERIC_FLOOD_COUNT:
            continue
        if any(word in sentence for word in _NUMERIC_INTERPRET_WORDS):
            continue
        return [
            LintFinding(
                rule_id="R11_NUMERIC_FLOOD",
                dimension="通俗度",
                severity="suggest",
                reason=f"单句堆叠{len(numbers)}个数值且无解读，读者只见数字不见结论",
                snippet=sentence[:20] + "…",
            )
        ]
    return []
