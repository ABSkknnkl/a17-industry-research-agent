"""Deterministic readability linting for chapter paragraphs.

Pure, dependency-free rules that flag objectively poor readability. This is the
rule-verifier "anchor" in the 9:1 judge design: it only emits findings and never
decides quality.passed or stage status, so it is safe to run on any paragraph.

Rules map onto the prompt.md v1.1.0 writing rules: R1 <-> rule 16 (double
subject), R2 <-> rule 15 (sentence length), R3 <-> rule 21 (self praise),
R4 <-> rule 20 (jargon stacking), R5 <-> rule 17 (bare-label splicing).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 中文句末标点切分
_SENTENCE_SPLIT = re.compile(r"[。！？；!?]")
MAX_SENTENCE_CHARS = 45

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

# R4 金融术语词表（堆瘆检测）
_JARGON = (
    "估值锚", "利润池", "景气度", "咽喉节点", "护城河",
    "议价权", "信用利差", "久期", "贝塔", "阿尔法",
)
_JARGON_THRESHOLD = 3

# R5 裸标签拼接：句号后紧跟 2~6 字中文标签 + 冒号
_BARE_LABEL = re.compile(r"。[\u4e00-\u9fa5]{2,6}：")


@dataclass(frozen=True, slots=True)
class LintFinding:
    rule_id: str
    dimension: str   # 通顺度 / 俗通度 / 连贯性 / 客观性
    severity: str    # must_fix / suggest
    reason: str
    snippet: str


def lint_paragraph(text: str, *, kind: str = "analysis") -> list[LintFinding]:
    findings: list[LintFinding] = []
    findings.extend(_check_double_subject(text))
    findings.extend(_check_sentence_length(text))
    findings.extend(_check_self_praise(text))
    findings.extend(_check_jargon_stack(text))
    findings.extend(_check_bare_label(text))
    return findings


def _check_double_subject(text: str) -> list[LintFinding]:
    for pattern in _DOUBLE_SUBJECT_PATTERNS:
        match = pattern.search(text)
        if match:
            return [LintFinding(
                rule_id="R1_DOUBLE_SUBJECT", dimension="通顺度", severity="must_fix",
                reason="双主语/句式杂粹，主谓搭配混乱", snippet=match.group(0),
            )]
    return []


def _check_sentence_length(text: str) -> list[LintFinding]:
    for sentence in _SENTENCE_SPLIT.split(text):
        sentence = sentence.strip()
        if len(sentence) > MAX_SENTENCE_CHARS:
            return [LintFinding(
                rule_id="R2_SENTENCE_TOO_LONG", dimension="通顺度", severity="suggest",
                reason=f"单句超过{MAX_SENTENCE_CHARS}字，应拆分", snippet=sentence[:20] + "…",
            )]
    return []


def _check_self_praise(text: str) -> list[LintFinding]:
    for phrase in _SELF_PRAISE:
        if phrase in text:
            return [LintFinding(
                rule_id="R3_SELF_PRAISE", dimension="客观性", severity="must_fix",
                reason="包含自我评价/自夸语句", snippet=phrase,
            )]
    return []


def _check_jargon_stack(text: str) -> list[LintFinding]:
    for sentence in _SENTENCE_SPLIT.split(text):
        hits = [term for term in _JARGON if term in sentence]
        if len(hits) >= _JARGON_THRESHOLD:
            return [LintFinding(
                rule_id="R4_JARGON_STACK", dimension="俗通度", severity="suggest",
                reason=f"单句堆瘆{len(hits)}个专业术语且未解释", snippet="、".join(hits),
            )]
    return []


def _check_bare_label(text: str) -> list[LintFinding]:
    match = _BARE_LABEL.search(text)
    if match:
        return [LintFinding(
            rule_id="R5_BARE_LABEL", dimension="连贯性", severity="suggest",
            reason="用裸标签机械拼接句子，缺少逻辑衔接", snippet=match.group(0),
        )]
    return []
