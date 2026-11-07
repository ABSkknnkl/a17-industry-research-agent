"""Deterministic gross-profit scenarios using explicitly sourced baselines."""
import math
from typing import Any


def calculate_sensitivity(model: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    try:
        if any(isinstance(model.get(key), bool) for key in ('price_change_pct', 'cost_change_pct')):
            raise ValueError('情景假设不能为布尔值')
        rid, cid = model['revenue_record_id'], model['cost_record_id']
        revenue, cost = evidence[rid], evidence[cid]
        revenue = revenue.model_dump(mode='json') if hasattr(revenue, 'model_dump') else revenue
        cost = cost.model_dump(mode='json') if hasattr(cost, 'model_dump') else cost
        price = float(model['price_change_pct'])
        cost_change = float(model['cost_change_pct'])
        scales = {'元': 1.0, '万元': 1e4, '亿元': 1e8}
        base_revenue = float(revenue['value']) * scales[revenue['unit']]
        base_cost = float(cost['value']) * scales[cost['unit']]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('缺少合法的来源记录、单位或显式情景假设') from exc
    if rid == cid or revenue.get('metric') not in ('revenue', '营业收入', '营业总收入') or cost.get('metric') not in ('营业成本', 'operating_cost', 'cost_of_revenue', 'cost_of_sales'):
        raise ValueError('基准必须分别是收入和营业成本')
    if not revenue.get('entity') or not revenue.get('period') or revenue.get('period_type') in (None, '', 'unknown'):
        raise ValueError('基准必须包含主体、期间和期间类型')
    if not revenue.get('scope') or revenue.get('scope') == 'unknown' or not revenue.get('currency') or revenue.get('currency') == 'unknown':
        raise ValueError('基准必须包含明确范围和币种')
    for key in ('entity', 'period', 'period_start', 'period_type', 'scope', 'currency'):
        if revenue.get(key) != cost.get(key):
            raise ValueError(f'基准的{key}不一致')
    if any('period_conflict' in (r.get('issues') or []) for r in (revenue, cost)):
        raise ValueError('存在期间冲突')
    if not all(math.isfinite(v) for v in (price, cost_change, base_revenue, base_cost)) or base_revenue <= 0 or base_cost < 0 or not (-100 <= price <= 1000) or not (-100 <= cost_change <= 1000):
        raise ValueError('输入数值无效')
    before = base_revenue - base_cost
    after = base_revenue * (1 + price / 100) - base_cost * (1 + cost_change / 100)
    if not all(math.isfinite(v) for v in (before, after, after - before)):
        raise ValueError('情景计算溢出')
    return {'entity': revenue['entity'], 'period': revenue['period'], 'scope': revenue.get('scope'),
        'currency': revenue.get('currency'), 'unit': '元', 'gross_profit_before': before,
        'gross_profit_after': after, 'gross_profit_change': after - before,
        'price_change_pct': price, 'cost_change_pct': cost_change, 'volume_assumption': '销量不变',
        'input_record_ids': [rid, cid], 'formula': '收入×(1+价格变化率)−营业成本×(1+成本变化率)',
        'limitations': ['假设销量及其他因素不变；结果为毛利润变化，不是归母净利润预测。']}
