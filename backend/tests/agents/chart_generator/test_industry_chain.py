import json

import pytest

from app.agents.chart_generator.industry_chain import (
    PROMPT_COMPILER_SYSTEM,
    build_connection_section,
    build_prompt_runtime_payload,
    build_verified_chain_graph,
    compile_chain_prompt,
    finalize_chain_prompt,
    select_chain_template,
    validate_chain_prompt,
)
from app.integrations.visuals.mock import MockPromptCompiler
from app.schemas.chart import ChartDataset


def test_product_request_selects_exploded_structure_template(
    chain_dataset: ChartDataset,
) -> None:
    product_dataset = chain_dataset.model_copy(
        update={"metric_name": "英伟达显卡产业链", "core_product_name": "英伟达显卡"}
    )

    template = select_chain_template(
        product_dataset,
        {"industry_topic": "英伟达显卡", "focus_questions": ["显卡零部件如何构成？"]},
    )
    graph = build_verified_chain_graph(
        title="英伟达显卡产业链全景图",
        dataset=product_dataset,
        request_context={"industry_topic": "英伟达显卡"},
        template=template,
    )
    payload = json.loads(build_prompt_runtime_payload(graph, template))

    assert template == "product_decomposition"
    assert graph["core_product_name"] == "英伟达显卡"
    assert "结构轮廓爆炸图" in payload["template_specification"]["layout"]
    assert "实拍摄影" in payload["template_specification"]["visual_rules"]


def test_full_industry_request_selects_horizontal_flow_template(
    chain_dataset: ChartDataset,
) -> None:
    template = select_chain_template(
        chain_dataset,
        {"industry_topic": "新能源行业", "focus_questions": ["全产业链供需如何传导？"]},
    )

    assert template == "horizontal_flow"


@pytest.mark.asyncio
async def test_ds_compiler_receives_only_verified_graph(
    chain_dataset: ChartDataset,
) -> None:
    graph = build_verified_chain_graph(
        title="新能源产业链",
        dataset=chain_dataset,
        request_context={"industry_topic": "新能源行业"},
        template="horizontal_flow",
    )

    prompt = await compile_chain_prompt(
        compiler=MockPromptCompiler(),
        graph=graph,
        template="horizontal_flow",
    )

    assert "新能源产业链" in prompt
    assert "只绘制已核验节点与连线" in prompt


# ---------------------------------------------------------------- 拓扑下传与门禁
# 背景：图谱边表原本只以「nodes=N edges=N」的计数形式出现在交付提示词里，
# 生图模型看不到任何 source→target，只能自己编流向（实测出图出现箭头反向、
# 节点被压扁、企业名错配）。下面这几条把「拓扑必须进产物」锁成契约。

_GRAPH = {
    "title": "测试产业链",
    "nodes": [
        {"node_id": "U1", "label": "锂资源", "stage": "upstream"},
        {"node_id": "M1", "label": "动力电池", "stage": "midstream"},
        {"node_id": "D1", "label": "新能源汽车", "stage": "downstream"},
        {"node_id": "S1", "label": "回收网络", "stage": "support"},
        {"node_id": "U2", "label": "孤立节点", "stage": "upstream"},
    ],
    "edges": [
        {"source": "U1", "target": "M1", "label": "供给", "flow_type": "supply"},
        {"source": "M1", "target": "D1", "label": "交付", "flow_type": "application"},
        {"source": "S1", "target": "M1", "label": "回收", "flow_type": "recycle"},
    ],
}


def test_connection_section_renders_every_edge_with_direction_and_line_style() -> None:
    section = build_connection_section(_GRAPH)

    assert section.startswith("【连接关系")
    assert "上游供给→中游制造与集成（供给·藏青实线）：锂资源 → 动力电池" in section
    assert "中游制造与集成→下游产品与场景（交付·藏青实线）：动力电池 → 新能源汽车" in section
    # support/recycle 走灰蓝虚线，与 _FLOW_TEMPLATE 的线型口径一致
    assert "配套与支撑→中游制造与集成（回收·灰蓝虚线）：回收网络 → 动力电池" in section
    # 未出现在任何边里的节点也要列出，保证节点集合完整
    assert "无连线节点：孤立节点" in section
    # 产物不得泄露内部编号
    assert "U1" not in section and "M1" not in section and "S1" not in section


def test_validate_chain_prompt_reports_missing_nodes_and_edge_endpoints() -> None:
    problems = validate_chain_prompt("一段与图谱无关的文字", _GRAPH)

    assert "节点缺失：锂资源" in problems
    assert "连线端点缺失：锂资源 → 动力电池" in problems
    assert len(problems) >= len(_GRAPH["nodes"])
    # 确定性连接段本身必须直接过门禁
    assert validate_chain_prompt(build_connection_section(_GRAPH), _GRAPH) == []


def test_finalize_chain_prompt_appends_connections_only_when_missing() -> None:
    finalized, missing = finalize_chain_prompt("请按版式绘制产业链信息图。", _GRAPH)

    assert missing and "【连接关系" in finalized
    # 幂等：已经带上连接段后再跑一次不应重复追加
    again, second_missing = finalize_chain_prompt(finalized, _GRAPH)
    assert again == finalized and second_missing == []


class _DroppingCompiler:
    """模拟「只写版式、把连线压缩掉」的编译器输出。"""

    model_name = "dropping-compiler"

    async def compile_prompt(self, *, system_prompt: str, runtime_prompt: str) -> str:
        # 长度超过 80 字的前置门槛，且完全不写任何 source→target（模拟真实漏写）
        return (
            "券商投行级行业深度报告信息图，横向16:9、A4横向PDF；顶部藏青标题栏；"
            "左至右依次为上游供给、中游制造与集成、下游产品与场景，底部配套与循环支撑通栏。"
            "白色背景，藏青与浅灰蓝配色，纯2D扁平矢量，文字卡片+线性图标+箭头，"
            "同级卡片等宽等高，中文文字清晰可读，禁止编造数据与虚构企业。"
        )


@pytest.mark.asyncio
async def test_compile_chain_prompt_backfills_topology_when_compiler_drops_it(
    chain_dataset: ChartDataset,
) -> None:
    graph = build_verified_chain_graph(
        title="新能源产业链",
        dataset=chain_dataset,
        request_context={"industry_topic": "新能源行业"},
        template="horizontal_flow",
    )
    assert graph["edges"], "fixture 必须带边，否则本测试会空转"

    prompt = await compile_chain_prompt(
        compiler=_DroppingCompiler(),
        graph=graph,
        template="horizontal_flow",
    )

    assert "【连接关系" in prompt
    assert validate_chain_prompt(prompt, graph) == []
    # 误导性的规模计数不应再出现
    assert "nodes=" not in prompt and "edges=" not in prompt


@pytest.mark.asyncio
async def test_compiled_prompt_carries_no_internal_ids_or_counters(
    chain_dataset: ChartDataset,
) -> None:
    graph = build_verified_chain_graph(
        title="新能源产业链",
        dataset=chain_dataset,
        request_context={"industry_topic": "新能源行业"},
        template="horizontal_flow",
    )

    prompt = await compile_chain_prompt(
        compiler=MockPromptCompiler(),
        graph=graph,
        template="horizontal_flow",
    )

    assert "nodes=" not in prompt and "edges=" not in prompt
    assert validate_chain_prompt(prompt, graph) == []


def test_system_prompt_requires_edge_enumeration_and_bans_counters() -> None:
    assert "必须逐条列出连线" in PROMPT_COMPILER_SYSTEM
    assert "不得写出 U1/M1/D1/S1 这类内部编号" in PROMPT_COMPILER_SYSTEM
    assert "不得出现 nodes=、edges= 这类计数" in PROMPT_COMPILER_SYSTEM
