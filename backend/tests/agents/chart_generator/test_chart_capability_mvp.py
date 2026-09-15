import asyncio
import json

import pytest

from app.agents.chart_generator.audit import bind_run, record_chart_operation
from app.agents.chart_generator.builders import build_bar_option, build_radar_option
from app.agents.chart_generator.constants import DATALABEL_MAX_POINTS, UNIT_PLACEHOLDERS
from app.agents.chart_generator.quality import (
    build_quality_report,
    check_title_conclusive,
    data_health_check,
)
from app.agents.chart_generator.service import _build_option, _calculated_metric_datasets
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


@pytest.mark.parametrize(
    ("title", "option", "footnotes", "expected"),
    [
        (
            "收入增长20%",
            {"series": [{"type": "line", "data": [1, 2]}]},
            [],
            {
                "five_second_readable": True,
                "axis_not_misleading": True,
                "key_point_highlighted": False,
            },
        ),
        (
            "收入趋势",
            {"series": [{"type": "line", "data": [1, 2]}]},
            [],
            {
                "five_second_readable": False,
                "axis_not_misleading": True,
                "key_point_highlighted": False,
            },
        ),
        (
            "收入增长20%",
            {"series": []},
            [],
            {
                "five_second_readable": False,
                "axis_not_misleading": True,
                "key_point_highlighted": False,
            },
        ),
        (
            "收入增长20%",
            {"yAxis": {"scale": True}, "series": [{"type": "line", "data": [1, 2]}]},
            [],
            {
                "five_second_readable": True,
                "axis_not_misleading": False,
                "key_point_highlighted": False,
            },
        ),
        (
            "收入增长20%",
            {"yAxis": [{"scale": True}], "series": [{"type": "line", "data": [1, 2]}]},
            ["纵轴未从 0 开始"],
            {
                "five_second_readable": True,
                "axis_not_misleading": True,
                "key_point_highlighted": False,
            },
        ),
        (
            "收入增长20%",
            {"xAxis": {"min": 5}, "series": [{"type": "bar", "data": [6, 7]}]},
            [],
            {
                "five_second_readable": True,
                "axis_not_misleading": False,
                "key_point_highlighted": False,
            },
        ),
        (
            "收入增长20%",
            {
                "yAxis": {"min": 1},
                "footnotes": ["纵轴未从 0 开始"],
                "series": [{"type": "line", "data": [1, 2]}],
            },
            [],
            {
                "five_second_readable": True,
                "axis_not_misleading": True,
                "key_point_highlighted": False,
            },
        ),
    ],
)
def test_quality_checklist_reports_machine_checks_without_changing_passed(
    title, option, footnotes, expected
) -> None:
    spec = _spec_with_title(title).model_copy(update={"option": option, "footnotes": footnotes})
    report = build_quality_report(candidate_count=1, specs=[spec], suppressed=[])
    assert report.model_dump()["review_checklist"] == expected
    assert report.passed is True


@pytest.mark.parametrize("mark", ["markLine", "markArea", "markPoint"])
@pytest.mark.parametrize("data", [[], [{"name": "目标", "yAxis": 2}]])
def test_quality_checklist_requires_rendered_nonempty_marks(mark, data) -> None:
    spec = _spec_with_title("收入增长20%")
    spec.option["series"][0][mark] = {"data": data}
    report = build_quality_report(candidate_count=1, specs=[spec], suppressed=[])
    assert report.model_dump()["review_checklist"]["key_point_highlighted"] is bool(data)


def test_quality_checklist_does_not_claim_empty_output_was_reviewed() -> None:
    report = build_quality_report(candidate_count=0, specs=[], suppressed=[])
    assert report.model_dump()["review_checklist"] == {
        "five_second_readable": False,
        "axis_not_misleading": False,
        "key_point_highlighted": False,
    }


def test_advisory_checklist_does_not_crash_on_null_optional_echarts_fields() -> None:
    spec = _spec_with_title("收入增长20%")
    spec.option.update({"xAxis": None, "yAxis": None, "series": None, "footnotes": None})
    report = build_quality_report(candidate_count=1, specs=[spec], suppressed=[])
    assert report.passed is True
    assert report.model_dump()["review_checklist"]["five_second_readable"] is False
    assert report.model_dump()["review_checklist"]["key_point_highlighted"] is False


@pytest.mark.parametrize("scale_min", [0, 50])
@pytest.mark.parametrize("disclosure_location", [None, "spec", "option"])
@pytest.mark.parametrize("radar_array", [False, True])
def test_radar_axis_checklist_requires_truncation_disclosure(
    radar_dataset: ChartDataset,
    scale_min: int,
    disclosure_location: str | None,
    radar_array: bool,
) -> None:
    dataset = radar_dataset.model_copy(update={"scale_min": scale_min})
    option = build_radar_option("能力评分提升", dataset)
    assert option["radar"]["indicator"][0]["min"] == scale_min
    if radar_array:
        option["radar"] = [option["radar"]]
    spec = _spec_with_title("能力评分提升").model_copy(
        update={
            "chart_type": "radar",
            "variant": "radar",
            "option": option,
        }
    )
    if disclosure_location == "spec":
        spec.footnotes.append("雷达轴未从 0 开始")
    elif disclosure_location == "option":
        spec.option["footnotes"].append("雷达轴未从 0 开始")
    report = build_quality_report(candidate_count=1, specs=[spec], suppressed=[])
    assert report.review_checklist["axis_not_misleading"] is (
        scale_min == 0 or disclosure_location is not None
    )
    assert report.passed is True


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


def test_calculated_metrics_normalize_placeholder_units_before_axis_handoff() -> None:
    metrics = [
        {
            "calculation_id": f"CALC-U-{index}",
            "calculation_type": "cr3",
            "metric_name": "集中度",
            "entity_scope": f"样本{index}",
            "market": "中国内地",
            "value": float(index),
            "unit": unit,
            "formula": "样本计算",
            "inputs": [
                {
                    "name": "份额",
                    "value": 1.0,
                    "unit": "%",
                    "evidence_id": f"E-U-{index}",
                }
            ],
            "evidence_ids": [f"E-U-{index}"],
            "methodology_note": "同口径样本。",
        }
        for index, unit in enumerate(("未提供", "文本", "不适用", ""), 1)
    ]

    datasets = _calculated_metric_datasets(metrics)

    assert len(datasets) == 1
    assert datasets[0].unit is None
    assert build_bar_option("集中度比较", datasets[0], "grouped")["yAxis"]["name"] == ""


@pytest.mark.asyncio
async def test_audit_run_context_is_isolated_between_concurrent_tasks(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("CHART_AUDIT_DIR", str(tmp_path))

    async def record_for_run(run_id: str, revision: int, chart_id: str) -> None:
        bind_run(run_id, revision)
        await asyncio.sleep(0)
        record_chart_operation(chart_id=chart_id, stage="route", decision="generated")

    await asyncio.gather(
        record_for_run("run-one", 1, "CHART-ONE"),
        record_for_run("run-two", 2, "CHART-TWO"),
    )

    rows = {
        row["chart_id"]: row
        for line in next(tmp_path.glob("*.jsonl")).read_text().splitlines()
        for row in [json.loads(line)]
    }
    assert (rows["CHART-ONE"]["run_id"], rows["CHART-ONE"]["revision"]) == ("run-one", 1)
    assert (rows["CHART-TWO"]["run_id"], rows["CHART-TWO"]["revision"]) == ("run-two", 2)


def test_service_wires_dual_panel_variant_to_the_panel_builder() -> None:
    dataset = ChartDataset(
        dataset_id="DS-SERVICE-PANEL",
        kind="time_series",
        metric_name="量价",
        business_linked=True,
        series_meta=[
            {"name": "销量", "unit": "万吨", "render_as": "bar"},
            {"name": "产量", "unit": "万吨", "render_as": "bar"},
            {"name": "增速", "unit": "%", "render_as": "line"},
        ],
        points=[
            ChartPoint(
                label=str(year),
                value=index + year,
                series=name,
                period_end=f"{year}-12-31",
                evidence_id=f"E-{index}-{year}",
            )
            for index, name in enumerate(("销量", "产量", "增速"), 1)
            for year in (2024, 2025)
        ],
        evidence_ids=[f"E-{index}-{year}" for index in range(1, 4) for year in (2024, 2025)],
        panels=[
            {"panel_id": "volume", "position": "left", "series": ["销量", "产量"]},
            {"panel_id": "rate", "position": "right", "series": ["增速"]},
        ],
    )

    option = _build_option(
        title="量增价稳",
        chart_type="combo",
        variant="dual_panel",
        dataset=dataset,
        theme="research_blue",
    )

    assert len(option["grid"]) == 2
    assert [series["xAxisIndex"] for series in option["series"]] == [0, 0, 1]
