"""P-10 下游收口：A4 只能引用 A2 已核验的净现比，禁止自行用合并净利润重算。

A2 的输出契约（`financial_ratios[*]`）：
- `cash_to_net_profit`：已按「经营活动现金流 / 归母净利润」计算并限幅的倍数；
- `calculations.cash_to_net_profit.denominator_metric`：必须是 `parent_net_profit`；
- `calculations.cash_to_net_profit.input_record_ids`：分子/分母两条证据。

本模块做两件事：
1. 生成前：把「可引用 / 不可用」清单塞进章节上下文，明确禁止用合并净利润自算；
2. 落盘前：扫描正文、要点、指标卡与对比表，发现自算或口径不符的净现比断言，
   当场改写为缺口句（或删除指标卡），并把修正写入 `content_audit`。
"""
from __future__ import annotations

import re
from typing import Any, Iterable

GAP_CLAUSE = "缺少同口径归母净利润，净现比无法计算"
REQUIRED_DENOMINATOR = "parent_net_profit"

_RATIO_NUMBER = re.compile(
    r"净现比\s*(?:约|为|达|仅|达到|接近|超过|是)?\s*([-+]?\d+(?:\.\d+)?)\s*倍?"
)
_ANY_NUMBER = re.compile(r"([-+]?\d+(?:\.\d+)?)")
_PERIOD_YEAR = re.compile(r"(20\d{2})\s*年")


def _as_dict(value: Any) -> dict:
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else dict(value or {})


def build_net_cash_ratio_policy(report: Any) -> dict[str, Any]:
    """从 A2 报告提取「可引用的净现比」与「缺口公司」清单。

    只在主体、期间、证据、口径都明确时才判定为可用；其余一律按缺口处理，
    防止旧产物缺 `denominator_metric` 时被当成有效值。
    """
    evidence_index = _as_dict(report).get("evidence_index") or {}
    verified: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for row in _as_dict(report).get("financial_ratios") or []:
        row = _as_dict(row)
        company = str(row.get("company") or "").strip()
        if not company:
            continue
        calculation = (row.get("calculations") or {}).get("cash_to_net_profit") or {}
        value = row.get("cash_to_net_profit")
        denominator = calculation.get("denominator_metric")
        input_ids = [str(rid) for rid in calculation.get("input_record_ids") or []]
        period = calculation.get("period_end") or row.get("period_end")
        evidence_ok = bool(input_ids) and all(rid in evidence_index for rid in input_ids)
        if (isinstance(value, (int, float)) and not isinstance(value, bool)
                and denominator == REQUIRED_DENOMINATOR and evidence_ok):
            verified.append({
                "company": company,
                "period": str(period or ""),
                "value": round(float(value), 2),
                "unit": "倍",
                "denominator_metric": denominator,
                "evidence_ids": input_ids,
            })
        else:
            missing.append({
                "company": company,
                "reason": row.get("period_warning") or "缺少同口径归母净利润",
            })
    return {
        "verified": verified,
        "missing": missing,
        "prompt": format_policy_prompt(verified, missing),
    }


def format_policy_prompt(verified: list[dict[str, Any]], missing: list[dict[str, Any]]) -> str:
    lines = ["净现比（经营活动现金流 / 归母净利润）口径（强制）："]
    if verified:
        lines.append("- 只能原样引用下列已核验结果，不得自行相除或改用合并净利润：")
        for item in verified:
            ids = "、".join(item["evidence_ids"])
            lines.append(f"  * {item['company']} {item['period']} = {item['value']:.2f} 倍（证据：{ids}）。")
    else:
        lines.append("- 本次没有任何已核验的净现比可引用。")
    if missing:
        names = "、".join(item["company"] for item in missing)
        lines.append(f"- 以下公司缺少同口径归母净利润：{names}；"
                     f"只能写「{GAP_CLAUSE}」，不得给出倍数。")
    lines.append("- 缺值时仍可分别描述有证据支持的经营现金流与净利润，但不得把两者相除得出净现比。")
    return "\n".join(lines)


def _split_keep(text: str, pattern: str) -> list[str]:
    parts = re.split(pattern, text)
    return [part for part in parts if part]


def _company_in(text: str, policy: dict[str, Any]) -> str | None:
    names = [item["company"] for item in policy["verified"]] + [item["company"] for item in policy["missing"]]
    hits = [name for name in names if name and name in text]
    return max(hits, key=len) if hits else None


def _verified_for(claimed: float, company: str | None, policy: dict[str, Any],
                  text: str = "") -> dict[str, Any] | None:
    years = set(_PERIOD_YEAR.findall(text or ""))
    for item in policy["verified"]:
        if company and item["company"] != company:
            continue
        item_year = str(item.get("period") or "")[:4]
        # 正文只提一个年份时，必须与该核验值的期间一致；多年份表述不强行绑定。
        if len(years) == 1 and item_year and item_year not in years:
            continue
        if abs(claimed - float(item["value"])) <= 0.005:
            return item
    return None


def _rewrite_text(text: str, policy: dict[str, Any]) -> tuple[str, list[dict[str, Any]], list[str]]:
    """按小句改写净现比断言；返回新文本、修正记录、命中的证据 ID。"""
    if not text or "净现比" not in text:
        return text, [], []
    corrections: list[dict[str, Any]] = []
    cited: list[str] = []
    output: list[str] = []
    for sentence in _split_keep(text, r"(?<=[。；;\n])"):
        if "净现比" not in sentence:
            output.append(sentence)
            continue
        company = _company_in(sentence, policy) or _company_in(text, policy)
        clauses = _split_keep(sentence, r"(?<=[，,])")
        rebuilt: list[str] = []
        for clause in clauses:
            if "净现比" not in clause:
                rebuilt.append(clause)
                continue
            match = _RATIO_NUMBER.search(clause)
            numbers = [float(match.group(1))] if match else [float(n) for n in _ANY_NUMBER.findall(clause)]
            if not numbers:
                rebuilt.append(clause)
                continue
            verified = next((item for item in (_verified_for(value, company, policy, clause) for value in numbers) if item), None)
            if verified:
                rebuilt.append(clause)
                cited.extend(verified["evidence_ids"])
                continue
            replacement = f"{company}{GAP_CLAUSE}" if company else GAP_CLAUSE
            corrections.append({
                "code": "net_cash_ratio_correction",
                "location": "",
                "claim": clause.strip(),
                "disposition": "corrected",
                "reason": "A2 无同口径归母净利润净现比，禁止自行计算或改用合并净利润",
            })
            rebuilt.append(replacement)
        output.append("".join(rebuilt))
    return "".join(output), corrections, list(dict.fromkeys(cited))


def _rewrite_list(values: Iterable[str], policy: dict[str, Any], location: str,
                  corrections: list[dict[str, Any]]) -> list[str]:
    rewritten = []
    for value in values:
        text, items, _ = _rewrite_text(str(value), policy)
        for item in items:
            item["location"] = location
            corrections.append(item)
        rewritten.append(text)
    return rewritten


def _card_is_unverified(card: Any, policy: dict[str, Any]) -> bool:
    label = str(_as_dict(card).get("label") or "")
    value = str(_as_dict(card).get("value") or "")
    company = _company_in(f"{label}{value}", policy)
    if "净现比" not in label and "净现比" not in value:
        return False
    if "无法计算" in value or GAP_CLAUSE in value:
        return False
    numbers = [float(n) for n in _ANY_NUMBER.findall(value)]
    return not any(_verified_for(number, company, policy) for number in numbers)


def _rewrite_table(table: Any, policy: dict[str, Any], location: str,
                   corrections: list[dict[str, Any]]) -> None:
    columns = list(getattr(table, "columns", []) or [])
    rows = list(getattr(table, "rows", []) or [])
    ratio_columns = [index for index, name in enumerate(columns) if "净现比" in str(name)]
    if not ratio_columns:
        return
    for row in rows:
        if not isinstance(row, list):
            continue
        company = str(row[0]).strip() if row else ""
        for index in ratio_columns:
            if index >= len(row):
                continue
            cell = str(row[index])
            if "无法计算" in cell or GAP_CLAUSE in cell:
                continue
            numbers = [float(n) for n in _ANY_NUMBER.findall(cell)]
            verified = next((item for item in (_verified_for(value, company, policy, cell) for value in numbers) if item), None)
            if verified:
                continue
            corrections.append({
                "code": "net_cash_ratio_correction",
                "location": f"{location}.comparison_table",
                "claim": f"{columns[index]}={cell}",
                "disposition": "corrected",
                "reason": "A2 无同口径归母净利润净现比，禁止自行计算或改用合并净利润",
            })
            row[index] = GAP_CLAUSE


def apply_net_cash_ratio_guard(chapters: list[Any], policy: dict[str, Any]) -> list[dict[str, Any]]:
    """落盘前统一校正章节里的净现比断言，返回修正清单（同时写入 content_audit）。"""
    corrections: list[dict[str, Any]] = []
    for chapter in chapters:
        chapter_start = len(corrections)
        chapter.summary, items, cited = _rewrite_text(str(getattr(chapter, "summary", "") or ""), policy)
        for item in items:
            item["location"] = f"{chapter.chapter_id}.summary"
            corrections.append(item)
        if cited and not getattr(chapter, "evidence_ids", []):
            chapter.evidence_ids = cited
        for section in chapter.sections:
            section.key_points = _rewrite_list(section.key_points, policy, section.section_id, corrections)
            section.uncertainties = _rewrite_list(section.uncertainties, policy, section.section_id, corrections)
            if getattr(section, "callouts", None):
                for callout in section.callouts:
                    title, items, _ = _rewrite_text(str(getattr(callout, "title", "") or ""), policy)
                    text, text_items, cited = _rewrite_text(str(getattr(callout, "text", "") or ""), policy)
                    callout.title, callout.text = title, text
                    for item in [*items, *text_items]:
                        item["location"] = f"{section.section_id}.callout"
                        corrections.append(item)
                    if cited:
                        callout.evidence_ids = list(dict.fromkeys([*callout.evidence_ids, *cited]))
            for paragraph in section.paragraphs:
                text, items, cited = _rewrite_text(paragraph.text, policy)
                paragraph.text = text
                for item in items:
                    item["location"] = paragraph.paragraph_id
                    corrections.append(item)
                if cited:
                    paragraph.evidence_ids = list(dict.fromkeys([*paragraph.evidence_ids, *cited]))
            if section.metric_cards:
                kept = []
                for card in section.metric_cards:
                    if _card_is_unverified(card, policy):
                        corrections.append({
                            "code": "net_cash_ratio_correction",
                            "location": f"{section.section_id}.metric_card",
                            "claim": f"{card.label}={card.value}",
                            "disposition": "removed",
                            "reason": "指标卡净现比无 A2 核验值",
                        })
                        continue
                    kept.append(card)
                section.metric_cards = kept
            if section.comparison_table is not None:
                _rewrite_table(section.comparison_table, policy, section.section_id, corrections)
        if len(corrections) > chapter_start:
            chapter.content_audit = [*chapter.content_audit, *corrections[chapter_start:]]
    return corrections
