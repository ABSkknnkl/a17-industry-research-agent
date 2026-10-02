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
    EventRecord,
    ResearchRecord,
    SkillResult,
    SourceRef,
    StructuredResearchDataset,
)


ENTITY_CODE_KEYS = (
    "股票代码", "证券代码", "代码", "成分代码", "stock_code", "symbol", "code",
    "指数代码", "板块代码", "行业代码", "index_code",
)
ENTITY_NAME_KEYS = (
    "股票简称", "证券简称", "公司简称", "公司名称", "成分简称", "成分名称", "名称", "company_name",
    "指数简称", "板块名称", "板块简称", "行业名称", "指数名称", "index_name",
)
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
    "最新总市值": "market_cap",
    "市值": "market_cap",
    "流通市值": "circulating_market_cap",
    "最新a股流通市值": "circulating_market_cap",
    "a股流通市值": "circulating_market_cap",
    "市盈率": "pe",
    "最新动态市盈率": "pe_ttm",
    "动态市盈率": "pe_ttm",
    "最新静态市盈率": "pe_lyr",
    "静态市盈率": "pe_lyr",
    "市盈率(pe)": "pe",
    "市盈率(动)": "pe_ttm",
    "市盈率(静)": "pe_lyr",
    "市盈率(ttm)": "pe_ttm",
    "最新市净率": "pb",
    "市净率": "pb",
    "市净率(pb)": "pb",
    "市销率": "ps",
    "市销率(ps)": "ps",
    "所属同花顺行业": "industry_name",
    "所属行业": "industry_name",
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
    for k, v in record.items():
        if v in (None, ""):
            continue
        clean_k = re.sub(r"[\[［@].*?[\]］]?", "", k).strip()
        if clean_k in keys:
            return v
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
    matched = re.search(r"(?<!\d)(\d{6})(?:\.(SZ|SH|BJ|TI|CSI|SSI))?(?!\d)", text)
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
        return round(number * multipliers[unit], 4), "元"
    if unit in ("万辆", "万吨"):
        return round(number * 1e4, 4), unit.replace("万", "")
    return number, unit


def _canonical_metric(raw_key: str) -> str:
    without_period = re.sub(r"[\[［].*?[\]］]", "", raw_key).strip()
    if without_period in METRIC_NAMES:
        return METRIC_NAMES[without_period]
    without_unit = re.sub(r"[\(（].*?[\)）]", "", without_period).strip()
    return METRIC_NAMES.get(without_unit, without_period)


def _period_from_key(key: str) -> date | None:
    match = re.search(r"[\[［](.*?)[\]］]", key)
    return _parse_date(match.group(1)) if match else None


def _record_id(parts: list[Any]) -> str:
    encoded = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return "R-" + sha256(encoded).hexdigest()[:20]


def _is_target_entity_match(target_entity: str, record_entity: str) -> bool:
    """Checks whether the record entity name is consistent with the queried target entity."""
    if not target_entity or not record_entity:
        return True
    t = target_entity.strip().lower()
    r = record_entity.strip().lower()
    if t == r:
        return True
    clean_t = re.sub(r"(股份有限公司|有限责任公司|有限公司|集团|控股|股份)$", "", t)
    clean_r = re.sub(r"(股份有限公司|有限责任公司|有限公司|集团|控股|股份)$", "", r)
    if clean_t in clean_r or clean_r in clean_t:
        return True
    if len(clean_t) >= 2 and clean_r.startswith(clean_t[:2]):
        return True
    return False


def _is_record_relevant_to_query(query: str, entity_name: str | None, entity_code: str | None) -> bool:
    """Checks whether a record returned from a single-company skill query is actually relevant.

    Iwencai API falls back to broad semantic search when an exact A-share ticker is not found
    (e.g. querying US-listed '亿航智能' returns A-share '同仁堂', '万科A').
    This guard rejects such unrelated companies.
    """
    if not query or not (entity_name or entity_code):
        return True

    q = query.strip()
    if entity_name and entity_name.strip() in q:
        return True
    if entity_code and entity_code.strip().split(".")[0] in q:
        return True

    tokens = q.split()
    if len(tokens) >= 2:
        target = tokens[0].strip()
        # If the target is an industry/concept/general phrase, do not filter as a single company query
        if any(k in target for k in ("测试", "测试查询", "查询", "获取", "调取", "请问", "近3年", "近5年", "行业", "经济", "概念", "产业", "赛道", "板块", "上市公司", "选股")):
            return True
        if entity_name and _is_target_entity_match(target, entity_name):
            return True
        return False

    return True


SINGLE_ENTITY_SKILLS = {
    "hithink-basicinfo-query",
    "hithink-finance-query",
    "hithink-business-query",
    "hithink-management-query",
}


# ── 类D(P-06): 事件/公告结构化抽取常量 ──────────────────────────────────────
EVENT_SOURCE_SKILLS = frozenset({"announcement-search", "hithink-event-query"})
EVENT_TYPE_KEYS = ("事件类型", "事件类别", "公告类型", "event_type")
EVENT_TITLE_KEYS = ("公告标题", "公告名称", "事件标题", "标题", "title")
EVENT_DATE_KEYS = ("公告日期", "发布日期", "事件日期", "公布日期", "publish_date", "publish_time",
                   "announce_date", "announcement_date")
EVENT_BODY_KEYS = ("公告内容", "公告摘要", "事件内容", "事件描述", "内容", "摘要", "summary",
                   "source_original", "body", "snippet")
EVENT_CONSUMABLE_KEYS = frozenset(EVENT_TYPE_KEYS + EVENT_TITLE_KEYS + EVENT_DATE_KEYS + EVENT_BODY_KEYS)

# 公告/资讯检索型返回的元数据键（channel/id/url/score/stock_infos…）不构成指标，
# 实测 announcement-search 每条返回 22 个字段中约 17 个属于此类——不消费会在 news 域产垃圾碎片。
EVENT_RETRIEVAL_METADATA_KEYS = frozenset({
    "channel", "id", "uid", "index", "score", "extra", "name", "status",
    "data_source", "source_original", "para_index", "stock_infos",
    "traceability_type", "trace_info", "site_authority", "modify_time",
    "operation_type", "publish_time", "publish_date", "url", "doc_type", "content",
})
EVENT_CONSUMED_ALL = EVENT_CONSUMABLE_KEYS | EVENT_RETRIEVAL_METADATA_KEYS

# event_type 缺失时的确定性推断规则（按序匹配标题/内容关键词；fusion 不调 LLM，见类 docstring）
_EVENT_TYPE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("业绩预告", ("业绩预增", "业绩预减", "业绩预告", "预盈", "预亏", "扭亏")),
    ("股权激励", ("股权激励", "限制性股票", "股票期权", "员工持股计划")),
    ("增发配股", ("增发", "配股", "定增", "非公开发行")),
    ("回购增持", ("回购", "增持")),
    ("分红派息", ("分红", "派息", "利润分配", "送转")),
    ("资产重组", ("重组", "并购", "收购", "重大资产")),
    ("股权质押", ("质押", "解押")),
    ("限售解禁", ("解禁", "限售股上市")),
    ("机构调研", ("调研", "接待机构")),
    ("监管函件", ("问询函", "关注函", "警示函", "监管函", "监管措施")),
    ("重大合同", ("中标", "重大合同", "签订合同")),
    ("股东大会", ("股东大会",)),
    ("高管变动", ("辞职", "聘任", "离任", "高管变动")),
)


def _infer_event_type(*texts: str | None) -> str | None:
    blob = "".join(t for t in texts if t)
    if not blob:
        return None
    for etype, keywords in _EVENT_TYPE_RULES:
        if any(kw in blob for kw in keywords):
            return etype
    return None


def _is_entity_excluded(
    entity_name: str | None,
    raw: dict[str, Any],
    clean_excluded: set[str],
    clean_must: set[str],
) -> bool:
    """Detect whether a record belongs to an explicitly excluded industry sector.

    Protects against semantic query drift, overly broad NLP matches, or disjunction leakage.
    """
    if not clean_excluded or not entity_name:
        return False
    if entity_name in clean_must:
        return False

    # 1. 检查 raw_fields 中明确标注的行业属性
    for key in ("所属同花顺行业", "所属行业", "行业名称", "同花顺行业", "申万行业", "一级行业", "二级行业", "行业"):
        val = raw.get(key)
        if val and isinstance(val, str):
            for ex in clean_excluded:
                if ex and ex in val:
                    return True

    # 2. 检查名称与常见行业大类的强语义绑定（当 raw 中无行业字段时的兜底防线）
    if any(ex in ("银行", "银行业") for ex in clean_excluded):
        if entity_name.endswith("银行") or entity_name in ("工行", "建行", "农行", "中行", "交行", "招行", "邮储银行"):
            return True
    if any(ex in ("石油", "石油石化", "采掘") for ex in clean_excluded):
        if entity_name in ("中国石油", "中国石化", "中国海油", "中海油服", "中石油", "中石化"):
            return True
    if any(ex in ("白酒", "食品饮料") for ex in clean_excluded):
        if entity_name in ("贵州茅台", "五粮液", "泸州老窖", "山西汾酒", "洋河股份"):
            return True
    if any(ex in ("房地产", "地产") for ex in clean_excluded):
        if entity_name in ("万科A", "保利发展", "招商蛇口", "金地集团", "新城控股"):
            return True
    return False


class DataFusion:
    """Pure fusion engine; it never calls an LLM or an external data source."""

    def fuse(
        self,
        results: list[SkillResult],
        as_of: date,
        *,
        excluded_industries: list[str] | None = None,
        must_include_entities: list[str] | None = None,
    ) -> StructuredResearchDataset:
        clean_excluded = {ind.strip() for ind in (excluded_industries or []) if ind and ind.strip()}
        clean_must = {ent.strip() for ent in (must_include_entities or []) if ent and ent.strip()}

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
                status="success" if result.success else "failed",
                record_count=len(result.records) if result.success else 0,
            )
            dataset.sources.append(source_base)
            if not result.success:
                failed_results += 1
                continue

            is_single_entity_skill = result.skill_id in SINGLE_ENTITY_SKILLS

            for raw_index, raw in enumerate(result.records):
                source = source_base.model_copy(update={"raw_record_index": raw_index})
                entity_name_value = _first(raw, ENTITY_NAME_KEYS)
                entity_name = str(entity_name_value).strip() if entity_name_value else None
                entity_code = _standard_code(_first(raw, ENTITY_CODE_KEYS))

                # Guard against iwencai semantic fallback / irrelevant company mismatch
                if is_single_entity_skill and not _is_record_relevant_to_query(result.query, entity_name, entity_code):
                    continue

                # Guard against records from explicitly excluded industry sectors
                if clean_excluded and _is_entity_excluded(entity_name, raw, clean_excluded, clean_must):
                    continue

                period = _parse_date(_first(raw, PERIOD_KEYS))
                published = _parse_date(_first(raw, PUBLISHED_KEYS))
                if (published and published > as_of) or (period and period > as_of):
                    dropped_future += 1
                    continue

                if entity_name or entity_code:
                    # 指数代码 (如 .TI, .CSI, .SSI) 或来自行业领域的板块指数实体，不作为个股公司录入
                    is_index_entity = (
                        (entity_code and any(entity_code.endswith(sfx) for sfx in (".TI", ".CSI", ".SSI")))
                        or (result.domain == Domain.INDUSTRY and any(k in raw for k in ("指数代码", "指数简称", "板块代码", "板块名称")))
                    )
                    if not is_index_entity:
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

                # Specialized atomic parsing for macro tabular records
                if result.domain == Domain.MACRO and any(k in raw for k in ("指标值", "数值", "value")):
                    val_raw = raw.get("指标值") if "指标值" in raw else (raw.get("数值") if "数值" in raw else raw.get("value"))
                    val, parsed_u = _split_value_unit(val_raw)
                    m_name = str(raw.get("指标") or raw.get("macro_name") or raw.get("指标名称") or "宏观指标").strip()
                    m_unit = parsed_u or str(raw.get("单位") or raw.get("指标单位") or "元").strip()
                    m_date = _parse_date(raw.get("时间") or raw.get("日期") or raw.get("period"))
                    m_ent = str(raw.get("国家") or raw.get("地区") or entity_name or "全国").strip()

                    if m_date and m_date > as_of:
                        dropped_future += 1
                        continue

                    compact_raw = raw
                    if len(raw) > 15:
                        ident_keys = ("指标名称", "指标", "macro_name", "单位", "指标单位", "时间", "日期", "period", "国家", "地区")
                        compact_raw = {k: raw[k] for k in ident_keys if k in raw}
                        if val_raw is not None:
                            compact_raw["指标值"] = val_raw

                    rec = ResearchRecord(
                        record_id=_record_id(["macro", m_ent, m_name, str(m_date), raw_index]),
                        domain=Domain.MACRO,
                        entity_name=m_ent,
                        entity_code=None,
                        metric=m_name,
                        value=val,
                        unit=m_unit,
                        period_end=m_date,
                        published_at=published or m_date,
                        source=source,
                        raw_fields=compact_raw,
                        issues=[] if m_date else ["missing_period_end"],
                    )
                    dataset.macro.append(rec)
                    continue

                macro_name = raw.get("指标名称") or raw.get("指标")
                macro_unit = raw.get("指标单位")
                if result.domain == Domain.MACRO and not entity_name:
                    entity_name = "宏观"

                # ── 类D(P-06): 事件/公告记录走独立结构化通道 ──
                # 识别条件：raw 含事件类型键，或来自事件类技能且带标题/正文（公告型返回）。
                # 实测 hithink-event-query 在部分 query 下返回行情型字段（最新价/涨跌幅），
                # 无任何事件要素 → 不产事件记录，完全落回通用指标拆分，避免空壳事件污染。
                # 数值字段（如"增发数量"）不在此 continue，仍走下方通用拆分保留为指标。
                is_event_source = result.skill_id in EVENT_SOURCE_SKILLS
                raw_event_type = _first(raw, EVENT_TYPE_KEYS)
                event_title = _first(raw, EVENT_TITLE_KEYS)
                event_body = _first(raw, EVENT_BODY_KEYS)
                has_event_signal = bool(raw_event_type) or (
                    is_event_source and (event_title or event_body)
                )
                consumed_event_keys: frozenset[str] = frozenset()
                if has_event_signal:
                    # 公告检索型返回的实体在 stock_infos[] 中，且首个元素常只有内部证券代码
                    # （如 [{"code":"CYATY"},…,{"name":"宁德时代","code":"300750"}]）→ 遍历取首个带名称项
                    if not (entity_name or entity_code):
                        stock_infos = raw.get("stock_infos")
                        if isinstance(stock_infos, list):
                            for info in stock_infos:
                                if not isinstance(info, dict):
                                    continue
                                info_name = info.get("name") or info.get("股票简称")
                                if not info_name:
                                    continue
                                entity_name = str(info_name).strip()
                                code_raw = info.get("code") or info.get("股票代码")
                                if code_raw:
                                    entity_code = _standard_code(code_raw)
                                break
                    announce_date = _parse_date(_first(raw, EVENT_DATE_KEYS) or published)
                    etype = (
                        str(raw_event_type).strip()
                        if raw_event_type not in (None, "")
                        else _infer_event_type(
                            str(event_title) if event_title else None,
                            str(event_body) if event_body else None,
                        )
                    )
                    if announce_date and announce_date > as_of:
                        dropped_future += 1
                        continue
                    event_issues: list[str] = []
                    if event_title in (None, ""):
                        event_issues.append("missing_title")
                    if not etype:
                        event_issues.append("missing_event_type")
                    if announce_date is None:
                        event_issues.append("missing_announce_date")
                    event_id = _record_id([
                        "event", entity_code or entity_name, etype, announce_date,
                        str(event_title) if event_title else None, result.skill_id,
                    ])
                    if event_id not in seen_record_ids:
                        dataset.events.append(EventRecord(
                            record_id=event_id,
                            entity_name=entity_name,
                            entity_code=entity_code,
                            title=str(event_title).strip() if event_title else None,
                            event_type=etype,
                            announce_date=announce_date,
                            body=str(event_body).strip() if event_body else None,
                            source=source,
                            raw_fields=raw,
                            issues=event_issues,
                        ))
                        seen_record_ids.add(event_id)
                    consumed_event_keys = EVENT_CONSUMED_ALL

                metrics = [
                    (key, value) for key, value in raw.items()
                    if key not in METADATA_KEYS and key not in consumed_event_keys
                ]
                if not metrics:
                    if consumed_event_keys:
                        # 纯事件记录：EventRecord 已承载全部结构化信息，不再产碎片
                        continue
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

                    # 1. 尝试从 raw_key_str 中提取括号内的单位，如 "营业收入(元)" -> "元", "销售毛利率(%)" -> "%", "总市值(亿元)" -> "亿元"
                    if not unit:
                        unit_match = re.search(r"[\(（]([^\)）]+)[\)）]", raw_key_str)
                        if unit_match:
                            cand_unit = unit_match.group(1).strip()
                            if cand_unit in ("元", "亿元", "万元", "万", "亿", "%", "倍", "家", "只", "人", "台", "辆", "万辆", "套", "吨", "万吨"):
                                unit = cand_unit

                    # 2. 经典金融指标默认单位智能补齐
                    if not unit and isinstance(value, (int, float)) and not isinstance(value, bool):
                        metric_lower = metric.lower()
                        raw_key_lower = raw_key_str.lower()
                        # 2.1 估值倍数类（必须严格限定 token/边界，严禁模糊子串匹配导致 operating_cash_flow 命中 pe）
                        is_multiple = (
                            any(k in metric_lower or k in raw_key_lower for k in ("市盈率", "市净率", "市销率", "估值倍数"))
                            or bool(re.search(r"(^|[^a-z0-9])(pe|pb|ps|ev_ebitda)([^a-z0-9]|$)", metric_lower))
                            or bool(re.search(r"(^|[^a-z0-9])(pe|pb|ps|ev_ebitda)([^a-z0-9]|$)", raw_key_lower))
                            or metric_lower.startswith(("pe_", "pb_", "ps_"))
                            or metric_lower.endswith(("_pe", "_pb", "_ps"))
                        )
                        # 2.2 比率/百分比类（排除市盈率等倍数类指标，包含 yoy/qoq/cagr/增长率/margin 等）
                        is_ratio = not is_multiple and (
                            any(k in metric_lower or k in raw_key_lower for k in ("率", "占比", "同比", "环比", "增长率", "margin", "ratio", "yoy", "qoq", "cagr", "涨跌幅", "幅度"))
                            or bool(re.search(r"(^|[^a-z0-9])(roe|roa|roic)([^a-z0-9]|$)", metric_lower))
                            or bool(re.search(r"(^|[^a-z0-9])(roe|roa|roic)([^a-z0-9]|$)", raw_key_lower))
                        )
                        # 2.3 金额类（涵盖现金流、营业收支、资产负债等，排除比率和倍数）
                        is_monetary = not is_multiple and not is_ratio and (
                            result.domain in (Domain.FINANCIALS, Domain.INDUSTRY, Domain.COMPANIES, Domain.MACRO)
                            and any(k in metric_lower or k in raw_key_lower for k in ("revenue", "profit", "income", "cost", "cash", "expense", "assets", "liabilities", "equity", "flow", "capital", "收入", "利润", "资产", "负债", "成本", "市值", "资金", "现金", "净额", "总额", "产值"))
                        )

                        if is_multiple:
                            unit = "倍"
                        elif is_ratio:
                            unit = "%"
                        elif is_monetary:
                            unit = "元"

                    metric_period = _period_from_key(str(raw_key)) or period
                    if metric_period and metric_period > as_of:
                        dropped_future += 1
                        continue

                    # 3. 日间行情数据领域重定向与快照豁免
                    record_domain = result.domain
                    record_published = published
                    is_snapshot_market_data = any(k in metric.lower() or k in raw_key_str.lower() for k in ("latest_price", "change_pct", "close_price", "最新价", "最新涨跌幅", "收盘价"))
                    # 若为个股日间快照（来自财务或市场查询），且非指数代码，归入 COMPANIES 领域
                    is_stock_market_data = (
                        is_snapshot_market_data
                        and not (entity_code and any(entity_code.endswith(sfx) for sfx in (".TI", ".CSI", ".SSI")))
                        and not any(k in raw for k in ("指数代码", "指数简称", "板块代码", "板块名称"))
                    )
                    if is_stock_market_data and result.domain in (Domain.FINANCIALS, Domain.INDUSTRY):
                        record_domain = Domain.COMPANIES
                        if record_published is None:
                            record_published = as_of

                    issues: list[str] = []
                    if metric_period is None and record_domain in (Domain.FINANCIALS, Domain.MACRO) and not is_snapshot_market_data:
                        issues.append("missing_period_end")
                    if record_published is None and record_domain in (Domain.REPORTS, Domain.NEWS):
                        # D-05 修复②：时间敏感域（reports/news）源侧缺发布时点时，统一以检索基准日
                        # as_of 兜底填充 published_at，并保留 issue 留痕（标记源侧缺失、as_of 为检索日代理而非
                        # 真实发布时点。避免下游时间轴/时效判定因 None 而整条记录不可用（D3 覆盖度）。
                        issues.append("missing_published_at")
                        record_published = as_of

                    record_id = _record_id([
                        record_domain.value, entity_code or entity_name, metric, metric_period,
                        record_published, result.skill_id, value,
                    ])
                    if record_id in seen_record_ids:
                        exact_duplicates += 1
                        continue
                    compact_raw = raw
                    if len(raw) > 15:
                        ident_keys = ("股票代码", "股票简称", "指标名称", "指标单位", "时间", "日期", "行业名称", "国家", "地区")
                        compact_raw = {k: raw[k] for k in ident_keys if k in raw}
                        compact_raw[raw_key_str] = raw_value

                    item = ResearchRecord(
                        record_id=record_id,
                        domain=record_domain,
                        entity_name=entity_name,
                        entity_code=entity_code,
                        metric=metric,
                        value=value,
                        unit=unit,
                        period_end=metric_period,
                        published_at=record_published,
                        source=source,
                        raw_fields=compact_raw,
                        issues=issues,
                    )
                    dataset.records_for(record_domain).append(item)
                    seen_record_ids.add(record_id)

        # 挖掘 reports 中的结构化财务时序并反哺至 financials 库
        mined_financials = self._mine_financials_from_reports(
            dataset, as_of, clean_excluded=clean_excluded, clean_must=clean_must
        )
        if mined_financials:
            dataset.financials.extend(mined_financials)

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
            "event_count": len(dataset.events),
            "events_with_issues": sum(1 for ev in dataset.events if ev.issues),
        }
        return dataset

    def _mine_financials_from_reports(
        self,
        dataset: StructuredResearchDataset,
        as_of: date,
        clean_excluded: set[str] | None = None,
        clean_must: set[str] | None = None,
    ) -> list[ResearchRecord]:
        """Scans unstructured report text in dataset.reports to extract structured financial metrics.

        Bridges the cognitive disconnect between Stage 1/4 (which see reports) and Stage 2 (which analyzes financials).
        """
        mined: list[ResearchRecord] = []
        seen: set[tuple[str, str, date]] = set()

        existing_keys = {
            (r.entity_name or r.entity_code, r.metric, r.period_end)
            for r in dataset.financials
            if (r.entity_name or r.entity_code) and r.period_end
        }

        for report_rec in dataset.reports:
            raw = report_rec.raw_fields or {}
            text = str(raw.get("summary") or raw.get("source_original") or "")
            if not text:
                continue

            entity_name = report_rec.entity_name
            entity_code = report_rec.entity_code
            if not entity_name:
                stock_infos = raw.get("stock_infos")
                if stock_infos and isinstance(stock_infos, list) and isinstance(stock_infos[0], dict):
                    entity_name = stock_infos[0].get("name")
                    if not entity_code:
                        code_str = stock_infos[0].get("code")
                        entity_code = _standard_code(code_str) if code_str else None

            if not entity_name:
                # Try bullet point e.g.  宇树科技：A股人形机器人第一股
                m_bullet = re.search(r"[•·\-\*]?\s*([一-龥]{2,6}(?:科技|股份|电子|机器人|制造|精密|智造|动力|自动化|系统|有限公司|公司))[:：]", text)
                if m_bullet:
                    entity_name = m_bullet.group(1)

            if not entity_name:
                title = str(raw.get("title") or "")
                title_match = re.match(r"^([^\s（(：:]{2,10})[（(]", title)
                if title_match:
                    entity_name = title_match.group(1)
                else:
                    m_title = re.search(r"([一-龥]{2,6}(?:科技|股份|电子|制造|精密|智造|动力|自动化|系统))", title)
                    if m_title:
                        entity_name = m_title.group(1)

            if entity_name and entity_name.startswith("从"):
                entity_name = entity_name[1:]

            if not entity_name:
                continue

            if clean_excluded and _is_entity_excluded(entity_name, raw, clean_excluded, clean_must or set()):
                continue

            def add_record(metric: str, raw_val_str: str, period: date, snippet: str):
                if period > as_of:
                    return
                key = (entity_name, metric, period)
                if key in seen or key in existing_keys:
                    return
                seen.add(key)
                val, unit = _split_value_unit(raw_val_str)
                rec_id = _record_id(["mined_fin", entity_name, metric, period.isoformat(), val])
                mined.append(ResearchRecord(
                    record_id=rec_id,
                    domain=Domain.FINANCIALS,
                    entity_name=entity_name,
                    entity_code=entity_code,
                    metric=metric,
                    value=val,
                    unit=unit,
                    period_end=period,
                    published_at=report_rec.published_at or as_of,
                    source=SourceRef(
                        task_id=report_rec.source.task_id,
                        skill_id="report-text-mining",
                        skill_version="1.0.0",
                        query=report_rec.source.query,
                        trace_id=report_rec.source.trace_id,
                        retrieved_at=report_rec.source.retrieved_at,
                    ),
                    raw_fields={"mined_snippet": snippet[:100], "source_report_title": str(raw.get("title") or "")},
                    issues=[],
                ))

            # 1. 营收跨期: 2022-2025年营收从1.23亿元增至16.99亿元
            m_rev_range = re.search(r"(\d{4})[—\-~至到](\d{4})\s*年(?:公司)?(?:营业收入|营收)(?:由|从)?\s*([0-9.]+)\s*(亿元|万|亿)?(?:增至|增长至|达到)?\s*([0-9.]+)\s*(亿元|万|亿)", text)
            if m_rev_range:
                y1, y2, v1, u1, v2, u2 = m_rev_range.groups()
                unit1 = u1 or u2 or "亿元"
                unit2 = u2 or u1 or "亿元"
                add_record("revenue", f"{v1}{unit1}", date(int(y1), 12, 31), m_rev_range.group(0))
                add_record("revenue", f"{v2}{unit2}", date(int(y2), 12, 31), m_rev_range.group(0))

            # 2. 单期营收与复合财务句: 2025年公司实现营收16.99亿元、扣非归母净利润5.91亿元...毛利率60.44%
            for m_s_rev in re.finditer(r"(\d{4})\s*年(?:公司)?(?:实现)?(?:营业收入|营收)\s*([0-9.]+)\s*(亿元|万|亿)", text):
                yr, val_str, u = m_s_rev.groups()
                add_record("revenue", f"{val_str}{u}", date(int(yr), 12, 31), m_s_rev.group(0))

                sub_sentence = text[m_s_rev.end():m_s_rev.end() + 150]
                m_sub_prof = re.search(r"^[、，,\s]*?(扣非归母净利润|扣非净利润|归母净利润|净利润)\s*([0-9.]+)\s*(亿元|万|亿)", sub_sentence)
                if m_sub_prof:
                    p_type, p_val, p_u = m_sub_prof.groups()
                    metric = "deducted_net_profit" if "扣非" in p_type else ("parent_net_profit" if "归母" in p_type else "net_profit")
                    add_record(metric, f"{p_val}{p_u}", date(int(yr), 12, 31), f"{m_s_rev.group(0)}{m_sub_prof.group(0)}")

                m_sub_gm = re.search(r"毛利率\s*([0-9.]+)%", sub_sentence)
                if m_sub_gm:
                    add_record("gross_margin", f"{m_sub_gm.group(1)}%", date(int(yr), 12, 31), m_sub_gm.group(0))

            # 3. 净利润跨期: 扣非归母净利润从-0.08亿元转正至5.91亿元
            m_prof_range = re.search(r"扣非(?:归母)?净利润(?:由|从)?\s*(-?[0-9.]+)\s*(亿元|万|亿)?(?:转正至|增至|增长至|达到)?\s*([0-9.]+)\s*(亿元|万|亿)", text)
            if m_prof_range and m_rev_range:
                y1, y2 = m_rev_range.group(1), m_rev_range.group(2)
                v1, u1, v2, u2 = m_prof_range.groups()
                unit1 = u1 or u2 or "亿元"
                unit2 = u2 or u1 or "亿元"
                add_record("deducted_net_profit", f"{v1}{unit1}", date(int(y1), 12, 31), m_prof_range.group(0))
                add_record("deducted_net_profit", f"{v2}{unit2}", date(int(y2), 12, 31), m_prof_range.group(0))

            # 4. 单期净利润: 2025年扣非归母净利润达到5.91亿元
            for m_prof in re.finditer(r"(\d{4})\s*年(?:公司)?(扣非归母净利润|扣非净利润|归母净利润|净利润)(?:达到|为|提升至)?\s*(-?[0-9.]+)\s*(亿元|万|亿)", text):
                yr, p_type, val_str, u = m_prof.groups()
                metric = "deducted_net_profit" if "扣非" in p_type else ("parent_net_profit" if "归母" in p_type else "net_profit")
                add_record(metric, f"{val_str}{u}", date(int(yr), 12, 31), m_prof.group(0))

            # 5. 毛利率: 2025年综合毛利率提升至60.44%
            for m_gm in re.finditer(r"(\d{4})\s*年(?:综合|销售)?毛利率(?:提升至|达到|为)?\s*([0-9.]+)%", text):
                yr, val_str = m_gm.groups()
                add_record("gross_margin", f"{val_str}%", date(int(yr), 12, 31), m_gm.group(0))

            # 5. 半年度/中报: 2026年上半年实现收入10.90亿元, 归母净利润2.82亿元
            m_h_rev = re.search(r"(\d{4})\s*年(?:上半年|H1)(?:预计)?(?:实现)?(?:收入|营收|营业收入)\s*([0-9.]+)\s*(亿元|万|亿)", text)
            if m_h_rev:
                yr, val_str, u = m_h_rev.groups()
                add_record("revenue", f"{val_str}{u}", date(int(yr), 6, 30), m_h_rev.group(0))

            m_h_prof = re.search(r"(\d{4})\s*年(?:上半年|H1)(?:预计)?(?:实现)?(?:归母净利润|净利润)\s*([0-9.]+)\s*(亿元|万|亿)", text)
            if m_h_prof:
                yr, val_str, u = m_h_prof.groups()
                add_record("parent_net_profit", f"{val_str}{u}", date(int(yr), 6, 30), m_h_prof.group(0))

        return mined

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
                # 针对价格、市值等实时市场指标，支持0.5%以内合理市场波动的容差消除，避免虚假冲突
                is_tolerable = False
                try:
                    num_vals = [float(record.value) for record in records if record.value is not None]
                    if len(num_vals) == len(records) and len(num_vals) >= 2:
                        min_v, max_v = min(num_vals), max(num_vals)
                        base = max(abs(min_v), abs(max_v))
                        if base > 0 and (max_v - min_v) / base <= 0.005:  # 0.5% tolerance
                            is_tolerable = True
                except (ValueError, TypeError):
                    pass

                if is_tolerable:
                    continue

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
