"""P1/P2/P3 层验收测试（2026-09-13 方案 §6.3）——捏造数据驱动 Agent3。

覆盖：P1-1 标题结论化 / P1-3 数值标签 / P1-4 截断轴 / P1-5 三种标注 /
P1-6 对比度 / P1-7 自查清单 / P1-8 三问 / P2-1 broker_thin / P2-3 红涨绿跌 /
P2-6 高亮 / P3-1 审计 / P3-2 失败落盘 / P3-3/5 数据体检。
双面项（P1-3/4/5、P2-1/2/5/6）的 SVG 面断言在 test_svg_option_parity.py。
"""

import json
from datetime import date
from pathlib import Path

import pytest

from app.agents.chart_generator.builders import (
    THEMES,
    build_bar_option,
    build_dual_panel_option,
    build_line_option,
)
from app.agents.chart_generator.constants import DOWN_COLOR, UP_COLOR
from app.agents.chart_generator.quality import (
    build_quality_report,
    check_palette_contrast,
    check_title_conclusive,
    data_health_check,
    preflight_checklist,
    review_gate_checklist,
)
from app.schemas.chart import (
    ChartAnnotation,
    ChartDataset,
    ChartPoint,
    ChartPanel,
    ChartSpec,
)


def _time_dataset(
    *,
    metric_name: str = "碳酸锂价格",
    unit: str | None = "元/吨",
    n_points: int = 8,
    highlight_series: str | None = None,
    annotations: list[ChartAnnotation] | None = None,
) -> ChartDataset:
    points = [
        ChartPoint(
            label=f"{2024 + (month - 1) // 12}-{((month - 1) % 12) + 1:02d}",
            value=100000.0 + month * 2500,
            series=metric_name,
            period_end=date(2024 + (month - 1) // 12, ((month - 1) % 12) + 1, 28),
            evidence_id=f"E-LITH-{month}",
        )
        for month in range(1, n_points + 1)
    ]
    return ChartDataset(
        dataset_id="DS-LITHIUM",
        kind="time_series",
        metric_name=metric_name,
        unit=unit,
        points=points,
        evidence_ids=[p.evidence_id for p in points],
        highlight_series=highlight_series,
        annotations=annotations,
    )


def _spec(option: dict, title: str = "碳酸锂价格同比下跌23%", chart_type: str = "line") -> ChartSpec:
    return ChartSpec.model_validate(
        {
            "chart_id": "CHART-TEST",
            "title": title,
            "chart_type": chart_type,
            "variant": chart_type,
            "option": option,
            "evidence_ids": ["E-1"],
            "data_fingerprint": "a" * 64,
            "dedupe_key": f"{chart_type}:test",
        }
    )


# ---------------------------------------------------------------------------
# P1-1 标题结论化（Agent3 校验层）
# ---------------------------------------------------------------------------


def test_p11_title_conclusive() -> None:
    """描述性标题 → title_not_conclusive；结论式标题通过。"""
    descriptive = _spec(
        build_line_option("碳酸锂价格趋势", _time_dataset()),
        title="碳酸锂价格趋势",
    )
    conclusive = _spec(
        build_line_option("碳酸锂价格走势", _time_dataset()),
        title="碳酸锂价格同比下跌23%",
    )
    assert check_title_conclusive(conclusive) is True
    assert check_title_conclusive(descriptive) is False
    report = build_quality_report(
        candidate_count=2, specs=[descriptive, conclusive], suppressed=[]
    )
    issues_text = " ".join(report.issues)
    assert "title_not_conclusive" in issues_text


# ---------------------------------------------------------------------------
# P1-3 数值标签（option 面；SVG 面见 parity 测试）
# ---------------------------------------------------------------------------


def test_p13_datalabel_option_face() -> None:
    """≤12 点：option.series.label.show=True；>12 点：无 label。"""
    small = build_line_option("碳酸锂价格", _time_dataset(n_points=8))
    assert small["series"][0]["label"]["show"] is True
    big = build_line_option("碳酸锂价格", _time_dataset(n_points=13))
    assert not big["series"][0].get("label", {}).get("show")


# ---------------------------------------------------------------------------
# P1-4 截断轴提示
# ---------------------------------------------------------------------------


def test_p14_truncated_axis_footnote() -> None:
    """scale=true → option.footnotes 含「纵轴未从 0 开始」。"""
    option = build_line_option("碳酸锂价格", _time_dataset())
    assert option["yAxis"]["scale"] is True
    assert any("纵轴未从 0 开始" in str(item) for item in option.get("footnotes", []))


# ---------------------------------------------------------------------------
# P1-5 三种标注（option 面）
# ---------------------------------------------------------------------------


def test_p15_annotations_option_face() -> None:
    """reference line / shaded region / call-out 三类进 option。"""
    dataset = _time_dataset(
        annotations=[
            ChartAnnotation(annotation_type="reference_line", label="成本线", value=120000),
            ChartAnnotation(annotation_type="shaded_region", label="旺季", start="2024-06", end="2024-08"),
            ChartAnnotation(annotation_type="callout", label="峰值", start="2024-08", value=120000),
        ]
    )
    option = build_line_option("碳酸锂价格与成本线", dataset)
    series = option["series"][0]
    assert "markLine" in series
    assert series["markLine"]["data"][0]["yAxis"] == 120000
    assert "markArea" in series
    assert series["markArea"]["data"][0][0]["xAxis"] == "2024-06"
    assert "markPoint" in series
    assert series["markPoint"]["data"][0]["coord"] == ["2024-08", 120000]


# ---------------------------------------------------------------------------
# P1-6 对比度
# ---------------------------------------------------------------------------


def test_p16_contrast_check() -> None:
    """低对比配色（<4.5:1）触发告警。"""
    issues = check_palette_contrast({"color": ["#F5F5F5", "#2563EB"]})
    assert any("low_contrast_palette" in issue for issue in issues)
    ok_issues = check_palette_contrast({"color": ["#2563EB"]})
    assert not ok_issues


# ---------------------------------------------------------------------------
# P1-7 自查清单
# ---------------------------------------------------------------------------


def test_p17_preflight_checklist() -> None:
    """5 问：颜色>5（非构成类）告警；合规 spec 全过。"""
    ok_spec = _spec(build_line_option("营收同比增长30%", _time_dataset(metric_name="营收")))
    # 单 spec 场景显式放宽推荐下限（数量档由报告级验收，不在此误报）。
    assert preflight_checklist([ok_spec], recommended_range=(1, 8)) == []
    many_color_option = dict(build_line_option("营收同比增长30%", _time_dataset(metric_name="营收")))
    many_color_option["color"] = ["#111111"] * 7
    color_spec = _spec(many_color_option)
    issues = preflight_checklist([color_spec])
    assert any("preflight_color_budget" in issue for issue in issues)


# ---------------------------------------------------------------------------
# P1-8 质量门三问
# ---------------------------------------------------------------------------


def test_p18_quality_three_questions() -> None:
    """三问纳入 quality 报告（review_checklist 三键）。"""
    spec = _spec(build_line_option("碳酸锂价格同比下跌23%", _time_dataset()))
    report = build_quality_report(candidate_count=1, specs=[spec], suppressed=[])
    assert report.review_checklist is not None
    assert set(report.review_checklist) == {
        "five_second_readable",
        "axis_not_misleading",
        "key_point_highlighted",
    }
    # 截断轴有 footnote → axis_not_misleading=True。


# ---------------------------------------------------------------------------
# P2-1 broker_thin / P2-5 okabe_ito 主题
# ---------------------------------------------------------------------------


def test_p21_broker_thin_theme_option_face() -> None:
    """broker_thin：无网格（splitLine.show=False）、细线 1.5、无数据点。"""
    assert "broker_thin" in THEMES
    option = build_line_option("碳酸锂价格同比下跌23%", _time_dataset(), theme="broker_thin")
    assert option["yAxis"]["splitLine"]["show"] is False
    assert option["series"][0]["lineStyle"]["width"] == 1.5
    assert option["series"][0]["showSymbol"] is False


def test_p25_okabe_ito_theme_registered() -> None:
    """okabe_ito 主题注册且为 8 色科学色板。"""
    palette = THEMES["okabe_ito"]
    assert len(palette) == 8
    option = build_line_option("碳酸锂价格同比下跌23%", _time_dataset(), theme="okabe_ito")
    assert option["color"] == palette


# ---------------------------------------------------------------------------
# P2-3 红涨绿跌
# ---------------------------------------------------------------------------


def test_p23_updown_colors() -> None:
    """涨跌序列 option.color 前两位 = [UP, DOWN]，per-point 红涨绿跌。"""
    points = [
        ChartPoint(
            label=f"2025-{month:02d}",
            value=(1.5 if month % 2 else -2.0),
            series="环比增速",
            period_end=date(2025, month, 28),
            evidence_id=f"E-UPDOWN-{month}",
        )
        for month in range(1, 9)
    ]
    dataset = ChartDataset(
        dataset_id="DS-UPDOWN",
        kind="time_series",
        metric_name="动力电池装机量环比增速",
        unit="%",
        points=points,
        evidence_ids=[p.evidence_id for p in points],
    )
    option = build_bar_option("装机量环比增速", dataset, "vertical")
    assert option["color"][0] == UP_COLOR
    assert option["color"][1] == DOWN_COLOR
    for raw in option["series"][0]["data"]:
        value = raw["value"]
        assert raw["itemStyle"]["color"] == (UP_COLOR if value >= 0 else DOWN_COLOR)


# ---------------------------------------------------------------------------
# P2-6 高亮法
# ---------------------------------------------------------------------------


def test_p26_highlight_option_face() -> None:
    """重点序列上色、其余灰化。"""
    dataset = _time_dataset(metric_name="碳酸锂价格")
    payload = dataset.model_dump(mode="json")
    payload["points"].extend(
        [
            {
                "label": f"2025-{month:02d}",
                "value": 60000.0 + month * 500,
                "series": "电解钴价格",
                "period_end": f"2025-{month:02d}-28",
                "evidence_id": f"E-CO-{month}",
            }
            for month in range(1, 9)
        ]
    )
    payload["evidence_ids"].extend(f"E-CO-{m}" for m in range(1, 9))
    payload["highlight_series"] = "碳酸锂价格"
    two_series = ChartDataset.model_validate(payload)
    option = build_line_option("碳酸锂价格与电解钴", two_series)
    series_map = {item["name"]: item for item in option["series"]}
    assert series_map["碳酸锂价格"]["itemStyle"]["color"] == THEMES["research_blue"][0]
    assert series_map["电解钴价格"]["itemStyle"]["color"] == "#9CA3AF"


# ---------------------------------------------------------------------------
# P2-2 dual_panel builder（option 面）
# ---------------------------------------------------------------------------


def test_p22_dual_panel_option_and_fallback() -> None:
    """4 series×12月 → 双 grid；缺 panels → 回退 line（不抛错）。"""
    periods = [date(2025, month, 28) for month in range(1, 13)]
    points = []
    for name in ("销量A", "销量B", "增速A", "增速B"):
        for index, period in enumerate(periods):
            points.append(
                ChartPoint(
                    label=f"2025-{index + 1:02d}",
                    value=100.0 + index * 5,
                    series=name,
                    period_end=period,
                    evidence_id=f"E-DP-{name}-{index}",
                )
            )
    base = {
        "dataset_id": "DS-VOL-GROWTH",
        "kind": "time_series",
        "metric_name": "销量与增速",
        "unit": None,
        "business_linked": True,
        "points": [p.model_dump(mode="json") for p in points],
        "evidence_ids": [p.evidence_id for p in points],
        "series_meta": [
            {"name": name, "unit": "万辆" if "销量" in name else "%", "currency": "CNY", "render_as": "bar" if "销量" in name else "line"}
            for name in ("销量A", "销量B", "增速A", "增速B")
        ],
    }
    with_panels = dict(base)
    with_panels["panels"] = [
        {"panel_id": "P1", "position": "left", "series": ["销量A", "销量B"], "axis_name": "万辆"},
        {"panel_id": "P2", "position": "right", "series": ["增速A", "增速B"], "axis_name": "%"},
    ]
    dataset = ChartDataset.model_validate(with_panels)
    option = build_dual_panel_option("销量与增速双面板", dataset)
    assert len(option["grid"]) == 2
    assert len(option["xAxis"]) == 2
    assert len(option["yAxis"]) == 2
    # 缺 panels → 回退 line 不抛错。
    fallback_option = build_dual_panel_option(
        "销量与增速双面板", ChartDataset.model_validate(base)
    )
    assert fallback_option["series"][0]["type"] == "line"
    # 单 grid（dict 而非双 grid list）。
    assert not isinstance(fallback_option.get("grid"), list)


# ---------------------------------------------------------------------------
# P3-3/P3-5 数据体检与运行前自检
# ---------------------------------------------------------------------------


def test_p35_data_health_check() -> None:
    """字段>=2列/行数>=5/缺失<=20%/类型一致。"""
    healthy = _time_dataset()
    assert data_health_check(healthy) == []  # 8 点：全部通过
    short = _time_dataset(n_points=4)
    assert "data_health_min_rows" in data_health_check(short)
    sparse = ChartDataset(
        dataset_id="DS-SPARSE",
        kind="time_series",
        metric_name="缺失序列",
        unit=None,
        points=[
            ChartPoint(label=str(i), value=None, evidence_id=f"E-M-{i}")
            for i in range(5)
        ],
        evidence_ids=[f"E-M-{i}" for i in range(5)],
    )
    issues = data_health_check(sparse)
    assert "data_health_missing_ratio" in issues
    mixed = ChartDataset(
        dataset_id="DS-MIXED",
        kind="time_series",
        metric_name="类型混杂",
        unit=None,
        points=[
            ChartPoint(label="1", value=1.5, evidence_id="E-X-1"),
            ChartPoint(label="2", value=2, evidence_id="E-X-2"),
        ] * 3,
        evidence_ids=[f"E-X-{i}" for i in range(6)],
    )
    assert "data_health_type_consistency" in data_health_check(mixed)


@pytest.mark.asyncio
async def test_p33_preflight_blocks_incomplete_data(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """运行前自检：缺失率超限的数据集被拦截（suppressed 而非报错）。"""
    from app.core.config import settings

    from tests.agents.chart_generator.test_agent import _evidence_items

    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    from app.schemas.workflow import StageName, StageResult, StageStatus
    from app.workflow.stages import StageContext

    from app.agents.chart_generator.service import ChartGeneratorAgent

    points = [
        ChartPoint(
            label=f"2025-{i + 1:02d}",
            value=(None if i % 2 else 10.0),
            series="缺失序列",
            period_end=date(2025, i + 1, 28),
            evidence_id=f"E-H-{i}",
        )
        for i in range(6)
    ]
    dataset = ChartDataset(
        dataset_id="DS-BAD-HEALTH",
        kind="time_series",
        metric_name="缺失过半序列",
        unit="亿元",
        points=points,
        evidence_ids=[p.evidence_id for p in points],
    )
    context = StageContext(
        project_id="p",
        run_id="run-p33-health",
        revision=1,
        input_data={
            "chart_datasets": [dataset.model_dump(mode="json")],
            "evidence_items": _evidence_items(dataset.evidence_ids),
        },
        previous_results={
            StageName.DATA_INTERPRET: StageResult(
                stage=StageName.DATA_INTERPRET,
                status=StageStatus.COMPLETED,
                data={
                    "chart_candidates": [
                        {
                            "title": "缺失过半序列趋势",
                            "chart_type": "line",
                            "evidence_ids": dataset.evidence_ids,
                        }
                    ]
                },
            )
        },
    )
    result = await ChartGeneratorAgent().run(context)
    assert any(
        item["reason_code"] == "data_health_check_failed"
        for item in result.data["suppressed_candidates"]
    )


@pytest.mark.asyncio
async def test_p31_p32_audit_and_failure_log(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P3-1 审计 7 字段落盘；P3-2 失败项落 data。"""
    from app.core.config import settings

    from tests.agents.chart_generator.test_agent import _evidence_items

    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    monkeypatch.setenv("CHART_AUDIT_DIR", str(tmp_path / "audit"))
    from app.schemas.workflow import StageName, StageResult, StageStatus
    from app.workflow.stages import StageContext

    from app.agents.chart_generator.service import ChartGeneratorAgent

    dataset = _time_dataset()
    context = StageContext(
        project_id="p",
        run_id="run-p31-audit",
        revision=1,
        input_data={
            "chart_datasets": [dataset.model_dump(mode="json")],
            "evidence_items": _evidence_items(dataset.evidence_ids),
        },
        previous_results={
            StageName.DATA_INTERPRET: StageResult(
                stage=StageName.DATA_INTERPRET,
                status=StageStatus.COMPLETED,
                data={
                    "chart_candidates": [
                        {
                            "title": "碳酸锂价格趋势",
                            "chart_type": "bar",
                            "evidence_ids": dataset.evidence_ids,
                        }
                    ]
                },
            )
        },
    )
    result = await ChartGeneratorAgent().run(context)
    # bar + time_series → 降级 line（chart_downgraded 失败项落盘）。
    failures = result.data.get("chart_generation_failures", [])
    assert any(
        item.get("reason_code") == "chart_downgraded" for item in failures
    ), "P3-2 失败项必须落盘"
    # 审计日志：7 字段。
    audit_files = list((tmp_path / "audit").glob("*.jsonl"))
    assert audit_files, "P3-1 审计日志必须落盘"
    records = [
        json.loads(line)
        for line in audit_files[0].read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert records
    for record in records:
        for field in (
            "chart_id",
            "stage",
            "decision",
            "evidence_ids",
            "quality_issues",
            "degradation",
            "retry_of",
        ):
            assert field in record, f"审计记录缺 {field}"
    decisions = {record["decision"] for record in records}
    assert "generated" in decisions
