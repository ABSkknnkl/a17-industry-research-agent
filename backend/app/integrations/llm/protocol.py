"""Provider-neutral model boundary for structured financial analysis."""

from typing import Protocol

from app.schemas.analysis import AnalysisDraft
from app.schemas.chapter import ChapterDraft


class AnalysisModel(Protocol):
    model_name: str

    async def generate_analysis(
        self,
        *,
        system_prompt: str,
        runtime_prompt: str,
    ) -> AnalysisDraft:
        """Return a schema-validated draft without provider-specific objects."""


class ChapterWritingModel(Protocol):
    model_name: str

    async def generate_chapter(
        self,
        *,
        system_prompt: str,
        runtime_prompt: str,
    ) -> ChapterDraft:
        """Return one schema-validated chapter without provider-specific objects."""
