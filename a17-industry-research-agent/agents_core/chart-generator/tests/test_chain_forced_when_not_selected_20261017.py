"""「有产业链数据就必须有一张产业链图」（2026-10-17）。

实测背景：run-20261017102225 的 A2 产出了 15 节点 / 13 边拓扑，但 A3 的 LLM 选型
只出了 6 张财务类图表，**产业链图整张缺失**（候选数已顶满 max_charts，确定性兜底的
追加分支进不去）。产业链图是 A3 的招牌交付物，不能靠选型运气，故加确定性补入。
"""
from __future__ import annotations

import asyncio

import pytest

from chart_generator import ChartGenerationRequest, ChartGeneratorAgent
from chart_generator.agent import _Candidate
from chart_generator.config import Settings
from chart_generator.models import ChartPreferences, InterpretationReport


def _report(with_topology: bool = True, with_segments: bool = True) -> InterpretationReport:
    evidence = {
        f"R{i}": {
            "record_id": f"R{i}", "domain": "financials", "entity": f"公司{i}",
            "metric": "营业收入", "value": 100.0 + i, "unit": "亿元",
            "period": "2026-06-30",
        }
        for i in range(1, 9)
    }
    payload = {
        "report_id": "FORCE1", "subject": "低空经济", "as_of": "2026-09-01",
        "status": "completed", "evidence_index": evidence,
    }
    if with_segments:
        payload["industry_chain_segments"] = [
            {"segment_name": "基础材料", "stage": "upstream",
             "representative_companies": ["甲材料"], "key_products": ["碳纤维"],
             "evidence_record_ids": ["R1"]},
            {"segment_name": "整机制造", "stage": "midstream",
             "representative_companies": ["乙整机"], "key_products": ["eVTOL"],
             "evidence_record_ids": ["R2"]},
            {"segment_name": "物流运输", "stage": "downstream",
             "representative_companies": ["丙物流"], "key_products": [],
             "evidence_record_ids": ["R3"]},
        ]
    if with_topology:
        payload["industry_chain_topology"] = {
            "title": "低空经济产业链", "core_product": "eVTOL",
            # 字段名与 A2 真实产出对齐：节点名是 label（不是 name），否则被判"缺名称"
            "nodes": [
                {"id": "n1", "label": "碳纤维", "stage": "upstream",
                 "companies": ["甲材料"], "evidence_ids": ["R1"]},
                {"id": "n2", "label": "整机", "stage": "midstream", "is_core": True,
                 "companies": ["乙整机"], "evidence_ids": ["R2"]},
                {"id": "n3", "label": "物流", "stage": "downstream",
                 "companies": ["丙物流"], "evidence_ids": ["R3"]},
            ],
            "edges": [
                {"source": "n1", "target": "n2", "label": "碳纤维", "flow": "material"},
                {"source": "n2", "target": "n3", "label": "整机交付", "flow": "material"},
            ],
        }
    return InterpretationReport.model_validate(payload)


def _bar_candidate(index: int) -> _Candidate:
    """6 张互不相同的财务图，用来把 max_charts 顶满、逼出"选型没选产业链"。"""
    return _Candidate(
        title=f"图表{index}",
        chart_type="bar",
        option={
            "xAxis": {"data": [f"公司{index}", f"公司{index + 4}"]},
            "yAxis": {"name": "亿元"},
            "series": [{"type": "bar", "data": [float(index), float(index) + 1]}],
        },
        evidence_ids=[f"R{index}", f"R{index + 4}"],
        goal=f"对比指标{index}",
        chapter="CH-03",
    )


def test_chain_chart_is_forced_in_when_selection_skipped_it(monkeypatch):
    settings = Settings(llm_api_key="dummy", llm_model="dummy-model")
    agent = ChartGeneratorAgent(settings=settings)

    candidates = [_bar_candidate(i) for i in range(1, 7)]

    async def _fake_generate(request, record):
        return ([], candidates, [])

    monkeypatch.setattr(agent, "_run_llm_generation", _fake_generate)

    result = asyncio.run(
        agent.run(
            ChartGenerationRequest(want_industry_chain=True, report=_report(),
                preferences=ChartPreferences(max_charts=6),
            ),
            save_artifacts=False,
        )
    )
    chain = [c for c in result.charts if c.chart_type == "industry_chain"]
    assert chain, "选型没覆盖产业链图时必须确定性补入"
    assert chain[0].render_mode == "svg"
    # 2026-10-21：版式已收敛到三列目录式 —— 用"读法提示 + 无 polyline"验证确实出图，
    # 不再断言旧四列版式的流线（<polyline 恒为 0 才是当前契约）。
    assert chain[0].inline_svg
    assert "读法：自上而下扫一列" in chain[0].inline_svg
    assert "<polyline" not in chain[0].inline_svg
    # 补入是"加一张"，不把原有财务图挤掉
    assert [c for c in result.charts if c.chart_type != "industry_chain"], "原有图表不得被顶掉"


def test_chain_forced_from_topology_even_without_segments(monkeypatch):
    """只有拓扑、没有扁平 segments 的报告也要出图（兜底映射的输入可能缺一块）。"""
    settings = Settings(llm_api_key="dummy", llm_model="dummy-model")
    agent = ChartGeneratorAgent(settings=settings)
    candidates = [_bar_candidate(i) for i in range(1, 7)]

    async def _fake_generate(request, record):
        return ([], candidates, [])

    monkeypatch.setattr(agent, "_run_llm_generation", _fake_generate)

    result = asyncio.run(
        agent.run(
            ChartGenerationRequest(want_industry_chain=True, report=_report(with_topology=True, with_segments=False),
                preferences=ChartPreferences(max_charts=6),
            ),
            save_artifacts=False,
        )
    )
    chain = [c for c in result.charts if c.chart_type == "industry_chain"]
    assert chain, "仅有拓扑时也必须补出产业链图"
    assert chain[0].chain_graph and chain[0].chain_graph.get("nodes")


def test_no_forced_chain_when_no_chain_data(monkeypatch):
    """没有产业链数据时不得凭空造图（避免"为了凑数生成空图"）。"""
    settings = Settings(llm_api_key="dummy", llm_model="dummy-model")
    agent = ChartGeneratorAgent(settings=settings)
    candidates = [_bar_candidate(i) for i in range(1, 7)]

    async def _fake_generate(request, record):
        return ([], candidates, [])

    monkeypatch.setattr(agent, "_run_llm_generation", _fake_generate)

    result = asyncio.run(
        agent.run(
            ChartGenerationRequest(want_industry_chain=True, report=_report(with_topology=False, with_segments=False),
                preferences=ChartPreferences(max_charts=6),
            ),
            save_artifacts=False,
        )
    )
    assert not [c for c in result.charts if c.chart_type == "industry_chain"]
