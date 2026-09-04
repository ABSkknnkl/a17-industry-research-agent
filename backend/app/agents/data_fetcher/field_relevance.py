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
