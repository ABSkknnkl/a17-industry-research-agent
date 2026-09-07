"""字段相关性与字段词表（从 normalizer 抽出，打破 executor↔normalizer 循环）。

本模块无任何 data_fetcher 内部依赖，可同时被 ``executor`` 与 ``normalizer``
导入而不形成环：

    field_relevance.py   ← 无内部依赖
        ↑                      ↑
   executor.py           normalizer.py（改 import 路径，函数签名不变）

P0-6（2026-09-01 方案）：问财在查不到业务字段时会静默回退行情数据
（行数>0、不报错），必须靠字段相关性校验识别。2026-09-04 文档通道降级链
把该校验前移进 ``executor`` 的成功判定——“有行且字段相关才算成功”——
从而让“零行”与“静默降级为行情”两类失败统一进入降级路径。
"""

import re
from typing import Any

from app.schemas.acquisition import SkillName

# ---------------------------------------------------------------------------
# 字段词表（原 normalizer 常量，签名/取值完全保持不变）
# ---------------------------------------------------------------------------
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

# 2026-09-06 L3 根因修复：意图任务（task_origin != "baseline"）把行情回退
# 校验扩展到 SECTOR/INDEX——A14-01 根因：PE/PB 诉求被静默回退成行情列，
# 而这两个技能不在原集合内。基线任务维持原语义（SECTOR/INDEX 本就返回
# 行情类数据），不扩展，避免 P0 全量扫描被误判。
_INTENT_QUOTE_FALLBACK_SKILLS = frozenset({SkillName.SECTOR, SkillName.INDEX})

# 各技能 _requirement_task_profile 的默认期望字段（泛型列名，不携带具体
# 指标语义）。用途：① 语义相关性判定时剔除它们，只留真实指标名当匹配
# 锚点；② executor 构造 L3 检索词时把它们当元数据剔除（否则“指标名称
# 指标值”这类词会发给博查，拉低联网召回质量）。
GENERIC_PROFILE_FIELDS = frozenset(
    {
        "指标名称",
        "指标值",
        "指标单位",
        "单位",
        "数据日期",
        "报告期",
        "来源",
        "行业名称",
        "行业规模",
        "市场规模",
        "同比增速",
        "增速",
        "估值",
        "景气度",
        "板块名称",
        "成分股",
        "产业链环节",
        "代表企业",
        "供需",
        "上游",
        "中游",
        "下游",
        "主营业务",
        "业务收入占比",
        "客户",
        "供应商",
        "标题",
        "公告标题",
        "公司",
        "公司全称",
        "机构",
        "发布主体",
        "发布日期",
        "公告日期",
        "报告日期",
        "上市地点",
        "上市日期",
        "事件类型",
        "评级",
        "盈利预测",
        "目标价",
        "值",
        "最新价",
        "涨跌幅",
        "市值",
    }
)

# 语义相关性判定（2026-09-06 L3 根因修复）覆盖的结构化技能，仅对意图
# 任务生效。文本检索类（NEWS/REPORT/ANNOUNCEMENT/EVENT/INDUSTRY_CHAIN）
# 返回自然语言行，字段匹配无意义；FUTURES 的品种简称与指标名无稳定
# 字面交叠（“镍价格” vs “沪镍”），纳入会误判，故不覆盖。
_INTENT_SEMANTIC_SKILLS = frozenset(
    {
        SkillName.MACRO,
        SkillName.INDUSTRY,
        SkillName.SECTOR,
        SkillName.INDEX,
        SkillName.FINANCE,
        SkillName.BUSINESS,
        SkillName.BASIC_INFO,
    }
)


def _semantic_metric_tokens(requested_metrics: list[str]) -> set[str]:
    """从期望字段提取具体指标锚点（泛型 profile 字段与元数据均已剔除）。"""

    tokens: set[str] = set()
    for metric in requested_metrics:
        normalized = _normalize_field_name(metric).lower()
        if (
            len(normalized) >= 2
            and normalized not in _METADATA_FIELDS
            and normalized not in GENERIC_PROFILE_FIELDS
        ):
            tokens.add(normalized)
    return tokens


def _token_matches(token: str, text: str) -> bool:
    """锚点与返回文本的双向包含匹配（短文本只允许被包含，防单字误命中）。"""

    if not token or not text:
        return False
    if token in text:
        return True
    return len(text) >= 2 and text in token


def _is_market_quote_field(field_name: str) -> bool:
    """识别行情/交易类字段名（含 [日期]、(%) 等修饰后缀）。"""

    compact = re.sub(r"\[.*?\]|\(.*?\)|（.*?）|\s+", "", str(field_name))
    return any(token in compact for token in _MARKET_QUOTE_FIELD_TOKENS)


def _field_relevance_check(
    *,
    rows: list[dict[str, Any]],
    requested_metrics: list[str],
    skill: SkillName,
    task_origin: str | None = None,
) -> tuple[bool, str | None]:
    """P0-6（2026-09-01 方案）+ 2026-09-06 语义相关性扩展：字段相关性校验。

    问财在查不到业务字段时不返回空，而是静默回退行情数据（最新价/
    涨跌幅/大单卖出量…）：行数>0、能过既有质量门，Agent 2 会把
    “当日行情”当成“查到了出货量”。本校验只作用于按公司取业务
    字段的技能（BUSINESS/BASIC_INFO）：返回数据列全部落在行情字段
    集合内、且请求指标并非行情类 → 判定 market_quote_fallback，
    返回 (False, "market_quote_fallback")，调用方不得计为成功证据。

    2026-09-06 L3 根因修复（碳酸锂价格 → CPI 宏观占位数据）：
    - 行情回退校验对意图任务（task_origin != "baseline"）扩展到
      SECTOR/INDEX（PE/PB 诉求被静默回退行情列，A14-01 根因）；
    - 新增语义相关性判定（仅意图任务）：期望指标锚点与返回数据
      （数据列名 + 实体列取值——宏观/期货的指标名在实体值里）完全
      零交集 → 判 field_mismatch，走降级路径而不是冒充成功。基线
      任务（P0 全量扫描）不启用语义判定：其期望字段是泛型 profile
      列，无具体指标语义，误判只会白烧 L2/L3 配额。
    """

    is_intent_task = task_origin not in (None, "baseline")

    if rows:
        # ---- 行情回退校验（P0-6 原有；意图任务扩展 SECTOR/INDEX）----
        quote_skills: set[SkillName] = set(_MARKET_QUOTE_FALLBACK_SKILLS)
        if is_intent_task:
            quote_skills |= _INTENT_QUOTE_FALLBACK_SKILLS
        if skill in quote_skills:
            # 请求指标本身是行情类（如查“最新价”）→ 合法返回，不算回退。
            metric_fields = [
                name for name in requested_metrics if name not in _METADATA_FIELDS
            ]
            if metric_fields and all(
                _is_market_quote_field(name) for name in metric_fields
            ):
                return True, None
            data_fields: set[str] = set()
            for row in rows:
                for field_name in row:
                    if field_name in _METADATA_FIELDS:
                        continue
                    data_fields.add(str(field_name))
            if data_fields and all(
                _is_market_quote_field(name) for name in data_fields
            ):
                return False, "market_quote_fallback"

        # ---- 语义相关性校验（2026-09-06 新增，仅意图任务）----
        if is_intent_task and skill in _INTENT_SEMANTIC_SKILLS:
            tokens = _semantic_metric_tokens(requested_metrics)
            if tokens:
                entity_fields = {
                    _normalize_field_name(name) for name in _ENTITY_FIELDS
                }
                texts: set[str] = set()
                for row in rows:
                    for field_name, value in row.items():
                        normalized = _normalize_field_name(field_name)
                        if normalized not in _METADATA_FIELDS:
                            texts.add(normalized.lower())
                        if (
                            normalized in entity_fields
                            and isinstance(value, str)
                            and value.strip()
                        ):
                            texts.add(value.strip().lower())
                if texts and not any(
                    _token_matches(token, text)
                    for token in tokens
                    for text in texts
                ):
                    return False, "field_mismatch"
    return True, None


def fields_relevant(
    rows: list[dict[str, Any]],
    requested_metrics: list[str],
    skill: SkillName,
) -> bool:
    """布尔包装，供 ``executor`` 成功判定使用（只关心是否相关）。

    校验过程绝不应让取数失败，任何异常一律按“相关”放行，交由下游
    正常清洗/隔离流程处理，保持 fail-open 不引入新故障面。
    """
    try:
        _, reason = _field_relevance_check(
            rows=rows,
            requested_metrics=requested_metrics,
            skill=skill,
        )
    except Exception:
        return True
    return reason is None


# ---------------------------------------------------------------------------
# S5（2026-09-06 方案 §2.2）：可用性预检——识别“空壳数据”
#
# 与 _field_relevance_check 互补，两者都过才算 L1 有效：
#   _field_relevance_check → 列名不对（返回的全是行情列，P0-6 静默降级）
#   _rows_usable_precheck  → 列名对得上但值全空（行存在、目标列全 None）
# 后者是 2026-09-06 新增的失败形态：问财对某些公司/指标返回一行占位记录，
# 行数>0、字段名也相关，但业务列全空——旧判定会当成成功，导致下游拿空值算数。
# ---------------------------------------------------------------------------


def _normalize_field_name(field_name: Any) -> str:
    """剥离 ``[日期]`` / ``(%)`` / ``（单位）`` / 空白等修饰后缀，便于与请求指标对齐。"""

    return re.sub(r"\[.*?\]|\(.*?\)|（.*?）|\s+", "", str(field_name))


def _is_non_empty_value(value: Any) -> bool:
    """业务值是否为空。注意 0 / 0.0 / False 都是合法观测值，绝不能当空。"""

    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict, tuple, set)):
        return bool(value)
    return True


def _rows_usable_precheck(payloads: Any, task: Any) -> bool:
    """至少一行在请求的业务字段上有非空值，否则判为空壳数据（不可用）。

    判定收敛在“确实匹配到目标列”这一前提上：一个目标列都没匹配到时，若
    仍存在非空业务值则放行（列名对不上可能是问财换了列名，交下游清洗与
    隔离流程判定，避免仅因命名差异就误触发降级、白烧 L2/L3 配额）；若
    连非空业务值都没有（占位行 + 业务列全 None 的空壳），判失败进入降级
    （2026-09-06 L3 根因修复：问财查装机量返回空壳值同样判 succeeded，
    把 L3 挡在门外）。
    fail-open：任何异常一律放行，与本模块既有哲学一致。
    """

    try:
        rows = [
            row
            for payload in payloads
            for row in (getattr(payload, "rows", None) or [])
            if isinstance(row, dict)
        ]
        if not rows:
            return False
        expected = getattr(task, "expected_fields", None) or []
        targets = {
            _normalize_field_name(field)
            for field in expected
            if str(field).strip() and str(field).strip() not in _METADATA_FIELDS
        }
        if not targets:
            # 没有明确目标字段时退化为“至少一行有任意非元数据业务值”。
            return any(
                _is_non_empty_value(value)
                for row in rows
                for key, value in row.items()
                if _normalize_field_name(key) not in _METADATA_FIELDS
            )
        matched_target_column = False
        for row in rows:
            for key, value in row.items():
                normalized = _normalize_field_name(key)
                if normalized in _METADATA_FIELDS:
                    continue
                # 问财列名常带口径后缀，先精确后包含匹配（与别名归一同口径）。
                hit = normalized in targets or any(
                    target in normalized or normalized in target for target in targets
                )
                if not hit:
                    continue
                matched_target_column = True
                if _is_non_empty_value(value):
                    return True
        if not matched_target_column:
            # 2026-09-06 L3 根因修复：列名完全对不上时不再无条件放行——
            # 至少要求存在任一非空业务值。问财对查不到的指标会返回
            # “占位行 + 业务列全 None”的空壳（装机量 case），旧 fail-open
            # 把它判成成功，L3 永远没有出场机会。仍有非空值时维持放行。
            return any(
                _is_non_empty_value(value)
                for row in rows
                for key, value in row.items()
                if _normalize_field_name(key) not in _METADATA_FIELDS
            )
        return False
    except Exception:
        return True
