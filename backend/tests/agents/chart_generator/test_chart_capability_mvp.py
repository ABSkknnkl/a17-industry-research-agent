from app.agents.chart_generator.constants import DATALABEL_MAX_POINTS, UNIT_PLACEHOLDERS
from app.schemas.chart import ChartAnnotation, ChartDataset, ChartPanel


def test_chart_contract_supports_four_series_panels_and_annotations() -> None:
    dataset = ChartDataset.model_validate(
        {
            "dataset_id": "DS-PANEL",
            "kind": "time_series",
            "metric_name": "量价",
            "points": [
                {"label": "2024", "value": 1, "series": name, "evidence_id": f"E-{i}"}
                for i, name in enumerate(("销量", "产量", "增速", "价格"), 1)
            ],
            "evidence_ids": ["E-1", "E-2", "E-3", "E-4"],
            "panels": [
                {
                    "panel_id": "volume",
                    "position": "left",
                    "series": ["销量", "产量"],
                    "axis_name": "万吨",
                },
                {
                    "panel_id": "rate",
                    "position": "right",
                    "series": ["增速", "价格"],
                    "axis_name": "%",
                },
            ],
            "annotations": [
                {"annotation_type": "reference_line", "label": "目标", "value": 8.0}
            ],
        }
    )

    assert [panel.position for panel in dataset.panels or []] == ["left", "right"]
    assert isinstance(dataset.annotations[0], ChartAnnotation)
    assert isinstance(dataset.panels[0], ChartPanel)
    assert DATALABEL_MAX_POINTS == 12
    assert UNIT_PLACEHOLDERS == frozenset({"未提供", "文本", "不适用", ""})
