"""Evidence-bound prompt construction for generated industry-chain charts."""

import json
import re
from typing import Any, Literal

from app.integrations.visuals.protocol import PromptCompiler
from app.schemas.chart import ChartDataset

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
7. 严格执行 template_specification 的版式、配色、箭头和负面约束。
8. 最终只输出完整生图提示词，不要解释、Markdown 标题或代码围栏。
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
    ),
    "content_rules": [
        "行业大类下展开二级节点，同级卡片严格等宽等高",
        "藏青实线表示供给、产品或价值流，灰蓝虚线表示软件、服务、配套或回收",
        "核心节点使用深藏青强调框，公司名称或Logo位于对应节点底部",
        "箭头不得交叉、穿过卡片或遮挡文字",
        "高信息密度、紧凑排布，但保持文字清晰和均匀留白",
    ],
    "visual_rules": (
        "白底，藏青#1F3A5F、科技蓝、浅灰蓝#E8F0F8、浅灰#F5F7FA；"
        "纯2D扁平矢量信息图，只使用文字卡片、线性图标、Logo、箭头和分区。"
    ),
    "negative_prompt": (
        "实拍照片堆砌，人物，卡通手绘，3D渲染，异形方框，复杂渐变，厚重投影，"
        "坐标轴，折线图，柱状图，饼图，水印，乱码，错别字，箭头交叉，"
        "模块稀少，大面积空白，虚构企业，虚构数字"
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
    return prompt
