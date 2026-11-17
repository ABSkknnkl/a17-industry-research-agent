"""A1 source observations and completeness checks for the NEV five-question template."""

from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re

from .models import (
    Coverage, Domain, RequirementCoverage, ResearchRecord, ResearchRequirement,
    ResearchRunResult, RunError, SourceRef, StructuredResearchDataset,
)


DATASET_PATH = Path(__file__).resolve().parents[3] / "data" / "nev_a1_2025.json"
COMPANIES = {
    "byd": ("比亚迪", "002594.SZ"), "changan": ("长安汽车", "000625.SZ"),
    "seres": ("赛力斯", "601127.SH"), "catl": ("宁德时代", "300750.SZ"),
    "eve": ("亿纬锂能", "300014.SZ"),
}
VEHICLES = tuple(name for name, _ in list(COMPANIES.values())[:3])
YEAR_END = date(2025, 12, 31)
FINANCIAL_FIELDS = {
    "营业收入": ("revenue", "元"), "销售毛利率": ("gross_margin", "%"),
    "经营活动产生的现金流量净额": ("operating_cash_flow", "元"),
    "归母净利润": ("parent_net_profit", "元"), "研发费用": ("rd_expense", "元"),
    "加权净资产收益率": ("roe", "%"), "资产负债率": ("debt_ratio", "%"),
}
MARKET_FIELDS = {
    "sales": ("新能源汽车:销量:累计值", "辆", "annual"),
    "exports": ("新能源汽车:出口量", "辆", "annual"),
    "penetration": ("国内零售渗透率:新能源汽车:当月值", "%", "month"),
}
BYD_PRODUCTS = {
    "汽车及相关产品": "汽车、汽车相关产品及其他产品",
    "手机部件及组装等": "手机部件、组装及其他产品",
    "其他": "其他",
}
POSITION_PRODUCTS = {
    "byd": "汽车及相关产品", "changan": "整车", "seres": "新能源汽车",
    "catl": "动力电池系统", "eve": "动力电池",
}
REQUIREMENTS = {
    "nev_sales_export_annual": ("2021—2025 年新能源汽车销量与出口量", Domain.INDUSTRY),
    "nev_retail_penetration_monthly": ("2021-02—2025-12 国内新能源乘用车月度零售渗透率", Domain.INDUSTRY),
    "nev_oem_finance_pb": ("三家整车企业 2023—2025 年财务及 2021—2025 年月末市净率", Domain.FINANCIALS),
    "nev_chain_positions": ("五家公司产业链、研发费用、毛利率及经营现金流", Domain.INDUSTRY_CHAIN),
    "nev_byd_product_mix": ("比亚迪 2025 年分产品收入、成本与占比", Domain.FINANCIALS),
}


def _day(text: str) -> date:
    return date.fromisoformat(f"{text[:4]}-{text[4:6]}-{text[6:8]}")


def _capture(folder: Path, label: str) -> tuple[dict, dict, SourceRef]:
    entry = json.loads((folder / f"{label}.json").read_bytes())
    request, raw = entry["request"], entry["response"]
    source = SourceRef(
        task_id=label, skill_id=request["skill_id"], skill_version="1",
        query=request["query"], trace_id=request["trace_id"],
        retrieved_at=datetime.fromisoformat(request["retrieved_at"]) if request.get("retrieved_at") else
        datetime.fromtimestamp((folder / f"{label}.json").stat().st_mtime, timezone.utc),
        status="success", record_count=request["rows"],
    )
    return request, raw, source


def _numeric(value) -> float:
    if type(value) not in (str, int, float) or not math.isfinite(result := float(value)):
        raise ValueError("非有限数值")
    return result


def normalize_captures(folder: Path, audited_positions: dict[str, dict]) -> StructuredResearchDataset:
    records: dict[tuple, ResearchRecord] = {}

    def add(source, entity, code, domain, metric, value, unit, period, period_type, *,
            fields=None, scope="consolidated", published_at=None):
        key = (domain.value, code or entity, metric, period.isoformat(), period_type, scope)
        record_id = "R-" + hashlib.sha256(json.dumps(key, ensure_ascii=False).encode()).hexdigest()[:20]
        previous = records.get(key)
        amount = _numeric(value)
        if previous:
            if previous.value != amount or previous.unit != unit:
                raise ValueError(f"同口径记录冲突：{entity} {metric} {period}")
            return
        start = date(period.year, 1, 1) if period_type == "annual" else (
            date(period.year, period.month, 1) if period_type == "month" else period
        )
        records[key] = ResearchRecord(
            record_id=record_id, entity_name=entity, entity_code=code, domain=domain,
            metric=metric, value=amount, unit=unit, unit_provenance="source_field",
            period_end=period, period_start=start, period_type=period_type,
            period_provenance="source_field", scope=scope, source=source, published_at=published_at,
            raw_fields=fields or {},
        )

    for label, (metric, expected_unit, period_type) in MARKET_FIELDS.items():
        _, raw, source = _capture(folder, label)
        for i, row in enumerate(raw["datas"]):
            if (row.get("macro_name"), row.get("国家"), row.get("单位")) != (metric, "中国", expected_unit):
                continue
            day = _day(row["时间"])
            if period_type == "annual" and (day.month, day.day) != (12, 31):
                continue
            add(source.model_copy(update={"raw_record_index": i}), "中国", None, Domain.INDUSTRY,
                metric, row["指标值"], expected_unit, day, period_type,
                fields={"index_no": row["macro_id"], "provider_frequency": row.get("周期")})

    for label in [*(f"annual-{slug}" for slug in COMPANIES if slug != "catl"),
                  "catl-2023", "catl-2024", "catl-2025", "roe-debt"]:
        _, raw, source = _capture(folder, label)
        columns = {column["key"]: column.get("unit") for column in raw["columns"]}
        for i, row in enumerate(raw["datas"]):
            name, code = row["股票简称"], row["股票代码"]
            if (name, code) not in COMPANIES.values():
                continue
            publish = date.fromisoformat(audited_positions[name]["published_at"])
            for field, value in row.items():
                match = re.fullmatch(r"(.+)\[(202[345]1231)\]", field)
                if not match or match[1] not in FINANCIAL_FIELDS or value in (None, "--"):
                    continue
                metric, unit = FINANCIAL_FIELDS[match[1]]
                if columns.get(field) != unit:
                    continue
                day = _day(match[2])
                add(source.model_copy(update={"raw_record_index": i}), name, code, Domain.FINANCIALS,
                    metric, value, unit, day, "annual", fields={"source_column": field},
                    published_at=publish if day == YEAR_END else None)

    for slug, (name, code) in list(COMPANIES.items())[:3]:
        _, raw, source = _capture(folder, f"pb-{slug}")
        months: dict[str, tuple[str, str, float]] = {}
        for row in raw["datas"]:
            if row.get("股票代码") != code:
                continue
            columns = {column["key"]: column.get("unit") for column in raw["columns"]}
            for field, value in row.items():
                match = re.fullmatch(r"市净率\[(202[1-5]\d{4})\]", field)
                if not match or columns.get(field) != "倍" or value in (None, "--"):
                    continue
                day = match[1]
                if day[:6] not in months or day > months[day[:6]][0]:
                    months[day[:6]] = (day, field, _numeric(value))
        for day, field, value in sorted(months.values()):
            if value > 0:
                add(source.model_copy(update={"raw_record_index": 0}), name, code, Domain.FINANCIALS,
                    "pb", value, "倍", _day(day), "point", fields={"source_column": field})

    for slug, (name, code) in COMPANIES.items():
        _, raw, source = _capture(folder, f"segments-{slug}")
        columns = {column["key"]: column.get("unit") for column in raw["columns"]}
        if any(columns.get(field) != "元" for field in ("业务收入", "业务成本")):
            raise ValueError(f"{name}分产品金额单位未确认")
        position = audited_positions[name]
        segments = [(i, row) for i, row in enumerate(raw["datas"])
                    if row.get("股票代码") == code and row.get("分类标准") == "产品"
                    and row.get("报告期截止日") == "20251231"]
        group_revenue = next((r.value for r in records.values() if r.entity_name == name
                              and r.metric == "revenue" and r.period_end == YEAR_END), None)
        match = next(((i, row) for i, row in segments if row.get("项目名称") == POSITION_PRODUCTS[slug]), None)
        if match is None or group_revenue is None or not math.isclose(
            _numeric(match[1]["业务收入"]) / group_revenue * 100, position["value"], abs_tol=1e-5,
        ):
            raise ValueError(f"{name}年报定位未通过同花顺收入交叉核对")
        fields = {key: position[key] for key in ("source_url", "source_locator", "document_sha256")}
        publish = date.fromisoformat(position["published_at"])
        official = source.model_copy(update={"skill_id": "official-segment", "raw_record_index": match[0]})
        add(official, name, code, Domain.INDUSTRY_CHAIN, "business_composition", position["value"],
            "%", YEAR_END, "annual", fields={**fields, "product": position["segment_name"],
            "provider_product": POSITION_PRODUCTS[slug], "cross_validated_group_revenue": group_revenue},
            scope="segment:product", published_at=publish)
        for i, row in segments:
            product = row["项目名称"]
            if slug == "byd":
                if product not in BYD_PRODUCTS:
                    raise ValueError(f"比亚迪出现未核对的产品类别：{product}")
                product = BYD_PRODUCTS[product]
            # The provider combines an aggregate automobile line with its component lines for Seres.
            if slug == "seres" and product == "汽车":
                continue
            for field, metric in (("业务收入", "product_revenue"), ("业务成本", "product_cost")):
                add(source.model_copy(update={"raw_record_index": i}), name, code, Domain.FINANCIALS,
                    f"{metric}:{product}", row[field], "元", YEAR_END, "annual",
                    fields={**fields, "product": product, "source_column": field},
                    scope="segment:product", published_at=publish)

    dataset = StructuredResearchDataset(subject="新能源汽车",
        research_as_of=max(date.fromisoformat(row["published_at"]) for row in audited_positions.values()))
    for record in records.values():
        dataset.records_for(record.domain).append(record)
    dataset.sources = list({r.source.trace_id: r.source.model_copy(update={"raw_record_index": None})
                            for r in records.values()}.values())
    return dataset


def _verify(dataset: StructuredResearchDataset, as_of: date):
    expected_units = {metric: unit for metric, unit, _ in MARKET_FIELDS.values()}
    expected_units.update({metric: unit for metric, unit in FINANCIAL_FIELDS.values()})
    expected_units.update(pb="倍", business_composition="%")

    def eligible(record: ResearchRecord) -> bool:
        is_product = record.metric.startswith(("product_revenue:", "product_cost:"))
        unit = "元" if is_product else expected_units.get(record.metric)
        scope = "segment:product" if is_product or record.metric == "business_composition" else "consolidated"
        return bool(record.period_end and record.period_end <= as_of
            and (not record.published_at or record.published_at <= as_of)
            and not record.issues and unit and record.unit == unit and record.scope == scope
            and record.currency == "CNY" and type(record.value) in (int, float)
            and math.isfinite(record.value)
            and (record.metric != "pb" or record.value > 0)
            and (unit != "%" or 0 <= record.value <= 100 or record.metric == "roe"))

    def unique_index(pairs):
        result, duplicates = {}, set()
        for key, record in pairs:
            if key in result:
                duplicates.add(key)
            result[key] = record
        return {key: record for key, record in result.items() if key not in duplicates}

    records = [record for record in dataset.all_records() if eligible(record)]
    index = unique_index(((r.entity_name, r.metric, r.period_end), r)
                         for r in records if r.period_type == "annual")
    requirements, results = [], []
    required = [[] for _ in REQUIREMENTS]
    for metric, _, _ in list(MARKET_FIELDS.values())[:2]:
        required[0].extend((f"{year} {metric}", index.get(("中国", metric, date(year, 12, 31))))
                           for year in range(2021, 2026))
    for target, companies, metric, start, period_type in (
        (1, ["中国"], MARKET_FIELDS["penetration"][0], 202102, "month"),
        (2, VEHICLES, "pb", 202101, "point"),
    ):
        for name in companies:
            observed = unique_index((r.period_end.year * 100 + r.period_end.month, r) for r in records
                                    if r.entity_name == name and r.metric == metric and r.period_type == period_type)
            required[target].extend((f"{name} {ym} {metric}", observed.get(ym))
                                    for year in range(2021, 2026) for month in range(1, 13)
                                    if (ym := year * 100 + month) >= start)
    for target, names, measures in (
        (2, VEHICLES, [(metric, year) for year in (2023, 2024, 2025)
                       for metric in ("revenue", "gross_margin", "operating_cash_flow", "parent_net_profit")]
                      + [("roe", 2025), ("debt_ratio", 2025)]),
        (3, [name for name, _ in COMPANIES.values()], [(metric, 2025) for metric in
            ("business_composition", "rd_expense", "gross_margin", "operating_cash_flow", "revenue")]),
        (4, ["比亚迪"], [("revenue", 2025)] + [(f"{metric}:{product}", 2025)
            for product in BYD_PRODUCTS.values() for metric in ("product_revenue", "product_cost")]),
    ):
        required[target].extend((f"{name} {year} {metric}", index.get((name, metric, date(year, 12, 31))))
                                for name in names for metric, year in measures)

    for (key, (label, domain)), rows in zip(REQUIREMENTS.items(), required):
        ids = list(dict.fromkeys(r.record_id for _, r in rows if r is not None))
        missing = [label for label, record in rows if record is None]
        if key == "nev_byd_product_mix" and not missing:
            values = {r.metric: r.value for _, r in rows}
            if round(sum(values[f"product_revenue:{name}"] for name in BYD_PRODUCTS.values()), 2) != values["revenue"]:
                missing.append("比亚迪分产品收入合计与合并营业收入不一致")
        requirements.append(ResearchRequirement(requirement_id=key, label=label, domain=domain,
            min_records=len(rows), requires_period_end=True,
            expected_metric_groups=[[metric] for metric in dict.fromkeys(
                r.metric for _, r in rows if r is not None and not r.metric.startswith("product_")
            )]))
        results.append(RequirementCoverage(requirement_id=key, label=label, domain=domain, hard=True,
            passed=not missing, evidence_count=len(ids), evidence_record_ids=ids, missing=missing))
    return requirements, results


def verified_run(run_id: str, as_of: date) -> ResearchRunResult:
    try:
        dataset = StructuredResearchDataset.model_validate_json(DATASET_PATH.read_bytes())
    except FileNotFoundError:
        dataset = StructuredResearchDataset(subject="新能源汽车")
    dataset.research_as_of = as_of
    requirements, checks = _verify(dataset, as_of)
    dataset.quality_summary.update(
        data_source="iwencai_verified_capture",
        requirement_evidence_matrix=[
            {"requirement": r.model_dump(mode="json"), "coverage": c.model_dump(mode="json")}
            for r, c in zip(requirements, checks)
        ],
        requested_requirement_coverage=[c.model_dump(mode="json") for c in checks],
    )
    complete = all(c.passed for c in checks)
    domains = list(dict.fromkeys(r.domain for r in requirements))
    missing = list(dict.fromkeys(c.domain for c in checks if not c.passed))
    return ResearchRunResult(
        run_id=run_id, status="completed" if complete else "blocked",
        stop_reason="coverage_complete" if complete else "nev_required_evidence_missing",
        dataset=dataset, model_requirements=requirements,
        coverage=Coverage(required_domains=domains, covered_domains=[d for d in domains if d not in missing],
            missing_domains=missing, complete=complete, score=sum(c.passed for c in checks)/len(checks),
            requirement_coverage=checks),
        errors=[RunError(stage="data_fetch", message=f"{c.label}缺少 {len(c.missing)} 项，首项：{c.missing[0]}")
                for c in checks if not c.passed],
    )
