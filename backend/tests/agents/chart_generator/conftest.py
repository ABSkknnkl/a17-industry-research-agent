from datetime import date

import pytest

from app.schemas.chart import ChainEdge, ChainNode, ChartDataset, ChartPoint


@pytest.fixture
def time_series_dataset() -> ChartDataset:
    return ChartDataset(
        dataset_id="DS-REVENUE",
        kind="time_series",
        metric_name="行业收入",
        unit="亿元",
        currency="CNY",
        points=[
            ChartPoint(
                label="2025",
                value=120,
                series="行业",
                period_end=date(2025, 12, 31),
                evidence_id="E-002",
            ),
            ChartPoint(
                label="2024",
                value=100,
                series="行业",
                period_end=date(2024, 12, 31),
                evidence_id="E-001",
            ),
            ChartPoint(
                label="2026E",
                value=None,
                series="行业",
                period_end=date(2026, 12, 31),
                evidence_id="E-003",
            ),
        ],
        evidence_ids=["E-001", "E-002", "E-003"],
    )


@pytest.fixture
def categorical_dataset() -> ChartDataset:
    return ChartDataset(
        dataset_id="DS-MARKET-SHARE",
        kind="categorical",
        metric_name="市场份额",
        unit="%",
        points=[
            ChartPoint(label="公司A", value=35, evidence_id="E-101"),
            ChartPoint(label="公司B", value=25, evidence_id="E-102"),
            ChartPoint(label="公司C", value=15, evidence_id="E-103"),
        ],
        evidence_ids=["E-101", "E-102", "E-103"],
    )


@pytest.fixture
def composition_dataset() -> ChartDataset:
    return ChartDataset(
        dataset_id="DS-COMPOSITION",
        kind="categorical",
        metric_name="市场份额",
        unit="%",
        is_additive=True,
        is_composition=True,
        points=[
            ChartPoint(label="公司A", value=45, evidence_id="E-111"),
            ChartPoint(label="公司B", value=30, evidence_id="E-112"),
            ChartPoint(label="其他", value=25, evidence_id="E-113"),
        ],
        evidence_ids=["E-111", "E-112", "E-113"],
    )


@pytest.fixture
def radar_dataset() -> ChartDataset:
    return ChartDataset(
        dataset_id="DS-RADAR",
        kind="categorical",
        metric_name="企业综合能力评分",
        unit="分",
        is_standardized=True,
        scale_min=0,
        scale_max=100,
        points=[
            ChartPoint(label="技术", value=85, series="公司A", evidence_id="E-121"),
            ChartPoint(label="渠道", value=72, series="公司A", evidence_id="E-122"),
            ChartPoint(label="盈利", value=68, series="公司A", evidence_id="E-123"),
            ChartPoint(label="技术", value=75, series="公司B", evidence_id="E-124"),
            ChartPoint(label="渠道", value=81, series="公司B", evidence_id="E-125"),
            ChartPoint(label="盈利", value=64, series="公司B", evidence_id="E-126"),
        ],
        evidence_ids=["E-121", "E-122", "E-123", "E-124", "E-125", "E-126"],
    )


@pytest.fixture
def chain_dataset() -> ChartDataset:
    return ChartDataset(
        dataset_id="DS-CHAIN",
        kind="industry_chain",
        metric_name="新能源产业链",
        nodes=[
            ChainNode(
                node_id="lithium",
                label="锂资源",
                stage="upstream",
                evidence_ids=["E-201"],
            ),
            ChainNode(
                node_id="battery",
                label="动力电池",
                stage="midstream",
                evidence_ids=["E-202"],
            ),
            ChainNode(
                node_id="vehicle",
                label="新能源汽车",
                stage="downstream",
                evidence_ids=["E-203"],
            ),
        ],
        edges=[
            ChainEdge(
                source="lithium",
                target="battery",
                evidence_ids=["E-201", "E-202"],
            ),
            ChainEdge(
                source="battery",
                target="vehicle",
                evidence_ids=["E-202", "E-203"],
            ),
        ],
        evidence_ids=["E-201", "E-202", "E-203"],
    )
