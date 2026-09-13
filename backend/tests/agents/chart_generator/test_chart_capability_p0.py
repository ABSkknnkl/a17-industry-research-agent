"""P0 层验收测试（2026-09-13 方案 §6.3）——捏造数据驱动 Agent3。

覆盖：P0-1 combo 量纲分支 / P0-2 单位占位符 / P0-3 去重键归一+抑制 /
P0-4 阈值单一来源 / P2-4 series_meta 2→4。
捏造数据规格见方案 §6.2（动力电池/新能源车）。
"""

from datetime import date

import pytest

from app.agents.chart_generator.builders import build_combo_option
from app.agents.chart_generator.constants import RECOMMENDED_CHARTS
from app.agents.chart_generator.router import (
    build_dedupe_key,
    route_chart,
)
from app.agents.chart_generator.quality import build_quality_report, validate_option
from app.schemas.chart import ChartDataset, ChartPoint, ChartSeriesMeta, ChartSpec, SuppressedChart


def _combo_dataset(
    metas: list[tuple[str, str | None]],
    *,
    unit: str | None = None,
    currency: str | None = "CNY",
    periods: tuple[date, ...] = (
        date(2021, 12, 31),
        date(2022, 12, 31),
        date(2023, 12, 31),
        date(2024, 12, 31),
        date(2025, 12, 31),
    ),
) -> ChartDataset:
    """构造 combo 数据集：metas = [(序列名, 单位)]，同时间轴、业务相关。"""

    points = []
    for name, _series_unit in metas:
        for index, period in enumerate(periods):
            points.append(
                ChartPoint(
                    label=period.isoformat(),
                    value=100.0 + index * 10,
                    series=name,
                    period_end=period,
                    evidence_id=f"E-FAKE-{name}-{index}",
                )
            )
    return ChartDataset(
        dataset_id="DS-COMBO-FAKE",
        kind="time_series",
        metric_name="营收与归母净利润",
        unit=unit,
        currency=currency,
        business_linked=True,
        series_meta=[
            ChartSeriesMeta(
                name=name,
                unit=series_unit,
                currency=currency,
                render_as="bar" if index == 0 else "line",
            )
            for index, (name, series_unit) in enumerate(metas)
        ],
        points=points,
        evidence_ids=[point.evidence_id for point in points],
    )


# ---------------------------------------------------------------------------
# P0-1 combo 量纲分支
# ---------------------------------------------------------------------------


def test_p01_combo_same_unit_single_axis() -> None:
    """DS-REV-PROFIT（营收+归母净利润，同为亿元）→ combo 单轴，不降级。"""
    dataset = _combo_dataset([("营业收入", "亿元"), ("归母净利润", "亿元")])
    decision = route_chart("combo", dataset)
    assert decision.accepted, decision.reason
    assert decision.chart_type == "combo"
    option = build_combo_option("营收与归母净利润对比", dataset)
    assert len(option["yAxis"]) == 1, "同量纲 combo 必须单轴"
    assert "亿元" in option["yAxis"][0]["name"]


def test_p01_combo_dual_unit_two_axis() -> None:
    """DS-VOL-GROWTH（销量万辆+增速%）→ combo 双轴，两轴单位均标注。"""
    dataset = _combo_dataset([("销量", "万辆"), ("增速", "%")])
    decision = route_chart("combo", dataset)
    assert decision.accepted, decision.reason
    option = build_combo_option("销量与增速", dataset)
    assert len(option["yAxis"]) == 2
    axis_names = {axis["name"] for axis in option["yAxis"]}
    assert any("万辆" in name for name in axis_names)
    assert any("%" in name for name in axis_names)


def test_p01_combo_zero_unit_rejected() -> None:
    """单位全为占位符（归一后不可知）→ 拒绝出图。"""
    dataset = _combo_dataset(
        [("营收", "未提供"), ("净利润", "文本")], currency=None
    )
    decision = route_chart("combo", dataset)
    assert not decision.accepted
    assert decision.reason_code == "combo_requirements_not_met"


def test_p01_combo_placeholder_same_currency_single_axis() -> None:
    """两序列单位都占位但币种相同 → 归一后同一量纲 → 单轴。"""
    dataset = _combo_dataset([("营收", "未提供"), ("净利润", "不适用")])
    decision = route_chart("combo", dataset)
    assert decision.accepted


# ---------------------------------------------------------------------------
# P0-2 单位占位符不进轴名
# ---------------------------------------------------------------------------


def test_p02_axis_name_no_placeholder() -> None:
    """DS-UNIT-MISSING：unit 占位 → 轴名不含占位符。"""
    dataset = _combo_dataset([("营业收入", "亿元"), ("归母净利润", "亿元")], unit="未提供")
    option = build_combo_option("营收趋势", dataset)
    for axis in option["yAxis"]:
        assert "未提供" not in axis.get("name", "")
        assert "文本" not in axis.get("name", "")


def test_p02_placeholder_to_footnote() -> None:
    """占位符出现在 footnotes（[需核实:货币单位]），不在轴名。"""
    dataset = _combo_dataset([("营业收入", "未提供"), ("归母净利润", "未提供")])
    option = build_combo_option("营收趋势", dataset)
    assert any("[需核实:货币单位]" in str(item) for item in option.get("footnotes", []))
    for axis in option["yAxis"]:
        assert "[需核实" not in axis.get("name", "")


def test_p02_quality_gate_unit_missing() -> None:
    """unit 缺失 → quality 报告含 unit_missing_or_placeholder（当且仅当）。"""
    missing = _combo_dataset([("营业收入", "未提供"), ("净利润", "未提供")])
    option_missing = build_combo_option("营收", missing)
    issues_missing = validate_option(option_missing)
    assert "unit_missing_or_placeholder" in issues_missing

    present = _combo_dataset([("营业收入", "亿元"), ("净利润", "亿元")])
    option_present = build_combo_option("营收", present)
    assert "unit_missing_or_placeholder" not in validate_option(option_present)


# ---------------------------------------------------------------------------
# P0-3 去重键归一 + 恢复抑制
# ---------------------------------------------------------------------------


def test_p03_dedupe_goal_normalized() -> None:
    """“展示趋势”与“展示变化”→ build_dedupe_key 相同（slot=trend）。"""
    key_trend = build_dedupe_key("line", "fp", insight_goal="展示趋势")
    key_change = build_dedupe_key("line", "fp", insight_goal="展示变化")
    key_walk = build_dedupe_key("line", "fp", insight_goal="观察出货量走势")
    assert key_trend == key_change == key_walk
    assert "trend" in key_trend
    # 不同槽位不归并。
    key_compare = build_dedupe_key("line", "fp", insight_goal="对比厂商出货量")
    assert key_compare != key_trend


def test_p03_dedupe_slots_covered() -> None:
    """五大槽位各自命中：trend/composition/comparison/ranking/positioning。"""
    assert "trend" in build_dedupe_key("line", "fp", insight_goal="展示趋势")
    assert "composition" in build_dedupe_key("pie", "fp", insight_goal="展示成本构成")
    assert "comparison" in build_dedupe_key("bar", "fp", insight_goal="对比三家厂商")
    assert "ranking" in build_dedupe_key("bar", "fp", insight_goal="展示排名")
    assert "positioning" in build_dedupe_key("scatter", "fp", insight_goal="竞争格局定位")


@pytest.mark.asyncio
async def test_p03_duplicate_suppressed(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DS-DUP-TREND：6 个同义 goal 候选 → 1 spec + 5 suppressed。

    需 allow_multiple_charts_per_dataset=true 跨过 fingerprint 拦截，
    使 dedupe key 抑制成为唯一防线（方案 P0-3 两步的第二步）。
    """
    from app.core.config import settings

    from tests.agents.chart_generator.test_agent import _evidence_items

    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    from app.schemas.workflow import StageName, StageResult, StageStatus
    from app.workflow.stages import StageContext

    from app.agents.chart_generator.service import ChartGeneratorAgent

    periods = tuple(date(2021 + i, 12, 31) for i in range(5))
    points = [
        ChartPoint(
            label=p.isoformat(),
            value=100.0 + i * 8,
            series="出货量",
            period_end=p,
            evidence_id=f"E-DUP-{i}",
        )
        for i, p in enumerate(periods)
    ]
    dataset = ChartDataset(
        dataset_id="DS-DUP-TREND",
        kind="time_series",
        metric_name="动力电池出货量",
        unit="GWh",
        points=points,
        evidence_ids=[p.evidence_id for p in points],
    )
    goals = [
        "展示趋势",
        "展示变化",
        "观察出货量走势",
        "出货量变化趋势",
        "看出货量趋势",
        "呈现出货量变化",
    ]
    context = StageContext(
        project_id="p",
        run_id="run-p03-dup",
        revision=1,
        input_data={
            "chart_datasets": [dataset.model_dump(mode="json")],
            "evidence_items": _evidence_items(dataset.evidence_ids),
            "chart_generate_options": {"allow_multiple_charts_per_dataset": True},
        },
        previous_results={
            StageName.DATA_INTERPRET: StageResult(
                stage=StageName.DATA_INTERPRET,
                status=StageStatus.COMPLETED,
                data={
                    "chart_candidates": [
                        {
                            "title": f"出货量分析{i}",
                            "chart_type": "line",
                            "evidence_ids": dataset.evidence_ids,
                            "insight_goal": goal,
                        }
                        for i, goal in enumerate(goals)
                    ]
                },
            )
        },
    )
    result = await ChartGeneratorAgent().run(context)
    data = result.data
    assert len(data["chart_specs"]) == 1, "同义 goal 去重后只能出 1 张"
    duplicates = [
        item
        for item in data["suppressed_candidates"]
        if item["reason_code"] == "duplicate_chart"
    ]
    assert len(duplicates) == 5, "其余 5 个完全重复候选必须抑制"


@pytest.mark.asyncio
async def test_p03_same_family_warns_not_suppress(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同 family 不同 slot（trend vs comparison）→ 告警但不抑制。"""
    from app.core.config import settings

    from tests.agents.chart_generator.test_agent import _evidence_items

    monkeypatch.setattr(settings, "ARTIFACT_ROOT", tmp_path)
    from app.schemas.workflow import StageName, StageResult, StageStatus
    from app.workflow.stages import StageContext

    from app.agents.chart_generator.service import ChartGeneratorAgent

    periods = tuple(date(2021 + i, 12, 31) for i in range(5))
    points = [
        ChartPoint(
            label=p.isoformat(),
            value=100.0 + i * 8,
            series="出货量",
            period_end=p,
            evidence_id=f"E-FAM-{i}",
        )
        for i, p in enumerate(periods)
    ]
    dataset = ChartDataset(
        dataset_id="DS-FAM",
        kind="time_series",
        metric_name="动力电池出货量",
        unit="GWh",
        points=points,
        evidence_ids=[p.evidence_id for p in points],
    )
    context = StageContext(
        project_id="p",
        run_id="run-p03-fam",
        revision=1,
        input_data={
            "chart_datasets": [dataset.model_dump(mode="json")],
            "evidence_items": _evidence_items(dataset.evidence_ids),
            "chart_generate_options": {"allow_multiple_charts_per_dataset": True},
        },
        previous_results={
            StageName.DATA_INTERPRET: StageResult(
                stage=StageName.DATA_INTERPRET,
                status=StageStatus.COMPLETED,
                data={
                    "chart_candidates": [
                        {
                            "title": "出货量趋势",
                            "chart_type": "line",
                            "evidence_ids": dataset.evidence_ids,
                            "insight_goal": "展示趋势",
                        },
                        {
                            "title": "出货量对比",
                            "chart_type": "line",
                            "evidence_ids": dataset.evidence_ids,
                            "insight_goal": "对比各年出货量",
                        },
                    ]
                },
            )
        },
    )
    result = await ChartGeneratorAgent().run(context)
    data = result.data
    assert len(data["chart_specs"]) == 2, "同 family 不同 slot 不得抑制"
    assert not any(
        item["reason_code"] == "duplicate_chart"
        for item in data["suppressed_candidates"]
    )


# ---------------------------------------------------------------------------
# P0-4 阈值单一来源 + P2-4 series_meta
# ---------------------------------------------------------------------------


def test_p04_single_source_threshold() -> None:
    """RECOMMENDED_CHARTS 在 chart_generator 内仅 constants.py 一处定义。"""
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "app" / "agents" / "chart_generator"
    result = subprocess.run(
        ["grep", "-rn", "RECOMMENDED_CHARTS =", str(root)],
        capture_output=True,
        text=True,
    )
    definitions = [
        line
        for line in result.stdout.splitlines()
        if "constants.py" not in line or "RECOMMENDED_CHARTS_PER" in line
    ]
    non_alias = [
        line
        for line in definitions
        if "= (" not in line or "constants.py" in line
    ]
    # 别名行（planner/service 的 RECOMMENDED_P1 = ...）允许；直接字面定义只许 constants。
    literal_defs = [
        line
        for line in result.stdout.splitlines()
        if "RECOMMENDED_CHARTS = (" in line and "constants.py" not in line
    ]
    assert not literal_defs, f"发现 constants.py 之外的字面定义: {literal_defs}"
    assert RECOMMENDED_CHARTS == (5, 8)


def test_p24_series_meta_max_length_4() -> None:
    """series_meta max_length=4；4 序列 combo（带 panels）不被拒。"""
    dataset = _combo_dataset(
        [("销量", "万辆"), ("增速", "%"), ("营收", "亿元"), ("毛利率", "%")]
    )
    assert len(dataset.series_meta) == 4
    # 4 序列无 panels → 拒绝（回退 line 由降级链处理，不抛错）。
    decision = route_chart("combo", dataset)
    assert not decision.accepted
    assert decision.reason_code == "panels_missing_for_dual_panel"
    # 带 panels → dual_panel 变体（model_validate 保证 ChartPanel 实例化）。
    payload = dataset.model_dump(mode="json")
    payload["panels"] = [
        {"panel_id": "P1", "position": "left", "series": ["销量", "营收"], "axis_name": "万辆/亿元"},
        {"panel_id": "P2", "position": "right", "series": ["增速", "毛利率"], "axis_name": "%"},
    ]
    dataset_panels = ChartDataset.model_validate(payload)
    decision_panels = route_chart("combo", dataset_panels)
    assert decision_panels.accepted
    assert decision_panels.variant == "dual_panel"


def test_p01_footnotes_in_quality_report() -> None:
    """quality report 集成：spec 构建链路 footnotes 与 issue 透出。"""
    spec = ChartSpec.model_validate(
        {
            "chart_id": "CHART-P02",
            "title": "营收与归母净利润对比：净利润同比增长25%",
            "chart_type": "combo",
            "variant": "combo",
            "option": build_combo_option(
                "营收与归母净利润对比",
                _combo_dataset([("营业收入", "未提供"), ("归母净利润", "未提供")]),
            ),
            "evidence_ids": ["E-1"],
            "data_fingerprint": "a" * 64,
            "dedupe_key": "combo:test",
        }
    )
    report = build_quality_report(
        candidate_count=1,
        specs=[spec],
        suppressed=[],
    )
    assert "unit_missing_or_placeholder" in report.issues
