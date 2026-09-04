from app.agents.chart_generator.builders import build_boxplot_option
from app.agents.chart_generator.router import route_chart
from app.schemas.chart import ChartDataset, DistributionSample


def test_boxplot_computes_quartiles_from_raw_samples() -> None:
    samples = [
        DistributionSample(
            group="行业样本",
            entity=f"公司{value}",
            value=float(value),
            evidence_id=f"E-D-{value}",
        )
        for value in range(1, 9)
    ]
    dataset = ChartDataset(
        dataset_id="DS-DISTRIBUTION",
        kind="distribution",
        metric_name="ROE分布",
        unit="%",
        distribution_samples=samples,
        evidence_ids=[sample.evidence_id for sample in samples],
    )

    decision = route_chart("boxplot", dataset)
    option = build_boxplot_option("ROE分布", dataset)

    assert decision.accepted is True
    assert option["series"][0]["type"] == "boxplot"
    assert option["series"][0]["data"] == [[1.0, 2.75, 4.5, 6.25, 8.0]]
    assert option["sampleEvidenceMap"]["行业样本"] == [f"E-D-{value}" for value in range(1, 9)]
