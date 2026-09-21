#!/usr/bin/env python3
"""小米手机产业链图谱（只构图，不写提示词 —— 提示词交给项目 LLM 编译）。

数据来自 2026-09-20 的公开检索（来源见 SOURCES），**不是 Agent1 取证链的 E-xxx**，
因此 evidence_ids 用 `E-WEB-xx` 标记，交付物会明确标注为「公开资料整理 · 演示」。
事实口径：只写来源里出现过的节点与企业名，不补来源未提及的公司，不写任何数字指标
（份额/出货量一律不进图谱，避免触发 Agent3「禁止虚构数字」的红线）。

产出：output/industry-chain-images/xiaomi-phone.graph.json（+ runtime.json）
然后：
    .venv/bin/python scripts/compile_chain_prompt_live.py --graph .../xiaomi-phone.graph.json --slug xiaomi-phone
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agents.chart_generator.industry_chain import (  # noqa: E402
    build_prompt_runtime_payload,
    build_verified_chain_graph,
    select_chain_template,
)
from app.schemas.chart import ChainEdge, ChainNode, ChartDataset  # noqa: E402

CWD = Path(__file__).resolve().parents[2]
OUT = CWD / "output" / "industry-chain-images"

# 公开来源（供人工核对；生成提示词时不会把 URL 写进画面）
SOURCES = {
    "E-WEB-01": "小米集团 2026 年第一季度业绩公告（港交所披露，2026-05-26）：中国大陆小米之家门店数、海外新零售门店、AIoT 连接设备数、智能手机 ASP",
    "E-WEB-02": "Omdia 2026 年第二季度智能手机出货数据（第三方报道转载）：全球出货与份额、各区域排名与份额",
    "E-WEB-03": "小米手机产业链分层梳理（官方披露与公开拆机资料汇编）：上游材料/芯片/显示/影像/电池、中游结构件与代工、下游渠道",
    "E-WEB-04": "小米手机各部件供应商汇编（企业信息平台公开词条）：芯片、屏幕、影像、电池、组装等环节供应商名单",
    "E-WEB-05": "小米合作商与生态链梳理（公开汇编）：核心供应商、代工厂、生态链企业分类",
}


def n(nid, label, stage, companies, ev, kind="component", core=False):
    return ChainNode(
        node_id=nid,
        label=label,
        stage=stage,
        node_kind=kind,
        companies=companies,
        logo_names=[],
        is_core=core,
        evidence_ids=ev,
    )


UP, MID, DOWN, SUP = "upstream", "midstream", "downstream", "support"

nodes = [
    # ---- 上游供给 ----
    n("U1", "主芯片与移动平台", UP, ["高通", "联发科", "小米玄戒"], ["E-WEB-03", "E-WEB-04"], kind="component"),
    n("U2", "存储与内存", UP, ["SK海力士", "美光", "三星", "长鑫存储"], ["E-WEB-03", "E-WEB-04"], kind="component"),
    n("U3", "显示面板", UP, ["TCL华星", "京东方", "深天马", "维信诺"], ["E-WEB-03", "E-WEB-04"], kind="component"),
    n("U4", "影像传感器与镜头", UP, ["索尼", "豪威", "思特威", "舜宇光学", "欧菲光", "徕卡"], ["E-WEB-03", "E-WEB-04"], kind="component"),
    n("U5", "电池与电源管理", UP, ["宁德时代", "比亚迪弗迪", "欣旺达", "德赛电池", "南芯科技"], ["E-WEB-03", "E-WEB-04"], kind="component"),
    n("U6", "玻璃盖板与外观件", UP, ["蓝思科技", "伯恩光学"], ["E-WEB-03", "E-WEB-04"], kind="material"),
    n("U7", "精密结构件与散热", UP, ["领益智造", "长盈精密", "中石科技"], ["E-WEB-03", "E-WEB-04"], kind="material"),
    n("U8", "PCB、声学与射频器件", UP, ["深南电路", "东山精密", "歌尔股份", "瑞声科技", "卓胜微", "汇顶"], ["E-WEB-03", "E-WEB-04"], kind="component"),
    # ---- 中游制造与集成 ----
    n("M1", "小米智能手机整机（设计与品牌）", MID, ["小米"], ["E-WEB-01", "E-WEB-03"], kind="manufacturing", core=True),
    n("M2", "ODM 整机设计代工", MID, ["华勤技术", "龙旗科技", "闻泰科技"], ["E-WEB-03"], kind="manufacturing"),
    n("M3", "EMS 整机组装", MID, ["比亚迪电子", "富士康", "英华达"], ["E-WEB-03", "E-WEB-05"], kind="manufacturing"),
    n("M4", "小米自有智能制造基地", MID, ["北京小米智能工厂"], ["E-WEB-03"], kind="manufacturing"),
    # ---- 下游产品与场景 ----
    n("D1", "中国大陆线下零售", DOWN, ["小米之家", "授权专卖店", "运营商营业厅"], ["E-WEB-01"], kind="application"),
    n("D2", "线上电商渠道", DOWN, ["小米商城", "京东", "天猫", "抖音电商"], ["E-WEB-01"], kind="application"),
    n("D3", "海外市场", DOWN, ["东南亚", "拉美", "欧洲", "中东", "非洲", "印度"], ["E-WEB-01", "E-WEB-02"], kind="application"),
    n("D4", "售后与以旧换新", DOWN, ["官方授权服务中心", "旧机回收置换"], ["E-WEB-01", "E-WEB-03"], kind="service"),
    # ---- 配套与支撑 ----
    n("S1", "操作系统与AI能力", SUP, ["HyperOS", "Android", "小米大模型"], ["E-WEB-01"], kind="software"),
    n("S2", "小米IoT生态与互联互通", SUP, ["AIoT平台", "米家", "小米汽车互联"], ["E-WEB-01", "E-WEB-05"], kind="software"),
    n("S3", "供应链管理与物流", SUP, ["全球供应链体系", "物流与仓配"], ["E-WEB-03", "E-WEB-05"], kind="service"),
]


def e(source, target, label, flow_type, ev):
    return ChainEdge(source=source, target=target, label=label, flow_type=flow_type, evidence_ids=ev)


edges = [
    # 上游 → 整机（供给）
    e("U1", "M1", "供给", "supply", ["E-WEB-03", "E-WEB-04"]),
    e("U2", "M1", "供给", "supply", ["E-WEB-03", "E-WEB-04"]),
    e("U3", "M1", "供给", "supply", ["E-WEB-03", "E-WEB-04"]),
    e("U4", "M1", "供给", "supply", ["E-WEB-03", "E-WEB-04"]),
    e("U5", "M1", "供给", "supply", ["E-WEB-03", "E-WEB-04"]),
    e("U6", "M1", "供给", "supply", ["E-WEB-03", "E-WEB-04"]),
    e("U7", "M1", "供给", "supply", ["E-WEB-03", "E-WEB-04"]),
    e("U8", "M1", "供给", "supply", ["E-WEB-03", "E-WEB-04"]),
    # 整机 → 制造（委外与自制）
    e("M1", "M2", "委外设计", "application", ["E-WEB-03"]),
    e("M1", "M3", "委外组装", "application", ["E-WEB-03"]),
    e("M1", "M4", "自制旗舰", "application", ["E-WEB-03"]),
    # 制造 → 渠道（交付）
    e("M2", "D1", "交付", "application", ["E-WEB-03"]),
    e("M2", "D2", "交付", "application", ["E-WEB-03"]),
    e("M2", "D3", "交付", "application", ["E-WEB-02"]),
    e("M3", "D1", "交付", "application", ["E-WEB-03"]),
    e("M3", "D2", "交付", "application", ["E-WEB-03"]),
    e("M3", "D3", "交付", "application", ["E-WEB-02"]),
    e("M4", "D1", "交付", "application", ["E-WEB-03"]),
    e("M4", "D2", "交付", "application", ["E-WEB-03"]),
    # 支撑关系（虚线语义）
    e("S1", "M1", "软件", "software", ["E-WEB-01"]),
    e("S2", "M1", "生态协同", "support", ["E-WEB-01", "E-WEB-05"]),
    e("S3", "D1", "支撑", "support", ["E-WEB-03"]),
    e("S3", "D2", "支撑", "support", ["E-WEB-03"]),
    e("S3", "D3", "支撑", "support", ["E-WEB-02"]),
    # 逆向闭环：回收 → 制造
    e("D4", "M1", "回收", "recycle", ["E-WEB-01", "E-WEB-03"]),
]

dataset = ChartDataset(
    dataset_id="DS-XIAOMI-PHONE-CHAIN",
    kind="industry_chain",
    metric_name="小米手机产业链",
    # 显式指定：要的是「上中下游产业链全景」，不是产品结构拆解图。
    # 不指定的话 select_chain_template 会因为整机节点 is_core=True 判成
    # product_decomposition（中心产品爆炸图），与本意不符。
    chain_template_hint="horizontal_flow",
    nodes=nodes,
    edges=edges,
    evidence_ids=list(SOURCES),
)


def main() -> None:
    ctx = {
        "industry_topic": "小米手机产业链",
        "focus_questions": ["小米手机产业链的上中下游与代表企业如何构成？"],
    }
    template = select_chain_template(dataset, ctx)
    graph = build_verified_chain_graph(
        title="小米手机产业链全景（公开资料整理）",
        dataset=dataset,
        request_context=ctx,
        template=template,
    )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "xiaomi-phone.graph.json").write_text(
        json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT / "xiaomi-phone.runtime.json").write_text(
        build_prompt_runtime_payload(graph, template), encoding="utf-8"
    )
    print(f"模板：{template}")
    print(f"节点 {len(graph['nodes'])} / 边 {len(graph['edges'])}")
    print(f"落盘：{OUT}/xiaomi-phone.graph.json")
    print("\n数据来源（公开检索，2026-09-20）：")
    for key, text in SOURCES.items():
        print(f"  {key}: {text[:88]}")


if __name__ == "__main__":
    main()
