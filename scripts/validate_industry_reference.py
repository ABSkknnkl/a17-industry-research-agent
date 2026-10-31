#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""行业参考主数据发布校验（D1，V8 最终方案 §8.4）。

校验项（任一不满足即非零退出）：
1. 每条原记录都有去向（accepted / candidate / conflict / pending_review / rejected），无静默丢弃。
2. 三条严重身份冲突在库且 disposition=conflict。
3. 14 处名称差异全部显式登记，且逐条有分类。
4. 2 条申万未命中（东方通、观典防务）显式记录且未被判无效。
5. 5 条北交所证券 market 已按显式交易所补齐，且不因申万缺失被误杀。
6. 11 个二级分类的 declared_count 与实际数组长度差异全部保留。
7. 原文件哈希与 manifest 一致（只读未改）。

用法::

    ./.venv/bin/python scripts/validate_industry_reference.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "data" / "industry_reference"

SEVERE_CONFLICT_TICKERS = {"300927.SZ", "301268.SZ", "688607.SH"}
NAME_DIFF_TICKERS = {
    "688347.SH", "300068.SZ", "300548.SZ", "688165.SH", "688561.SH", "001301.SZ",
    "688185.SH", "300832.SZ", "300927.SZ", "301268.SZ", "688607.SH", "688076.SH",
    "603501.SH", "688779.SH",
}
MISSING_TICKERS = {"300379.SZ", "688287.SH"}
BJ_TICKERS = {"920077.BJ", "920491.BJ", "920522.BJ", "920185.BJ", "920368.BJ"}
COUNT_MISMATCH_LEVEL2 = {
    "种植业", "化学制品", "半导体", "白色家电", "饰品", "化学制药",
    "通信服务", "证券Ⅱ", "摩托车及其他", "通用设备", "专用设备",
}


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def main() -> int:
    pointer = BASE / "current.json"
    if not pointer.exists():
        print("[失败] 缺少 current.json，请先运行 import_industry_reference.py")
        return 1
    release_id = json.loads(pointer.read_text(encoding="utf-8"))["release_id"]
    rel = BASE / "releases" / release_id
    manifest = json.loads((rel / "manifest.json").read_text(encoding="utf-8"))

    orgs = _load_jsonl(rel / "organizations.jsonl")
    secs = _load_jsonl(rel / "securities.jsonl")
    classes = _load_jsonl(rel / "classifications.jsonl")
    roles = _load_jsonl(rel / "role_candidates.jsonl")
    conflicts = _load_jsonl(rel / "conflicts.jsonl")

    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" | {detail}" if detail else ""))
        if not ok:
            failures.append(name)

    # 1) 每条记录有去向
    def has_disposition(rows: list[dict], field: str) -> bool:
        return all(str(r.get(field) or "") for r in rows)

    check("组织记录均有身份去向", has_disposition(orgs, "identity_status"))
    check("证券记录均有身份去向", has_disposition(secs, "identity_status"))
    check("角色记录均有角色去向", has_disposition(roles, "role_status"))
    check("冲突记录均有处置", has_disposition(conflicts, "disposition"))

    # 2) 三条严重冲突
    severe = {c["ticker"] for c in conflicts if c.get("kind") == "severe_identity_conflict"}
    check("三条严重身份冲突已隔离", SEVERE_CONFLICT_TICKERS <= severe,
          f"missing={sorted(SEVERE_CONFLICT_TICKERS - severe)}")
    severe_disposition_ok = all(
        c.get("disposition") == "conflict"
        for c in conflicts
        if c.get("kind") == "severe_identity_conflict"
    )
    check("严重冲突处置为 conflict（不自动设别名）", severe_disposition_ok)

    # 3) 14 处名称差异
    diff_tickers = {
        c["ticker"] for c in conflicts
        if c.get("kind") in ("name_difference", "severe_identity_conflict") and c.get("ticker")
    }
    check("14 处名称差异全部登记", NAME_DIFF_TICKERS <= diff_tickers,
          f"missing={sorted(NAME_DIFF_TICKERS - diff_tickers)}")
    diff_classified = all(
        str(c.get("classification") or "")
        for c in conflicts
        if c.get("kind") in ("name_difference", "severe_identity_conflict")
    )
    check("名称差异逐条有分类", diff_classified)

    # 4) 申万未命中 2 条
    missing = {c["ticker"] for c in conflicts if c.get("kind") == "missing_in_classification"}
    check("2 条申万未命中已留痕", MISSING_TICKERS <= missing,
          f"missing={sorted(MISSING_TICKERS - missing)}")
    not_invalidated = all(
        "无效" in str(c.get("reason") or "") or "退市" in str(c.get("reason") or "")
        for c in conflicts
        if c.get("ticker") in MISSING_TICKERS
    )
    check("未命中未被判无效/退市", not_invalidated)

    # 5) 北交所 market
    bj_market = {s["ticker"]: s.get("market") for s in secs if s.get("ticker") in BJ_TICKERS}
    check("5 条北交所证券 market 已补齐", all(str(v or "") == "A股" for v in bj_market.values()), str(bj_market))
    bj_conflict = {c["ticker"] for c in conflicts if c.get("kind") == "missing_market_label"}
    check("北交所缺标签已留痕", BJ_TICKERS <= bj_conflict)

    # 6) 11 个计数差异
    cnt = {
        c["names"][0] for c in conflicts
        if c.get("kind") == "count_mismatch" and c.get("names")
    }
    check("11 个二级分类计数差异已保留", COUNT_MISMATCH_LEVEL2 <= cnt,
          f"missing={sorted(COUNT_MISMATCH_LEVEL2 - cnt)}")
    # declared_count 必须原样保留在成分记录上，且与 actual_count 并存（不补公司凑数）
    mismatch_rows = [c for c in classes if c.get("count_mismatch")]
    mismatch_level2 = {c.get("level2_name") for c in mismatch_rows}
    declared_preserved = all(
        c.get("declared_count") is not None and c.get("actual_count") is not None
        for c in mismatch_rows
    )
    check(
        "计数差异不补公司凑数（declared/actual 原样保留）",
        declared_preserved and COUNT_MISMATCH_LEVEL2 <= mismatch_level2,
        f"rows={len(mismatch_rows)} level2={sorted(mismatch_level2)[:4]}",
    )

    # 7) 原文件哈希未变
    hashes = manifest.get("source_hashes") or {}
    hash_ok = True
    for rel_path, expected in hashes.items():
        path = ROOT / rel_path
        if not path.exists():
            hash_ok = False
            break
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            hash_ok = False
            break
    check("原始快照哈希与 manifest 一致（只读未改）", hash_ok)

    # 附加：规模与契约
    check("组织规模 591", len(orgs) == 591, str(len(orgs)))
    check("证券规模 615", len(secs) == 615, str(len(secs)))
    check("角色候选规模 652", len(roles) == 652, str(len(roles)))
    check("申万成分规模 5221", len(classes) == 5221, str(len(classes)))
    check("rank/weight 不生成 leader_score", all("leader_score" not in r for r in roles))

    print()
    print(f"release = {release_id}")
    if failures:
        print("失败项：", "；".join(failures))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
