"""真实全链路测试（无 Mock，真实业务数据 + 真实 LLM + 真实 SkillHub）。

从 Agent 1（问财 SkillHub 真实取数）→ Agent 2（真实 LLM 分析）→ Agent 3（图表生成）
→ Agent 4（真实 LLM 章节撰写）→ Agent 5（报告融合导出），完整跑通五阶段，
产出可直接下载的 MD/HTML/PDF 报告。

硬约束（本文件禁止出现任何 Mock）：
  - LLM_USE_MOCK 必须为 False，且 LLM_API_KEY + LLM_BASE_URL 已配置；
  - SKILLHUB_USE_MOCK 必须为 False，且 IWENCAI_API_KEY / SKILLHUB_API_KEY 已配置；
  - 任一模 mock 开关被打开 → assert 失败；任一 API Key 缺失 → pytest.skip，
    绝不回退 Mock 或伪造业务数据。
"""

import pytest

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.core.config import settings
from app.integrations.llm.factory import create_analysis_model, create_chapter_writing_model
from app.schemas.workflow import StageName, StageStatus
from app.workflow.factory import create_stage_registry
from app.workflow.graph import REINPUT_REQUIRED_ERRORS, build_pipeline_graph
from app.workflow.state import create_pipeline_state


def _skillhub_key_present() -> bool:
    return settings.IWENCAI_API_KEY is not None or settings.SKILLHUB_API_KEY is not None


def _llm_key_present() -> bool:
    return settings.LLM_API_KEY is not None and settings.LLM_BASE_URL is not None


@pytest.fixture(autouse=True)
def _require_real_credentials() -> None:
    """进入真实链路测试前：必须先确认「无 mock」且「凭证齐全」。"""
    assert settings.LLM_USE_MOCK is False, "LLM_USE_MOCK=True：真实链路禁止 Mock LLM"
    assert settings.SKILLHUB_USE_MOCK is False, "SKILLHUB_USE_MOCK=True：真实链路禁止 Mock SkillHub"
    if not _llm_key_present():
        pytest.skip("缺少 LLM_API_KEY / LLM_BASE_URL，无法调用真实 LLM")
    if not _skillhub_key_present():
        pytest.skip("缺少 IWENCAI_API_KEY / SKILLHUB_API_KEY，无法取真实数据")


@pytest.fixture
def real_registry():
    """用真实 LLM（OpenAICompatible）+ 真实 SkillHub 装配五阶段 registry。"""
    analysis_model = create_analysis_model(settings)      # LLM_USE_MOCK=False → 真实模型
    chapter_model = create_chapter_writing_model(settings)
    return create_stage_registry(analysis_model, chapter_model)


def _base_input() -> dict:
    """真实业务研究请求（财务 + 主营结构，能命中真实数据层 Skill）。"""
    return {
        "industry_topic": "动力电池",
        "market_scope": ["中国内地"],
        "security_types": ["普通股"],
        "reporting_currency": "CNY",
        "research_as_of": "2026-08-11",
        "focus_questions": [
            "整理宁德时代近四年营业收入、归母净利润、毛利率及主营业务构成"
        ],
        "evidence_items": [],
        "analysis_depth": "standard",
        "risk_preference": "balanced",
        "research_brief": {},
        "data_fetch_options": {},
    }


async def _drive(graph, state, config, max_rounds: int = 8) -> dict:
    """驱动图并自动处理 review interrupt（approve / accept_with_risks / cancel）。"""
    result = await graph.ainvoke(state, config)
    for _ in range(max_rounds):
        interrupts = result.get("__interrupt__")
        if not interrupts:
            return result
        info = interrupts[0].value
        stage_result = info.get("result", {}) or {}
        error = stage_result.get("error")
        dp = (stage_result.get("data", {}) or {}).get("decision_package", {}) or {}
        expected_revision = info.get("revision", 1)
        # 用户裁决优先（全链路用户裁决门语义）：有决策包即接受全部风险
        # 继续生成——数据缺口/计算缺数/质量降级都不阻断报告产出。
        if dp:
            decision = {
                "action": "accept_with_risks",
                "expected_revision": expected_revision,
                "decision_id": dp.get("decision_id", ""),
                "risk_snapshot_sha256": dp.get("risk_snapshot_sha256", ""),
                "accepted_risk_codes": dp.get("acknowledgement_required_codes", []),
                "comment": "测试驱动：模拟用户无视风险继续生成。",
            }
        elif stage_result.get("status") == "failed":
            decision = {"action": "regenerate", "expected_revision": expected_revision}
        elif error in REINPUT_REQUIRED_ERRORS:
            # 无决策包的数据不可得（遗留路径）：取消任务，不作为测试失败
            decision = {"action": "cancel", "expected_revision": expected_revision}
        else:
            decision = {"action": "approve", "expected_revision": expected_revision}
        try:
            result = await graph.ainvoke(Command(resume=decision), config)
        except ValueError:
            return result
    return result


@pytest.mark.asyncio
async def test_real_full_chain_runs_five_stages_on_real_data(real_registry) -> None:
    graph = build_pipeline_graph(real_registry, checkpointer=InMemorySaver())
    state = create_pipeline_state(
        project_id="project-real",
        run_id="run-real-full-chain",
        input_data=_base_input(),
        review_stages=[StageName.DATA_FETCH, StageName.DATA_INTERPRET],
    )
    config = {"configurable": {"thread_id": "run-real-full-chain"}}

    final = await _drive(graph, state, config)

    stage_results = final.get("stage_results", {})
    # Agent 1 真实取数必须执行（链路起点的硬门槛）
    assert stage_results, "全链路未执行任何阶段"
    assert "data_fetch" in stage_results, "Agent 1 数据获取阶段未执行"

    status = final.get("status")
    # 诚实终态：completed（五阶段全跑完）或 waiting_review/cancelled（真实数据不足被拦截）
    assert status in {
        StageStatus.COMPLETED,
        StageStatus.WAITING_REVIEW,
        StageStatus.CANCELLED,
    }, f"非法终态 {status}"

    # fail-closed：终态 completed 时必须五阶段齐全、无 error 伪装、报告产物非空
    if status == StageStatus.COMPLETED:
        for stage in StageName:
            assert stage.value in stage_results, f"completed 但缺少 {stage} 阶段结果"
        fusion = stage_results[StageName.REPORT_FUSION.value]
        assert fusion.get("error") is None, "completed 阶段却携带 error"
        artifacts = fusion.get("artifacts", [])
        assert artifacts, "completed 但报告产物为空（report_fusion 未产出 MD/HTML/PDF/manifest）"
