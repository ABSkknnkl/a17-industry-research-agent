"""产业链图"用户意图闸门"测试（2026-10-21）。

用户裁定规则：
  · 未**明确**需要产业链图 → **不出产业链图**（改出别的图），且不调用豆包
  · 明确需要 → 出产业链图，并把用户输入透传给豆包

本文件验证这三件事，防止"意图闸门"被后续改动静默绕过
（历史上 provider 切换曾因调用方硬编码而从未生效）。
"""
import asyncio

from chart_generator import ChartGenerationRequest, ChartGeneratorAgent
from chart_generator.chain_intent import user_wants_industry_chain
from chart_generator.models import InterpretationReport


def _report(subject: str = "低空经济") -> InterpretationReport:
    """构造带产业链 segments 的报告；subject 默认**不含**产业链关键词。"""
    evidence = {}
    for index, (entity, value) in enumerate((("甲", 10.0), ("乙", -3.0), ("丙", 8.0)), 1):
        evidence[f"R{index}"] = {
            "record_id": f"R{index}", "domain": "industry_chain", "entity": entity,
            "metric": "环节", "value": value, "unit": "%", "period": "2026-06-30",
        }
    return InterpretationReport.model_validate({
        "report_id": "INTENT1", "subject": subject, "as_of": "2026-09-01",
        "status": "completed", "evidence_index": evidence,
        "industry_chain_segments": [
            {"segment_name": "基础材料", "stage": "upstream",
             "representative_companies": ["甲公司"], "key_products": ["碳纤维"],
             "evidence_record_ids": ["R1"]},
            {"segment_name": "整机制造", "stage": "midstream",
             "representative_companies": ["乙公司"], "key_products": ["eVTOL"],
             "evidence_record_ids": ["R2"]},
            {"segment_name": "物流运输", "stage": "downstream",
             "representative_companies": ["丙公司"], "key_products": [],
             "evidence_record_ids": ["R3"]},
        ],
    })


def _chain_charts(result):
    return [c for c in result.charts if c.chart_type == "industry_chain"]


# ── 1. 意图判定真值表 ──────────────────────────────────────────────────────

def test_strong_keyword_hits():
    assert user_wants_industry_chain("手机产业链")
    assert user_wants_industry_chain("光伏供应链结构")
    assert user_wants_industry_chain("白酒上中下游有哪些企业")


def test_plain_topic_misses():
    """只问行情/财务的主题不算"明确要产业链图"。"""
    assert not user_wants_industry_chain("手机")
    assert not user_wants_industry_chain("帮我分析一下白酒")
    assert not user_wants_industry_chain("光伏", ["品牌格局", "盈利能力"])


def test_defaulted_focus_is_not_user_intent():
    """adapters.py 默认注入的 focus_points 含"产业链"，不代表用户意图。"""
    assert not user_wants_industry_chain("手机", ["产业链", "龙头财务"], defaulted_focus=True)
    assert user_wants_industry_chain("手机", ["产业链"], defaulted_focus=False)


def test_weak_signal_needs_two():
    assert not user_wants_industry_chain("家电行业", ["梳理"])
    assert user_wants_industry_chain("家电行业", ["梳理", "有哪些公司"])


def test_explicit_overrides_everything():
    assert user_wants_industry_chain("白酒", explicit=True)
    assert not user_wants_industry_chain("手机产业链", explicit=False)


def test_overly_broad_words_excluded():
    """'环节''全景'这类词太宽，不得单独触发（财务语境常见）。"""
    assert not user_wants_industry_chain("手机生产环节成本")
    assert not user_wants_industry_chain("行业全景回顾")


# ── 2. 未明确要 → 不出产业链图 ─────────────────────────────────────────────

def test_chain_suppressed_when_intent_absent():
    result = asyncio.run(
        ChartGeneratorAgent().run(
            ChartGenerationRequest(report=_report()), save_artifacts=False))
    assert not _chain_charts(result), "用户未明确要产业链图时不应产出产业链图"
    codes = {s.reason_code for s in result.suppressed_charts}
    assert "industry_chain_not_requested" in codes


def test_chain_kept_when_intent_explicit():
    result = asyncio.run(
        ChartGeneratorAgent().run(
            ChartGenerationRequest(report=_report(), want_industry_chain=True),
            save_artifacts=False))
    assert _chain_charts(result), "显式要求时必须出产业链图"


def test_chain_kept_when_subject_has_keyword():
    """主题词自带"产业链"也算用户明确表达。"""
    result = asyncio.run(
        ChartGeneratorAgent().run(
            ChartGenerationRequest(report=_report("低空经济产业链")),
            save_artifacts=False))
    assert _chain_charts(result)


# ── 3. 未明确要 → 不调豆包 ─────────────────────────────────────────────────

def test_no_websearch_call_when_intent_absent(monkeypatch):
    """意图缺失时，联网补漏一次都不许发生（省月度额度）。"""
    calls = []

    async def _fake_fill(*_a, **_kw):
        calls.append(1)
        raise AssertionError("不应调用联网补漏")

    import chart_generator.agent as agent_mod
    monkeypatch.setattr(agent_mod, "fill_chain_gaps", _fake_fill)

    result = asyncio.run(
        ChartGeneratorAgent().run(
            ChartGenerationRequest(report=_report()), save_artifacts=False))
    assert not calls, "未明确要产业链图时不得调用联网补漏"
    assert not _chain_charts(result)
