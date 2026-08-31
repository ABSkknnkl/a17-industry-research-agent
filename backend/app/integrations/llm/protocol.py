"""Provider-neutral model boundary for structured financial analysis."""

from typing import Protocol

from app.schemas.analysis import AnalysisDraft
from app.schemas.chapter import ChapterDraftLoose
from app.schemas.readability import ReadabilityReport


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
    ) -> ChapterDraftLoose:
        """Return one loose chapter draft; strict tightening happens in Agent 4."""


class ReadabilityReviewModel(Protocol):
    model_name: str

    async def review_paragraph(
        self,
        *,
        paragraph_text: str,
        kind: str,
    ) -> ReadabilityReport:
        """Review one paragraph's readability; input-isolated (text + kind only)."""
