"""Normalize dynamic SkillHub rows into the stable EvidenceItem contract."""

import hashlib
import json
import re
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import UTC, date, datetime
from collections.abc import Iterator
from typing import Any, Literal

from app.agents.data_fetcher.executor import ExecutedTask
from app.schemas.acquisition import (
    NormalizationSummary,
    DataGap,
    QuarantinedRecord,
    SkillName,
    SourceRecord,
)
from app.schemas.evidence import (
    AuditStatus,
    CorporateActionAdjustment,
    EvidenceGrade,
    EvidenceItem,
    RestatementStatus,
)

FiscalPeriod = Literal["FY", "H1", "Q1", "Q2", "Q3", "Q4", "TTM"]

_ENTITY_FIELDS = (
    "股票简称",
    "证券简称",
    "公司名称",
    "企业名称",
    "行业名称",
    "板块名称",
    "指数简称",
    "合约简称",
    "品种简称",
    "指标名称",
    "macro_name",
    "name",
)
_PERIOD_FIELDS = (
    "报告期",
    "数据日期",
    "日期",
    "时间",
    "交易日期",
    "统计期",
    "report_date",
    "end_date",
)
_AVAILABLE_FIELDS = (
    "发布日期",
    "公告日期",
    "可得日期",
    "披露日期",
    "更新日期",
    "publish_date",
    "publish_time",
    "modify_time",
)
_LOCATOR_FIELDS = ("链接", "url", "URL", "来源链接", "公告链接", "研报链接")
_METADATA_FIELDS = set(
    _ENTITY_FIELDS
    + _PERIOD_FIELDS
    + _AVAILABLE_FIELDS
    + _LOCATOR_FIELDS
    + (
        "来源",
        "发布主体",
        "机构",
        "单位",
        "产业链数据来源",
        "data_source",
        "source_original",
        "channel",
        "extra",
        "id",
        "index",
        "operation_type",
        "para_index",
        "score",
        "site_authority",
        "status",
        "stock_infos",
        "trace_info",
        "traceability_type",
        "uid",
        "股票代码",
        "证券代码",
        "指数代码",
        "合约代码",
        "品种代码",
        "国家",
        "指标",
        "周期",
        "macro_id",
        "地区级别",
    )
)
_MAX_EVIDENCE_ITEMS = 200
_MAX_POINTS_PER_METRIC_PER_TASK = 12
_MISSING_VALUES = {"", "--", "-", "n/a", "na", "none", "null", "暂无", "不适用"}
_RELEVANCE_FIELDS = (
    "所属同花顺行业",
    "所属概念",
    "纳入概念原因",
    "主营业务",
    "项目名称",
    "业务名称",
)
_TEXT_SEARCH_SKILLS = {
    SkillName.ANNOUNCEMENT,
    SkillName.EVENT,
    SkillName.INSTITUTIONAL_RESEARCH,
    SkillName.NEWS,
    SkillName.REPORT,
}
_METRIC_ALIASES = {
    "归属于母公司股东的净利润": "归母净利润",
    "母公司股东净利润": "归母净利润",
    "销售毛利率": "毛利率",
    "综合毛利率": "毛利率",
}
_FINANCE_BASE_CURRENCY_METRICS = {
    "营业收入",
    "营业成本",
    "归母净利润",
    "净利润",
    "经营现金流",
    "经营活动产生的现金流量净额",
    "总资产",
    "股东权益",
    "存货",
    "应收账款",
    "销售费用",
    "管理费用",
    "研发费用",
    "财务费用",
    "主营业务收入",
}

# P0-6（2026-09-01 方案）：行情字段词表。问财在查不到业务字段时会
# 静默回退行情数据（行数>0、不报错），必须靠字段相关性校验识别。
_MARKET_QUOTE_FIELD_TOKENS = (
    "最新价", "涨跌幅", "涨跌额", "开盘价", "收盘价", "最高价", "最低价",
    "昨收", "成交量", "成交额", "成交数量", "换手率", "换手", "量比",
    "振幅", "委比", "委差", "内盘", "外盘", "市值", "大单", "小单",
    "买入量", "卖出量", "买入额", "卖出额", "涨速", "股息率",
)
# 只在“按公司取业务字段”的技能上启用校验；INDUSTRY/MACRO 走宏观
# 指标路径，INDEX/SECTOR 本就返回行情类数据，均不适用。STOCK_SELECTOR
# 与 BUSINESS 同类（按公司取市场份额等业务字段），2026-09-01 真实
# 接口实测其同样静默回退行情列（成交量/成交额/换手率冒充市场份额）。
# 请求指标本身是行情类（如按换手率选股）时由 requested_metrics 判定放行。
_MARKET_QUOTE_FALLBACK_SKILLS = {
    SkillName.BUSINESS,
    SkillName.BASIC_INFO,
    SkillName.STOCK_SELECTOR,
}
# 证据口径标签（P0-6 配套）：行业口径技能 vs 公司口径技能。
_INDUSTRY_LEVEL_SKILLS = {
    SkillName.INDUSTRY,
    SkillName.MACRO,
    SkillName.SECTOR,
    SkillName.INDEX,
    SkillName.INDUSTRY_CHAIN,
}
_COMPANY_LEVEL_SKILLS = {
    SkillName.FINANCE,
    SkillName.BUSINESS,
    SkillName.BASIC_INFO,
    SkillName.STOCK_SELECTOR,
}


@dataclass(frozen=True)
class NormalizationResult:
    evidence: list[EvidenceItem]
    sources: list[SourceRecord]
    chain_rows: list[dict[str, Any]]
    quarantined: list[QuarantinedRecord]
    summary: NormalizationSummary
    # P0-6：清洗阶段识别出的字段相关性缺口（market_quote_fallback）。
    gaps: list[DataGap] = dataclass_field(default_factory=list)

    def __iter__(
        self,
    ) -> Iterator[list[EvidenceItem] | list[SourceRecord] | list[dict[str, Any]]]:
        """Keep the former three-value unpacking contract for local callers.

        New audit metadata is intentionally exposed as named attributes so an
        older Agent 1 consumer does not break merely because cleaning became
        observable.
        """

        yield self.evidence
        yield self.sources
        yield self.chain_rows


def normalize_tasks(
    executed: list[ExecutedTask],
    *,
    industry_topic: str,
    market_scope: list[str],
    security_types: list[str],
    reporting_currency: str | None,
    research_as_of: date,
) -> NormalizationResult:
    evidence: list[EvidenceItem] = []
    sources: list[SourceRecord] = []
    chain_rows: list[dict[str, Any]] = []
    quarantined: list[QuarantinedRecord] = []
    fallback_gaps: list[DataGap] = []
    raw_row_count = 0
    duplicate_raw_row_count = 0
    seen_rows: set[str] = set()
    clean_payload_rows: dict[tuple[str, int], list[dict[str, Any]]] = {}
    task_clean_row_counts: dict[str, int] = {}
    task_metric_names: dict[str, set[str]] = {}

    # Always inventory every provider payload first.  Evidence is bounded for
    # downstream model context, but provenance must never disappear merely
    # because an earlier high-volume skill consumed that evidence budget.
    for result in executed:
        # Intent tasks carry their own retrieval semantics (entity +
        # intent keywords); their rows are judged against the task
        # query tokens as well as the industry baseline topic.
        intent_relevance_tokens = (
            _query_relevance_tokens(result.task.query)
            | frozenset(result.task.target_entities)
            if getattr(result.task, "task_origin", "baseline") != "baseline"
            else frozenset()
        )
        for payload in result.payloads:
            raw_row_count += len(payload.rows)
            source_digest = hashlib.sha256(
                (
                    f"{payload.skill_name.value}|{payload.source_locator}|" f"{payload.raw_sha256}"
                ).encode("utf-8")
            ).hexdigest()[:16]
            source_id = "SRC-" + source_digest
            sources.append(
                SourceRecord(
                    source_id=source_id,
                    skill_name=payload.skill_name,
                    source_name=payload.source_name,
                    source_locator=payload.source_locator,
                    retrieved_at=datetime.now(UTC),
                    as_of_date=research_as_of,
                    raw_sha256=payload.raw_sha256,
                    row_count=len(payload.rows),
                    license_scope="authorized_provider",
                    storage_scope="metadata_only",
                )
            )
            # P0-6（2026-09-01 方案）：字段相关性校验（治成因 D）。
            # 返回列全部为行情字段且请求指标非行情类 → 判定
            # market_quote_fallback：整批行不进清洗、全部隔离并写
            # data_gap 如实披露，绝不计为成功证据。
            relevant, fallback_reason = _field_relevance_check(
                rows=payload.rows,
                requested_metrics=result.task.expected_fields,
                skill=payload.skill_name,
            )
            if fallback_reason == "market_quote_fallback":
                fallback_gaps.append(
                    DataGap(
                        gap_id=(
                            f"GAP-{result.task.task_id.removeprefix('Q-')}-P{payload.page}"
                        ),
                        skill_name=payload.skill_name,
                        task_id=result.task.task_id,
                        reason_code=fallback_reason,
                        description=(
                            f"{payload.skill_name.value}返回的列全部为行情字段"
                            "（最新价/涨跌幅/成交量等），与请求的业务指标无关："
                            "问财在查不到业务字段时会静默回退行情数据，"
                            "本次调用不计为成功证据，相关需求按数据缺口披露。"
                        ),
                        blocking=False,
                    )
                )
                for row in payload.rows:
                    cleaned_fallback = _clean_row(row)
                    row_hash_fallback = _row_hash(cleaned_fallback, payload.skill_name)
                    quarantined.append(
                        QuarantinedRecord(
                            quarantine_id=f"QUAR-{row_hash_fallback[:16]}",
                            skill_name=payload.skill_name,
                            row_sha256=row_hash_fallback,
                            entity=(
                                _first_text(cleaned_fallback, _ENTITY_FIELDS)
                                or industry_topic
                            )[:500],
                            reason_code="market_quote_fallback",
                            reason=(
                                "返回行仅含行情字段（最新价/涨跌幅等），"
                                "与请求的业务指标不相关，已隔离防止伪证据进入报告。"
                            ),
                        )
                    )
                clean_payload_rows[(result.task.task_id, payload.page)] = []
                continue
            cleaned_rows: list[dict[str, Any]] = []
            for row in payload.rows:
                cleaned = _clean_row(row)
                if not cleaned:
                    continue
                row_hash = _row_hash(cleaned, payload.skill_name)
                if row_hash in seen_rows:
                    duplicate_raw_row_count += 1
                    continue
                seen_rows.add(row_hash)
                entity = _first_text(cleaned, _ENTITY_FIELDS) or industry_topic
                if result.task.target_entities and not _matches_target_entity(
                    entity,
                    result.task.target_entities,
                    row=cleaned,
                    skill_name=payload.skill_name,
                ):
                    quarantined.append(
                        QuarantinedRecord(
                            quarantine_id=f"QUAR-{row_hash[:16]}",
                            skill_name=payload.skill_name,
                            row_sha256=row_hash,
                            entity=entity[:500],
                            reason_code="target_entity_mismatch",
                            reason=(
                                f"返回实体“{entity}”不属于用户指定目标"
                                f"（{'、'.join(result.task.target_entities)}），已隔离。"
                            ),
                        )
                    )
                    continue
                available_at = _first_date(cleaned, _AVAILABLE_FIELDS)
                if available_at is not None and available_at > research_as_of:
                    quarantined.append(
                        QuarantinedRecord(
                            quarantine_id=f"QUAR-{row_hash[:16]}",
                            skill_name=payload.skill_name,
                            row_sha256=row_hash,
                            entity=entity[:500],
                            reason_code="future_availability",
                            reason=(
                                f"返回数据的可得日{available_at.isoformat()}晚于研究时点"
                                f"{research_as_of.isoformat()}，已隔离以防止前视偏差。"
                            ),
                        )
                    )
                    continue
                # BUG-3（2026-09-02）：宏观行先过“任务查询 ∪ 任务意图 ∪ 研究主题”
                # 相关性门。问财会按宏观任务过宽返回（问出货量却回 PMI/CPI），
                # 这些行既不匹配任务查询也不匹配主题 → 隔离；而任务明确查询的
                # 指标（如查商品房销售面积）仍保留。仅作用于本次清洗，不回溯。
                if payload.skill_name == SkillName.MACRO and _macro_row_off_topic(
                    cleaned,
                    industry_topic,
                    relevance_tokens=(
                        intent_relevance_tokens
                        | _query_relevance_tokens(result.task.query)
                    ),
                ):
                    indicator = _first_text(cleaned, _MACRO_INDICATOR_FIELDS) or entity
                    quarantined.append(
                        QuarantinedRecord(
                            quarantine_id=f"QUAR-{row_hash[:16]}",
                            skill_name=payload.skill_name,
                            row_sha256=row_hash,
                            entity=entity[:500],
                            reason_code="macro_off_topic",
                            reason=(
                                f"宏观指标“{indicator}”与本次任务意图及研究主题"
                                f"“{industry_topic}”无可验证关联，已隔离防止无关宏观"
                                "序列进入证据库。"
                            ),
                        )
                    )
                    continue
                # hithink_sector_selector is a screening skill:
                # membership is the provider core filter and constituent
                # rows declare their own industries which never contain
                # the basket name, so topic matching can only false-
                # quarantine them (E-48 root cause).
                if payload.skill_name != SkillName.SECTOR and _is_low_relevance(
                    cleaned,
                    industry_topic,
                    require_text_match=payload.skill_name in _TEXT_SEARCH_SKILLS,
                    extra_tokens=intent_relevance_tokens,
                ):
                    quarantined.append(
                        QuarantinedRecord(
                            quarantine_id=f"QUAR-{row_hash[:16]}",
                            skill_name=payload.skill_name,
                            row_sha256=row_hash,
                            entity=entity[:500],
                            reason=(
                                f"返回行的行业、概念或主营业务字段与研究主题"
                                f"“{industry_topic}”无可验证匹配，已隔离等待人工复核。"
                            ),
                        )
                    )
                    continue
                cleaned_rows.append(cleaned)
            clean_payload_rows[(result.task.task_id, payload.page)] = cleaned_rows
            task_clean_row_counts[result.task.task_id] = task_clean_row_counts.get(
                result.task.task_id, 0
            ) + len(cleaned_rows)
            if payload.skill_name == SkillName.INDUSTRY_CHAIN:
                chain_rows.extend(cleaned_rows)

    populated_results = [result for result in executed if result.payloads]
    remaining_budget = _MAX_EVIDENCE_ITEMS
    remaining_results = len(populated_results)
    for result in populated_results:
        if remaining_budget <= 0:
            break
        task_budget = max(1, remaining_budget // remaining_results)
        task_evidence_count = 0
        task_complete = False
        metric_counts: dict[tuple[str, str], int] = {}
        for payload in result.payloads:
            rows = clean_payload_rows.get((result.task.task_id, payload.page), [])
            for row_index, row in enumerate(rows):
                entity = _first_text(row, _ENTITY_FIELDS) or industry_topic
                period_end = _first_date(row, _PERIOD_FIELDS)
                available_at = _first_date(row, _AVAILABLE_FIELDS) or research_as_of
                row_source = _publisher_from_row(row)
                source_name = (
                    f"{row_source}（经同花顺问财SkillHub获取）"
                    if row_source and row_source != "本地测试桩"
                    else payload.source_name
                )
                locator = _first_text(row, _LOCATOR_FIELDS) or payload.source_locator
                ordered_fields = sorted(
                    row.items(),
                    key=lambda item: _field_period(str(item[0])) or date.min,
                    reverse=True,
                )
                for field_name, raw_value in ordered_fields:
                    if field_name in _METADATA_FIELDS or _is_missing(raw_value):
                        continue
                    if (
                        payload.skill_name in _MARKET_QUOTE_FALLBACK_SKILLS
                        and _is_market_quote_field(field_name)
                    ):
                        # P0-6：部分命中场景——业务字段保留为证据，
                        # 行情列不产证据（防行情值混进业务指标序列）。
                        continue
                    item_period_end = period_end or _field_period(str(field_name))
                    metric_name = _metric_name_from_row(
                        str(field_name),
                        row,
                        payload.skill_name,
                    )
                    metric_key = (_normalized_identity(entity), metric_name)
                    if metric_counts.get(metric_key, 0) >= _MAX_POINTS_PER_METRIC_PER_TASK:
                        continue
                    value, unit = _parse_value_and_unit(
                        str(field_name),
                        raw_value,
                        row,
                        skill_name=payload.skill_name,
                        metric_name=metric_name,
                    )
                    fingerprint = hashlib.sha256(
                        json.dumps(
                            [
                                payload.skill_name.value,
                                payload.raw_sha256,
                                row_index,
                                metric_name,
                                raw_value,
                                entity,
                                (item_period_end.isoformat() if item_period_end else None),
                            ],
                            ensure_ascii=False,
                            default=str,
                        ).encode("utf-8")
                    ).hexdigest()[:16]
                    audit, restatement = _financial_posture(payload.skill_name)
                    evidence.append(
                        EvidenceItem(
                            evidence_id=f"E-{fingerprint}",
                            metric_name=metric_name[:200],
                            value=value,
                            unit=unit,
                            period_end=item_period_end,
                            fiscal_period=_fiscal_period(
                                str(field_name),
                                item_period_end,
                                payload.skill_name,
                            ),
                            available_at=available_at,
                            audit_status=audit,
                            restatement_status=restatement,
                            scope=str(entity)[:5_000],
                            market=(market_scope[0] if market_scope else "未指定")[:100],
                            exchange="不适用",
                            security_type=(security_types[0] if security_types else "行业汇总")[
                                :100
                            ],
                            currency=(reporting_currency or "不适用")[:20],
                            accounting_standard=(
                                "未提供" if payload.skill_name == SkillName.FINANCE else "不适用"
                            ),
                            corporate_action_adjustment=CorporateActionAdjustment.NOT_APPLICABLE,
                            source_name=source_name[:500],
                            publisher=(row_source[:500] if row_source else None),
                            retrieval_method="同花顺问财 SkillHub",
                            source_locator=locator[:1_000],
                            grade=_grade(payload.skill_name),
                            caliber=_evidence_caliber(payload.skill_name),
                            notes=(
                                f"通过{payload.skill_name.value}获取；"
                                f"原始字段：{str(field_name)[:200]}；"
                                "原始字段口径以SkillHub返回为准，未返回的审计/追溯信息不作推断。"
                            ),
                        )
                    )
                    task_metric_names.setdefault(result.task.task_id, set()).add(metric_name)
                    metric_counts[metric_key] = metric_counts.get(metric_key, 0) + 1
                    task_evidence_count += 1
                    if task_evidence_count >= task_budget:
                        task_complete = True
                        break
                if task_complete:
                    break
            if task_complete:
                break
        remaining_budget -= task_evidence_count
        remaining_results -= 1
    skill_evidence_counts: dict[SkillName, int] = {}
    for item in evidence:
        for skill in SkillName:
            if item.notes and f"通过{skill.value}获取" in item.notes:
                skill_evidence_counts[skill] = skill_evidence_counts.get(skill, 0) + 1
                break
    return NormalizationResult(
        evidence=evidence,
        sources=_unique_sources(sources),
        chain_rows=chain_rows,
        quarantined=quarantined,
        gaps=fallback_gaps,
        summary=NormalizationSummary(
            raw_row_count=raw_row_count,
            unique_row_count=len(seen_rows),
            clean_row_count=sum(len(rows) for rows in clean_payload_rows.values()),
            evidence_count=len(evidence),
            duplicate_raw_row_count=duplicate_raw_row_count,
            quarantined_count=len(quarantined),
            skill_evidence_counts=skill_evidence_counts,
            task_clean_row_counts=task_clean_row_counts,
            task_metric_names={
                task_id: sorted(names) for task_id, names in task_metric_names.items()
            },
        ),
    )


def _unique_sources(sources: list[SourceRecord]) -> list[SourceRecord]:
    return list({source.source_id: source for source in sources}.values())


def _clean_row(row: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for raw_key, raw_value in row.items():
        key = re.sub(r"[\u200b-\u200d\ufeff]", "", str(raw_key))
        key = re.sub(r"\s+", " ", key).strip()
        if not key or _is_missing(raw_value):
            continue
        value = raw_value
        if isinstance(value, str):
            value = re.sub(r"<[^>]+>", " ", value)
            value = re.sub(r"[\u200b-\u200d\ufeff]", "", value)
            value = re.sub(r"\s+", " ", value).strip()
            if _is_missing(value):
                continue
        cleaned[key] = value
    return cleaned


def _is_market_quote_field(field_name: str) -> bool:
    """识别行情/交易类字段名（含 [日期]、(%) 等修饰后缀）。"""

    compact = re.sub(r"\[.*?\]|\(.*?\)|（.*?）|\s+", "", str(field_name))
    return any(token in compact for token in _MARKET_QUOTE_FIELD_TOKENS)


def _field_relevance_check(
    *,
    rows: list[dict[str, Any]],
    requested_metrics: list[str],
    skill: SkillName,
) -> tuple[bool, str | None]:
    """P0-6（2026-09-01 方案）：字段相关性校验（治成因 D）。

    问财在查不到业务字段时不返回空，而是静默回退行情数据（最新价/
    涨跌幅/大单卖出量…）：行数>0、能过既有质量门，Agent 2 会把
    “当日行情”当成“查到了出货量”。本校验只作用于按公司取业务
    字段的技能（BUSINESS/BASIC_INFO）：返回数据列全部落在行情字段
    集合内、且请求指标并非行情类 → 判定 market_quote_fallback，
    返回 (False, "market_quote_fallback")，调用方不得计为成功证据。
    """

    if skill not in _MARKET_QUOTE_FALLBACK_SKILLS or not rows:
        return True, None
    # 请求指标本身是行情类（如查“最新价”）→ 合法返回，不算回退。
    metric_fields = [
        name for name in requested_metrics if name not in _METADATA_FIELDS
    ]
    if metric_fields and all(_is_market_quote_field(name) for name in metric_fields):
        return True, None
    data_fields: set[str] = set()
    for row in rows:
        for field_name in row:
            if field_name in _METADATA_FIELDS:
                continue
            data_fields.add(str(field_name))
    if data_fields and all(_is_market_quote_field(name) for name in data_fields):
        return False, "market_quote_fallback"
    return True, None


def _evidence_caliber(skill_name: SkillName) -> str | None:
    """P0-6 配套：证据口径标签（行业级/公司级）。

    产业运营指标（出货量/产能/产量/产能利用率）经 industry_query 取
    得的是行业口径；财务/业务字段是公司口径。下游必须凭标签区分，
    防止“用行业产量冒充公司出货量”。定性检索类证据无明确口径，标 None。
    """

    if skill_name in _INDUSTRY_LEVEL_SKILLS:
        return "industry_level"
    if skill_name in _COMPANY_LEVEL_SKILLS:
        return "company_level"
    return None


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().casefold() in _MISSING_VALUES
    return False


def _row_hash(row: dict[str, Any], skill_name: SkillName) -> str:
    return hashlib.sha256(
        json.dumps(
            [skill_name.value, row],
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _topic_tokens(topic: str) -> set[str]:
    compact = re.sub(r"(?:行业|产业链|产业|板块|概念|市场)$", "", topic.strip())
    tokens = {compact} if compact else set()
    for prefix in ("中国", "国内", "全球", "海外"):
        if compact.startswith(prefix) and len(compact) - len(prefix) >= 2:
            tokens.add(compact[len(prefix) :])
    tokens.update(token for token in re.split(r"[、/\s-]+", compact) if len(token) >= 2)
    return tokens


_QUERY_TOKEN_STOPWORDS = frozenset(
    {
        "公告",
        "事件",
        "最新",
        "研究",
        "新闻",
        "财报",
        "业绩预告",
        "机构覆盖",
        "盈利预测",
        "评级",
        "目标价",
        "价格走势",
        "价格",
        "对比",
        "分析",
        "归因",
        "配置逻辑",
        "板块",
        "概念股",
    }
)


def _query_relevance_tokens(query: str) -> frozenset[str]:
    """Entity/subject tokens of an intent query; generic words drop."""
    tokens: set[str] = set()
    for raw in query.split():
        token = re.sub(r"(?:行业|产业链|产业|板块|概念|市场)$", "", raw.strip())
        if len(token) >= 2 and token not in _QUERY_TOKEN_STOPWORDS:
            tokens.add(token)
    return frozenset(tokens)


def _normalized_identity(value: str) -> str:
    return re.sub(r"[\s（）()\-_/]+", "", value).casefold()


def _matches_target_entity(
    entity: str,
    targets: list[str],
    *,
    row: dict[str, Any] | None = None,
    skill_name: SkillName | None = None,
) -> bool:
    if not targets:
        return True
    identity = _normalized_identity(entity)
    target_ids = {(_normalized_identity(t), t) for t in targets}
    for norm, raw in target_ids:
        if norm and norm == identity:
            return True
        if norm and identity and (norm in identity or identity in norm):
            return True
    # Text-search channels (announcement/event/research/news/report) return
    # rows whose entity column is often a system value (admin) or the source
    # account rather than the subject company; the subject only appears in
    # the row text itself.  For those skills a target name found anywhere in
    # the row is a real subject match (E-41 announcement rows about
    # 宁德时代 were quarantined because their entity column read admin).
    if row is not None and skill_name in _TEXT_SEARCH_SKILLS:
        haystack = " ".join(
            str(value) for value in row.values() if isinstance(value, str)
        )
        for _, raw in target_ids:
            if raw and raw in haystack:
                return True
    return False


def _is_low_relevance(
    row: dict[str, Any],
    industry_topic: str,
    *,
    require_text_match: bool = False,
    extra_tokens: frozenset[str] = frozenset(),
) -> bool:
    if extra_tokens:
        # Intent sub-requirements carry their own retrieval semantics
        # (entity + intent keywords); a row matching any query token is
        # on-topic for that task even when it is off-topic for the
        # industry baseline (E-41: a company announcement row is not a
        # sector row but is exactly what the sub-requirement asked for).
        searchable = " ".join(
            str(value) for value in row.values() if isinstance(value, str)
        )
        if any(token in searchable for token in extra_tokens):
            return False
    declared = [str(row[field]).strip() for field in _RELEVANCE_FIELDS if row.get(field)]
    if not declared:
        if not require_text_match:
            return False
        searchable = " ".join(
            str(value) for value in row.values() if isinstance(value, str)
        )
        return not any(token in searchable for token in _topic_tokens(industry_topic))
    haystack = " ".join(declared)
    if any(token in haystack for token in _topic_tokens(industry_topic)):
        return False
    compact_topic = re.sub(r"[\s、，,;/\-]+", "", industry_topic)
    declared_terms = {
        re.sub(r"(?:行业|产业链|产业|板块|概念|市场)$", "", term.strip())
        for value in declared
        for term in re.split(r"[、，,;/\s\-]+", value)
        if len(term.strip()) >= 2
    }
    return not any(
        term and (term in compact_topic or compact_topic in term) for term in declared_terms
    )


# BUG-3（2026-09-02）：宏观行不含 _RELEVANCE_FIELDS（行业/概念/主营业务），
# 也不属于 _TEXT_SEARCH_SKILLS，_is_low_relevance 对其恒为放行，导致
# PMI/CPI 等与研究主题无关的宏观序列整批进入证据库。这里单独对宏观行做
# 相关性判定：指标名/行文本须与“任务意图 tokens ∪ 研究主题 tokens”有交集。
_MACRO_INDICATOR_FIELDS = ("指标", "指标名称", "macro_name")


def _macro_row_off_topic(
    row: dict[str, Any],
    industry_topic: str,
    *,
    relevance_tokens: frozenset[str],
) -> bool:
    """True when a MACRO row cannot be tied to the task intent or topic."""
    tokens = set(relevance_tokens) | _topic_tokens(industry_topic)
    if not tokens:
        # 无任何可判定 token 时不做拦截（保持既有行为，避免误杀）。
        return False
    indicator = _first_text(row, _MACRO_INDICATOR_FIELDS) or ""
    haystack_parts = [indicator]
    haystack_parts.extend(str(value) for value in row.values() if isinstance(value, str))
    haystack = " ".join(haystack_parts)
    return not any(token and token in haystack for token in tokens)


def _normalize_metric_name(field_name: str) -> str:
    name = re.sub(r"\[(?:19|20)\d{6}(?:-(?:19|20)\d{6})?\]", "", field_name)
    name = re.sub(r"\s+", " ", name).strip()
    name = re.sub(r"[（(](?:pe,?ttm|ttm|mrq)[）)]$", "", name, flags=re.IGNORECASE)
    name = re.sub(
        r"[（(](?:元|万元|亿元|股|万股|亿股|%|千瓦|兆瓦|吉瓦|kW|MW|GW|"
        r"千瓦时|兆瓦时|吉瓦时|kWh|MWh|GWh)[）)]$",
        "",
        name,
        flags=re.IGNORECASE,
    ).strip()
    for alias, canonical in _METRIC_ALIASES.items():
        if name == alias or name.startswith(f"{alias}(") or name.startswith(f"{alias}（"):
            suffix = name[len(alias) :]
            return f"{canonical}{suffix}"
    return name


def _metric_name_from_row(
    field_name: str,
    row: dict[str, Any],
    skill_name: SkillName,
) -> str:
    """Recover the actual macro indicator name from generic provider columns."""

    if skill_name == SkillName.MACRO and field_name in {"指标值", "value", "数值"}:
        indicator = _first_text(row, ("指标", "指标名称", "macro_name"))
        if indicator:
            return re.sub(r"^(?:全国|中国)[:：]", "", indicator).strip()[:200]
    metric_name = _normalize_metric_name(field_name)
    business_metrics = {
        "业务收入": "主营业务收入",
        "业务成本": "主营业务成本",
        "业务利润": "主营业务利润",
        "收入占比": "主营业务收入占比",
        "成本占比": "主营业务成本占比",
        "利润占比": "主营业务利润占比",
        "毛利率": "主营业务毛利率",
    }
    if skill_name == SkillName.BUSINESS and metric_name in business_metrics:
        business_item = _first_text(row, ("项目名称", "业务名称"))
        if business_item and business_item not in metric_name:
            return f"{business_metrics[metric_name]}-{business_item}"[:200]
    return metric_name


def _publisher_from_row(row: dict[str, Any]) -> str | None:
    """Accept only compact publisher labels, never full provider content blobs."""

    value = _first_text(row, ("发布主体", "机构", "作者", "publisher", "来源"))
    if value is None or len(value) > 200 or value.count("|") >= 3 or "\n" in value:
        return None
    return value


def _first_text(row: dict[str, Any], fields: tuple[str, ...]) -> str | None:
    for field in fields:
        value = row.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _first_date(row: dict[str, Any], fields: tuple[str, ...]) -> date | None:
    for field in fields:
        value = row.get(field)
        parsed = _parse_date(value)
        if parsed is not None:
            return parsed
    return None


def _field_period(field_name: str) -> date | None:
    """Read provider dates embedded in dynamic columns such as 指标[20251231]."""

    candidates = re.findall(r"(?<!\d)(?:19|20)\d{6}(?!\d)", field_name)
    for candidate in reversed(candidates):
        parsed = _parse_date(candidate)
        if parsed is not None:
            return parsed
    return None


def _fiscal_period(
    field_name: str,
    period_end: date | None,
    skill_name: SkillName,
) -> FiscalPeriod | None:
    """Preserve provider period semantics without guessing from numeric magnitude."""

    if skill_name != SkillName.FINANCE:
        return None
    compact = re.sub(r"[\s_\-]+", "", field_name).casefold()
    markers: tuple[tuple[tuple[str, ...], FiscalPeriod], ...] = (
        (("ttm", "滚动十二月"), "TTM"),
        (("年报", "年度", "全年", "fy"), "FY"),
        (("中报", "半年", "半年度", "h1"), "H1"),
        (("一季", "第一季度", "q1"), "Q1"),
        (("二季", "第二季度", "q2"), "Q2"),
        (("三季", "第三季度", "q3"), "Q3"),
        (("四季", "第四季度", "q4"), "Q4"),
    )
    for tokens, label in markers:
        if any(token in compact for token in tokens):
            return label
    # Dynamic annual fields frequently contain only a 31-December period. It
    # is safe to mark those as FY for the finance skill; other dates remain
    # unknown and therefore cannot be mixed with an explicit fiscal period.
    if period_end is not None and (period_end.month, period_end.day) == (12, 31):
        return "FY"
    return None


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    digits = re.sub(r"[^0-9]", "", value)
    try:
        if len(digits) >= 8:
            return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
        if len(digits) == 6:
            return date(int(digits[:4]), int(digits[4:6]), 1)
        if len(digits) == 4:
            return date(int(digits), 12, 31)
    except ValueError:
        return None
    return None


def _parse_value_and_unit(
    field_name: str,
    raw_value: Any,
    row: dict[str, Any],
    *,
    skill_name: SkillName,
    metric_name: str,
) -> tuple[int | float | str, str]:
    unit_match = re.search(r"[（(]([^()（）]{1,20})[）)]", field_name)
    unit = unit_match.group(1) if unit_match else None
    if unit and unit.casefold().replace(" ", "") in {"pe,ttm", "pettm", "ttm", "mrq"}:
        unit = None
    explicit_unit = row.get("单位")
    if isinstance(explicit_unit, str) and explicit_unit.strip():
        unit = explicit_unit.strip()
    if unit is None:
        unit = _provider_contract_unit(skill_name, metric_name)
    if isinstance(raw_value, bool):
        return str(raw_value), unit or "文本"
    if isinstance(raw_value, (int, float)):
        value, normalized_unit = _normalize_numeric_unit(float(raw_value), unit)
        value = _provider_contract_value(skill_name, metric_name, value)
        return (int(value) if value.is_integer() else value), normalized_unit
    text = str(raw_value).strip()
    numeric = text.replace(",", "").replace("，", "")
    suffix_unit: str | None = None
    unit_suffix = re.fullmatch(
        r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*"
        r"(亿元|万元|亿股|万股|兆瓦时|吉瓦时|千瓦时|"
        r"GWh|MWh|kWh|兆瓦|吉瓦|千瓦|GW|MW|kW|元|股|%|万|亿)",
        numeric,
        flags=re.IGNORECASE,
    )
    if unit_suffix:
        numeric = unit_suffix.group(1)
        suffix_unit = unit_suffix.group(2)
    try:
        value, normalized_unit = _normalize_numeric_unit(float(numeric), unit or suffix_unit)
        value = _provider_contract_value(skill_name, metric_name, value)
        return (int(value) if value.is_integer() else value), normalized_unit
    except ValueError:
        return text[:5_000], unit or "文本"


def _provider_contract_unit(skill_name: SkillName, metric_name: str) -> str | None:
    """Return only units guaranteed by a known provider field contract.

    This deliberately does not infer units from numeric magnitude. Dynamic
    finance amount fields from the official finance skill are base-currency
    values, while rate fields are percentage points.
    """

    if skill_name in {SkillName.FINANCE, SkillName.STOCK_SELECTOR} and (
        metric_name in _FINANCE_BASE_CURRENCY_METRICS
    ):
        return "元"
    if skill_name == SkillName.INDEX and metric_name in {"市盈率", "市净率"}:
        return "倍"
    compact = metric_name.casefold()
    if skill_name in {
        SkillName.FINANCE,
        SkillName.INDEX,
        SkillName.FUTURES,
        SkillName.STOCK_SELECTOR,
    } and (
        "率" in metric_name
        or "同比" in metric_name
        or "环比" in metric_name
        or "涨跌幅" in metric_name
        or "占比" in metric_name
        or "分位点" in metric_name
        or compact == "roe"
    ):
        return "%"
    return None


def _provider_contract_value(
    skill_name: SkillName,
    metric_name: str,
    value: float,
) -> float:
    """Apply value scaling only when confirmed by a provider field contract."""

    if skill_name == SkillName.INDEX and "分位点" in metric_name and 0.0 <= value <= 1.0:
        return value * 100.0
    return value


def _normalize_numeric_unit(value: float, unit: str | None) -> tuple[float, str]:
    normalized = (unit or "未提供").strip()
    conversions = {
        "元": (1.0, "元"),
        "万元": (10_000.0, "元"),
        "万": (10_000.0, "元"),
        "亿元": (100_000_000.0, "元"),
        "亿": (100_000_000.0, "元"),
        "股": (1.0, "股"),
        "万股": (10_000.0, "股"),
        "亿股": (100_000_000.0, "股"),
        "千瓦": (0.001, "兆瓦"),
        "兆瓦": (1.0, "兆瓦"),
        "吉瓦": (1_000.0, "兆瓦"),
        "kW": (0.001, "兆瓦"),
        "MW": (1.0, "兆瓦"),
        "GW": (1_000.0, "兆瓦"),
        "千瓦时": (0.001, "兆瓦时"),
        "兆瓦时": (1.0, "兆瓦时"),
        "吉瓦时": (1_000.0, "兆瓦时"),
        "kWh": (0.001, "兆瓦时"),
        "MWh": (1.0, "兆瓦时"),
        "GWh": (1_000.0, "兆瓦时"),
    }
    factor, target = conversions.get(normalized, (1.0, normalized))
    return value * factor, target


def _financial_posture(skill: SkillName) -> tuple[AuditStatus, RestatementStatus]:
    if skill == SkillName.FINANCE:
        return AuditStatus.UNAUDITED, RestatementStatus.UNKNOWN
    return AuditStatus.NOT_APPLICABLE, RestatementStatus.NOT_APPLICABLE


def _grade(skill: SkillName) -> EvidenceGrade:
    if skill in {
        SkillName.FINANCE,
        SkillName.MACRO,
        SkillName.ANNOUNCEMENT,
        SkillName.EVENT,
    }:
        return EvidenceGrade.B
    if skill in {
        SkillName.INDUSTRY,
        SkillName.INDUSTRY_CHAIN,
        SkillName.BUSINESS,
        SkillName.SECTOR,
    }:
        return EvidenceGrade.C
    return EvidenceGrade.D
