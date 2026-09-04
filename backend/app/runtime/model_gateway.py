"""Model decorators that account for calls without changing business protocols."""

from app.integrations.llm.protocol import AnalysisModel, ChapterWritingModel
from app.schemas.analysis import AnalysisDraft
from app.schemas.chapter import ChapterDraftLoose
from app.runtime.guard import get_runtime_session


class RuntimeAwareAnalysisModel:
    def __init__(self, model: AnalysisModel) -> None:
        self._model = model
        self.model_name = model.model_name

    async def generate_analysis(
        self,
        *,
        system_prompt: str,
        runtime_prompt: str,
    ) -> AnalysisDraft:
        session = get_runtime_session()
        if session is not None:
            session.before_model_call(self.model_name)
        succeeded = False
        try:
            result = await self._model.generate_analysis(
                system_prompt=system_prompt,
                runtime_prompt=runtime_prompt,
            )
            succeeded = True
            return result
        finally:
            if session is not None:
                session.after_model_call(self.model_name, succeeded=succeeded)


class RuntimeAwareChapterWritingModel:
    def __init__(self, model: ChapterWritingModel) -> None:
        self._model = model
        self.model_name = model.model_name

    async def generate_chapter(
        self,
        *,
        system_prompt: str,
        runtime_prompt: str,
    ) -> ChapterDraftLoose:
        session = get_runtime_session()
        if session is not None:
            session.before_model_call(self.model_name)
        succeeded = False
        try:
            result = await self._model.generate_chapter(
                system_prompt=system_prompt,
                runtime_prompt=runtime_prompt,
            )
            succeeded = True
            return result
        finally:
            if session is not None:
                session.after_model_call(self.model_name, succeeded=succeeded)
