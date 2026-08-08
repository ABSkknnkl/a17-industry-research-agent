"""Application composition for the current real and placeholder stages."""

from app.agents.data_interpreter.service import DataInterpreterAgent
from app.agents.chapter_writer.service import ChapterWriterAgent
from app.agents.chart_generator.service import ChartGeneratorAgent
from app.agents.report_fusion.service import ReportFusionAgent
from app.integrations.llm.mock import MockChapterWritingModel
from app.integrations.llm.protocol import AnalysisModel, ChapterWritingModel
from app.schemas.workflow import StageName
from app.runtime.model_gateway import (
    RuntimeAwareAnalysisModel,
    RuntimeAwareChapterWritingModel,
)
from app.security.agent_guard import SecuredStageAgent
from app.workflow.mock_stage import MockStageAgent
from app.workflow.stages import StageRegistry


def create_stage_registry(
    model: AnalysisModel,
    chapter_model: ChapterWritingModel | None = None,
) -> StageRegistry:
    """Use real interpretation/writing stages and contract-compatible neighbour mocks."""

    writer_model = RuntimeAwareChapterWritingModel(chapter_model or MockChapterWritingModel())
    analysis_model = RuntimeAwareAnalysisModel(model)

    return StageRegistry(
        [
            MockStageAgent(StageName.DATA_FETCH),
            SecuredStageAgent(DataInterpreterAgent(model=analysis_model)),
            ChartGeneratorAgent(),
            SecuredStageAgent(ChapterWriterAgent(model=writer_model)),
            ReportFusionAgent(),
        ]
    )
