from datetime import date
from unittest.mock import MagicMock
import pytest

from chart_generator.agent import ChartGeneratorAgent
from chart_generator.models import EvidenceRef


def test_evidence_binning_preserves_macro_timeseries():
    agent = ChartGeneratorAgent()

    # 30 company timeseries records across multiple companies and metrics
    evidence = []
    for i in range(10):
        for yr in ["2022", "2023", "2024"]:
            evidence.append(EvidenceRef(
                record_id=f"c_{i}_{yr}",
                domain="financials",
                entity=f"企业{i}",
                metric="营业收入",
                value=100.0,
                period=date(int(yr), 12, 31),
            ))
    # 3 macro records
    for yr in ["2022", "2023", "2024"]:
        evidence.append(EvidenceRef(
            record_id=f"m_{yr}",
            domain="macro",
            entity="全国",
            metric="国内生产总值(GDP)",
            value=1300000.0,
            period=date(int(yr), 12, 31),
        ))

    binned = agent._bin_evidence_for_prompt(evidence, max_total=60)
    binned_ids = [b["record_id"] for b in binned]

    # Macro records MUST NOT be starved out by company financials
    assert any("m_" in bid for bid in binned_ids)


def test_chart_chapter_fallback_semantic():
    agent = ChartGeneratorAgent()
    # Chart with debt ratio shouldn't default to CH-04
    assigned_ch5 = agent._infer_chart_chapter(
        title="核心企业资产负债率对比",
        chart_type="horizontal_bar",
        domain="financials",
        metrics=["debt_ratio", "资产负债率"],
    )
    assert assigned_ch5 == "CH-05"

    assigned_ch6 = agent._infer_chart_chapter(
        title="全国国内生产总值(GDP)走势",
        chart_type="line",
        domain="macro",
        metrics=["GDP"],
    )
    assert assigned_ch6 == "CH-06"
