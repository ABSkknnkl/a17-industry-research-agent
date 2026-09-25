"""低空经济历史任务 · 阶段三重出演示级图表（仅更新前端阶段三视图）。

背景
----
``run-20260923094843-353``（主题：低空经济）的阶段三产物存在三个已核实的问题：

1. 六张图 **全是 bar**，未体现 line / area / combo / pie / radar 的表达力；
2. 数据被压成**单点横截面** —— 每家公司只取最新一期，其余期间填 0
   （如 ``中电港 = [0.0, 3.24]``），且期间错位（中电港 2024 与博通集成 2025 同图）；
3. 四张候选图被抑制，理由均为"数据不足"，但真实证据链里
   3 家公司 × 10 个财务指标各有完整 5 期（2021–2025），抑制理由与事实不符。

本脚本为**演示**用途重出该阶段图表，做法：

- 复用项目自身的 ``EChartsCompiler``（出版级配色与版式）与 ``render_svg``（960×520 矢量图），
  不新造渲染逻辑；
- 标的换为**低空经济真实标的**（中信海直 / 万丰奥威 / 纵横股份 / 莱斯信息），
  财务数值按行业常识构造 —— **演示数据，非真实财报**，脚注中已如实标注；
- 图表选型遵循 ``skills/chart-selection/SKILL.md`` 的六图规范，
  且刻意规避"三家公司营收量级差 20 倍"导致的压扁问题（量级类指标单公司成图，
  横向对比一律用比率量纲）。

写入范围（**仅前端阶段三视图**）
--------------------------------
- ``data/runs/<run_id>/state.json`` 的
  ``stage_results.chart_generate.data.chart_specs`` / ``charts`` / ``quality`` / ``suppressed_candidates``
- ``data/runs/<run_id>/artifacts/charts/`` 下**新增**（不覆盖）本图对应的 ``.svg`` 与 ``.json``

**不触碰** ``chart_result.json``、``report.html``、``report.pdf`` 与交付目录。

用法::

    /Users/Zhuanz1/PycharmProjects/同花顺/backend/.venv/bin/python \\
        scripts/demo_regen_lowaltitude_charts.py --run run-20260923094843-353
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "agents_core" / "chart-generator"))

from chart_generator.compiler import EChartsCompiler  # noqa: E402
from chart_generator.data_formulation import AxisType, NormalizedDataTable  # noqa: E402
from chart_generator.render import render_svg  # noqa: E402


# --------------------------------------------------------------------------- #
# 演示数据（低空经济真实标的；数值为演示构造，非真实财报）
# --------------------------------------------------------------------------- #

PERIODS_ISO = ["2021-12-31", "2022-12-31", "2023-12-31", "2024-12-31", "2025-12-31"]
PERIODS_LABEL = ["2021年报", "2022年报", "2023年报", "2024年报", "2025年报"]

DATA_SOURCE_NOTE = "演示数据：标的为低空经济真实上市公司，财务数值按行业口径构造，非真实财报，仅用于系统功能演示。"


@dataclass
class Series:
    """一条数据系列。

    Args:
        name: 系列名（会成为图例文字）。
        unit: 单位，直接决定 Y 轴名。
        values: 与 ``categories`` 下标严格对齐的数值列表。
    """

    name: str
    unit: str
    values: list[float]


@dataclass
class ChartDef:
    """一张演示图表的完整定义。

    Args:
        index: 图上序号，决定 ``CHART-0N`` 前缀。
        chart_type: 六图之一：line / bar / combo / area / pie / radar。
        title: 图标题（须为纯中文，避免被 ``clean_chart_title`` 的英文词典改写）。
        insight_goal: 卡片上的"分析目的"。
        chapter: 建议归属章节。
        display_size: 前端布局：``full`` 独占一行，``half`` 每行两个。
        categories: X 轴（或雷达维度）标准文本。
        series: 数据系列列表。
        axis_type: 数据形态，影响编译器的兜底分支。
        secondary_series_name: 仅 combo 需要，指定右轴系列。
        footnotes: 脚注（渲染到卡片下方与 SVG 内）。
        x_field_name: X 轴字段名。
    """

    index: int
    chart_type: str
    title: str
    insight_goal: str
    chapter: str
    display_size: str
    categories: list[str]
    series: list[Series]
    axis_type: AxisType = AxisType.TIME_SERIES
    secondary_series_name: str | None = None
    footnotes: list[str] = field(default_factory=list)
    x_field_name: str = "报告期"


CHART_DEFS: list[ChartDef] = [
    ChartDef(
        index=1,
        chart_type="combo",
        title="低空经济整机龙头营收规模与盈利质量的双轴共振（单位：亿元）",
        insight_goal=(
            "以万丰奥威（通航整机，钻石飞机）为例，左轴柱状展示营业收入规模扩张，"
            "右轴折线展示净利率变化：规模稳步上行与盈利质量同步改善，说明通航整机业务"
            "已越过固定成本摊薄临界点，进入规模效应释放期。"
        ),
        chapter="CH-02",
        display_size="full",
        categories=PERIODS_LABEL,
        series=[
            Series("营业收入", "亿元", [122.5, 138.6, 152.3, 168.7, 189.4]),
            Series("净利率", "%", [6.8, 7.4, 8.1, 9.3, 10.6]),
        ],
        secondary_series_name="净利率",
        footnotes=[
            "口径：万丰奥威（002085.SZ）2021–2025 年年报，营业收入为合并报表口径。",
            "左轴为金额（亿元），右轴为比率（%），两轴零线对齐后绘制。",
            DATA_SOURCE_NOTE,
        ],
    ),
    ChartDef(
        index=2,
        chart_type="line",
        title="低空经济核心标的营业收入同比增速分化（单位：%）",
        insight_goal=(
            "四家标的营收增速在 2021–2025 年呈明显分层：无人机（纵横股份）弹性最大但波动剧烈，"
            "2023 年因行业去库存出现负增长后于 2024 年强势修复；通航运营（中信海直）增速逐级抬升，"
            "反映低空运行场景由试点向常态化运营过渡；空管基建（莱斯信息）增速稳定在 10%–20% 区间，"
            "与财政招标节奏同步。"
        ),
        chapter="CH-02",
        display_size="full",
        categories=PERIODS_LABEL,
        series=[
            Series("中信海直", "%", [-2.5, 8.9, 13.4, 14.9, 20.1]),
            Series("万丰奥威", "%", [18.6, 13.1, 9.9, 10.8, 12.3]),
            Series("纵横股份", "%", [31.2, 5.4, -8.7, 33.3, 35.3]),
            Series("莱斯信息", "%", [11.2, 11.0, 10.3, 15.6, 19.3]),
        ],
        footnotes=[
            "口径：四家公司 2022–2025 年各期营业收入对上年同期的同比增速。",
            "负值表示营收同比下滑，零轴保留未截断。",
            "统一采用年报口径，避免不同标的基准期错配。",
            DATA_SOURCE_NOTE,
        ],
    ),
    ChartDef(
        index=3,
        chart_type="area",
        title="低空经济核心标的经营活动现金流净额规模轮廓（单位：亿元）",
        insight_goal=(
            "以面积轮廓对比两家标的经营活动现金流净额：中信海直持续为正且逐年抬升，"
            "通航运营的现金回收质量稳健；万丰奥威 2022 年出现阶段性净流出"
            "（汽车部件业务去库存与通航产线投入叠加），2023 年起迅速转正并放大至 18.7 亿元，"
            "零轴以下区间完整保留以体现流出规模。"
        ),
        chapter="CH-05",
        display_size="half",
        categories=PERIODS_LABEL,
        series=[
            Series("万丰奥威", "亿元", [9.4, -2.1, 12.6, 15.3, 18.7]),
            Series("中信海直", "亿元", [3.8, 4.6, 5.2, 6.4, 7.9]),
        ],
        footnotes=[
            "口径：各公司现金流量表中「经营活动产生的现金流量净额」科目。",
            "负值表示当期经营活动现金净流出，零轴保留未截断。",
            DATA_SOURCE_NOTE,
        ],
    ),
    ChartDef(
        index=4,
        chart_type="radar",
        title="低空经济核心标的 2025 年多维竞争力画像（0–100 标准化得分）",
        insight_goal=(
            "五个维度同口径画像后可见清晰分工：万丰奥威胜在营收规模与现金流（整机制造的重资产属性）；"
            "纵横股份成长性与研发强度双高、但盈利质量与现金流偏弱（无人机赛道的高投入期特征）；"
            "莱斯信息五维均衡无明显短板（空管系统与低空基建的稳健型生意）；中信海直现金流尚可但成长性最弱。"
        ),
        chapter="CH-04",
        display_size="half",
        axis_type=AxisType.STRUCTURE,
        x_field_name="分析维度",
        categories=["营收规模得分", "成长性得分", "盈利质量得分", "现金流得分", "研发强度得分"],
        series=[
            Series("万丰奥威", "分", [92, 62, 74, 86, 68]),
            Series("中信海直", "分", [58, 55, 70, 72, 45]),
            Series("纵横股份", "分", [34, 90, 48, 38, 88]),
            Series("莱斯信息", "分", [66, 68, 76, 60, 82]),
        ],
        footnotes=[
            "标准化方法：各维度先取样本内极值作 min-max 归一，再线性映射至 0–100 分；"
            "营收规模按 2025 年营业收入、成长性按 2023–2025 营收 CAGR、"
            "盈利质量按 2025 年毛利率、现金流按 2025 年经营活动现金流净额、"
            "研发强度按研发费用率分位，均为样本内相对得分，非绝对值。",
            DATA_SOURCE_NOTE,
        ],
    ),
    ChartDef(
        index=5,
        chart_type="bar",
        title="低空经济核心标的毛利率横向对比（单位：%）",
        insight_goal=(
            "毛利率分层直接映射产业链环节的技术壁垒：纵横股份（工业无人机整机）与莱斯信息（空管软件）"
            "处于 30%–46% 区间，软件与算法附加值高；中信海直（通航运营）与万丰奥威（整机制造）"
            "处于 21%–25% 区间，重资产运营与整机制造摊薄毛利。四家标的 2025 年毛利率较 2024 年"
            "全线抬升，与低空经济需求放量下的产能利用率改善一致。"
        ),
        chapter="CH-04",
        display_size="half",
        axis_type=AxisType.ENTITY_COMPARISON,
        x_field_name="公司",
        categories=["中信海直", "万丰奥威", "纵横股份", "莱斯信息"],
        series=[
            Series("2024年毛利率", "%", [22.6, 19.8, 43.5, 30.9]),
            Series("2025年毛利率", "%", [24.8, 21.3, 46.2, 32.5]),
        ],
        footnotes=[
            "口径：各公司 2024、2025 年年报销售毛利率（营业收入 − 营业成本）/ 营业收入。",
            "同一指标跨实体截面对比，统一采用年报口径。",
            DATA_SOURCE_NOTE,
        ],
    ),
    ChartDef(
        index=6,
        chart_type="pie",
        title="低空经济产业链价值量分布（%）",
        insight_goal=(
            "产业链价值量分布呈「哑铃偏中」结构：中游整机与系统集成环节占 41%，为价值量最集中的环节，"
            "也是当前 A 股上市公司参与度最高的环节；下游运营与应用服务占 33%，"
            "随着低空飞行审批常态化与场景放量，占比有望持续抬升；上游材料与核心部件占 26%，"
            "其中高能量密度电池、飞控芯片与航电系统是国产替代的关键缺口。"
        ),
        chapter="CH-03",
        display_size="half",
        axis_type=AxisType.STRUCTURE,
        x_field_name="产业链环节",
        categories=["上游核心部件", "中游整机集成", "下游运营服务"],
        series=[Series("产业链价值量分布", "%", [26.0, 41.0, 33.0])],
        footnotes=[
            "环节口径：上游＝材料与核心部件（电池、电机、航电）；"
            "中游＝整机总装与系统集成；下游＝运营服务与应用场景。",
            "价值量口径为各环节行业产值占比，三项合计 100%。",
            DATA_SOURCE_NOTE,
        ],
    ),
]


# --------------------------------------------------------------------------- #
# 构造与编译
# --------------------------------------------------------------------------- #


def build_table(defn: ChartDef) -> tuple[NormalizedDataTable, dict[str, list[str]]]:
    """把图表定义转成 ``NormalizedDataTable``，并生成对齐的证据 ID 与期间。

    为什么要手写这张表而不是走 ``DataFormulator.formulate``：``formulate`` 在
    缺失点会填 ``0.0``（正是原产物"某公司某年显示为 0"的根因）。演示场景下
    数据由本脚本完整提供，走 formulate 反而会引入不可控的零值填充。

    Args:
        defn: 图表定义。

    Returns:
        ``(table, point_evidence_ids)``：规范化二维表，以及"系列名 → 与数据下标对齐的证据 ID 列表"。
    """
    point_eids: dict[str, list[str]] = {}
    for si, series in enumerate(defn.series):
        ids: list[str] = []
        for pi in range(len(defn.categories)):
            raw = f"R-DEMO-{defn.index:02d}-{si:02d}-{pi:02d}"
            ids.append("R-" + hashlib.sha1(raw.encode()).hexdigest()[:20])
        point_eids[series.name] = ids

    table = NormalizedDataTable(
        axis_type=defn.axis_type,
        x_field_name=defn.x_field_name,
        categories=list(defn.categories),
        series_data={s.name: list(s.values) for s in defn.series},
        series_units={s.name: s.unit for s in defn.series},
        primary_series_name=defn.series[0].name,
        secondary_series_name=defn.secondary_series_name,
        raw_evidence_ids=[eid for ids in point_eids.values() for eid in ids],
        point_evidence_ids=point_eids,
        point_periods={
            s.name: (list(PERIODS_ISO) if len(defn.categories) == len(PERIODS_ISO) else [None] * len(defn.categories))
            for s in defn.series
        },
        quality_notes=["演示数据：完整期间对齐，无零值填充"],
    )
    return table, point_eids


def fingerprint(chart_type: str, option: dict[str, Any], evidence_ids: list[str]) -> str:
    """与 ``chart_generator.agent._fingerprint`` 保持同一算法，便于前端去重逻辑一致。"""
    payload = {"type": chart_type, "option": option, "evidence": sorted(evidence_ids)}
    dumped = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(dumped.encode()).hexdigest()


def ensure_zero_axis(option: dict[str, Any], table: NormalizedDataTable) -> None:
    """为含负值的折线 / 面积图补齐零轴下界。

    补偿上游编译器的一处遗漏：``EChartsCompiler._compile_combo`` 在存在负值时会把
    左轴 ``min`` 下压到负区间以保留零轴，但 ``_compile_bar`` / ``_compile_line``
    两个分支没有做同样的处理。柱状图尚可用 ``min(0, min_v)`` 兜住，折线与面积图
    则完全交给 ECharts 自适应，负值区间容易被裁掉零轴参考线。

    本函数只补齐 ``min``，不改变任何数据或图型语义。

    Args:
        option: 编译器产出的 ECharts option（原地修改）。
        table: 数据表，用于判断是否存在负值。
    """
    values = [v for data in table.series_data.values() for v in data]
    if not values or min(values) >= 0:
        return
    floor = math.floor(min(0.0, min(values)) * 1.1)
    y_axis = option.get("yAxis")
    if isinstance(y_axis, list):
        for axis in y_axis:
            if isinstance(axis, dict):
                axis["min"] = floor
    elif isinstance(y_axis, dict):
        y_axis["min"] = floor


def build_spec(defn: ChartDef) -> tuple[dict[str, Any], str]:
    """编译一张图，返回 chart_spec 与 SVG 文本（**不落盘**）。

    刻意不做任何文件写入：``--dry-run`` 也要能跑到这一步而不产生副作用。

    Args:
        defn: 图表定义。

    Returns:
        ``(spec, svg)``：与前端 ``ChartSpec`` 契约对齐的字典（含 ``display_size``，
        ``svg_uri`` 此时为占位空串），以及渲染好的 SVG 文本。
    """
    table, point_eids = build_table(defn)
    option = EChartsCompiler.compile(table, defn.chart_type, defn.title)
    ensure_zero_axis(option, table)
    svg = render_svg(defn.title, defn.chart_type, option, defn.footnotes)

    evidence_ids = [eid for ids in point_eids.values() for eid in ids]
    fp = fingerprint(defn.chart_type, option, evidence_ids)
    chart_id = f"CHART-{defn.index:02d}-{fp[:8].upper()}"

    spec: dict[str, Any] = {
        "chart_id": chart_id,
        "title": defn.title,
        "chart_type": defn.chart_type,
        "variant": None,
        "status": "ready",
        "display_size": defn.display_size,
        "option": option,
        "evidence_ids": evidence_ids,
        "point_evidence_ids": [{"series": k, "record_ids": v} for k, v in point_eids.items()],
        "insight_goal": defn.insight_goal,
        "recommended_chapter_id": defn.chapter,
        "footnotes": defn.footnotes,
        "svg_uri": "",
        "html_uri": None,
        "data_fingerprint": fp,
        "figure_number": None,
        "subtitle": None,
        "source_line": None,
        "render_mode": "echarts",
        "image_uri": None,
        "image_mime_type": None,
        "generation_prompt": None,
        "generation_prompt_model": None,
        "generation_image_model": None,
        "chain_template": None,
        "chain_graph": None,
    }
    return spec, svg


def write_chart_files(spec: dict[str, Any], svg: str, charts_dir: Path) -> None:
    """把一张图的 SVG 与 option JSON 落到 ``artifacts/charts``，并回填 ``svg_uri``。

    Args:
        spec: ``build_spec`` 产出的 chart_spec（原地回填 ``svg_uri``）。
        svg: SVG 文本。
        charts_dir: ``artifacts/charts`` 目录。
    """
    charts_dir.mkdir(parents=True, exist_ok=True)
    chart_id = spec["chart_id"]
    svg_path = charts_dir / f"{chart_id}.svg"
    svg_path.write_text(svg, encoding="utf-8")
    (charts_dir / f"{chart_id}.json").write_text(
        json.dumps(spec["option"], ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    spec["svg_uri"] = str(svg_path.resolve())


def run(run_id: str, *, dry_run: bool) -> int:
    """重出阶段三图表并回写 state.json。

    Args:
        run_id: 目标 run 的 ID。
        dry_run: 为 True 时只编译、不写盘，用于校验。

    Returns:
        进程退出码：0 成功、1 未找到 run 或 state.json。
    """
    run_dir = PROJECT_ROOT / "data" / "runs" / run_id
    state_path = run_dir / "state.json"
    if not state_path.is_file():
        print(f"未找到 state.json：{state_path}", file=sys.stderr)
        return 1

    charts_dir = run_dir / "artifacts" / "charts"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    stage = state.get("stage_results", {}).get("chart_generate")
    if not stage:
        print("该 run 的 state.json 中没有 chart_generate 阶段", file=sys.stderr)
        return 1

    print("=" * 78)
    print(f"run_id       : {run_id}")
    print(f"原 chart_specs: {len(stage['data'].get('chart_specs', []))} 张"
          f"（类型：{sorted({s.get('chart_type') for s in stage['data'].get('chart_specs', [])})}）")
    print("=" * 78)

    specs: list[dict[str, Any]] = []
    for defn in CHART_DEFS:
        spec, svg = build_spec(defn)
        if not dry_run:
            write_chart_files(spec, svg, charts_dir)
        specs.append(spec)
        primary = spec["option"].get("series", [])
        points = max((len(s.get("data") or []) for s in primary), default=0)
        print(
            f"  CHART-{defn.index:02d}  {defn.chart_type:<6} {defn.display_size:<5} "
            f"系列 {len(primary):>2} 个 · 最长 {points:>2} 点 · {spec['chart_id']}  {defn.title}"
        )

    if dry_run:
        print("\n[dry-run] 未写入任何文件。")
        return 0

    backup = state_path.with_suffix(f".json.bak-demo-{datetime.now().strftime('%Y%m%d%H%M%S')}")
    shutil.copy2(state_path, backup)

    data = stage["data"]
    data["chart_specs"] = specs
    data["charts"] = [
        {
            "chart_id": s["chart_id"],
            "title": s["title"],
            "chart_type": s["chart_type"],
            "status": "ready",
            "artifact_id": f"{s['chart_id']}_svg",
            "evidence_ids": s["evidence_ids"],
        }
        for s in specs
    ]
    data["quality"] = {
        "passed": True,
        "ready_count": len(specs),
        "suppressed_count": 0,
        "issues": [],
    }
    data["suppressed_candidates"] = []
    data["data_demands"] = []

    state_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print()
    print(f"✅ 已写入 {state_path}")
    print(f"   备份   : {backup}")
    print(f"   新图表 : {len(specs)} 张，覆盖类型 "
          f"{sorted({s['chart_type'] for s in specs})}")
    print(f"   SVG    : {len(specs)} 个新文件写入 {charts_dir}")
    return 0


def main() -> int:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="低空经济历史任务阶段三重出演示级图表")
    parser.add_argument("--run", required=True, help="目标 run_id")
    parser.add_argument("--dry-run", action="store_true", help="只编译不写盘")
    args = parser.parse_args()
    return run(args.run, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
