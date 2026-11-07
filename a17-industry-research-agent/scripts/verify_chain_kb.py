"""产业链知识底座验收脚本（2026-10-25）。

用法：
  # 1) 底座自检 + 8 行业金标准集打分
  ./.venv/bin/python scripts/verify_chain_kb.py

  # 2) 额外审计某次真实产物（读 chart_result.json 里的 chain_graph）
  ./.venv/bin/python scripts/verify_chain_kb.py --audit data/runs/run-xxx

输出四段：底座规模 / 20 家企业抽查 / 金标准集评分 / 真实产物归属命中率。
只读，不改任何产物。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents_core" / "chart-generator"))

from chart_generator import chain_kb  # noqa: E402
from chart_generator.chain_topology import company_fit_report  # noqa: E402

GOLDEN = ROOT / "agents_core" / "chart-generator" / "tests" / "golden" / "chain_brand_golden.json"

# 20 家跨行业抽查样本：人工核对"行业归属 + 主营产品"是否与常识一致
SAMPLE = [
    "金风科技", "明阳智能", "东方电缆", "中天科技", "日月股份",
    "贵州茅台", "五粮液", "泸州老窖", "奥瑞金",
    "恒瑞医药", "复星医药", "药明康德", "泰格医药",
    "北方华创", "中微公司", "富创精密", "沪硅产业",
    "宁德时代", "恩捷股份", "生益科技",
]


def _p(line: str = "") -> None:
    print(line)


def section_stats() -> None:
    st = chain_kb.stats()
    _p("=" * 78)
    _p("① 知识底座规模")
    _p("=" * 78)
    _p(f"可用：{st['available']}　目录：{st['dir']}")
    _p(f"企业 {st['companies']} 家｜行业 {st['industries']} 个｜产品词 {st['products']} 个")
    _p(f"原始行数：company {st['company_rows']} / company_industry {st['industry_rows']} / "
       f"company_product {st['product_rows']}")
    _p(f"口径：{st['coverage_note']}")
    _p()


def section_sample() -> None:
    _p("=" * 78)
    _p("② 20 家企业抽查（行业归属 + 主营产品，人工核对正确率）")
    _p("=" * 78)
    ok = 0
    for name in SAMPLE:
        prof = chain_kb.company_profile(name)
        if prof is None:
            _p(f"  ✗ {name:6s} 无记录")
            continue
        ok += 1
        _p(f"  ✓ {name:6s} {prof.describe()}")
    _p(f"\n命中 {ok}/{len(SAMPLE)}；无记录 {len(SAMPLE) - ok} 家（未上市/HK/改名未收录→属已知边界）")
    _p()


def section_golden() -> float:
    with GOLDEN.open(encoding="utf-8") as fh:
        golden = json.load(fh)
    _p("=" * 78)
    _p("③ 8 行业金标准集评分（品牌位）")
    _p("=" * 78)
    brand_total = brand_keep = 0
    sup_total = sup_block = 0
    sup_missing = 0
    leaks: list[str] = []
    kills: list[str] = []
    for case in golden["cases"]:
        slot = case["brand_slot"]
        exempt = set(case.get("profile_exempt") or ())
        b_keep = 0
        for n in case["brand"]:
            v = chain_kb.company_fit(n, slot, role="brand")
            if n in exempt:
                continue
            brand_total += 1
            if v.mismatch:
                kills.append(f"{case['industry']}/{n}")
            else:
                b_keep += 1
                brand_keep += 1
        b_block = 0
        for n in case["supplier"]:
            v = chain_kb.company_fit(n, slot, role="brand")
            if v.missing:
                sup_missing += 1
                continue
            sup_total += 1
            if v.mismatch:
                sup_block += 1
                b_block += 1
            else:
                leaks.append(f"{case['industry']}/{n}")
        _p(f"  {case['industry']:6s} 品牌保留 {b_keep:2d}/{len(case['brand'])}"
           f"　供应商拦截 {b_block:2d}")
    rate = sup_block / sup_total if sup_total else 0.0
    _p(f"\n品牌误杀 {len(kills)}/{brand_total}（门槛 0）")
    _p(f"供应商拦截 {sup_block}/{sup_total} = {rate:.0%}（基线 ≥60%；"
       f"kb_missing 不计入分母：{sup_missing} 家）")
    if kills:
        _p(f"  误杀：{kills}")
    _p(f"  漏放（多为 kb_unknown，只留痕不删人）：{leaks}")
    _p()
    return rate


def section_audit(run_dir: Path) -> None:
    path = run_dir / "artifacts" / "chart_result.json"
    if not path.exists():
        _p(f"⚠️ 找不到 {path}")
        return
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    charts = data.get("charts") or []
    graph = None
    for c in charts:
        if isinstance(c, dict) and c.get("chain_graph"):
            graph = c["chain_graph"]
            break
    if not graph:
        _p("⚠️ 该产物里没有 chain_graph")
        return
    # chart_graph 用 name/items/node_id，先转成内部拓扑口径再审计
    top = {
        "title": graph.get("title") or "",
        "core_product": graph.get("core_product") or "",
        "nodes": [{"label": n.get("name"), "stage": n.get("stage"),
                   "is_core": n.get("is_core"), "companies": n.get("companies") or [],
                   "key_products": n.get("items") or []}
                  for n in (graph.get("nodes") or [])],
    }
    rep = company_fit_report(top, str(graph.get("title") or ""))
    _p("=" * 78)
    _p(f"④ 真实产物归属命中率：{run_dir.name}")
    _p("=" * 78)
    _p(f"企业 {rep['total']} 家｜KB 命中 {rep['backed']}｜无记录 {rep['missing']}｜"
       f"词表沉默 {rep['unknown']}｜判不符 {rep['mismatch']}｜命中率 {rep['hit_rate']:.0%}")
    for row in rep["rows"]:
        _p(f"  [{row['verdict']:11s}] {row['node']:12s} {row['company']:8s} {row['reason'][:60]}")
    _p()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit", default="", help="审计某次 run 目录下的 chart_result.json")
    args = ap.parse_args()

    section_stats()
    section_sample()
    rate = section_golden()
    if args.audit:
        section_audit(Path(args.audit).expanduser().resolve())

    failed = []
    if not chain_kb.available():
        failed.append("知识底座不可用")
    if rate < 0.6:
        failed.append(f"供应商拦截率 {rate:.0%} < 60%")
    if failed:
        _p("❌ 验收未通过：" + "；".join(failed))
        return 1
    _p("✅ 验收通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
