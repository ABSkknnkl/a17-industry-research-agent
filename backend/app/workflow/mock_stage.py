"""Contract-compatible placeholder used until another stage is implemented."""

from app.schemas.workflow import StageName, StageResult, StageStatus
from app.workflow.stages import StageContext


class MockStageAgent:
    def __init__(self, stage: StageName) -> None:
        self.stage = stage

    async def run(self, context: StageContext) -> StageResult:
        if self.stage == StageName.DATA_FETCH:
            data = dict(context.input_data)
        else:
            data = {
                "mock": True,
                "stage": self.stage.value,
                "available_upstream_stages": [stage.value for stage in context.previous_results],
            }
        return StageResult(
            stage=self.stage,
            status=StageStatus.COMPLETED,
            revision=context.revision,
            data=data,
        )
