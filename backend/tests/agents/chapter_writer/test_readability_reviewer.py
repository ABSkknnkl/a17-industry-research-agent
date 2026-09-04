import pytest
from pydantic import SecretStr

from app.agents.chapter_writer.service import ChapterWriterAgent
from app.core.config import Settings
from app.integrations.llm.factory import create_readability_model
from app.integrations.llm.mock import MockChapterWritingModel, MockReadabilityModel
from app.schemas.analysis import AnalysisResult
from app.schemas.chapter import ChapterWritingResult
from app.schemas.readability import ReadabilityFinding, ReadabilityReport
from app.schemas.workflow import StageName, StageResult, StageStatus
from app.workflow.stages import StageContext


def _context(analysis: AnalysisResult, *, run_id: str) -> StageContext:
    return StageContext(
        project_id="project-readability",
        run_id=run_id,
        revision=1,
        previous_results={
            StageName.DATA_INTERPRET: StageResult(
                stage=StageName.DATA_INTERPRET,
                status=StageStatus.APPROVED,
                data=analysis.model_dump(mode="json"),
                evidence_sources=["E-001"],
            ),
            StageName.CHART_GENERATE: StageResult(
                stage=StageName.CHART_GENERATE,
                status=StageStatus.COMPLETED,
                data={"mock": True},
            ),
        },
    )


class CountingChapterModel(MockChapterWritingModel):
    def __init__(self) -> None:
        self.calls = 0

    async def generate_chapter(self, *, system_prompt: str, runtime_prompt: str):
        self.calls += 1
        return await super().generate_chapter(
            system_prompt=system_prompt,
            runtime_prompt=runtime_prompt,
        )


class SpyReviewer(MockReadabilityModel):
    """记录评审器收到的全部入参（输入隔离断言依据）。"""

    def __init__(self) -> None:
        super().__init__(score=1.0)
        self.calls: list[dict[str, str]] = []

    async def review_paragraph(
        self, *, paragraph_text: str, kind: str
    ) -> ReadabilityReport:
        self.calls.append({"paragraph_text": paragraph_text, "kind": kind})
        return await super().review_paragraph(
            paragraph_text=paragraph_text, kind=kind
        )


@pytest.mark.asyncio
async def test_readability_does_not_affect_deterministic_passed(
    chapter_analysis_result: AnalysisResult,
) -> None:
    # 4.3.1 软硬门分离（最关键契约）：硬门全合规时，
    # 即使评审器给出极低软分，passed 仍为 True。
    low_score_reviewer = MockReadabilityModel(score=0.3)
    agent = ChapterWriterAgent(
        model=MockChapterWritingModel(),
        readability_model=low_score_reviewer,
        readability_threshold=0.6,
    )

    stage_result = await agent.run(_context(chapter_analysis_result, run_id="run-rb-softgate"))
    writing = ChapterWritingResult.model_validate(stage_result.data)

    assert stage_result.status == StageStatus.COMPLETED
    assert writing.quality.passed is True
    assert writing.readability_reports
    assert writing.readability_reports[0].score < 0.5
    assert any(
        request.request_id == "READABILITY"
        for request in writing.collaboration_requests
    )
    # 软门不写入硬门产物：quality.issues 不含可读性段落 id。
    assert not any("P-" in issue for issue in writing.quality.issues)


@pytest.mark.asyncio
async def test_reviewer_hits_limit_and_requests_human(
    chapter_analysis_result: AnalysisResult,
) -> None:
    # 4.3.2 重写上限（防死循环）：must_fix 反复出现时，
    # 改写轮次有限，达上限后转人工而非无限打回。
    never_good = MockReadabilityModel(
        score=0.9,
        findings=[
            ReadabilityFinding(
                dimension="通顺度",
                severity="must_fix",
                reason="主谓搭配混乱，读者无法定位断言主体。",
                rewrite_hint="拆分为结论句与证据句。",
            )
        ],
    )
    counting = CountingChapterModel()
    agent = ChapterWriterAgent(
        model=counting,
        readability_model=never_good,
        readability_threshold=0.6,
        readability_max_rewrites=2,
    )

    stage_result = await agent.run(_context(chapter_analysis_result, run_id="run-rb-limit"))
    writing = ChapterWritingResult.model_validate(stage_result.data)

    assert stage_result.status == StageStatus.COMPLETED
    assert writing.quality.passed is True  # 软门不改硬门结论
    assert any(
        request.request_id == "READABILITY"
        for request in writing.collaboration_requests
    )
    assert any(report.needs_human_review for report in writing.readability_reports)
    # 每章 1 次初稿 + 2 次改写 = 3 次；7 章 = 21 次，
    # 证明改写循环有限终止。
    assert counting.calls == 21

@pytest.mark.asyncio
async def test_reviewer_only_receives_paragraph_text_and_kind(
    chapter_analysis_result: AnalysisResult,
) -> None:
    # 4.3.3 输入隔离：评审器只收到 paragraph_text 与 kind，
    # 不吥 summary、标题、key_points 或人工 comment。
    spy = SpyReviewer()
    agent = ChapterWriterAgent(model=MockChapterWritingModel(), readability_model=spy)

    stage_result = await agent.run(_context(chapter_analysis_result, run_id="run-rb-spy"))
    writing = ChapterWritingResult.model_validate(stage_result.data)

    assert spy.calls
    for call in spy.calls:
        assert set(call) == {"paragraph_text", "kind"}
        assert call["kind"] == "analysis"
    paragraph_texts = {
        paragraph.text
        for chapter in writing.chapters
        for section in chapter.sections
        for paragraph in section.paragraphs
        if paragraph.kind == "analysis"
    }
    assert all(call["paragraph_text"] in paragraph_texts for call in spy.calls)
    summaries = {chapter.summary for chapter in writing.chapters}
    titles = (
        {chapter.title for chapter in writing.chapters}
        | {
            section.title
            for chapter in writing.chapters
            for section in chapter.sections
        }
    )
    leaked = [
        call for call in spy.calls if call["paragraph_text"] in (summaries | titles)
    ]
    assert leaked == []

@pytest.mark.asyncio
async def test_readability_disabled_by_default_produces_empty_reports(
    chapter_analysis_result: AnalysisResult,
) -> None:
    # 评审器默认不启用：不传 readability_model 时，
    # 结果不含任何可读性产物，graph 行为与历史版本一致。
    agent = ChapterWriterAgent(model=CountingChapterModel())

    stage_result = await agent.run(
        _context(chapter_analysis_result, run_id="run-rb-default-off")
    )
    writing = ChapterWritingResult.model_validate(stage_result.data)

    assert stage_result.status == StageStatus.COMPLETED
    assert writing.readability_reports == []
    assert writing.quality.passed is True
    assert agent._model.calls == 7

@pytest.mark.asyncio
async def test_mock_readability_model_conforms_to_protocol() -> None:
    model = MockReadabilityModel()
    assert model.model_name == "mock-readability-reviewer"
    report = await model.review_paragraph(
        paragraph_text="样本企业数量为10家；鉴于样本仍需扩充，该结论的适用范围有限。",
        kind="analysis",
    )
    assert isinstance(report, ReadabilityReport)
    assert report.score == 1.0
    assert report.findings == []
    assert report.needs_human_review is False


def test_factory_creates_readability_model_in_mock_mode() -> None:
    settings = Settings(ENVIRONMENT="test", LLM_USE_MOCK=True)
    model = create_readability_model(settings)
    assert model.model_name == "mock-readability-reviewer"


def test_factory_creates_readability_model_with_judge_fallback() -> None:
    # LLM_JUDGE_MODEL 为空时回落到 LLM_MODEL；显式指定时使用指定值。
    base = dict(
        ENVIRONMENT="development",
        LLM_USE_MOCK=False,
        LLM_API_KEY=SecretStr("test-key"),
        LLM_BASE_URL="http://llm.test/v1",
        LLM_MODEL="deepseek-v4-flash",
    )
    model = create_readability_model(Settings(**base))
    assert model.model_name == "deepseek-v4-flash"

    model_judge = create_readability_model(
        Settings(**base, LLM_JUDGE_MODEL="judge-x")
    )
    assert model_judge.model_name == "judge-x"
