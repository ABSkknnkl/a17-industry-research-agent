#!/usr/bin/env python3
"""构建新能源汽车产业链「审定事实底座」``vehicle.json``（一次性构建记录）。

输入：主项目 2026-10-16 评测产出的 18 节点 ChainGraphSpec 存档。
输出：本目录 ``vehicle.json`` —— **运行时自包含**，不依赖主项目路径。

本次修订（见用户 2026-11-12 诊断）：
  B1 Tier1 零部件商（拓普集团/三花智控）从「整车制造与集成」移出，另立环节；
  B2 比亚迪/特斯拉中国等跨环节复用 → annotations.vertical_integration 显式标注；
  B3 整车环节补入财务分析对象长安汽车、赛力斯；
  B4 下游按「用途/采购主体」单一维度重分，海外出口降为地域渠道注记，不并列；
  B5 充换电补专业运营商、电池回收补第三方回收商；
  B6 上游补锂镍钴矿产资源端；
  C3 商用车队「试点中」→「已落地」，并给出 phase_basis 口径定义。

只做数据修订，不写死任何公司名单进 engine / 提示词。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

SRC = Path(
    "/Users/Zhuanz1/Downloads/行业研究智能体-全链路系统 4"
    "/scratch/chain_template_eval/新能源汽车.chain_topology.json"
)
OUT = Path(__file__).resolve().parent / "vehicle.json"

# ── B 类内容修订：只改这几处，其余字段原样保留 ────────────────────────────
NODE_PATCH: dict[str, dict] = {
    "CH3": {  # C2：瓶颈依据显式化
        "bottleneck": True,
    },
    "CH6": {
        "bottleneck": True,
    },
    "CH7": {  # C2：同受资源约束，补齐并给依据
        "bottleneck": True,
        "description": "提供驱动电机转子磁钢，受稀土开采配额与价格波动约束",
    },
    "CH8": {  # 与 A2 审定卡中游口径对齐
        "companies": ["宁德时代", "比亚迪", "中创新航", "亿纬锂能"],
    },
    "CH10": {  # B3：补 Q1 财务样本
        "companies": ["比亚迪", "长安汽车", "赛力斯", "特斯拉中国", "蔚来", "理想", "小鹏"],
    },
    "CH11": {  # B1 移出 Tier1；B3 补财务样本；描述保持完整不截断
        "companies": ["比亚迪", "长安汽车", "赛力斯", "特斯拉中国"],
        "items": ["整车总装", "底盘系统", "热管理集成"],
        "description": "承担整车生产制造与底盘/热管理等系统集成，实现产品落地",
    },
    "CH13": {  # B4：用途维度统一命名
        "name": "网约与出行运营",
        "phase": "已落地",
    },
    "CH14": {  # B4 + C3
        "name": "商用与物流车队",
        "phase": "已落地",
    },
    "CH15": {  # B4：把「海外出口」这个地域维度从并列分类里移出
        "name": "公共及专用场景",
        "items": ["公务用车", "环卫与专用车", "市政作业车"],
        "description": "公共机构与专用作业场景批量采购，属用途维度分类",
        "phase": "已落地",
    },
    "CH16": {  # B5：补专业补能运营商
        "companies": ["特来电", "星星充电", "国家电网", "宁德时代", "比亚迪"],
    },
    "CH17": {  # B5：补第三方回收商
        "companies": ["格林美", "华友循环", "比亚迪", "宁德时代", "中创新航"],
    },
    "CH18": {
        "companies": ["华为", "百度Apollo", "特斯拉中国", "蔚来", "小鹏"],
    },
}

# ── B6 / B1：新增两个上游真实环节 ────────────────────────────────────────
NEW_NODES: list[dict] = [
    {
        "node_id": "CH19", "name": "锂镍钴矿产资源", "stage": "upstream", "group": None,
        "items": ["锂辉石", "盐湖卤水", "硫酸镍", "钴精矿"],
        "companies": ["赣锋锂业", "天齐锂业", "华友钴业", "洛阳钼业"],
        "description": "提供锂、镍、钴等上游资源，经冶炼盐类进入正极前驱体",
        "is_core": False, "emphasis": False, "evidence_record_ids": ["R1"],
        "inferred": False, "source_tier": "industry_common", "bottleneck": False,
        "phase": "", "buyer": "",
    },
    {
        "node_id": "CH20", "name": "底盘与热管理部件", "stage": "upstream", "group": None,
        "items": ["底盘结构件", "内饰件", "热管理阀件", "电子膨胀阀"],
        "companies": ["拓普集团", "三花智控"],
        "description": "Tier1 零部件供应商，向整车总装提供底盘与热管理部件",
        "is_core": False, "emphasis": False, "evidence_record_ids": ["R2"],
        "inferred": False, "source_tier": "industry_common", "bottleneck": False,
        "phase": "", "buyer": "",
    },
]

# ── 边：原 17 条全部保留（标签逐字不改），仅修正 B4 改名后的那一条 ─────────
EDGE_LABEL_PATCH = {
    ("CH11", "CH15"): "整车交付公共及专用场景",
}
NEW_EDGES: list[dict] = [
    {"source": "CH19", "target": "CH1", "label": "锂镍钴资源供给正极前驱体",
     "flow": "material", "kind": "flow"},
    {"source": "CH19", "target": "CH4", "label": "锂盐供给电解液溶质",
     "flow": "material", "kind": "flow"},
    {"source": "CH20", "target": "CH11", "label": "底盘与热管理部件供给整车总装",
     "flow": "material", "kind": "flow"},
    {"source": "CH17", "target": "CH19", "label": "再生锂镍钴回流资源端",
     "flow": "recycle", "kind": "flow"},
]

ANNOTATIONS: dict = {
    "theme": "新能源汽车",
    "frame": "full_chain",
    "reviewed_at": "2026-11-12",
    "subtitle": "上游资源与核心材料 → 中游电驱动与整车制造 → 下游用途场景，配套补能回收与车联网支撑",
    # C1：证据来源可追溯
    "sources": {
        "R1": "上游资源与正负极材料环节（行业公开资料）",
        "R2": "电池材料、结构件与 Tier1 部件环节",
        "R3": "芯片功率器件与稀土永磁环节",
        "R4": "动力电池与电驱动总成环节",
        "R5": "整车研发、品牌与制造环节",
        "R6": "下游用途与采购主体场景",
        "R7": "充换电、电池回收与车联网配套",
        "R8": "瓶颈环节的供给约束判据",
    },
    # C2：瓶颈判定依据
    "bottleneck_basis": {
        "CH3": "高端涂覆隔膜与涂布设备国产化受限",
        "CH6": "车规 IGBT / SiC 模块与 MCU 供给受限",
        "CH7": "稀土永磁受开采配额与价格波动约束",
    },
    "bottleneck_rule": "瓶颈 = 关键材料/器件存在供给约束或国产替代未完成；本图按审定口径标注 3 处",
    # C3：状态口径
    "phase_basis": "已落地 = 已有商业化规模运营；试点中 = 局部示范未规模化。本图下游四类场景均为已落地",
    # C4：flow 图例
    "flow_legend": {
        "material": "物料 / 产品供给",
        "technical": "技术 / 工艺输出",
        "service": "服务 / 数据支撑",
        "recycle": "逆向回收 / 资源闭环",
    },
    # B2：垂直整合 / 集团复用
    "vertical_integration": {
        "比亚迪": ["CH8", "CH10", "CH11", "CH16", "CH17"],
        "特斯拉中国": ["CH10", "CH11", "CH18"],
        "中创新航": ["CH8", "CH17"],
        "宁德时代": ["CH8", "CH16", "CH17"],
        "蔚来": ["CH10", "CH18"],
        "小鹏": ["CH10", "CH18"],
    },
    # B3：Q1 财务分析对象
    "financial_sample": ["比亚迪", "长安汽车", "赛力斯"],
    # B4：地域渠道不与用途维度并列
    "channel_note": "海外出口属地域渠道维度，可与任一用途场景叠加，故不列为并列的第四类下游；出口规模另见报告 Q2",
    "sample_note": "图中企业为产业链环节代表主体，非财务样本全集；加「样本」标记者为报告 Q1 对比标的",
    "evidence_note": "R1–R8 为环节级来源索引，图面标注供追溯；企业名单未逐家与原始披露核对",
}


def main() -> None:
    raw = json.loads(SRC.read_text(encoding="utf-8"))
    spec = copy.deepcopy(raw)

    nodes = spec["nodes"]
    by_id = {n["node_id"]: n for n in nodes}
    for nid, patch in NODE_PATCH.items():
        by_id[nid].update(patch)
    nodes.extend(copy.deepcopy(NEW_NODES))
    # 上游新环节排在资源端之后，保证视觉顺序由 stage + 显式顺序控制
    spec["nodes"] = nodes

    for edge in spec["edges"]:
        key = (edge["source"], edge["target"])
        if key in EDGE_LABEL_PATCH:
            edge["label"] = EDGE_LABEL_PATCH[key]
    spec["edges"].extend(copy.deepcopy(NEW_EDGES))

    spec["title"] = "新能源汽车产业链关系全景图"
    spec["subtitle"] = ANNOTATIONS["subtitle"]
    spec["source"] = "merged"
    spec["stages"] = [
        {"stage_id": "upstream", "title": "上游：资源、核心材料与零部件"},
        {"stage_id": "midstream", "title": "中游：设计研发与制造集成"},
        {"stage_id": "downstream", "title": "下游：用途与采购主体"},
        {"stage_id": "support", "title": "配套：补能、回收与车联网"},
    ]

    payload = {
        "theme": "新能源汽车",
        "version": "2026-11-12.1",
        "frame": "full_chain",
        "source_archive": str(SRC),
        "spec": spec,
        "annotations": ANNOTATIONS,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[build] {len(spec['nodes'])} 节点 / {len(spec['edges'])} 边 -> {OUT}")
    print(f"[build] 企业 {sum(len(n['companies']) for n in spec['nodes'])} 家次 / "
          f"品类 {sum(len(n['items']) for n in spec['nodes'])} 项")


if __name__ == "__main__":
    main()
