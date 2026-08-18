import json

import pytest

from app.agents.chart_generator.industry_chain import (
    build_prompt_runtime_payload,
    build_verified_chain_graph,
    compile_chain_prompt,
    select_chain_template,
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
