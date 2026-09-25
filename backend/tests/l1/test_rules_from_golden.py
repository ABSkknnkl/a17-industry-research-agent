"""L1 规则判定（R/G/P/H/T 类）——全部基于黄金样本产物离线回放。

**判据来源**：任务书 §3.1（V8 判定项全量映射）与 §3.4（判据变更登记）。
**输入**：黄金样本 `run-20260923094843-353`（completed，五阶段全通过）的既有产物，
不重跑、不调用任何模型（`provider_mode=replay`、`input_source=golden-run`）。

**关键设计纪律**：
- 章节数基准**从大纲单一事实源推导**（`chapter_writer.outline.DEFAULT_OUTLINE`），不写死 7 / 21；
- 禁词扫描**豁免合规免责声明**（"不构成投资建议"是应有表述，不是违规）；
- 证据池不变量按任务书 §3.1 注记：**A2 ⊆ A1、A3 ⊆ A1**（A1 是证据唯一所有者）。
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

import pytest

from chapter_writer.outline import DEFAULT_OUTLINE

PROJECT_ROOT = Path(__file__).resolve().parents[3]
GOLDEN_RUN_ID = "run-20260923094843-353"
GOLDEN_DIR = PROJECT_ROOT / "data" / "runs" / GOLDEN_RUN_ID / "artifacts"

# R2 禁词（任务书 §3.1 R2）：违规表述
FORBIDDEN_PATTERNS = ("收益承诺", "买入", "卖出", "目标价", "稳赚", "投资建议")
# 合规豁免：免责声明句式中的"投资建议"不构成违规
COMPLIANCE_EXEMPTIONS = ("不构成投资建议", "不构成任何投资建议", "仅供研究参考")
# 技能调用上限锚点（任务书 §3.4 T3：默认 max_skill_calls=24）
DEFAULT_MAX_SKILL_CALLS = 24


@lru_cache(maxsize=1)
def _artifact(name: str) -> dict:
    path = GOLDEN_DIR / name
    assert path.exists(), f"黄金样本产物缺失: {path}"
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _evidence_pool() -> set[str]:
    """A1 证据池：dataset.json 中所有记录的 record_id（按 §3.1 注记，A1 是唯一所有者）。"""
    dataset = _artifact("dataset.json")
    pool: set[str] = set()
    for key, value in dataset.items():
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and item.get("record_id"):
                    pool.add(str(item["record_id"]))
    return pool


# --------------------------------------------------------------------------
# R 类：报告结构与表述
# --------------------------------------------------------------------------


def test_r1_outline_structure_matches_single_source_of_truth() -> None:
    """R1：章节骨架 == DEFAULT_OUTLINE 推导值（不写死 7 / 21）。"""
    chapters = _artifact("chapter_result.json").get("chapters") or []
    expected_chapters = len(DEFAULT_OUTLINE)
    expected_sections = sum(len(getattr(c, "items", getattr(c, "sections", []))) for c in DEFAULT_OUTLINE)
    actual_sections = sum(len(c.get("sections") or []) for c in chapters)
    assert len(chapters) == expected_chapters, f"章节数 {len(chapters)} != 大纲 {expected_chapters}"
    assert actual_sections == expected_sections, (
        f"节数 {actual_sections} != 大纲推导 {expected_sections}（大纲版本 "
        f"{_artifact('chapter_result.json').get('outline_version')}）"
    )


def test_r2_no_forbidden_wording_veto() -> None:
    """R2（一票否决）：禁词零命中，合规免责声明除外。"""
    raw = json.dumps(_artifact("chapter_result.json"), ensure_ascii=False)
    cleaned = raw
    for phrase in COMPLIANCE_EXEMPTIONS:
        cleaned = cleaned.replace(phrase, "")
    hits = {p: cleaned.count(p) for p in FORBIDDEN_PATTERNS if p in cleaned}
    assert hits == {}, f"R2 命中违规表述: {hits}"


def test_r3_every_chapter_has_traceable_evidence() -> None:
    """R3：每章 evidence_ids 非空且全部落在 A1 证据池内。"""
    chapters = _artifact("chapter_result.json").get("chapters") or []
    pool = _evidence_pool()
    problems: dict[str, dict] = {}
    for ch in chapters:
        ids = [str(i) for i in (ch.get("evidence_ids") or [])]
        missing = sorted(set(ids) - pool)
        if not ids or missing:
            problems[str(ch.get("chapter_id"))] = {"count": len(ids), "not_in_pool": missing[:5]}
    assert problems == {}, f"R3 存在无溯源或越界引用的章节: {problems}"


# --------------------------------------------------------------------------
# G 类：图表约束
# --------------------------------------------------------------------------


def test_g1_no_duplicate_chart_for_same_evidence_set() -> None:
    """G1：同一 evidence_ids 集合的图表 ≤ 1 张。"""
    charts = _artifact("chart_result.json").get("charts") or []
    seen: dict[frozenset, str] = {}
    duplicates: list[tuple[str, str]] = []
    for ch in charts:
        key = frozenset(str(i) for i in (ch.get("evidence_ids") or []))
        if key in seen:
            duplicates.append((seen[key], str(ch.get("chart_id"))))
        else:
            seen[key] = str(ch.get("chart_id"))
    assert duplicates == [], f"G1 同一证据集重复出图: {duplicates}"


def test_g3_industry_chain_chart_at_most_one() -> None:
    """G3：产业链图每报告 ≤ 1 张。"""
    charts = _artifact("chart_result.json").get("charts") or []
    chain = [str(c.get("chart_id")) for c in charts if c.get("chart_type") == "industry_chain"]
    assert len(chain) <= 1, f"G3 产业链图 {len(chain)} 张（判据 ≤1）: {chain}"


def test_g4_chart_numbers_traceable_to_charts_evidence() -> None:
    """G4（可离线部分）：每张图的证据 ID 必须落在 A1 证据池内。"""
    charts = _artifact("chart_result.json").get("charts") or []
    pool = _evidence_pool()
    bad: dict[str, list[str]] = {}
    for ch in charts:
        ids = {str(i) for i in (ch.get("evidence_ids") or [])}
        missing = sorted(ids - pool)
        if missing:
            bad[str(ch.get("chart_id"))] = missing[:5]
    assert bad == {}, f"G4 图表引用了证据池外的 ID: {bad}"


# --------------------------------------------------------------------------
# H 类：交接契约的不变量（任务书 §3.1 注记）
# --------------------------------------------------------------------------


def test_h1_a2_evidence_pool_is_subset_of_a1() -> None:
    """H1 关键不变量：A2 证据池 ⊆ A1 证据池（A1 是证据唯一所有者）。"""
    index = _artifact("interpretation_report.json").get("evidence_index") or {}
    pool = _evidence_pool()
    a2 = set(map(str, index.keys()))
    leaked = sorted(a2 - pool)
    assert leaked == [], f"A2 出现 A1 池外的证据（单写者不变量破坏）: {leaked[:10]}（共 {len(leaked)} 条）"


def test_h2_a3_evidence_pool_is_subset_of_a1() -> None:
    """H1/H2 关键不变量：A3（图表）证据池 ⊆ A1 证据池。"""
    charts = _artifact("chart_result.json").get("charts") or []
    pool = _evidence_pool()
    a3: set[str] = set()
    for ch in charts:
        a3 |= {str(i) for i in (ch.get("evidence_ids") or [])}
        a3 |= {str(i) for i in (ch.get("point_evidence_ids") or [])}
    leaked = sorted(a3 - pool)
    assert leaked == [], f"A3 出现 A1 池外的证据: {leaked[:10]}（共 {len(leaked)} 条）"


# --------------------------------------------------------------------------
# T 类：技能调用台账（判据重锚，见 §3.4 T3）
# --------------------------------------------------------------------------


def test_t3_skill_calls_within_budget_and_deduplicated() -> None:
    """T3：调用条数 ≤ max_skill_calls（默认 24）；同 (skill_id, query) 不得重复。"""
    sources = _artifact("dataset.json").get("sources") or []
    assert len(sources) <= DEFAULT_MAX_SKILL_CALLS, (
        f"T3 调用条数 {len(sources)} 超过上限 {DEFAULT_MAX_SKILL_CALLS}"
    )
    seen: set[tuple[str, str]] = set()
    duplicates: list[tuple[str, str]] = []
    for item in sources:
        key = (str(item.get("skill_id")), str(item.get("query")))
        if key in seen:
            duplicates.append(key)
        seen.add(key)
    assert duplicates == [], f"T3 存在重复的 (skill, query) 调用: {duplicates}"


def test_t1_skill_invocations_are_registered_skills() -> None:
    """T1（可离线部分）：调用台账中的 skill_id 必须是已注册技能（命名规范 hithink-* / *-search）。"""
    sources = _artifact("dataset.json").get("sources") or []
    registered = re.compile(r"^(hithink-[a-z0-9-]+|news-search|report-search)$")
    unknown = sorted({str(s.get("skill_id")) for s in sources if not registered.match(str(s.get("skill_id")))})
    assert unknown == [], f"T1 出现未注册技能 ID: {unknown}"
