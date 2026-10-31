"""验收打分口径的回归测试（2026-10-25）。

`scripts/score_chain_baseline.py` 是**验收尺子**。尺子自身口径错了，比被测代码错了
更危险——它会让人去改对的代码。本文件锁三件事：

  1. 覆盖率分母：下游卡由 `buyer` 承载时，`companies` 空是**合规**，不计分母；
     `buyer` 也空的才计入（那才是真缺口）。
  2. 数字判据：必须与渲染边界 `chain_lint.sanitize_text_no_numbers` 同口径，
     放行型号/等级代号（3D/3C/5G/L4/H800/35KV），只杀财务数值与占位符。
  3. KB 命中率是**信息项**，不得再进退出码（底座快照截止 2021-10，
     新上市公司必然不命中，做成硬门槛等于逼人放宽 chain_kb._role_of）。

每条都带阴性对照：既断言"该罚的罚了"，也断言"不该罚的没罚"。
"""
from __future__ import annotations

import importlib.util
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, "agents_core", "chart-generator"))


def _load_scorer():
    path = os.path.join(ROOT, "scripts", "score_chain_baseline.py")
    spec = importlib.util.spec_from_file_location("score_chain_baseline_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


scorer = _load_scorer()


def _graph(nodes: list[dict]) -> dict:
    return {"title": "测试产业链全景图", "core_product": "测试产品",
            "nodes": nodes, "edges": []}


def _n(name, *, stage="upstream", companies=None, buyer="", role_items=None):
    return {"name": name, "stage": stage, "companies": companies or [],
            "items": role_items or [], "buyer": buyer, "description": "",
            "is_core": False, "source_tier": "evidence"}


# ── 1. 覆盖率分母 ───────────────────────────────────────────────────────────

def test_downstream_with_buyer_excluded_from_denominator():
    """下游卡 + buyer 已填 → 不进分母（客户不是企业，这是设计不是缺口）。"""
    g = _graph([
        _n("显示面板", companies=["京东方A"]),
        _n("工业应用", stage="downstream", buyer="企业 / 专业用户",
           role_items=["工业笔记本"]),
    ])
    r = scorer.score_artifact(g, {"structure_cases": [], "forbidden_slot_labels": []})
    assert r["coverage"] == 1.0, r          # 分母只剩「显示面板」


def test_downstream_without_buyer_still_counts_as_gap():
    """下游卡 buyer 也空 → 真缺口，必须计入分母。

    这是阴性对照：如果为了指标好看把所有 downstream 一律排除，
    这张「没人说清谁在用」的卡就会被掩盖掉。
    """
    g = _graph([
        _n("显示面板", companies=["京东方A"]),
        _n("工业应用", stage="downstream", buyer=""),   # 没 buyer
    ])
    r = scorer.score_artifact(g, {"structure_cases": [], "forbidden_slot_labels": []})
    assert r["coverage"] == 0.5, r


def test_support_card_empty_is_a_real_gap():
    """配套层卡不靠 buyer 承载，companies 空就是缺口（如「运维与回收」）。"""
    g = _graph([
        _n("显示面板", companies=["京东方A"]),
        _n("运维与回收", stage="support", buyer=""),
    ])
    r = scorer.score_artifact(g, {"structure_cases": [], "forbidden_slot_labels": []})
    assert r["coverage"] == 0.5, r


def test_scene_rate_counts_buyer_filled_downstream():
    g = _graph([
        _n("工业应用", stage="downstream", buyer="企业用户"),
        _n("消费应用", stage="downstream", buyer=""),
        _n("显示面板", companies=["京东方A"]),
    ])
    r = scorer.score_artifact(g, {"structure_cases": [], "forbidden_slot_labels": []})
    assert r["scene_rate"] == 0.5, r


# ── 2. 数字判据与渲染边界同口径 ─────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "3D激光雷达与深度相机", "3C电子装配", "220KV海缆", "35KV",
    "5G通信模组", "L4级自动驾驶", "HBM3", "H800芯片",
])
def test_model_codes_are_not_number_violations(text):
    """型号/等级代号放行——旧判据把这些全报成违规（83 条里 24 条假阳性）。"""
    assert scorer.is_number_violation(text) is False, text


@pytest.mark.parametrize("text", [
    "毛利率区间25%-45%", "2", "XX公司1", "2024年营收",
])
def test_finance_numbers_are_violations(text):
    assert scorer.is_number_violation(text) is True, text


def test_placeholder_words_not_double_counted():
    """占位语由 PLACEHOLDERS 单独统计，数字判据不得重复报一次。"""
    assert scorer.is_number_violation("证据未覆盖2024") is False


def test_scorer_reuses_lint_judgment():
    """防回退：判据必须来自 chain_lint，不能自己写 `[0-9]`。"""
    src = open(os.path.join(ROOT, "scripts", "score_chain_baseline.py"),
               encoding="utf-8").read()
    assert "sanitize_text_no_numbers" in src
    assert "re.compile(r\"[0-9" not in src, "又写了粗暴的数字正则"


# ── 3. KB 命中率不得进退出码 ────────────────────────────────────────────────

def test_kb_threshold_removed_from_gates():
    """防回退：kb 不得再出现在 THRESHOLDS 里。"""
    assert "kb" not in scorer.THRESHOLDS, scorer.THRESHOLDS
    src = open(os.path.join(ROOT, "scripts", "score_chain_baseline.py"),
               encoding="utf-8").read()
    assert 'avg("kb_rate") < THRESHOLDS' not in src, "KB 命中率又被做成硬门槛了"
