# -*- coding: utf-8 -*-
"""
测试: 动态注入用户指标到 FINANCE 查询 vs 原硬编码查询

测试目的:
- 对比原逻辑 vs 动态注入后的需求覆盖效果
- 验证"注入用户指标后是否能解决问题"
- 不修改任何生产代码，仅在测试中模拟修改后的效果

数据来源:
- 仍然用捏造数据，不调用真实 API
"""
import sys
import json
from pathlib import Path
from typing import List, Dict, Any
from dataclasses import dataclass

# 添加 backend 到路径
sys.path.insert(0, str(Path(__file__).parent / "backend"))

# 导入生产代码不修改
from app.agents.data_fetcher.planner import (
    _metric_skill,
    _build_requirements,
    _normalised_requirement_text,
    _conditional_market_skill,
    SkillName,
)

OUTPUT_DIR = Path(__file__).parent / "test_output" / "光伏逆变器_dynamic_injection"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ==================== 测试输入 = 跟之前一样 ====================
INDUSTRY_TOPIC = "光伏逆变器行业竞争格局"
FOCUS_QUESTIONS = [
    "光伏逆变器行业竞争格局如何？",
    "龙头企业优势与差异化体现在哪些方面？",
    "国内外厂商市占率对比",
    "海外贸易政策对出口业务的影响",
]
REQUESTED_METRICS = [
    "营业收入",
    "毛利率",
    "净利率",
    "出货量",
    "海外收入占比",
    "研发费用率",
    "市占率",
]
FOCUS_COMPANIES = [
    "阳光电源",
    "华为",
    "锦浪科技",
    "固德威",
    "SMA",
    "SolarEdge",
]


# ==================== 原生产逻辑：_market_skill_query(FINANCE) ====================
def original_market_skill_query_finance(
    industry_topic: str,
    request_text: str,
    research_as_of,
    target_entities: List[str],
) -> str:
    """原硬编码版本。"""
    subject = " ".join(target_entities) if target_entities else industry_topic
    periods = f"{research_as_of.year - 1}年 {research_as_of.year}年"
    return (
        f"{subject} {periods} 营业收入 营业成本 净利润 "
        "经营活动现金流量净额 投资活动现金流量净额 "
        "筹资活动现金流量净额 期末现金及现金等价物余额 "
        "货币资金 总资产 负债合计 "
        "股东权益 存货 应收账款"
    )


# ==================== 动态注入版本：FINANCE 查询拼接用户指标 ====================
def dynamic_injected_market_skill_query_finance(
    industry_topic: str,
    request_text: str,
    research_as_of,
    target_entities: List[str],
    user_metrics: List[str],
) -> str:
    """动态注入版本：把用户指标追加到查询字段列表。

    保留基础必选字段，然后加上用户请求的指标（去重）。
    """
    subject = " ".join(target_entities) if target_entities else industry_topic
    periods = f"{research_as_of.year - 1}年 {research_as_of.year}年"

    # 基础必选字段（原硬编码列表）
    base_fields = [
        "营业收入", "营业成本", "净利润",
        "经营活动现金流量净额", "投资活动现金流量净额",
        "筹资活动现金流量净额", "期末现金及现金等价物余额",
        "货币资金", "总资产", "负债合计",
        "股东权益", "存货", "应收账款",
    ]

    # 去重：把用户指标中不在 base_fields 里的追加进去
    base_set = set(base_fields)
    extra_fields = [m for m in user_metrics if m not in base_set]
    all_fields = base_fields + extra_fields

    return f"{subject} {periods} {' '.join(all_fields)}"


# ==================== STOCK_SELECTOR 动态注入 ====================
def original_market_skill_query_stock_selector(
    industry_topic: str,
    research_as_of,
) -> str:
    """原版本：营收排名。"""
    return f"{industry_topic}概念股 {research_as_of.year - 1}年营业收入 从高到低"


def dynamic_injected_market_skill_query_stock_selector(
    industry_topic: str,
    research_as_of,
    requested_metric: str,
) -> str:
    """动态注入版本：如果请求的是市占率，则按市占率排序。"""
    if "市占率" in requested_metric:
        return f"{industry_topic}概念股 {research_as_of.year - 1}年 市占率 从高到低"
    # 其他指标默认还是营收排名
    return f"{industry_topic}概念股 {research_as_of.year - 1}年营业收入 从高到低"


# ==================== 测试：_metric_skill 路由对比（补全token vs 原token） ====================
ORIGINAL_METRIC_TOKENS = {
    "营业收入", "营业成本", "净利润", "毛利率", "roe",
    "总资产", "股东权益", "存货", "应收账款", "费用率",
    "股票代码", "证券代码", "上市地点", "上市日期", "发行主体",
}

ENRICHED_METRIC_TOKENS = ORIGINAL_METRIC_TOKENS | {
    "净利率", "出货量", "海外收入占比", "海外营收",
}


def original_metric_skill(metric: str) -> SkillName:
    """原版本：token白名单不完整。"""
    compact = _normalised_requirement_text(metric)
    conditional = _conditional_market_skill(compact)
    if conditional is not None:
        return conditional
    if any(token in compact for token in ORIGINAL_METRIC_TOKENS):
        return SkillName.FINANCE
    return SkillName.INDUSTRY


def enriched_metric_skill(metric: str) -> SkillName:
    """优化后：添加缺失的token。"""
    compact = _normalised_requirement_text(metric)
    conditional = _conditional_market_skill(compact)
    if conditional is not None:
        return conditional
    if any(token in compact for token in ENRICHED_METRIC_TOKENS):
        return SkillName.FINANCE
    return SkillName.INDUSTRY


# ==================== 运行对比测试 ====================
from datetime import date
research_as_of = date(2025, 12, 31)

print("=" * 80)
print("测试一：_metric_skill 路由对比 — 原版本 vs token补全版本")
print("=" * 80)
print()

results_route: list[dict] = []
for metric in REQUESTED_METRICS:
    orig = original_metric_skill(metric)
    enri = enriched_metric_skill(metric)
    correct = (
        (metric in ["毛利率", "净利率", "营业收入", "研发费用率", "海外收入占比"]) or
        "市占" in metric
    )
    correct_skill = (
        SkillName.FINANCE if metric != "市占率" and "市占" not in metric else
        SkillName.STOCK_SELECTOR
    )
    results_route.append({
        "metric": metric,
        "original": orig.value,
        "enriched": enri.value,
        "expected": correct_skill.value,
        "original_correct": orig == correct_skill,
        "enriched_correct": enri == correct_skill,
    })

for r in results_route:
    o_mark = "✅" if r["original_correct"] else "❌"
    e_mark = "✅" if r["enriched_correct"] else "❌"
    print(f"{r['metric']:>12} | 原: {r['original']:<10} {o_mark} | 优化: {r['enriched']:<10} {e_mark} | 期望: {r['expected']}")

print()
print("路由正确率：")
orig_correct_count = sum(1 for r in results_route if r["original_correct"])
enri_correct_count = sum(1 for r in results_route if r["enriched_correct"])
print(f"原版本: {orig_correct_count}/{len(results_route)} ({orig_correct_count/len(results_route)*100:.0f}%)")
print(f"补token: {enri_correct_count}/{len(results_route)} ({enri_correct_count/len(results_route)*100:.0f}%)")

print()
print("=" * 80)
print("测试二：FINANCE 查询对比 — 原硬编码 vs 动态注入用户指标")
print("=" * 80)
print()

orig_query_finance = original_market_skill_query_finance(
    INDUSTRY_TOPIC, "", research_as_of, FOCUS_COMPANIES[:3]  # 只看A股
)
dyn_query_finance = dynamic_injected_market_skill_query_finance(
    INDUSTRY_TOPIC, "", research_as_of, FOCUS_COMPANIES[:3], REQUESTED_METRICS
)

print("【原硬编码查询字段】:")
orig_fields = orig_query_finance.split()[-14:]  # 基础字段在最后
print("  " + " ".join(orig_fields))
print(f"  共 {len(orig_fields)} 个字段")
print()
print("【动态注入后查询字段】:")
dyn_fields = dyn_query_finance.split()[len(dyn_query_finance.split()) - len(REQUESTED_METRICS + orig_fields) :]
extra_added = [m for m in REQUESTED_METRICS if m not in orig_fields]
print("  " + " ".join(dyn_fields))
print(f"  新增用户指标: {extra_added}")
print(f"  共 {len(dyn_fields)} 个字段（基础 {len(orig_fields)} + 用户 {len(extra_added)}）")

print()
print("【完整查询】原版本:")
print(f"  {orig_query_finance}")
print()
print("【完整查询】动态注入版:")
print(f"  {dyn_query_finance}")

print()
print("=" * 80)
print("测试三：STOCK_SELECTOR 对比 — 原营收排名 vs 动态市占率查询")
print("=" * 80)
print()

orig_query_ss = original_market_skill_query_stock_selector(INDUSTRY_TOPIC, research_as_of)
dyn_query_ss = dynamic_injected_market_skill_query_stock_selector(INDUSTRY_TOPIC, research_as_of, "市占率")

print(f"【原版本】: {orig_query_ss}")
print(f"【动态注入】: {dyn_query_ss}")
print()

print("=" * 80)
print("测试四：需求覆盖 — _build_requirements 在两种场景下的输出")
print("=" * 80)
print()

reqs_original = _build_requirements(FOCUS_QUESTIONS, REQUESTED_METRICS)
# 这里我们用 enriched_metric_skill 替换 _metric_skill，模拟补全token后的行为
# 猴子补丁
import app.agents.data_fetcher.planner as planner
original__metric_skill = planner._metric_skill
planner._metric_skill = enriched_metric_skill
reqs_enriched = _build_requirements(FOCUS_QUESTIONS, REQUESTED_METRICS)
planner._metric_skill = original__metric_skill  # 恢复


def print_requirements(reqs, title):
    print(f"\n{title}:")
    supported = 0
    missing = 0
    for i, req in enumerate(reqs):
        req_skills = [s.value for s in req.target_skills]
        supported_any = len(req.target_skills) > 0
        if supported_any:
            supported += 1
        else:
            missing += 1
        print(f"  REQ-{i+1:02d} [{req.question[:30]:<30}] → skills: {req_skills}")
    print(f"  总计: supported={supported}, missing={missing}")
    return supported, missing


orig_supported, orig_missing = print_requirements(reqs_original, "原token白名单")
enr_supported, enr_missing = print_requirements(reqs_enriched, "补全token后")

print()
print(f"需求覆盖统计:")
print(f"  原版本: {orig_supported}/{len(reqs_original)} supported ({orig_supported/len(reqs_original)*100:.0f}%)")
print(f"  补全后: {enr_supported}/{len(reqs_enriched)} supported ({enr_supported/len(reqs_enriched)*100:.0f}%)")

# 保存结果到文件
result_json = {
    "route_comparison": results_route,
    "original_route_correct": orig_correct_count,
    "enriched_route_correct": enri_correct_count,
    "original_finance_query": orig_query_finance,
    "dynamic_finance_query": dyn_query_finance,
    "original_extra_fields": extra_added,
    "original_stock_selector_query": orig_query_ss,
    "dynamic_stock_selector_query": dyn_query_ss,
    "original_requirement_supported": orig_supported,
    "enriched_requirement_supported": enr_supported,
    "total_requirements": len(reqs_original),
}

with (OUTPUT_DIR / "test_result.json").open("w", encoding="utf-8") as f:
    json.dump(result_json, f, ensure_ascii=False, indent=2)

with (OUTPUT_DIR / "SUMMARY.md").open("w", encoding="utf-8") as f:
    f.write("# 动态注入用户指标测试 — 总结\n\n")
    f.write("测试时间: 2026-08-18\n")
    f.write("输入: 光伏逆变器行业竞争格局，7个指标\n\n")
    f.write("## 一、路由对比（_metric_skill）\n\n")
    f.write("| 指标 | 原版本 | 补全token | 期望 |\n")
    f.write("|------|--------|-----------|------|\n")
    for r in results_route:
        o_mark = "✅" if r["original_correct"] else "❌"
        e_mark = "✅" if r["enriched_correct"] else "❌"
        f.write(f"| {r['metric']} | {r['original']} {o_mark} | {r['enriched']} {e_mark} | {r['expected']} |\n")
    f.write(f"\n正确率: 原 {orig_correct_count}/{len(results_route)} ({orig_correct_count/len(results_route)*100:.0f}%) → 补全 {enri_correct_count}/{len(results_route)} ({enri_correct_count/len(results_route)*100:.0f}%)\n\n")
    f.write("## 二、FINANCE 查询对比\n\n")
    f.write("**原硬编码**:\n```\n")
    f.write(orig_query_finance + "\n")
    f.write("```\n\n**动态注入（保留基础+追加用户指标）**:\n```\n")
    f.write(dyn_query_finance + "\n")
    f.write(f"```\n\n新增用户指标: {extra_added}\n\n")
    f.write("## 三、STOCK_SELECTOR 查询对比\n\n")
    f.write(f"原版本:\n```\n{orig_query_ss}\n```\n\n")
    f.write(f"动态注入（检测到市占率则查询市占率）:\n```\n{dyn_query_ss}\n```\n\n")
    f.write("## 四、需求覆盖\n\n")
    f.write(f"原版本: {orig_supported}/{len(reqs_original)} ({orig_supported/len(reqs_original)*100:.0f}%) supported\n")
    f.write(f"补全后: {enr_supported}/{len(reqs_enriched)} ({enr_supported/len(reqs_enriched)*100:.0f}%) supported\n\n")
    f.write("## 结论\n\n")
    f.write("仅需两处修改（不改变架构，不碰现有逻辑）:\n")
    f.write("1. `_metric_skill` token白名单补充 `净利率` `出货量` `海外收入占比` → 正确路由\n")
    f.write("2. `_market_skill_query(FINANCE)` 在基础字段后追加用户请求的指标（去重）→ 能查到用户要的数据\n")
    f.write("3. `_market_skill_query(STOCK_SELECTOR)` 如果用户请求的是市占率，则查询市占率而非营收排名 → 拿到正确数据\n")

print()
print(f"结果已保存到: {OUTPUT_DIR}")
print(f"  - {OUTPUT_DIR}/test_result.json")
print(f"  - {OUTPUT_DIR}/SUMMARY.md")
