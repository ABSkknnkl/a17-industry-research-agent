"""Application composition for the current real and placeholder stages."""

from app.agents.data_interpreter.service import DataInterpreterAgent
from app.agents.data_fetcher.factory import create_data_fetcher_agent
from app.agents.chapter_writer.service import ChapterWriterAgent
from app.agents.chart_generator.service import ChartGeneratorAgent
from app.agents.report_fusion.service import ReportFusionAgent
from app.integrations.llm.protocol import AnalysisModel, ChapterWritingModel
from app.core.config import settings
from app.runtime.model_gateway import (
    RuntimeAwareAnalysisModel,
    RuntimeAwareChapterWritingModel,
)
from app.security.agent_guard import SecuredStageAgent
from app.workflow.stages import StageRegistry


def create_stage_registry(
    model: AnalysisModel,
    chapter_model: ChapterWritingModel,
) -> StageRegistry:
    """Compose all five production stages without an implicit Mock fallback."""

    writer_model = RuntimeAwareChapterWritingModel(chapter_model)
    analysis_model = RuntimeAwareAnalysisModel(model)

    return StageRegistry(
        [
            create_data_fetcher_agent(settings),
            SecuredStageAgent(DataInterpreterAgent(model=analysis_model)),
            ChartGeneratorAgent(),
            SecuredStageAgent(ChapterWriterAgent(model=writer_model)),
            ReportFusionAgent(),
        ]
    )
