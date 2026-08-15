"""独立测试智能体3（图表生成）——仅测试 Agent 3，不调用 Agent 1/2/4/5。

构造覆盖全部 12 种图表类型的数据集与候选，调用 ChartGeneratorAgent.run()，
将生成的 ECharts option 嵌入 HTML 输出展示。
禁止改动任何生产代码。
"""

import asyncio
import json
import os
import sys
from datetime import date
from pathlib import Path

os.environ["no_proxy"] = "*"
os.environ["ENVIRONMENT"] = "test"

BACKEND_DIR = Path(__file__).parent / "backend"
os.chdir(str(BACKEND_DIR))
sys.path.insert(0, str(BACKEND_DIR))

from app.schemas.chart import ChartDataset
from app.schemas.analysis import ChartCandidate
from app.schemas.evidence import AuditStatus, CorporateActionAdjustment, EvidenceGrade, EvidenceItem, RestatementStatus
from app.schemas.workflow import StageName, StageResult, StageStatus
from app.workflow.stages import StageContext


def evidence(eid: str, metric: str, value=None, unit="亿元", period_end=None) -> dict:
    return EvidenceItem(
        evidence_id=eid,
        metric_name=metric,
        value=value,
        unit=unit,
        period_end=period_end,
        audit_status=AuditStatus.AUDITED,
        restatement_status=RestatementStatus.NOT_RESTATED,
        scope="宁德时代",
        market="中国",
        exchange="深圳证券交易所",
        security_type="A股",
        currency="CNY",
        accounting_standard="CAS",
        corporate_action_adjustment=CorporateActionAdjustment.UNADJUSTED,
        source_name="同花顺iFinD",
        grade=EvidenceGrade.A,
    ).model_dump(mode="json")


def build_datasets_and_items():
    items: list[dict] = []
    datasets: list[ChartDataset] = []

    def eids(prefix: str, n: int) -> list[str]:
        return [f"E-{prefix}-{i}" for i in range(1, n + 1)]

    # ---- line: time_series ----
    ids = eids("LINE", 4)
    for i, (pe, v) in enumerate([(date(2023, 12, 31), 4237.0), (date(2024, 12, 31), 4600.0),
                                  (date(2025, 12, 31), 5000.0), (date(2026, 6, 30), 2600.0)], 1):
        items.append(evidence(ids[i-1], "营业收入", v, period_end=pe))
    datasets.append(ChartDataset(
        dataset_id="DS-LINE", kind="time_series", metric_name="营业收入",
        unit="亿元", currency="CNY", evidence_ids=ids,
        points=[
            {"label": "2023", "value": 4237.0, "period_end": "2023-12-31", "evidence_id": ids[0]},
            {"label": "2024", "value": 4600.0, "period_end": "2024-12-31", "evidence_id": ids[1]},
            {"label": "2025", "value": 5000.0, "period_end": "2025-12-31", "evidence_id": ids[2]},
            {"label": "2026H1", "value": 2600.0, "period_end": "2026-06-30", "evidence_id": ids[3]},
        ],
    ))

    # ---- area: time_series (actual + forecast) ----
    ids = eids("AREA", 6)
    for i, (pe, v, kind) in enumerate([
        (date(2023, 12, 31), 722.0, "actual"), (date(2024, 12, 31), 780.0, "actual"),
        (date(2025, 12, 31), 850.0, "actual"), (date(2026, 12, 31), 920.0, "forecast"),
        (date(2027, 12, 31), 1000.0, "forecast"), (date(2028, 12, 31), 1080.0, "forecast")], 1):
        items.append(evidence(ids[i-1], "归母净利润", v, period_end=pe))
    datasets.append(ChartDataset(
        dataset_id="DS-AREA", kind="time_series", metric_name="归母净利润",
        unit="亿元", currency="CNY", evidence_ids=ids,
        points=[
            {"label": f"202{3+i}", "value": 722.0, "period_end": "2023-12-31", "value_kind": "actual", "evidence_id": ids[0]},
            {"label": f"202{4+i}", "value": 780.0, "period_end": "2024-12-31", "value_kind": "actual", "evidence_id": ids[1]},
            {"label": f"202{5+i}", "value": 850.0, "period_end": "2025-12-31", "value_kind": "actual", "evidence_id": ids[2]},
            {"label": f"202{6+i}", "value": 920.0, "period_end": "2026-12-31", "value_kind": "forecast", "evidence_id": ids[3]},
            {"label": f"202{7+i}", "value": 1000.0, "period_end": "2027-12-31", "value_kind": "forecast", "evidence_id": ids[4]},
            {"label": f"202{8+i}", "value": 1080.0, "period_end": "2028-12-31", "value_kind": "forecast", "evidence_id": ids[5]},
        ],
    ))

    # ---- combo: time_series dual axis ----
    ids = eids("COMBO", 8)
    for i, (pe, rev, eps) in enumerate([
        (date(2023, 12, 31), 4237.0, 6.8), (date(2024, 12, 31), 4600.0, 7.5),
        (date(2025, 12, 31), 5000.0, 8.2), (date(2026, 6, 30), 2600.0, 4.1)], 1):
        items.append(evidence(ids[(i-1)*2], "营业收入", rev, unit="亿元", period_end=pe))
        items.append(evidence(ids[(i-1)*2+1], "每股收益", eps, unit="元", period_end=pe))
    datasets.append(ChartDataset(
        dataset_id="DS-COMBO", kind="time_series", metric_name="营收与每股收益",
        unit="亿元", currency="CNY", business_linked=True, evidence_ids=ids,
        series_meta=[
            {"name": "营业收入", "unit": "亿元", "currency": "CNY", "render_as": "bar"},
            {"name": "每股收益", "unit": "元", "currency": "CNY", "render_as": "line"},
        ],
        points=[
            {"label": "2023", "value": 4237.0, "series": "营业收入", "period_end": "2023-12-31", "evidence_id": ids[0]},
            {"label": "2023", "value": 6.8, "series": "每股收益", "period_end": "2023-12-31", "evidence_id": ids[1]},
            {"label": "2024", "value": 4600.0, "series": "营业收入", "period_end": "2024-12-31", "evidence_id": ids[2]},
            {"label": "2024", "value": 7.5, "series": "每股收益", "period_end": "2024-12-31", "evidence_id": ids[3]},
            {"label": "2025", "value": 5000.0, "series": "营业收入", "period_end": "2025-12-31", "evidence_id": ids[4]},
            {"label": "2025", "value": 8.2, "series": "每股收益", "period_end": "2025-12-31", "evidence_id": ids[5]},
        ],
    ))

    # ---- bar: categorical ----
    ids = eids("BAR", 4)
    for i, (seg, v) in enumerate([("动力电池", 3000.0), ("储能系统", 800.0), ("电池材料", 300.0), ("其他", 137.0)], 1):
        items.append(evidence(ids[i-1], "分业务收入", v, period_end=date(2025, 12, 31)))
    datasets.append(ChartDataset(
        dataset_id="DS-BAR", kind="categorical", metric_name="分业务收入",
        unit="亿元", currency="CNY", evidence_ids=ids,
        points=[
            {"label": "动力电池", "value": 3000.0, "evidence_id": ids[0]},
            {"label": "储能系统", "value": 800.0, "evidence_id": ids[1]},
            {"label": "电池材料", "value": 300.0, "evidence_id": ids[2]},
            {"label": "其他", "value": 137.0, "evidence_id": ids[3]},
        ],
    ))

    # ---- pie: categorical composition ----
    ids = eids("PIE", 4)
    for i, (seg, v) in enumerate([("境内", 55.0), ("欧洲", 25.0), ("美国", 12.0), ("其他海外", 8.0)], 1):
        items.append(evidence(ids[i-1], "收入构成", v, unit="%", period_end=date(2025, 12, 31)))
    datasets.append(ChartDataset(
        dataset_id="DS-PIE", kind="categorical", metric_name="收入构成",
        unit="%", currency="CNY", is_composition=True, evidence_ids=ids,
        points=[
            {"label": "境内", "value": 55.0, "evidence_id": ids[0]},
            {"label": "欧洲", "value": 25.0, "evidence_id": ids[1]},
            {"label": "美国", "value": 12.0, "evidence_id": ids[2]},
            {"label": "其他海外", "value": 8.0, "evidence_id": ids[3]},
        ],
    ))

    # ---- radar: categorical standardized ----
    ids = eids("RADAR", 8)
    rows = [
        ("盈利能力", 85.0, 80.0), ("成长性", 90.0, 70.0), ("偿债能力", 75.0, 82.0),
        ("运营效率", 80.0, 78.0),
    ]
    k = 0
    for ind, a, b in rows:
        k += 1; items.append(evidence(ids[k-1], f"{ind}评分", a, unit="分", period_end=date(2025, 12, 31)))
        k += 1; items.append(evidence(ids[k-1], f"{ind}评分", b, unit="分", period_end=date(2025, 12, 31)))
    datasets.append(ChartDataset(
        dataset_id="DS-RADAR", kind="categorical", metric_name="竞争力评分",
        unit="分", currency="CNY", is_standardized=True, scale_min=0.0, scale_max=100.0,
        evidence_ids=ids,
        points=[
            {"label": "盈利能力", "value": 85.0, "series": "宁德时代", "evidence_id": ids[0]},
            {"label": "盈利能力", "value": 80.0, "series": "行业平均", "evidence_id": ids[1]},
            {"label": "成长性", "value": 90.0, "series": "宁德时代", "evidence_id": ids[2]},
            {"label": "成长性", "value": 70.0, "series": "行业平均", "evidence_id": ids[3]},
            {"label": "偿债能力", "value": 75.0, "series": "宁德时代", "evidence_id": ids[4]},
            {"label": "偿债能力", "value": 82.0, "series": "行业平均", "evidence_id": ids[5]},
            {"label": "运营效率", "value": 80.0, "series": "宁德时代", "evidence_id": ids[0]},
            {"label": "运营效率", "value": 78.0, "series": "行业平均", "evidence_id": ids[1]},
        ],
    ))

    # ---- scatter: xy ----
    ids = eids("SCAT", 5)
    for i, (e, x, y) in enumerate([("宁德时代", 3.2, 28.0), ("比亚迪", 2.1, 18.0), ("亿纬锂能", 1.5, 15.0),
                                     ("国轩高科", 0.9, 12.0), ("中创新航", 1.2, 14.0)], 1):
        items.append(evidence(ids[i-1], "市占率与ROE", y, unit="%", period_end=date(2025, 12, 31)))
    datasets.append(ChartDataset(
        dataset_id="DS-SCAT", kind="xy", metric_name="市占率与盈利定位",
        unit="%", currency="CNY", x_metric="市占率", x_unit="%", y_metric="ROE", y_unit="%",
        evidence_ids=ids,
        xy_points=[
            {"entity": "宁德时代", "x": 37.0, "y": 28.0, "evidence_ids": [ids[0]]},
            {"entity": "比亚迪", "x": 18.0, "y": 18.0, "evidence_ids": [ids[1]]},
            {"entity": "亿纬锂能", "x": 8.0, "y": 15.0, "evidence_ids": [ids[2]]},
            {"entity": "国轩高科", "x": 5.0, "y": 12.0, "evidence_ids": [ids[3]]},
            {"entity": "中创新航", "x": 7.0, "y": 14.0, "evidence_ids": [ids[4]]},
        ],
    ))

    # ---- bubble: xy with size ----
    ids = eids("BUB", 5)
    for i, (e, x, y, s) in enumerate([("宁德时代", 37.0, 28.0, 9000.0), ("比亚迪", 18.0, 18.0, 6000.0),
                                        ("亿纬锂能", 8.0, 15.0, 2000.0), ("国轩高科", 5.0, 12.0, 1500.0),
                                        ("中创新航", 7.0, 14.0, 1800.0)], 1):
        items.append(evidence(ids[i-1], "市占率", x, unit="%", period_end=date(2025, 12, 31)))
    datasets.append(ChartDataset(
        dataset_id="DS-BUB", kind="xy", metric_name="市场地位气泡",
        unit="%", currency="CNY", x_metric="市占率", x_unit="%", y_metric="ROE", y_unit="%",
        size_metric="市值", size_unit="亿元", evidence_ids=ids,
        xy_points=[
            {"entity": "宁德时代", "x": 37.0, "y": 28.0, "size": 9000.0, "evidence_ids": [ids[0]]},
            {"entity": "比亚迪", "x": 18.0, "y": 18.0, "size": 6000.0, "evidence_ids": [ids[1]]},
            {"entity": "亿纬锂能", "x": 8.0, "y": 15.0, "size": 2000.0, "evidence_ids": [ids[2]]},
            {"entity": "国轩高科", "x": 5.0, "y": 12.0, "size": 1500.0, "evidence_ids": [ids[3]]},
            {"entity": "中创新航", "x": 7.0, "y": 14.0, "size": 1800.0, "evidence_ids": [ids[4]]},
        ],
    ))

    # ---- heatmap: matrix ----
    ids = eids("HEAT", 20)
    rows_v = ["2021", "2022", "2023", "2024", "2025"]
    cols_v = ["营收", "净利", "ROE", "负债率"]
    k = 0
    matrix = [
        [1500, 180, 20, 55], [2800, 320, 22, 60], [3500, 420, 24, 58],
        [4600, 500, 26, 55], [5000, 550, 28, 52],
    ]
    for r_i, rv in enumerate(rows_v):
        for c_i, cv in enumerate(cols_v):
            k += 1
            items.append(evidence(ids[k-1], f"{rv}{cv}", matrix[r_i][c_i], unit="%", period_end=date(2025, 12, 31)))
    datasets.append(ChartDataset(
        dataset_id="DS-HEAT", kind="matrix", metric_name="财务指标矩阵",
        unit="%", currency="CNY", is_standardized=True, evidence_ids=ids,
        matrix_cells=[
            {"row": rv, "column": cv, "value": matrix[r_i][c_i], "evidence_id": ids[r_i*4+c_i]}
            for r_i, rv in enumerate(rows_v) for c_i, cv in enumerate(cols_v)
        ],
    ))

    # ---- boxplot: distribution ----
    ids = eids("BOX", 16)
    k = 0
    for g in ["宁德时代", "行业均值"]:
        for j in range(8):
            k += 1
            items.append(evidence(ids[k-1], "净利率分布", 15 + (3 if g == "宁德时代" else 0) + j * 0.5, unit="%", period_end=date(2025, 12, 31)))
    datasets.append(ChartDataset(
        dataset_id="DS-BOX", kind="distribution", metric_name="净利率分布",
        unit="%", currency="CNY", evidence_ids=ids,
        distribution_samples=[
            {"group": "宁德时代", "entity": f"标的{j}", "value": 15 + j * 0.5, "evidence_id": ids[j+1]}
            for j in range(8)
        ] + [
            {"group": "行业均值", "entity": f"标的{j}", "value": 12 + j * 0.5, "evidence_id": ids[j+8]}
            for j in range(8)
        ],
    ))

    # ---- treemap: hierarchy ----
    ids = eids("TREE", 5)
    items.append(evidence(ids[0], "营业总收入", 3200.0, unit="亿元", period_end=date(2025, 12, 31)))
    for i, (nd, v) in enumerate([("动力电池", 1800.0), ("储能", 900.0), ("材料", 300.0), ("回收", 200.0)], 1):
        items.append(evidence(ids[i], "业务板块收入", v, unit="亿元", period_end=date(2025, 12, 31)))
    datasets.append(ChartDataset(
        dataset_id="DS-TREE", kind="hierarchy", metric_name="业务板块构成",
        unit="亿元", currency="CNY", data_as_of=date(2025, 12, 31), evidence_ids=ids,
        hierarchy_nodes=[
            {"node_id": "root", "label": "宁德时代", "parent_id": None, "value": 3200.0, "evidence_ids": [ids[0]]},
            {"node_id": "b1", "label": "动力电池", "parent_id": "root", "value": 1800.0, "evidence_ids": [ids[1]]},
            {"node_id": "b2", "label": "储能", "parent_id": "root", "value": 900.0, "evidence_ids": [ids[2]]},
            {"node_id": "b3", "label": "材料", "parent_id": "root", "value": 300.0, "evidence_ids": [ids[3]]},
            {"node_id": "b4", "label": "回收", "parent_id": "root", "value": 200.0, "evidence_ids": [ids[4]]},
        ],
    ))

    # ---- industry_chain ----
    ids = eids("CHAIN", 6)
    for i, m in enumerate(["上游锂矿", "正负极材料", "电芯制造", "电池pack", "新能源整车", "回收利用"]):
        items.append(evidence(ids[i], m, 100.0 - i, unit="亿元", period_end=date(2025, 12, 31)))
    datasets.append(ChartDataset(
        dataset_id="DS-CHAIN", kind="industry_chain", metric_name="动力电池产业链",
        unit="亿元", currency="CNY", evidence_ids=ids,
        nodes=[
            {"node_id": "n1", "label": "上游锂矿", "stage": "upstream", "evidence_ids": [ids[0]]},
            {"node_id": "n2", "label": "正负极材料", "stage": "upstream", "evidence_ids": [ids[1]]},
            {"node_id": "n3", "label": "电芯制造", "stage": "midstream", "evidence_ids": [ids[2]]},
            {"node_id": "n4", "label": "电池pack", "stage": "midstream", "evidence_ids": [ids[3]]},
            {"node_id": "n5", "label": "新能源整车", "stage": "downstream", "evidence_ids": [ids[4]]},
            {"node_id": "n6", "label": "回收利用", "stage": "support", "evidence_ids": [ids[5]]},
        ],
        edges=[
            {"source": "n1", "target": "n2", "evidence_ids": [ids[0]]},
            {"source": "n2", "target": "n3", "evidence_ids": [ids[1]]},
            {"source": "n3", "target": "n4", "evidence_ids": [ids[2]]},
            {"source": "n4", "target": "n5", "evidence_ids": [ids[3]]},
            {"source": "n5", "target": "n6", "evidence_ids": [ids[4]]},
        ],
    ))

    return datasets, items


def build_candidates(datasets: list[ChartDataset]) -> list[dict]:
    type_map = {
        "DS-LINE": "line", "DS-AREA": "area", "DS-COMBO": "combo", "DS-BAR": "bar",
        "DS-PIE": "pie", "DS-RADAR": "radar", "DS-SCAT": "scatter", "DS-BUB": "bubble",
        "DS-HEAT": "heatmap", "DS-BOX": "boxplot", "DS-TREE": "treemap", "DS-CHAIN": "industry_chain",
    }
    purpose_map = {
        "line": "trend", "area": "trend", "combo": "trend", "bar": "comparison",
        "pie": "composition", "radar": "scoring", "scatter": "positioning", "bubble": "positioning",
        "heatmap": "comparison", "boxplot": "distribution", "treemap": "composition",
        "industry_chain": "relationship",
    }
    candidates = []
    for ds in datasets:
        ct = type_map[ds.dataset_id]
        candidates.append(ChartCandidate(
            title=f"{ds.metric_name}——{ct}可视化",
            chart_type=ct,
            evidence_ids=ds.evidence_ids,
            analysis_purpose=purpose_map[ct],
            insight_goal=f"基于数据集呈现{ds.metric_name}的{ct}形态",
            priority=80,
            chapter_hint="CH-02" if ct in {"line", "bar", "pie", "area", "combo"} else "CH-04",
            user_requested=True,
        ).model_dump(mode="json"))
    return candidates


def build_html(chart_specs: list[dict], suppressed: list[dict], quality: dict) -> str:
    cards = []
    for spec in chart_specs:
        option_json = json.dumps(spec["option"], ensure_ascii=False)
        var_name = "c_" + spec["chart_id"].replace("-", "_")
        cards.append(f"""
        <div class="card">
          <h3>{spec['title']}</h3>
          <div class="tag">{spec['chart_type']} / {spec['variant']}</div>
          <div class="ids">{spec['chart_id']}</div>
          <div id="{spec['chart_id']}" class="chart"></div>
          <script>
            var {var_name} = echarts.init(document.getElementById('{spec['chart_id']}'));
            {var_name}.setOption({option_json});
          </script>
        </div>""")

    supp_cards = "".join(
        f'<div class="supp"><b>{s["title"]}</b> — {s["reason_code"]}: {s["reason"]}</div>'
        for s in suppressed
    ) or "<div class='supp'>无抑制图表</div>"

    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>智能体3独立测试——图表生成报告</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
<style>
  body {{ font-family: -apple-system, "PingFang SC", sans-serif; margin: 24px; background: #f5f7fa; color: #1f2937; }}
  h1 {{ color: #1e3a5f; }}
  h2 {{ margin-top: 32px; color: #2563eb; }}
  .summary {{ background: #fff; padding: 16px 20px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,.1); }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(480px, 1fr)); gap: 20px; margin-top: 16px; }}
  .card {{ background: #fff; border-radius: 8px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,.1); }}
  .card h3 {{ margin: 0 0 6px; }}
  .tag {{ display: inline-block; background: #e0e7ff; color: #3730a3; padding: 2px 10px; border-radius: 12px; font-size: 12px; }}
  .ids {{ color: #6b7280; font-size: 11px; margin-top: 4px; }}
  .chart {{ width: 100%; height: 360px; }}
  .supp {{ background: #fff7ed; color: #9a3412; padding: 8px 12px; border-radius: 6px; margin: 6px 0; font-size: 13px; }}
  .issues {{ color: #b91c1c; }}
</style>
</head>
<body>
<h1>智能体3独立测试 —— 图表生成</h1>
<div class="summary">
  <p><b>质量门:</b> {'✅ 通过' if quality.get('passed') else '❌ 未通过'}</p>
  <p><b>成功图表:</b> {quality.get('ready_count')} | <b>抑制候选:</b> {quality.get('suppressed_count')}</p>
  <p class="issues"><b>问题:</b> {'; '.join(quality.get('issues', [])) or '无'}</p>
</div>
<h2>抑制/降级详情</h2>
{supp_cards}
<h2>生成的图表（共{len(chart_specs)}张）</h2>
<div class="grid">
{''.join(cards)}
</div>
</body>
</html>"""


async def main():
    datasets, items = build_datasets_and_items()
    candidates = build_candidates(datasets)

    input_data = {
        "industry_topic": "新能源动力电池",
        "market_scope": ["中国"],
        "security_types": ["A股"],
        "research_as_of": "2026-08-12",
        "focus_questions": ["宁德时代核心财务与市场地位？"],
        "evidence_items": items,
        "chart_datasets": [ds.model_dump(mode="json") for ds in datasets],
        "chart_generate_options": {
            "requested_chart_count": len(datasets),
            "requested_chart_types": [c["chart_type"] for c in candidates],
            "user_priority": True,
        },
    }

    interpret_data = {"chart_candidates": candidates, "data_quality_issues": []}
    interpret_result = StageResult(
        stage=StageName.DATA_INTERPRET,
        status=StageStatus.COMPLETED,
        revision=1,
        data=interpret_data,
    )

    context = StageContext(
        owner_id="test",
        project_id="agent3-standalone",
        run_id="agent3-standalone-test",
        revision=1,
        input_data=input_data,
        previous_results={StageName.DATA_INTERPRET: interpret_result},
    )

    from app.agents.chart_generator.service import ChartGeneratorAgent
    agent = ChartGeneratorAgent()
    result = await agent.run(context)

    print(f"状态: {result.status}")
    print(f"错误: {result.error or '无'}")
    data = result.data
    chart_specs = data.get("chart_specs", [])
    suppressed = data.get("suppressed_candidates", [])
    quality = data.get("quality", {})
    print(f"质量门: passed={quality.get('passed')}, ready={quality.get('ready_count')}, suppressed={quality.get('suppressed_count')}")
    print(f"生成图表类型: {[s['chart_type'] for s in chart_specs]}")
    generated_types = {s["chart_type"] for s in chart_specs}
    all_types = {"line", "bar", "pie", "radar", "industry_chain", "combo", "area",
                 "scatter", "bubble", "heatmap", "boxplot", "treemap"}
    print(f"覆盖类型: {len(generated_types)}/{len(all_types)}")
    print(f"缺失类型: {sorted(all_types - generated_types) or '无'}")
    if suppressed:
        print(f"\n抑制详情:")
        for s in suppressed:
            print(f"  - {s['title']}: [{s['reason_code']}] {s['reason']}")

    out_dir = Path(__file__).parent / "test_output" / "agent3_standalone"
    out_dir.mkdir(parents=True, exist_ok=True)
    html = build_html(chart_specs, suppressed, quality)
    (out_dir / "agent3_report.html").write_text(html, encoding="utf-8")
    (out_dir / "agent3_result.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nHTML产物: {out_dir / 'agent3_report.html'}")


if __name__ == "__main__":
    asyncio.run(main())