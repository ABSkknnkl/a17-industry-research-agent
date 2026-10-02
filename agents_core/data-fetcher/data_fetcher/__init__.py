"""Public API for the data-fetcher agent foundation."""

from data_fetcher.agent import DataFetcherAgent
from data_fetcher.models import (
    EventRecord,
    ResearchRequest,
    ResearchRunResult,
    StructuredResearchDataset,
)

__all__ = [
    "DataFetcherAgent",
    "EventRecord",
    "ResearchRequest",
    "ResearchRunResult",
    "StructuredResearchDataset",
]

