"""Small shared contracts for reporting periods and comparable observations.

Publication/retrieval dates never substitute for a financial measurement period.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import math
import re
from typing import Any


_ISO_DATE = re.compile(r'(?<!\d)((?:19|20)\d{2}-\d{2}-\d{2})(?!\d)')
_NAMED_PERIOD = re.compile(r'(20\d{2})(?:年|-\d{2}-\d{2})')
_MONEY_SCALES = {'元': 1, '万元': 1e4, '亿元': 1e8, '万亿元': 1e12}


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


def period_shape(end: date | None, label: str = '', *, point: bool = False) -> dict[str, Any]:
    if end is None:
        return dict(period_start=None, period_type='unknown')
    if point:
        return dict(period_start=end, period_type='point')
    if '单季' in label or '当季' in label:
        month = ((end.month - 1) // 3) * 3 + 1
        return dict(period_start=date(end.year, month, 1), period_type='quarter')
    if '累计' in label and end.month not in (3, 6, 9, 12):
        return dict(period_start=date(end.year, 1, 1), period_type='ytd_month')
    kinds = {(12, 31): 'annual', (9, 30): 'ytd_q3', (6, 30): 'half_year', (3, 31): 'q1'}
    kind = kinds.get((end.month, end.day), 'month')
    if '累计' in label:
        kind = 'ytd_month'
    return dict(period_start=date(end.year, 1 if kind != 'month' else end.month, 1), period_type=kind)


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
        kind = data.get("period_type") or "unknown"
        shape = period_shape(end, "单季" if kind == "quarter" else "", point=kind == "point")
        if kind == "unknown":
            kind = shape["period_type"]
        raw_start = data.get("period_start")
        start = date.fromisoformat(str(raw_start)[:10]) if raw_start else shape["period_start"]
        expected_ends = {"annual": (12,31), "half_year": (6,30), "ytd_q3": (9,30), "q1": (3,31)}
        if kind in expected_ends and (end.month, end.day) != expected_ends[kind]:
            return None
        if start > end:
            return None
        return start, end, kind
    except (TypeError, ValueError):
        return None


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
            }.get(metric)
            if formula is None:
                continue
            numerator, denominator, multiplier, unit = formula
            expected = f"{numerator}/{denominator}" + ("*100" if multiplier == 100 else "")
            if (calc.get("formula") != expected or metric_family(a.get("metric", "")) != numerator
                    or metric_family(b.get("metric", "")) != denominator):
                continue
            try:
                scales = {"元": 1, "万元": 1e4, "亿元": 1e8, "CNY": 1, "RMB": 1}
                base = float(b["value"]) * scales[b["unit"]]
                if not math.isfinite(base) or base <= 0 or (metric == "cash_to_net_profit" and base < 5e6):
                    continue
                value = float(a["value"]) * scales[a["unit"]] / base * multiplier
            except (TypeError, ValueError, ZeroDivisionError, KeyError):
                continue
            if not math.isfinite(value):
                continue
            observations.append(dict(record_id="derived:" + "/".join(ids), entity=entity,
                metric=metric, value=value, unit=unit, period=str(pa[1]), period_start=str(pa[0]),
                period_type=pa[2], scope=a.get("scope", "consolidated"), currency=a.get("currency", "CNY")))
    return observations


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
        '新增装机量': 'pv_new_capacity', '新增装机容量': 'pv_new_capacity',
        '光伏装机': 'pv_new_capacity', '新增光伏装机': 'pv_new_capacity',
        '中国光伏新增装机容量': 'pv_new_capacity', '光伏新增装机容量': 'pv_new_capacity',
        '新增光伏装机容量': 'pv_new_capacity',
        '新能源汽车销量': 'nev_sales', '中国新能源汽车销量': 'nev_sales',
        '市场渗透率': 'nev_penetration', '新能源汽车市场渗透率': 'nev_penetration',
        '中国新能源汽车市场渗透率': 'nev_penetration',
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
QUANTITY_RE = re.compile(r'(?<![\dA-Za-z])([-+−]?\d[\d,]*(?:\.\d+)?)\s*(万亿元|亿元|万元|元|%|％|倍|家|万辆|辆|万吨|吨|GWh|GW|个百分点)?')


def _as_dict(value: Any) -> dict:
    return value.model_dump(mode='json') if hasattr(value, 'model_dump') else dict(value)


# Numeric thousands separators and decimal points do not end a claim clause.
_CLAUSE_BOUNDARY = re.compile(r'[。；;\n！？!?，]|(?<!\d),|,(?!\d)|(?<!\d)\.|\.(?!\d)')
_CAUSAL = re.compile(r'证明|证实|必然|表明|反映|意味着|说明了|导致|归因于|源于|驱动(?!因素|因子|机制|模型|分析)|印证|利润分配.*重构|利润池.*转移|(?:说明|体现)(?=.*(?:议价权|应收|存货|利润池|业务|分部))')
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
                     entity: str | None, unit: str | None) -> float | None:
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
        elif source_unit in _MONEY_SCALES:
            value, dimension = value * _MONEY_SCALES[source_unit], 'money'
        elif source_unit:
            dimension = source_unit
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
        change = delta / abs(from_row[2]) * 100
    elif from_row[3] == 'money' and unit in _MONEY_SCALES:
        change = delta / _MONEY_SCALES[unit]
    elif from_row[3] == unit:
        change = delta
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


def quantity_issues(text: str, evidence: list[Any], *, universe: list[Any] = (),
                    assumption_note: str | None = None, kind: str = '', location: str = '') -> list[dict]:
    """Fail closed on a numeric claim without matching measurement semantics.

    Rounding tolerance is half the displayed final digit, never a percentage of
    the claim. A matching real ID by itself is insufficient.
    """
    refs = [_as_dict(e) for e in evidence]
    all_refs = [_as_dict(e) for e in universe] or refs
    known_entities = {str(e.get('entity') or e.get('entity_name') or '') for e in all_refs} - {''}
    issues = []
    clauses = _claim_clauses(text)
    iso_dates = _valid_iso_dates(text)
    for start, _, clause_text in clauses:
        if _CAUSAL.search(clause_text) and not _UNCERTAIN_CAUSE.search(clause_text):
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
        forecast = bool(re.search(r"未来|将持续|将继续|势必", clause_text))
        qualitative_comparison = bool(direction and not QUANTITY_RE.search(
            _NAMED_PERIOD.sub("", clause_text)) and len(_NAMED_PERIOD.findall(clause_text)) >= 2)
        continuous = bool(direction and re.search(r"持续|连续", clause_text))
        unbounded_rank = bool(re.search(r"(?:行业|市场|同业|同行)(?:中)?(?:领先|第一|最高)", clause_text))
        if (unbounded_rank or (direction and (forecast or qualitative_comparison or continuous))) and not re.search(
            r"假设|如果|可能|或许|待验证|无法|不足以|不一定|是否|不能|风险在于|目标是", clause_text
        ):
            entities = [name for name in known_entities if name in clause_text]
            entity = max(entities, key=len, default=None)
            matches = [term for term in CLAIM_METRICS if term.casefold() in clause_text.casefold()]
            family = CLAIM_METRICS[max(matches, key=len)] if matches else None
            direction_text = clause_text.replace("下滑", "下降")
            measured = (
                not (forecast or continuous or unbounded_rank)
                and _verified_change(direction_text, direction_text, refs, family, entity, None) is not None
            )
            if not measured:
                issues.append(dict(code="unsupported_direction_claim", severity="error", location=location,
                    claim=clause_text, evidence_ids=[r.get("record_id") for r in refs],
                    suggestion="补充同口径观测，或明确区分已观察变化与待验证假设。"))
    for match in QUANTITY_RE.finditer(text):
        if any(start <= match.start() < end for start, end, _ in iso_dates):
            continue
        raw, unit = match.groups()
        raw = raw.replace(',', '').replace('−', '-')
        value = float(raw)
        if unit is None and (1900 <= value <= 2099 and value.is_integer()):
            continue
        if unit is None and re.search(r"(?:图|表|第)\s*$", text[:match.start()]):
            continue
        decimals = len(raw.split('.')[1]) if '.' in raw else 0
        tolerance = 0.5 * 10 ** -decimals + 1e-9
        before = text[:match.start()]
        clause = re.split(r'[。；;\n]', before)[-1]
        context = clause[-100:]
        selected = [(context.casefold().rfind(term.casefold()), len(term), family)
                    for term, family in CLAIM_METRICS.items() if term.casefold() in context.casefold()]
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
        change_tail = local_prefix if re.search(r'相对变化|相对变动', local_prefix) else metric_tail
        is_level = bool(re.search(r'(?:下降|降低|上升|提高|提升|增长|减少|回落)(?:至|到|为)\s*$', change_tail))
        growth_observation = family in ('revenue_yoy', 'net_profit_yoy') and selected_metric and selected_metric[2] in ('revenue', 'net_profit', 'parent_net_profit')
        is_change = unit == '个百分点' or (not is_level and not growth_observation and bool(re.search(
            r'下降|降低|减少|回落|上升|提高|提升|增长|增加|持平|相对变化|相对变动|变化|变动', change_tail)))
        if is_change:
            computed = _verified_change(context, local_prefix, refs, family, entity, str(unit or ''))
            supported = computed is not None and abs(computed - value) <= tolerance
        for ref in (() if is_change else refs):
            try:
                actual = float(ref.get('value'))
            except (TypeError, ValueError):
                continue
            if ref.get('issues') and 'period_conflict' in ref['issues']:
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
            scales = {'元': 1, '万元': 1e4, '亿元': 1e8, '万亿元': 1e12}
            if unit in scales and source_unit in scales:
                displayed = actual * scales[source_unit] / scales[unit]
            elif unit in ('%', '％') and _rate_points(actual, source_unit) is not None:
                displayed = _rate_points(actual, source_unit)
            elif unit == source_unit:
                displayed = actual
            else:
                continue
            if abs(displayed - value) <= tolerance:
                supported = True
                break
        if not supported:
            issues.append(dict(code='unsupported_quantity', severity='error', location=location,
                claim=match.group(0), metric=family, entity=entity, year=year,
                evidence_ids=[r.get('record_id') for r in refs],
                suggestion='补充同实体、同指标定义、同期间和单位的证据；否则从草稿删除该断言。'))
    return issues
