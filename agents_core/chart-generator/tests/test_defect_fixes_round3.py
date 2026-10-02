"""Regression test for Round 3:
Verify ChartSkillLinter does not misclassify micro financial metrics (e.g. net_margin, revenue) as macro indicators
when a combo chart is present.
"""

from datetime import date
from pydantic import BaseModel, Field
from chart_generator.linter import ChartSkillLinter
from chart_generator.models import EvidenceRef


class SimpleCandidate(BaseModel):
    chart_id: str
    title: str
    chart_type: str
    evidence_ids: list[str] = Field(default_factory=list)


def test_chart_skill_linter_does_not_suppress_micro_metrics():
    linter = ChartSkillLinter()
    
    # 证据索引包含：宏观增加值 (domain="macro") 与 企业净利率 (domain="financials")
    evidence_index = {
        "M1": EvidenceRef(record_id="M1", domain="macro", metric="industrial_added_value", value=5.2, period=date(2026, 8, 31)),
        "F1": EvidenceRef(record_id="F1", domain="financials", metric="net_margin", entity="北方华创", value=22.5, period=date(2025, 12, 31)),
        "F2": EvidenceRef(record_id="F2", domain="financials", metric="net_margin", entity="中微公司", value=19.8, period=date(2025, 12, 31)),
    }
    
    # 候选图 1：宏微观综合组合图（包含 M1 与 F1）
    cand_combo = SimpleCandidate(
        chart_id="C_COMBO",
        title="行业产值与龙头企业净利率综合图",
        chart_type="combo",
        evidence_ids=["M1", "F1"],
    )
    
    # 候选图 2：微观财务净利率趋势图（包含 F1, F2）
    cand_micro_line = SimpleCandidate(
        chart_id="C_MICRO",
        title="主要企业净利率趋势",
        chart_type="line",
        evidence_ids=["F1", "F2"],
    )
    
    # 候选图 3：宏观单独趋势图（包含 M1）
    cand_macro_line = SimpleCandidate(
        chart_id="C_MACRO",
        title="工业增加值同比走势",
        chart_type="line",
        evidence_ids=["M1"],
    )
    
    violations = linter.lint([cand_combo, cand_micro_line, cand_macro_line], evidence_index)
    
    violated_titles = [v.chart_title for v in violations if v.code == "redundant_macro_metric"]
    
    # 宏观单独趋势图应该被判定为冗余（因为 combo 已经涵盖工业增加值）
    assert "工业增加值同比走势" in violated_titles
    # 净利率属于微观财务指标，绝不能被当作宏观指标误伤剔除！
    assert "主要企业净利率趋势" not in violated_titles
