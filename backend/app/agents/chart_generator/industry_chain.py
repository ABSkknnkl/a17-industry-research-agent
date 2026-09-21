"""Evidence-bound prompt construction for generated industry-chain charts."""

import json
import logging
import re
from typing import Any, Literal

from app.integrations.visuals.protocol import PromptCompiler
from app.schemas.chart import ChartDataset

logger = logging.getLogger(__name__)

ChainTemplate = Literal["product_decomposition", "horizontal_flow"]

PROMPT_VERSION = "industry-chain-image-v1"

_PRODUCT_TERMS = (
    "显卡",
    "手机",
    "无人机",
    "机器人",
    "充电桩",
    "储能柜",
    "服务器",
    "发动机",
    "整车",
    "汽车",
)
_PRODUCT_INTENT_TERMS = ("产品拆解", "结构拆解", "零部件", "部件构成", "BOM", "核心系统")
_FLOW_INTENT_TERMS = ("行业全景", "全产业链", "上中下游", "供需", "赛道", "原材料到应用")

PROMPT_COMPILER_SYSTEM = """
你是证券行业研究报告的信息图提示词设计师。输入包含经过证据约束的产业链图谱和固定视觉模板。

你的任务只是把输入编译成一段可直接交给 GPT 生图模型的中文提示词，不研究行业事实。
必须遵守：
1. 只能使用 verified_chain_graph 中出现的标题、节点、层级、公司、Logo 名称和连线；不得补充、删除或改写事实。
2. 不得生成市场份额、产能、营收、利润、价格、供需缺口或任何输入未提供的数字。
3. 公司 Logo 可以出现，但仅限 logo_names 中列出的公司；不得增加其他企业。
4. product_decomposition 模板的中心必须是核心产品的实物结构轮廓爆炸图：拆开显示部件层次，属于技术示意，不是产品摄影、场景摄影或营销渲染。
5. horizontal_flow 模板不得使用实物照片，以文字卡片、线性图标、Logo、箭头和分区为主。
6. 所有可见文字必须沿用图谱中的原始中文名称，卡片短句优先。
7. 严格执行 template_specification 的版式、配色、语义色、箭头和负面约束。
8. 必须逐条列出连线：每条写成「上游节点 → 下游节点（关系类型·线型）」，不得只给数量、只说方向或概括成上中下游三段。
9. 节点名称必须使用图谱中的中文 label，不得写出 U1/M1/D1/S1 这类内部编号。
10. 每个节点一张卡片，节点名称与其企业名必须在同一张卡片内，不得拆散、错配或省略节点。
11. 输出中不得出现 nodes=、edges= 这类计数，也不得出现允许企业/标识之外的型号或编号字符串。
12. 版面必须高信息密度且以文字为主：按图谱节点数铺网格，每张卡片写满三行文字（节点名、企业或细分项、该环节作用），卡片数与节点数一致；图标全图不超过 4 个且只用于阶段标题；禁止只写阶段标题、只画少数几个大框、用图标替代文字或留出大片空白。
13. 运行时输入里的 required_text_blocks 是必须**逐字原样**出现在最终提示词中的文字块，尤其是【连接关系】里的每一条连线；不得改写、精简、合并、省略或改写成自己的话。你可以在这些块之外补充衔接语与视觉风格描述，但块本身必须一字不改地保留。
14. 最终只输出完整生图提示词，不要解释、Markdown 标题或代码围栏。
""".strip()

_PRODUCT_TEMPLATE = {
    "template_id": "product_decomposition",
    "display_name": "中心产品结构拆解型产业链全景图",
    "layout": (
        "横向16:9、A4横向PDF；顶部深色标题栏；中央放实物结构轮廓爆炸图，"
        "用分层拆解的技术示意展示核心组成；左右各三组等宽信息卡；底部三栏配套层。"
    ),
    "content_rules": [
        "中心结构轮廓图只表现已给定核心产品和节点，不添加未知部件",
        "周边模块采用模块标题、细分品类、代表企业三层文字",
        "部件与系统使用细实线连接中心，终端应用使用粗实线向外连接",
        "公司名称或Logo置于所属节点底部，Logo不得大于节点标题",
        "高信息密度但每张卡片最多四条关键词，禁止大面积空白",
    ],
    "visual_rules": (
        "白底，藏青#1F3A5F、浅灰蓝#E8F0F8、浅灰#F5F7FA；纯2D金融研报图表框架；"
        "中心产品为半写实技术结构轮廓爆炸图，不使用实拍摄影、人物、场景或营销背景。"
    ),
    "negative_prompt": (
        "产品摄影，实拍照片，人物，卡通动漫，手绘涂鸦，营销海报，过度3D渲染，"
        "厚重阴影，发光特效，高饱和色彩，水印，乱码，错别字，箭头交叉，"
        "模块大小不一，大面积留白，虚构企业，虚构数字"
    ),
}

_FLOW_TEMPLATE = {
    "template_id": "horizontal_flow",
    "display_name": "上中下游横向流向型产业链全景图",
    "layout": (
        "横向16:9、A4横向PDF；顶部深色标题栏和分段导航；左至右依次为上游供给、"
        "中游制造与集成、下游产品、终端需求；底部设置配套与循环支撑通栏。"
        "【信息密度】画布按节点数铺满网格：上游/下游节点数≥4 时排 2 列，3 个及以下排 1 列；"
        "中游 1-2 张强调卡；底部支撑通栏横排 2-4 项；整体留白不超过 12%，"
        "四个阶段的分区底色块之间不留空档。"
        "【文字密度】文字是主要信息载体：卡片内的文字块不少于卡片数的 2 倍"
        "（节点名、企业/细分项、环节说明各成一行文字）；"
        "图标只允许出现在四个阶段标题旁、全图不超过 4 个，节点卡片内不画图标。"
    ),
    # 四个阶段各一个指定语义色。此前规格只给了「藏青/科技蓝/浅灰蓝/浅灰」四色，
    # 没有为下游与支撑规定颜色，导致每张图各自发挥（下游画绿、支撑画琥珀都算越界）。
    "semantic_colors": {
        "upstream": "科技蓝#2C6CAE",
        "midstream": "深藏青#1F3A5F（核心强调框）",
        "downstream": "浅绿#E8F4EF",
        "support": "浅金#FFF2D8",
    },
    "content_rules": [
        "行业大类下展开二级节点，同级卡片严格等宽等高",
        "藏青实线表示供给、产品或价值流，灰蓝虚线表示软件、服务、配套或回收",
        "每条连线必须逐条画出，箭头方向与 source→target 一致，不得反向、省略或合并成一段概括流向",
        "一个节点一张卡片：节点名称与其企业名必须同卡，不得拆散、错配或省略节点",
        "每张卡片至少三行文字：第一行节点名（主）；第二行 2-4 个企业或细分项（次）；第三行一句话说明该环节供给什么、交付给谁或在链条中的作用；只写节点名的空卡片不合格",
        "卡片数量必须与图谱该阶段节点数一致，不得压缩合并成少数几个大框",
        "多文字少图标：节点卡片内不画图标；图标只允许出现在四个阶段标题旁且全图不超过 4 个；禁止用图标替代文字表达节点含义",
        "文字必须逐字照抄：节点名、企业名、关系文字不得省略、缩写、改写或替换成同义词",
        "字号层级：主标题 22-26pt，阶段标题 14-16pt，节点名 12-14pt，企业或细分项 9-10pt，环节说明 8-9pt；最小字号不小于 8pt",
        "禁止占位符：不得出现 XX、某某、…、示例、占位这类占位文字",
        "节点第三行文字优先使用图谱给出的「源 → 目标（关系）」，不要另编一套说明；除【连接关系】里的 `→` 外，画面与提示词中不得出现反向箭头记号",
        "Logo 不得替代文字，单枚 Logo 面积不超过所在卡片的 12%",
        "每条连线旁必须标注关系文字（供给、交付、配套、软件、支撑、回收、运维、反馈），不得只画裸箭头",
        "底部支撑通栏每一项都要写一行说明文字，不得只写标题",
        "核心节点使用深藏青强调框，公司名称或Logo位于对应节点底部",
        "箭头不得交叉、穿过卡片或遮挡文字",
        "高信息密度、紧凑排布，但保持文字清晰和均匀留白",
    ],
    "visual_rules": (
        "白底，藏青#1F3A5F、科技蓝、浅灰蓝#E8F0F8、浅灰#F5F7FA，"
        "并按上游/中游/下游/支撑分别着语义色，四个阶段使用分区底色块区分；"
        "卡片圆角 2-4px、内边距 4-6px、行距 1.2-1.3；"
        "纯2D扁平矢量信息图，以文字卡片为主体，图标仅作点缀（全图不超过 4 个），"
        "不得用装饰性图形侵占文字面积。"
    ),
    "negative_prompt": (
        "实拍照片堆砌，人物，卡通手绘，3D渲染，异形方框，复杂渐变，厚重投影，"
        "坐标轴，折线图，柱状图，饼图，水印，乱码，错别字，箭头交叉，"
        # 信息密度：这几项是「画得很空」最常见的成因，逐条堵死
        "模块稀少，大面积空白，卡片内只有一行文字，分区只画外框不填内容，"
        "卡片数量少于图谱节点数，留白超过12%，阶段之间大片空档，"
        # 多文字少图标：防止模型用图形偷懒替代文字
        "图标替代文字，图标占比过大，卡片只画图标不写字，装饰性图形侵占文字面积，"
        "裸箭头没有关系文字，节点卡片只有一行标题，"
        "虚构企业，虚构数字，"
        # 可判定的具体表述：把「禁止3D渲染」细化成一眼能判的项，避免模型打太极
        "金属质感，发光光晕，景深虚化，半写实插画，实物渲染，"
        "节点被压缩或合并，企业名与节点错配，规格外配色"
    ),
}


def select_chain_template(dataset: ChartDataset, request_context: dict[str, Any]) -> ChainTemplate:
    if dataset.chain_template_hint is not None:
        return dataset.chain_template_hint
    if dataset.core_product_name or any(node.is_core for node in dataset.nodes):
        return "product_decomposition"
    focus = request_context.get("focus_questions", [])
    focus_text = " ".join(str(item) for item in focus) if isinstance(focus, list) else str(focus)
    text = " ".join(
        [
            dataset.metric_name,
            str(request_context.get("industry_topic", "")),
            focus_text,
        ]
    )
    if any(term in text for term in _FLOW_INTENT_TERMS):
        return "horizontal_flow"
    if any(term in text for term in (*_PRODUCT_INTENT_TERMS, *_PRODUCT_TERMS)):
        return "product_decomposition"
    return "horizontal_flow"


def _core_product_name(dataset: ChartDataset, request_context: dict[str, Any]) -> str | None:
    if dataset.core_product_name:
        return dataset.core_product_name
    core = next((node.label for node in dataset.nodes if node.is_core), None)
    if core:
        return core
    text = " ".join([dataset.metric_name, str(request_context.get("industry_topic", ""))])
    for term in _PRODUCT_TERMS:
        if term in text:
            match = re.search(rf"[A-Za-z0-9\u4e00-\u9fff]{{0,12}}{re.escape(term)}", text)
            return match.group(0).strip() if match else term
    return None


def build_verified_chain_graph(
    *,
    title: str,
    dataset: ChartDataset,
    request_context: dict[str, Any],
    template: ChainTemplate,
) -> dict[str, Any]:
    nodes = [
        {
            "node_id": node.node_id,
            "label": node.label,
            "stage": node.stage,
            "group": node.group,
            "node_kind": node.node_kind,
            "companies": node.companies,
            "logo_names": node.logo_names,
            "is_core": node.is_core,
            "evidence_ids": node.evidence_ids,
        }
        for node in dataset.nodes
    ]
    edges = [
        {
            "source": edge.source,
            "target": edge.target,
            "label": edge.label,
            "flow_type": edge.flow_type,
            "evidence_ids": edge.evidence_ids,
        }
        for edge in dataset.edges
    ]
    return {
        "title": title,
        "subtitle": dataset.chart_subtitle or f"{dataset.metric_name}的价值传导与供需流向",
        "template_id": template,
        "core_product_name": _core_product_name(dataset, request_context),
        "nodes": nodes,
        "edges": edges,
        "evidence_ids": dataset.evidence_ids,
        "allowed_company_names": list(
            dict.fromkeys(company for node in dataset.nodes for company in node.companies)
        ),
        "allowed_logo_names": list(
            dict.fromkeys(logo for node in dataset.nodes for logo in node.logo_names)
        ),
    }


def build_required_content_blocks(
    graph: dict[str, Any], template: ChainTemplate
) -> list[str]:
    """确定性渲染出「必须原样出现在最终提示词里」的文字块。

    根因对策：让 LLM 从 JSON 自己生成 19 个节点与 25 条边时，它会按"生图提示词就该简短"的先验做压缩，
    实测把边全部省掉、节点名漏掉十几个。改成**把事实先由代码写成文本块**交给编译器，
    模型只需"保留这些块 + 补充衔接与风格"——模型对"保留给定文本"的遵从度远高于
    "从结构化数据生成文本"。
    """

    blocks = build_chain_image_prompt_body(graph, template).splitlines()
    blocks.append(build_connection_section(graph))
    return [block for block in blocks if block.strip()]


def missing_required_blocks(prompt: str, blocks: list[str]) -> list[str]:
    """检查编译器是否原样保留了必需的文字块（返回缺失的块，空 = 全部保留）。"""

    return [block for block in blocks if block not in prompt]


def build_prompt_runtime_payload(
    graph: dict[str, Any],
    template: ChainTemplate,
) -> str:
    template_specification = (
        _PRODUCT_TEMPLATE if template == "product_decomposition" else _FLOW_TEMPLATE
    )
    return json.dumps(
        {
            "prompt_version": PROMPT_VERSION,
            "verified_chain_graph": graph,
            "template_specification": template_specification,
            # 事实块由代码预先渲染，要求编译器原样保留（见 build_required_content_blocks 的说明）
            "required_text_blocks": build_required_content_blocks(graph, template),
            "output_requirements": {
                "language": "简体中文",
                "aspect_ratio": "16:9",
                "target": "券商行业深度报告PDF",
                "text_priority": "清晰可读、高信息密度",
            },
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


#: 四个阶段的中文名，与 _FLOW_TEMPLATE.layout 的四段一一对应
_STAGE_LABELS = {
    "upstream": "上游供给",
    "midstream": "中游制造与集成",
    "downstream": "下游产品与场景",
    "support": "配套与支撑",
}

#: 实线 = 供给 / 产品 / 价值流；其余 flow_type（support、software、recycle…）走灰蓝虚线。
#: 与 _FLOW_TEMPLATE.content_rules 的线型定义保持同一口径。
_SOLID_FLOW_TYPES = frozenset({"supply", "value", "application"})

_CONNECTION_HEADING = "【连接关系（必须逐条绘制，方向不得反向、省略或合并）】"


def _edge_line_style(flow_type: str | None) -> str:
    return "藏青实线" if flow_type in _SOLID_FLOW_TYPES else "灰蓝虚线"


def build_connection_section(graph: dict[str, Any]) -> str:
    """把图谱边表渲染成确定性的【连接关系】文本块（不依赖 LLM）。

    图谱里的边用节点 id（U1/M1…）表示，这里先映射成中文 label（产物里不得出现内部编号），
    再按「阶段→阶段 + 关系类型 + 线型」分组，同一分组内聚合成「source → 目标1、目标2」。
    从未出现在任何边里的孤立节点也会单独列出，保证节点集合完整。
    """

    label_of = {node["node_id"]: node["label"] for node in graph["nodes"]}
    stage_of = {node["node_id"]: node.get("stage") or "" for node in graph["nodes"]}

    grouped: dict[tuple[str, str, str, str], dict[str, list[str]]] = {}
    order: list[tuple[str, str, str, str]] = []
    linked: set[str] = set()
    for edge in graph.get("edges") or []:
        source, target = edge.get("source"), edge.get("target")
        if source not in label_of or target not in label_of:
            continue
        linked.update((source, target))
        key = (
            stage_of[source],
            stage_of[target],
            edge.get("label") or "关联",
            _edge_line_style(edge.get("flow_type")),
        )
        if key not in grouped:
            grouped[key] = {}
            order.append(key)
        grouped[key].setdefault(label_of[source], []).append(label_of[target])

    lines = [_CONNECTION_HEADING]
    for key in order:
        stage_from, stage_to, relation, style = key
        head = (
            f"{_STAGE_LABELS.get(stage_from, stage_from or '其他')}"
            f"→{_STAGE_LABELS.get(stage_to, stage_to or '其他')}"
        )
        pairs = "；".join(
            f"{source} → {'、'.join(dict.fromkeys(targets))}"
            for source, targets in grouped[key].items()
        )
        lines.append(f"{head}（{relation}·{style}）：{pairs}")

    orphans = [node["label"] for node in graph["nodes"] if node["node_id"] not in linked]
    if orphans:
        lines.append(f"无连线节点：{'、'.join(orphans)}")
    return "\n".join(lines)


def build_chain_image_prompt_body(graph: dict[str, Any], template: ChainTemplate) -> str:
    """确定性拼装「交付生图模型的纯文字提示词正文」。

    设计契约（对应用户要求「最终给生图模型一定是纯文字，不能有其他」）：
    - 版式/配色/语义色/绘制规则/负面约束**全部取自 template_specification**，
      不再让调用方手写——消除此前两个代打脚本各拼一份 body 的「两处真相」；
    - 只输出描述性中文文字：**不含**编译器系统规则、不含 runtime JSON、
      不含内部模板编号（horizontal_flow 之类）、不含 nodes=/edges= 计数；
    - 节点按阶段分组、用图谱里的中文 label，企业名与节点同卡列出；
    - 拓扑（连接段）由 finalize_chain_prompt 统一补，本函数不重复写边。
    """

    spec = _PRODUCT_TEMPLATE if template == "product_decomposition" else _FLOW_TEMPLATE
    title = graph.get("title", "")
    subtitle = graph.get("subtitle", "")
    core = graph.get("core_product_name") or title
    allowed = "、".join(graph.get("allowed_company_names", []))

    # 每个节点补一行「供向 / 来源」文字，作为卡片内的第三行。
    # 信息全部来自图谱的边（不新增事实），既提高文字密度（多文字少图标），
    # 又避免让生图模型自己编造环节作用——它是照抄清单，不是创作。
    label_of = {node["node_id"]: node["label"] for node in graph["nodes"]}
    flow_of: dict[str, list[str]] = {}
    for edge in graph.get("edges") or []:
        relation = edge.get("label") or "关联"
        if edge.get("source") in label_of and edge.get("target") in label_of:
            # 一律按「源 → 目标（关系）」书写，**绝不出现 `←`**：
            # 实测生图模型会把 `←供给：X` 误读成"本节点指向 X"，从而把箭头画反。
            triple = f"{label_of[edge['source']]} → {label_of[edge['target']]}（{relation}）"
            flow_of.setdefault(edge["source"], []).append(triple)
            flow_of.setdefault(edge["target"], []).append(triple)

    node_lines: list[str] = []
    for stage in ("upstream", "midstream", "downstream", "support"):
        cards: list[str] = []
        for node in graph["nodes"]:
            if node.get("stage") != stage:
                continue
            companies = node.get("companies") or []
            suffix = f"（{'、'.join(companies[:3])}）" if companies else ""
            flow = "；".join(dict.fromkeys(flow_of.get(node["node_id"], [])))
            cards.append(f"{node['label']}{suffix}｜{flow}" if flow else f"{node['label']}{suffix}")
        if cards:
            node_lines.append(f"{_STAGE_LABELS[stage]}（{len(cards)}）：{'；'.join(cards)}")

    lines = [
        f"【标题】{title}",
        f"【副标题】{subtitle}",
        f"【核心产品】{core}",
        f"【版式】{spec['layout']}",
        f"【配色】{spec['visual_rules']}",
    ]
    semantic = spec.get("semantic_colors")
    if semantic:
        pairs = "；".join(
            f"{_STAGE_LABELS.get(key, key)}={value}" for key, value in semantic.items()
        )
        lines.append(f"【语义色】{pairs}")
    lines.append("【节点】一节点一卡片，节点名与其企业名必须同卡，不得拆散或省略：")
    lines.extend(node_lines)
    lines.append(f"【允许企业/标识】{allowed}")
    lines.append(f"【绘制规则】{'；'.join(spec['content_rules'])}")
    lines.append(f"【负面约束】{spec['negative_prompt']}")
    lines.append(
        "【硬约束】只使用上述节点与允许企业名；节点名用中文、不得写内部编号；"
        "不得出现市场份额/产能/营收等未提供数字；连线以下方【连接关系】为准，"
        "逐条绘制、方向不得反向或合并。"
    )
    lines.append(
        "【出图前自查】卡片数是否等于各阶段括号里的数量；箭头是否全部由上游指向下游、"
        "没有反向或裸箭头；每条连线旁是否都写了关系文字；每个卡片是否至少三行文字；"
        "有没有把节点压缩合并或漏画。"
    )
    return "\n".join(lines)


def _extract_connection_section(prompt: str) -> str | None:
    """取出交付提示词里的【连接关系】段（从标题到文末）。

    确定性补全总是把该段追加在末尾，因此「标题→文末」即该段边界。
    返回 None 表示编译器完全没写连接段。
    """

    idx = prompt.find(_CONNECTION_HEADING)
    return prompt[idx:] if idx >= 0 else None


def validate_chain_prompt(prompt: str, graph: dict[str, Any]) -> list[str]:
    """确定性门禁：交付提示词必须在【连接关系】段里逐条写出连线。

    返回缺失项清单（空 = 通过）。判据是机械可判定的，不猜语义：
    1. 必须存在【连接关系】段落；
    2. 每个节点名都必须出现在**连接段内**——只在【图谱内容】里罗列节点不算写了拓扑
       （这正是此前门禁太弱的根因：节点名在别处出现就放行，连接段残缺也拦不住）；
    3. 每条连线的两端名都必须出现在**连接段内**。
    """

    missing: list[str] = []
    section = _extract_connection_section(prompt)
    if section is None:
        missing.append("缺少【连接关系】段落（拓扑未逐条写出）")
        # 连接段缺失时，后续所有节点/端点检查必然落空，用空串统一走「缺失」分支
        section = ""

    label_of = {node["node_id"]: node["label"] for node in graph["nodes"]}
    for node in graph["nodes"]:
        if node["label"] not in section:
            missing.append(f"节点缺失：{node['label']}")
    for edge in graph.get("edges") or []:
        source = label_of.get(edge.get("source"))
        target = label_of.get(edge.get("target"))
        if source is None or target is None:
            continue
        if source not in section or target not in section:
            missing.append(f"连线端点缺失：{source} → {target}")
    return missing


def finalize_chain_prompt(prompt: str, graph: dict[str, Any]) -> tuple[str, list[str]]:
    """保证交付提示词一定带完整拓扑（LLM 漏写或写残时由确定性代码补齐）。

    返回 (最终提示词, 补全前的缺失项)。以【连接关系】段的存在性与完整性为准：
    1. 段已存在且门禁通过 → 原样保留（幂等，重复跑不会叠加）；
    2. 段完全缺失 → 把 build_connection_section 的完整连接段追加到末尾；
    3. 段存在但残缺（写了标题却漏边/漏节点）→ 砍掉残缺段，用确定性连接段重建。
    追加/重建内容全部来自经证据约束的图谱，只做「把已核验的边写清楚」，不新增任何事实。
    """

    problems = validate_chain_prompt(prompt, graph)
    heading_idx = prompt.find(_CONNECTION_HEADING)

    # 分支 1：连接段已存在且完整，原样返回（保证幂等）
    if heading_idx >= 0 and not problems:
        return prompt, problems

    # 分支 2：完全没有连接段，直接在末尾追加
    if heading_idx < 0:
        return f"{prompt.rstrip()}\n\n{build_connection_section(graph)}", problems

    # 分支 3：连接段存在但残缺，砍掉从标题起的残缺段，用确定性连接段重建
    head = prompt[:heading_idx].rstrip()
    return f"{head}\n\n{build_connection_section(graph)}", problems


#: 纯文字契约的「污染标记」：一旦出现在交付生图模型的提示词里，说明编译器把
#: 输入（runtime JSON / 系统规则）原样吐了回来，而不是产出干净的描述性文字。
#: 取 build_prompt_runtime_payload 的三个顶层 JSON 键 + 系统规则首行作为特征。
_PURITY_FORBIDDEN_MARKERS = (
    '"verified_chain_graph"',
    '"template_specification"',
    '"prompt_version"',
    PROMPT_COMPILER_SYSTEM.splitlines()[0],
)


def assert_pure_image_prompt(prompt: str) -> None:
    """硬门禁：交付生图模型的提示词必须是纯文字，命中污染标记即 fail-closed。"""

    leaked = [marker for marker in _PURITY_FORBIDDEN_MARKERS if marker in prompt]
    if leaked:
        raise ValueError(
            "生图提示词不是纯文字（回带了编译器输入标记）：" + "；".join(leaked)
        )


async def compile_chain_prompt(
    *,
    compiler: PromptCompiler,
    graph: dict[str, Any],
    template: ChainTemplate,
) -> str:
    prompt = await compiler.compile_prompt(
        system_prompt=PROMPT_COMPILER_SYSTEM,
        runtime_prompt=build_prompt_runtime_payload(graph, template),
    )
    prompt = prompt.strip()
    if len(prompt) < 80:
        raise ValueError("compiled industry-chain prompt is underspecified")
    # 遵约率观测：编译器是否原样保留了代码预渲染的事实块（根因对策的效果指标）。
    blocks = build_required_content_blocks(graph, template)
    dropped = missing_required_blocks(prompt, blocks)
    logger.warning(
        "industry-chain 编译器遵约率：必需文字块 %d/%d 被原样保留（丢失 %d）",
        len(blocks) - len(dropped),
        len(blocks),
        len(dropped),
    )
    # 拓扑硬门禁：此前只有长度门槛，拦不住「有计数、无拓扑」。
    # 编译器漏写连线时在此确定性补齐。
    finalized, missing = finalize_chain_prompt(prompt, graph)
    if missing:
        logger.warning(
            "industry-chain prompt 缺少拓扑信息，已确定性补全 %d 项：%s",
            len(missing),
            "；".join(missing[:5]),
        )
    # 纯文字硬契约：最终交付生图模型的提示词不得回带 runtime JSON / 编译器系统规则。
    assert_pure_image_prompt(finalized)
    return finalized
