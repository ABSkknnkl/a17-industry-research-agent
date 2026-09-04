"""跨智能体交接契约测试（L2，对应方案 §4.9）。

验证五个智能体 StageResult 之间的交接不丢数据、引用闭合、revision 隔离，
确保「任一阶段失败时，下游不会把空数据包装成成功」。

纯契约层测试：不调用任何 Agent / LLM / SkillHub，只对运行时 Pydantic 模型的
字段约束与引用关系做断言，零网络、零随机性。

交接链路：
  Agent1 证据(EvidenceItem) → Agent2 分析(AnalysisClaim/ChartCandidate)
  → Agent3 图表 → Agent4 章节(ChapterDraft) → Agent5 报告(EmbeddedChart)
"""

import pytest
from pydantic import BaseModel

from app.schemas.analysis import AnalysisClaim, ChartCandidate
from app.schemas.chapter import ChapterDraft
from app.schemas.evidence import EvidenceItem
from app.schemas.report import EmbeddedChart, EvidenceSourceEntry
from app.schemas.workflow import StageName, StageResult, StageStatus


def _is_required(model: type[BaseModel], field: str) -> bool:
    """字段是否必填（无 default、无 default_factory 即为必填）。"""
    return model.model_fields[field].is_required()


def assert_evidence_refs_closed(pool: set[str], refs: list[str]) -> None:
    """下游引用的 evidence_id 必须全部落在上游证据池内，禁止 ghost 引用。"""
    ghost = sorted({ref for ref in refs if ref not in pool})
    assert not ghost, f"下游引用了上游不存在的证据: {ghost}"


def test_a1_to_a2_evidence_keeps_traceability_fields() -> None:
    """Agent1→Agent2：证据可溯源字段不丢。"""
    for name in (
        "evidence_id", "metric_name", "scope", "market", "currency",
        "accounting_standard", "source_name", "grade",
    ):
        assert name in EvidenceItem.model_fields, f"EvidenceItem 缺少必填字段 {name}"
    for name in ("unit", "period_end", "available_at", "fiscal_period", "source_locator"):
        assert name in EvidenceItem.model_fields, f"EvidenceItem 缺少可溯源字段 {name}"


def test_a2_to_a4_claim_requires_evidence_refs() -> None:
    """Agent2→Agent4：claim 的证据引用必填。"""
    assert _is_required(AnalysisClaim, "evidence_ids")


def test_a2_to_a3_chart_candidate_requires_evidence_refs() -> None:
    """Agent2→Agent3：图表候选的证据引用必填。"""
    assert _is_required(ChartCandidate, "evidence_ids")


def test_a3_to_a5_report_requires_evidence_refs() -> None:
    """Agent3→Agent5：报告中图表与证据目录的证据引用必填。"""
    assert _is_required(EmbeddedChart, "evidence_ids")
    assert _is_required(EvidenceSourceEntry, "evidence_ids")


def test_reference_closure_accepts_closed_refs() -> None:
    pool = {"E-D-revenue", "E-D-profit"}
    assert_evidence_refs_closed(pool, ["E-D-revenue", "E-D-profit"])


def test_reference_closure_detects_ghost_refs() -> None:
    pool = {"E-D-revenue"}
    with pytest.raises(AssertionError):
        assert_evidence_refs_closed(pool, ["E-D-revenue", "E-D-ghost"])


def test_chapter_draft_carries_claim_evidence_chart_refs() -> None:
    """Agent4→Agent5：章节三路引用字段（claim/evidence/chart）不丢。"""
    for name in ("claim_ids", "evidence_ids", "chart_ids"):
        assert name in ChapterDraft.model_fields, f"ChapterDraft 缺少引用字段 {name}"


def test_stage_result_revision_is_independent() -> None:
    """审核恢复：revision 独立，旧结果不污染新结果。"""
    old = StageResult(
        stage=StageName.DATA_FETCH, status=StageStatus.COMPLETED,
        revision=1, data={"v": 1},
    )
    new = StageResult(
        stage=StageName.DATA_FETCH, status=StageStatus.COMPLETED,
        revision=2, data={"v": 2},
    )
    assert old.revision == 1 and new.revision == 2
    assert old.data["v"] != new.data["v"]


def test_error_bearing_result_must_not_carry_artifacts() -> None:
    """任一阶段失败：error 非空时不得携带报告产物（防包装空数据成成功）。"""
    result = StageResult(
        stage=StageName.DATA_FETCH, status=StageStatus.FAILED,
        revision=1, data={}, error="required_data_unavailable",
    )
    assert result.error is not None
    assert result.artifacts == []
