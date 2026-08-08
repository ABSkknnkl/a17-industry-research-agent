from app.agents.chart_generator.builders import build_heatmap_option
from app.agents.chart_generator.router import route_chart
from app.schemas.chart import ChartDataset, MatrixCell


def test_heatmap_requires_complete_comparable_matrix() -> None:
    rows = [f"公司{index}" for index in range(5)]
    columns = ["技术", "渠道", "盈利", "成长"]
    cells = [
        MatrixCell(
            row=row,
            column=column,
            value=float(row_index * 10 + column_index),
            evidence_id=f"E-M-{row_index}-{column_index}",
        )
        for row_index, row in enumerate(rows)
        for column_index, column in enumerate(columns)
    ]
    dataset = ChartDataset(
        dataset_id="DS-MATRIX",
        kind="matrix",
        metric_name="企业能力矩阵",
        unit="分",
        is_standardized=True,
        scale_min=0,
        scale_max=100,
        matrix_cells=cells,
        evidence_ids=[cell.evidence_id for cell in cells],
    )

    decision = route_chart("heatmap", dataset)
    option = build_heatmap_option("企业能力矩阵", dataset)

    assert decision.accepted is True
    assert option["series"][0]["type"] == "heatmap"
    assert len(option["series"][0]["data"]) == 20
    assert option["visualMap"]["min"] == 0.0
    assert option["visualMap"]["max"] == 100.0
