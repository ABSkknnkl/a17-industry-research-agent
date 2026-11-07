#!/usr/bin/env python3
"""产业链图批量诊断套件（P2，2026-10-19）。

一次跑完 N 个行业的产业链图诊断，产出 AI 可直接消费的 ``report.json`` 与
人可读的 ``report.md``。三种模式：

    synthetic  从行业画像合成"理想拓扑"→ 断言规则不误杀（秒级，50/50）
    inject     在合成拓扑上注入已知缺陷 → 断言规则能抓到（验证不漏报）
    real       用 ``data/runs/`` 里真实 A2 拓扑（走 hoist + repair 后诊断）

用法::

    python scripts/run_chain_suite.py --mode synthetic
    python scripts/run_chain_suite.py --mode inject
    python scripts/run_chain_suite.py --mode real
    python scripts/run_chain_suite.py --mode all --out output/chain_suite

设计原则（与实施方案 §四 对齐）：

1. **测规则不测行业**：50 个行业共用同一套 25 条规则；
2. **两遍才可信**：synthetic 证明不误杀，inject 证明不漏报；
3. **每个问题可定位**：Finding 带 ``rule_id + code_ref + hint``；
4. **L0 是预期行为**：无画像行业只要求 0 P0，P1（空卡）/P2（覆盖）不算失败。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "agents_core" / "chart-generator"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from chart_generator.chain_diag import RULE_REGISTRY, diagnose  # noqa: E402
from chart_generator.chain_loader import profile_level  # noqa: E402
from chart_generator.chain_structure import detect_structure  # noqa: E402
from chart_generator.chain_profile import (  # noqa: E402
    cert_bodies,
    detect_profile,
    leading_companies,
    mid_card_pool,
    upstream_leaders,
)

CASES = ROOT / "agents_core" / "chart-generator" / "chain_cases" / "cases.json"
RUNS = ROOT / "data" / "runs"

# real 模式使用的真实 run（与 scratch/verify_f8_f14_offline.py 同源）
REAL_RUNS = {
    "海上风电": "run-20261019123544-c4c98d",
    "工业机器人": "run-20261019123544-6449d0",
    "创新药": "run-20261019125108-f84de2",
    "半导体设备（刻蚀/沉积）": "run-20261019124137-542817",
    "消费级无人机": "run-20261019130155-9ff867",
    "车载激光雷达": "run-20261019125531-1b6ab6",
}


# ── 拓扑合成器 ────────────────────────────────────────────────────────────

def _synthesize_from_structure(subject: str, struct, prof: dict[str, Any]) -> dict[str, Any]:
    """按**结构骨架**合成拓扑（消费品/流程/医药/数字/服务用这个）。

    与离散制造的区别：环节来自 ``struct.stages``，不是"核心部件/整机制造"的硬编码。
    白酒这类主题因此得到「农产品原料 → 酿造灌装 → 品牌运营(核心) → 经销商 → 商超」，
    而不是「专用设备 → 整机制造」。
    """
    brands = [c for c in (prof.get("leading_brand") or []) if c][:6]
    ups = [c for c in (prof.get("leading_upstream") or []) if c]

    up = [s for s in struct.stages if s.stage == "upstream"]
    mid = [s for s in struct.stages if s.stage == "midstream"]
    down = [s for s in struct.stages if s.stage == "downstream"]
    sup = [s for s in struct.stages if s.stage == "support"]
    core = next((s for s in mid if s.is_core), mid[0] if mid else None)
    core_id = "M-core"

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    used: set[str] = set(brands)

    for i, st in enumerate(up):
        comps = [ups[i]] if i < len(ups) and ups[i] not in used else []
        used.update(comps)
        nodes.append({
            "id": f"U{i+1}", "label": st.label, "companies": comps,
            "key_products": list(st.key_products) or [st.label],
            "description": f"提供{st.label}", "stage": "upstream",
            "is_core": False, "bottleneck": i == 0, "evidence_ids": [],
        })

    for i, st in enumerate(mid):
        nid = core_id if st is core else f"M{i+1}"
        nodes.append({
            "id": nid, "label": st.label,
            "companies": brands if st.is_core else [],
            "key_products": list(st.key_products) or [st.label],
            "description": f"{st.label}环节",
            "stage": "midstream", "is_core": bool(st.is_core),
            "bottleneck": False, "evidence_ids": [],
        })

    for i, st in enumerate(down):
        nodes.append({
            "id": f"D{i+1}", "label": st.label, "companies": [],
            "key_products": list(st.key_products) or [st.label],
            "description": f"{st.label}场景", "stage": "downstream",
            "is_core": False, "bottleneck": False,
            "phase": ["已落地", "试点中", "示范期", "远期"][i % 4],
            "buyer": "终端客户", "evidence_ids": [],
        })

    from chart_generator.chain_profile import cert_bodies
    certs = cert_bodies(subject)
    for i, st in enumerate(sup):
        comps = certs[:2] if ("认证" in st.label or "检测" in st.label) else []
        nodes.append({
            "id": f"S{i+1}", "label": st.label, "companies": comps,
            "key_products": list(st.key_products) or [st.label],
            "description": f"{st.label}支撑", "stage": "support",
            "is_core": False, "bottleneck": False, "evidence_ids": [],
        })

    for i in range(len(up)):
        edges.append({"source": f"U{i+1}", "target": core_id,
                      "label": "原料供给", "flow": "material"})
    for i, st in enumerate(mid):
        if st is core:
            continue
        nid = f"M{i+1}"
        edges.append({"source": nid, "target": core_id,
                      "label": "工艺方案", "flow": "technical"})
    for i in range(len(down)):
        edges.append({"source": core_id, "target": f"D{i+1}",
                      "label": "产品交付", "flow": "material"})
    for i in range(len(sup)):
        edges.append({"source": core_id, "target": f"S{i+1}",
                      "label": "配套支撑", "flow": "service"})

    return {
        "title": f"{subject}产业链全景图",
        "subtitle": f"{struct.name}结构",
        # 🔴 core_product 用主题词，不用骨架节点 label——节点名是结构模板词
        # （如「品牌与产品运营」），当检索词命中率极低（build_gap_queries 的既定约束）。
        "core_product": subject,
        "structure": struct.key,
        "nodes": nodes,
        "edges": edges,
    }


def synthesize(subject: str, prof: dict[str, Any]) -> dict[str, Any]:
    """按画像合成一个"结构合法"的拓扑，用来验证规则不会误杀。

    设计目标：让 L1/L2 行业得到 0 P0、0 P1；L0 行业允许 CHAIN-CAP-01（空企业卡）
    与 CHAIN-COVER-01（无画像），这是降级的**预期行为**，不是失败。

    能力卡尽量填人（cap_pool / mid_card_pool / leading_upstream），否则合成器自己
    造出的空卡会淹没真实问题——"验证规则不误杀"的前提是喂给它一个**合规的样本**。
    """
    # 2026-10-20：先判结构。非离散制造（消费品/流程/医药/数字/服务）走各自骨架，
    # 不再被硬套成"核心部件 → 整机制造"。白酒因此得到"农产品→酿造→品牌→渠道"。
    struct = detect_structure(subject)
    if struct.key != "discrete":
        return _synthesize_from_structure(subject, struct, prof)

    brands = [c for c in (prof.get("leading_brand") or []) if c][:6]
    ups = [c for c in (prof.get("leading_upstream") or []) if c]
    up_items = [x for x in (prof.get("upstream") or []) if isinstance(x, str)][:6]
    mid_cards = prof.get("mid_cards") or []
    cert_word = str(prof.get("cert") or "").strip()
    # generic 画像的 cert 是说明性文本（"按行业真实名称填写…"），不能当节点名
    if not cert_word or "填写" in cert_word or "按行业" in cert_word:
        cert_word = "测试与认证"
    certs = cert_bodies(subject)
    caps = [c for c in (prof.get("cap_pool") or []) if c]
    mid_pool = mid_card_pool(subject) or {}

    used: set[str] = set(brands) | set(certs[:2])
    def _take(pool: list[str], n: int = 1) -> list[str]:
        out = [c for c in pool if c not in used][:n]
        used.update(out)
        return out

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    # 上游 6 个（第一个标瓶颈），企业优先取 leading_upstream，其次 upstream_anchor 反查
    base_up = up_items or ["核心部件", "关键材料", "基础器件", "专用设备",
                           "检测仪器", "配套服务"]
    anchor_map = prof.get("upstream_anchor") or {}
    for i, label in enumerate(base_up[:6]):
        pool = ups[i:i+1] or [c for c, kw in anchor_map.items()
                              if any(k in label for k in str(kw).split("/"))]
        comps = _take(pool, 1)
        nodes.append({
            "id": f"U{i+1}", "label": label,
            "companies": comps,
            "key_products": [f"{label}产品"],
            "description": f"提供{label}",
            "stage": "upstream", "is_core": False,
            "bottleneck": i == 0, "evidence_ids": [],
        })

    # 中游 3 个：研发 / 整机（core）/ 制造
    rd_label = "研发与设计"
    for card in mid_cards:
        if isinstance(card, (list, tuple)) and card and "研发" in str(card[0]):
            rd_label = str(card[0])
            break
    m2_label = str(mid_cards[1][0]) if len(mid_cards) > 1 else "整机制造与总装"
    m3_label = str(mid_cards[2][0]) if len(mid_cards) > 2 else "制造与集成"

    # 🔴 不用 cap_pool 兜底：cap_pool 是"通用候选池"，直接填进特定环节正是
    # F12 要拦的错配（半导体「设备研发」被塞华亚智能/先锋精科＝精密结构件商）。
    # 匹配不到就留空——宁可空卡（P1），不可错配（P0）。
    rd_pool = list(mid_pool.get(rd_label) or [])
    nodes.append({
        "id": "M1", "label": rd_label, "companies": _take(rd_pool, 2),
        "key_products": ["设计方案"], "description": "输出图纸与技术方案",
        "stage": "midstream", "is_core": False, "bottleneck": False,
        "evidence_ids": [],
    })
    nodes.append({
        "id": "M2", "label": m2_label, "companies": brands,
        "key_products": ["整机"], "description": "集成为整机并出厂",
        "stage": "midstream", "is_core": True, "bottleneck": False,
        "evidence_ids": [],
    })
    m3_pool = list(mid_pool.get(m3_label) or [])
    nodes.append({
        "id": "M3", "label": m3_label, "companies": _take(m3_pool, 2),
        "key_products": ["制造服务"], "description": "承接制造与集成",
        "stage": "midstream", "is_core": False, "bottleneck": False,
        "evidence_ids": [],
    })

    # 下游 4 个（phase/buyer 齐备）
    for i, (label, buyer) in enumerate([
        ("工业应用", "工业企业"), ("消费应用", "个人用户"),
        ("政府采购", "政府与公共部门"), ("海外市场", "海外客户"),
    ]):
        nodes.append({
            "id": f"D{i+1}", "label": label, "companies": [],
            "key_products": ["应用场景"], "description": f"{label}场景",
            "stage": "downstream", "is_core": False, "bottleneck": False,
            "phase": ["已落地", "试点中", "示范期", "远期"][i],
            "buyer": buyer, "evidence_ids": [],
        })

    # 配套 3 个（认证卡填真实机构）
    sup = [("运维与回收", []), ("软件与数据服务", []),
           (cert_word or "测试与认证", certs[:2])]
    for i, (label, comps) in enumerate(sup):
        nodes.append({
            "id": f"S{i+1}", "label": label, "companies": list(comps),
            "key_products": ["配套服务"], "description": "支撑主链运行",
            "stage": "support", "is_core": False, "bottleneck": False,
            "evidence_ids": [],
        })

    # 连线：上游→整机、研发→整机、整机→下游、整机→配套
    for i in range(1, 7):
        edges.append({"source": f"U{i}", "target": "M2", "label": "部件供应", "flow": "material"})
    edges.append({"source": "M1", "target": "M2", "label": "设计方案", "flow": "technical"})
    edges.append({"source": "M3", "target": "M2", "label": "制造服务", "flow": "service"})
    for i in range(1, 5):
        edges.append({"source": "M2", "target": f"D{i}", "label": "整机交付", "flow": "material"})
    edges.append({"source": "M2", "target": "S1", "label": "售后支持", "flow": "service"})
    edges.append({"source": "M2", "target": "S2", "label": "数据服务", "flow": "service"})
    edges.append({"source": "M2", "target": "S3", "label": "送检认证", "flow": "service"})

    return {
        "title": f"{subject}产业链全景图",
        "subtitle": "上游 → 整机 → 下游",
        "core_product": "整机",
        "nodes": nodes,
        "edges": edges,
    }


# ── 缺陷注入 ──────────────────────────────────────────────────────────────

def inject_defect(topo: dict[str, Any], subject: str) -> tuple[dict[str, Any], str]:
    """注入一个已知缺陷，返回 (改后的拓扑, 期望命中的 rule_id)。

    按画像能力分三级（**L0 不能注入品牌卡问题**——无基准时规则按设计不断言，
    注入了也不会报，那是正确行为不是漏报）：

    1. 有 upstream 龙头 → 塞进品牌卡，期望 CHAIN-BRAND-03；
    2. 有品牌基准但无 upstream → 塞杂牌，期望 CHAIN-BRAND-02；
    3. L0（无任何基准）→ 制造企业跨节点重复，期望 CHAIN-STRUCT-08。
    """
    import copy
    t = copy.deepcopy(topo)
    core = next((n for n in t["nodes"] if n.get("is_core")), None)
    if core is None:
        return t, "CHAIN-STRUCT-02"

    ups = upstream_leaders(subject)
    if ups:
        core["companies"] = list(core.get("companies") or []) + [ups[0]]
        return t, "CHAIN-BRAND-03"

    if leading_companies(subject):
        core["companies"] = list(core.get("companies") or []) + ["某某贸易"]
        return t, "CHAIN-BRAND-02"

    up = next((n for n in t["nodes"]
               if n.get("stage") == "upstream" and n.get("companies")), None)
    if up is not None:
        up["companies"] = list(up["companies"]) + [core["companies"][0]]
        return t, "CHAIN-STRUCT-08"

    for n in t["nodes"]:
        n["is_core"] = False
    return t, "CHAIN-STRUCT-02"


# ── 运行与汇总 ────────────────────────────────────────────────────────────

def load_cases() -> list[dict[str, Any]]:
    return json.loads(CASES.read_text(encoding="utf-8"))["cases"]


def run_synthetic(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for case in cases:
        subj = case["subject"]
        prof = detect_profile(subj)
        topo = synthesize(subj, prof)
        rep = diagnose(topo, subject=subj, stage="post_repair")
        rows.append({
            "case": case,
            "mode": "synthetic",
            "actual_level": profile_level(prof),
            "verdict": rep.verdict,
            "metrics": rep.metrics,
            "findings": [f.to_dict() for f in rep.findings],
        })
    return rows


def run_inject(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for case in cases:
        subj = case["subject"]
        prof = detect_profile(subj)
        topo = synthesize(subj, prof)
        bad, expect = inject_defect(topo, subj)
        rep = diagnose(bad, subject=subj, stage="pre_repair")
        got = {f.rule_id for f in rep.findings}
        rows.append({
            "case": case,
            "mode": "inject",
            "expected_rule": expect,
            "detected": expect in got,
            "verdict": rep.verdict,
            "findings": [f.to_dict() for f in rep.findings],
        })
    return rows


def run_real() -> list[dict[str, Any]]:
    from chart_generator.chain_render import render_chain_svg
    from chart_generator.chain_topology import (
        hoist_leading_to_brand_card,
        repair_topology,
        topology_to_spec,
    )

    rows = []
    for subj, rid in REAL_RUNS.items():
        fp = RUNS / rid / "artifacts" / "interpretation_report.json"
        if not fp.exists():
            rows.append({"case": {"subject": subj, "level": "?"}, "mode": "real",
                         "verdict": "skip", "findings": [], "error": f"缺少 {rid}"})
            continue
        raw = json.loads(fp.read_text(encoding="utf-8"))["industry_chain_topology"]
        fixed, _ = hoist_leading_to_brand_card(raw, subj)
        fixed, _ = repair_topology(fixed, allowed_companies=None)
        svg = render_chain_svg(topology_to_spec(fixed, fallback_title=subj))
        rep = diagnose(fixed, subject=subj, svg=svg)
        rows.append({
            "case": {"subject": subj, "level": profile_level(detect_profile(subj))},
            "mode": "real",
            "verdict": rep.verdict,
            "metrics": rep.metrics,
            "findings": [f.to_dict() for f in rep.findings],
            "run_id": rid,
        })
    return rows


# ── 报告 ──────────────────────────────────────────────────────────────────

def summarize(rows: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    p0_cases = [r for r in rows if any(f["severity"] == "P0" for f in r.get("findings", []))]
    by_rule: Counter[str] = Counter()
    by_sev: Counter[str] = Counter()
    for r in rows:
        for f in r.get("findings", []):
            by_rule[f["rule_id"]] += 1
            by_sev[f["severity"]] += 1
    out = {
        "mode": mode,
        "total": len(rows),
        "p0_cases": len(p0_cases),
        "pass": sum(1 for r in rows if r["verdict"] == "pass"),
        "warn": sum(1 for r in rows if r["verdict"] == "warn"),
        "fail": sum(1 for r in rows if r["verdict"] == "fail"),
        "by_rule": dict(by_rule.most_common()),
        "by_severity": dict(by_sev),
    }
    if mode == "inject":
        out["detected"] = sum(1 for r in rows if r.get("detected"))
        out["detection_rate"] = round(out["detected"] / len(rows), 4) if rows else 0
    return out


def write_markdown(rows: list[dict[str, Any]], summary: dict[str, Any], path: Path) -> None:
    lines = [
        "# 产业链图批量诊断报告",
        "",
        f"> 生成时间：{datetime.now():%Y-%m-%d %H:%M:%S}　模式：**{summary['mode']}**",
        f"> 行业数：{summary['total']}　P0 行业：{summary['p0_cases']}　"
        f"pass/warn/fail：{summary['pass']}/{summary['warn']}/{summary['fail']}",
        "",
    ]
    if "detection_rate" in summary:
        lines += [f"> 缺陷注入检出率：**{summary['detection_rate']*100:.1f}%**"
                  f"（{summary['detected']}/{summary['total']}）", ""]

    lines += ["## 按规则聚合（一类问题一次修完）", ""]
    if not summary["by_rule"]:
        lines += ["无问题命中。", ""]
    for rule_id, cnt in summary["by_rule"].items():
        meta = RULE_REGISTRY.get(rule_id, {})
        lines.append(f"### {rule_id} · {meta.get('name', '')}（{cnt} 例，{meta.get('sev','')}）")
        samples = [(r["case"]["subject"], f) for r in rows for f in r.get("findings", [])
                   if f["rule_id"] == rule_id][:8]
        lines.append("")
        lines.append("| 行业 | 节点 | 说明 | 修复动作 |")
        lines.append("|---|---|---|---|")
        for subj, f in samples:
            lines.append(f"| {subj} | {f.get('node_label','-')} | {f['message'][:60]} | "
                         f"{f.get('hint','')[:50]} |")
        lines.append("")

    lines += ["## 逐行业明细", "", "| 行业 | 等级 | 判定 | P0 | P1 | 主要问题 |", "|---|---|---|---|---|---|"]
    for r in rows:
        fs = r.get("findings", [])
        rules = "、".join(sorted({f["rule_id"] for f in fs}))[:70] or "—"
        m = r.get("metrics") or {}
        lines.append(f"| {r['case']['subject']} | {r['case'].get('level','?')} | "
                     f"{r['verdict']} | {m.get('p0',0)} | {m.get('p1',0)} | {rules} |")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="产业链图批量诊断套件")
    ap.add_argument("--mode", choices=["synthetic", "inject", "real", "all"], default="all")
    ap.add_argument("--out", default="output/chain_suite")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    cases = load_cases()
    if args.limit:
        cases = cases[: args.limit]

    outdir = ROOT / args.out / datetime.now().strftime("%Y%m%d_%H%M%S")
    outdir.mkdir(parents=True, exist_ok=True)

    all_rows: list[dict[str, Any]] = []
    summary: dict[str, Any] = {"mode": args.mode, "runs": {}}

    if args.mode in ("synthetic", "all"):
        rows = run_synthetic(cases)
        s = summarize(rows, "synthetic")
        summary["runs"]["synthetic"] = s
        all_rows += rows
        print(f"[synthetic] {s['total']} 行业  P0 行业={s['p0_cases']}  "
              f"pass/warn/fail={s['pass']}/{s['warn']}/{s['fail']}")

    if args.mode in ("inject", "all"):
        rows2 = run_inject(cases)
        s2 = summarize(rows2, "inject")
        summary["runs"]["inject"] = s2
        all_rows += rows2
        print(f"[inject]    {s2['total']} 行业  检出率={s2['detection_rate']*100:.1f}%")

    if args.mode in ("real", "all"):
        rows3 = run_real()
        s3 = summarize(rows3, "real")
        summary["runs"]["real"] = s3
        all_rows += rows3
        print(f"[real]      {s3['total']} 行业  P0 行业={s3['p0_cases']}")

    (outdir / "report.json").write_text(
        json.dumps({"summary": summary, "rows": all_rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_markdown(all_rows, summary["runs"].get("synthetic") or summarize(all_rows, args.mode),
                   outdir / "report.md")
    print(f"\n报告：{outdir/'report.json'}\n      {outdir/'report.md'}")

    if args.mode in ("synthetic", "all"):
        s = summary["runs"]["synthetic"]
        if s["p0_cases"]:
            print(f"🔴 synthetic 出现 {s['p0_cases']} 个 P0 行业——见报告")
            return 1
    if args.mode in ("inject", "all"):
        s2 = summary["runs"]["inject"]
        if s2["detection_rate"] < 1.0:
            print(f"🔴 缺陷注入检出率 {s2['detection_rate']*100:.1f}% < 100%")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
