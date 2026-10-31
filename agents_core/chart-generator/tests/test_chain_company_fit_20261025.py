"""品牌卡归属裁决（apply_company_fit）接入测试（2026-10-25）。

三个必守的行为契约：

1. **能修**：品牌卡上的包装厂被移出并归位到「包装材料」（P5 归属串岗的同类案例）；
2. **不乱修**：KB 无记录（境外/未上市）与词表沉默的企业**一个都不能删**——
   2026-10-18 那次把 8 家整机龙头摘成 0 家，就是拿"查不到"当"是错的"；
3. **画像优先**：画像 ``leading_brand`` / ``leading_upstream`` 里的名字，
   轮不到 2021 年的申万分类来否定。
"""
from __future__ import annotations

from chart_generator.chain_topology import apply_company_fit, repair_topology


def _topo(nodes, subject="白酒"):
    return {"title": f"{subject}产业链图谱", "subtitle": "", "core_product": subject,
            "nodes": nodes, "edges": []}


def _n(nid, label, stage, *, core=False, companies=None, key_products=None):
    return {"id": nid, "label": label, "stage": stage, "is_core": core,
            "companies": companies or [], "key_products": key_products or [],
            "description": "", "evidence_ids": [], "source_tier": "industry_common"}


def _baijiu_topo(brand_companies):
    """白酒没有专属画像 → 走 generic，正是 KB 归属裁决真正生效的场景。"""
    return _topo([
        _n("U1", "包装材料", "upstream", companies=[]),
        _n("U2", "农产品原料", "upstream"),
        _n("M1", "品牌与产品运营", "midstream", core=True, companies=brand_companies,
           key_products=["白酒品牌"]),
        _n("D1", "经销商与终端", "downstream"),
        _n("S1", "食品安全与认证", "support"),
    ])


def test_supplier_removed_from_brand_card():
    topo = _baijiu_topo(["贵州茅台", "五粮液", "奥瑞金"])
    fixed, notes = apply_company_fit(topo, "白酒")
    core = next(n for n in fixed["nodes"] if n["is_core"])
    assert "奥瑞金" not in core["companies"]
    assert "贵州茅台" in core["companies"] and "五粮液" in core["companies"]
    assert any("奥瑞金" in n for n in notes)


def test_supplier_relocated_to_matching_upstream():
    """删掉会让本来就空的上游更空——能对上环节的要归位，不是丢弃。"""
    topo = _baijiu_topo(["奥瑞金"])
    fixed, _ = apply_company_fit(topo, "白酒")
    pack = next(n for n in fixed["nodes"] if n["label"] == "包装材料")
    assert "奥瑞金" in pack["companies"]


def test_missing_company_is_kept():
    """境外/未上市（无 KB 记录）必须原样保留。"""
    topo = _baijiu_topo(["贵州茅台", "保乐力加", "帝亚吉欧"])
    fixed, notes = apply_company_fit(topo, "白酒")
    core = next(n for n in fixed["nodes"] if n["is_core"])
    assert "保乐力加" in core["companies"]
    assert "帝亚吉欧" in core["companies"]
    assert not notes


def test_profile_known_names_are_exempt():
    """画像 leading_brand 里的名字一律跳过（隆基绿能：2021 分类是硅料硅片，但它是组件龙头）。"""
    topo = _topo([
        _n("U1", "硅料与硅片", "upstream"),
        _n("M1", "组件封装与出货", "midstream", core=True,
           companies=["隆基绿能", "晶科能源"], key_products=["组件"]),
        _n("S1", "检测认证", "support"),
    ])
    fixed, notes = apply_company_fit(topo, "光伏")
    core = next(n for n in fixed["nodes"] if n["is_core"])
    assert "隆基绿能" in core["companies"], "画像点名的龙头不能被 KB 判成供应商"
    assert not notes


def test_profile_upstream_leaders_are_left_to_rehome():
    """画像 `leading_upstream` 的名字不归 KB 管——风电的东方电缆由 F8 归位器处理。

    两条规则各管一段，不能互相拆台：KB 管"画像没覆盖的行业"，
    画像管"它自己点名过的公司"。
    """
    topo = _topo([
        _n("U1", "海缆/电缆", "upstream"),
        _n("M1", "整机制造与总装", "midstream", core=True,
           companies=["金风科技", "东方电缆"], key_products=["整机"]),
        _n("S1", "检验检测与认证", "support"),
    ], subject="海上风电")
    fixed, notes = apply_company_fit(topo, "海上风电")
    core = next(n for n in fixed["nodes"] if n["is_core"])
    assert "东方电缆" in core["companies"], "画像已登记的上游龙头由归位器处理，KB 不越权"
    assert not notes


def test_idempotent_and_noop_without_core():
    topo = _baijiu_topo(["奥瑞金"])
    once, _ = apply_company_fit(topo, "白酒")
    twice, _ = apply_company_fit(once, "海上风电")
    assert twice == once

    no_core = _topo([_n("U1", "包装材料", "upstream", companies=["奥瑞金"])])
    same, notes = apply_company_fit(no_core, "海上风电")
    assert same == no_core and not notes


def test_repair_topology_runs_company_fit():
    """接入点验证：走完整 repair 管线也能摘掉品牌卡上的供应商。"""
    fixed, repairs = repair_topology(_baijiu_topo(["金风科技", "奥瑞金"]), subject="海上风电")
    core = next(n for n in fixed["nodes"] if n["is_core"])
    assert "奥瑞金" not in core["companies"]
    assert any("奥瑞金" in r for r in repairs)
