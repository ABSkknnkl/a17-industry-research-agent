import pytest
from pydantic import ValidationError

from app.schemas.chart import ChartReference


def test_ready_chart_requires_an_artifact_reference() -> None:
    with pytest.raises(ValidationError, match="ready charts require artifact_id"):
        ChartReference(
            chart_id="CHART-01",
            title="行业增速",
            chart_type="line",
            status="ready",
            evidence_ids=["E-001"],
        )
