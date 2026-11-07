"""产业链结构契约（ChainGraphSpec）——内容层与版式层的分界（2026-10-07）。

设计原则（见 output/产业链图_模板vs大模型_动态生成架构评估.md）：
- **LLM/取数负责"是什么"**（环节、节点、公司、连线），产出本契约的 JSON；
- **代码负责"画在哪"**（坐标、形状、箭头），渲染器只认本契约，不认行业；
- 任意行业/公司零代码接入：段数、组数、层级深度全部数据驱动；
- 每个节点可挂 evidence_record_ids 回溯证据；挂不上证据的走 inferred 通道
  （图上以虚线+"推断"角标呈现），宁可缺一块不假造一个节点。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# 阶段 id 不封闭：除标准三段外允许任意自定义（如"配套层""出口"），渲染器按序排布
STAGE_ORDER_HINT = ("upstream", "midstream", "downstream", "support")

# 全链路共享上限（提示词/裁判/渲染三处同源，避免各写一份漂移）
MAX_BRANDS = 8            # 整机本体品牌列表上限（渲染按行排，超了画不下）
MAX_BOTTLENECK = 3        # 瓶颈标记上限：标成一片等于没标

# 2026-10-21：``ChainTemplateHint`` / ``ChainGraphSpec.template_hint`` /
# ``choose_chain_template()`` 已删除。版式只剩「三列目录式」一种，
# 渲染入口 ``render_chain_svg`` 不再分派，「按结构选版式」这层判断随之作废。

# 产业链四段式（2026-10-07 升级，移植老项目 chain_designer 的 stage 语义）：
# support=配套支撑层（软件生态/售后回收/以旧换新），与 downstream 销售区严格分开
STAGE_TITLES_FULL = {
    "upstream": "上游：核心供给与零部件",
    "midstream": "中游：设计研发与制造集成",
    "downstream": "下游：渠道销售与终端应用",
    "support": "配套：服务、软件与回收体系",
    "other": "其他关联环节",
}

# 流线语义（移植老项目 line_style）：material=产品实物流（藏青实线）；
# technical=技术/指令流、service=软件/服务流、recycle=逆向物流（灰蓝虚线）
FLOW_SEMANTICS: dict[str, tuple[str, str, str]] = {
    # flow: (中文语义, 线型, 颜色)
    "material": ("产品实物流", "solid", "#1B365D"),
    "technical": ("技术/指令流", "dashed", "#7B93AC"),
    "service": ("软件/服务流", "dashed", "#7B93AC"),
    "recycle": ("逆向物流", "dashed", "#8FA3B8"),
}


class ChainStage(BaseModel):
    stage_id: str                      # upstream / midstream / downstream / support / 自定义
    title: str                         # 显示名，如「上游：基础支撑与核心供给」


class ChainGroup(BaseModel):
    group_id: str
    label: str                         # 组名（虚线框标签），如「感知系统」「传统专用设备」
    stage: str                         # 所属 stage_id


class ChainNode(BaseModel):
    node_id: str
    name: str                          # 环节/节点名
    stage: str = "other"
    group: str | None = None           # 所属 group_id（可选）
    items: list[str] = Field(default_factory=list)      # 子项（细分品类/产品）
    companies: list[str] = Field(default_factory=list)  # 代表企业（老项目卡片第二行）
    description: str = ""              # 环节说明（老项目卡片第三行：说明而非复读连线文字）
    is_core: bool = False              # 核心节点（设计研发/品牌整机）：视觉强调 + 拓扑规则锚点
    emphasis: bool = False             # 主链节点（视觉强调：深色/加大/菱形）
    evidence_record_ids: list[str] = Field(default_factory=list)
    inferred: bool = False             # 无证据支撑的推断节点（虚线+角标）
    # 内容来源层级（2026-10-17）：
    #   "evidence"         = 有问财结构化证据回溯（最可靠）
    #   "industry_common"  = 行业公认常识（问财只覆盖 A 股，eVTOL 三强/低空基建龙头
    #                        多在境外或未上市，取不到结构化证据，但属行业通识）
    #   "web_unverified"   = 博查联网得到、未在问财白名单复核（图上画中性「待核」）
    #   "inferred"         = 三项全空：无证据、无企业、无细分品类（图上画红色「推断」）
    source_tier: Literal["evidence", "industry_common", "web_unverified", "inferred"] = "evidence"
    # ── 2026-10-16 研报级高密度模板扩展（对齐 scratch/chain_redesign 成品图）──
    bottleneck: bool = False           # 卡脖子环节：橙框 + 「瓶颈」角标（全图 1-3 个）
    phase: str = ""                    # 下游场景落地阶段：已落地/试点中/示范期/远期
    buyer: str = ""                    # 下游场景采购方（如「汽车 / 3C / 物流头部企业」）


class ChainEdge(BaseModel):
    source: str                        # node_id
    target: str                        # node_id
    label: str = ""                    # 边标签（关系/工艺方法名）
    flow: str = "flow"                 # material/technical/service/recycle；flow=通用主流向
    kind: Literal["flow", "attach"] = "flow"   # flow=主流向；attach=挂接细线
    edge_id: str = ""
    assertion_ids: list[str] = Field(default_factory=list)
    evidence_record_ids: list[str] = Field(default_factory=list)


class ChainGraphSpec(BaseModel):
    """产业链图谱结构。渲染器只消费本对象，不感知行业语义。"""

    title: str
    subtitle: str = ""                          # 副标题（一句话价值传导）
    core_product: str = ""                      # 核心产品/主体
    stages: list[ChainStage]
    groups: list[ChainGroup] = Field(default_factory=list)
    nodes: list[ChainNode] = Field(default_factory=list)
    edges: list[ChainEdge] = Field(default_factory=list)
    anchor: str | None = None          # 中心锚点 node_id（公司锚定/中心辐射版式）
    source: Literal["deterministic", "llm", "merged", "v2_bundle"] = "merged"
    # ── 2026-10-21 口径（A 企业专属 / B 行业全景）─────────────────────────
    # 渲染层只消费这两个字段，不自己判口径（判定在 chart_generator.chain_scope）。
    # A 版品牌卡只有 1 家是正常的，所以本体盒下限必须可调，不能用固定 3。
    scope_kind: Literal["entity", "industry"] = "industry"
    scope_entity: str = ""
    core_min_brands: int = 3           # 品牌卡画成"本体盒"所需的最少家数

    def node_map(self) -> dict[str, ChainNode]:
        return {n.node_id: n for n in self.nodes}

    def stage_nodes(self, stage_id: str) -> list[ChainNode]:
        return [n for n in self.nodes if n.stage == stage_id]


def _stage_sort_key(stage_id: str) -> tuple[int, str]:
    try:
        return (STAGE_ORDER_HINT.index(stage_id), stage_id)
    except ValueError:
        return (len(STAGE_ORDER_HINT), stage_id)


def build_chain_graph_from_segments(
    segments: list[dict[str, Any]],
    *,
    subject: str = "",
    source: Literal["deterministic", "llm", "merged"] = "merged",
) -> ChainGraphSpec | None:
    """把 A2 的 industry_chain_segments 映射为 ChainGraphSpec。

    映射规则：
    - 每个 segment → 一个节点（name=segment_name，items=代表企业+主要产品）；
    - stage 字段直接落 stage；段标题按标准三段生成，自定义段原样保留；
    - 相邻阶段之间自动补 flow 边（阶段内第一个节点互连），保证主流向箭头不断链；
    - segment 上带 ``inferred=True``（A2 无证据降级标记）的节点进 inferred 通道。
    """
    clean: list[ChainNode] = []
    seen_stages: dict[str, ChainStage] = {}
    default_titles = dict(STAGE_TITLES_FULL)

    for idx, raw in enumerate(segments):
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("segment_name") or "").strip()
        if not name:
            continue
        stage = str(raw.get("stage") or "other").strip() or "other"
        items: list[str] = []
        for key in ("key_products", "representative_companies"):
            for v in raw.get(key) or []:
                v_str = str(v).strip()
                if v_str and v_str not in items:
                    items.append(v_str)
        eids = [str(e) for e in (raw.get("evidence_record_ids") or [])]
        node = ChainNode(
            node_id=f"N{idx + 1}",
            name=name,
            stage=stage,
            items=items,
            evidence_record_ids=eids,
            inferred=bool(raw.get("inferred")) or (not eids),
        )
        clean.append(node)
        if stage not in seen_stages:
            seen_stages[stage] = ChainStage(stage_id=stage, title=default_titles.get(stage, stage))

    if not clean:
        return None

    stages = [seen_stages[k] for k in sorted(seen_stages, key=_stage_sort_key)]

    # 主流向边：相邻阶段之间连一条主干，保证图不断链。
    #
    # 契约（2026-10-17 修订）：
    #   · **部分节点无证据** → 主链只用非推断节点（保留原设计：不把无据环节画进主链）；
    #   · **全图无证据**（A1 取数失败 → segments 全部 inferred=True，见 run-20261017193421）
    #     → 每阶段取第一个节点兜底连边。旧实现在这种情形下 `stage_first` 为空、
    #     **一条边都不生成**，图上只剩 3 张孤立卡片。结构连通性与"内容有无证据"是两件事，
    #     没有证据顶多在节点上画「推断」角标，不能因此把整张图拆散。
    edges: list[ChainEdge] = []
    stage_first: dict[str, ChainNode] = {}
    all_inferred = bool(clean) and all(n.inferred for n in clean)
    if all_inferred:
        for n in clean:
            stage_first.setdefault(n.stage, n)
    else:
        for n in clean:
            if not n.inferred and n.stage not in stage_first:
                stage_first[n.stage] = n
    ordered = [stage_first[s.stage_id] for s in stages if s.stage_id in stage_first]
    for a, b in zip(ordered, ordered[1:]):
        edges.append(ChainEdge(source=a.node_id, target=b.node_id, kind="flow"))

    return ChainGraphSpec(
        title=f"{subject}产业链结构" if subject else "产业链结构",
        stages=stages,
        nodes=clean,
        edges=edges,
        source=source,
    )
