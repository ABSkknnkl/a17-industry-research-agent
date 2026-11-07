"""P0-6 / P0-2 / P0-5 三个 A3 生产缺陷的修复回归测试（2026-10-07）。

- P0-6：LLM suppressed_charts 的 requested_type 未过白名单 → pydantic Literal
  抛 ValidationError，且在批量解析循环内 → 整批图表丢失。修复后降级为 None。
- P0-2：`_synthesize_option_from_evidence` 手写 scatter/bubble 分支使用
  PRIMARY_COLOR 但未导入 → formulator 拒答时该图 NameError。修复后正常出图。
- P0-5：过滤管线末尾 `candidates = filtered or candidates` 静默放宽 →
  质量门全灭时被整体架空。修复后过滤为空就是空。
"""
import asyncio
from datetime import date
from typing import Any

from chart_generator import ChartGenerationRequest, ChartGeneratorAgent
from chart_generator.agent import VALID_CHART_TYPES
from chart_generator.models import ChartPreferences, InterpretationReport, SuppressedChart


def _chain_report() -> InterpretationReport:
    """带产业链证据的报告——走 LLM 不可用时的确定性 fallback 也能产图。"""
    evidence: dict[str, Any] = {}
    for index, (entity, value) in enumerate((("甲", 10.0), ("乙", -3.0), ("丙", 8.0)), 1):
        evidence[f"R{index}"] = {
            "record_id": f"R{index}", "domain": "financials", "entity": entity,
            "metric": "利润增长率", "value": value, "unit": "%", "period": "2026-06-30",
        }
    for index, value in enumerate((10.0, 13.0, 16.0), 4):
        evidence[f"R{index}"] = {
            "record_id": f"R{index}", "domain": "industry", "entity": "行业",
            "metric": "市场规模", "value": value, "unit": "亿元", "period": f"202{index - 3}-12-31",
        }
    return InterpretationReport.model_validate({
        "report_id": "P0X", "subject": "测试行业", "as_of": "2026-09-01",
        "status": "completed", "evidence_index": evidence,
    })


class _StubLLM:
    """可控的 LLM 桩：is_available=True，返回预置 llm_data。"""

    is_available = True
    settings = type("S", (), {"llm_timeout_seconds": 180.0})()

    def __init__(self, payload: dict[str, Any]):
        self._payload = payload

    async def run_skill_and_chart_loop(self, **kwargs: Any):
        return [], self._payload


# ── P0-6：非法 requested_type 不得中断整批解析 ──────────────────────────────

def test_p06_illegal_requested_type_in_suppressed_does_not_crash_batch():
    """suppressed_charts 里塞非法 requested_type，修复前：ValidationError 整批丢失。"""
    report = _chain_report()
    payload = {
        "suppressed_charts": [
            {"title": "被审查掉的图", "requested_type": "funnel_3d_glowing",  # 非法类型
             "reason_code": "llm_suppressed", "reason": "数据不足", "evidence_ids": ["R1"]},
        ],
        "charts": [
            {"title": "利润增长率对比", "chart_type": "bar", "evidence_ids": ["R1", "R2", "R3"],
             "insight_goal": "对比三家利润增长率", "recommended_chapter_id": "CH-04"},
        ],
    }
    agent = ChartGeneratorAgent(llm=_StubLLM(payload))
    result = asyncio.run(agent.run(ChartGenerationRequest(report=report), save_artifacts=False))

    # 关键断言：批处理没有被 ValidationError 中断，合法图表仍然产出
    assert any("利润增长率" in c.title and c.data_contract.get("points") for c in result.charts), \
        "P0-6 回归：非法 requested_type 导致整批图表丢失"
    # 非法类型降级为 None 而不是崩掉
    bad = [s for s in result.suppressed_charts if s.title == "被审查掉的图"]
    assert bad and bad[0].requested_type is None


def test_p06_legal_requested_type_preserved():
    """合法 requested_type 照常保留（不误伤）。"""
    report = _chain_report()
    payload = {
        "suppressed_charts": [
            {"title": "合理的压制", "requested_type": "radar",
             "reason_code": "llm_suppressed", "reason": "维度不足", "evidence_ids": ["R4"]},
        ],
        "charts": [],
    }
    agent = ChartGeneratorAgent(llm=_StubLLM(payload))
    result = asyncio.run(agent.run(ChartGenerationRequest(report=report), save_artifacts=False))
    kept = [s for s in result.suppressed_charts if s.title == "合理的压制"]
    assert kept and kept[0].requested_type == "radar"


def test_p06_suppressed_chart_model_accepts_all_valid_types():
    """白名单与模型 Literal 保持一致（防未来新增类型时两处漂移）。"""
    for t in VALID_CHART_TYPES:
        sc = SuppressedChart(title="x", requested_type=t, reason_code="r", reason="r")  # 不抛即过
        assert sc.requested_type == t


# ── P0-2：PRIMARY_COLOR 未导入 → formulator 拒答时手写分支 NameError ─────────

def test_p02_scatter_synthesize_branch_does_not_raise_nameerror():
    """直接调用 _synthesize_option_from_evidence 的 scatter 分支（monkeypatch formulate→None）。"""
    from chart_generator import agent as agent_mod
    from chart_generator.data_formulation import DataFormulator

    report = InterpretationReport.model_validate({
        "report_id": "P02", "subject": "测试行业", "as_of": "2026-09-01", "status": "completed",
        "evidence_index": {
            "R1": {"record_id": "R1", "domain": "financials", "entity": "甲", "metric": "毛利率", "value": 30.0, "unit": "%"},
            "R2": {"record_id": "R2", "domain": "financials", "entity": "甲", "metric": "净利率", "value": 12.0, "unit": "%"},
            "R3": {"record_id": "R3", "domain": "financials", "entity": "乙", "metric": "毛利率", "value": 25.0, "unit": "%"},
            "R4": {"record_id": "R4", "domain": "financials", "entity": "乙", "metric": "净利率", "value": 9.0, "unit": "%"},
        },
    })
    agent = ChartGeneratorAgent()

    orig = DataFormulator.formulate
    DataFormulator.formulate = staticmethod(lambda *a, **k: None)  # 强制走手写分支
    try:
        option = agent._synthesize_option_from_evidence(
            "scatter", ["R1", "R2", "R3", "R4"], "盈利散点", report,
        )
    finally:
        DataFormulator.formulate = orig

    assert option is None or isinstance(option, dict)  # 不抛 NameError 即修复生效
    if option is not None:
        assert "series" in option


# ── P0-5：过滤全灭时不得静默回退到未过滤候选 ─────────────────────────────────

def test_p05_empty_filter_result_is_not_silently_restored():
    """构造全部候选都会被质量门杀掉的场景：修复前 `or candidates` 会把它们全放回来。"""
    # boxplot 质量门要求 ≥15 证据点（且未显式请求）；这里每个候选只有 2 条证据 → 全灭。
    # 修复前：filtered 为空 → `filtered or candidates` 回退为未过滤列表 → 箱线图照样出图。
    # 注意：函数在 len(candidates) < 4 时提前返回，所以必须 ≥4 个候选才能进过滤循环。
    report = _chain_report()
    agent = ChartGeneratorAgent()

    from chart_generator.agent import _Candidate
    doomed = [
        _Candidate(title=f"箱线图{i}", chart_type="boxplot", option={"series": []},
                   evidence_ids=["R1", "R2"], goal="g", chapter="CH-04", score=100)
        for i in range(4)
    ]
    request = ChartGenerationRequest(report=report)
    conformed = agent._conform_diversity_deterministically(doomed, request)
    assert conformed == [], "P0-5 回归：被质量门全灭的候选被静默放回"
