"""analysis_notes 透传验收（2026-09-01 仲裁方案的配套接线，选项 A）。

根因背景：P0-2 起 Agent 1 把分析型/否决型诉求写入 ``analysis_notes``
"透传给 Agent 2"，但 Agent 2 从未消费它——白名单只取
``AnalysisRequest`` 声明字段，``intent_routing`` 整体被排除。仲裁改动
把显式否决的唯一交付通道压在这条链上后，缺口被放大。

本文件覆盖三处：
1. 契约：``AnalysisRequest.analysis_notes`` 可选、默认空（向后兼容）；
2. 提示词：非空时注入护栏要求，空时不注入（不得污染无否决的运行）；
3. 交接：Agent 2 从 ``fetch_result.data`` 顶层键取到 notes 并进入
   runtime prompt。
"""

from __future__ import annotations

import json

import pytest

from app.agents.data_interpreter.prompt_adapter import build_runtime_prompt
from app.agents.data_interpreter.service import DataInterpreterAgent
from app.integrations.llm.mock import MockAnalysisModel
from app.schemas.analysis import AnalysisRequest
from app.schemas.evidence import EvidenceItem
from app.schemas.workflow import StageName, StageResult, StageStatus
from app.workflow.stages import StageContext

_NOTE = "储能行业产能是否过剩（判断题，已被显式否决，不单独取数）"

_EVIDENCE = {
    "evidence_id": "E-NOTES-001",
    "metric_name": "新增装机量",
    "value": 88.0,
    "unit": "GWh",
    "period_end": "2025-12-31",
    "available_at": "2026-01-20",
    "audit_status": "not_applicable",
    "restatement_status": "not_applicable",
    "scope": "中国储能行业",
    "market": "中国内地",
    "exchange": "不适用",
    "security_type": "行业汇总",
    "currency": "CNY",
    "accounting_standard": "不适用",
    "corporate_action_adjustment": "not_applicable",
    "source_name": "行业协会",
    "source_locator": "年报表1",
    "grade": "B",
}


def _request(**overrides: object) -> AnalysisRequest:
    base: dict[str, object] = {
        "industry_topic": "储能行业",
        "market_scope": ["中国内地"],
        "security_types": ["行业汇总"],
        "reporting_currency": "CNY",
        "research_as_of": "2026-06-30",
        "focus_questions": ["行业供需格局如何？"],
        "evidence_items": [EvidenceItem.model_validate(_EVIDENCE)],
    }
    base.update(overrides)
    return AnalysisRequest.model_validate(base)


class RuntimeCapturingModel(MockAnalysisModel):
    def __init__(self) -> None:
        self.runtime_prompt = ""

    async def generate_analysis(self, *, system_prompt: str, runtime_prompt: str):
        self.runtime_prompt = runtime_prompt
        return await super().generate_analysis(
            system_prompt=system_prompt, runtime_prompt=runtime_prompt
        )


def test_analysis_request_notes_default_empty_for_backward_compatibility() -> None:
    """旧运行没有 analysis_notes 键：字段必须默认空列表，不得破坏既有契约。"""

    request = _request()
    assert request.analysis_notes == []


def test_analysis_request_accepts_notes() -> None:
    request = _request(analysis_notes=[_NOTE])
    assert request.analysis_notes == [_NOTE]


def test_prompt_injects_notes_with_guard_when_present() -> None:
    """非空时：payload 携带 notes，且 requirements 出现护栏条目
    （仅作为分析线索、不得当作已采集数据、不得虚构证据引用）。"""

    prompt = build_runtime_prompt(_request(analysis_notes=[_NOTE]))
    payload = json.loads(prompt)

    assert payload["analysis_request"]["analysis_notes"] == [_NOTE]
    guards = [
        requirement
        for requirement in payload["technical_output_contract"]["requirements"]
        if "analysis_notes" in requirement
    ]
    assert guards, "analysis_notes 非空时必须注入护栏要求"
    assert "不得" in guards[0], "护栏必须包含禁止性措辞"


def test_prompt_omits_notes_guard_when_empty() -> None:
    """空 notes 不得注入护栏——不污染无否决的常规运行。"""

    prompt = build_runtime_prompt(_request())
    payload = json.loads(prompt)

    assert payload["analysis_request"]["analysis_notes"] == []
    assert not any(
        "analysis_notes" in requirement
        for requirement in payload["technical_output_contract"]["requirements"]
    )


@pytest.mark.asyncio
async def test_agent2_receives_notes_from_fetch_result_data() -> None:
    """交接闭环：Agent 1 成功出口的顶层 analysis_notes 必须进入
    Agent 2 的 runtime prompt（经由 AnalysisRequest 白名单）。"""

    fetch_result = StageResult(
        stage=StageName.DATA_FETCH,
        status=StageStatus.COMPLETED,
        revision=1,
        data={
            "industry_topic": "储能行业",
            "market_scope": ["中国内地"],
            "security_types": ["行业汇总"],
            "reporting_currency": "CNY",
            "research_as_of": "2026-06-30",
            "focus_questions": ["行业供需格局如何？"],
            "evidence_items": [_EVIDENCE],
            "analysis_notes": [_NOTE],
        },
    )
    context = StageContext(
        project_id="project-notes",
        run_id="run-notes",
        revision=1,
        input_data={},
        previous_results={StageName.DATA_FETCH: fetch_result},
    )
    model = RuntimeCapturingModel()

    result = await DataInterpreterAgent(model=model).run(context)

    assert result.status == StageStatus.COMPLETED
    payload = json.loads(model.runtime_prompt)
    assert payload["analysis_request"]["analysis_notes"] == [_NOTE]
