# 动态注入用户指标测试 — 总结

测试时间: 2026-08-18
输入: 光伏逆变器行业竞争格局，7个指标

## 一、路由对比（_metric_skill）

| 指标 | 原版本 | 补全token | 期望 |
|------|--------|-----------|------|
| 营业收入 | hithink_finance_query ✅ | hithink_finance_query ✅ | hithink_finance_query |
| 毛利率 | hithink_finance_query ✅ | hithink_finance_query ✅ | hithink_finance_query |
| 净利率 | hithink_industry_query ❌ | hithink_finance_query ✅ | hithink_finance_query |
| 出货量 | hithink_industry_query ❌ | hithink_finance_query ✅ | hithink_finance_query |
| 海外收入占比 | hithink_industry_query ❌ | hithink_finance_query ✅ | hithink_finance_query |
| 研发费用率 | hithink_finance_query ✅ | hithink_finance_query ✅ | hithink_finance_query |
| 市占率 | hithink_stock_selector ✅ | hithink_stock_selector ✅ | hithink_stock_selector |

正确率: 原 4/7 (57%) → 补全 7/7 (100%)

## 二、FINANCE 查询对比

**原硬编码**:
```
阳光电源 华为 锦浪科技 2024年 2025年 营业收入 营业成本 净利润 经营活动现金流量净额 投资活动现金流量净额 筹资活动现金流量净额 期末现金及现金等价物余额 货币资金 总资产 负债合计 股东权益 存货 应收账款
```

**动态注入（保留基础+追加用户指标）**:
```
阳光电源 华为 锦浪科技 2024年 2025年 营业收入 营业成本 净利润 经营活动现金流量净额 投资活动现金流量净额 筹资活动现金流量净额 期末现金及现金等价物余额 货币资金 总资产 负债合计 股东权益 存货 应收账款 毛利率 净利率 出货量 海外收入占比 研发费用率 市占率
```

新增用户指标: ['毛利率', '净利率', '出货量', '海外收入占比', '研发费用率', '市占率']

## 三、STOCK_SELECTOR 查询对比

原版本:
```
光伏逆变器行业竞争格局概念股 2024年营业收入 从高到低
```

动态注入（检测到市占率则查询市占率）:
```
光伏逆变器行业竞争格局概念股 2024年 市占率 从高到低
```

## 四、需求覆盖

原版本: 11/11 (100%) supported
补全后: 11/11 (100%) supported

## 结论

仅需两处修改（不改变架构，不碰现有逻辑）:
1. `_metric_skill` token白名单补充 `净利率` `出货量` `海外收入占比` → 正确路由
2. `_market_skill_query(FINANCE)` 在基础字段后追加用户请求的指标（去重）→ 能查到用户要的数据
3. `_market_skill_query(STOCK_SELECTOR)` 如果用户请求的是市占率，则查询市占率而非营收排名 → 拿到正确数据
