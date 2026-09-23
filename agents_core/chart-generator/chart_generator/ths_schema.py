"""点级图表数据契约：ChartDataset / ChartPoint / ChartPanel / ChartSeriesMeta。

## 为什么需要这个模块

本项目原有的 `NormalizedDataTable`（见 `data_formulation.py`）是**展平结构**：

    categories: list[str]                      # X 轴文本
    series_data: dict[str, list[float]]        # 系列名 -> 纯数值列表
    raw_evidence_ids: list[str]                # 一整个列表

`categories[i]` 与 `series_data[k][i]` 靠**下标**对应，点与证据的对应关系在展平
过程中已经丢失 —— `raw_evidence_ids` 无法还原“第 i 个点用的是哪条证据”。
本模块用 `ChartPoint(label, value, series, period_end, evidence_id)` 承载点级
信息，使每个数据点都可追溯（`evidence_id` 为必填字段）。

## 借鉴来源与明确边界

- **数据契约借鉴**同花顺 `backend/app/schemas/chart.py`：核心收益就是
  `ChartPoint.evidence_id` 必填这一设计。
- **配色不借鉴**同花顺：其 `UP_COLOR = "#C0392B"` / `DOWN_COLOR = "#1E8449"`
  （涨红跌绿）是**行情语义**，与本项目“行业研究出版级”配色冲突 —— 本项目
  `compiler.PALETTE` 六个色位**没有绿色**，且正负值区分用「主蓝 / 警示红」。
  因此本模块**不含任何颜色常量**，配色一律由 `compiler` / `render` 的 PALETTE 决定。
- **类型收窄**：同花顺 `ChartDataset.kind` 含 `industry_chain` / `xy` / `matrix` /
  `distribution` / `hierarchy` 五种，恰好对应本项目**禁用**的下排图型
  （scatter / bubble / heatmap / boxplot / treemap / industry_chain）。此处收窄为
  `time_series` / `categorical` 两种，使禁用类型**在数据层就没有表达能力**，
  而不是只靠上层 `normalize_active_chart_type` 单点拦截。
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# 六种启用图型（line/bar/combo/area/pie/radar）只需两种数据形态即可覆盖：
#   time_series -> line / area / combo(dual_axis)
#   categorical -> bar / pie / radar / combo(dual_panel)
ActiveKind = Literal["time_series", "categorical"]


class ChartPoint(BaseModel):
    """单个数据点。`evidence_id` 必填 —— 点级溯源的落点。

    Attributes:
        label: X 轴标签（实体名或报告期）。
        value: 数值，允许 None（表示缺失，绘图时留空而非补零）。
        series: 所属系列名，多系列/双轴图用于分组。
        period_end: 报告期，时序图据此排序。
        value_kind: actual=已实现，forecast=预测。由 period_end 是否晚于研究时点推导。
        evidence_id: 证据记录 ID，**必须**来自 `report.evidence_index`。
        is_synthetic: 是否为补齐数据形态而构造的模拟数据。真实数据恒为 False；
            置 True 的数据不得计入证据覆盖率，供演示产物与真实产物区分。
    """

    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=200)
    value: int | float | None
    series: str = Field(default="默认", min_length=1, max_length=100)
    period_end: date | None = None
    value_kind: Literal["actual", "forecast"] = "actual"
    evidence_id: str = Field(min_length=1)
    is_synthetic: bool = False


class ChartSeriesMeta(BaseModel):
    """系列级渲染与单位元数据，供 combo 双轴 / dual_panel 使用。

    Attributes:
        name: 系列名，需与 `ChartPoint.series` 一致。
        unit: 该系列的单位（如“亿元”“%”），用于轴名披露。
        currency: 币种，与 unit 拼接为轴名。
        render_as: 该系列画成柱还是线。
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    unit: str = Field(default="", max_length=50)
    currency: str | None = Field(default=None, max_length=20)
    render_as: Literal["bar", "line"] = "line"


class ChartPanel(BaseModel):
    """dual_panel 复合图的一侧面板（左右分区，各有独立 X/Y 轴）。

    Attributes:
        panel_id: 面板标识。
        position: 左或右。
        series: 该面板承载的系列名列表，需存在于 `ChartDataset.points`。
        axis_name: Y 轴名，用于披露该面板的单位。
    """

    model_config = ConfigDict(extra="forbid")

    panel_id: str = Field(min_length=1, max_length=50)
    position: Literal["left", "right"]
    series: list[str] = Field(min_length=1, max_length=4)
    axis_name: str | None = Field(default=None, max_length=100)


class ChartAnnotation(BaseModel):
    """可审计的图表标注（参考线 / 标注）。

    Attributes:
        annotation_type: reference_line=横向参考线；callout=点标注。
        label: 标注文字。
        value: 参考线取值（reference_line 时使用）。
        series: 作用的系列名（callout 时使用）。
    """

    model_config = ConfigDict(extra="forbid")

    annotation_type: Literal["reference_line", "callout"]
    label: str = Field(default="", max_length=100)
    value: float | None = None
    series: str | None = Field(default=None, max_length=100)


class ChartDataset(BaseModel):
    """图表生成的标准化输入（点级）。

    Attributes:
        dataset_id: 数据集标识。
        kind: 数据形态，收窄为 time_series / categorical。
        metric_name: 主指标名。
        unit: 主指标单位。
        currency: 币种。
        is_additive: 数值是否可相加（决定能否画堆叠）。
        is_composition: 是否构成类（各部分占比合计有意义）—— pie 的**唯一**判据，
            取代“合计有意义”这类无法代码化的启发式。
        series_meta: 系列级元数据。
        panels: dual_panel 的面板定义，非 dual_panel 时为空。
        annotations: 标注。
        data_as_of: 数据时点，用于推导 value_kind。
        points: 数据点列表（点级 evidence）。
        evidence_ids: 去重后的证据 ID 汇总，供快速校验。
    """

    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(min_length=1, max_length=100)
    kind: ActiveKind
    metric_name: str = Field(min_length=1, max_length=200)
    unit: str | None = None
    currency: str | None = None
    is_additive: bool = False
    is_composition: bool = False
    series_meta: list[ChartSeriesMeta] = Field(default_factory=list, max_length=4)
    panels: list[ChartPanel] = Field(default_factory=list, max_length=2)
    annotations: list[ChartAnnotation] = Field(default_factory=list, max_length=10)
    data_as_of: date | None = None
    points: list[ChartPoint] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)

    def point_evidence_ids(self, *, include_synthetic: bool = False) -> list[str]:
        """返回去重后的点级证据 ID。

        Args:
            include_synthetic: 是否包含 `is_synthetic=True` 的模拟数据点。
                默认 False —— 模拟数据不应进入真实证据链。

        Returns:
            按首次出现顺序去重的 evidence_id 列表。
        """
        seen: dict[str, None] = {}
        for point in self.points:
            if point.is_synthetic and not include_synthetic:
                continue
            seen.setdefault(point.evidence_id, None)
        return list(seen)

    def series_names(self) -> list[str]:
        """按首次出现顺序返回系列名列表。"""
        return list(dict.fromkeys(point.series for point in self.points))
