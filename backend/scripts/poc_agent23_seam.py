"""PoC：验证 Agent 2 → Agent 3 证据池不对称导致的两类缺陷。

场景：用户在 DATA_INTERPRET 审核（REVISE）时编辑了 evidence_items（工作流
graph.py L539 将 edited_data.update 进 input_data），Agent 2 重跑时通过
revision 覆盖逻辑采用用户新证据（service.py L269-289），但 Agent 3 的
_source_payload（service.py L137-145）无 revision 覆盖，永远以 Agent 1 的
旧 evidence_items / chart_datasets 为准。

Case A：用户修正已有证据的数值（同 ID 新值）→ Agent 3 图表仍渲染旧值，
        且无任何标记（静默不一致）。
Case B：用户新增证据 → Agent 2 候选引用新 ID → Agent 3 无数据集可匹配 →
        图表被 suppress（丢失，但有 reason_code）。
"""

import asyncio
import json
from datetime import date

from app.agents.chart_generator.service import ChartGeneratorAgent
from app.schemas.chart import ChartDataset, ChartPoint
from app.schemas.evidence import EvidenceItem
from app.schemas.workflow import StageName, StageResult, StageStatus
from app.workflow.stages import StageContext


def _evidence(evidence_id: str, value) -> dict:
    return EvidenceItem(
        evidence_id=evidence_id,
        metric_name="行业收入",
        value=value,
        unit="亿元",
        period_end=date(2024, 12, 31),
        available_at=date(2025, 1, 1),
        scope="行业",
        market="中国",
        exchange="不适用",
        security_type="不适用",
        currency="CNY",
        accounting_standard="不适用",
        source_name="问财",
        source_locator="https://example.com",
        grade="A",
    ).model_dump(mode="json")


def _dataset(value_2024) -> dict:
    return ChartDataset(
        dataset_id="DS-REVENUE",
        kind="time_series",
        metric_name="行业收入",
        unit="亿元",
        currency="CNY",
        points=[
            ChartPoint(label="2024", value=value_2024, series="行业",
                       period_end=date(2024, 12, 31), evidence_id="E-001"),
            ChartPoint(label="2025", value=120, series="行业",
                       period_end=date(2025, 12, 31), evidence_id="E-002"),
        ],
        evidence_ids=["E-001", "E-002"],
    ).model_dump(mode="json")


def _context(input_evidence: list[dict], candidates: list[dict]) -> StageContext:
    return StageContext(
        project_id="P-1",
        run_id="R-1",
        revision=2,  # 已推进：模拟 review 后重跑
        input_data={"evidence_items": input_evidence},
        previous_results={
            StageName.DATA_FETCH: StageResult(
                stage=StageName.DATA_FETCH,
                status=StageStatus.COMPLETED,
                revision=1,
                data={
                    "evidence_items": [_evidence("E-001", 100), _evidence("E-002", 120)],
                    "chart_datasets": [_dataset(100)],  # Agent 1 旧数据：100
                },
            ),
            StageName.DATA_INTERPRET: StageResult(
                stage=StageName.DATA_INTERPRET,
                status=StageStatus.COMPLETED,
                revision=2,
                data={"chart_candidates": candidates},
            ),
        },
    )


def _candidate(evidence_ids: list[str]) -> dict:
    return {
        "title": "行业收入趋势",
        "chart_type": "line",
        "evidence_ids": evidence_ids,
        "analysis_purpose": "trend",
        "insight_goal": "观察行业收入变化",
    }


async def main() -> None:
    agent = ChartGeneratorAgent()

    # Case A：用户把 E-001 从 100 修正为 999（同 ID）
    ctx_a = _context(
        input_evidence=[_evidence("E-001", 999), _evidence("E-002", 120)],
        candidates=[_candidate(["E-001", "E-002"])],
    )
    result_a = await agent.run(ctx_a)
    print("[Case A] result.data keys:", sorted(result_a.data.keys()))
    print("[Case A] status:", result_a.status, "error:", result_a.error)
    raw_a = json.dumps(result_a.data, ensure_ascii=False)
    print(f"[Case A] 含 100(旧值)={'100' in raw_a}, 含 999(用户修正)={'999' in raw_a}")
    charts_a = result_a.data.get("charts", [])
    if charts_a:
        print("[Case A] chart[0] keys:", sorted(charts_a[0].keys()))
        spec = charts_a[0].get("spec") or charts_a[0]
        print("[Case A] series 数据:", json.dumps(
            spec.get("option", {}).get("series", "N/A"), ensure_ascii=False))

    # Case B：用户新增 E-009，Agent 2 候选引用它
    ctx_b = _context(
        input_evidence=[_evidence("E-001", 100), _evidence("E-002", 120), _evidence("E-009", 50)],
        candidates=[_candidate(["E-009"])],
    )
    result_b = await agent.run(ctx_b)
    print("\n[Case B] result.data keys:", sorted(result_b.data.keys()))
    print("[Case B] status:", result_b.status, "error:", result_b.error)
    raw_b = json.dumps(result_b.data, ensure_ascii=False)
    print("[Case B] full data:", raw_b[:800])


asyncio.run(main())
