"""A3 数值图通用展示配置（presentation）。

职责：在 A3 点级证据校验通过之后、首次 SVG 渲染之前，为已发布的数值图
附加一份版本化的展示配置，并把它翻译成 ECharts 原生字段
（``yAxis[].min/max/interval``、``series[].label``）。

边界（对应实施方案「展示配置与数据边界」）：
* **只改展示层**：不触碰 xAxis.data、yAxis[].name/type、series[].name/type/data、
  legend.data、observation_range、evidence_ids、data_contract 等保护字段。
* 配置存于 ``option.presentation``，按 version 读取；前端与 SVG 共享同一份轴定义。
* 预设是「针对基线数据的展示预设」：运行时先校验全部有限数值与参考线，
  遇到越界/非法范围时回退通用规则，通用规则也失败则不附加配置。
* 产业链图（industry_chain）走现有专用入口，不参与展示配置。

版本化模型用纯标准库校验，避免给 chart-generator 引入额外依赖。
"""

from __future__ import annotations

import copy
import math
from dataclasses import asdict, dataclass, field
from typing import Any

PRESENTATION_VERSION = 1
MAX_TICKS = 100
NEV_SUBJECT = "新能源汽车"

SUPPORTED_NUMERIC_TYPES = {
    "bar", "horizontal_bar", "comparison_bar", "diverging_bar",
    "line", "area", "combo", "scatter", "bubble",
    "pie", "donut", "radar", "treemap", "heatmap", "boxplot",
}

# 保护字段：应用展示配置前后必须逐项一致
PROTECTED_PATHS = (
    ("xAxis", "data"),
    ("observation_range",),
    ("legend", "data"),
)


@dataclass(frozen=True)
class AxisPresentation:
    series_index: int
    min: float
    max: float
    interval: float


@dataclass(frozen=True)
class LabelPresentation:
    series_index: int
    mode: str = "all"                       # all | key | endpoints | none
    point_indices: tuple[int, ...] = ()
    decimals: int = 2


@dataclass(frozen=True)
class Presentation:
    version: int = PRESENTATION_VERSION
    short_title: str = ""
    period_labels: str = "auto"             # year | month | auto
    plot_height: str = "regular"            # regular | compact
    axes: tuple[AxisPresentation, ...] = ()
    labels: tuple[LabelPresentation, ...] = ()
    note: str = ""
    reference_lines: tuple[dict[str, Any], ...] = ()
    role: str = ""
    fallback_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["axes"] = [asdict(a) for a in self.axes]
        data["labels"] = [asdict(l) for l in self.labels]
        data["reference_lines"] = [dict(r) for r in self.reference_lines]
        return data


# ---------------------------------------------------------------------------
# 新能源汽车五图确定性预设（轴范围/刻度针对基线数据，运行时逐项校验）
# ---------------------------------------------------------------------------
NEV_PRESETS: dict[str, Presentation] = {
    "nev.q1.sales": Presentation(
        short_title="新能源汽车销量及同比", period_labels="year",
        axes=(
            AxisPresentation(0, 0, 1800, 300),
            AxisPresentation(1, 0, 100, 20),
        ),
        labels=(
            LabelPresentation(0, "all", decimals=2),
            LabelPresentation(1, "key", (1, 4), decimals=1),
        ),
        note="2025 年销量 1,649 万辆，同比 +28.2%",
        role="nev.q1.sales",
    ),
    "nev.q2.margin": Presentation(
        short_title="整车组毛利率", period_labels="year",
        axes=(AxisPresentation(0, 12, 32, 4),),
        labels=(
            LabelPresentation(0, "endpoints", decimals=2),
            LabelPresentation(1, "endpoints", decimals=2),
            LabelPresentation(2, "endpoints", decimals=2),
        ),
        note="8/9 个有效观测，赛力斯 2023 年观测按 A2 裁定隔离；纵轴采用局部范围",
        role="nev.q2.margin",
    ),
    "nev.q2.margin_partial": Presentation(
        short_title="整车组毛利率", period_labels="year",
        axes=(AxisPresentation(0, 12, 32, 4),),
        labels=(
            LabelPresentation(0, "endpoints", decimals=2),
            LabelPresentation(1, "endpoints", decimals=2),
            LabelPresentation(2, "endpoints", decimals=2),
        ),
        note="8/9 个有效观测，赛力斯 2023 年观测按 A2 裁定隔离；纵轴采用局部范围",
        role="nev.q2.margin_partial",
    ),
    "nev.q4.exports": Presentation(
        short_title="新能源汽车出口量及同比", period_labels="year",
        axes=(
            AxisPresentation(0, 0, 300, 60),
            AxisPresentation(1, 0, 120, 30),
        ),
        labels=(
            LabelPresentation(0, "all", decimals=2),
            LabelPresentation(1, "key", (3, 4), decimals=1),
        ),
        note="2025 年出口 258.43 万辆，同比 +102.8%",
        role="nev.q4.exports",
    ),
    "nev.q3.battery_rd": Presentation(
        short_title="电池组研发费用率", period_labels="year", plot_height="compact",
        axes=(AxisPresentation(0, 4.50, 5.50, 0.25),),
        labels=(LabelPresentation(0, "all", decimals=2),),
        note="2025 年为 5.18%，较 2024 年回落约 0.06 个百分点；保留同源金额倍率假设说明",
        role="nev.q3.battery_rd",
    ),
    "nev.q1.monthly": Presentation(
        short_title="国内零售渗透率", period_labels="month",
        axes=(AxisPresentation(0, 48, 62, 2),),
        labels=(LabelPresentation(0, "key", (0, 8, 9), decimals=1),),
        note="3–12 月增加 8.0 个百分点，11 月达到 59.3%",
        reference_lines=({"series_index": 0, "value": 50, "style": "neutral_dashed"},),
        role="nev.q1.monthly",
    ),
}


# ---------------------------------------------------------------------------
# 数值读取与校验
# ---------------------------------------------------------------------------
def _num(value: Any) -> float | None:
    if isinstance(value, dict):
        value = value.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(float(value)) else None


def _axis_key(chart_type: str) -> str:
    return "xAxisIndex" if chart_type == "horizontal_bar" else "yAxisIndex"


def axis_values(option: dict[str, Any], chart_type: str, axis_index: int) -> list[float]:
    """按已校验的轴索引分组，读取绑定到该轴的全部有限值。"""
    key = _axis_key(chart_type)
    out: list[float] = []
    for series in option.get("series") or []:
        if not isinstance(series, dict):
            continue
        if int(series.get(key, 0) or 0) != axis_index:
            continue
        for item in series.get("data") or []:
            v = _num(item)
            if v is not None:
                out.append(v)
    return out


def _enumerable_ticks(axis: AxisPresentation) -> list[float] | None:
    count = (axis.max - axis.min) / axis.interval
    if count <= 0 or count > MAX_TICKS or abs(count - round(count)) > 1e-6:
        return None
    n = int(round(count))
    return [round(axis.min + i * axis.interval, 10) for i in range(n + 1)]


def validate_presentation(
    presentation: Presentation, option: dict[str, Any], chart_type: str
) -> list[str]:
    """返回问题列表；空列表代表配置可用于渲染。"""
    problems: list[str] = []
    if presentation.version != PRESENTATION_VERSION:
        problems.append(f"不支持的展示配置版本 {presentation.version}")
    if chart_type not in SUPPORTED_NUMERIC_TYPES:
        problems.append(f"图型 {chart_type} 不在通用数值图范围")
    if chart_type in ("pie", "donut", "radar", "treemap", "heatmap", "boxplot") \
            and presentation.axes:
        problems.append("构成/多维图当前不注入数值轴范围")

    series = option.get("series") or []
    for axis in presentation.axes:
        if not (0 <= axis.series_index < max(len(series), 1)):
            problems.append(f"轴 series_index {axis.series_index} 越界")
            continue
        if not (math.isfinite(axis.min) and math.isfinite(axis.max)
                and math.isfinite(axis.interval)):
            problems.append("轴范围含非有限值")
            continue
        if axis.min >= axis.max or axis.interval <= 0:
            problems.append(f"轴范围非法 min={axis.min} max={axis.max} interval={axis.interval}")
            continue
        if _enumerable_ticks(axis) is None:
            problems.append("刻度范围不可枚举或超过上限")
        vals = axis_values(option, chart_type, axis.series_index)
        if vals and (min(vals) < axis.min - 1e-9 or max(vals) > axis.max + 1e-9):
            problems.append(
                f"轴 {axis.series_index} 未覆盖全部实际点 "
                f"[{min(vals):.6f}, {max(vals):.6f}] vs [{axis.min}, {axis.max}]"
            )
        if chart_type in ("bar", "comparison_bar", "horizontal_bar", "diverging_bar", "combo") \
                and axis.min > 0:
            problems.append("规模柱/双轴的值轴必须包含 0")

    # 双轴共享零线：两轴都含 0 且 0 的像素位置一致
    if chart_type == "combo" and len(presentation.axes) >= 2:
        a, b = presentation.axes[0], presentation.axes[1]
        if a.min > 0 or b.min > 0:
            problems.append("双轴必须共享零线（两轴下界均 ≤ 0）")
        elif abs((0 - a.min) / (a.max - a.min) - (0 - b.min) / (b.max - b.min)) > 1e-6:
            problems.append("双轴零线像素位置不一致")

    for label in presentation.labels:
        if not (0 <= label.series_index < max(len(series), 1)):
            problems.append(f"标签 series_index {label.series_index} 越界")
            continue
        data = series[label.series_index].get("data") or []
        for idx in label.point_indices:
            if not (0 <= idx < len(data)) or _num(data[idx]) is None:
                problems.append(f"标签索引 {idx} 不是非空点")
        if label.mode not in ("all", "key", "endpoints", "none"):
            problems.append(f"未知标签模式 {label.mode}")

    for ref in presentation.reference_lines:
        idx, val = int(ref.get("series_index", 0)), ref.get("value")
        matching = [a for a in presentation.axes if a.series_index == idx]
        if matching and isinstance(val, (int, float)) \
                and not (matching[0].min <= val <= matching[0].max):
            problems.append(f"参考线 {val} 超出轴范围")
    return problems


# ---------------------------------------------------------------------------
# 通用展示配置（其他行业及新增数值图）
# ---------------------------------------------------------------------------
def _nice_interval(span: float) -> float:
    if span <= 0:
        return 1.0
    raw = span / 5.0
    magnitude = 10 ** math.floor(math.log10(raw))
    for factor in (1, 2, 2.5, 5, 10):
        if raw <= factor * magnitude:
            return factor * magnitude
    return 10 * magnitude


def build_generic_presentation(option: dict[str, Any], chart_type: str) -> Presentation:
    """按实施方案「其他数值图的通用优化」计算轴范围、标签与图幅。"""
    if chart_type not in SUPPORTED_NUMERIC_TYPES:
        return Presentation()
    axes_cfg = option.get("yAxis") if chart_type != "horizontal_bar" else option.get("xAxis")
    axes_list = axes_cfg if isinstance(axes_cfg, list) else ([axes_cfg] if isinstance(axes_cfg, dict) else [])
    series = option.get("series") or []
    axes: list[AxisPresentation] = []
    for idx in range(len(axes_list) or 1):
        vals = axis_values(option, chart_type, idx)
        if not vals:
            continue
        lo, hi = min(vals), max(vals)
        is_barish = chart_type in ("bar", "comparison_bar", "horizontal_bar", "diverging_bar")
        is_combo = chart_type == "combo"
        if is_barish or is_combo or lo < 0:
            low = min(0.0, lo)
        else:
            # 折线/面积/散点：按观测跨度采用明确标示的局部刻度
            pad = (hi - lo) * 0.12 or (abs(hi) * 0.05 or 1.0)
            low = lo - pad
        if is_barish or is_combo:
            pad_top = (hi - low) * 0.10 or 1.0
            high = hi + pad_top
        else:
            pad = (hi - lo) * 0.12 or (abs(hi) * 0.05 or 1.0)
            high = hi + pad
        if math.isclose(low, high):
            # 恒定序列：由单位精度决定的有限刻度间隔
            step = 0.25 if abs(hi) < 10 else _nice_interval(abs(hi) or 1.0)
            low, high = hi - 2 * step, hi + 2 * step
        else:
            step = _nice_interval(high - low)
        # 把上下界对齐到刻度，保证可枚举
        low = math.floor(low / step) * step
        high = math.ceil(high / step) * step
        if high <= low:
            high = low + step
        axes.append(AxisPresentation(idx, round(low, 10), round(high, 10), step))

    n_points = max((len(s.get("data") or []) for s in series), default=0)
    labels: list[LabelPresentation] = []
    for i, s in enumerate(series):
        data = s.get("data") or []
        non_null = [j for j, v in enumerate(data) if _num(v) is not None]
        if not non_null:
            continue
        if len(non_null) <= 3:
            labels.append(LabelPresentation(i, "all", tuple(non_null), decimals=2))
        else:
            labels.append(LabelPresentation(
                i, "key", (non_null[0], non_null[-1]), decimals=2
            ))
    height = "compact" if 0 < n_points <= 3 else "regular"
    return Presentation(
        short_title="", period_labels="auto", plot_height=height,
        axes=tuple(axes), labels=tuple(labels), role="generic",
    )


# ---------------------------------------------------------------------------
# 角色识别与配置应用
# ---------------------------------------------------------------------------
def resolve_chart_role(
    chart_type: str,
    *,
    subject: str = "",
    title: str = "",
    contract: dict[str, Any] | None = None,
) -> str | None:
    """基线匹配用主题 + 已核实数据角色 + 图型；非新能源汽车不命中预设。"""
    if subject and NEV_SUBJECT not in str(subject):
        return None
    metrics = {
        str(p.get("metric", "")) for p in (contract or {}).get("points", [])
    }
    metric_text = " ".join(metrics)
    text = f"{title} {metric_text}"
    if chart_type == "combo":
        if "出口" in text or "出口量" in metric_text:
            return "nev.q4.exports"
        if "销量" in text or "销量" in metric_text:
            return "nev.q1.sales"
    if chart_type in ("line", "area"):
        if "渗透率" in text or "渗透率" in metric_text:
            return "nev.q1.monthly"
        if "研发" in text or "rd_ratio" in metric_text or "rd_expense" in metric_text:
            return "nev.q3.battery_rd"
        if "毛利率" in text or "gross_margin" in metric_text:
            categories = (contract or {}).get("categories") or []
            series_order = (contract or {}).get("series_order") or []
            points = (contract or {}).get("points") or []
            has_gap = bool(categories and series_order and len(points) < len(categories) * len(series_order))
            return "nev.q2.margin_partial" if has_gap else "nev.q2.margin"
    return None


def _protected_snapshot(option: dict[str, Any]) -> dict[str, Any]:
    def get(path: tuple[str, ...]) -> Any:
        node: Any = option
        for key in path:
            if not isinstance(node, dict):
                return None
            node = node.get(key)
        return copy.deepcopy(node)

    snap = {"/".join(p): get(p) for p in PROTECTED_PATHS}
    snap["series.data"] = [
        copy.deepcopy(s.get("data")) for s in option.get("series") or [] if isinstance(s, dict)
    ]
    snap["series.name"] = [
        s.get("name") for s in option.get("series") or [] if isinstance(s, dict)
    ]
    snap["series.type"] = [
        s.get("type") for s in option.get("series") or [] if isinstance(s, dict)
    ]
    snap["axis.name"] = [
        a.get("name") if isinstance(a, dict) else None
        for a in (option.get("yAxis") if isinstance(option.get("yAxis"), list)
                  else [option.get("yAxis")])
    ]
    return snap


def apply_presentation(
    option: dict[str, Any],
    chart_type: str,
    *,
    subject: str = "",
    title: str = "",
    contract: dict[str, Any] | None = None,
    presentation: Presentation | None = None,
) -> tuple[dict[str, Any], Presentation | None, str]:
    """返回 (新 option, 生效配置, 回退原因)。任何校验失败都安全回退。

    * ``presentation`` 可由 AI 提议传入；校验失败时按本图确定性预设 →
      通用规则 → 原 option 逐级回退（实施方案「按顺序实施」末段）。
    """
    if chart_type not in SUPPORTED_NUMERIC_TYPES or not isinstance(option, dict):
        return option, None, "unsupported_chart_type"

    role = resolve_chart_role(chart_type, subject=subject, title=title, contract=contract)
    candidates: list[tuple[str, Presentation]] = []
    if presentation is not None:
        candidates.append(("ai_proposal", presentation))
    if role and role in NEV_PRESETS:
        candidates.append(("nev_preset", NEV_PRESETS[role]))
    candidates.append(("generic", build_generic_presentation(option, chart_type)))

    fallback_reason = ""
    chosen: Presentation | None = None
    for source, candidate in candidates:
        problems = validate_presentation(candidate, option, chart_type)
        if not problems:
            chosen = candidate
            if source != "ai_proposal" and candidates and candidates[0][0] == "ai_proposal":
                fallback_reason = "ai_proposal_rejected"
            break
        fallback_reason = f"{source}:{problems[0]}"
    if chosen is None:
        return option, None, fallback_reason or "all_presentations_failed"

    original_snapshot = _protected_snapshot(option)
    out = copy.deepcopy(option)

    axis_key = "xAxis" if chart_type == "horizontal_bar" else "yAxis"
    axes_obj = out.get(axis_key)
    for axis in chosen.axes:
        if isinstance(axes_obj, list):
            if not (0 <= axis.series_index < len(axes_obj)):
                continue
            target = axes_obj[axis.series_index]
        else:
            target = axes_obj
        if isinstance(target, dict):
            target["min"] = axis.min
            target["max"] = axis.max
            target["interval"] = axis.interval
            target["splitNumber"] = len(_enumerable_ticks(axis) or []) - 1

    # 前端 ECharts 原生 label：具体的按索引显示与小数位由 presentation.labels
    # 在前端 sanitizedOption 中生成 formatter；SVG 端由 render_svg 直接读取。
    for label in chosen.labels:
        series_list = out.get("series") or []
        if not (0 <= label.series_index < len(series_list)):
            continue
        if label.mode == "none":
            continue
        series_list[label.series_index].setdefault("label", {})
        lab = series_list[label.series_index]["label"]
        if isinstance(lab, dict):
            lab["show"] = True
            lab["position"] = "top"
            lab["fontSize"] = 10

    out["presentation"] = chosen.to_dict()
    out["presentation"]["role"] = role or chosen.role
    if fallback_reason:
        out["presentation"]["fallback_reason"] = fallback_reason

    if _protected_snapshot(out) != original_snapshot:
        return option, None, "protected_fields_changed"
    return out, chosen, fallback_reason


def read_presentation(option: dict[str, Any]) -> dict[str, Any] | None:
    """渲染层读取：只接受版本化、且 axes 为合法结构的配置。"""
    pres = option.get("presentation") if isinstance(option, dict) else None
    if not isinstance(pres, dict) or pres.get("version") != PRESENTATION_VERSION:
        return None
    if not isinstance(pres.get("axes"), list):
        return None
    return pres


def explicit_ticks(axis_index: int, option: dict[str, Any]) -> list[float] | None:
    """给 render_svg 使用：按 versioned 配置返回可枚举刻度，否则 None 走自动尺度。"""
    pres = read_presentation(option)
    if not pres:
        return None
    for axis in pres["axes"]:
        if int(axis.get("series_index", -1)) != axis_index:
            continue
        try:
            lo, hi, step = float(axis["min"]), float(axis["max"]), float(axis["interval"])
        except (KeyError, TypeError, ValueError):
            return None
        if not (math.isfinite(lo) and math.isfinite(hi) and math.isfinite(step)) \
                or lo >= hi or step <= 0:
            return None
        count = (hi - lo) / step
        if count > MAX_TICKS or abs(count - round(count)) > 1e-6:
            return None
        return [round(lo + i * step, 10) for i in range(int(round(count)) + 1)]
    return None


def label_spec(series_index: int, option: dict[str, Any]) -> dict[str, Any] | None:
    pres = read_presentation(option)
    if not pres:
        return None
    for label in pres.get("labels", []):
        if int(label.get("series_index", -1)) == series_index:
            return label
    return None


def should_label(spec: dict[str, Any] | None, index: int, count: int) -> bool:
    if not spec:
        return False
    mode = spec.get("mode", "none")
    if mode == "none":
        return False
    if mode == "all":
        return True
    if mode == "endpoints":
        return index in (0, count - 1)
    return index in set(spec.get("point_indices") or [])


def format_label(value: float, spec: dict[str, Any] | None, *, suffix: str = "") -> str:
    decimals = int((spec or {}).get("decimals", 2))
    return f"{value:.{decimals}f}{suffix}"
