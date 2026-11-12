"""Audit an A2 interpretation report against the A2 skills' hard rules.

The rule set comes from the seven skills A2 actually executes in this project
(``agents_core/data-analysis/data_interpreter/skills/*/SKILL.md``), plus
``valuation-context-analysis`` and ``quantitative-validation`` as cross
checks.  All judgements are deterministic and offline: no LLM, no network.

Usage::

    env -u PYTHONPATH python3 scripts/review_a2_with_skills.py \
        --report <interpretation_report.json> \
        --output <A2技能终审报告.md>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT, ROOT / "agents_core", ROOT / "agents_core" / "data-analysis"):
    sys.path.insert(0, str(_path))

from data_interpreter.analysis_guard import (  # noqa: E402
    CURRENT_YTD_MARKERS,
    VALUATION_JUDGEMENT,
    is_row_dump,
    _CURRENT_YEAR,
    _HISTORICAL_YEAR,
    _NUMERIC_TOKEN,
    _TEMPLATE_SENTENCE,
)

SEVERE = "严重"
MEDIUM = "中等"
MINOR = "轻微"
PENDING = "待核实"
PASS = "通过"


def _insights(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Return insight rows as plain dicts."""
    return [r for r in report.get("insights", []) if isinstance(r, dict)]


def _check_attribution(report: dict[str, Any]) -> tuple[str, str, str]:
    """R1: industry-chain-analysis:10,12 -- no name guessing, explicit basis."""
    segs = report.get("industry_chain_segments", []) or []
    problems: list[str] = []
    for seg in segs:
        tier = str(seg.get("source_tier", ""))
        basis = str(seg.get("attribution_basis", ""))
        companies = seg.get("representative_companies", []) or []
        if tier in ("", "industry_common") and companies:
            problems.append(f"{seg.get('stage')} 段有 {len(companies)} 家公司但无审定依据")
        if tier == "gap" and companies:
            problems.append(f"{seg.get('stage')} 段标 gap 却列了公司")
        if tier == "reviewed_profile" and not basis:
            problems.append(f"{seg.get('stage')} 段缺 attribution_basis")
    if not segs:
        return MEDIUM, "无产业链段", "补充三段结构或缺口声明"
    if problems:
        return SEVERE, "；".join(problems), "由 reviewed 结构卡驱动归属，无卡行业输出 gap"
    return PASS, f"{len(segs)} 段均有审定依据或无据留空", "—"


def _check_evidence_loop(report: dict[str, Any]) -> tuple[str, str, str]:
    """R2: industry-chain-analysis:12 / quantitative-validation:14."""
    segs = report.get("industry_chain_segments", []) or []
    seen: dict[str, str] = {}
    duplicates: list[str] = []
    padded = 0
    for seg in segs:
        refs = seg.get("evidence_record_ids", []) or []
        if len(refs) == 10:
            padded += 1
        for rid in refs:
            if rid in seen and seen[rid] != seg.get("stage"):
                duplicates.append(str(rid))
            seen[rid] = str(seg.get("stage"))
    if duplicates:
        return SEVERE, f"{len(duplicates)} 个 record_id 跨段复用", "一条证据只归属一个环节"
    if padded == 3 and all(s.get("source_tier") in ("", "industry_common") for s in segs):
        return SEVERE, "三段均凑满 10 条证据且无审定依据（证据自我循环）", "清空弱证据，改由结构卡或缺口声明"
    return PASS, f"证据 {len(seen)} 条，无跨段复用、无凑数", "—"


def _check_valuation(report: dict[str, Any]) -> tuple[str, str, str]:
    """R3: industry-chain-analysis:14 / tech-hype-vs-fundamentals:8."""
    hits: list[str] = []
    blob = str(report.get("executive_summary", ""))
    for item in _insights(report):
        blob += " " + str(item.get("title", "")) + " " + str(item.get("conclusion", ""))
    for word in VALUATION_JUDGEMENT:
        if word in blob:
            hits.append(word)
    if hits:
        return SEVERE, "命中判断性估值/买卖表述：" + "、".join(sorted(set(hits))), \
            "剥离判断句，仅保留带期间与来源的数值事实"
    return PASS, "无估值/买卖/评级判断", "—"


def _check_period(report: dict[str, Any]) -> tuple[str, str, str]:
    """R4: industry-overview-analysis:12 / macro-cycle-analysis:14."""
    offenders: list[str] = []
    for item in _insights(report):
        blob = str(item.get("title", "")) + " " + str(item.get("conclusion", ""))
        if (_CURRENT_YEAR.search(blob) and _HISTORICAL_YEAR.search(blob)
                and not any(m in blob for m in CURRENT_YTD_MARKERS)):
            offenders.append(str(item.get("insight_id", "?")))
    if offenders:
        return MEDIUM, "当期数据与历史年度并列且未标期间：" + "、".join(offenders), \
            "拆分结论句并标注「当年至今」及统计期间"
    return PASS, "无跨期混用（或已显式标注当期）", "—"


def _check_groups(report: dict[str, Any]) -> tuple[str, str, str]:
    """R5: competitive-landscape-analysis:10 -- no unified cross-group ranking."""
    chain = report.get("chain_analysis") or {}
    if not chain:
        return MEDIUM, "无分组量化分析（chain_analysis 缺失）", \
            "按 comparison_groups 分组计算，跨组只做差值不做统一排名"
    groups = chain.get("groups", {}) or {}
    rules = chain.get("comparison_rules", []) or []
    if len(groups) < 2:
        return MEDIUM, f"仅 {len(groups)} 个分组", "至少两组并保留分组规则"
    if not any("不" in str(r) or "严格区分" in str(r) for r in rules):
        return MEDIUM, "缺少禁止统一排名的比较规则", "写入 comparison_rules"
    return PASS, f"{len(groups)} 组，规则 {len(rules)} 条，跨组仅差值对照", "—"


def _check_titles(report: dict[str, Any]) -> tuple[str, str, str]:
    """R6: SEMANTIC_SYSTEM_PROMPT output contract -- judgement-style titles."""
    offenders: list[str] = []
    for item in _insights(report):
        title = str(item.get("title", ""))
        if len(_NUMERIC_TOKEN.findall(title)) >= 3 or "；" in title:
            offenders.append(str(item.get("insight_id", "?")))
    if offenders:
        return MINOR, "数据串标题：" + "、".join(offenders), "改写为判断句，数值留在 conclusion"
    return PASS, "标题均为判断句", "—"


def _check_summary(report: dict[str, Any]) -> tuple[str, str, str]:
    """R7: executive summary must be a judgement skeleton, not metadata."""
    text = str(report.get("executive_summary", ""))
    head = text[:400]
    templates = len(_TEMPLATE_SENTENCE.findall(head))
    numeric = len(_NUMERIC_TOKEN.findall(head))
    if templates > 1:
        return MINOR, f"前 400 字覆盖度模板句 {templates} 次", "按指标族去重，最多保留 1 条"
    if numeric >= 6:
        return MINOR, f"前 400 字数据串 {numeric} 处（模板句被拦后改用财务行填充）", \
            "压缩为判断句 + 数据限制声明，数值交给关键指标表"
    return PASS, f"前 400 字模板句 {templates} 次、数值串 {numeric} 处", "—"


def _check_conclusions(report: dict[str, Any]) -> tuple[str, str, str]:
    """R10: a conclusion must be a conclusion, not a dump of raw rows."""
    offenders = [
        str(item.get("insight_id", "?"))
        for item in _insights(report)
        if is_row_dump(str(item.get("conclusion", "")))
    ]
    if offenders:
        return MINOR, "结论数据串：" + "、".join(offenders), \
            "保留判断句，逐年数值交给 evidence_record_ids 与关键指标表"
    return PASS, "结论均为判断句", "—"


def _check_evidence_chain(report: dict[str, Any]) -> tuple[str, str, str]:
    """R8: keep the baseline pass items -- complete evidence index."""
    index = report.get("evidence_index", {}) or {}
    dangling = 0
    for item in _insights(report):
        for rid in item.get("evidence_record_ids", []) or []:
            if rid not in index:
                dangling += 1
    if dangling:
        return SEVERE, f"{dangling} 条悬空引用", "修复 record_id 映射"
    return PASS, f"证据索引 {len(index)} 条，0 悬空引用", "—"


def _check_semantic_coverage(report: dict[str, Any]) -> tuple[str, str, str]:
    """R9: an offline deterministic run cannot validate semantic-channel fixes."""
    status = str(report.get("semantic_status", ""))
    if status != "completed":
        return PENDING, (
            f"semantic_status={status!r}；估值/期间/摘要类规则本次只在确定性通道与单元测试中验证"
        ), "用真实 LLM 复跑一次语义通道做端到端确认（会消耗额度）"
    return PASS, "语义通道已执行，内容质量规则已覆盖真实模型输出", "—"


CHECKS = [
    ("R1 产业链归属", "industry-chain-analysis:10,12", _check_attribution),
    ("R2 证据自我循环", "industry-chain-analysis:12 / quantitative-validation:14", _check_evidence_loop),
    ("R3 估值结论越界", "industry-chain-analysis:14 / valuation-context-analysis:12", _check_valuation),
    ("R4 期间切分", "industry-overview-analysis:12 / macro-cycle-analysis:14", _check_period),
    ("R5 分组可比", "competitive-landscape-analysis:10", _check_groups),
    ("R6 洞察标题", "SEMANTIC_SYSTEM_PROMPT 输出契约", _check_titles),
    ("R7 摘要模板句", "industry-overview-analysis + 输出规范", _check_summary),
    ("R8 证据链完整性", "quantitative-validation:14（基线通过项）", _check_evidence_chain),
    ("R9 语义通道覆盖", "审核覆盖边界（非技能规则）", _check_semantic_coverage),
    ("R10 结论数据串", "输出契约：conclusion 应为判断而非数据罗列", _check_conclusions),
]


def audit(report: dict[str, Any]) -> list[dict[str, str]]:
    """Run every rule check.

    Args:
        report: Parsed ``interpretation_report.json``.

    Returns:
        A list of finding dicts with name, rule, verdict, detail, suggestion.
    """
    findings: list[dict[str, str]] = []
    for name, rule, fn in CHECKS:
        verdict, detail, suggestion = fn(report)
        findings.append({
            "name": name, "rule": rule, "verdict": verdict,
            "detail": detail, "suggestion": suggestion,
        })
    return findings


def render_markdown(report_path: Path, report: dict[str, Any],
                    findings: list[dict[str, str]]) -> str:
    """Render the audit as a Markdown report.

    Args:
        report_path: Source report path (recorded for traceability).
        report: Parsed report.
        findings: Results from :func:`audit`.

    Returns:
        Markdown text.
    """
    counts = {level: sum(1 for f in findings if f["verdict"] == level)
              for level in (SEVERE, MEDIUM, MINOR, PENDING, PASS)}
    passed = counts[SEVERE] == 0 and counts[MEDIUM] == 0
    verdict = "通过（语义通道待核实）" if passed and counts[PENDING] else \
        "通过" if passed else "未通过"
    lines = [
        "# A2 技能终审报告", "",
        f"- 生成时间：{datetime.now(timezone.utc).isoformat()}",
        f"- 被审产物：`{report_path}`",
        f"- run subject：{report.get('subject', '')}｜as_of：{report.get('as_of', '')}",
        f"- semantic_status：{report.get('semantic_status', '')}",
        "- 审核依据：A2 实跑的 7 个技能 SKILL.md 硬规则 + valuation-context-analysis / quantitative-validation",
        "", f"## 结论：{verdict}", "",
        f"严重 {counts[SEVERE]} ｜ 中等 {counts[MEDIUM]} ｜ 轻微 {counts[MINOR]} ｜ "
        f"待核实 {counts[PENDING]} ｜ 通过 {counts[PASS]}",
        "",
        "> 待核实项不影响本次判定，但代表审核覆盖边界；上线前应按建议补验。",
        "", "| 检查项 | 技能规则 | 判定 | 依据/发现 | 建议 |", "|---|---|---|---|---|",
    ]
    for f in findings:
        lines.append(f"| {f['name']} | {f['rule']} | {f['verdict']} | "
                     f"{f['detail'].replace('|', '/')} | {f['suggestion']} |")
    lines += ["", "## 判定纪律", "",
              "- 只评审、不改写；每条意见含位置、依据、判定、建议。",
              "- 证据不足标「待核实」，不以模型常识补数。",
              "- 通过门槛：0 严重、0 中等；轻微项记录但不阻断。", ""]
    return "\n".join(lines)


def main() -> int:
    """CLI entry point.

    Returns:
        0 when the audit passes, 1 otherwise.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report = json.loads(args.report.read_text(encoding="utf-8"))
    findings = audit(report)
    markdown = render_markdown(args.report, report, findings)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(markdown, encoding="utf-8")
    print(markdown)
    severe = sum(1 for f in findings if f["verdict"] == SEVERE)
    medium = sum(1 for f in findings if f["verdict"] == MEDIUM)
    return 0 if severe == 0 and medium == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
