"""Capture exact iWenCai responses for the A17 NEV template before A1 normalization."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
import secrets

import httpx

import backend.app.core.setup_env  # noqa: F401
from data_fetcher.config import Settings
from data_fetcher.skillhub import SkillHub, _extract_records


COMPANIES = (("byd", "比亚迪"), ("changan", "长安汽车"), ("seres", "赛力斯"),
             ("catl", "宁德时代"), ("eve", "亿纬锂能"))
INDUSTRY = "hithink-industry-query"
MACRO = "hithink-macro-query"
FINANCE = "hithink-finance-query"
BUSINESS = "hithink-business-query"
ANNUAL = "2021年 2022年 2023年 2024年 2025年"
FINANCIAL_METRICS = "营业收入 销售毛利率 经营活动产生的现金流量净额 归母净利润 研发费用"

QUERIES = {
    "market": [
        ("sales", INDUSTRY, f"中国新能源汽车销量 全年 年度序列 {ANNUAL}"),
        ("exports", INDUSTRY, f"中国新能源汽车出口量 全年 年度序列 {ANNUAL}"),
        ("penetration", MACRO, "国内零售渗透率:新能源汽车:当月值 2021年1月至2025年12月"),
    ],
    "pb": [(f"pb-{slug}", FINANCE, f"{name} 2021年1月至2025年12月 市净率")
           for slug, name in COMPANIES[:3]],
    "finance": [
        (f"annual-{slug}", FINANCE, f"{name} 全年 {FINANCIAL_METRICS} 2023年 2024年 2025年")
        for slug, name in COMPANIES
    ] + [("roe-debt", FINANCE, "比亚迪 长安汽车 赛力斯 宁德时代 亿纬锂能 2025年 加权净资产收益率 资产负债率")],
    "segments": [(f"segments-{slug}", BUSINESS, f"{name} 2025年主营业务构成")
                 for slug, name in COMPANIES],
    "finance-retry": [(f"catl-{year}", FINANCE, "宁德时代 " +
                       " ".join(f"{year}年{metric}" for metric in FINANCIAL_METRICS.split()))
                      for year in (2023, 2024, 2025)],
    "filings": [(f"filing-{slug}", "announcement-search", f"{name} 2025年年度报告 全文")
                for slug, name in COMPANIES],
}


def safe_response(value):
    """Keep market observations and source trace fields, without provider tokens."""
    if isinstance(value, dict):
        secret_fields = {"token", "api_key", "access_token", "refresh_token", "authorization"}
        return {key: safe_response(item) for key, item in value.items() if key.casefold() not in secret_fields}
    if isinstance(value, list):
        return [safe_response(item) for item in value]
    return value


async def run(output: Path, groups: list[str]) -> None:
    hub = SkillHub()
    if not Settings.from_env().iwencai_api_keys:
        raise SystemExit("项目未配置同花顺凭证。")
    output.mkdir(parents=True, exist_ok=True)
    limit = asyncio.Semaphore(3)

    async def fetch(label: str, skill: str, query: str) -> dict:
        spec = hub.catalog[skill]
        trace_id = secrets.token_hex(32)
        entry = {"id": label, "query": query, "skill_id": spec.skill_id, "trace_id": trace_id,
                 "retrieved_at": datetime.now(timezone.utc).isoformat()}
        async with limit:
            try:
                raw = await hub.gateway.call(spec, {"query": query, "limit": 100, "size": 10},
                                             call_type="manual", trace_id=trace_id)
                records = _extract_records(raw, spec.response_list_keys)
                entry.update(rows=len(records), has_more=bool(raw.get("has_more")) if isinstance(raw, dict) else False)
                (output / f"{label}.json").write_text(
                    json.dumps({"request": entry, "response": safe_response(raw)}, ensure_ascii=False, indent=2), encoding="utf-8",
                )
            except httpx.HTTPStatusError as exc:
                entry["error"] = f"HTTP {exc.response.status_code}"
            except Exception as exc:
                entry["error"] = type(exc).__name__
        print(label, entry.get("rows"), entry.get("error", ""), flush=True)
        return entry

    try:
        results = await asyncio.gather(*(fetch(*job) for group in groups for job in QUERIES[group]))
    finally:
        await hub.gateway.aclose()
    suffix = "-".join(groups)
    (output / f"probe-summary-{suffix}.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--normalize", action="store_true",
                        help="生成 A1 数据集并在写入前验收五问")
    parser.add_argument("--group", choices=QUERIES, action="append")
    parser.add_argument("--output-dir", type=Path,
                        default=Path("output/nev-a1-probe") / datetime.now().strftime("%Y%m%d-%H%M%S"))
    options = parser.parse_args()
    if options.normalize:
        from data_fetcher.nev_profile import DATASET_PATH, _verify, normalize_captures
        audited_positions = json.loads(DATASET_PATH.with_name("nev_a1_2025_filing_anchors.json").read_bytes())
        dataset = normalize_captures(options.output_dir, audited_positions)
        _, checks = _verify(dataset, dataset.research_as_of)
        for check in checks:
            print(check.requirement_id, check.passed, check.evidence_count, check.missing[:4])
        if not all(check.passed for check in checks):
            raise SystemExit("A1 证据验收未通过。")
        temp = DATASET_PATH.with_suffix(".tmp")
        temp.write_text(dataset.model_dump_json(indent=2), encoding="utf-8")
        temp.replace(DATASET_PATH)
        print("A1 验收通过", len(dataset.all_records()), DATASET_PATH)
    else:
        asyncio.run(run(options.output_dir, options.group or ["market", "pb", "finance", "segments", "finance-retry"]))
