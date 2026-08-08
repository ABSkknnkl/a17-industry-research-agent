from datetime import date

from app.agents.chart_generator.builders import build_treemap_option
from app.agents.chart_generator.router import route_chart
from app.schemas.chart import ChartDataset, HierarchyNode


def test_treemap_requires_non_negative_audited_hierarchy() -> None:
    nodes = [
        HierarchyNode(
            node_id="hardware",
            label="硬件",
            parent_id=None,
            value=70,
            evidence_ids=["E-HARDWARE"],
        ),
        HierarchyNode(
            node_id="chip",
            label="芯片",
            parent_id="hardware",
            value=45,
            evidence_ids=["E-CHIP"],
        ),
        HierarchyNode(
            node_id="server",
            label="服务器",
            parent_id="hardware",
            value=25,
            evidence_ids=["E-SERVER"],
        ),
        HierarchyNode(
            node_id="software",
            label="软件与服务",
            parent_id=None,
            value=30,
            evidence_ids=["E-SOFTWARE"],
        ),
    ]
    dataset = ChartDataset(
        dataset_id="DS-TREEMAP",
        kind="hierarchy",
        metric_name="产业收入构成",
        unit="亿元",
        currency="CNY",
        data_as_of=date(2025, 12, 31),
        hierarchy_nodes=nodes,
        evidence_ids=[evidence_id for node in nodes for evidence_id in node.evidence_ids],
    )

    decision = route_chart("treemap", dataset)
    option = build_treemap_option("产业收入构成", dataset)

    assert decision.accepted is True
    assert option["series"][0]["type"] == "treemap"
    hardware = option["series"][0]["data"][0]
    assert hardware["name"] == "硬件"
    assert {child["name"] for child in hardware["children"]} == {"芯片", "服务器"}
