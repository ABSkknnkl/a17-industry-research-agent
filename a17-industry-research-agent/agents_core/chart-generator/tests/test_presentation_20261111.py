"""A3 展示配置回归（2026-11-11）。

覆盖实施方案「按顺序实施」末段要求的两条回归：
1. 出口图右轴在 option 与 SVG 中不同（0–200% vs 0–125%）；
2. 电池组研发费用率后两年都显示成 5.2（5.2478 / 5.1843）。
另覆盖保护字段、越界回退、旧图兼容、非新能源汽车主题的折线与正负值图。
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
PKG_ROOT = HERE.parents[1]
PROJECT_ROOT = HERE.parents[3]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from chart_generator import presentation as pres  # noqa: E402
from chart_generator.publication import option_contract_issue  # noqa: E402
from chart_generator.render import render_svg  # noqa: E402

BASELINE = (
    PROJECT_ROOT / "output/a3_refactor_validation/runs"
    / "a3-live-20261110235216656541/artifacts/chart_result.json"
)


@pytest.fixture(scope="module")
def baseline():
    if not BASELINE.exists():
        pytest.skip(f"冻结基线不存在：{BASELINE}")
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def _chart(baseline, chart_id):
    return next(c for c in baseline["charts"] if c["chart_id"] == chart_id)


def _present(chart):
    out, cfg, reason = pres.apply_presentation(
        chart["option"], chart["chart_type"], subject="新能源汽车",
        title=chart["title"], contract=chart["data_contract"],
    )
    assert option_contract_issue(out, chart["data_contract"], chart["chart_type"]) is None
    return out, cfg, reason


def _svg(chart, option):
    return render_svg(
        chart["title"], chart["chart_type"], option, chart["footnotes"],
        figure_number=chart["figure_number"], as_of=option["as_of"],
        source="公司公告、同花顺 iFinD、行业公开披露",
        insight_takeaway=chart["insight_goal"],
    )


# ---------------------------------------------------------------------------
# 回归 1：出口双轴 option 与 SVG 一致
# ---------------------------------------------------------------------------
def test_exports_right_axis_option_matches_svg(baseline):
    chart = _chart(baseline, "CHART-04-6339166A")
    option, cfg, _ = _present(chart)
    assert cfg.role == "nev.q4.exports"
    right = option["yAxis"][1]
    assert (right["min"], right["max"], right["interval"]) == (0, 120, 30)

    svg = _svg(chart, option)
    for tick in ("0%", "30%", "60%", "90%", "120%"):
        assert f">{tick}</text>" in svg
    assert ">125%</text>" not in svg, "旧渲染器把右轴自动算成 0–125%，与 option 不一致"
    # 左轴 0–300/60，网格跟主轴
    for tick in ("0", "60", "120", "180", "240", "300"):
        assert f">{tick}</text>" in svg
    assert ">102.8%</text>" in svg and ">10.6%</text>" in svg, "折线只标 2024、2025 两个重点点位"


def test_sales_dual_axis_and_shared_zero(baseline):
    chart = _chart(baseline, "CHART-02-8530EBAC")
    option, cfg, _ = _present(chart)
    assert cfg.role == "nev.q1.sales"
    assert (option["yAxis"][0]["max"], option["yAxis"][0]["interval"]) == (1800, 300)
    assert (option["yAxis"][1]["max"], option["yAxis"][1]["interval"]) == (100, 20)
    assert option["yAxis"][0]["min"] == option["yAxis"][1]["min"] == 0
    svg = _svg(chart, option)
    assert ">1800</text>" in svg and ">100%</text>" in svg
    assert ">95.6%</text>" in svg and ">28.2%</text>" in svg
    assert ">37.9%</text>" not in svg  # 2023 非重点点位


# ---------------------------------------------------------------------------
# 回归 2：研发费用率两位小数，后两年不再同值
# ---------------------------------------------------------------------------
def test_battery_rd_two_decimals_not_collapsed(baseline):
    chart = _chart(baseline, "CHART-05-1B49A9E3")
    option, cfg, _ = _present(chart)
    assert cfg.role == "nev.q3.battery_rd"
    assert cfg.plot_height == "compact"
    axis = option["yAxis"]
    assert (axis["min"], axis["max"], axis["interval"]) == (4.5, 5.5, 0.25)
    svg = _svg(chart, option)
    for expected in ("4.69", "5.25", "5.18"):
        assert f">{expected}</text>" in svg
    assert svg.count(">5.2</text>") == 0, "两位小数不得被 _format_num 压成 5.2"
    assert ">4.75</text>" in svg and ">5.25</text>" in svg  # 刻度完整可见
    # 短图：画布高度低于常规 540
    assert 'height="4' in svg


# ---------------------------------------------------------------------------
# 渗变率局部刻度与重点标签、毛利率末端标签
# ---------------------------------------------------------------------------
def test_penetration_local_axis_and_key_labels(baseline):
    chart = _chart(baseline, "CHART-06-5ED7CC84")
    option, cfg, _ = _present(chart)
    assert cfg.role == "nev.q1.monthly"
    assert (option["yAxis"]["min"], option["yAxis"]["max"], option["yAxis"]["interval"]) == (48, 62, 2)
    svg = _svg(chart, option)
    for tick in ("48", "50", "52", "54", "56", "58", "60", "62"):
        assert f">{tick}</text>" in svg
    for label in ("51.1", "59.3", "59.1"):
        assert f">{label}</text>" in svg
    assert "参考线" in svg
    assert ">55.2</text>" not in svg  # 只标 3/11/12 月


def test_margin_partial_keeps_gap_and_end_labels(baseline):
    chart = _chart(baseline, "CHART-03-365B59B0")
    option, cfg, _ = _present(chart)
    assert cfg.role == "nev.q2.margin_partial"
    assert (option["yAxis"]["min"], option["yAxis"]["max"], option["yAxis"]["interval"]) == (12, 32, 4)
    assert option["series"][2]["data"][0] is None, "赛力斯 2023 缺口按 A2 裁定保留"
    svg = _svg(chart, option)
    for end in ("17.74%", "15.54%", "29.14%"):
        assert end in svg
    assert ">12</text>" in svg and ">32</text>" in svg


# ---------------------------------------------------------------------------
# 数据边界与通用规则
# ---------------------------------------------------------------------------
def test_protected_fields_unchanged(baseline):
    for chart in baseline["charts"]:
        if chart["chart_type"] == "industry_chain":
            continue
        out, _, _ = _present(chart)
        assert out["xAxis"]["data"] == chart["option"]["xAxis"]["data"]
        assert out["observation_range"] == chart["option"]["observation_range"]
        assert out.get("legend") == chart["option"].get("legend")
        assert [s["name"] for s in out["series"]] == [s["name"] for s in chart["option"]["series"]]
        assert [s["type"] for s in out["series"]] == [s["type"] for s in chart["option"]["series"]]
        assert [s["data"] for s in out["series"]] == [s["data"] for s in chart["option"]["series"]]
        assert [a["name"] for a in out["yAxis"]] == [a["name"] for a in chart["option"]["yAxis"]] \
            if isinstance(out["yAxis"], list) else out["yAxis"]["name"] == chart["option"]["yAxis"]["name"]


def test_chain_chart_untouched(baseline):
    chain = _chart(baseline, "CHART-01-3552556C")
    out, cfg, reason = pres.apply_presentation(
        chain["option"], chain["chart_type"], subject="新能源汽车", title=chain["title"]
    )
    assert cfg is None and reason == "unsupported_chart_type"
    assert out == chain["option"] and "presentation" not in out


def test_out_of_range_falls_back_to_generic(baseline):
    chart = copy.deepcopy(_chart(baseline, "CHART-05-1B49A9E3"))
    chart["option"]["series"][0]["data"][2] = 9.81  # 超出 4.50–5.50 预设
    out, cfg, reason = pres.apply_presentation(
        chart["option"], chart["chart_type"], subject="新能源汽车",
        title=chart["title"], contract=chart["data_contract"],
    )
    assert reason, "预设越界必须记录回退原因"
    axis = out["yAxis"]
    assert axis["min"] <= 4.6893 and axis["max"] >= 9.81
    assert pres.validate_presentation(cfg, out, chart["chart_type"]) == []
    assert out["series"][0]["data"] == chart["option"]["series"][0]["data"]


def test_old_chart_without_presentation_uses_auto_scale(baseline):
    chart = _chart(baseline, "CHART-05-1B49A9E3")
    svg = _svg(chart, copy.deepcopy(chart["option"]))
    assert svg.startswith("<svg") and ">5.2</text>" in svg or ">5.2" in svg
    assert "presentation" not in chart["option"]


def test_generic_non_nev_line_and_diverging():
    line_option = {
        "xAxis": {"type": "category", "data": ["2023", "2024", "2025"]},
        "yAxis": {"type": "value", "name": "%"},
        "series": [{"name": "毛利率", "type": "line", "data": [20.1, None, 26.4]}],
        "observation_range": {"start": "2023-12-31", "end": "2025-12-31"},
    }
    out, cfg, reason = pres.apply_presentation(line_option, "line", subject="半导体设备")
    assert cfg.role == "generic" and not reason
    assert pres.validate_presentation(cfg, out, "line") == []
    assert out["series"][0]["data"] == [20.1, None, 26.4]
    svg = render_svg("半导体设备毛利率", "line", out, [])
    assert svg.startswith("<svg")

    diverging = {
        "xAxis": {"type": "category", "data": ["A", "B", "C"]},
        "yAxis": {"type": "value", "name": "%"},
        "series": [{"name": "同比", "type": "bar", "data": [-12.0, 3.5, 8.0]}],
    }
    out2, cfg2, _ = pres.apply_presentation(diverging, "diverging_bar", subject="光伏")
    assert cfg2.role == "generic"
    assert out2["yAxis"]["min"] <= -12.0 and out2["yAxis"]["max"] >= 8.0
    assert out2["yAxis"]["min"] <= 0 <= out2["yAxis"]["max"], "正负值比较图必须保留零线"
    assert out2["series"][0]["data"] == [-12.0, 3.5, 8.0]


def test_ai_proposal_rejected_falls_back_to_preset(baseline):
    chart = _chart(baseline, "CHART-04-6339166A")
    bad = pres.Presentation(axes=(pres.AxisPresentation(1, 10, -10, 0),))
    out, cfg, reason = pres.apply_presentation(
        chart["option"], chart["chart_type"], subject="新能源汽车",
        title=chart["title"], contract=chart["data_contract"], presentation=bad,
    )
    assert cfg.role == "nev.q4.exports"
    assert reason, "非法 AI 提议必须回退到确定性预设"
    assert (out["yAxis"][1]["min"], out["yAxis"][1]["max"]) == (0, 120)
