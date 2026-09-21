"""Deterministic fusion of raw SkillHub records into the research dataset."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from hashlib import sha256
import json
import re
from typing import Any

from data_fetcher.models import (
    ConflictRecord,
    Domain,
    ResearchRecord,
    SkillResult,
    SourceRef,
    StructuredResearchDataset,
)


ENTITY_CODE_KEYS = ("股票代码", "证券代码", "代码", "stock_code", "symbol", "code")
ENTITY_NAME_KEYS = ("股票简称", "证券简称", "公司简称", "公司名称", "名称", "company_name")
PERIOD_KEYS = ("报告期", "报告日期", "截止日期", "period_end", "REPORT_DATE")
PUBLISHED_KEYS = (
    "发布日期", "公告日期", "发布时间", "publish_date", "published_at", "publish_time", "date"
)
METADATA_KEYS = set(ENTITY_CODE_KEYS + ENTITY_NAME_KEYS + PERIOD_KEYS + PUBLISHED_KEYS) | {
    "来源", "source", "链接", "url", "研报链接", "新闻链接", "document_url",
    "宏观@id", "指标名称", "指标单位", "指标类型", "频度", "数据来源", "国家", "地区",
}

METRIC_NAMES = {
    "营业收入": "revenue",
    "营业总收入": "revenue",
    "营收": "revenue",
    "主营业务收入": "revenue",
    "净利润": "net_profit",
    "归属于母公司所有者的净利润": "parent_net_profit",
    "归属于母公司股东的净利润": "parent_net_profit",
    "归母净利润": "parent_net_profit",
    "扣除非经常性损益后的净利润": "deducted_net_profit",
    "扣非净利润": "deducted_net_profit",
    "毛利率": "gross_margin",
    "销售毛利率": "gross_margin",
    "综合毛利率": "gross_margin",
    "净利率": "net_margin",
    "销售净利率": "net_margin",
    "净资产收益率": "roe",
    "加权净资产收益率": "roe",
    "摊薄净资产收益率": "roe",
    "ROE": "roe",
    "资产负债率": "debt_ratio",
    "经营活动产生的现金流量净额": "operating_cash_flow",
    "经营现金流": "operating_cash_flow",
    "经营活动现金流量净额": "operating_cash_flow",
    "投资活动产生的现金流量净额": "investing_cash_flow",
    "筹资活动产生的现金流量净额": "financing_cash_flow",
    "现金及现金等价物净增加额": "net_cash_flow",
    "研发费用": "rd_expense",
    "研发投入": "rd_expense",
    "研发费用占营业收入的比例": "rd_ratio",
    "研发投入占营业收入比例": "rd_ratio",
    "总市值": "market_cap",
    "市值": "market_cap",
    "流通市值": "circulating_market_cap",
    "市盈率": "pe",
    "市盈率(pe)": "pe",
    "市盈率(动)": "pe_ttm",
    "市盈率(静)": "pe_lyr",
    "市盈率(ttm)": "pe_ttm",
    "市净率": "pb",
    "市净率(pb)": "pb",
    "市销率": "ps",
    "市销率(ps)": "ps",
    "基本每股收益": "eps",
    "每股收益": "eps",
    "每股净资产": "bps",
    "每股经营现金流": "cfps",
    "货币资金": "monetary_funds",
    "总资产": "total_assets",
    "资产总计": "total_assets",
    "总负债": "total_liabilities",
    "负债合计": "total_liabilities",
    "净资产": "total_equity",
    "所有者权益合计": "total_equity",
    "流动比率": "current_ratio",
    "速动比率": "quick_ratio",
    "行业名称": "industry_name",
    "行业估值": "industry_valuation",
    "主营业务": "main_business",
    "主营构成": "business_composition",
    "产业链环节": "chain_segment",
    "研报": "report_title",
    "研报标题": "report_title",
    "标题": "title",
    "最新价": "latest_price",
    "收盘价": "close_price",
    "涨跌幅": "change_pct",
    "涨跌幅:前复权": "change_pct",
    "区间涨跌幅": "period_change_pct",
    "区间涨跌幅:前复权": "period_change_pct",
    "概念解析": "concept_detail",
    "所属概念": "concept_name",
}


def _first(record: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return value
    return None


def _parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            timestamp = float(value)
            if timestamp > 10_000_000_000:
                timestamp /= 1000
            return datetime.fromtimestamp(timestamp).date()
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    # 1. Full date: YYYY-MM-DD, YYYY/MM/DD, YYYYMMDD
    match = re.search(r"(20\d{2})[-/.年]?([01]?\d)[-/.月]?([0-3]\d)", text)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            pass
    # 2. Quarterly dates: Q1/Q2/Q3/Q4, 一季报/中报/半年报/三季报/年报
    q_match = re.search(r"(20\d{2})[-/.年\s]*(?:(?:第?([1-4])季[度报]?)|([一二三四])季[度报]?|(Q[1-4])|(中报|半年报)|(年报))", text, re.I)
    if q_match:
        y = int(q_match.group(1))
        q_tag = (q_match.group(2) or q_match.group(3) or q_match.group(4) or q_match.group(5) or q_match.group(6) or "").upper()
        if any(x in q_tag for x in ("1", "一", "Q1")):
            return date(y, 3, 31)
        if any(x in q_tag for x in ("2", "二", "Q2", "中报", "半年报")):
            return date(y, 6, 30)
        if any(x in q_tag for x in ("3", "三", "Q3")):
            return date(y, 9, 30)
        if any(x in q_tag for x in ("4", "四", "Q4", "年报")):
            return date(y, 12, 31)
    # 3. Year-month: YYYY-MM, YYYY.MM, YYYY/MM
    ym_match = re.search(r"\b(20\d{2})[-/.年](0[1-9]|1[0-2])(?:月)?\b", text)
    if ym_match:
        y, m = int(ym_match.group(1)), int(ym_match.group(2))
        last_days = [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
        return date(y, m, last_days[m - 1])
    # 4. Pure year: 2024, 2024年
    y_match = re.search(r"\b(20\d{2})年?\b", text)
    if y_match:
        return date(int(y_match.group(1)), 12, 31)
    return None


def _standard_code(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip().upper()
    matched = re.search(r"(?<!\d)(\d{6})(?:\.(SZ|SH|BJ))?(?!\d)", text)
    if matched:
        digits, suffix = matched.groups()
        if not suffix:
            suffix = "SH" if digits.startswith(("6", "9")) else "BJ" if digits.startswith(("4", "8")) else "SZ"
        return f"{digits}.{suffix}"
    hk = re.fullmatch(r"(?:HK)?(\d{1,5})(?:\.HK)?", text)
    if hk and len(hk.group(1)) <= 5:
        return f"{hk.group(1).zfill(5)}.HK"
    us = re.fullmatch(r"([A-Z]{1,5})(?:\.US)", text)
    return f"{us.group(1)}.US" if us else None


def _split_value_unit(value: Any) -> tuple[Any, str | None]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value, None
    if not isinstance(value, str):
        return value, None
    text = value.strip().replace(",", "")
    match = re.fullmatch(r"([-+]?\d+(?:\.\d+)?)\s*(万亿元|亿元|万元|万|亿|元|%|倍|家|只|人|台|辆|万辆|套|吨|万吨)?", text)
    if not match:
        return value, None
    number = float(match.group(1))
    unit = match.group(2)
    multipliers = {"万亿元": 1e12, "亿元": 1e8, "万元": 1e4, "万": 1e4, "亿": 1e8}
    if unit in multipliers:
        return number * multipliers[unit], "元"
    if unit in ("万辆", "万吨"):
        return number * 1e4, unit.replace("万", "")
    return number, unit


def _canonical_metric(raw_key: str) -> str:
    without_period = re.sub(r"[\[［].*?[\]］]", "", raw_key).strip()
    return METRIC_NAMES.get(without_period, without_period)


def _period_from_key(key: str) -> date | None:
    match = re.search(r"[\[［](.*?)[\]］]", key)
    return _parse_date(match.group(1)) if match else None


def _record_id(parts: list[Any]) -> str:
    encoded = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return "R-" + sha256(encoded).hexdigest()[:20]


class DataFusion:
    """Pure fusion engine; it never calls an LLM or an external data source."""

    def fuse(self, results: list[SkillResult], as_of: date) -> StructuredResearchDataset:
        dataset = StructuredResearchDataset()
        seen_record_ids: set[str] = set()
        seen_companies: set[str] = set()
        dropped_future = 0
        exact_duplicates = 0
        failed_results = 0

        for result in results:
            source_base = SourceRef(
                task_id=result.task_id,
                skill_id=result.skill_id,
                skill_version=result.skill_version,
                query=result.query,
                trace_id=result.trace_id,
                retrieved_at=result.retrieved_at,
            )
            dataset.sources.append(source_base)
            if not result.success:
                failed_results += 1
                continue

            for raw_index, raw in enumerate(result.records):
                source = source_base.model_copy(update={"raw_record_index": raw_index})
                entity_name_value = _first(raw, ENTITY_NAME_KEYS)
                entity_name = str(entity_name_value).strip() if entity_name_value else None
                entity_code = _standard_code(_first(raw, ENTITY_CODE_KEYS))
                period = _parse_date(_first(raw, PERIOD_KEYS))
                published = _parse_date(_first(raw, PUBLISHED_KEYS))
                if (published and published > as_of) or (period and period > as_of):
                    dropped_future += 1
                    continue

                if entity_name or entity_code:
                    company_key = entity_code or entity_name or ""
                    if company_key not in seen_companies:
                        company_record = ResearchRecord(
                            record_id=_record_id(["company", company_key, result.skill_id, raw_index]),
                            domain=Domain.COMPANIES,
                            entity_name=entity_name,
                            entity_code=entity_code,
                            metric="entity_identity",
                            value=entity_name or entity_code,
                            period_end=period,
                            published_at=published,
                            source=source,
                            raw_fields=raw,
                            issues=[] if entity_code else ["missing_entity_code"],
                        )
                        dataset.companies.append(company_record)
                        seen_companies.add(company_key)

                macro_name = raw.get("指标名称") or raw.get("指标")
                macro_unit = raw.get("指标单位")
                if result.domain == Domain.MACRO and not entity_name:
                    entity_name = "宏观"

                metrics = [(key, value) for key, value in raw.items() if key not in METADATA_KEYS]
                if not metrics:
                    metrics = [("record", raw)]
                for raw_key, raw_value in metrics:
                    raw_key_str = str(raw_key)
                    if macro_name and ("宏观@值" in raw_key_str or "@值" in raw_key_str):
                        metric = str(macro_name).strip()
                    else:
                        metric = _canonical_metric(raw_key_str)
                    value, unit = _split_value_unit(raw_value)
                    if not unit and macro_unit and result.domain == Domain.MACRO:
                        unit = str(macro_unit).strip()
                    metric_period = _period_from_key(str(raw_key)) or period
                    if metric_period and metric_period > as_of:
                        dropped_future += 1
                        continue
                    issues: list[str] = []
                    if metric_period is None and result.domain in (Domain.FINANCIALS, Domain.MACRO):
                        issues.append("missing_period_end")
                    if published is None and result.domain in (Domain.REPORTS, Domain.NEWS):
                        issues.append("missing_published_at")
                    record_id = _record_id([
                        result.domain.value, entity_code or entity_name, metric, metric_period,
                        published, result.skill_id, value,
                    ])
                    if record_id in seen_record_ids:
                        exact_duplicates += 1
                        continue
                    seen_record_ids.add(record_id)
                    item = ResearchRecord(
                        record_id=record_id,
                        domain=result.domain,
                        entity_name=entity_name,
                        entity_code=entity_code,
                        metric=metric,
                        value=value,
                        unit=unit,
                        period_end=metric_period,
                        published_at=published,
                        source=source,
                        raw_fields=raw,
                        issues=issues,
                    )
                    dataset.records_for(result.domain).append(item)

        dataset.sources = list({
            (source.task_id, source.trace_id): source for source in dataset.sources
        }.values())
        dataset.conflicts = self._find_conflicts(dataset)
        dataset.quality_summary = {
            "successful_skill_calls": sum(1 for result in results if result.success),
            "failed_skill_calls": failed_results,
            "raw_record_count": sum(len(result.records) for result in results if result.success),
            "structured_record_count": sum(
                len(dataset.records_for(domain)) for domain in Domain
            ),
            "dropped_future_records": dropped_future,
            "exact_duplicates_removed": exact_duplicates,
            "conflict_count": len(dataset.conflicts),
            "records_with_issues": sum(
                1 for domain in Domain for record in dataset.records_for(domain) if record.issues
            ),
        }
        return dataset

    def _find_conflicts(self, dataset: StructuredResearchDataset) -> list[ConflictRecord]:
        grouped: dict[tuple[str, str, date | None], list[ResearchRecord]] = defaultdict(list)
        for domain in Domain:
            if domain == Domain.COMPANIES:
                continue
            for record in dataset.records_for(domain):
                entity = record.entity_code or record.entity_name
                if not entity and domain in (Domain.REPORTS, Domain.NEWS):
                    entity = next(
                        (
                            str(record.raw_fields[key])
                            for key in ("id", "uid", "url", "title", "标题", "研报标题")
                            if record.raw_fields.get(key) not in (None, "")
                        ),
                        None,
                    )
                entity = entity or domain.value
                grouped[(entity, record.metric, record.period_end or record.published_at)].append(record)

        conflicts: list[ConflictRecord] = []
        for (entity, metric, period), records in grouped.items():
            distinct = {json.dumps(record.value, ensure_ascii=False, sort_keys=True, default=str) for record in records}
            sources = {record.source.skill_id for record in records}
            if len(distinct) > 1 and len(sources) > 1:
                key = _record_id([entity, metric, period])
                conflicts.append(ConflictRecord(
                    conflict_key=key,
                    entity=entity,
                    metric=metric,
                    period=period,
                    values=[record.value for record in records],
                    record_ids=[record.record_id for record in records],
                ))
        return conflicts
