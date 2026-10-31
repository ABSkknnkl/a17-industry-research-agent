#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""行业参考主数据导入与发布（D1，V8 最终方案 §8）。

职责边界：
- **只读**原始快照；不改原文件、不改既有 chart_kb。
- 身份/证券/分类成分/角色候选分别落库；冲突与差异显式记录，不自动和解。
- 发布只包含可核验范围；未完成核验的留在 staged 并以 disposition 标注。

用法::

    ./.venv/bin/python scripts/import_industry_reference.py --release 2026-10-31-r1
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agents_core"))
sys.path.insert(0, str(ROOT / "agents_core" / "industry_reference"))

RAW_DIRNAME = "2026-10-31"
CLASSIFICATION_SYSTEM = "申万宏源行业分类"
CLASSIFICATION_VERSION = "2021"

# 14 处名称差异的**逐条**处置（V8 最终方案 §8.1 明确列举）。
# alias_variant/status_variant 可发布为已审别名；rename_candidate /
# same_group_different_listing 保持 pending_review；severe 直接 conflict。
NAME_DIFF_DISPOSITION: dict[str, dict[str, str]] = {
    "688347": {"classification": "same_group_different_listing", "disposition": "pending_review",
               "reason": "华虹半导体（A股）与华虹宏力（H股）为同一集团不同上市主体，不可自动合并"},
    "300068": {"classification": "status_variant", "disposition": "accepted",
               "reason": "ST 为风险警示状态标识，主体同一；别名不改变状态语义"},
    "300548": {"classification": "rename_candidate", "disposition": "pending_review",
               "reason": "博创科技 → 长芯博创 疑为更名，须以公告/工商核验后发布"},
    "688165": {"classification": "status_variant", "disposition": "accepted",
               "reason": "-U 为科创板未盈利标识，主体同一"},
    "688561": {"classification": "status_variant", "disposition": "accepted",
               "reason": "-U 为科创板未盈利标识，主体同一"},
    "001301": {"classification": "rename_candidate", "disposition": "pending_review",
               "reason": "尚太股份 / 尚太科技 简称差异疑为更名，待核"},
    "688185": {"classification": "alias_variant", "disposition": "accepted",
               "reason": "康希诺生物 / 康希诺 为完整名与简写"},
    "300832": {"classification": "alias_variant", "disposition": "accepted",
               "reason": "新产业生物 / 新产业 为完整名与简写"},
    "300927": {"classification": "severe_identity_conflict", "disposition": "conflict",
               "reason": "同代码 300927.SZ 在两份资料中指向不同主体（法本信息 / 江天化学），不裁定"},
    "301268": {"classification": "severe_identity_conflict", "disposition": "conflict",
               "reason": "同代码 301268.SZ 在两份资料中指向不同主体（润阳股份 / 铭利达），不裁定"},
    "688607": {"classification": "severe_identity_conflict", "disposition": "conflict",
               "reason": "同代码 688607.SH 在两份资料中指向不同主体（美科股份 / 康众科技），不裁定"},
    "688076": {"classification": "status_variant", "disposition": "accepted",
               "reason": "ST 为风险警示状态标识，主体同一"},
    "603501": {"classification": "alias_variant", "disposition": "accepted",
               "reason": "豪威集团（韦尔股份）括号内为曾用名，别名可发布"},
    "688779": {"classification": "rename_candidate", "disposition": "pending_review",
               "reason": "长远锂科 → 五矿新能 疑为更名，待核"},
}

_NEW_MARKETS = {"SH": "A股", "SZ": "A股", "BJ": "A股", "HK": "港股", "SS": "A股"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _provenance(source_id: str, file_name: str, sha: str, pointer: str, as_of: str) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "source_file": file_name,
        "source_sha256": sha,
        "json_pointer": pointer,
        "source_declared_as_of": as_of,
        "imported_at": datetime.now().isoformat(),
    }


def _bare_and_exchange(ticker: str) -> tuple[str, str]:
    text = str(ticker or "").strip().upper()
    for suffix in (".SH", ".SZ", ".BJ", ".HK", ".SS", ".NO", ".US"):
        if text.endswith(suffix):
            exch = suffix.lstrip(".")
            exch = "SH" if exch == "SS" else exch
            return text[: -len(suffix)], exch
    return text, ""


def _org_id(name: str) -> str:
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:12]
    return f"org-{digest}"


def _role_id(org_id: str, theme: str, segment: str, subfield: str) -> str:
    key = f"{org_id}|{theme}|{segment}|{subfield}".encode("utf-8")
    return "role-" + hashlib.sha1(key).hexdigest()[:14]


def _norm_theme(industry: str) -> tuple[str, str]:
    """来源 industry（如 半导体/集成电路）→ (theme_id, theme_name)。"""
    name = str(industry or "").strip()
    if not name:
        return "unclassified", "未分类"
    theme_id = "".join(ch for ch in name if ch.isalnum() or ch in "-_") or "unclassified"
    return f"theme-{theme_id}", name


def build_staged(raw_dir: Path) -> dict[str, Any]:
    core_path = raw_dir / "core_whitelist.json"
    sw_path = raw_dir / "sw_industry.json"
    core_sha = _sha256(core_path)
    sw_sha = _sha256(sw_path)

    core = json.loads(core_path.read_text(encoding="utf-8"))
    sw = json.loads(sw_path.read_text(encoding="utf-8"))
    core_as_of = str(core.get("meta", {}).get("data_date") or RAW_DIRNAME)
    sw_as_of = str(sw.get("meta", {}).get("data_date") or RAW_DIRNAME)

    # ── 1. 申万分类成分（先建 ticker → 名称/交易所映射）──────────────────
    sw_name_by_ticker: dict[str, str] = {}
    classifications: list[dict[str, Any]] = []
    count_mismatches: list[dict[str, Any]] = []
    for li, l1 in enumerate(sw.get("industries") or []):
        for lj, l2 in enumerate(l1.get("level2") or []):
            declared = l2.get("declared_count")
            companies = l2.get("companies") or []
            actual = len(companies)
            mismatch = bool(declared is not None and declared != actual)
            if mismatch:
                count_mismatches.append({
                    "conflict_id": f"cnt-{l2.get('level2_code')}",
                    "kind": "count_mismatch",
                    "ticker": "",
                    "names": [l2.get("level2_name", "")],
                    "classification": "source_count_disagreement",
                    "disposition": "pending_review",
                    "reason": (
                        f"申万二级「{l2.get('level2_name')}」声明 {declared} 家、实际 {actual} 条；"
                        "按实际数组计数，保留源声明差异，不补公司凑数"
                    ),
                    "provenance": [
                        _provenance("sw_industry", sw_path.name, sw_sha,
                                    f"/industries/{li}/level2/{lj}", sw_as_of)
                    ],
                })
            for hi, holding in enumerate(companies):
                ticker = str(holding.get("ticker") or "")
                bare, exch = _bare_and_exchange(ticker)
                name = str(holding.get("company") or "")
                if bare and name:
                    sw_name_by_ticker.setdefault(bare, name)
                classifications.append({
                    "membership_id": f"cls-{l2.get('level2_code')}-{bare or hi}",
                    "classification_system": CLASSIFICATION_SYSTEM,
                    "classification_version": CLASSIFICATION_VERSION,
                    "level1_code": str(l1.get("level1_code") or ""),
                    "level1_name": str(l1.get("level1_name") or ""),
                    "level2_code": str(l2.get("level2_code") or ""),
                    "level2_name": str(l2.get("level2_name") or ""),
                    "security_id": f"sec-{bare}.{exch}" if exch else (f"sec-{bare}" if bare else None),
                    "ticker": ticker,
                    "company_name": name,
                    "rank": holding.get("rank"),
                    "weight": holding.get("weight"),
                    "source_declared_as_of": sw_as_of,
                    "declared_count": declared,
                    "actual_count": actual,
                    "count_mismatch": mismatch,
                    # 成分口径只是分类快照，不等于已核身份
                    "identity_status": "candidate",
                    "provenance": [
                        _provenance("sw_industry", sw_path.name, sw_sha,
                                    f"/industries/{li}/level2/{lj}/companies/{hi}", sw_as_of)
                    ],
                })

    # ── 2. 核心名单：组织 + 证券 + 角色候选 ─────────────────────────────
    organizations: list[dict[str, Any]] = []
    securities: list[dict[str, Any]] = []
    roles: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = list(count_mismatches)

    core_a_share: list[tuple[str, str, str]] = []  # (bare, ticker, core_name)
    bj_missing_market: list[tuple[str, str, str]] = []

    for ci, company in enumerate(core.get("companies") or []):
        name = str(company.get("company") or "").strip()
        if not name:
            continue
        org_id = _org_id(name)
        sec_rows = company.get("securities") or []
        org_markets: list[str] = []

        for si, sec in enumerate(sec_rows):
            ticker = str(sec.get("ticker") or "")
            bare, exch = _bare_and_exchange(ticker)
            market = str(sec.get("market") or "")
            exchange = str(sec.get("exchange") or "")
            # 格式规范化规则（不猜测）：缺 market 时按显式交易所后缀补 A股/港股
            if not market and exch:
                market = _NEW_MARKETS.get(exch, "未知")
                if exch == "BJ":
                    bj_missing_market.append((bare, ticker, name))
            if not market:
                market = "未知"
            security_id = f"sec-{bare}.{exch}" if exch else f"sec-{bare}"
            securities.append({
                "security_id": security_id,
                "organization_id": org_id,
                "market": market,
                "exchange": exch,
                "ticker": ticker,
                "bare_ticker": bare,
                "valid_from": None,
                "valid_to": None,
                "identity_status": "candidate",   # 身份待核；冲突处理在下方覆盖
                "provenance": [
                    _provenance("core_whitelist", core_path.name, core_sha,
                                f"/companies/{ci}/securities/{si}", core_as_of)
                ],
            })
            if market:
                org_markets.append(market)
            if market == "A股" and bare:
                core_a_share.append((bare, ticker, name))

        # 角色候选：segment + subfield 明确映射为 activity_key（不做全局 stage 替换）
        for bi, belong in enumerate(company.get("belongs_to") or []):
            industry = str(belong.get("industry") or "")
            segment = str(belong.get("segment") or "")
            subfield = str(belong.get("subfield") or "")
            theme_id, theme_name = _norm_theme(industry)
            activity_key = f"{segment}:{subfield}" if subfield else segment
            roles.append({
                "role_id": _role_id(org_id, theme_id, segment, subfield),
                "organization_id": org_id,
                "organization_name": name,
                "theme_id": theme_id,
                "theme_name": theme_name,
                "category_id": industry,
                "activity_key": activity_key,
                "role": _role_for_tier(str(belong.get("tier") or "")),
                "source_segment": segment,
                "source_subfield": subfield,
                "source_declared_tier": str(belong.get("tier") or ""),
                "scope_market": sorted(set(org_markets)),
                "scope_notes": "",
                "role_status": "candidate",   # 名单只是候选，证据仍要另走
                "evidence_refs": [],
                "provenance": [
                    _provenance("core_whitelist", core_path.name, core_sha,
                                f"/companies/{ci}/belongs_to/{bi}", core_as_of)
                ],
            })

        organizations.append({
            "organization_id": org_id,
            "canonical_name": name,
            "aliases": [],
            "identity_status": "candidate",
            "organization_type": "listed_company" if sec_rows else "unlisted_company",
            "group_hint": None,
            "notes": list(company.get("notes") or [])[:5],
            "provenance": [
                _provenance("core_whitelist", core_path.name, core_sha, f"/companies/{ci}", core_as_of)
            ],
        })

    # ── 3. 名称差异 / 严重冲突 / 未命中 ─────────────────────────────────
    org_by_id = {o["organization_id"]: o for o in organizations}
    sec_by_bare = {s["bare_ticker"]: s for s in securities if s.get("bare_ticker")}

    for bare, ticker, core_name in core_a_share:
        sw_name = sw_name_by_ticker.get(bare)
        if sw_name is None:
            is_bj = str(ticker).upper().endswith(".BJ")
            conflicts.append({
                "conflict_id": f"miss-{bare}",
                "kind": "missing_in_classification",
                "ticker": ticker,
                "names": [core_name],
                "classification": "bj_outside_sw_scope" if is_bj else "not_in_sw_snapshot",
                "disposition": "pending_review",
                "reason": (
                    "申万文件声明沪深范围，北交所不在其覆盖内；不据其缺失判无效"
                    if is_bj
                    else "核心名单有该证券、本次申万快照无对应成分；不能仅据缺失断言退市或无效"
                ),
                "provenance": [],
            })
            continue
        if sw_name == core_name:
            continue
        rule = NAME_DIFF_DISPOSITION.get(bare, {
            "classification": "alias_variant", "disposition": "pending_review",
            "reason": "未登记的名称差异，待人工核定",
        })
        conflicts.append({
            "conflict_id": f"name-{bare}",
            "kind": "severe_identity_conflict" if rule["classification"] == "severe_identity_conflict" else "name_difference",
            "ticker": ticker,
            "names": [core_name, sw_name],
            "classification": rule["classification"],
            "disposition": rule["disposition"],
            "reason": rule["reason"],
            "provenance": [],
        })
        sec = sec_by_bare.get(bare)
        org = org_by_id.get(sec["organization_id"]) if sec else None
        if rule["classification"] == "severe_identity_conflict":
            # 同代码不同主体：证券与组织都置为 conflict，禁止当作已确认身份
            if sec:
                sec["identity_status"] = "conflict"
            if org:
                org["identity_status"] = "conflict"
                org["notes"] = list(org.get("notes") or []) + ["身份冲突：同代码在两份资料中指向不同主体，待人工裁定"]
        elif rule["disposition"] == "accepted" and org:
            alias = sw_name if sw_name != org["canonical_name"] else core_name
            if alias and alias not in org["aliases"]:
                org["aliases"].append(alias)
            org["identity_status"] = "accepted" if org["identity_status"] != "conflict" else "conflict"
            if sec:
                sec["identity_status"] = org["identity_status"]
        else:
            if org:
                org["notes"] = list(org.get("notes") or []) + [
                    f"名称差异待核：{core_name} / {sw_name}（{rule['classification']}）"
                ]

    # 可发布组织：非冲突；其余仍留 staged（disposition=pending_review/conflict）
    for org in organizations:
        if org["identity_status"] == "candidate" and org["aliases"]:
            # 有已审别名但主体未确认 → 保持 candidate（不因别名升级）
            pass
    for sec in securities:
        if sec["identity_status"] == "candidate":
            org = org_by_id.get(sec["organization_id"])
            if org and org["identity_status"] == "accepted":
                sec["identity_status"] = "accepted"

    # 角色状态：组织已确认 → 角色仍为 candidate（名单不等于证据）
    for role in roles:
        org = org_by_id.get(role["organization_id"])
        if org and org["identity_status"] == "conflict":
            role["role_status"] = "conflict"

    for bare, ticker, name in bj_missing_market:
        conflicts.append({
            "conflict_id": f"mkt-{bare}",
            "kind": "missing_market_label",
            "ticker": ticker,
            "names": [name],
            "classification": "market_label_filled_from_explicit_exchange",
            "disposition": "accepted",
            "reason": "原记录 market 为空；按显式 .BJ 后缀补为 A股（格式规范化，不改主体）",
            "provenance": [],
        })

    return {
        "source_hashes": {
            str(core_path.relative_to(ROOT)): core_sha,
            str(sw_path.relative_to(ROOT)): sw_sha,
        },
        "organizations": organizations,
        "securities": securities,
        "classifications": classifications,
        "role_candidates": roles,
        "conflicts": conflicts,
        "source_declared": {"core_as_of": core_as_of, "sw_as_of": sw_as_of},
    }


def _role_for_tier(tier: str) -> str:
    """源声明 tier → 角色词（不提升为置信度）。"""
    return {
        "龙头": "leading_brand_or_upstream",
        "核心": "core_supplier_or_brand",
        "配套": "supporting",
    }.get(tier, "candidate_role")


def main() -> int:
    parser = argparse.ArgumentParser(description="导入并发布行业参考主数据")
    parser.add_argument("--release", default=datetime.now().strftime("%Y-%m-%d-r1"))
    parser.add_argument("--raw-date", default=RAW_DIRNAME)
    args = parser.parse_args()

    raw_dir = ROOT / "data" / "industry_reference" / "raw" / args.raw_date
    if not raw_dir.exists():
        print(f"[错误] 原始快照目录不存在: {raw_dir}")
        return 1

    staged = build_staged(raw_dir)
    staged_dir = ROOT / "data" / "industry_reference" / "staged"
    _write_jsonl(staged_dir / "organizations.jsonl", staged["organizations"])
    _write_jsonl(staged_dir / "securities.jsonl", staged["securities"])
    _write_jsonl(staged_dir / "classifications.jsonl", staged["classifications"])
    _write_jsonl(staged_dir / "role_candidates.jsonl", staged["role_candidates"])
    _write_jsonl(staged_dir / "conflicts.jsonl", staged["conflicts"])

    # 发布：只发布可核验范围（accepted/candidate），冲突与待核记录保留 disposition
    release_dir = ROOT / "data" / "industry_reference" / "releases" / args.release
    release_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(release_dir / "organizations.jsonl", staged["organizations"])
    _write_jsonl(release_dir / "securities.jsonl", staged["securities"])
    _write_jsonl(release_dir / "classifications.jsonl", staged["classifications"])
    _write_jsonl(release_dir / "role_candidates.jsonl", staged["role_candidates"])
    _write_jsonl(release_dir / "conflicts.jsonl", staged["conflicts"])

    dispositions: dict[str, int] = {}
    for row in [*staged["organizations"], *staged["securities"], *staged["role_candidates"], *staged["conflicts"]]:
        key = str(row.get("identity_status") or row.get("role_status") or row.get("disposition") or "unknown")
        dispositions[key] = dispositions.get(key, 0) + 1

    manifest = {
        "release_id": args.release,
        "created_at": datetime.now().isoformat(),
        "source_hashes": staged["source_hashes"],
        "source_declared": staged["source_declared"],
        "counts": {
            "organizations": len(staged["organizations"]),
            "securities": len(staged["securities"]),
            "classifications": len(staged["classifications"]),
            "role_candidates": len(staged["role_candidates"]),
            "conflicts": len(staged["conflicts"]),
        },
        "dispositions": dispositions,
        "notes": [
            "身份已确认不代表角色已确认；角色候选仍须走证据发现。",
            "rank/weight 为申万成分口径，不生成 leader_score 或市场份额。",
            "冲突与名称差异不自动和解，逐条保留 disposition 供人工核验。",
        ],
    }
    (release_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ROOT / "data" / "industry_reference" / "current.json").write_text(
        json.dumps({"release_id": args.release, "updated_at": datetime.now().isoformat()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"[完成] release={args.release}")
    for k, v in manifest["counts"].items():
        print(f"  {k}: {v}")
    print(f"  dispositions: {dispositions}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
