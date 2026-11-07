"""AB-1 明确指标定义与来源单位 —— 最小失败测试（D01–D05）。

对应方案 docs/superpowers/plans/2026-11-07-AB-root-causes-and-repair-plan.md §5 AB-1 / §6.2。
全部离线、零配额。先确认在有缺陷路径上失败，再修改责任层。

覆盖：
  D01 研发费用 vs 研发投入 不再合并为同一指标族；研发费用率只接受费用分子。
  D02 仅公式与适用条件成立时推导比率，记录输入与公式；错期/错范围/无有效分母不计算。
  D03 无来源单位金额 → unknown，不参与量化覆盖/比率；显式单位换算正确；来源冲突记录待核。
  D04 0.12 带 ratio/%/百分点/无单位 分别表达，无单位不猜口径。
  D05 旧产物缺 unit_provenance 字段 → legacy_unknown，且 unknown 不默认为元。
"""
from datetime import date, datetime, timezone

import pytest

from data_fetcher.fusion import DataFusion, infer_default_unit
from data_fetcher.models import Domain, ResearchRecord, SkillResult, SourceRef
from agents_core.financial_semantics import metric_family, verified_calculations
from data_interpreter.engine import DeterministicAnalysisEngine


def _src(task_id="t1"):
    return SourceRef(
        task_id=task_id, skill_id="hithink-finance-query", skill_version="1.0.0",
        query="q", trace_id="tr1", retrieved_at=datetime(2026, 11, 7, tzinfo=timezone.utc),
    )


def _fuse(raw_data, domain=Domain.FINANCIALS, as_of=date(2026, 11, 7)):
    result = SkillResult(
        task_id="t1", skill_name="hithink-finance-query", skill_id="hithink-finance-query",
        skill_version="1.0.0", domain=domain, query="q", trace_id="tr1",
        success=True, records=raw_data,
    )
    return DataFusion().fuse([result], as_of)


def _rec(rid, metric, value, unit="亿元", *, entity="合成样本", year=2025,
         scope="consolidated", provenance="source_field"):
    return ResearchRecord(
        record_id=rid, domain=Domain.FINANCIALS, entity_name=entity, entity_code="600001.SH",
        metric=metric, value=value, unit=unit,
        period_start=date(year, 1, 1), period_end=date(year, 12, 31),
        period_type="annual", scope=scope, currency="CNY",
        source=_src(), unit_provenance=provenance,
    )


# ---------------------------------------------------------------------------
# D01 研发费用 / 研发投入 指标族拆分
# ---------------------------------------------------------------------------

def test_d01_metric_family_separates_rd_expense_from_rd_investment():
    """研发投入（可能含资本化）与研发费用（费用化）不是同一指标族。"""
    assert metric_family("研发费用") == "rd_expense"
    assert metric_family("研发投入") == "rd_investment"
    assert metric_family("研发费用") != metric_family("研发投入")


def test_d01_fusion_maps_rd_investment_to_distinct_metric():
    """融合层不得把 研发投入 规范化成 rd_expense。"""
    ds = _fuse([{
        "证券代码": "600001.SH", "证券简称": "合成样本",
        "研发费用[20251231](元)": 1_000_000_000.0,
        "研发投入[20251231](元)": 1_300_000_000.0,
    }])
    metrics = {r.metric for r in ds.financials}
    assert "rd_expense" in metrics
    assert "rd_investment" in metrics
    # 两条记录绑定各自原值，不互相覆盖
    exp = next(r for r in ds.financials if r.metric == "rd_expense")
    inv = next(r for r in ds.financials if r.metric == "rd_investment")
    assert exp.value == 1_000_000_000.0
    assert inv.value == 1_300_000_000.0


def test_d01_rd_ratio_only_accepts_expense_numerator():
    """研发费用率只接受 rd_expense 分子；仅有研发投入时不得产伪费用率。"""
    engine = DeterministicAnalysisEngine()
    from data_fetcher.models import StructuredResearchDataset
    # 只有研发投入（含资本化），没有研发费用
    ds = StructuredResearchDataset(financials=[
        _rec("REV", "revenue", 100), _rec("INV", "rd_investment", 12),
    ])
    ratios = engine.compute_financial_ratios(ds)
    assert ratios[0]["rd_ratio_pct"] is None
    assert "rd_ratio" not in ratios[0]["calculations"]

    # 研发费用齐全时正常推导，且分子是 rd_expense 的 record_id
    ds2 = StructuredResearchDataset(financials=[
        _rec("REV", "revenue", 100), _rec("EXP", "rd_expense", 12),
    ])
    ratios2 = engine.compute_financial_ratios(ds2)
    assert ratios2[0]["rd_ratio_pct"] == 12
    assert ratios2[0]["calculations"]["rd_ratio"]["input_record_ids"] == ["EXP", "REV"]


# ---------------------------------------------------------------------------
# D03 无来源单位金额 → unknown，不参与量化
# ---------------------------------------------------------------------------

def test_d03_unitless_monetary_is_unknown_not_yuan():
    """缺来源单位的金额不得被默认为元；标 unknown 并保留原值供审计。"""
    ds = _fuse([{
        "证券代码": "600879.SH", "证券简称": "航天电子",
        "净利润[20241231]": 850_000_000.0,  # 无 (元) 后缀、无行级单位
    }])
    np_rec = next(r for r in ds.financials if r.metric == "net_profit")
    assert np_rec.unit is None
    assert np_rec.unit_provenance == "unknown"
    assert np_rec.value == 850_000_000.0  # 原值保留用于审计/补采
    assert "unit_unknown" in np_rec.issues


def test_d03_source_field_unit_is_trusted():
    """列头括号单位 → source_field，保留可信单位。"""
    ds = _fuse([{
        "证券代码": "600118.SH", "证券简称": "中国卫星",
        "营业收入[20241231](元)": 7_500_000_000.0,
        "总市值[20260923](亿元)": 500.0,
    }])
    rev = next(r for r in ds.financials if r.metric == "revenue")
    assert rev.unit == "元"
    assert rev.unit_provenance == "source_field"


def test_d03_ratio_multiple_inference_is_schema_trusted():
    """比率/倍数的定义性单位（%、倍）由指标语义确定，标 source_schema 且保留。"""
    ds = _fuse([{
        "证券代码": "600879.SH", "证券简称": "航天电子",
        "ROE[20241231]": 12.3,
        "市盈率(pe)": 28.5,
    }])
    roe = next(r for r in ds.financials if r.metric == "roe")
    pe = next(r for r in ds.financials if r.metric == "pe")
    assert roe.unit == "%" and roe.unit_provenance == "source_schema"
    assert pe.unit == "倍" and pe.unit_provenance == "source_schema"


def test_d03_unknown_unit_excluded_from_ratio():
    """unknown 单位金额不得进入比率计算（即便数值量级看起来像元）。

    用一条可信单位的 market_cap 把公司锚定在 comps 中，从而把"unknown 被排除出
    比率"与"公司因无可比金额而整体退出 comps"两种效应分离。
    """
    engine = DeterministicAnalysisEngine()
    from data_fetcher.models import StructuredResearchDataset
    ds = StructuredResearchDataset(financials=[
        _rec("MC", "market_cap", 500, unit="亿元", provenance="source_field"),
        _rec("REV", "revenue", 100, unit=None, provenance="unknown"),
        _rec("EXP", "rd_expense", 12, unit=None, provenance="unknown"),
    ])
    ratios = engine.compute_financial_ratios(ds)
    assert len(ratios) == 1  # 公司仍在 comps（有可信市值）
    assert ratios[0]["rd_ratio_pct"] is None  # 但 unknown 单位不产费用率
    assert "rd_ratio" not in ratios[0]["calculations"]


def test_d03_unknown_only_money_drops_from_comps():
    """仅有 unknown 单位金额、无任何可比锚点的公司退出 peer comps（金额比较被排除）。"""
    engine = DeterministicAnalysisEngine()
    from data_fetcher.models import StructuredResearchDataset
    ds = StructuredResearchDataset(financials=[
        _rec("REV", "revenue", 100, unit=None, provenance="unknown"),
        _rec("EXP", "rd_expense", 12, unit=None, provenance="unknown"),
    ])
    assert engine.compute_financial_ratios(ds) == []


def test_d03_explicit_units_convert_correctly():
    """元/万元/亿元 三种显式单位换算到同一尺度（亿元）一致。"""
    engine = DeterministicAnalysisEngine()
    assert engine._normalize_money(1_000_000_000.0, "元") == pytest.approx(10.0)
    assert engine._normalize_money(100_000.0, "万元") == pytest.approx(10.0)
    assert engine._normalize_money(10.0, "亿元") == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# D04 无来源单位不得按量级/大小猜尺度
# ---------------------------------------------------------------------------

def test_d04_normalize_money_does_not_guess_scale_from_magnitude():
    """_normalize_money 对未知单位不得按绝对值猜尺度（12 不能当成 12 亿）。"""
    engine = DeterministicAnalysisEngine()
    assert engine._normalize_money(12.0, None) is None
    assert engine._normalize_money(850_000_000.0, None) is None
    assert engine._normalize_money(12.0, "unknown") is None


def test_d04_normalize_pct_does_not_guess_unitless_ratio():
    """0.12 无单位不得被猜成 12%；带 ratio/% 分别正确。"""
    engine = DeterministicAnalysisEngine()
    assert engine._normalize_pct(0.12, "ratio") == pytest.approx(12.0)
    assert engine._normalize_pct(12.0, "%") == pytest.approx(12.0)
    # 无单位：不猜口径，原样返回（不 *100）
    assert engine._normalize_pct(0.12, None) == pytest.approx(0.12)
    assert engine._normalize_pct(0.12, "") == pytest.approx(0.12)


# ---------------------------------------------------------------------------
# D05 旧产物兼容
# ---------------------------------------------------------------------------

def test_d05_legacy_record_without_provenance_defaults_legacy_unknown():
    """旧 JSON 缺 unit_provenance 字段 → legacy_unknown，不默认为元。"""
    legacy = ResearchRecord.model_validate({
        "record_id": "R-legacy", "domain": "financials", "entity_name": "甲公司",
        "metric": "revenue", "value": 100, "unit": "元",
        "source": {
            "task_id": "t1", "skill_id": "s", "skill_version": "1.0.0",
            "query": "q", "trace_id": "tr", "retrieved_at": "2026-01-01T00:00:00+00:00",
        },
    })
    assert legacy.unit_provenance == "legacy_unknown"


def test_d05_evidence_ref_carries_unit_provenance():
    """EvidenceRef 透传 unit_provenance，下游可区分原始/推断单位。"""
    engine = DeterministicAnalysisEngine()
    rec = _rec("R1", "revenue", 100, unit=None, provenance="unknown")
    ev = engine._evidence(rec)
    assert ev.unit_provenance == "unknown"
    assert ev.unit is None


# ---------------------------------------------------------------------------
# infer_default_unit 函数本身保持既有语义（融合层负责是否信任）
# ---------------------------------------------------------------------------

def test_infer_default_unit_function_unchanged():
    """infer_default_unit 仍按指标类返回定义性单位；信任决策在融合包装层。"""
    assert infer_default_unit("gross_margin") == "%"
    assert infer_default_unit("pe") == "倍"
    assert infer_default_unit("revenue") == "元"
