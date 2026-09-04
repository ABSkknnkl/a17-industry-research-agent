"""Contract-compatible placeholder used until another stage is implemented."""

from typing import Any

from app.schemas.workflow import StageName, StageResult, StageStatus
from app.workflow.stages import StageContext


class MockStageAgent:
    def __init__(self, stage: StageName) -> None:
        self.stage = stage

    async def run(self, context: StageContext) -> StageResult:
        if self.stage == StageName.DATA_FETCH:
            data = dict(context.input_data)
            if "chart_datasets" not in data:
                data["chart_datasets"] = self._chart_datasets_from_evidence(data)
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

    @staticmethod
    def _chart_datasets_from_evidence(data: dict[str, Any]) -> list[dict[str, Any]]:
        """Development adapter until Agent 1 emits the real ChartDataset contract.

        It only reshapes numeric evidence and never derives or invents a value.
        """

        datasets: list[dict[str, Any]] = []
        evidence_items = data.get("evidence_items", [])
        if not isinstance(evidence_items, list):
            return datasets
        for item in evidence_items:
            if not isinstance(item, dict) or not isinstance(item.get("value"), (int, float)):
                continue
            evidence_id = item.get("evidence_id")
            metric_name = item.get("metric_name")
            if not isinstance(evidence_id, str) or not isinstance(metric_name, str):
                continue
            datasets.append(
                {
                    "dataset_id": f"DS-MOCK-{evidence_id.removeprefix('E-')}",
                    "kind": "categorical",
                    "metric_name": metric_name,
                    "unit": item.get("unit"),
                    "currency": item.get("currency"),
                    "is_additive": False,
                    "points": [
                        {
                            "label": item.get("scope") or metric_name,
                            "value": item["value"],
                            "series": "默认",
                            "period_end": item.get("period_end"),
                            "evidence_id": evidence_id,
                        }
                    ],
                    "nodes": [],
                    "edges": [],
                    "evidence_ids": [evidence_id],
                }
            )
        return datasets
