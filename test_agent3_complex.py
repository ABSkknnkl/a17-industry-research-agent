"""智能体3独立测试——12个最复杂问题 × 12种图表类型，一对一生成。

模拟真实金融研究员复杂查询的定量证据，调用 ChartGeneratorAgent.run()，
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


# ============================================================
# 工具函数
# ============================================================

def ev(eid, metric, value=None, unit="亿元", period_end=None):
    return EvidenceItem(
        evidence_id=eid, metric_name=metric, value=value, unit=unit,
        period_end=period_end, audit_status=AuditStatus.AUDITED,
        restatement_status=RestatementStatus.NOT_RESTATED, scope="中国",
        market="中国", exchange="深圳证券交易所", security_type="A股",
        currency="CNY", accounting_standard="CAS",
        corporate_action_adjustment=CorporateActionAdjustment.UNADJUSTED,
        source_name="同花顺iFinD", grade=EvidenceGrade.A,
    ).model_dump(mode="json")

def eids(prefix, n):
    return [f"E-{prefix}-{i}" for i in range(1, n + 1)]

def cand(ds_id, title, ct, purpose, **kw):
    return ChartCandidate(
        title=title, chart_type=ct, evidence_ids=["E-DUMMY"], analysis_purpose=purpose,
        insight_goal=title, priority=80, chapter_hint="CH-02", user_requested=True, **kw
    ).model_dump(mode="json")


# ============================================================
# Q1: 锂钴镍近三年价格走势 → line
# ============================================================
def q1_price_trend():
    ids = eids("Q1", 24)
    items = []
    metals = [("碳酸锂", [50, 25, 15, 10, 12, 11, 20, 18, 14, 9, 8, 10]),
              ("钴",     [35, 30, 28, 22, 20, 18, 25, 24, 22, 19, 17, 16])]
    month_dates = [date(2025,8,1), date(2025,10,1), date(2025,12,1), date(2026,2,1),
                   date(2026,3,1), date(2026,4,1), date(2026,5,1), date(2026,6,1),
                   date(2026,7,1), date(2026,8,1), date(2026,9,1), date(2026,10,1)]
    months = ["2025-08","2025-10","2025-12","2026-02","2026-03","2026-04",
              "2026-05","2026-06","2026-07","2026-08","2026-09","2026-10"]
    k = 0
    pts = []
    for metal, vals in metals:
        for m, v, pd in zip(months, vals, month_dates):
            k += 1
            items.append(ev(ids[k-1], f"{metal}价格", v, unit="万元/吨", period_end=pd))
            pts.append({"label": m, "value": v, "series": metal, "period_end": pd.isoformat(), "evidence_id": ids[k-1]})
    ds = ChartDataset(
        dataset_id="DS-Q1", kind="time_series", metric_name="碳酸锂与钴价格走势",
        unit="万元/吨", currency="CNY", evidence_ids=ids,
        series_meta=[{"name": "碳酸锂", "unit": "万元/吨", "render_as": "line"}, {"name": "钴", "unit": "万元/吨", "render_as": "line"}],
        points=pts,
    )
    return ds, items, cand("DS-Q1", "碳酸锂、钴近一年价格走势（line）", "line", "trend")


# ============================================================
# Q2: 光伏产业链各环节盈利对比 → bar
# ============================================================
def q2_pv_profit():
    ids = eids("Q2", 8)
    items = []
    stages = ["硅料", "硅片", "电池片", "组件"]
    gross_2024 = [18.5, 8.2, 5.1, 3.8]
    gross_2025 = [12.3, 6.0, 3.5, 2.1]
    k = 0
    pts = []
    for i, s in enumerate(stages):
        k += 1; items.append(ev(ids[k-1], "毛利率", gross_2024[i], unit="%", period_end=date(2024,12,31)))
        pts.append({"label": s, "value": gross_2024[i], "series": "2024", "evidence_id": ids[k-1]})
        k += 1; items.append(ev(ids[k-1], "毛利率", gross_2025[i], unit="%", period_end=date(2025,12,31)))
        pts.append({"label": s, "value": gross_2025[i], "series": "2025", "evidence_id": ids[k-1]})
    ds = ChartDataset(
        dataset_id="DS-Q2", kind="categorical", metric_name="光伏各环节毛利率",
        unit="%", currency="CNY", evidence_ids=ids,
        series_meta=[{"name":"2024毛利率","unit":"%","render_as":"bar"},{"name":"2025毛利率","unit":"%","render_as":"bar"}],
        points=pts,
    )
    return ds, items, cand("DS-Q2", "光伏产业链各环节毛利率对比（bar）", "bar", "comparison")


# ============================================================
# Q3: 锂电池行业CR3/CR5市场占有率 → pie
# ============================================================
def q3_market_share():
    ids = eids("Q3", 5)
    items = []
    firms = [("宁德时代", 37.5), ("比亚迪", 18.2), ("中创新航", 8.1), ("亿纬锂能", 5.6), ("其他", 30.6)]
    pts = []
    for i, (f, v) in enumerate(firms):
        items.append(ev(ids[i], "市占率", v, unit="%", period_end=date(2025,12,31)))
        pts.append({"label": f, "value": v, "evidence_id": ids[i]})
    ds = ChartDataset(
        dataset_id="DS-Q3", kind="categorical", metric_name="锂电池市占率",
        unit="%", currency="CNY", is_composition=True, evidence_ids=ids, points=pts,
    )
    return ds, items, cand("DS-Q3", "锂电池行业CR5市场占有率（pie）", "pie", "composition")


# ============================================================
# Q4: 宁德时代 vs 亿纬锂能储能业务多维度对比 → radar
# ============================================================
def q4_radar_compare():
    ids = eids("Q4", 12)
    items = []
    dims = ["储能出货量", "海外收入占比", "单瓦毛利", "在手订单", "技术专利数", "客户覆盖深度"]
    catl = [85, 30, 82, 90, 95, 88]
    eve  = [45, 42, 68, 65, 40, 55]
    k = 0
    pts = []
    for i, d in enumerate(dims):
        k += 1; items.append(ev(ids[k-1], f"{d}评分", catl[i], unit="分", period_end=date(2025,12,31)))
        pts.append({"label": d, "value": catl[i], "series": "宁德时代", "evidence_id": ids[k-1]})
        k += 1; items.append(ev(ids[k-1], f"{d}评分", eve[i], unit="分", period_end=date(2025,12,31)))
        pts.append({"label": d, "value": eve[i], "series": "亿纬锂能", "evidence_id": ids[k-1]})
    ds = ChartDataset(
        dataset_id="DS-Q4", kind="categorical", metric_name="储能业务竞争力",
        unit="分", currency="CNY", is_standardized=True, scale_min=0, scale_max=100,
        evidence_ids=ids, points=pts,
    )
    return ds, items, cand("DS-Q4", "宁德时代vs亿纬锂能储能业务六维雷达图（radar）", "radar", "scoring")


# ============================================================
# Q5: 锂电池全产业链供需结构 → industry_chain
# ============================================================
def q5_industry_chain():
    ids = eids("Q5", 10)
    items = []
    chain_nodes = [
        ("锂矿开采", "upstream"), ("正极材料", "upstream"), ("负极材料", "upstream"),
        ("电解液", "upstream"), ("隔膜", "upstream"), ("电芯制造", "midstream"),
        ("电池Pack", "midstream"), ("新能源整车", "downstream"),
        ("储能系统", "downstream"), ("电池回收", "support"),
    ]
    for i, (lbl, _) in enumerate(chain_nodes):
        items.append(ev(ids[i], lbl, float(100-i*5), unit="亿元", period_end=date(2025,12,31)))
    ds = ChartDataset(
        dataset_id="DS-Q5", kind="industry_chain", metric_name="锂电池全产业链",
        unit="亿元", currency="CNY", evidence_ids=ids,
        nodes=[{"node_id": f"n{i+1}", "label": lbl, "stage": st, "evidence_ids": [ids[i]]}
               for i, (lbl, st) in enumerate(chain_nodes)],
        edges=[
            {"source":"n1","target":"n2","evidence_ids":[ids[0]]},
            {"source":"n1","target":"n3","evidence_ids":[ids[1]]},
            {"source":"n2","target":"n6","evidence_ids":[ids[2]]},
            {"source":"n3","target":"n6","evidence_ids":[ids[3]]},
            {"source":"n4","target":"n6","evidence_ids":[ids[4]]},
            {"source":"n5","target":"n6","evidence_ids":[ids[5]]},
            {"source":"n6","target":"n7","evidence_ids":[ids[6]]},
            {"source":"n7","target":"n8","evidence_ids":[ids[7]]},
            {"source":"n7","target":"n9","evidence_ids":[ids[8]]},
            {"source":"n8","target":"n10","evidence_ids":[ids[9]]},
            {"source":"n9","target":"n10","evidence_ids":[ids[9]]},
        ],
    )
    return ds, items, cand("DS-Q5", "锂电池全产业链供需结构（industry_chain）", "industry_chain", "relationship")


# ============================================================
# Q6: 新能源车头部企业营收+毛利率双轴 → combo
# ============================================================
def q6_combo():
    ids = eids("Q6", 8)
    items = []
    rev = [4237, 4600, 5000, 2600]
    gm  = [22.5, 24.0, 25.5, 26.0]
    periods = ["2023", "2024", "2025", "2026H1"]
    period_dates = [date(2023,12,31), date(2024,12,31), date(2025,12,31), date(2026,6,30)]
    k = 0
    pts = []
    for p, rv, gv, pd in zip(periods, rev, gm, period_dates):
        k += 1; items.append(ev(ids[k-1], "营业收入", rv, unit="亿元", period_end=pd))
        pts.append({"label": p, "value": rv, "series": "营收", "period_end": pd.isoformat(), "evidence_id": ids[k-1]})
        k += 1; items.append(ev(ids[k-1], "毛利率", gv, unit="%", period_end=pd))
        pts.append({"label": p, "value": gv, "series": "毛利率", "period_end": pd.isoformat(), "evidence_id": ids[k-1]})
    ds = ChartDataset(
        dataset_id="DS-Q6", kind="time_series", metric_name="宁德时代营收与毛利率",
        unit="亿元", currency="CNY", business_linked=True, evidence_ids=ids,
        series_meta=[
            {"name":"营收","unit":"亿元","render_as":"bar"},
            {"name":"毛利率","unit":"%","render_as":"line"},
        ],
        points=pts,
    )
    return ds, items, cand("DS-Q6", "宁德时代营收+毛利率双轴趋势（combo）", "combo", "trend")


# ============================================================
# Q7: 光伏周期复盘：产能过剩阶段价格跌幅（历史+预测） → area
# ============================================================
def q7_area():
    ids = eids("Q7", 10)
    items = []
    prices = [("2021H2", 220, "actual"), ("2022H1", 260, "actual"), ("2022H2", 300, "actual"),
              ("2023H1", 180, "actual"), ("2023H2", 90, "actual"), ("2024H1", 55, "actual"),
              ("2024H2", 45, "actual"), ("2025H1", 40, "actual"),
              ("2025H2", 38, "forecast"), ("2026H1", 35, "forecast")]
    period_dates = [date(2021,6,30), date(2022,6,30), date(2022,12,31), date(2023,6,30),
                    date(2023,12,31), date(2024,6,30), date(2024,12,31), date(2025,6,30),
                    date(2025,12,31), date(2026,6,30)]
    k = 0
    pts = []
    for (lbl, v, kind), pd in zip(prices, period_dates):
        k += 1
        items.append(ev(ids[k-1], "硅料价格", v, unit="元/kg", period_end=pd))
        pts.append({"label": lbl, "value": v, "value_kind": kind, "period_end": pd.isoformat(), "evidence_id": ids[k-1]})
    ds = ChartDataset(
        dataset_id="DS-Q7", kind="time_series", metric_name="硅料价格周期",
        unit="元/kg", currency="CNY", evidence_ids=ids, points=pts,
    )
    return ds, items, cand("DS-Q7", "光伏周期复盘：硅料价格历史与预测区间（area）", "area", "trend")


# ============================================================
# Q8: 碳酸锂供需平衡：不同需求情景下均衡价格 → scatter
# ============================================================
def q8_scatter():
    ids = eids("Q8", 8)
    items = []
    scenarios = [
        ("乐观-2030", 180, 14), ("基准-2030", 140, 10), ("悲观-2030", 100, 7),
        ("乐观-2028", 150, 16), ("基准-2028", 120, 12), ("悲观-2028", 90, 8),
        ("乐观-2026", 120, 18), ("基准-2026", 100, 14),
    ]
    k = 0
    pts = []
    for lbl, supply, price in scenarios:
        k += 1
        items.append(ev(ids[k-1], "碳酸锂均衡价格", price, unit="万元/吨", period_end=date(2030,12,31)))
        pts.append({"entity": lbl, "x": supply, "y": price, "evidence_ids": [ids[k-1]]})
    ds = ChartDataset(
        dataset_id="DS-Q8", kind="xy", metric_name="碳酸锂供需情景",
        unit="万元/吨", currency="CNY", x_metric="供给量(万吨LCE)", x_unit="万吨",
        y_metric="均衡价格", y_unit="万元/吨", evidence_ids=ids, xy_points=pts,
    )
    return ds, items, cand("DS-Q8", "碳酸锂供需平衡：不同情景下均衡价格定位（scatter）", "scatter", "positioning")


# ============================================================
# Q9: 人形机器人产业链价值拆分（市占率×技术壁垒×市值） → bubble
# ============================================================
def q9_bubble():
    ids = eids("Q9", 6)
    items = []
    firms = [("汇川技术", 25, 88, 2200), ("绿的谐波", 12, 92, 350),
             ("拓斯达", 8, 70, 180), ("埃斯顿", 10, 65, 200),
             ("禾川科技", 5, 55, 80), ("步科股份", 3, 45, 45)]
    k = 0
    pts = []
    for fn, share, barrier, mcap in firms:
        k += 1
        items.append(ev(ids[k-1], "市占率", share, unit="%", period_end=date(2025,12,31)))
        pts.append({"entity": fn, "x": share, "y": barrier, "size": mcap, "evidence_ids": [ids[k-1]]})
    ds = ChartDataset(
        dataset_id="DS-Q9", kind="xy", metric_name="人形机器人零部件竞争",
        unit="分", currency="CNY", x_metric="市占率", x_unit="%",
        y_metric="技术壁垒", y_unit="分", size_metric="市值", size_unit="亿元",
        evidence_ids=ids, xy_points=pts,
    )
    return ds, items, cand("DS-Q9", "人形机器人产业链价值气泡图（bubble）", "bubble", "positioning")


# ============================================================
# Q10: 利率下行对四大成长板块估值影响 → heatmap
# ============================================================
def q10_heatmap():
    ids = eids("Q10", 25)
    items = []
    sectors = ["白酒", "创新药", "光伏储能", "高端制造", "半导体"]
    rates = ["5年期LPR 3.5%", "LPR 3.0%", "LPR 2.5%", "LPR 2.0%", "LPR 1.5%"]
    matrix = [
        [0.8, 0.5, 0.2, -0.3, -0.5],
        [1.5, 1.2, 0.8, 0.5, 0.3],
        [1.2, 0.9, 0.6, 0.3, 0.0],
        [1.0, 0.7, 0.4, 0.1, -0.2],
        [1.8, 1.4, 1.0, 0.6, 0.4],
    ]
    k = 0
    cells = []
    for r_i, sec in enumerate(sectors):
        for c_i, rate in enumerate(rates):
            k += 1
            items.append(ev(ids[k-1], "估值弹性", matrix[r_i][c_i], unit="倍", period_end=date(2025,12,31)))
            cells.append({"row": sec, "column": rate, "value": matrix[r_i][c_i], "evidence_id": ids[k-1]})
    ds = ChartDataset(
        dataset_id="DS-Q10", kind="matrix", metric_name="利率下行估值弹性",
        unit="倍", currency="CNY", is_standardized=True, evidence_ids=ids[:25],
        matrix_cells=cells,
    )
    return ds, items, cand("DS-Q10", "利率下行对四大板块估值弹性热力图（heatmap）", "heatmap", "comparison")


# ============================================================
# Q11: 储能上市公司储能业务净利率分布 → boxplot
# ============================================================
def q11_boxplot():
    ids = eids("Q11", 24)
    items = []
    groups = {
        "电网侧": [12.5, 14.0, 15.5, 16.0, 13.0, 11.0, 10.5, 13.5],
        "用户侧": [8.0, 9.5, 10.0, 11.0, 7.5, 6.0, 8.5, 9.0],
        "海外储能": [18.0, 20.0, 22.0, 19.0, 17.5, 21.0, 23.0, 20.5],
    }
    k = 0
    pts = []
    for g, vals in groups.items():
        for j, v in enumerate(vals):
            k += 1
            items.append(ev(ids[k-1], "储能净利率", v, unit="%", period_end=date(2025,12,31)))
            pts.append({"group": g, "entity": f"公司{j+1}", "value": v, "evidence_id": ids[k-1]})
    ds = ChartDataset(
        dataset_id="DS-Q11", kind="distribution", metric_name="储能业务净利率",
        unit="%", currency="CNY", evidence_ids=ids[:24], distribution_samples=pts,
    )
    return ds, items, cand("DS-Q11", "储能上市公司分类型净利率分布箱线图（boxplot）", "boxplot", "distribution")


# ============================================================
# Q12: 储能产业链价值拆分（层级节点） → treemap
# ============================================================
def q12_treemap():
    ids = eids("Q12", 9)
    items = []
    items.append(ev(ids[0], "储能产业链总值", 8500, unit="亿元", period_end=date(2025,12,31)))
    items.append(ev(ids[1], "电池系统", 4500, unit="亿元", period_end=date(2025,12,31)))
    items.append(ev(ids[2], "PCS变流器", 1200, unit="亿元", period_end=date(2025,12,31)))
    items.append(ev(ids[3], "BMS/EMS", 800, unit="亿元", period_end=date(2025,12,31)))
    items.append(ev(ids[4], "系统集成", 1500, unit="亿元", period_end=date(2025,12,31)))
    items.append(ev(ids[5], "温控消防", 500, unit="亿元", period_end=date(2025,12,31)))
    items.append(ev(ids[6], "电芯", 2500, unit="亿元", period_end=date(2025,12,31)))
    items.append(ev(ids[7], "Pack", 2000, unit="亿元", period_end=date(2025,12,31)))
    items.append(ev(ids[8], "逆变器", 1200, unit="亿元", period_end=date(2025,12,31)))
    ds = ChartDataset(
        dataset_id="DS-Q12", kind="hierarchy", metric_name="储能产业链价值",
        unit="亿元", currency="CNY", data_as_of=date(2025,12,31), evidence_ids=ids,
        hierarchy_nodes=[
            {"node_id":"root","label":"储能产业链","parent_id":None,"value":8500,"evidence_ids":[ids[0]]},
            {"node_id":"battery","label":"电池系统","parent_id":"root","value":4500,"evidence_ids":[ids[1]]},
            {"node_id":"pcs","label":"PCS变流器","parent_id":"root","value":1200,"evidence_ids":[ids[2]]},
            {"node_id":"bms","label":"BMS/EMS","parent_id":"root","value":800,"evidence_ids":[ids[3]]},
            {"node_id":"integration","label":"系统集成","parent_id":"root","value":1500,"evidence_ids":[ids[4]]},
            {"node_id":"thermal","label":"温控消防","parent_id":"root","value":500,"evidence_ids":[ids[5]]},
            {"node_id":"cell","label":"电芯","parent_id":"battery","value":2500,"evidence_ids":[ids[6]]},
            {"node_id":"pack","label":"Pack","parent_id":"battery","value":2000,"evidence_ids":[ids[7]]},
            {"node_id":"inverter","label":"逆变器","parent_id":"pcs","value":1200,"evidence_ids":[ids[8]]},
        ],
    )
    return ds, items, cand("DS-Q12", "储能产业链价值拆分矩形树图（treemap）", "treemap", "composition")


# ============================================================
# 组装并运行
# ============================================================

QUESTIONS = [
    ("Q1",  "锂、钴、镍近一年价格走势", q1_price_trend),
    ("Q2",  "光伏产业链各环节盈利对比",  q2_pv_profit),
    ("Q3",  "锂电池行业CR5市场占有率",   q3_market_share),
    ("Q4",  "宁德时代vs亿纬锂能储能六维雷达", q4_radar_compare),
    ("Q5",  "锂电池全产业链供需结构",   q5_industry_chain),
    ("Q6",  "新能源车头部企业营收+毛利率双轴", q6_combo),
    ("Q7",  "光伏周期复盘：硅料价格与预测",  q7_area),
    ("Q8",  "碳酸锂供需平衡情景定位",    q8_scatter),
    ("Q9",  "人形机器人产业链价值气泡",  q9_bubble),
    ("Q10", "利率下行对四大板块估值热力图",  q10_heatmap),
    ("Q11", "储能上市公司净利率分布箱线图",  q11_boxplot),
    ("Q12", "储能产业链价值拆分矩形树图",  q12_treemap),
]

# 将12张图表分布到两个章节，避免单章硬上限10张
CHAPTER_HINTS = {
    "Q1": "CH-02", "Q2": "CH-02", "Q3": "CH-02", "Q4": "CH-02", "Q5": "CH-02", "Q6": "CH-02",
    "Q7": "CH-03", "Q8": "CH-03", "Q9": "CH-03", "Q10": "CH-03", "Q11": "CH-03", "Q12": "CH-03",
}


def build_html(chart_specs, suppressed, quality, question_map):
    # 按问题映射标题
    cards = []
    for spec in chart_specs:
        option_json = json.dumps(spec["option"], ensure_ascii=False)
        var_name = "c_" + spec["chart_id"].replace("-", "_")
        q_label = question_map.get(spec["chart_id"], spec["title"])
        cards.append(f"""
        <div class="card">
          <div class="q-label">{q_label}</div>
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
        f'<div class="supp"><b>{s["title"]}</b> — [{s["reason_code"]}] {s["reason"]}</div>'
        for s in suppressed
    ) or "<div class='supp'>无抑制图表</div>"

    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>智能体3复杂问题测试——12张图表</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
<style>
  body {{ font-family: -apple-system, "PingFang SC", sans-serif; margin: 24px; background: #f0f2f5; color: #1f2937; }}
  h1 {{ color: #1e3a5f; }}
  h2 {{ margin-top: 32px; color: #2563eb; }}
  .summary {{ background: #fff; padding: 16px 20px; border-radius: 10px; box-shadow: 0 1px 4px rgba(0,0,0,.08); margin-bottom: 20px; }}
  .summary p {{ margin: 4px 0; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(520px, 1fr)); gap: 20px; margin-top: 16px; }}
  .card {{ background: #fff; border-radius: 10px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,.06); }}
  .q-label {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: #fff; display: inline-block; padding: 3px 14px; border-radius: 14px; font-size: 12px; font-weight: 600; margin-bottom: 8px; }}
  .card h3 {{ margin: 4px 0 6px; font-size: 15px; }}
  .tag {{ display: inline-block; background: #e0e7ff; color: #3730a3; padding: 2px 10px; border-radius: 12px; font-size: 12px; }}
  .ids {{ color: #9ca3af; font-size: 11px; margin-top: 4px; }}
  .chart {{ width: 100%; height: 380px; }}
  .supp {{ background: #fff7ed; color: #9a3412; padding: 8px 14px; border-radius: 8px; margin: 6px 0; font-size: 13px; }}
  .issues {{ color: #b91c1c; }}
</style>
</head>
<body>
<h1>智能体3独立测试 —— 12个复杂问题 × 12种图表类型</h1>
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
    all_items = []
    all_datasets = []
    all_candidates = []
    q_map = {}

    for qid, qlabel, factory in QUESTIONS:
        ds, items, candidate = factory()
        all_items.extend(items)
        all_datasets.append(ds)
        candidate["evidence_ids"] = ds.evidence_ids
        candidate["chapter_hint"] = CHAPTER_HINTS[qid]
        all_candidates.append(candidate)
        q_map[ds.dataset_id] = qlabel

    input_data = {
        "industry_topic": "新能源与高端制造",
        "market_scope": ["中国"],
        "security_types": ["A股"],
        "research_as_of": "2026-08-12",
        "focus_questions": ["各维度综合分析"],
        "evidence_items": all_items,
        "chart_datasets": [ds.model_dump(mode="json") for ds in all_datasets],
        "chart_generate_options": {
            "requested_chart_count": len(all_datasets),
            "requested_chart_types": [c["chart_type"] for c in all_candidates],
            "user_priority": True,
        },
    }

    interpret_result = StageResult(
        stage=StageName.DATA_INTERPRET, status=StageStatus.COMPLETED,
        revision=1, data={"chart_candidates": all_candidates, "data_quality_issues": []},
    )

    context = StageContext(
        owner_id="test", project_id="agent3-complex", run_id="agent3-complex-test",
        revision=1, input_data=input_data,
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
    print(f"生成图表: {len(chart_specs)}/12")
    generated_types = {s["chart_type"] for s in chart_specs}
    all_types = {"line","bar","pie","radar","industry_chain","combo","area","scatter","bubble","heatmap","boxplot","treemap"}
    missing = sorted(all_types - generated_types)
    print(f"缺失类型: {missing or '无'}")
    if suppressed:
        print(f"\n抑制详情:")
        for s in suppressed:
            print(f"  - {s['title']}: [{s['reason_code']}] {s['reason']}")

    out_dir = Path(__file__).parent / "test_output" / "agent3_complex"
    out_dir.mkdir(parents=True, exist_ok=True)
    html = build_html(chart_specs, suppressed, quality, q_map)
    (out_dir / "agent3_complex_report.html").write_text(html, encoding="utf-8")
    (out_dir / "agent3_complex_result.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nHTML产物: {out_dir / 'agent3_complex_report.html'}")


if __name__ == "__main__":
    asyncio.run(main())