"""A3 用户问题驱动选图 · off / observe / apply 三档离线集成验证（方案第 4.4、6 节）。

用冻结的新能源汽车 A2 产物与离线模型夹具，不调用外部服务、不启用真实选图模型。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from chart_generator.agent import ChartGeneratorAgent
from chart_generator.config import Settings
from chart_generator.models import ChartGenerationRequest, ChartPreferences, InterpretationReport
from chart_generator.question_planner import parse_question_briefs

GOLDEN_A2 = (
    Path(__file__).resolve().parents[3]
    / "output/a3_refactor_validation/runs/a3-live-20261110235216656541/artifacts"
    / "interpretation_report.json"
)

QUESTIONS = [
    "2021—2025 年新能源汽车销量、渗透率及出口量如何变化？不同统计口径会如何影响结论？请配趋势图。",
    "比亚迪、长安汽车、赛力斯 2023—2025 年的营收、毛利率及经营现金流如何分化？",
    "宁德时代、亿纬锂能与整车企业在研发强度、利润率方面有何差异？为什么应按环节分组分析？",
]


class OfflinePlanLLM:
    """模拟结构化选卡模型：只引用 prompt 里真实存在的候选卡。"""

    is_available = False  # 让旧选型分支走确定性候选，保证离线可复现

    def __init__(self) -> None:
        self.calls = 0

    async def select_cards(self, system_prompt: str, user_prompt: str) -> str:
        self.calls += 1
        payload = json.loads(user_prompt)
        cards = payload.get("candidate_cards") or []
        selections = []
        for q in payload.get("questions") or []:
            pick = cards[0]["card_id"] if cards else ""
            selections.append({
                "question_id": q["question_id"],
                "needs_chart": bool(q.get("requests_chart")) or bool(pick),
                "primary_card_ids": [pick] if pick else [],
                "supporting_card_ids": [],
                "rationale": "离线夹具：取首张合法候选卡",
            })
        return json.dumps({"selections": selections}, ensure_ascii=False)


@pytest.fixture(scope="module")
def golden_report() -> InterpretationReport:
    if not GOLDEN_A2.exists():
        pytest.skip(f"冻结黄金样本不存在：{GOLDEN_A2}")
    return InterpretationReport.model_validate(json.loads(GOLDEN_A2.read_text(encoding="utf-8")))


def _run(mode: str, report: InterpretationReport, tmp_path: Path):
    briefs = [b.model_dump(mode="json") for b in parse_question_briefs(QUESTIONS)]
    request = ChartGenerationRequest(
        report=report,
        preferences=ChartPreferences(max_charts=6),
        question_plan_mode=mode,
        question_briefs=briefs if mode != "off" else [],
    )
    llm = OfflinePlanLLM()
    agent = ChartGeneratorAgent(settings=Settings(output_dir=tmp_path), llm=llm)
    result = asyncio.run(agent.run(request, save_artifacts=False))
    return result, llm


def test_off_keeps_legacy_behavior(golden_report, tmp_path):
    result, llm = _run("off", golden_report, tmp_path / "off")
    assert result.question_plan is None
    assert llm.calls == 0
    assert result.charts, "off 应与既有链路一样产出图表"


def test_observe_writes_shadow_plan_without_changing_charts(golden_report, tmp_path):
    off, _ = _run("off", golden_report, tmp_path / "off2")
    observed, llm = _run("observe", golden_report, tmp_path / "observe")
    assert observed.question_plan is not None
    assert observed.question_plan.mode == "observe"
    assert observed.question_plan.coverage, "影子计划也要有覆盖状态"
    assert [c.chart_id for c in observed.charts] == [c.chart_id for c in off.charts]
    assert observed.question_coverage == off.question_coverage
    assert llm.calls == 0, "observe 本实现不额外消耗模型调用"


def test_apply_settles_coverage_and_calls_llm_once(golden_report, tmp_path):
    result, llm = _run("apply", golden_report, tmp_path / "apply")
    assert result.question_plan is not None
    assert result.question_plan.mode == "apply"
    assert llm.calls == 1, "apply 每次 A3 执行至多一次选卡调用"
    statuses = {c.status for c in result.question_plan.coverage}
    assert statuses <= {"published", "partially_published", "not_needed",
                        "not_published", "evidence_gap", "capability_gap"}
    assert {c.question_id for c in result.question_plan.coverage} == {"Q-1", "Q-2", "Q-3"}
    assert result.question_coverage, "apply 需同步既有 question_coverage 供 A4/A5 读取"
    assert all("question_id" in item for item in result.question_coverage)
    assert {c.chart_id for c in result.charts}, "apply 不得清空既有发布图"


def test_apply_compacts_frozen_nev_charts_before_rendering(tmp_path):

    frozen = GOLDEN_A2.parents[4] / (
        "a3_question_plan_probe/live_runs/runs/charts-20261111233013-07f9c10f/request.json"
    )
    if not frozen.is_file():
        pytest.skip("本轮 16 图的冻结输入不存在")
    request = ChartGenerationRequest.model_validate_json(frozen.read_text(encoding="utf-8"))
    agent = ChartGeneratorAgent(settings=Settings(output_dir=tmp_path), llm=OfflinePlanLLM())
    result = asyncio.run(agent.run(request))
    assert result.question_plan is not None
    links = {cid for row in result.question_plan.coverage for cid in row.chart_ids}
    assert {c.chart_id for c in result.charts} == links
    assert sum(c.chart_type == "combo" for c in result.charts) == 2
    assert any(
        len(c.data_contract["points"]) == 12
        and c.data_contract["comparison_group"] == "电池组"
        and {p["metric"] for p in c.data_contract["points"]} == {"gross_margin", "net_margin"}
        for c in result.charts
    )
    assert len(result.charts) < 16
    assert any(row.status == "partially_published" for row in result.question_plan.coverage)
    art = Path(result.artifact_dir)
    assert {p.stem for p in (art / "charts").glob("*.svg")} == links
    assert (art / "preview.html").read_text().count("<svg ") == len(result.charts)
