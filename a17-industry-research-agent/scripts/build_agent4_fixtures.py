"""Build reproducible, desensitised SYNTHETIC fixtures for the Agent-4 refactor.

Run from the application root::

    env -u PYTHONPATH /Users/Zhuanz1/miniconda3/bin/python3 scripts/build_agent4_fixtures.py

Everything written here is synthetic. It must never be reported as real model
output; the only real acceptance run is the one governed by section 09.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agents_core" / "chapter-writer"))

from chapter_writer.models import ChapterWritingRequest, ChapterWritingResult  # noqa: E402
from chapter_writer.outline import DEFAULT_OUTLINE  # noqa: E402

OUT = ROOT / "output" / "agent4_refactor_eval"
FIXTURES = OUT / "fixtures"
AS_OF = "2026-11-09"
GENERATED_AT = "2026-11-09T00:00:00+00:00"


def _evidence(rid: str, domain: str, entity: str, metric: str, value, unit: str, period: str) -> dict:
    return {
        "record_id": rid, "domain": domain, "entity": entity, "metric": metric,
        "value": value, "unit": unit, "period": period,
        "scope": "consolidated", "currency": "CNY",
    }


def _requirement(rid: str, label: str, domain: str, families: list[str],
                 passed: bool, eids: list[str]) -> dict:
    return {
        "requirement": {
            "requirement_id": rid, "label": label, "domain": domain,
            "hard": True, "metric_families": families,
        },
        "coverage": {"passed": passed, "evidence_record_ids": eids},
    }


def _report(report_id: str, subject: str, evidence: dict, matrix: list[dict],
            segments: list[dict], comps: dict | None = None) -> dict:
    return {
        "report_id": report_id, "subject": subject, "as_of": AS_OF, "status": "completed",
        "executive_summary": "合成夹具，仅用于离线对照，不代表真实研究结论。",
        "key_metrics": [], "trends": [], "anomalies": [], "cross_validations": [],
        "knowledge_facts": [], "insights": [], "content_outline": [],
        "evidence_index": evidence,
        "comps_matrix": comps,
        "industry_chain_segments": segments,
        "financial_ratios": [],
        "data_quality": {"record_count": len(evidence)},
        "data_quality_appendix": {"requirement_evidence_matrix": matrix},
        "warnings": ["SYNTHETIC FIXTURE - offline evaluation only"],
    }


def _chart(cid: str, title: str, chapter: str, eids: list[str]) -> dict:
    return {
        "chart_id": cid, "title": title, "chart_type": "line", "status": "ready",
        "evidence_ids": eids, "insight_goal": "离线夹具图表",
        "recommended_chapter_id": chapter, "svg_uri": None,
    }


def _request(report: dict, charts: list[dict]) -> dict:
    return {
        "report": report,
        "selected_skills": [],
        "charts": {"run_id": "synthetic", "charts": charts, "warnings": []},
        "input_dataset": None,
        "outline": None,
        "options": {"style": "professional", "audience": "证券研究人员",
                    "target_length": "standard", "instruction": None, "max_repairs": 2},
    }


# ---------------------------------------------------------------- case A
# Deliberately repeats one financial conclusion across three chapters. The
# matrix contains several hard "financials" rows, which is the verified cause
# of cross-chapter expansion in retriever.DOMAIN_AFFINITY.
CASE_A_EVIDENCE = {
    "A-NEV-SALES-21": _evidence("A-NEV-SALES-21", "industry", "中国新能源汽车", "新能源汽车销量", 352.1, "万辆", "2021-12-31"),
    "A-NEV-SALES-25": _evidence("A-NEV-SALES-25", "industry", "中国新能源汽车", "新能源汽车销量", 1286.6, "万辆", "2025-12-31"),
    "A-NEV-PEN-21": _evidence("A-NEV-PEN-21", "industry", "中国新能源汽车", "市场渗透率", 13.4, "%", "2021-12-31"),
    "A-NEV-PEN-25": _evidence("A-NEV-PEN-25", "industry", "中国新能源汽车", "市场渗透率", 45.8, "%", "2025-12-31"),
    "A-BYD-REV-24": _evidence("A-BYD-REV-24", "financials", "比亚迪", "营业收入", 7771.02, "亿元", "2024-12-31"),
    "A-BYD-GM-24": _evidence("A-BYD-GM-24", "financials", "比亚迪", "销售毛利率", 20.7, "%", "2024-12-31"),
    "A-BYD-OCF-24": _evidence("A-BYD-OCF-24", "financials", "比亚迪", "经营现金流", 1335.4, "亿元", "2024-12-31"),
    "A-CA-REV-24": _evidence("A-CA-REV-24", "financials", "长安汽车", "营业收入", 1597.33, "亿元", "2024-12-31"),
    "A-CA-GM-24": _evidence("A-CA-GM-24", "financials", "长安汽车", "销售毛利率", 14.2, "%", "2024-12-31"),
    "A-SERES-REV-24": _evidence("A-SERES-REV-24", "financials", "赛力斯", "营业收入", 1451.76, "亿元", "2024-12-31"),
    "A-CATL-RD-24": _evidence("A-CATL-RD-24", "financials", "宁德时代", "研发费用", 186.07, "亿元", "2024-12-31"),
    "A-CATL-NM-24": _evidence("A-CATL-NM-24", "financials", "宁德时代", "销售净利率", 14.1, "%", "2024-12-31"),
}

CASE_A_MATRIX = [
    _requirement("a-nev-sales", "2021-2025 年销量趋势", "industry", ["nev_sales"], True, ["A-NEV-SALES-21", "A-NEV-SALES-25"]),
    _requirement("a-nev-pen", "2021-2025 年渗透率", "industry", ["nev_penetration"], True, ["A-NEV-PEN-21", "A-NEV-PEN-25"]),
    _requirement("a-revenue", "三家车企营业收入", "financials", ["revenue"], True, ["A-BYD-REV-24", "A-CA-REV-24", "A-SERES-REV-24"]),
    _requirement("a-gross-margin", "三家车企毛利率", "financials", ["gross_margin"], True, ["A-BYD-GM-24", "A-CA-GM-24"]),
    _requirement("a-ocf", "经营现金流", "financials", ["operating_cash_flow"], True, ["A-BYD-OCF-24"]),
    _requirement("a-rd", "动力电池研发强度", "financials", ["rd_expense"], True, ["A-CATL-RD-24"]),
    _requirement("a-net-margin", "动力电池利润率", "financials", ["net_margin"], True, ["A-CATL-NM-24"]),
    _requirement("a-exports", "出口量", "industry", ["nev_exports"], False, []),
]

# Exact-duplicate paragraph text used in CH-02, CH-05 and CH-07.
REPEATED_TEXT = (
    "比亚迪 2024 年营业收入 7771.02 亿元、毛利率 20.7%、经营现金流 1335.4 亿元。"
    "长安汽车营业收入 1597.33 亿元、毛利率 14.2%。赛力斯营业收入 1451.76 亿元。"
)
NEAR_REPEATED_TEXT = (
    "比亚迪 2024 年营业收入 7771.02 亿元、毛利率 20.7%、经营现金流 1335.4 亿元。"
    "长安汽车营业收入 1597.33 亿元、毛利率 14.3%。赛力斯营业收入 1451.76 亿元。"
)


def _baseline_chapters(subject: str) -> dict:
    """Seven chapters / 21 sections with known cross-chapter duplicate paragraphs."""
    chapters = []
    for chapter in DEFAULT_OUTLINE:
        sections = []
        for section in chapter.sections:
            pid = f"P-{section.section_id[4:].replace('-', '-')}-01"
            text = "合成夹具正文：本节用于离线重复率与信息密度评估。"
            if section.section_id in ("SEC-02-01", "SEC-05-01", "SEC-07-03"):
                text = REPEATED_TEXT
            elif section.section_id == "SEC-04-02":
                text = NEAR_REPEATED_TEXT
            elif section.section_id == "SEC-02-02":
                text = (
                    "2021 年销量 352.1 万辆、渗透率 13.4%；2025 年销量 1286.6 万辆、"
                    "渗透率 45.8%。"
                )
            sections.append({
                "section_id": section.section_id, "title": section.title,
                "purpose": section.purpose, "key_points": [],
                "paragraphs": [{
                    "paragraph_id": pid, "kind": "analysis", "text": text,
                    "evidence_ids": ["A-BYD-REV-24"] if text == REPEATED_TEXT else [],
                    "assumption_note": None,
                }],
                "chart_ids": [], "uncertainties": [], "metric_cards": [],
                "comparison_table": None, "callouts": [], "layout_hint": "text_only",
            })
        chapters.append({
            "chapter_id": chapter.chapter_id, "title": chapter.title,
            "summary": "合成夹具章节摘要", "sections": sections,
            "evidence_ids": [], "chart_ids": [], "used_fallback": False,
            "content_audit": [],
        })
    return {
        "run_id": "synthetic-baseline", "source_report_id": "synthetic-a",
        "subject": subject, "as_of": AS_OF, "status": "completed",
        "generated_at": GENERATED_AT, "outline_version": "2026.1",
        "model_name": "offline-stub", "applied_skills": [], "chapters": chapters,
        "quality": {"passed": True, "chapter_count": len(chapters),
                    "section_count": sum(len(c["sections"]) for c in chapters),
                    "evidence_coverage": 0.0, "issues": [], "fallback_chapter_ids": []},
        "warnings": ["SYNTHETIC FIXTURE - not real model output"],
        "artifact_dir": None,
    }


def _case_a() -> tuple[dict, dict, dict]:
    report = _report("synthetic-a-repetitive", "新能源汽车（合成夹具）", CASE_A_EVIDENCE,
                     CASE_A_MATRIX, [], comps={
                         "entries": [{"company_name": "比亚迪", "market_cap": 8000.0, "valuation_tier": "profitable"}],
                         "total_market_cap": 8000.0, "median_pe": 21.5, "median_pb": 3.2,
                         "median_gross_margin": 18.9,
                     })
    charts = [
        _chart("CHART-A-01", "销量与渗透率趋势（合成）", "CH-02", ["A-NEV-SALES-21", "A-NEV-SALES-25"]),
        _chart("CHART-A-02", "三家车企财务对比（合成）", "CH-05", ["A-BYD-REV-24", "A-CA-REV-24"]),
    ]
    meta = {
        "case_id": "case_a_repetitive", "synthetic": True,
        "purpose": "正文重复明显的高重复样本，用于 G2/G3 对照",
        "original_questions": [
            "2021-2025 年销量与渗透率如何变化？",
            "三家整车企业营收、毛利率、经营现金流如何分化？",
            "动力电池与整车环节如何分组？",
        ],
        "answerable_requirements": [r["requirement"]["requirement_id"] for r in CASE_A_MATRIX
                                    if r["coverage"]["passed"]],
        "data_gaps": ["a-exports：出口量无有效证据，coverage.passed=false"],
        "report_id": report["report_id"], "chart_ids": [c["chart_id"] for c in charts],
        "model_config": {"mode": "offline-stub", "real_llm_calls": 0},
    }
    return _request(report, charts), meta, _baseline_chapters(report["subject"])


# ---------------------------------------------------------------- case B
CASE_B_EVIDENCE = {
    "B-IND-01": _evidence("B-IND-01", "industry", "工业软件", "市场规模", 2800.0, "亿元", "2025-12-31"),
    "B-FIN-01": _evidence("B-FIN-01", "financials", "示例企业甲", "营业收入", 42.6, "亿元", "2024-12-31"),
}
CASE_B_MATRIX = [
    _requirement("b-market", "市场规模", "industry", ["market_size"], True, ["B-IND-01"]),
    _requirement("b-cash-flow", "经营现金流", "financials", ["operating_cash_flow"], False, []),
    _requirement("b-rd", "研发投入", "financials", ["rd_expense"], False, []),
]


def _case_b() -> tuple[dict, dict]:
    report = _report("synthetic-b-sparse", "工业软件（合成夹具）", CASE_B_EVIDENCE,
                     CASE_B_MATRIX, [])
    meta = {
        "case_id": "case_b_sparse_non_aerospace", "synthetic": True,
        "purpose": "证据稀疏的非航天样本，用于 G1 行业污染与缺数据缺口检查",
        "original_questions": ["市场规模有多大？", "经营现金流与研发投入如何？"],
        "answerable_requirements": ["b-market"],
        "data_gaps": ["b-cash-flow：缺经营现金流证据", "b-rd：缺研发投入证据"],
        "report_id": report["report_id"], "chart_ids": [],
        "model_config": {"mode": "offline-stub", "real_llm_calls": 0},
    }
    return _request(report, []), meta


# ---------------------------------------------------------------- case C
CASE_C_EVIDENCE = {
    "C-COMP-01": _evidence("C-COMP-01", "companies", "中国卫星", "营业收入", 75.5, "亿元", "2024-12-31"),
    "C-COMP-02": _evidence("C-COMP-02", "companies", "铖昌科技", "销售毛利率", 72.68, "%", "2024-12-31"),
}
CASE_C_SEGMENTS = [
    {"segment_name": "上游：核心元器件", "stage": "upstream",
     "representative_companies": ["铖昌科技"], "evidence_record_ids": ["C-COMP-02"]},
    {"segment_name": "中游：卫星研制与系统总装", "stage": "midstream",
     "representative_companies": ["中国卫星"], "evidence_record_ids": []},
    {"segment_name": "下游：卫星运营服务", "stage": "downstream",
     "representative_companies": ["中国卫通"], "evidence_record_ids": []},
]


def _case_c() -> tuple[dict, dict]:
    report = _report("synthetic-c-aerospace", "商业航天（合成夹具）", CASE_C_EVIDENCE,
                     [_requirement("c-sat-revenue", "中国卫星营业收入", "companies", ["revenue"],
                                   True, ["C-COMP-01"])],
                     CASE_C_SEGMENTS, comps={
                         "entries": [{"company_name": "中国卫星", "market_cap": 300.0, "valuation_tier": "profitable"}],
                         "total_market_cap": 300.0, "median_pe": 60.0, "median_pb": 4.0,
                         "median_gross_margin": 30.0,
                     })
    charts = [_chart("CHART-C-01", "产业链结构（合成）", "CH-03", ["C-COMP-02"])]
    meta = {
        "case_id": "case_c_aerospace", "synthetic": True,
        "purpose": "航天证据夹具：含 1 条可回指证据的环节关系 + 2 条无证据的待核关系",
        "original_questions": ["中国卫星营业收入是多少？", "代表公司的产业链环节如何归属？"],
        "answerable_requirements": ["c-sat-revenue"],
        "data_gaps": ["中游/下游环节无 evidence_record_ids，归属待核"],
        "report_id": report["report_id"], "chart_ids": [c["chart_id"] for c in charts],
        "model_config": {"mode": "offline-stub", "real_llm_calls": 0},
    }
    return _request(report, charts), meta


def _write_json(path: Path, payload: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(raw, encoding="utf-8")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _annotations(case_a_sha: str) -> dict:
    duplicate = [
        "CH-02/SEC-02-01/P-02-01-01",
        "CH-05/SEC-05-01/P-05-01-01",
        "CH-07/SEC-07-03/P-07-03-01",
    ]
    near = ["CH-04/SEC-04-02/P-04-02-01"]
    readout = [
        {"version": "baseline", "locator": "CH-02/SEC-02-01/P-02-01-01",
         "comparison": 0, "meaning": 0, "boundary": 0, "reason": "仅罗列三家车企数字，无同口径比较、业务含义或边界"},
        {"version": "baseline", "locator": "CH-05/SEC-05-01/P-05-01-01",
         "comparison": 0, "meaning": 0, "boundary": 0, "reason": "与前节完全相同的数字堆叠"},
        {"version": "baseline", "locator": "CH-07/SEC-07-03/P-07-03-01",
         "comparison": 0, "meaning": 0, "boundary": 0, "reason": "结论段重复展开同一组财务数字"},
        {"version": "baseline", "locator": "CH-04/SEC-04-02/P-04-02-01",
         "comparison": 0, "meaning": 0, "boundary": 0, "reason": "近似复写，毛利率口径不同但仍未解读"},
        {"version": "baseline", "locator": "CH-02/SEC-02-02/P-02-02-01",
         "comparison": 1, "meaning": 0, "boundary": 0, "reason": "给出 2021/2025 两端数值但未解释变化原因与统计口径"},
        {"version": "baseline", "locator": "CH-01/SEC-01-03/P-01-03-01",
         "comparison": 0, "meaning": 0, "boundary": 0, "reason": "占位正文，无关键数字"},
    ]
    return {
        "case_id": "case_a_repetitive", "input_sha256": case_a_sha, "synthetic": True,
        "requirements": [
            {"requirement_id": rid, "version": "baseline", "owner_section_id": None,
             "paragraph_locator": None, "evidence_ids": [], "answer_status": "unknown",
             "reason": "基线未做写前分配，主答小节待候选版本标注"}
            for rid in ("a-nev-sales", "a-nev-pen", "a-revenue", "a-gross-margin",
                        "a-ocf", "a-rd", "a-net-margin", "a-exports")
        ],
        "duplicate_paragraph_ids": {"baseline": duplicate, "baseline_near": near, "candidate": []},
        "readout_reviews": readout,
        "notes": "全部段落为合成正文；重复与评分为 T0 人工标注，不代表真实模型能力。",
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    cases: dict[str, dict] = {}

    a_request, a_meta, a_baseline = _case_a()
    a_dir = FIXTURES / "case_a_repetitive"
    a_sha = _write_json(a_dir / "request.json", a_request)
    _write_json(a_dir / "baseline_chapters.json", a_baseline)
    ChapterWritingRequest.model_validate(a_request)
    ChapterWritingResult.model_validate(a_baseline)
    a_meta["input_sha256"] = a_sha
    _write_json(a_dir / "meta.json", a_meta)
    cases["case_a_repetitive"] = {"input_sha256": a_sha, "path": str(a_dir.relative_to(ROOT))}

    b_request, b_meta = _case_b()
    b_dir = FIXTURES / "case_b_sparse_non_aerospace"
    b_sha = _write_json(b_dir / "request.json", b_request)
    ChapterWritingRequest.model_validate(b_request)
    b_meta["input_sha256"] = b_sha
    _write_json(b_dir / "meta.json", b_meta)
    cases["case_b_sparse_non_aerospace"] = {"input_sha256": b_sha, "path": str(b_dir.relative_to(ROOT))}

    c_request, c_meta = _case_c()
    c_dir = FIXTURES / "case_c_aerospace"
    c_sha = _write_json(c_dir / "request.json", c_request)
    ChapterWritingRequest.model_validate(c_request)
    c_meta["input_sha256"] = c_sha
    _write_json(c_dir / "meta.json", c_meta)
    cases["case_c_aerospace"] = {"input_sha256": c_sha, "path": str(c_dir.relative_to(ROOT))}

    _write_json(OUT / "T0_annotations.json", _annotations(a_sha))
    _write_json(OUT / "T0_fixture_manifest.json", {
        "batch_id": "agent4-refactor-offline", "synthetic": True,
        "outline": {"chapters": len(DEFAULT_OUTLINE),
                    "sections": sum(len(c.sections) for c in DEFAULT_OUTLINE)},
        "cases": cases,
    })
    print(f"FIXTURES={FIXTURES}")
    for name, item in cases.items():
        print(f"  {name}: {item['input_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
