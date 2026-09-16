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


def test_finance_dashboard_treemap_has_hierarchical_spacing_and_labels() -> None:
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
            node_id="software",
            label="软件与服务",
            parent_id=None,
            value=30,
            evidence_ids=["E-SOFTWARE"],
        ),
    ]
    dataset = ChartDataset(
        dataset_id="DS-FINANCE-TREEMAP",
        kind="hierarchy",
        metric_name="产业收入构成",
        unit="亿元",
        currency="CNY",
        hierarchy_nodes=nodes,
        evidence_ids=["E-HARDWARE", "E-CHIP", "E-SOFTWARE"],
    )

    option = build_treemap_option("产业收入构成", dataset, "finance_dashboard")
    series = option["series"][0]

    assert series["itemStyle"] == {"borderColor": "#FFFFFF", "borderWidth": 3, "gapWidth": 3}
    assert series["label"]["color"] == "#FFFFFF"
    assert series["label"]["formatter"] == "{b}\n{c} 亿元"
    assert series["label"]["position"] == "inside"
    assert series["left"] == 16
    assert series["right"] == 16
    assert series["top"] == 28
    assert series["bottom"] == 12
    assert series["upperLabel"] == {
        "show": True,
        "height": 28,
        "color": "#FFFFFF",
        "fontWeight": 700,
        "formatter": "{b}",
    }
    assert series["levels"][0]["itemStyle"]["gapWidth"] == 4
    assert series["levels"][1]["color"][:3] == ["#3473EA", "#69B2ED", "#F3AC28"]
    assert len(series["levels"]) == 3
    assert series["levels"][2]["colorSaturation"] == [0.32, 0.7]
    assert [item["name"] for item in series["data"]] == ["硬件", "软件与服务"]
    assert [item["itemStyle"]["color"] for item in series["data"]] == [
        "#3473EA",
        "#69B2ED",
    ]
    assert all("children" not in item for item in series["data"])
    assert series["colorMappingBy"] == "id"
    assert option["legend"]["show"] is False
