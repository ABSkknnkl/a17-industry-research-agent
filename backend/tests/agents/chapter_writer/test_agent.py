import pytest

from app.agents.chapter_writer.service import ChapterWriterAgent
from app.integrations.llm.mock import MockChapterWritingModel
from app.schemas.analysis import AnalysisResult
from app.schemas.chapter import ChapterWritingResult
from app.schemas.workflow import StageName, StageResult, StageStatus
from app.workflow.stages import StageContext


class RepairingChapterModel(MockChapterWritingModel):
    def __init__(self) -> None:
        self.calls = 0

    async def generate_chapter(self, *, system_prompt: str, runtime_prompt: str):
        self.calls += 1
        chapter = await super().generate_chapter(
            system_prompt=system_prompt,
            runtime_prompt=runtime_prompt,
        )
        if self.calls == 1:
            chapter.sections[0].paragraphs[0].text = "建议买入该行业。"
        return chapter


class CountingChapterModel(MockChapterWritingModel):
    def __init__(self) -> None:
        self.calls = 0

    async def generate_chapter(self, *, system_prompt: str, runtime_prompt: str):
        self.calls += 1
        return await super().generate_chapter(
            system_prompt=system_prompt,
            runtime_prompt=runtime_prompt,
        )


class SectionChangingModel(CountingChapterModel):
    async def generate_chapter(self, *, system_prompt: str, runtime_prompt: str):
        chapter = await super().generate_chapter(
            system_prompt=system_prompt,
            runtime_prompt=runtime_prompt,
        )
        if self.calls > 7:
            for section in chapter.sections:
                section.paragraphs[0].text += "经人工复核后保留该证据边界。"
        return chapter


@pytest.mark.asyncio
async def test_agent_writes_seven_traceable_chapters_and_repairs_redlines(
    chapter_analysis_result: AnalysisResult,
) -> None:
    model = RepairingChapterModel()
    agent = ChapterWriterAgent(model=model)
    context = StageContext(
        project_id="project-1",
        run_id="run-chapter-1",
        revision=1,
        previous_results={
            StageName.DATA_INTERPRET: StageResult(
                stage=StageName.DATA_INTERPRET,
                status=StageStatus.APPROVED,
                data=chapter_analysis_result.model_dump(mode="json"),
                evidence_sources=["E-001"],
            ),
            StageName.CHART_GENERATE: StageResult(
                stage=StageName.CHART_GENERATE,
                status=StageStatus.COMPLETED,
                data={"mock": True},
            ),
        },
    )

    stage_result = await agent.run(context)
    writing = ChapterWritingResult.model_validate(stage_result.data)

    assert stage_result.stage == StageName.CHAPTER_WRITE
    assert stage_result.status == StageStatus.COMPLETED
    assert len(writing.chapters) == 7
    assert sum(len(chapter.sections) for chapter in writing.chapters) == 21
    assert writing.quality.passed is True
    assert writing.quality.revision_count == 1
    assert model.calls == 8
    assert writing.chart_requests[0].status == "planned"
    assert all(not chapter.chart_ids for chapter in writing.chapters)
    assert "建议买入" not in str(stage_result.data)


@pytest.mark.asyncio
async def test_agent_regenerates_only_the_requested_chapter(
    chapter_analysis_result: AnalysisResult,
) -> None:
    model = CountingChapterModel()
    agent = ChapterWriterAgent(model=model)
    upstream = {
        StageName.DATA_INTERPRET: StageResult(
            stage=StageName.DATA_INTERPRET,
            status=StageStatus.APPROVED,
            data=chapter_analysis_result.model_dump(mode="json"),
            evidence_sources=["E-001"],
        ),
        StageName.CHART_GENERATE: StageResult(
            stage=StageName.CHART_GENERATE,
            status=StageStatus.COMPLETED,
            data={"mock": True},
        ),
    }
    initial = await agent.run(
        StageContext(
            project_id="project-1",
            run_id="run-chapter-revise",
            revision=1,
            previous_results=upstream,
        )
    )
    initial_writing = ChapterWritingResult.model_validate(initial.data)
    assert model.calls == 7

    revised = await agent.run(
        StageContext(
            project_id="project-1",
            run_id="run-chapter-revise",
            revision=2,
            input_data={
                "chapter_write_options": {
                    "target_chapter_ids": ["CH-04"],
                    "instruction": "加强竞争格局的证据边界说明。",
                }
            },
            previous_results={
                **upstream,
                StageName.CHAPTER_WRITE: initial,
            },
            review_feedback="仅修改第四章。",
        )
    )
    revised_writing = ChapterWritingResult.model_validate(revised.data)

    assert model.calls == 8
    assert revised_writing.chapters[3].revision == 2
    assert revised_writing.chapters[0] == initial_writing.chapters[0]
    assert revised_writing.chapters[6] == initial_writing.chapters[6]


@pytest.mark.asyncio
async def test_agent_preserves_untargeted_sections_during_section_revision(
    chapter_analysis_result: AnalysisResult,
) -> None:
    model = SectionChangingModel()
    agent = ChapterWriterAgent(model=model)
    upstream = {
        StageName.DATA_INTERPRET: StageResult(
            stage=StageName.DATA_INTERPRET,
            status=StageStatus.APPROVED,
            data=chapter_analysis_result.model_dump(mode="json"),
            evidence_sources=["E-001"],
        ),
        StageName.CHART_GENERATE: StageResult(
            stage=StageName.CHART_GENERATE,
            status=StageStatus.COMPLETED,
            data={"mock": True},
        ),
    }
    initial = await agent.run(
        StageContext(
            project_id="project-1",
            run_id="run-section-revise",
            revision=1,
            previous_results=upstream,
        )
    )
    initial_writing = ChapterWritingResult.model_validate(initial.data)

    revised = await agent.run(
        StageContext(
            project_id="project-1",
            run_id="run-section-revise",
            revision=2,
            input_data={
                "chapter_write_options": {
                    "target_section_ids": ["SEC-04-02"],
                    "instruction": "仅复核第4章第2节。",
                }
            },
            previous_results={**upstream, StageName.CHAPTER_WRITE: initial},
        )
    )
    revised_writing = ChapterWritingResult.model_validate(revised.data)
    before = initial_writing.chapters[3]
    after = revised_writing.chapters[3]

    assert model.calls == 8
    assert after.sections[0] == before.sections[0]
    assert after.sections[1] != before.sections[1]
    assert after.sections[2] == before.sections[2]
