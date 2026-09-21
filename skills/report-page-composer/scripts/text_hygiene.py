#!/usr/bin/env python3
"""Pre-render text hygiene audit for report-page-composer (shift-left gate).

The render-time audit (scripts/audit_render.py) catches what is *visible*.
This script catches what should never have been written into the page plan in
the first place: duplicated paragraphs, internal pipeline vocabulary,
audit-grade numeric precision, and template filler in the public reading layer.

Run it on the content inventory produced in step 1 of the skill workflow,
before page composition and before rendering.

Usage:
    python3 scripts/text_hygiene.py inventory.json [--out hygiene.json]
                                                 [--json] [--quiet]
    python3 scripts/text_hygiene.py plan.json --text-field body

Accepted input shapes (auto-detected):
    {"facts":   [{"id": ..., "chapter": ..., "kind": ..., "body": ...}, ...]}
    {"blocks":  [...]}
    {"items":   [...]}
    [ {...}, {...} ]

Exit codes:
    0  no critical or major issue
    1  at least one critical or major issue
    2  bad input
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from text_rules import (  # noqa: E402
    BARE_CODE_RE,
    FILLER_RES,
    MACHINE_FIELD_MAP,
    PAREN_CODE_RE,
    PIPELINE_PHRASE_RES,
    STATUS_CODE_MAP,
    filler_pattern_index,
    is_filler,
    normalize_text,
    sanitize_public,
    similarity,
)
from audit_render import (  # noqa: E402
    AGENT_RE,
    ASCII_PIPELINE_FRAGMENT_RE,
    DUPLICATE_MIN_LEN,
    DUPLICATE_SIMILARITY,
    HIGH_PRECISION_PLAIN_RE,
    HIGH_PRECISION_RE,
    INTERNAL_ID_RE,
    LONG_INT_RE,
    SNAKE_CASE_RE,
    summarize,
)

PIPELINE_NAMES = tuple(sorted(MACHINE_FIELD_MAP, key=len))
_normalize = normalize_text
_similarity = similarity

TEXT_FIELDS = ("body", "text", "content", "paragraph", "summary", "value")
ID_FIELDS = ("id", "block_id", "fact_id", "para", "paragraph_id")



def _text_of(item: dict[str, Any], field: str | None) -> str:
    if field:
        return str(item.get(field) or "")
    for name in TEXT_FIELDS:
        value = item.get(name)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _id_of(item: dict[str, Any], fallback: str) -> str:
    for name in ID_FIELDS:
        value = item.get(name)
        if isinstance(value, (str, int)) and str(value).strip():
            return str(value)
    return fallback


def _collect(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [i for i in payload if isinstance(i, dict)]
    if isinstance(payload, dict):
        for key in ("facts", "blocks", "items", "paragraphs", "content", "sections"):
            value = payload.get(key)
            if isinstance(value, list):
                return [i for i in value if isinstance(i, dict)]
    return []


class Hygiene:
    def __init__(self, items: list[dict[str, Any]], field: str | None) -> None:
        self.items = items
        self.field = field
        self.issues: list[dict[str, Any]] = []
        self._prepared: list[tuple[str, str, str, str]] = []
        self._filler_seen: dict[int, int] = {}
        for idx, item in enumerate(items):
            raw = _text_of(item, field)
            self._prepared.append(
                (
                    _id_of(item, f"item-{idx + 1}"),
                    str(item.get("chapter") or ""),
                    _normalize(raw),
                    raw.strip(),
                )
            )

    def add(self, item_id: str, chapter: str, code: str, severity: str,
            confidence: float, evidence: str, fix: str,
            action: str) -> None:
        self.issues.append(
            {
                "item_id": item_id,
                "chapter": chapter or None,
                "issue_code": code,
                "severity": severity,
                "confidence": round(confidence, 2),
                "evidence": evidence,
                "fix_action": fix,
                "editorial_action": action,
                "recheck_status": "pending",
            }
        )

    def run(self) -> list[dict[str, Any]]:
        # 1. 逐条检查
        for item_id, chapter, norm, raw in self._prepared:
            if not raw:
                self.add(item_id, chapter, "EMPTY_BODY", "major", 0.99,
                         "内容条目正文为空，只保留了 ID", "删除该条目或补齐正文。",
                         "omit_from_public")
                continue

            hits: list[str] = [name for name in PIPELINE_NAMES if name in raw]
            m = AGENT_RE.search(raw)
            if m:
                hits.append(m.group(0))
            m = INTERNAL_ID_RE.search(raw)
            if m:
                hits.append(m.group(0))
            hits += [t for t in SNAKE_CASE_RE.findall(raw) if len(t) >= 6]
            m = ASCII_PIPELINE_FRAGMENT_RE.search(raw)
            if m:
                hits.append(m.group(0))
            if hits:
                self.add(item_id, chapter, "MACHINE_FIELD_IN_BODY", "major", 0.95,
                         f"正文含内部工件标识 {sorted(set(hits))}：「{raw[:70]}」",
                         "改写为读者可读的业务表述；整句口径说明下沉到内部审计附录。",
                         "rewrite")

            long_ints = LONG_INT_RE.findall(raw)
            hi_prec = HIGH_PRECISION_RE.findall(raw) + HIGH_PRECISION_PLAIN_RE.findall(raw)
            if long_ints or hi_prec:
                self.add(item_id, chapter, "PRECISION_OVERFLOW", "major", 0.9,
                         f"超精度数值 整数位={long_ints[:2]} 高精度={hi_prec[:2]}：「{raw[:70]}」",
                         "正文统一到业务精度：金额改亿元/万元并千分位，比率 2 位小数；"
                         "审计级精度下沉附录。",
                         "rewrite")

            filler_idx = filler_pattern_index(raw)
            if filler_idx is not None:
                self._filler_seen[filler_idx] = self._filler_seen.get(filler_idx, 0) + 1
                # 第 1 次出现是正常结论；第 2 次起才是逐章复制的空话模板
                if self._filler_seen[filler_idx] > 1:
                    self.add(item_id, chapter, "TEMPLATE_FILLER", "major", 0.9,
                             f"「{FILLER_RES[filler_idx].pattern}」句式第 {self._filler_seen[filler_idx]} 次出现"
                             f"（同一句式全文只应保留一次）：「{raw[:64]}」",
                             "同一“无数据可判”结论在全文只保留首次完整表达，其余并入覆盖矩阵的一行；"
                             "禁止逐章复制同一句式撑版面。",
                             "deduplicate")

        # 2. 跨条目重复
        reported: set[tuple[int, int]] = set()
        for i in range(len(self._prepared)):
            for j in range(i + 1, len(self._prepared)):
                if (i, j) in reported:
                    continue
                ida, cha, na, rawa = self._prepared[i]
                idb, chb, nb, rawb = self._prepared[j]
                if len(na) < DUPLICATE_MIN_LEN or len(nb) < DUPLICATE_MIN_LEN:
                    continue
                sim = _similarity(na, nb)
                if sim < DUPLICATE_SIMILARITY:
                    continue
                reported.add((i, j))
                scope = "同章" if cha == chb else "跨章"
                self.add(
                    idb, chb, "DUPLICATE_TEXT", "major", 0.93,
                    f"{scope}重复：{ida} 与 {idb} 相似度 {sim:.2f}（原样重复={na == nb}）："
                    f"「{rawb[:60]}」",
                    "保留首次完整表达，后者改为短引导或内部交叉引用；"
                    "两处都是唯一事实时合并为一个条目并保留全部事实 ID。",
                    "deduplicate",
                )

        order = {"critical": 0, "major": 1, "minor": 2, "suggestion": 3}
        self.issues.sort(key=lambda x: (order.get(x["severity"], 9), x["item_id"]))
        return self.issues


def build_fixed_payload(payload: Any, items: list[dict[str, Any]], field: str | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """产出净化后的清单：数值精度降档、内部标识改写、重复与空话条目合并。

    合并掉的条目不会静默消失，而是写入 content_dispositions，
    供 PageCompositionPlan 的内容追溯校验使用。
    """
    seen_norm: dict[str, str] = {}
    seen_filler: set[int] = set()
    dispositions: list[dict[str, Any]] = []
    out_items: list[dict[str, Any]] = []

    for idx, item in enumerate(items):
        fixed = dict(item)
        raw = _text_of(item, field)
        item_id = _id_of(item, f"item-{idx + 1}")
        if raw:
            cleaned = sanitize_public(PAREN_CODE_RE.sub("", raw))
            key = normalize_text(cleaned)
            if len(key) >= DUPLICATE_MIN_LEN and key in seen_norm:
                dispositions.append({
                    "content_id": item_id,
                    "action": "deduplicate",
                    "merged_into": seen_norm[key],
                    "note": "与已保留条目正文归一后重复，合并为单一条目。",
                })
                continue
            # 空话模板按“句式”归并，而不是按原文：同一句式换个主语也算重复
            filler_idx = filler_pattern_index(cleaned)
            if filler_idx is not None and filler_idx in seen_filler:
                dispositions.append({
                    "content_id": item_id,
                    "action": "deduplicate",
                    "merged_into": "COVERAGE-MATRIX",
                    "note": f"空话模板句式 #{filler_idx} 全文只保留一次，其余并入覆盖矩阵。",
                })
                continue
            if filler_idx is not None:
                seen_filler.add(filler_idx)
            if len(key) >= DUPLICATE_MIN_LEN:
                seen_norm[key] = item_id
            for name in TEXT_FIELDS:
                if isinstance(fixed.get(name), str):
                    fixed[name] = sanitize_public(PAREN_CODE_RE.sub("", fixed[name]))
        out_items.append(fixed)

    if isinstance(payload, dict):
        fixed_payload = dict(payload)
        for key in ("facts", "blocks", "items", "paragraphs", "content", "sections"):
            if isinstance(fixed_payload.get(key), list):
                fixed_payload[key] = out_items
                break
        else:
            fixed_payload = {"items": out_items}
        if dispositions:
            fixed_payload["content_dispositions"] = dispositions
    else:
        fixed_payload = {"items": out_items, "content_dispositions": dispositions}
    return fixed_payload, dispositions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory", help="内容清单 JSON（facts/blocks/items 列表）")
    parser.add_argument("--text-field", help="显式指定正文字段名")
    parser.add_argument("--out", help="写出 JSON 审计报告")
    parser.add_argument("--write-fixed", metavar="PATH",
                        help="写出净化后的清单（含 content_dispositions 追溯记录）")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    try:
        payload = json.loads(Path(args.inventory).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"INVALID_INPUT: {exc}", file=sys.stderr)
        return 2

    items = _collect(payload)
    if not items:
        print("NO_ITEMS: 未找到可检查的内容条目", file=sys.stderr)
        return 2

    issues = Hygiene(items, args.text_field).run()
    summary = summarize(issues)
    report = {"item_count": len(items), "summary": summary, "issues": issues}

    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.write_fixed:
        fixed_payload, dispositions = build_fixed_payload(payload, items, args.text_field)
        fixed_payload["_hygiene_report"] = summary
        Path(args.write_fixed).write_text(
            json.dumps(fixed_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        report["fixed_path"] = args.write_fixed
        report["dispositions"] = dispositions
        if not args.quiet:
            print(f"fixed inventory written: {args.write_fixed} "
                  f"({len(items)} -> {len(fixed_payload.get('facts') or fixed_payload.get('items') or [])} 条，"
                  f"{len(dispositions)} 条合并记录)")

    if args.json and not args.quiet:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        s = summary
        print(f"items={len(items)} total={s['total']} "
              f"critical={s['counts']['critical']} major={s['counts']['major']} "
              f"minor={s['counts']['minor']} clean={s['deliverable']}")
        for code, n in s["by_code"].items():
            print(f"  {code}: {n}")
        if not args.quiet:
            for issue in issues:
                if issue["severity"] in {"critical", "major"}:
                    print(f"[{issue['severity'].upper()}] {issue['item_id']} "
                          f"{issue['issue_code']} -> {issue['editorial_action']}: {issue['evidence']}")

    return 0 if summary["deliverable"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
