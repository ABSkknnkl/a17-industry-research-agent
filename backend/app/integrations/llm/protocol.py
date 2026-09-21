"""Provider-neutral model boundary for structured financial analysis."""

from typing import Protocol

from app.schemas.analysis import AnalysisDraft
from app.schemas.chapter import ChapterDraftLoose
from app.schemas.readability import ReadabilityReport
from app.schemas.report import VisualReviewReport


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


class VisualReviewModel(Protocol):
    model_name: str

    async def review_report(
        self,
        *,
        report_context: str,
        page_images: list[bytes],
        page_numbers: list[int],
        total_page_count: int,
        deterministic_findings: list[str],
        review_round: int,
    ) -> VisualReviewReport:
        """Review rendered pages without permission to change report facts."""
