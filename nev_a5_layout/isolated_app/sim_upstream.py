#!/usr/bin/env python3
"""伪造 NEV 上游数据（A1 dataset / A2 report / A3 charts），明确标注模拟。

数值刻意与真实样例不同，避免与真实报告混淆；本文件只用于真实 LLM 联调
与 A5 排版验证，不得对外引用为行业结论。
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

DST = Path(__file__).resolve().parent
for p in (DST, DST / "agents_core", DST / "agents_core/report-fusion"):
    sys.path.insert(0, str(p))

from chapter_writer.models import (  # noqa: E402
    ChartRef, ChartResult, EvidenceRef, Insight, InterpretationReport,
)

SIM_TAG = "【模拟数据】"
SIM_NOTE = (f"{SIM_TAG}本数据集为 A5 版式与真实模型联调用例，数值为虚构，"
            "不代表任何真实行业或公司披露，不得对外引用。")

SALES = {2021: 320.0, 2022: 640.0, 2023: 900.0, 2024: 1180.0, 2025: 1500.0}
EXPORT = {2021: 30.0, 2022: 62.0, 2023: 104.0, 2024: 118.0, 2025: 220.0}
PENETRATION = {"2021-12": 21.0, "2022-12": 27.5, "2023-12": 37.0,
               "2024-12": 45.5, "2025-12": 55.0}
COMPANIES = {
    "比亚迪": {"group": "整车", "rev25": 7600.0, "rev23": 5700.0, "gm25": 17.2,
               "gm23": 19.8, "ocf25": 640.0, "ocf23": 1500.0, "np25": 300.0,
               "rd25": 520.0, "rd23": 360.0},
    "长安汽车": {"group": "整车", "rev25": 1580.0, "rev23": 1460.0, "gm25": 15.1,
                 "gm23": 17.9, "ocf25": 22.0, "ocf23": 180.0, "np25": 42.0,
                 "rd25": 70.0, "rd23": 58.0},
    "赛力斯": {"group": "整车", "rev25": 1600.0, "rev23": 350.0, "gm25": 27.5,
               "gm23": 10.5, "ocf25": 270.0, "ocf23": 60.0, "np25": 56.0,
               "rd25": 76.0, "rd23": 16.0},
    "宁德时代": {"group": "电池", "rev25": 4100.0, "rev23": 3900.0, "gm25": 25.8,
                 "gm23": 22.5, "ocf25": 1280.0, "ocf23": 900.0, "np25": 690.0,
                 "rd25": 215.0, "rd23": 180.0},
    "亿纬锂能": {"group": "电池", "rev25": 600.0, "rev23": 470.0, "gm25": 15.9,
                 "gm23": 16.8, "ocf25": 72.0, "ocf23": 84.0, "np25": 40.0,
                 "rd25": 29.0, "rd23": 26.0},
}


def build():
    sim_dir = DST / "output" / "sim"
    sim_dir.mkdir(parents=True, exist_ok=True)
    sim_svg = sim_dir / "sim_chart.svg"
    sim_svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 220">'
        '<rect width="600" height="220" fill="#ffffff"/>'
        '<rect width="600" height="3" fill="#0A5C5C"/>'
        '<text x="24" y="58" font-size="19" fill="#0A5C5C">模拟数据图（非真实披露）</text>'
        '<line x1="40" y1="180" x2="560" y2="180" stroke="#dfe3e8" stroke-width="2"/>'
        '<polyline points="40,158 140,138 240,132 340,108 440,92 560,74" '
        'fill="none" stroke="#0A5C5C" stroke-width="3"/></svg>',
        encoding="utf-8")

    evidence: dict[str, EvidenceRef] = {}

    def add(rid: str, domain: str, metric: str, entity: str | None,
            value, unit: str, period: date, ptype: str = "annual"):
        evidence[rid] = EvidenceRef(
            record_id=rid, domain=domain, metric=metric, entity=entity,
            value=value, unit=unit, period=period, period_type=ptype,
            period_provenance="simulated", scope="consolidated",
            issues=[SIM_TAG], trace_id="sim-trace",
        )

    for i, (year, value) in enumerate(SALES.items(), 1):
        add(f"R-sim-sales-{year}", "macro", "新能源汽车:销量:累计值", None,
            value, "万辆", date(year, 12, 31))
    for i, (year, value) in enumerate(EXPORT.items(), 1):
        add(f"R-sim-export-{year}", "industry", "新能源汽车:出口量", None,
            value, "万辆", date(year, 12, 31))
    for ym, value in PENETRATION.items():
        add(f"R-sim-pen-{ym}", "macro", "国内零售渗透率:新能源汽车:当月值", None,
            value, "%", date(int(ym[:4]), int(ym[5:7]), 28), ptype="month")
    for name, c in COMPANIES.items():
        add(f"R-sim-rev-{name}-2025", "financial", "营业收入", name,
            c["rev25"], "亿元", date(2025, 12, 31))
        add(f"R-sim-gm-{name}-2025", "financial", "销售毛利率", name,
            c["gm25"], "%", date(2025, 12, 31))
        add(f"R-sim-ocf-{name}-2025", "financial", "经营活动现金流净额", name,
            c["ocf25"], "亿元", date(2025, 12, 31))
        add(f"R-sim-rd-{name}-2025", "financial", "研发费用", name,
            c["rd25"], "亿元", date(2025, 12, 31))

    key_metrics = [
        {"label": "2025年销量", "value": "1,500.0", "unit": "万辆",
         "period": "2025", "evidence_ids": ["R-sim-sales-2025"]},
        {"label": "2025年末渗透率", "value": "55.0", "unit": "%",
         "period": "2025-12", "evidence_ids": ["R-sim-pen-2025-12"]},
        {"label": "2025年出口", "value": "220.0", "unit": "万辆",
         "period": "2025", "evidence_ids": ["R-sim-export-2025"]},
        {"label": "比亚迪毛利率", "value": "17.2", "unit": "%",
         "period": "2025", "evidence_ids": ["R-sim-gm-比亚迪-2025"]},
        {"label": "宁德时代毛利率", "value": "25.8", "unit": "%",
         "period": "2025", "evidence_ids": ["R-sim-gm-宁德时代-2025"]},
        {"label": "赛力斯毛利率", "value": "27.5", "unit": "%",
         "period": "2025", "evidence_ids": ["R-sim-gm-赛力斯-2025"]},
    ]
    trends = [
        {"metric": "新能源汽车:销量:累计值", "points": len(SALES),
         "start": "2021-12-31", "end": "2025-12-31",
         "direction": "上行", "evidence_ids": [f"R-sim-sales-{y}" for y in SALES]},
        {"metric": "新能源汽车:出口量", "points": len(EXPORT),
         "start": "2021-12-31", "end": "2025-12-31",
         "direction": "加速上行", "evidence_ids": [f"R-sim-export-{y}" for y in EXPORT]},
        {"metric": "国内零售渗透率:新能源汽车:当月值", "points": len(PENETRATION),
         "start": "2021-12", "end": "2025-12",
         "direction": "台阶式上行", "evidence_ids": [f"R-sim-pen-{k}" for k in PENETRATION]},
    ]
    insights = [
        Insight(insight_id="I-01", title="销量仍在扩张但增速换挡",
                conclusion="2021—2025 年模拟销量从 320.0 增至 1,500.0 万辆，"
                           "2025 年增量 320.0 万辆，增速回落但绝对增量仍高。",
                significance="判断需求是否见顶要看增量而非单看增速。",
                confidence="medium",
                evidence_record_ids=[f"R-sim-sales-{y}" for y in SALES]),
        Insight(insight_id="I-02", title="出口成为第二增长极",
                conclusion="模拟出口从 30.0 增至 220.0 万辆，2025 年同比约 +86%。",
                significance="出口对总量的边际贡献上升。", confidence="medium",
                evidence_record_ids=[f"R-sim-export-{y}" for y in EXPORT]),
        Insight(insight_id="I-03", title="渗透率台阶上行但月度有回撤",
                conclusion="模拟渗透率从 2021-12 的 21.0% 升至 2025-12 的 55.0%，"
                           "单月存在季节性回撤。",
                significance="单月回撤不等于趋势反转。", confidence="medium",
                evidence_record_ids=[f"R-sim-pen-{k}" for k in PENETRATION]),
        Insight(insight_id="I-04", title="毛利率组内差异大于组间差异",
                conclusion="模拟 2025 年整车组毛利率 15.1%—27.5%，"
                           "电池组 15.9%—25.8%，组内极差明显。",
                significance="应按环节分组比较，不跨组排名。", confidence="low",
                evidence_record_ids=["R-sim-gm-比亚迪-2025", "R-sim-gm-长安汽车-2025",
                                     "R-sim-gm-赛力斯-2025", "R-sim-gm-宁德时代-2025",
                                     "R-sim-gm-亿纬锂能-2025"]),
        Insight(insight_id="I-05", title="现金流分化早于利润分化",
                conclusion="模拟比亚迪 OCF 从 1,500.0 降至 640.0 亿元，"
                           "长安从 180.0 降至 22.0 亿元，赛力斯从 60.0 升至 270.0 亿元。",
                significance="现金转化差异需要营运资金附注才能归因。", confidence="low",
                evidence_record_ids=[f"R-sim-ocf-{n}-2025" for n in COMPANIES]
                + ["R-sim-ocf-比亚迪-2025"]),
    ]
    report = InterpretationReport(
        report_id="SIM-NEV-A2-20261114", subject="新能源汽车",
        as_of=date(2026, 11, 14), status="completed",
        executive_summary=f"{SIM_TAG}模拟新能源汽车行业解读：销量与出口扩张、"
                          "渗透率台阶上行、整车与电池组内毛利率差异大于组间差异。",
        key_metrics=key_metrics, trends=trends, insights=insights,
        evidence_index=evidence,
        industry_chain_segments=[
            {"segment": "上游", "items": ["锂", "正极", "负极", "隔膜", "电解液"],
             "note": f"{SIM_TAG}上游未纳入样本，只做结构定位"},
            {"segment": "中游", "items": ["动力电池", "电机电控"],
             "note": f"{SIM_TAG}样本仅宁德时代、亿纬锂能"},
            {"segment": "下游", "items": ["整车制造", "充电", "换电", "回收"],
             "note": f"{SIM_TAG}样本仅比亚迪、长安汽车、赛力斯"},
        ],
        financial_ratios=[
            {"entity": name, "group": c["group"], "gross_margin": c["gm25"],
             "rd_intensity": round(c["rd25"] / c["rev25"] * 100, 2),
             "ocf_to_np": round(c["ocf25"] / c["np25"], 2)}
            for name, c in COMPANIES.items()
        ],
        analysis_facts={
            "sales_growth_2025": "SIM 20.3%",
            "export_share_2025": "SIM 14.7%",
            "penetration_2025_12": "SIM 55.0%",
        },
        warnings=[SIM_NOTE],
    )

    chart_list = [
            ChartRef(chart_id="SIM-C-01", title="模拟销量及同比（2021—2025）",
                     chart_type="combo", evidence_ids=[f"R-sim-sales-{y}" for y in SALES],
                     insight_goal="看总量与增速", recommended_chapter_id="CH-02",
                     data_contract={"unit": "万辆", "frequency": "annual"}),
            ChartRef(chart_id="SIM-C-02", title="模拟渗透率月度路径（2021-12—2025-12）",
                     chart_type="line", evidence_ids=[f"R-sim-pen-{k}" for k in PENETRATION],
                     insight_goal="看台阶与回撤", recommended_chapter_id="CH-02",
                     data_contract={"unit": "%", "frequency": "monthly",
                                    "missing_points": ["2021-01"]}),
            ChartRef(chart_id="SIM-C-03", title="模拟出口量及同比（2021—2025）",
                     chart_type="combo", evidence_ids=[f"R-sim-export-{y}" for y in EXPORT],
                     insight_goal="看第二增长极", recommended_chapter_id="CH-02",
                     data_contract={"unit": "万辆", "frequency": "annual"}),
            ChartRef(chart_id="SIM-C-04", title="模拟整车组毛利率（2023—2025）",
                     chart_type="line",
                     evidence_ids=["R-sim-gm-比亚迪-2025", "R-sim-gm-长安汽车-2025",
                                   "R-sim-gm-赛力斯-2025"],
                     insight_goal="看组内分化", recommended_chapter_id="CH-05",
                     data_contract={"unit": "%", "frequency": "annual"}),
            ChartRef(chart_id="SIM-C-05", title="模拟电池组毛利率（2023—2025）",
                     chart_type="line",
                     evidence_ids=["R-sim-gm-宁德时代-2025", "R-sim-gm-亿纬锂能-2025"],
                     insight_goal="看电池组分化", recommended_chapter_id="CH-05",
                     data_contract={"unit": "%", "frequency": "annual"}),
            ChartRef(chart_id="SIM-C-06", title="模拟经营现金流（2023—2025）",
                     chart_type="line", evidence_ids=[f"R-sim-ocf-{n}-2025" for n in COMPANIES],
                     insight_goal="看现金分化", recommended_chapter_id="CH-05",
                     data_contract={"unit": "亿元", "frequency": "annual"}),
            ChartRef(chart_id="SIM-C-07", title="模拟研发强度（2025）",
                     chart_type="bar", evidence_ids=[f"R-sim-rd-{n}-2025" for n in COMPANIES],
                     insight_goal="看研发投入差异", recommended_chapter_id="CH-05",
                     data_contract={"unit": "%", "frequency": "annual"}),
            ChartRef(chart_id="SIM-C-08", title="模拟产业链结构（上游—中游—下游）",
                     chart_type="industry_chain",
                     evidence_ids=[], insight_goal="看环节关系",
                     recommended_chapter_id="CH-03",
                     data_contract={"unit": None, "frequency": None}),
    ]
    for item in chart_list:
        item.svg_uri = str(sim_svg)
    charts = ChartResult(run_id="SIM-NEV-A3-20261114", charts=chart_list,
                         warnings=[SIM_NOTE])
    dataset = {
        "run_id": "SIM-NEV-A1-20261114", "subject": "新能源汽车",
        "as_of": "2026-11-14", "record_count": len(evidence),
        "records": [e.model_dump(mode="json") for e in evidence.values()],
        "note": SIM_NOTE,
    }
    return report, charts, dataset


def main() -> int:
    report, charts, dataset = build()
    out = DST / "output" / "sim"
    out.mkdir(parents=True, exist_ok=True)
    (out / "a2_interpretation_report.json").write_text(
        report.model_dump_json(indent=2), encoding="utf-8")
    (out / "a3_chart_result.json").write_text(
        charts.model_dump_json(indent=2), encoding="utf-8")
    (out / "a1_dataset.json").write_text(
        json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{SIM_TAG}上游数据已生成：evidence {len(report.evidence_index)} 条 / "
          f"charts {len(charts.charts)} 张 / dataset {len(dataset['records'])} 条")
    print(f"输出目录: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
