"""N28–N30 · A2 方法论技能覆盖矩阵（20 个 skill）——离线静态判定。

**判据来源**：任务书 §3.3「A2 方法论覆盖矩阵从 7 扩到 20 个 skill：逐个验 M1 触发 / M2 不误触发 / M3 模板完整」。

**可判边界（诚实声明）**：
- M1/M2 的**语义触发**判定需要模型（本轮不跑真实模型）→ 本文件按**可规则化部分**判：
  `_meta.json` 的 `domains`/`keywords`/`requires_signal` 是触发表，触发结果（`applied_skills`）必须与之自洽；
- M3「模板完整」落到**包结构完备性**：SKILL.md 的 frontmatter 与 `_meta.json` 必需字段。

**为什么把 `requires_signal` 列为必需字段**：它决定"该技能是否要求输入具备信号才允许触发"（M2 不误触发的唯一可判依据）。
实测 6/20 个技能未声明该字段 → 无法对它们执行 M2 判定（见台账缺陷 D-06）。
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = PROJECT_ROOT / "agents_core" / "data-analysis" / "data_interpreter" / "skills"
GOLDEN_RUN_ID = "run-20260926022235-107"
EXPECTED_SKILL_COUNT = 20
REQUIRED_META_FIELDS = ("domains", "keywords", "requires_signal")
DOMAINS = ("industry", "companies", "financials", "macro", "industry_chain", "reports", "news")


@lru_cache(maxsize=1)
def _skill_packages() -> dict[str, dict]:
    """{skill 目录名: {"md": text, "meta": dict|None}}"""
    packages: dict[str, dict] = {}
    for path in sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir()):
        md = path / "SKILL.md"
        meta_path = path / "_meta.json"
        meta = None
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                meta = "INVALID"
        packages[path.name] = {
            "md": md.read_text(encoding="utf-8") if md.exists() else None,
            "meta": meta,
        }
    return packages


@lru_cache(maxsize=1)
def _applied_skills() -> list[str]:
    report = json.loads(
        (PROJECT_ROOT / "data" / "runs" / GOLDEN_RUN_ID / "artifacts" / "interpretation_report.json").read_text(
            encoding="utf-8"
        )
    )
    return [str(s.get("name")) for s in (report.get("applied_skills") or [])]


def test_n30_a2_methodology_skills_count_is_20() -> None:
    """N30 前置：A2 方法论技能目录数必须为 20（覆盖矩阵的基数）。"""
    packages = _skill_packages()
    assert len(packages) == EXPECTED_SKILL_COUNT, (
        f"A2 方法论 skill 目录数 {len(packages)} != 期望 {EXPECTED_SKILL_COUNT}: {sorted(packages)}"
    )


def test_n30_skill_package_structure_is_complete() -> None:
    """N30（M3 模板完整）：每个技能包 frontmatter 与 _meta 必需字段齐备。"""
    problems: dict[str, list[str]] = {}
    for name, pkg in _skill_packages().items():
        issues: list[str] = []
        md, meta = pkg["md"], pkg["meta"]
        if not md:
            issues.append("缺 SKILL.md")
        else:
            m = re.search(r"^name:\s*(.+)$", md, re.M)
            if not m:
                issues.append("SKILL.md 缺 frontmatter name")
            elif m.group(1).strip() != name:
                issues.append(f"frontmatter name={m.group(1).strip()} != 目录名")
            if not re.search(r"^description:\s*\S+", md, re.M):
                issues.append("SKILL.md 缺 frontmatter description")
            if len(md.strip()) < 80:
                issues.append("SKILL.md 正文过短（模板不完整）")
        if meta is None:
            issues.append("缺 _meta.json")
        elif meta == "INVALID":
            issues.append("_meta.json 非法 JSON")
        else:
            for key in REQUIRED_META_FIELDS:
                if key not in meta:
                    issues.append(f"_meta 缺 {key}")
            if not meta.get("domains"):
                issues.append("_meta.domains 为空")
            if not meta.get("keywords"):
                issues.append("_meta.keywords 为空")
        if issues:
            problems[name] = issues
    assert problems == {}, (
        f"N30 技能包结构不完备（{len(problems)}/{EXPECTED_SKILL_COUNT} 个有问题）: {problems}"
    )


def test_n29_requires_signal_is_explicitly_declared() -> None:
    """N29（M2 不误触发的前提）：`requires_signal` 必须显式声明为 bool。

    该字段是"是否要求输入具备信号才允许触发"的唯一依据；缺失即无法对 M2 做规则化判定。
    """
    undeclared = sorted(
        name
        for name, pkg in _skill_packages().items()
        if not isinstance((pkg["meta"] or {}), dict) or "requires_signal" not in (pkg["meta"] or {})
    )
    assert undeclared == [], (
        f"N29 {len(undeclared)}/{EXPECTED_SKILL_COUNT} 个技能未声明 requires_signal: {undeclared}"
        f"（这些技能无法执行 M2 不误触发判定）"
    )


def test_n29_skill_domains_are_registered_domains() -> None:
    """N29：每个技能声明的 domains 必须是七个已注册 Domain 的子集。"""
    unknown: dict[str, list[str]] = {}
    for name, pkg in _skill_packages().items():
        meta = pkg["meta"]
        if not isinstance(meta, dict):
            continue
        bad = sorted(set(meta.get("domains") or []) - set(DOMAINS))
        if bad:
            unknown[name] = bad
    assert unknown == {}, f"N29 技能声明了未注册 Domain: {unknown}"


def test_n28_applied_skills_are_registered_packages() -> None:
    """N28（M1 触发正确性，可判部分）：实际触发的技能必须全部是已注册技能包。"""
    applied = _applied_skills()
    assert applied, "样本未记录任何 applied_skills"
    registered = set(_skill_packages())
    unregistered = sorted(set(applied) - registered)
    assert unregistered == [], f"N28 触发了未注册技能: {unregistered}"


def test_n29_triggered_skills_have_supporting_domains() -> None:
    """N29（M2 不误触发，可判部分）：被触发技能的 domains 至少要有一个在数据集中存在数据。

    语义：若某技能声明的适用域在本次输入里完全没有记录，却仍被触发，即为误触发。
    """
    dataset = json.loads(
        (PROJECT_ROOT / "data" / "runs" / GOLDEN_RUN_ID / "artifacts" / "dataset.json").read_text(encoding="utf-8")
    )
    populated = {dom for dom in DOMAINS if dataset.get(dom)}
    packages = _skill_packages()
    violations: dict[str, list[str]] = {}
    for name in _applied_skills():
        meta = packages.get(name, {}).get("meta") or {}
        declared = set(meta.get("domains") or [])
        if declared and not (declared & populated):
            violations[name] = sorted(declared)
    assert violations == {}, (
        f"N29 误触发嫌疑：以下技能声明的适用域在本次输入中均无数据: {violations}（数据实有域={sorted(populated)}）"
    )
