from datetime import date, datetime, timezone
import pytest

from data_interpreter.engine import DeterministicAnalysisEngine
from data_interpreter.models import (
    AnalysisRequest,
    Domain,
    ResearchRecord,
    SourceRef,
    StructuredResearchDataset,
)


def _mock_record(record_id, domain, entity_name, entity_code, metric, value, raw_fields=None, unit="元"):
    return ResearchRecord(
        record_id=record_id,
        domain=domain,
        entity_name=entity_name,
        entity_code=entity_code,
        metric=metric,
        value=value,
        unit=unit,
        period_end=date(2025, 12, 31),
        source=SourceRef(
            task_id="t1",
            skill_id="test-skill",
            query="q",
            trace_id="tr1",
            retrieved_at=datetime(2026, 9, 23, tzinfo=timezone.utc),
        ),
        raw_fields=raw_fields or {},
    )


def test_engine_dynamic_ticker_and_chain_products():
    engine = DeterministicAnalysisEngine()
    # A completely unknown company with code not in any hardcoded dictionary
    dataset = StructuredResearchDataset(
        companies=[
            _mock_record("c1", Domain.COMPANIES, "未来超导科技", "688999.SH", "总市值", 500_0000_0000.0),
        ],
        industry_chain=[
            _mock_record(
                "ic1", Domain.INDUSTRY_CHAIN, "未来超导科技", "688999.SH", "主营业务",
                "超导电缆与高温磁体", raw_fields={"产业链环节": "中游"}
            ),
        ],
    )

    comps = engine.build_peer_comps_matrix(dataset)
    assert any(c.company_name == "未来超导科技" for c in comps.entries)

    chain = engine.extract_industry_chain(dataset, "超导材料")
    for seg in chain:
        for p in seg.key_products:
            # Must NOT contain hardcoded robotics phrases
            assert "一体化关节模组" not in p
            assert "石墨电极" not in p
            assert "生猪" not in p
