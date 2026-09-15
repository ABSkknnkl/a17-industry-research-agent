import json

from app.agents.chart_generator.audit import record_chart_operation
from app.agents.chart_generator.constants import DATALABEL_MAX_POINTS, UNIT_PLACEHOLDERS
from app.agents.chart_generator.quality import check_title_conclusive, data_health_check
from app.schemas.chart import ChartAnnotation, ChartDataset, ChartPanel, ChartPoint, ChartSpec
from app.agents.data_fetcher.fusion import build_chart_datasets
from app.schemas.evidence import EvidenceItem


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
            "annotations": [{"annotation_type": "reference_line", "label": "目标", "value": 8.0}],
        }
    )

    assert [panel.position for panel in dataset.panels or []] == ["left", "right"]
    assert isinstance(dataset.annotations[0], ChartAnnotation)
    assert isinstance(dataset.panels[0], ChartPanel)
    assert DATALABEL_MAX_POINTS == 12
    assert UNIT_PLACEHOLDERS == frozenset({"未提供", "文本", "不适用", ""})


def _dataset_with_values(values: list[int | float | None]) -> ChartDataset:
    return ChartDataset(
        dataset_id="DS-HEALTH",
        kind="time_series",
        metric_name="收入",
        points=[
            ChartPoint(label=str(2020 + index), value=value, evidence_id=f"E-{index}")
            for index, value in enumerate(values, 1)
        ],
        evidence_ids=[f"E-{index}" for index in range(1, len(values) + 1)],
    )


def _spec_with_title(title: str) -> ChartSpec:
    return ChartSpec(
        chart_id="CHART-TITLE",
        title=title,
        chart_type="line",
        variant="line",
        option={"series": [{"type": "line", "data": [1]}]},
        evidence_ids=["E-1"],
        data_fingerprint="0" * 64,
        dedupe_key="title-test",
    )


def test_data_health_boundaries_and_title_rule() -> None:
    four_rows = _dataset_with_values([1, 2, 3, 4])
    five_rows = _dataset_with_values([1, 2, 3, 4, 5])
    exactly_twenty_percent_missing = _dataset_with_values([1, 2, 3, 4, None])
    over_twenty_percent_missing = _dataset_with_values([1, 2, 3, None, None])

    assert "data_health_min_rows" in data_health_check(four_rows)
    assert "data_health_min_rows" not in data_health_check(five_rows)
    assert "data_health_missing_ratio" not in data_health_check(exactly_twenty_percent_missing)
    assert "data_health_missing_ratio" in data_health_check(over_twenty_percent_missing)
    assert "data_health_type_consistency" in data_health_check(
        _dataset_with_values([1, 2.0, 3, 4, 5])
    )
    assert "data_health_min_fields" in data_health_check(
        ChartDataset(
            dataset_id="DS-EMPTY",
            kind="categorical",
            metric_name="收入",
            evidence_ids=["E-EMPTY"],
        )
    )
    assert check_title_conclusive(_spec_with_title("收入同比增长20%")) is True
    assert check_title_conclusive(_spec_with_title("收入趋势")) is False


def test_audit_writes_seven_business_fields(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CHART_AUDIT_DIR", str(tmp_path))

    record_chart_operation(chart_id="CHART-1", stage="route", decision="generated")

    row = json.loads(next(tmp_path.glob("*.jsonl")).read_text().splitlines()[0])
    expected = {
        "chart_id",
        "stage",
        "decision",
        "evidence_ids",
        "quality_issues",
        "degradation",
        "retry_of",
    }
    assert expected <= row.keys()


def test_fusion_normalizes_all_chart_unit_placeholders() -> None:
    evidence = [
        EvidenceItem.model_validate(
            {
                "evidence_id": f"E-U-{index}",
                "metric_name": "行业产量",
                "value": index,
                "unit": unit,
                "scope": f"企业{index}",
                "market": "中国内地",
                "exchange": "不适用",
                "security_type": "行业汇总",
                "currency": "不适用",
                "accounting_standard": "不适用",
                "source_name": "测试来源",
                "grade": "C",
            }
        )
        for index, unit in enumerate(("未提供", "文本", "不适用", ""), 1)
    ]

    datasets = build_chart_datasets(evidence, [])

    assert len(datasets) == 1
    assert datasets[0].unit is None
