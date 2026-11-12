"""A1 (data fetcher) coverage probe for the five-industry question document.

Read-only with respect to business code. Runs one real A1 per industry with the
four webpage questions as focus_points, then classifies every required data item:
  OK            - fetched and present in the fused dataset
  FILTERED_OUT  - a skill returned records but fusion dropped them (bug candidate)
  CALL_FAILED   - the relevant skill call failed (bug / environment)
  NOT_PLANNED   - the planner never issued a query for this item (routing bug)
  NO_DATA       - a call succeeded but returned zero records (real data gap)
  BUDGET_LIMITED- the run stopped on iteration/call/time budget, so absence is inconclusive
  OUT_OF_SCOPE  - the item is qualitative disclosure, not in a financial data service

Credentials are injected from an external .env by the caller into process env;
this script never writes secrets into the workspace.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
import json
import os
import sys
import zipfile
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agents_core" / "data-fetcher"))
sys.path.insert(0, str(ROOT / "agents_core"))

import backend.app.core.setup_env  # noqa: F401,E402
from data_fetcher.agent import DataFetcherAgent  # noqa: E402
from data_fetcher.config import Settings  # noqa: E402
from data_fetcher.models import ResearchRequest  # noqa: E402

DOCX = Path("/Users/Zhuanz1/Downloads/五行业选题与网页研究问题.docx")
PROBE_DIR = ROOT / "output" / "a1_five_industry_probe"
AS_OF = date(2026, 11, 9)
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

INDUSTRY_HEADS = ("1. 白酒行业", "2. 半导体设备", "3. 光伏产业链", "4. 低空经济", "5. 新能源汽车")

ENTITIES = {
    "白酒行业": ["贵州茅台", "五粮液", "泸州老窖", "山西汾酒"],
    "半导体设备": ["北方华创", "中微公司", "拓荆科技", "盛美上海"],
    "光伏产业链": ["通威股份", "隆基绿能", "晶澳科技", "阳光电源"],
    "低空经济": [],
    "新能源汽车": ["比亚迪", "长安汽车", "赛力斯", "宁德时代", "亿纬锂能"],
}

# label, kind, keywords used both to look for records and to look for issued queries
NEEDS = {
    "白酒行业": [
        ("经营现金流 / 净利润（四家）", "financial", ["经营现金流", "operating_cash_flow", "净利润", "net_profit"]),
        ("营运资金明细：合同负债 / 应收款项 / 存货", "non_struct", ["合同负债", "应收账款", "应收款项", "存货", "营运资金"]),
        ("2023—2025 营业收入 / 归母净利润 / 毛利率 / 经营现金流 + 同比", "financial", ["营业收入", "revenue", "毛利率", "gross_margin", "同比"]),
        ("现金流／归母净利润比率及年报证据", "non_struct", ["现金流", "归母净利润", "合同负债", "年报"]),
        ("渠道与产品结构披露", "non_struct", ["渠道", "产品结构", "主营业务", "产品收入"]),
    ],
    "半导体设备": [
        ("2023—2025 研发投入 / 研发费用", "financial", ["研发", "rd_expense", "rd_investment"]),
        ("研发费用率 / 研发强度", "financial", ["研发费用率", "研发强度", "rd_ratio"]),
        ("收入增速（四家）", "financial", ["收入增速", "营收增速", "revenue_yoy", "营业收入"]),
        ("刻蚀 / 薄膜沉积 / 清洗设备作用与技术壁垒", "non_struct", ["刻蚀", "薄膜沉积", "清洗设备", "技术壁垒", "工艺"]),
        ("关键性能指标 / 客户验证 / 量产进度", "non_struct", ["客户验证", "量产", "性能指标", "验证进度"]),
        ("产品收入结构 / 客户导入证据", "non_struct", ["产品收入", "收入结构", "客户导入", "主营业务"]),
    ],
    "光伏产业链": [
        ("2021—2025 中国光伏新增装机量", "market", ["光伏新增装机", "新增装机", "pv_new_capacity", "装机"]),
        ("2023—2025 四家营业收入 / 毛利率", "financial", ["营业收入", "revenue", "毛利率", "gross_margin"]),
        ("分环节毛利率 / 经营现金流", "financial", ["毛利率", "gross_margin", "经营现金流", "operating_cash_flow"]),
        ("组件出货量 / 装机需求与公司收入区分", "market", ["出货量", "组件", "装机"]),
        ("各环节业务覆盖与不重复计数", "non_struct", ["业务环节", "主营构成", "产业链", "跨环节"]),
    ],
    "低空经济": [
        ("无人机 / eVTOL / 运营服务 / 基础设施业务分类", "non_struct", ["无人机", "eVTOL", "低空", "基础设施"]),
        ("A 股公司低空相关产品 / 收入 / 订单披露", "non_struct", ["年报", "订单", "主营业务", "低空经济"]),
        ("2024—2025 无人机注册数量 / 飞行小时", "market", ["注册数量", "注册数", "飞行小时"]),
        ("eVTOL 研发试验 / 适航认证 / 商业运营阶段", "non_struct", ["适航", "认证", "商业运营", "研发试验"]),
    ],
    "新能源汽车": [
        ("2021—2025 销量与渗透率", "market", ["销量", "渗透率", "nev_sales", "nev_penetration"]),
        ("2021—2025 出口量", "market", ["出口量", "出口", "nev_exports"]),
        ("统计口径：汽车总量 / 乘用车", "non_struct", ["汽车总量", "乘用车", "统计口径", "口径"]),
        ("2023—2025 三家车企营收 / 毛利率 / 经营现金流", "financial", ["营业收入", "revenue", "毛利率", "gross_margin", "经营现金流"]),
        ("整车业务分部（能否单独比较）", "non_struct", ["分部", "整车业务", "分业务", "业务分部"]),
        ("宁德时代 / 亿纬锂能研发强度", "financial", ["研发", "研发强度", "研发费用率", "rd_ratio"]),
        ("整车与动力电池产业链关系", "non_struct", ["产业链", "动力电池", "上下游", "供货"]),
    ],
}


def load_questions() -> dict[str, list[str]]:
    with zipfile.ZipFile(DOCX) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    paragraphs = []
    for para in root.iter(W + "p"):
        text = "".join((node.text or "") for node in para.iter(W + "t")).strip()
        if text:
            paragraphs.append(text)
    result: dict[str, list[str]] = {}
    current = None
    for text in paragraphs:
        if text in INDUSTRY_HEADS:
            current = text.split(". ", 1)[1]
            result[current] = []
            continue
        if current is None or text.startswith("试跑反馈") or text.startswith("拟输入网页") or text.startswith("生成报告"):
            continue
        if len(text) > 2 and text[0].isdigit() and "。" not in text[:3] and len(result[current]) < 4:
            # question lines start with "1. " ... "4. " and are not the intro paragraph
            if text[1] == "." and text[0] in "1234":
                result[current].append(text)
    return result


def record_text(record) -> str:
    if isinstance(record, dict):
        parts = [str(record.get(k) or "") for k in ("metric", "entity_name", "entity", "unit", "raw_fields")]
    else:
        parts = [str(getattr(record, k, "") or "") for k in ("metric", "entity_name", "entity", "unit", "raw_fields")]
    return " ".join(parts)


def source_text(source) -> str:
    if isinstance(source, dict):
        return str(source.get("query") or "")
    return str(getattr(source, "query", "") or "")


BUDGET_STOPS = frozenset({
    "max_iterations", "max_skill_calls", "skill_budget_exhausted", "budget_exhausted",
    "timeout", "deadline", "max_execution", "max_execution_seconds",
})


def classify(item, dataset, sources, events, stop_reason):
    label, kind, keywords = item
    lowered = [k.lower() for k in keywords]
    records = list(dataset.all_records()) if hasattr(dataset, "all_records") else []
    matched_records = [r for r in records
                       if any(k in record_text(r).lower() for k in lowered)]
    related_sources = [s for s in sources
                       if any(k in source_text(s).lower() for k in lowered)]

    def status(source):
        return source.get("status") if isinstance(source, dict) else getattr(source, "status", "")

    def count(source):
        value = source.get("record_count") if isinstance(source, dict) else getattr(source, "record_count", 0)
        return int(value or 0)

    failed = [s for s in related_sources if status(s) in ("failed", "error")]
    empty = [s for s in related_sources if status(s) == "success_empty"]
    with_records = [s for s in related_sources if status(s) == "success" and count(s) > 0]
    rejected = [e for e in events if e.get("event") == "task_rejected"
                and any(k in json.dumps(e.get("details", {}), ensure_ascii=False).lower() for k in lowered)]

    if matched_records:
        return "OK", {"records": len(matched_records), "sources": len(related_sources)}
    if with_records:
        return "FILTERED_OUT", {"skill_returned": len(with_records),
                                "note": "records returned but missing from fused dataset (fusion/filter bug)"}
    if failed:
        return "CALL_FAILED", {"failed_calls": len(failed), "note": "skill invocation failed (bug or environment)"}
    if rejected:
        return "NOT_PLANNED", {"rejected_tasks": len(rejected),
                              "note": "task validator rejected the query (routing/validation bug)"}
    if kind == "non_struct":
        return "OUT_OF_SCOPE", {
            "note": "qualitative / annual-report disclosure, not a structured financial metric",
            "attempted_queries": len(related_sources), "empty_calls": len(empty),
        }
    if stop_reason in BUDGET_STOPS:
        return "BUDGET_LIMITED", {"stop_reason": stop_reason,
                                  "attempted_queries": len(related_sources), "empty_calls": len(empty)}
    if empty:
        return "NO_DATA", {"empty_calls": len(empty), "note": "skill call succeeded with zero records"}
    if not related_sources:
        return "NOT_PLANNED", {"note": "planner issued no query containing these keywords (routing bug)"}
    return "NO_DATA", {"note": "no matching record and no failure evidence"}


async def run_one(industry: str, questions: list[str], *, output_dir: Path,
                  iterations: int, calls: int, seconds: float) -> dict:
    # Settings is a frozen dataclass: constructing it directly silently drops
    # every env-backed credential. Load from env, then override only output_dir.
    settings = replace(Settings.from_env(), output_dir=output_dir)
    agent = DataFetcherAgent(settings=settings)
    request = ResearchRequest(
        industry=industry,
        focus_points=questions,
        must_include_entities=ENTITIES.get(industry, []),
        as_of=AS_OF,
        max_iterations=iterations,
        max_skill_calls=calls,
        max_execution_seconds=seconds,
    )
    events: list[dict] = []

    async def emit(item: dict) -> None:
        events.append(item)

    result = await agent.run(request, emit=emit, save_artifacts=True)
    payload = {
        "industry": industry,
        "questions": questions,
        "run_id": result.run_id,
        "status": result.status,
        "stop_reason": result.stop_reason,
        "coverage": result.coverage.model_dump(mode="json") if result.coverage else None,
        "errors": [e.model_dump(mode="json") for e in result.errors],
        "model_requirements": [r.model_dump(mode="json") for r in result.model_requirements],
        "quality_summary": result.dataset.quality_summary,
        "record_counts": {k: len(v) for k, v in {
            "industry": result.dataset.industry, "companies": result.dataset.companies,
            "financials": result.dataset.financials, "macro": result.dataset.macro,
            "industry_chain": result.dataset.industry_chain, "reports": result.dataset.reports,
            "news": result.dataset.news, "events": result.dataset.events,
        }.items()},
    }
    (output_dir / "runs" / result.run_id).mkdir(parents=True, exist_ok=True)
    target = output_dir / "runs" / result.run_id
    (target / "dataset.json").write_text(result.dataset.model_dump_json(indent=2), encoding="utf-8")
    (target / "probe_result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (target / "probe_events.jsonl").write_text(
        "".join(json.dumps(e, ensure_ascii=False, default=str) + "\n" for e in events), encoding="utf-8")

    sources = [s.model_dump(mode="json") if hasattr(s, "model_dump") else s for s in result.dataset.sources]
    classified = []
    for item in NEEDS[industry]:
        verdict, detail = classify(item, result.dataset, sources, events, result.stop_reason)
        classified.append({"label": item[0], "kind": item[1], "verdict": verdict, "detail": detail})
    payload["classified"] = classified
    (target / "probe_result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", default=None, help="run a single industry")
    parser.add_argument("--iterations", type=int, default=6)
    parser.add_argument("--calls", type=int, default=16)
    parser.add_argument("--seconds", type=float, default=240.0)
    args = parser.parse_args()

    questions = load_questions()
    print("parsed industries =", {k: len(v) for k, v in questions.items()}, flush=True)
    PROBE_DIR.mkdir(parents=True, exist_ok=True)
    selected = [args.only] if args.only else list(questions)
    summary = {}
    for industry in selected:
        if industry not in questions:
            print("unknown industry", industry, flush=True)
            continue
        print("RUN", industry, "questions=", len(questions[industry]), flush=True)
        out = PROBE_DIR / industry
        out.mkdir(parents=True, exist_ok=True)
        try:
            payload = asyncio.run(run_one(industry, questions[industry], output_dir=out,
                                          iterations=args.iterations, calls=args.calls,
                                          seconds=args.seconds))
        except Exception as exc:
            payload = {"industry": industry, "error": f"{type(exc).__name__}: {exc}"}
            print("  FAILED", payload["error"], flush=True)
        summary[industry] = payload
        print("  status=", payload.get("status"), "stop=", payload.get("stop_reason"),
              "records=", payload.get("record_counts"), flush=True)
        for row in payload.get("classified", []):
            print("   ", row["verdict"], row["label"], flush=True)
    (PROBE_DIR / "probe_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
