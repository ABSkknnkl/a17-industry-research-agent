"""Small shared contracts for reporting periods and comparable observations.

Publication/retrieval dates never substitute for a financial measurement period.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import math
import re
from typing import Any


_ISO_DATE = re.compile(r'(?<!\d)((?:19|20)\d{2}-\d{2}-\d{2})(?!\d)')
_NAMED_PERIOD = re.compile(r'(20\d{2})(?:年|-\d{2}-\d{2})')
# P-08：基期为零或负时，只有明确声明「按基期绝对值」的描述性变化才允许百分比口径。
_ABSOLUTE_BASE = re.compile(r'按基期绝对值|按绝对值|绝对基数|绝对值口径|相对绝对值')

# P-01：金额单位必须按**完整单位**解析，不能靠子串包含。
# 旧实现 `if "万" in u` 先于"百"分支命中，导致「百万元」被当成「万元」（差 100 倍）、
# 「千万元」同样被当成「万元」（差 1000 倍）；「万亿元」则被「亿」分支吃掉（差 1 万倍）。
# 这里以元为基准维护显式倍率表，所有模块（A1 解析 / A2 归一 / A3 轴单位）共用同一份。
MONEY_UNIT_SCALES: dict[str, int] = {
    '元': 1,
    '千元': 1_000,
    '万元': 10_000,
    '百万元': 1_000_000,
    '千万元': 10_000_000,
    '亿元': 100_000_000,
    '万亿元': 1_000_000_000_000,
}
# 兼容旧数据/旧别名：不带"元"字的量级后缀、以及纯币种标记。
_MONEY_ALIAS_SCALES: dict[str, int] = {
    '万': 10_000,
    '亿': 100_000_000,
    '万亿': 1_000_000_000_000,
}
_MONEY_CURRENCY_TOKENS = frozenset({'人民币', 'cny', 'rmb', '¥', '元人民币', '人民币元'})
_MONEY_PREFIX_SCALES: dict[str, int] = {
    '万亿': 10**12, '亿': 10**8, '百万': 10**6, '千万': 10**7, '万': 10**4, '千': 10**3,
}
_MONEY_UNKNOWN_TOKENS = frozenset({'unknown', 'legacy_unknown', 'none', 'nan', 'null', '-'})

# 兼容既有调用点（_verified_change 等处按元基准换算）。
_MONEY_SCALES = MONEY_UNIT_SCALES


def normalize_money_unit(unit: Any) -> str | None:
    """把来源单位清洗成标准金额单位；无法识别一律返回 None（不按量级猜）。

    仅做**结构化**解析（币种标记 + 量级前缀 + 元），不做任意子串包含匹配：
    「百万元/千万元/万亿元」必须整体识别，避免再次被「万」「亿」截获。
    """
    if unit is None:
        return None
    text = str(unit).strip().replace(' ', '').replace('\u3000', '')
    if not text:
        return None
    if text.casefold() in _MONEY_UNKNOWN_TOKENS:
        return None
    if text in MONEY_UNIT_SCALES:
        return text
    if text in _MONEY_ALIAS_SCALES:
        return text
    low = text.casefold()
    if low in _MONEY_CURRENCY_TOKENS or text in _MONEY_CURRENCY_TOKENS:
        return '元'
    core = low
    for token in ('人民币', 'cny', 'rmb', '¥'):
        core = core.replace(token, '')
    if core in {'', '元'}:
        return '元'
    match = re.fullmatch(r'(万亿|亿|百万|千万|万|千)?(?:元)?', core)
    if match and match.group(1):
        prefix = match.group(1)
        if prefix in _MONEY_PREFIX_SCALES:
            # 反查等价的标准单位名（保证「万」→「万元」这类别名落到同一键）。
            for name, scale in MONEY_UNIT_SCALES.items():
                if scale == _MONEY_PREFIX_SCALES[prefix]:
                    return name
    return None


def money_scale(unit: Any) -> int | None:
    """返回该金额单位相对「元」的倍率；不可识别返回 None。"""
    name = normalize_money_unit(unit)
    if name is None:
        return None
    if name in MONEY_UNIT_SCALES:
        return MONEY_UNIT_SCALES[name]
    return _MONEY_ALIAS_SCALES.get(name)


def money_to_yuan(value: Any, unit: Any) -> Decimal | None:
    """金额还原到「元」（Decimal，避免浮点误差）；单位不可信返回 None。"""
    scale = money_scale(unit)
    if scale is None or value is None:
        return None
    try:
        if isinstance(value, bool):
            return None
        return Decimal(str(value)) * Decimal(scale)
    except (InvalidOperation, ValueError, TypeError):
        return None


def money_to_yi(value: Any, unit: Any) -> Decimal | None:
    """金额换算到「亿元」（项目 A2 的统一金额基准）。"""
    yuan = money_to_yuan(value, unit)
    if yuan is None:
        return None
    return yuan / Decimal(100_000_000)


def choose_display_money_unit(values: list[Any], units: list[Any]) -> str:
    """按同轴全部可绘点的**规范金额**（元）选唯一展示单位（P-14）。

    规则与 A3 各路径共用：先还原到元，再按最大绝对值选 亿元 / 万元 / 元。
    没有任何可信单位时返回空串（不可比较），不按数值量级猜。
    """
    base_values: list[float] = []
    for value, unit in zip(values, units):
        scale = money_scale(unit)
        if scale is None:
            continue
        try:
            if isinstance(value, bool):
                continue
            base_values.append(abs(float(value)) * scale)
        except (TypeError, ValueError):
            continue
    if not base_values:
        return ''
    maximum = max(base_values)
    if maximum >= 1e8:
        return '亿元'
    if maximum >= 1e4:
        return '万元'
    return '元'


REPORT_BASIS_LABELS = {
    "annual": "年度", "consolidated": "合并报表", "parent": "母公司报表",
    "half_year": "半年度", "quarter": "单季度", "ytd_q3": "前三季度",
    "rate_observation_change": "比率观测值变化",
}


def format_report_rate(value: Any, unit: str) -> str:
    try:
        number = Decimal(str(value).strip().replace(",", ""))
        rounded = number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return f"{value}{unit}"
    if not number.is_finite():
        return f"{value}{unit}"
    if number and not rounded:
        prefix = "负值，绝对值" if number < 0 else ""
        return f"{prefix}小于0.01{unit}"
    return f"{rounded:.2f}{unit}"


def _valid_iso_dates(text: str) -> list[tuple[int, int, date]]:
    dates = []
    for match in _ISO_DATE.finditer(text):
        try:
            dates.append((match.start(), match.end(), date.fromisoformat(match.group(1))))
        except ValueError:
            pass
    return dates


def _rate_points(value: float, unit: str) -> float | None:
    if unit.strip().lower() in ('%', '％', '百分比', 'percent', 'percentage'):
        return value
    if unit.strip().lower() in ('ratio', '0-1'):
        return value * 100
    return None


# P0-1：期间证据优先级。来源明确的期间字段/标签 > 日期形状推导。
# 这里的别名只覆盖**期间限定词**，不把「当月值」当成指标名的一部分。
_PERIOD_KIND_ALIASES = {
    'annual': 'annual', 'year': 'annual', '年': 'annual', '年度': 'annual',
    '全年': 'annual', '年报': 'annual',
    'half_year': 'half_year', '半年': 'half_year', '半年度': 'half_year', '中报': 'half_year',
    'quarter': 'quarter', '季': 'quarter', '季度': 'quarter', '单季': 'quarter', '当季': 'quarter',
    'q1': 'q1', '一季度': 'q1', '第一季度': 'q1',
    'ytd_q3': 'ytd_q3', '前三季度': 'ytd_q3', '三季报': 'ytd_q3',
    'ytd_month': 'ytd_month', '累计': 'ytd_month',
    'month': 'month', '月': 'month', '月度': 'month', '当月': 'month', '当月值': 'month',
    'point': 'point', '日': 'point', '时点': 'point',
}
_PERIOD_YEAR_START_KINDS = frozenset({'annual', 'half_year', 'ytd_q3', 'q1', 'ytd_month'})


def normalize_period_kind(value: Any) -> str | None:
    """把来源期间字段（周期/期间类型/中文标签）归一为期间枚举；不识别返回 None。"""
    if value in (None, ''):
        return None
    return _PERIOD_KIND_ALIASES.get(str(value).strip().casefold())


def period_start_for(kind: str, end: date) -> date | None:
    """按期间类型给出共同起点；unknown 不推导。"""
    if kind in _PERIOD_YEAR_START_KINDS:
        return date(end.year, 1, 1)
    if kind == 'quarter':
        return date(end.year, ((end.month - 1) // 3) * 3 + 1, 1)
    if kind == 'month':
        return date(end.year, end.month, 1)
    if kind == 'point':
        return end
    return None


def _date_shape_kind(end: date) -> str:
    return {(12, 31): 'annual', (9, 30): 'ytd_q3', (6, 30): 'half_year', (3, 31): 'q1'}.get(
        (end.month, end.day), 'month'
    )


def _cumulative_kind(end: date | None) -> str:
    # 年末累计 = 全年；其余月份的累计值仍是年内累计（保留既有 ytd_month 语义）。
    if end is not None and (end.month, end.day) == (12, 31):
        return 'annual'
    return 'ytd_month'


def label_period_kind(label: str, end: date | None) -> str | None:
    """从指标名/字段名里的期间限定词读出期间类型。

    `周期=月` 描述的是序列频率；`累计值` 才是期间口径。因此标签优先于频率字段：
    动力电池「合计:累计值」在 12/31 仍是全年累计，不能被降成单月。
    """
    text = str(label or '').strip().casefold()
    if not text:
        return None
    if '当月值' in text or '当月' in text or '月度' in text:
        return 'month'
    if '累计值' in text or '累计' in text or '年累计' in text:
        return _cumulative_kind(end)
    if '单季' in text or '当季' in text:
        return 'quarter'
    if '年度值' in text or '全年' in text or '年度' in text or '年报' in text:
        # 只有年末才可能是全年；其它月份的年累计按 ytd_month 处理。
        return 'annual' if end is not None and (end.month, end.day) == (12, 31) else 'ytd_month'
    return None


def resolve_source_period(
    end: date | None,
    label: str = '',
    *,
    source_period: Any = None,
    explicit_type: Any = None,
    explicit_start: Any = None,
    point: bool = False,
) -> tuple[dict[str, Any], bool]:
    """A1/A2/A3 共用的期间解析。返回 (qualifiers, period_conflict)。

    优先级：显式期间类型 > 指标标签 > 来源周期字段 > 日期形状。
    显式期间字段与标签指向不同区间时判为冲突，记录仍保留原值但退出量化核验。
    """
    if end is None:
        return dict(period_start=None, period_type='unknown'), False
    if point:
        return dict(period_start=end, period_type='point'), False
    explicit_kind = normalize_period_kind(explicit_type)
    label_kind = label_period_kind(label, end)
    source_kind = normalize_period_kind(source_period)
    conflict = False
    if explicit_kind and label_kind:
        conflict = period_start_for(explicit_kind, end) != period_start_for(label_kind, end)
    chosen = explicit_kind or label_kind or source_kind or _date_shape_kind(end)
    start = period_start_for(chosen, end)
    parsed_start = _parse_loose_date(explicit_start)
    if parsed_start is not None:
        if chosen != 'unknown' and start is not None and parsed_start != start:
            conflict = True
        else:
            start = parsed_start
    return dict(period_start=start, period_type=chosen), conflict


def _parse_loose_date(value: Any) -> date | None:
    if value in (None, ''):
        return None
    text = str(value).strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def period_shape(end: date | None, label: str = '', *, point: bool = False) -> dict[str, Any]:
    if end is None:
        return dict(period_start=None, period_type='unknown')
    if point:
        return dict(period_start=end, period_type='point')
    kind = label_period_kind(label, end) or _date_shape_kind(end)
    return dict(period_start=period_start_for(kind, end), period_type=kind)


def source_report_period(text: str) -> date | None:
    """Only an explicitly named report, not an announcement date in surrounding text."""
    hits = re.findall(r'(20\d{2})年?\s*(三季报|前三季度|一季报|第一季度|中报|半年报|半年度|年报|年度报告)', text)
    periods = {date(int(y), *({'三季报': (9, 30), '前三季度': (9, 30),
                '一季报': (3, 31), '第一季度': (3, 31), '中报': (6, 30),
                '半年报': (6, 30), '半年度': (6, 30), '年报': (12, 31),
                '年度报告': (12, 31)}[tag])) for y, tag in hits}
    return next(iter(periods)) if len(periods) == 1 else None


def measurement_period(value: Any) -> tuple[date, date, str] | None:
    data = _as_dict(value)
    raw_end = data.get("period_end") or data.get("period")
    if not raw_end or "period_conflict" in (data.get("issues") or []):
        return None
    try:
        end = date.fromisoformat(str(raw_end)[:10])
    except (TypeError, ValueError):
        return None
    metric = str(data.get("metric") or data.get("indicator") or "")
    stored_kind = normalize_period_kind(data.get("period_type"))
    label_kind = label_period_kind(metric, end)
    kind = stored_kind or 'unknown'
    # 兼容防线：旧产物把「当月值」写成 annual + 2025-01-01 起日。
    # 这条记录可以按月度观测读取，但绝不能继续支撑全年断言。
    if label_kind == 'month' and kind in ('annual', 'unknown'):
        kind = 'month'
    if kind == 'unknown':
        kind = label_kind or _date_shape_kind(end)
    start = period_start_for(kind, end)
    raw_start = _parse_loose_date(data.get("period_start"))
    if raw_start is not None:
        if kind == 'month' and label_kind == 'month':
            start = period_start_for('month', end)
        elif stored_kind and start is not None and raw_start != start:
            return None
        else:
            start = raw_start
    if start is None or start > end:
        return None
    expected_ends = {"annual": (12,31), "half_year": (6,30), "ytd_q3": (9,30), "q1": (3,31)}
    if kind in expected_ends and (end.month, end.day) != expected_ends[kind]:
        return None
    if kind == 'quarter' and end.month not in (3, 6, 9, 12):
        return None
    if kind == 'point' and start != end:
        return None
    return start, end, kind


def comparable_key(record: Any, *, include_year: bool = True) -> tuple | None:
    period = measurement_period(record)
    if period is None:
        return None
    start, end, kind = period
    data = _as_dict(record)
    return (end if include_year else (end.month, end.day), kind,
            start if include_year else (start.month, start.day),
            data.get("scope", "consolidated"), data.get("currency", "CNY"))


def verified_calculations(rows: list[dict], index: dict[str, Any], allowed_ids: list[str]) -> list[dict]:
    """Only recalculate declared formulas using the same entity and full duration."""
    import math
    observations = []
    for row in rows:
        for metric, calc in (row.get("calculations") or {}).items():
            ids = calc.get("input_record_ids") or []
            if len(ids) != 2 or not set(ids).issubset(allowed_ids) or any(rid not in index for rid in ids):
                continue
            a, b = (_as_dict(index[rid]) for rid in ids)
            entity = a.get("entity") or a.get("entity_name")
            if not entity or entity != (b.get("entity") or b.get("entity_name")) or row.get("company") != entity:
                continue
            pa, pb = measurement_period(a), measurement_period(b)
            if pa is None or pa != pb or a.get("scope", "consolidated") != b.get("scope", "consolidated") or a.get("currency", "CNY") != b.get("currency", "CNY"):
                continue
            formula = {
                "cash_to_net_profit": ("operating_cash_flow", "parent_net_profit", 1, "倍"),
                "rd_ratio": ("rd_expense", "revenue", 100, "%"),
                "net_margin": ("net_profit", "revenue", 100, "%"),
            }.get(metric)
            if formula is None:
                continue
            numerator, denominator, multiplier, unit = formula
            expected = f"{numerator}/{denominator}" + ("*100" if multiplier == 100 else "")
            if (calc.get("formula") != expected or metric_family(a.get("metric", "")) != numerator
                    or metric_family(b.get("metric", "")) != denominator):
                continue
            try:
                numerator_value = money_to_yuan(a["value"], a["unit"])
                base = money_to_yuan(b["value"], b["unit"])
                if (numerator_value is None or base is None or not numerator_value.is_finite()
                        or not base.is_finite() or base <= 0
                        or (metric in {"cash_to_net_profit", "net_margin"} and base < 5e6)
                        or any(ref.get("unit_provenance") == "unknown"
                               or any("conflict" in issue for issue in ref.get("issues") or [])
                               for ref in (a, b))):
                    continue
                value = float(numerator_value / base * multiplier)
            except (TypeError, ValueError, ZeroDivisionError, KeyError):
                continue
            if not math.isfinite(value):
                continue
            observations.append(dict(record_id="derived:" + "/".join(ids), entity=entity,
                metric=metric, value=value, unit=unit, period=str(pa[1]), period_start=str(pa[0]),
                period_type=pa[2], scope=a.get("scope", "consolidated"), currency=a.get("currency", "CNY")))
    return observations


def financial_calculation_rows(ratios: list[dict], comps: dict | None) -> list[dict]:
    """Keep the A2 formulas attached to their operands through both text gates."""
    rows = list(ratios)
    for entry in (comps or {}).get("entries") or []:
        if not isinstance(entry, dict):
            continue
        calculation = (entry.get("metric_provenance") or {}).get("net_margin")
        if isinstance(calculation, dict) and calculation.get("input_record_ids"):
            rows.append({"company": entry.get("company_name"), "calculations": {"net_margin": calculation}})
    return rows


def covered_data_gap_filter(index: dict[str, Any], coverage_rows: list[dict],
                            ratios: list[dict]) -> Callable[[str], str]:
    """Build a filter for missing-data statements contradicted by verified source records."""
    coverage = {row["requirement_id"]: row for row in coverage_rows
                if row.get("requirement_id") and row.get("passed")}
    segment_ids = coverage.get("business_composition", {}).get("evidence_record_ids", [])
    segment_complete = bool(segment_ids) and all(
        rid in index and (ref := _as_dict(index[rid])).get("skill_id") == "official-segment"
        and ref.get("segment_name") and ref.get("source_url") and ref.get("value") is not None
        for rid in segment_ids
    )
    ratio_entities = {
        item["entity"] for item in verified_calculations(ratios, index, list(index))
        if item["metric"] == "rd_ratio"
    }
    all_entities = {
        str(ref.get("entity") or ref.get("entity_name")) for value in index.values()
        if (ref := _as_dict(value)).get("entity") or ref.get("entity_name")
    }

    def keep(sentence: str) -> bool:
        if (segment_complete and re.search(r"主营业务构成|分产品(?:收入|构成)", sentence)
                and re.search(r"未在.{0,12}提供|未提供.{0,8}(?:构成明细|分产品数据)|没有.{0,8}构成明细", sentence)):
            return bool(re.search(r"历史|其他年度|资本化|分部利润|供应商|地区", sentence))
        if "研发" not in sentence:
            return True
        if limited := re.search(r"研发(?:强度|费用率).{0,8}(?:仅|只能)([^。；;，,]+)(?:可计算|可核验)", sentence):
            named = {name for name in ratio_entities if name in limited[1]}
            if named and ratio_entities - named:
                return False
        if re.search(r"研发(?:费用|投入).{0,16}(?:未.{0,8}提供|缺失|无可用)", sentence):
            named = {name for name in all_entities if len(name) >= 3 and name in sentence}
            if named and named <= ratio_entities and not re.search(r"资本化|分部|季度|历史", sentence):
                return False
        return True

    return lambda text: retain_supported_claims(text, keep)


def claim_period_matches(context: str, ref: dict, year: int | None, family: str | None) -> bool:
    period = measurement_period(ref)
    qualifiers = r"全年|年度|年报|上半年|半年度|中报|半年报|前三季度|三季报|第一季度|一季度|一季报|第二季度|第三季度|第四季度|单季|当季"
    if period is None:
        flow = metric_family(str(ref.get("metric", ""))) in ("revenue", "parent_net_profit", "net_profit", "operating_cash_flow", "gross_margin", "net_margin", "revenue_yoy", "net_profit_yoy", "cash_to_net_profit")
        return not (flow or year or re.search(qualifiers, context))
    start, end, kind = period
    named = list(_NAMED_PERIOD.finditer(context))
    claimed_date = None
    if named:
        last = named[-1]
        year = int(last.group(1))
        if '-' in last.group(0):
            try:
                claimed_date = date.fromisoformat(last.group(0))
            except ValueError:
                return False
            if end != claimed_date:
                return False
    if year and end.year != year:
        return False
    # The latest explicit ISO date/year scopes this observation's duration.
    label = context[named[-1].end():] if named else context
    quarter_match = re.search(r"第?([一二三四1-4])季度", label)
    quarter = ("一二三四".find(quarter_match.group(1)) + 1 if quarter_match and quarter_match.group(1) in "一二三四" else int(quarter_match.group(1)) if quarter_match else None)
    if re.search(r"前三季度|三季报", label):
        return (start.month,start.day,end.month,end.day) == (1,1,9,30) and kind != "quarter"
    if re.search(r"上半年|半年度|中报|半年报", label):
        return (start.month,start.day,end.month,end.day) == (1,1,6,30) and kind != "quarter"
    if "一季报" in label:
        return (start.month,start.day,end.month,end.day) == (1,1,3,31)
    if quarter:
        month = (quarter-1)*3+1
        final_month = quarter*3
        final_day = 30 if quarter in (2,3) else 31
        return (start.month,start.day,end.month,end.day) == (month,1,final_month,final_day)
    if re.search(r"单季|当季", label):
        return kind in ("quarter","q1")
    if re.search(r"全年|年度|年报", label):
        return kind == "annual" and (start.month,start.day,end.month,end.day) == (1,1,12,31)
    # A bare financial year denotes the full year, unless an explicit cutoff date is supplied.
    flow = family in ("revenue","parent_net_profit","net_profit","operating_cash_flow","gross_margin","net_margin","revenue_yoy","net_profit_yoy","cash_to_net_profit")
    if year and flow and claimed_date is None and not re.search(r"截至|截止|年初至今|\d{1,2}月", label):
        return kind == "annual"
    return True


def metric_family(metric: str) -> str:
    """Exact aliases. In particular dynamic PE is never TTM, float cap never total."""
    key = re.sub(r'[\[［].*?[\]］]', '', metric).strip().casefold()
    aliases = {
        '最新市盈率ttm': 'pe_ttm', '市盈率ttm': 'pe_ttm', '市盈率(ttm)': 'pe_ttm',
        '最新动态市盈率': 'pe_dynamic', '动态市盈率': 'pe_dynamic', '市盈率(动)': 'pe_dynamic',
        '最新静态市盈率': 'pe_lyr', '静态市盈率': 'pe_lyr', '市盈率(静)': 'pe_lyr',
        '净利润': 'net_profit', '营业收入同比增长率': 'revenue_yoy', '归母净利润同比增长率': 'net_profit_yoy', '营业收入': 'revenue', '营业总收入': 'revenue', '营收': 'revenue',
        '归母净利润': 'parent_net_profit', '归属于母公司股东的净利润': 'parent_net_profit',
        '归属于母公司所有者的净利润': 'parent_net_profit',
        '经营活动产生的现金流量净额': 'operating_cash_flow', '经营现金流': 'operating_cash_flow',
        '研发费用': 'rd_expense', '研发投入': 'rd_investment', '研发费用率': 'rd_ratio',
        '研发费用占营业收入的比例': 'rd_ratio', '研发投入占营业收入比例': 'rd_investment_ratio',
        '研发投入占比': 'rd_investment_ratio',
        '光伏新增装机量': 'pv_new_capacity', '中国光伏新增装机量': 'pv_new_capacity',
        '中国光伏新增装机容量': 'pv_new_capacity', '光伏新增装机容量': 'pv_new_capacity',
        '新增光伏装机容量': 'pv_new_capacity',
        '新能源汽车销量': 'nev_sales', '中国新能源汽车销量': 'nev_sales',
        '市场渗透率': 'nev_penetration', '新能源汽车市场渗透率': 'nev_penetration',
        '中国新能源汽车市场渗透率': 'nev_penetration',
        # 问财长表把期间限定词写进指标名；家族归一后仍属同一渗透率观测。
        '国内零售渗透率:新能源汽车:当月值': 'nev_penetration',
        '国内零售渗透率:新能源汽车:年度值': 'nev_penetration',
        '新能源汽车:渗透率:年度': 'nev_penetration',
        '新能源汽车:渗透率:当月': 'nev_penetration',
        # 模型需求词常只写「渗透率」；空车行业以外的行业不会复用该家族，
        # 白名单按 domain=industry 再匹配一次，故不会误命中其它行业。
        '渗透率': 'nev_penetration', '新能源渗透率': 'nev_penetration',
        'penetration rate': 'nev_penetration',
        '新能源汽车:销量:年度值': 'nev_sales',
        '新能源汽车:销量:累计值': 'nev_sales',
        '新能源汽车:市场渗透率:中汽协全口径': 'nev_penetration',
        '新能源汽车:出口量:中汽协口径': 'nev_exports',
        '新能源汽车出口量': 'nev_exports', '中国新能源汽车出口量': 'nev_exports',
        # AB：模型需求里常写成交付/描述性说法，统一归到同一家族，否则
        # 「出口量」与「新能源汽车出口」会被当成两个家族，白名单匹配失败。
        '出口量': 'nev_exports', '新能源汽车出口': 'nev_exports',
        '新能源汽车:出口量': 'nev_exports', '中国新能源汽车:出口量': 'nev_exports',
        'export volume': 'nev_exports', 'nev export': 'nev_exports',
        # 研发强度是比率类家族，与研发费用（金额）严格区分：问财原生字段为
        # 「研发费用 / 营业收入」，直接命中该列名。
        '研发强度': 'rd_ratio', '研发投入强度': 'rd_ratio',
        '研发费用/营业收入': 'rd_ratio', '研发费用 / 营业收入': 'rd_ratio',
        '研发投入/营业收入': 'rd_ratio', '研发投入 / 营业收入': 'rd_ratio',
        '经营活动现金流净额': 'operating_cash_flow',
        '经营活动现金流量净额': 'operating_cash_flow',
        '销售毛利率': 'gross_margin', '毛利率': 'gross_margin',
        '销售净利率': 'net_margin', '净利率': 'net_margin',
        '最新总市值': 'market_cap', '总市值': 'market_cap',
        '最新a股流通市值': 'circulating_market_cap', 'a股流通市值': 'circulating_market_cap',
        '流通市值': 'circulating_market_cap',
    }
    return aliases.get(key, key)


def chart_comparability_issues(refs: list[Any], *, temporal: bool) -> list[str]:
    """Check observed measurement contracts before selection and again at delivery."""
    if not refs:
        return []
    rows = [_as_dict(ref) for ref in refs]
    problems = []
    if any(measurement_period(row) is None for row in rows):
        problems.append("缺少有效观测期间，只能作为受限资料展示，不能正式比较")
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(metric_family(str(row.get("metric") or "")), []).append(row)
    for records in groups.values():
        if len({r.get("scope", "consolidated") for r in records}) > 1 or len({r.get("currency", "CNY") for r in records}) > 1:
            problems.append("比较样本的测量范围或币种不一致")
        periods = {measurement_period(r) for r in records if measurement_period(r) is not None}
        if temporal:
            shapes = {("point",) if kind == "point" else
                      ("quarter", 3) if kind in ("quarter", "q1") else
                      (kind, (end.year - start.year) * 12 + end.month - start.month + 1, start.day)
                      for start, end, kind in periods}
            if len(shapes) > 1:
                problems.append("时间序列混合不同长度或定义的报告期间")
        elif len({r.get("entity") or r.get("entity_name") for r in records}) > 1 and len(periods) > 1:
            problems.append("横截面样本缺少共同观测期间，不能作同期间比较")
    return list(dict.fromkeys(problems))

# Terms describe measurements, not merely a matching number somewhere in a record.
CLAIM_METRICS = {
    '新能源汽车销量': 'nev_sales', '新能源汽车出口量': 'nev_exports',
    '营业收入同比增长率': 'revenue_yoy', '营收同比': 'revenue_yoy', '营收增速': 'revenue_yoy',
    '归母净利润同比增长率': 'net_profit_yoy', '利润增速': 'net_profit_yoy',
    '营业收入': 'revenue', '营收': 'revenue', '归母净利润': 'parent_net_profit',
    '归母净利': 'parent_net_profit', '净利润': 'net_profit',
    '经营现金流': 'operating_cash_flow', '经营活动现金流': 'operating_cash_flow',
    '经营活动产生的现金流量净额': 'operating_cash_flow',
    '研发费用率': 'rd_ratio', 'rd_ratio': 'rd_ratio',
    '毛利率': 'gross_margin', '净利率': 'net_margin', '净现比': 'cash_to_net_profit',
    'gross_margin': 'gross_margin', 'net_margin': 'net_margin',
    '动态市盈率': 'pe_dynamic', 'PE(TTM)': 'pe_ttm', 'PE（TTM）': 'pe_ttm',
    'TTM': 'pe_ttm', '市盈率': 'pe', '市净率': 'pb', 'PB': 'pb',
    '流通市值': 'circulating_market_cap', '总市值': 'market_cap', '资产负债率': 'debt_ratio',
    'ROE': 'roe', '净资产收益率': 'roe', '最新价': 'latest_price', '股价': 'latest_price',
}
QUANTITY_RE = re.compile(r'(?<![\dA-Za-z])([-+−]?\d[\d,]*(?:\.\d+)?)\s*'
                         r'(万亿元|亿元|千万元|百万元|万元|千元|亿辆|万辆|万台|亿台|万套|亿套|万人次|元|%|％|倍|家|辆|万吨|吨|台|套|人次|GWh|GW|个百分点)?')
_COUNT_UNITS = {
    prefix + base: (base, scale)
    for base in ('辆', '台', '套', '吨', '人次')
    for prefix, scale in (('', 1), ('万', 10_000), ('亿', 100_000_000))
}
_CHART_REFERENCE = re.compile(r'\[CHART-[\w.-]+\]')
_YEAR_RANGE = re.compile(r'((?:19|20)\d{2})\s*年?\s*(?:[-—–至到~～])\s*((?:19|20)\d{2})\s*年')
_CAGR = re.compile(r'复合(?:年均|年化)?(?:增长率|增长|增速)|CAGR', re.I)
_EXPORT_SHARE = re.compile(r'出口(?:量)?(?:占|/).{0,18}销量')
_NEV_METRICS = {'总销量': 'nev_sales', '销量': 'nev_sales', '出口量': 'nev_exports', '出口': 'nev_exports'}


def _scaled_unit(unit: str) -> tuple[str, int]:
    if unit in MONEY_UNIT_SCALES:
        return 'money', MONEY_UNIT_SCALES[unit]
    return _COUNT_UNITS.get(unit, (unit, 1))


def _as_dict(value: Any) -> dict:
    return value.model_dump(mode='json') if hasattr(value, 'model_dump') else dict(value)


# Numeric thousands separators and decimal points do not end a claim clause.
_CLAUSE_BOUNDARY = re.compile(r'[。；;\n！？!?，]|(?<!\d),|,(?!\d)|(?<!\d)\.|\.(?!\d)')
_CAUSAL = re.compile(r'证明|证实|必然|表明|反映|意味着|说明了|由于|导致|造成|推动|带动|归因于|源于|驱动(?!因素|因子|机制|模型|分析)|印证|利润分配.*重构|利润池.*转移|(?:说明|体现)(?=.*(?:议价权|应收|存货|利润池|业务|分部))')
_PROFIT_SHIFT = re.compile(r"(?:产业链)?利润(?:分配|池).{0,18}(?:倾斜|迁移|转向|集中到)")
_GROWTH_SHIFT = re.compile(r"增长重心.{0,12}(?:转移|转向|移向|偏向)|油价.{0,12}(?:强化|削弱).{0,12}出口优势")
_UNCERTAIN_CAUSE = re.compile(r'假设|可能|或许|待验证|不能证明|并不证明|不能表明|不能说明|不意味着|并不意味着|不足以|无法|未必|不代表')
_ASSUMPTION_INPUT = re.compile(r'假设|如果|若|设定|敏感性')
_SCENARIO_OUTPUT = re.compile(r'(?<!准)则|因此|从而|由此|导致|使得|会使|推算|测算|计算得|可得|分析显示|模型结果|推演结果|敏感性结果|结果为|输出')


_REPORT_CLAUSE_END = re.compile(r"[。；;\n！？!?]")


def retain_supported_claims(text: str, is_supported: Callable[[str], bool]) -> str:
    """Keep independently supported clauses, including their punctuation."""
    kept = []
    start = 0
    for boundary in _REPORT_CLAUSE_END.finditer(text):
        clause = text[start:boundary.start()].strip()
        if clause and is_supported(clause):
            kept.append(clause + boundary.group())
        start = boundary.end()
    tail = text[start:].strip()
    if tail and is_supported(tail):
        kept.append(tail)
    return "".join(kept).strip()


def _claim_clauses(text: str) -> list[tuple[int, int, str]]:
    spans = []
    start = 0
    for boundary in _CLAUSE_BOUNDARY.finditer(text):
        spans.append((start, boundary.start(), text[start:boundary.start()].strip()))
        start = boundary.end()
    spans.append((start, len(text), text[start:].strip()))
    return spans


def _scope_matches_claim(context: str, scope: str) -> bool:
    scope = (scope or "consolidated").strip()
    segment_claim = bool(re.search(r"分部|分业务|[\u4e00-\u9fff]{2,12}(?:业务|板块)", context)) and not re.search(r"主营业务|公司业务|业务整体", context)
    if segment_claim:
        if scope in ("consolidated", "parent", "group", "unknown", "segment"):
            return False
        if scope in context or scope.casefold() in context.casefold():
            return True
        if scope.startswith("battery") and "电池" in context:
            return True
        if scope.startswith("auto") and "汽车" in context:
            return True
        return False
    return scope in ("consolidated", "parent", "group", "")


def _claimed_duration(context: str) -> str | None:
    if re.search(r"前三季度|三季报", context):
        return "ytd_q3"
    if re.search(r"上半年|半年度|中报|半年报", context):
        return "half_year"
    if re.search(r"一季报", context):
        return "q1"
    quarter_match = re.search(r"第?([一二三四1-4])季度", context)
    if quarter_match:
        q = "一二三四".find(quarter_match.group(1)) + 1 if quarter_match.group(1) in "一二三四" else int(quarter_match.group(1))
        return "q1" if q == 1 else "quarter"
    if re.search(r"单季|当季", context):
        return "quarter"
    if re.search(r"全年|年度|年报", context):
        return "annual"
    return None


def _row_matches_token(row: tuple, token: str) -> bool:
    _, period, _, _ = row
    end_date = period[1]
    iso_match = _ISO_DATE.search(token)
    if iso_match:
        try:
            return end_date == date.fromisoformat(iso_match.group(1))
        except ValueError:
            return False
    year_match = re.search(r'((?:19|20)\d{2})', token)
    if year_match:
        return end_date.year == int(year_match.group(1))
    return False


def _verified_change(context: str, local_prefix: str, refs: list[dict], family: str | None,
                     entity: str | None, unit: str | None, *, yoy: bool = False) -> float | None:
    """Recompute an unambiguous comparison from bound comparable observations."""
    if not family or not entity:
        return None
    named = list(dict.fromkeys(m.group(0) for m in _NAMED_PERIOD.finditer(context)))
    selected_periods = named[-2:] if len(named) >= 2 else []
    rows = {}
    for ref in refs:
        if (ref.get('entity') or ref.get('entity_name')) != entity or metric_family(str(ref.get('metric', ''))) != family:
            continue
        scope = str(ref.get('scope') or 'consolidated')
        if not _scope_matches_claim(context, scope):
            continue
        period = measurement_period(ref)
        if period is None or ref.get('conflicted') or any('conflict' in issue for issue in ref.get('issues', [])):
            continue
        if selected_periods and not any(str(period[1]) == label if '-' in label else period[1].year == int(label[:4]) for label in selected_periods):
            continue
        try:
            if isinstance(ref.get('value'), bool):
                continue
            value = float(ref['value'])
        except (ValueError, TypeError, KeyError):
            continue
        if not math.isfinite(value):
            continue
        source_unit = str(ref.get('unit') or '')
        points = _rate_points(value, source_unit)
        if points is not None:
            value, dimension = points, 'percent'
        elif source_unit:
            dimension, scale = _scaled_unit(source_unit)
            value *= scale
        else:
            continue
        key = (period, comparable_key(ref, include_year=False), dimension, value)
        rows[key] = (ref, period, value, dimension)
    # Duplicate identical evidence is harmless; conflicting or extra observations
    # cannot acquire a winner merely because one pair matches the prose number.
    if len(rows) != 2:
        return None
    r1, r2 = list(rows.values())
    if comparable_key(r1[0], include_year=False) != comparable_key(r2[0], include_year=False) or r1[3] != r2[3]:
        return None

    # Check claimed duration vs observation duration
    claimed_dur = _claimed_duration(context)
    if claimed_dur is not None:
        if r1[1][2] != claimed_dur and not (claimed_dur == "quarter" and r1[1][2] in ("quarter", "q1")):
            return None
    else:
        has_iso = bool(_ISO_DATE.search(context))
        if not has_iso and family in ("revenue", "parent_net_profit", "net_profit", "operating_cash_flow",
                                      "gross_margin", "net_margin", "revenue_yoy", "net_profit_yoy",
                                      "cash_to_net_profit"):
            if r1[1][2] != "annual":
                return None

    # Determine from_row (base) and to_row (target)
    from_to = re.search(
        r'从\s*((?:19|20)\d{2}(?:年|-\d{2}-\d{2})?)\s*(?:到|至)\s*((?:19|20)\d{2}(?:年|-\d{2}-\d{2})?)',
        context
    )
    if not from_to:
        from_to = re.search(
            r'((?:19|20)\d{2}(?:年|-\d{2}-\d{2})?)\s*(?:到|至)\s*((?:19|20)\d{2}(?:年|-\d{2}-\d{2})?)',
            context
        )

    compare = None
    if not from_to:
        compare = re.search(
            r'((?:19|20)\d{2}(?:年|-\d{2}-\d{2})?).*?(?:较|比|相比)\s*((?:19|20)\d{2}(?:年|-\d{2}-\d{2})?)',
            context
        )

    if from_to:
        token_from, token_to = from_to.group(1), from_to.group(2)
        if _row_matches_token(r1, token_from) and _row_matches_token(r2, token_to):
            from_row, to_row = r1, r2
        elif _row_matches_token(r2, token_from) and _row_matches_token(r1, token_to):
            from_row, to_row = r2, r1
        else:
            return None
    elif compare:
        token_to, token_from = compare.group(1), compare.group(2)
        if _row_matches_token(r1, token_from) and _row_matches_token(r2, token_to):
            from_row, to_row = r1, r2
        elif _row_matches_token(r2, token_from) and _row_matches_token(r1, token_to):
            from_row, to_row = r2, r1
        else:
            return None
    elif len(named) >= 2:
        token_from, token_to = named[-2], named[-1]
        if _row_matches_token(r1, token_from) and _row_matches_token(r2, token_to):
            from_row, to_row = r1, r2
        elif _row_matches_token(r2, token_from) and _row_matches_token(r1, token_to):
            from_row, to_row = r2, r1
        else:
            earlier, later = sorted([r1, r2], key=lambda row: row[1][1])
            from_row, to_row = earlier, later
    elif len(named) == 1:
        earlier, later = sorted([r1, r2], key=lambda row: row[1][1])
        label = named[0]
        # The single named change year must be the current observation (later period).
        if not _row_matches_token(later, label):
            return None
        from_row, to_row = earlier, later
    else:
        earlier, later = sorted([r1, r2], key=lambda row: row[1][1])
        from_row, to_row = earlier, later

    if from_row[1] == to_row[1]:
        return None
    if yoy and to_row[1][1].year - from_row[1][1].year != 1:
        return None

    delta = to_row[2] - from_row[2]
    if unit is None:
        change = delta
    elif unit == '个百分点':
        if from_row[3] != 'percent':
            return None
        change = delta
    elif unit in ('%', '％'):
        if from_row[2] == 0:
            return None
        if from_row[2] < 0 and not _ABSOLUTE_BASE.search(context):
            # 负基期的「同比增长」在算术上合法但业务上无意义（扭亏会算成负增长），
            # 只有明确声明按基期绝对值时才按描述性口径放行。
            return None
        change = delta / abs(from_row[2]) * 100
    elif from_row[3] == _scaled_unit(unit)[0]:
        change = delta / _scaled_unit(unit)[1]
    else:
        return None
    directions = list(re.finditer(r'下降|降低|减少|回落|上升|提升|提高|增长|增加|持平|相对变化|相对变动|变化|变动', local_prefix))
    direction = directions[-1].group(0) if directions else ''
    if direction in ('下降', '降低', '减少', '回落'):
        return abs(change) if delta < 0 else None
    if direction in ('上升', '提升', '提高', '增长', '增加'):
        return abs(change) if delta > 0 else None
    if direction == '持平':
        return 0.0 if delta == 0 else None
    return change


def _market_quantity(ref: dict, entity: str, family: str, year: int) -> tuple[tuple, float] | None:
    if ((ref.get('entity') or ref.get('entity_name')) != entity
            or metric_family(str(ref.get('metric') or '')) != family or ref.get('conflicted')
            or any('conflict' in issue for issue in (ref.get('issues') or []))):
        return None
    period = measurement_period(ref)
    dimension, scale = _scaled_unit(str(ref.get('unit') or ''))
    value = ref.get('value')
    if (period is None or period[2] != 'annual' or period[1].year != year or dimension != '辆'
            or type(value) not in (int, float) or not math.isfinite(value) or value < 0):
        return None
    return comparable_key(ref, include_year=False), value * scale


def _market_calculation(context: str, refs: list[dict], family: str | None,
                        entity: str | None, year: int | None, formula: str) -> float | None:
    if not entity or family not in ('nev_sales', 'nev_exports') or not year:
        return None
    base_year = year - 1
    if formula == 'cagr':
        years = _YEAR_RANGE.search(context)
        if not years:
            return None
        base_year, year = map(int, years.groups())
        if base_year >= year:
            return None
    base_family, target_family = family, family
    if formula == 'share':
        base_year = year
        base_family, target_family = 'nev_sales', 'nev_exports'
    rows = [
        {row for ref in refs if (row := _market_quantity(ref, entity, metric, period_year)) is not None}
        for metric, period_year in ((base_family, base_year), (target_family, year))
    ]
    if any(len(values) != 1 for values in rows):
        return None
    (base_key, base), (target_key, target) = (next(iter(values)) for values in rows)
    if base_key != target_key or base <= 0:
        return None
    scope = str(target_key[3] or "")
    if scope not in ("consolidated", "group") and (not scope or scope not in context):
        return None
    if formula == 'share':
        return target / base * 100 if target <= base else None
    if formula == 'cagr':
        return ((target / base) ** (1 / (year - base_year)) - 1) * 100
    return (target / base - 1) * 100


_SECURITY_CODE = re.compile(r'\d{6}(?:\.(?:SZ|SH|BJ))?', re.I)


def _is_security_code(text: str, match: 're.Match[str]') -> bool:
    """A six-digit ticker is an identifier, never a measured quantity."""
    if match.group(2):
        return False
    raw = match.group(1).replace(',', '')
    if raw.startswith(('+', '-', '−')) or not (raw.isdigit() and len(raw) == 6):
        return False
    after = text[match.end():]
    if re.match(r'\s*\.(?:SZ|SH|BJ)(?![A-Za-z])', after, re.I):
        return True
    return bool(re.search(r'[（(]\s*$', text[:match.start()]))


def quantity_issues(text: str, evidence: list[Any], *, universe: list[Any] = (),
                    assumption_note: str | None = None, kind: str = '', location: str = '',
                    comparisons: Sequence[dict] = ()) -> list[dict]:
    """Fail closed on a numeric claim without matching measurement semantics.

    Rounding tolerance is half the displayed final digit, never a percentage of
    the claim. A matching real ID by itself is insufficient.
    """
    refs = [_as_dict(e) for e in evidence]
    text = _CHART_REFERENCE.sub(lambda match: " " * len(match.group()), text)
    all_refs = [_as_dict(e) for e in universe] or refs
    known_entities = {str(e.get('entity') or e.get('entity_name') or '') for e in all_refs} - {''}
    claim_metrics = CLAIM_METRICS
    if any(metric_family(str(ref.get("metric") or "")) in ("nev_sales", "nev_exports") for ref in refs):
        claim_metrics = CLAIM_METRICS | _NEV_METRICS
    issues = []
    clauses = _claim_clauses(text)
    iso_dates = _valid_iso_dates(text)
    for start, _, clause_text in clauses:
        causal = _CAUSAL.search(clause_text) or _PROFIT_SHIFT.search(clause_text) or _GROWTH_SHIFT.search(clause_text)
        if causal and not _UNCERTAIN_CAUSE.search(clause_text):
            attributed = bool(re.search(r"据|称|认为|预计|预测", text[max(0, start - 35):start] + clause_text))
            direct_support = False
            for ref in refs:
                value = ref.get("value")
                if not isinstance(value, str) or clause_text not in value:
                    continue
                offset = value.index(clause_text)
                opinion = ref.get("domain") in {"news", "events", "reports"} and bool(
                    re.search(r"预计|预测|认为|观点|展望", value[max(0, offset - 35):offset])
                )
                if attributed or not opinion:
                    direct_support = True
                    break
            if not direct_support:
                issues.append(dict(code="unsupported_causal_claim", severity="error", location=location,
                    claim=clause_text, evidence_ids=[r.get("record_id") for r in refs],
                    suggestion="补充直接证据，或在该因果子句中明确标记为待验证假设。"))
        direction = re.search(r"下降|下滑|降低|减少|回落|上升|提升|提高|增长|增加|持平", clause_text)
        group_cash_claim = bool(re.search(
            r"(?:电池|整车)(?:环节|组).{0,12}(?:经营)?现金流.{0,6}(?:增长|收缩|下降|上升|减少|增加)",
            clause_text,
        ))
        forecast = bool(re.search(r"未来|将持续|将继续|势必", clause_text))
        qualitative_comparison = bool(direction and not QUANTITY_RE.search(
            _NAMED_PERIOD.sub("", clause_text)) and len(_NAMED_PERIOD.findall(clause_text)) >= 2)
        continuous = bool(direction and re.search(r"持续|连续", clause_text))
        unbounded_rank = bool(re.search(
            r"(?:行业|市场|同业|同行)(?:中)?(?:领先|第一|最高)"
            r"|(?:盈利|现金流)质量(?:最佳|最优|最强|优于)", clause_text,
        ))
        if (group_cash_claim or unbounded_rank or (direction and (forecast or qualitative_comparison or continuous))) and not re.search(
            r"假设|如果|可能|或许|待验证|无法|不足以|不一定|是否|不能|风险在于|目标是", clause_text
        ):
            entities = [name for name in known_entities if name in clause_text]
            entity = max(entities, key=len, default=None)
            matches = [term for term in claim_metrics if term.casefold() in clause_text.casefold()]
            family = claim_metrics[max(matches, key=len)] if matches else None
            direction_text = clause_text.replace("下滑", "下降")
            measured = (
                not (group_cash_claim or forecast or continuous or unbounded_rank)
                and _verified_change(direction_text, direction_text, refs, family, entity, None) is not None
            )
            if not measured:
                issues.append(dict(code="unsupported_direction_claim", severity="error", location=location,
                    claim=clause_text, evidence_ids=[r.get("record_id") for r in refs],
                    suggestion="补充同口径观测，或明确区分已观察变化与待验证假设。"))
    for match in QUANTITY_RE.finditer(text):
        if any(start <= match.start() < end for start, end, _ in iso_dates):
            continue
        if _is_security_code(text, match):
            continue
        raw, unit = match.groups()
        raw = raw.replace(',', '').replace('−', '-')
        value = float(raw)
        if unit is None and (1900 <= value <= 2099 and value.is_integer()):
            continue
        # A bare 1-31 immediately followed by 月/日/号 is a calendar token, not
        # a measured quantity. This keeps "2025 年 12 月当月..." auditable
        # against a monthly record instead of flagging the month ordinal.
        if unit is None and 1 <= value <= 31 and value.is_integer() and re.match(
            r"\s*(?:月|日|号)", text[match.end():]
        ):
            continue
        if unit is None and re.search(r"(?:图|表|第)\s*$", text[:match.start()]):
            continue
        decimals = len(raw.split('.')[1]) if '.' in raw else 0
        tolerance = 0.5 * 10 ** -decimals + 1e-9
        before = text[:match.start()]
        clause = re.split(r'[。；;\n]', before)[-1]
        context = clause[-100:]
        selected = [(context.casefold().rfind(term.casefold()), len(term), family)
                    for term, family in claim_metrics.items() if term.casefold() in context.casefold()]
        # A longer measurement phrase wins when terms overlap at the same end.
        selected_metric = max(selected, key=lambda x: (x[0] + x[1], x[1])) if selected else None
        family = selected_metric[2] if selected_metric else None
        metric_tail = context[selected_metric[0] + selected_metric[1]:] if selected_metric else ""
        if family in ("revenue", "net_profit", "parent_net_profit") and re.search(r"同比|增速|增长率", metric_tail):
            family = "revenue_yoy" if family == "revenue" else "net_profit_yoy"
        if unit is None:
            if family in ("pe", "pe_ttm", "pe_dynamic", "pe_lyr", "pb", "ps", "cash_to_net_profit"):
                unit = "倍"
            elif family and (family.endswith("margin") or family.endswith("_yoy") or family in ("roe", "debt_ratio")):
                unit = "%"
            else:
                units = {r.get("unit") for r in refs if metric_family(str(r.get("metric"))) == family}
                unit = next(iter(units)) if len(units) == 1 else None
            if not family and value.is_integer() and 0 <= value <= 10:
                continue
        mentioned = [(before.rfind(e), e) for e in known_entities if e in before]
        entity = max(mentioned)[1] if mentioned else None
        explicit = re.search(r'([\u4e00-\u9fff]{2,12})\s*(?:20\d{2})年', context)
        if explicit and not entity:
            entity = explicit.group(1).removeprefix('公司')
        named_periods = list(_NAMED_PERIOD.finditer(context))
        year = int(named_periods[-1].group(1)) if named_periods else None
        local_clause = next((part for start, end, part in clauses if start <= match.start() < end), "")
        scenario_context = kind in ('scenario', 'methodology', 'risk') and bool(
            assumption_note or re.search(r'情景假设|敏感性', text))
        probabilistic = bool(re.search(r'概率|胜率|目标价|目标市值', context))
        # An explicit input assumption is not a licence for another clause's
        # forecast output. This contract has no verified scenario-model channel;
        # a hypothetical result cannot borrow matching historical observations.
        if scenario_context and _ASSUMPTION_INPUT.search(text) and _SCENARIO_OUTPUT.search(local_clause):
            issues.append(dict(code='unsupported_sensitivity_output', severity='error', location=location,
                claim=match.group(0), metric=family, entity=entity, year=year,
                evidence_ids=[r.get('record_id') for r in refs],
                suggestion='补充可重算的敏感性模型、输入来源和公式；输入假设不能替代派生结果依据。'))
            continue
        is_assumption = scenario_context and _ASSUMPTION_INPUT.search(local_clause)
        if is_assumption and not probabilistic:
            continue
        supported = False
        local_start = next((start for start, end, _ in clauses if start <= match.start() < end), 0)
        local_prefix = text[local_start:match.start()]
        if family in ('nev_sales', 'nev_exports') and unit in _COUNT_UNITS and (year_range := _YEAR_RANGE.search(context)):
            after = text[match.end():]
            if re.search(r'从\s*$', context) and re.match(r'\s*(?:增|升|增长|降|下降)?(?:至|到)', after):
                year = int(year_range[1])
                # Scope the first endpoint to the start of the explicitly named range.
                start, end = year_range.span()
                context = f"{context[:start]}{year}年{context[end:]}"
            elif re.search(r'从\s*[-+]?\d[\d,.]*\s*(?:万|亿)?辆\s*(?:增|升|增长|降|下降)?(?:至|到)\s*$', context):
                year = int(year_range[2])
        change_tail = local_prefix if re.search(r'相对变化|相对变动', local_prefix) else metric_tail
        is_level = bool(re.search(r'(?:下降|降低|上升|提高|提升|增长|减少|回落)(?:至|到|为)\s*$', change_tail))
        growth_observation = family in ('revenue_yoy', 'net_profit_yoy') and selected_metric and selected_metric[2] in ('revenue', 'net_profit', 'parent_net_profit')
        is_change = unit == '个百分点' or (not is_level and not growth_observation and bool(re.search(
            r'下降|降低|减少|回落|上升|提高|提升|增长|增加|持平|相对变化|相对变动|变化|变动', change_tail)))
        formula = None
        if unit in ('%', '％') and family in ('nev_sales', 'nev_exports'):
            if _EXPORT_SHARE.search(context) or (
                _EXPORT_SHARE.search("出口量" + local_prefix)
                and re.search(r'出口(?:量)?\s*[-+]?\d', context)
            ):
                formula = 'share'
            elif _CAGR.search(context):
                formula = 'cagr'
            elif re.search(r'同比|增速|增长率', metric_tail):
                formula = 'yoy'
        if formula:
            computed = _market_calculation(context, refs, family, entity, year, formula)
            if computed is not None and formula == 'yoy' and not is_level:
                direction = re.search(r'(?:同比\s*)?(增长|增加|下降|减少|下滑)\s*$', local_prefix)
                if direction:
                    up = direction.group(1) in ('增长', '增加')
                    computed = abs(computed) if (computed > 0 if up else computed < 0) else None
            supported = computed is not None and abs(computed - value) <= tolerance
        elif is_change:
            computed = _verified_change(context, local_prefix, refs, family, entity, str(unit or ''),
                                        yoy="同比" in metric_tail)
            if computed is None and named_periods:
                by_id = {ref.get("record_id"): ref for ref in refs}
                candidates = set()
                for comparison in comparisons:
                    old = by_id.get(comparison.get("from_record_id"))
                    new = by_id.get(comparison.get("to_record_id"))
                    if not old or not new or comparison.get("entity") != entity:
                        continue
                    value_from_pair = _verified_change(context, local_prefix, [old, new], family, entity,
                                                       str(unit or ''), yoy="同比" in metric_tail)
                    if value_from_pair is not None:
                        candidates.add(value_from_pair)
                if len(candidates) == 1:
                    computed = candidates.pop()
            supported = computed is not None and abs(computed - value) <= tolerance
        for ref in (() if is_change or formula else refs):
            try:
                actual = float(ref.get('value'))
            except (TypeError, ValueError):
                continue
            if ref.get('conflicted') or any('conflict' in issue for issue in ref.get('issues') or []):
                continue
            actual_entity = ref.get('entity') or ref.get('entity_name')
            if entity and actual_entity != entity:
                continue
            if re.search(r"全球|世界|global", context, re.I) and actual_entity in ("中国", "国内", "全国", "中国市场"):
                continue
            segment_claim = bool(re.search(r"分部|分业务|[\u4e00-\u9fff]{2,12}(?:业务|板块)", context)) and not re.search(r"主营业务|公司业务|业务整体", context)
            if segment_claim:
                scope = str(ref.get("scope") or "consolidated")
                if scope in ("consolidated", "parent", "group", "unknown", "segment") or scope not in context:
                    continue
            actual_metric = metric_family(str(ref.get('metric') or ''))
            # Explicit ratio labels remain distinct; a generic profit is not parent profit.
            if family and metric_family(family) != actual_metric:
                continue
            if probabilistic:
                continue
            period = str(ref.get('period') or ref.get('period_end') or '')
            if year and not period.startswith(str(year)):
                continue
            if not claim_period_matches(context, ref, year, family):
                continue
            source_unit = str(ref.get('unit') or '')
            target_dimension, target_scale = _scaled_unit(str(unit or ''))
            source_dimension, source_scale = _scaled_unit(source_unit)
            if source_dimension == 'money' and ref.get('unit_provenance') == 'unknown':
                continue
            if unit in ('%', '％') and _rate_points(actual, source_unit) is not None:
                displayed = _rate_points(actual, source_unit)
            elif target_dimension and target_dimension == source_dimension:
                displayed = actual * source_scale / target_scale
            else:
                continue
            if abs(displayed - value) <= tolerance:
                supported = True
                break
        if not supported:
            underlying = {"revenue_yoy": "revenue", "net_profit_yoy": "parent_net_profit"}.get(family)
            if (underlying and year and entity and unit in ('%', '％')
                    and re.search(r"同比|增长率|增速", context)
                    and not re.search(r"较|相比|从.+(?:到|至)|相对变化|相对变动", metric_tail)):
                comparable = [
                    ref for ref in refs
                    if (period := measurement_period(ref)) is not None and period[1].year in (year - 1, year)
                ]
                computed = _verified_change(context, local_prefix, comparable, underlying, entity, "%",
                                            yoy=True)
                supported = computed is not None and abs(computed - value) <= tolerance
        if not supported:
            issues.append(dict(code='unsupported_quantity', severity='error', location=location,
                claim=match.group(0), metric=family, entity=entity, year=year,
                evidence_ids=[r.get('record_id') for r in refs],
                suggestion='补充同实体、同指标定义、同期间和单位的证据；否则从草稿删除该断言。'))
    return issues


# --- P-11/P-12：披露精度与舍入等价（A1 冲突判定与 A2 复核共用同一实现） ------
# 规则：只有原始披露字符串（或等价的显式精度元数据）能证明精度；
# float 的 repr 只能作为**已存值**的兜底证据，绝不能反过来当作原始披露精度。
_NUMBER_IN_TEXT = re.compile(r"([-+]?\d[\d,]*(?:\.\d+)?)")

# 可能带金额单位的指标族：只有它们才允许跨单位换算后比较。
MONEY_METRIC_FAMILIES = frozenset({
    'revenue', 'net_profit', 'parent_net_profit', 'operating_cash_flow',
    'rd_expense', 'rd_investment', 'market_cap', 'circulating_market_cap',
})


def decimal_step_from_text(value: Any) -> Decimal | None:
    """末位单位：'16.20%' → 0.01，'16.2%' → 0.1，'100万元' → 1（单位内的末位）。"""
    if not isinstance(value, str):
        return None
    match = re.fullmatch(
        r"\s*([-+]?\d[\d,]*(?:\.\d+)?)\s*(?:%|％|元|千元|万元|百万元|千万元|亿元|万亿元|倍)?\s*",
        value,
    )
    if not match:
        return None
    decimals = match.group(1).partition(".")[2]
    return Decimal(1).scaleb(-len(decimals))


def disclosure_text(record: Any) -> str | None:
    """从 raw_fields 里找与已存数值一致的原始披露字符串。"""
    raw = _as_dict(record).get("raw_fields") or {}
    if not isinstance(raw, dict):
        return None
    candidates = [raw.get(str(_as_dict(record).get("metric", "") or "")), raw.get("value"),
                  raw.get("指标值"), raw.get("数值")]
    candidates.extend(value for value in raw.values() if isinstance(value, str))
    target = _as_dict(record).get("value")
    for text in candidates:
        if not isinstance(text, str):
            continue
        step = decimal_step_from_text(text)
        if step is None:
            continue
        try:
            if Decimal(_NUMBER_IN_TEXT.search(text).group(1).replace(",", "")) == Decimal(str(target)):
                return text
        except (AttributeError, InvalidOperation, ValueError, TypeError):
            continue
    return None


def disclosure_step(record: Any) -> Decimal | None:
    text = disclosure_text(record)
    return decimal_step_from_text(text) if text else None


def inferred_step(record: Any) -> Decimal | None:
    """已存数值的兜底精度（仅用于「来源值」本身，不用于我方重算结果）。"""
    value = _as_dict(record).get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    text = repr(float(value)) if not isinstance(value, Decimal) else str(value)
    step = decimal_step_from_text(text)
    if step is not None:
        return step
    try:
        exponent = (Decimal(text) if isinstance(value, Decimal) else Decimal(repr(float(value)))).normalize().as_tuple().exponent
    except (InvalidOperation, ValueError):
        return None
    return Decimal(1).scaleb(exponent)


def record_step(record: Any) -> Decimal | None:
    """已存值的精度：优先原始披露字符串，其次数值本身的十进制表示。"""
    return disclosure_step(record) or inferred_step(record)


def round_to_step(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * step


def matches_disclosed(stored: Decimal, target: Decimal,
                      stored_step: Decimal | None, target_step: Decimal | None) -> bool | None:
    """按更精细侧舍入到低精度侧，判断两个数是否只是披露精度差异。"""
    if stored == target:
        return True
    if stored_step is None or target_step is None:
        return None
    if stored_step == target_step:
        return False
    if stored_step > target_step:
        return round_to_step(target, stored_step) == stored
    return round_to_step(stored, target_step) == target


def rounding_verdict(records: list[Any], values: list[Decimal]) -> bool | None:
    """同一口径多条记录：True 等价，False 实质冲突，None 精度不可确认（保守拦）。"""
    steps: list[Decimal | None] = [record_step(record) for record in records]
    if any(step is None for step in steps):
        return None
    if len(set(values)) <= 1:
        return True
    precise = min(steps, key=lambda step: step)
    reference_index = next(index for index, step in enumerate(steps) if step == precise)
    reference = values[reference_index]
    for index, (value, step) in enumerate(zip(values, steps)):
        if index == reference_index:
            continue
        if matches_disclosed(value, reference, step, precise) is False:
            return False
    return True


def money_value_yuan(record: Any) -> Decimal | None:
    """把记录值换到元；单位不可信或非金额单位返回 None。"""
    data = _as_dict(record)
    provenance = str(data.get("unit_provenance") or "").strip().casefold()
    if provenance in {"unknown", "legacy_unknown"}:
        return None
    scale = money_scale(data.get("unit"))
    if scale is None:
        return None
    value = data.get("value")
    if isinstance(value, bool) or value is None:
        return None
    try:
        return Decimal(str(value)) * scale
    except (InvalidOperation, ValueError, TypeError):
        return None


def _unit_identity(record: Any, money_metric: bool) -> tuple:
    data = _as_dict(record)
    if money_metric and money_scale(data.get("unit")) is not None:
        return ("money", str(data.get("currency") or "CNY"))
    return ("unit", str(data.get("unit")))


def _group_verdict(records: list[Any], values: list[Decimal]) -> bool | None:
    if len(values) <= 1 or len(set(values)) <= 1:
        return True
    return rounding_verdict(records, values)


def _cross_unit_verdict(records: list[Any]) -> bool | None:
    """金额跨单位：先换算到元，再用同一套披露精度规则比较。"""
    values: list[Decimal] = []
    steps: list[Decimal | None] = []
    for record in records:
        data = _as_dict(record)
        scale = money_scale(data.get("unit"))
        value = money_value_yuan(record)
        if scale is None or value is None:
            return None
        values.append(value)
        step = record_step(record)
        steps.append(step * scale if step is not None else None)
    if any(step is None for step in steps):
        return None
    if len(set(values)) <= 1:
        return True
    # 换算到元之后，精度步长也必须一起换算，不能再按原单位重算一次。
    return _weighted_verdict(values, steps)


def _weighted_verdict(values: list[Decimal], steps: list[Decimal]) -> bool | None:
    precise = min(steps)
    reference_index = next(index for index, step in enumerate(steps) if step == precise)
    reference = values[reference_index]
    for index, (value, step) in enumerate(zip(values, steps)):
        if index == reference_index:
            continue
        if matches_disclosed(value, reference, step, precise) is False:
            return False
    return True


def measurement_conflict_verdict(records: list[Any]) -> bool | None:
    """同一测量口径的一组记录是否构成冲突。

    True  = 等价（含披露精度舍入等价、跨单位换算后相等）；
    False = 实质冲突；
    None  = 精度/单位不可确认，调用方应按保守门禁处理。
    非金额单位不同（如 % 与 倍）不合并比较，沿用原有分组边界。
    """
    if not records:
        return True
    data = _as_dict(records[0])
    money_metric = metric_family(str(data.get("metric") or "")) in MONEY_METRIC_FAMILIES
    buckets: dict[tuple, list[Any]] = {}
    for record in records:
        buckets.setdefault(_unit_identity(record, money_metric), []).append(record)

    pending = False
    money_records: list[Any] = []
    for identity, bucket in buckets.items():
        if identity[0] == "money":
            money_records.extend(bucket)
            continue
        values = []
        for record in bucket:
            try:
                values.append(Decimal(str(_as_dict(record).get("value"))))
            except (InvalidOperation, ValueError, TypeError):
                return None
        verdict = _group_verdict(bucket, values)
        if verdict is False:
            return False
        if verdict is None:
            pending = True

    if money_records:
        units = {str(_as_dict(record).get("unit")) for record in money_records}
        if len(money_records) > 1 and len(set(_as_dict(record).get("value") for record in money_records)) > 1:
            if any(money_scale(_as_dict(record).get("unit")) is None for record in money_records):
                pending = True
            elif len(units) > 1:
                verdict = _cross_unit_verdict(money_records)
                if verdict is False:
                    return False
                if verdict is None:
                    pending = True
            else:
                values = []
                for record in money_records:
                    try:
                        values.append(Decimal(str(_as_dict(record).get("value"))))
                    except (InvalidOperation, ValueError, TypeError):
                        return None
                verdict = _group_verdict(money_records, values)
                if verdict is False:
                    return False
                if verdict is None:
                    pending = True
    return None if pending else True
