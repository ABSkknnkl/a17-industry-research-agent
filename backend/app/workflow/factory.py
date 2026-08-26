"""Application composition for the current real and placeholder stages."""

from app.agents.data_interpreter.service import DataInterpreterAgent
from app.agents.data_fetcher.factory import (
    create_data_fetcher_agent,
    create_feedback_interpreter,
)
from app.agents.chapter_writer.service import ChapterWriterAgent
from app.agents.chart_generator.service import ChartGeneratorAgent
from app.agents.report_fusion.service import ReportFusionAgent
from app.integrations.llm.protocol import AnalysisModel, ChapterWritingModel
from app.integrations.visuals.factory import create_image_generator, create_prompt_compiler
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
    prompt_compiler = None
    image_generator = None
    if settings.INDUSTRY_CHAIN_IMAGE_ENABLED:
        prompt_compiler = create_prompt_compiler(settings)
        image_generator = create_image_generator(settings)

    # One shared interpreter instance serves Agent 1 and Agent 3 so both
    # stages translate review feedback with the same rules and thresholds.
    feedback_interpreter = create_feedback_interpreter(settings)

    return StageRegistry(
        [
            create_data_fetcher_agent(
                settings,
                feedback_interpreter=feedback_interpreter,
            ),
            SecuredStageAgent(DataInterpreterAgent(model=analysis_model)),
            ChartGeneratorAgent(
                prompt_compiler=prompt_compiler,
                image_generator=image_generator,
                generate_industry_chain_images=settings.INDUSTRY_CHAIN_IMAGE_ENABLED,
                feedback_interpreter=feedback_interpreter,
            ),
            SecuredStageAgent(ChapterWriterAgent(model=writer_model)),
            ReportFusionAgent(),
        ]
    )
