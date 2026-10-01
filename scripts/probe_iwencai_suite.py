#!/usr/bin/env python3
"""
同花顺问财（iWenCai）全市场通用持续摸测与回归评测 CLI (Universal iWenCai Continuous Probing Benchmark CLI)
支持：
  1. 任意行业即时动态摸测: --topic "宠物经济" / --topic "具身智能" / --topic "磷化工"
  2. 全谱系代表性行业自动化回归矩阵: --all-sectors (涵盖高端制造、新能源、TMT、消费、医药、周期、前沿等8大产业谱系)
  3. 运行时遥测踩坑日志一键重放与自愈验证: --replay-telemetry
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Any

import httpx

# 优先从环境读取最新 KEY，支持硬编码兜底
DEFAULT_KEY = "sk-proj-00-84DhWOShDF8azRQI1dR8PwoqYaNMW0FEt1m49YidTDeCUdK6MR_iv-fbjvn_MdcTQ0P3lFTA9weURFd6kKANQKQfX7_FN3xvbyL0e38I3z53LX7843K3pFgHxFSZjH7KiKTrhA"
BASE_URL = "https://openapi.iwencai.com"


def load_api_key() -> str:
    env_file = Path(__file__).resolve().parents[1] / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("IWENCAI_API_KEY="):
                val = line.split("=", 1)[1].strip().strip("'\"")
                if val:
                    return val
    return os.getenv("IWENCAI_API_KEY", DEFAULT_KEY)


class ProbeResult:
    def __init__(
        self,
        test_id: str,
        category: str,
        industry: str,
        query: str,
        endpoint: str,
        status_code: int,
        latency_ms: float,
        row_count: int,
        columns: list[str],
        sample_data: dict[str, Any],
        error_msg: str | None = None,
        relaxed_query: str | None = None,
    ):
        self.test_id = test_id
        self.category = category
        self.industry = industry
        self.query = query
        self.endpoint = endpoint
        self.status_code = status_code
        self.latency_ms = latency_ms
        self.row_count = row_count
        self.columns = columns
        self.sample_data = sample_data
        self.error_msg = error_msg
        self.relaxed_query = relaxed_query

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_id": self.test_id,
            "category": self.category,
            "industry": self.industry,
            "query": self.query,
            "endpoint": self.endpoint,
            "status_code": self.status_code,
            "latency_ms": round(self.latency_ms, 1),
            "row_count": self.row_count,
            "columns": self.columns,
            "sample_data": self.sample_data,
            "error_msg": self.error_msg,
            "relaxed_query": self.relaxed_query,
            "success": self.status_code == 200 and self.row_count > 0,
        }


async def run_query(
    client: httpx.AsyncClient,
    api_key: str,
    test_id: str,
    category: str,
    industry: str,
    query: str,
    endpoint: str = "/v1/query2data",
    limit: int = 5,
    channels: list[str] | None = None,
) -> tuple[ProbeResult, list[dict[str, Any]]]:
    trace_id = "trace-" + hashlib.md5(f"{test_id}-{query}".encode()).hexdigest()[:16]
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Claw-Call-Type": "manual",
        "X-Claw-Skill-Id": "universal-testbench",
        "X-Claw-Skill-Version": "2.0.0",
        "X-Claw-Trace-Id": trace_id,
    }
    if endpoint.endswith("/search"):
        payload = {
            "query": query,
            "channels": channels or ["report"],
            "app_id": "AIME_SKILL",
            "size": limit,
        }
    else:
        payload = {
            "query": query,
            "page": "1",
            "limit": str(limit),
            "is_cache": "1",
            "expand_index": "true",
        }

    t0 = time.time()
    try:
        res = await client.post(f"{BASE_URL}{endpoint}", json=payload, headers=headers)
        latency = (time.time() - t0) * 1000
        if res.status_code != 200:
            return ProbeResult(test_id, category, industry, query, endpoint, res.status_code, latency, 0, [], {}, res.text), []
        data = res.json()

        if endpoint.endswith("/search"):
            items = data.get("data", [])
            cols = list(items[0].keys()) if items else []
            s_data = items[0] if items else {}
            return ProbeResult(test_id, category, industry, query, endpoint, res.status_code, latency, len(items), cols, s_data), items
        else:
            rows = []
            for k in ("items", "list", "records", "datas", "result", "results", "data"):
                if isinstance(data.get(k), list):
                    rows = data.get(k)
                    break
                elif isinstance(data.get("data"), dict) and isinstance(data["data"].get(k), list):
                    rows = data["data"][k]
                    break
            cols = list(rows[0].keys()) if rows else []
            s_data = rows[0] if rows else {}
            return ProbeResult(test_id, category, industry, query, endpoint, res.status_code, latency, len(rows), cols, s_data), rows
    except Exception as e:
        latency = (time.time() - t0) * 1000
        return ProbeResult(test_id, category, industry, query, endpoint, -1, latency, 0, [], {}, str(e)), []


def generate_universal_suite(topic: str) -> list[tuple[str, str, str, str, str, int, list[str] | None]]:
    """
    针对任意行业主题，依据 6 大通用元模式动态组装标准摸测用例包
    """
    clean_topic = topic.strip()
    return [
        # 1. 概念与赛道单概念选股元模式
        ("SEL-01", "概念选股元模式", clean_topic, f"{clean_topic} A股 最新总市值 动态市盈率 按总市值降序", "/v1/query2data", 10, None),
        # 2. 多概念 OR 选股元模式 (防范空格 AND 陷阱)
        ("SEL-02", "多环节或选股元模式", clean_topic, f"{clean_topic} 或 {clean_topic}核心材料 或 {clean_topic}设备 A股 按总市值降序", "/v1/query2data", 5, None),
        # 3. 语法陷阱对比用例 (空格多概念触发严格AND，预期 0 条)
        ("TRAP-01", "空格陷阱对照用例", clean_topic, f"{clean_topic} 核心材料 零部件 制造 A股 总市值大于30亿元 按总市值降序", "/v1/query2data", 5, None),
        # 4. 深度行业研报检索元模式
        ("REP-01", "权威研报检索元模式", clean_topic, f"{clean_topic} 深度研究 行业分析", "/v1/comprehensive/search", 5, ["report"]),
        # 5. 行业资讯与动态搜索元模式
        ("NEWS-01", "行业资讯检索元模式", clean_topic, f"{clean_topic} 行业动态 市场趋势", "/v1/comprehensive/search", 5, ["news"]),
        # 6. 通用宏观/中观周期指标
        ("MAC-01", "宏观中观周期元模式", clean_topic, "国内生产总值:当季同比 季度 近3年", "/v1/query2data", 10, None),
    ]


ALL_SPECTRUM_SECTORS = [
    ("高端制造", "工业母机"),
    ("绿色低碳", "固态电池"),
    ("TMT科技", "光通信"),
    ("消费民生", "宠物经济"),
    ("生物医药", "创新药"),
    ("资源周期", "磷化工"),
    ("大金融", "财富管理"),
    ("未来前沿", "具身智能"),
]


async def run_topic_probe(
    client: httpx.AsyncClient, api_key: str, topic: str, prefix: str = ""
) -> list[ProbeResult]:
    print(f"\n👉 开始对主题 【{topic}】 执行全行业通用元模式摸测...")
    test_cases = generate_universal_suite(topic)
    results: list[ProbeResult] = []
    top_companies: list[str] = []

    for idx, (tid, cat, ind, q, ep, lim, ch) in enumerate(test_cases, 1):
        full_tid = f"{prefix}{tid}" if prefix else tid
        print(f"  [{idx:02d}/{len(test_cases):02d}] [{cat}]: \"{q[:42]}...\" ...", end="", flush=True)
        res, rows = await run_query(client, api_key, full_tid, cat, ind, q, endpoint=ep, limit=lim, channels=ch)
        results.append(res)
        status_sym = "✅" if res.status_code == 200 and res.row_count > 0 else ("⚠️ 0条" if res.status_code == 200 else "❌ 报错")
        print(f" -> {status_sym} (Rows={res.row_count}, 耗时={res.latency_ms:.0f}ms)")

        # 从选股结果中动态提取前 3~5 家核心标的名称
        if tid == "SEL-01" and rows:
            for r in rows[:5]:
                for k in ("股票简称", "证券简称", "名称", "公司简称"):
                    if r.get(k):
                        top_companies.append(str(r[k]))
                        break
        await asyncio.sleep(0.2)

    # 若成功识别到标的，继续动态组装标的行情合并查询与主营产品拆解
    if top_companies:
        print(f"  🔍 动态识别到【{topic}】前沿标的: {', '.join(top_companies)}")
        # 7. 多标的批量行情与估值元模式
        batch_q = f"{' '.join(top_companies)} 最新价 总市值 a股流通市值 动态市盈率 市净率 最新涨跌幅 所属同花顺行业 主营业务"
        b_tid = f"{prefix}VAL-BATCH" if prefix else "VAL-BATCH"
        print(f"  [07/08] [批量行情估值元模式]: \"{batch_q[:42]}...\" ...", end="", flush=True)
        b_res, _ = await run_query(client, api_key, b_tid, "核心标的行情", topic, batch_q, limit=10)
        results.append(b_res)
        b_sym = "✅" if b_res.status_code == 200 and b_res.row_count > 0 else "❌ 报错"
        print(f" -> {b_sym} (Rows={b_res.row_count}, 耗时={b_res.latency_ms:.0f}ms)")

        # 8. 标的主营产品拆解元模式
        top1 = top_companies[0]
        prod_q = f"{top1} 主营构成 分产品收入占比"
        p_tid = f"{prefix}BIZ-01" if prefix else "BIZ-01"
        print(f"  [08/08] [主营构成拆解元模式]: \"{prod_q}\" ...", end="", flush=True)
        p_res, _ = await run_query(client, api_key, p_tid, "主营业务拆解", topic, prod_q, limit=5)
        results.append(p_res)
        p_sym = "✅" if p_res.status_code == 200 and p_res.row_count > 0 else "❌ 报错"
        print(f" -> {p_sym} (Rows={p_res.row_count}, 耗时={p_res.latency_ms:.0f}ms)")
        await asyncio.sleep(0.2)

    return results


async def replay_telemetry_queries(client: httpx.AsyncClient, api_key: str) -> list[ProbeResult]:
    telemetry_file = Path(__file__).resolve().parents[1] / "scratch" / "iwencai_query_telemetry.jsonl"
    if not telemetry_file.exists():
        print(f"ℹ️ 遥测日志文件不存在: {telemetry_file}，目前尚无运行时记录。")
        return []

    lines = telemetry_file.read_text(encoding="utf-8").splitlines()
    print(f"\n🔄 从遥测日志中读取到 {len(lines)} 条历史真实踩坑 query，开始执行自愈重放测试...")
    results: list[ProbeResult] = []
    for idx, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except Exception:
            continue
        q = record.get("query", "")
        ind = record.get("industry", "通用行业")
        tid = f"TEL-{idx:03d}"
        print(f"  [{idx:02d}/{len(lines):02d}] 正在重放: \"{q[:45]}...\" ...", end="", flush=True)
        res, _ = await run_query(client, api_key, tid, "遥测重放", ind, q, limit=5)
        results.append(res)
        status_sym = "✅" if res.status_code == 200 and res.row_count > 0 else ("⚠️ 0条" if res.status_code == 200 else "❌ 报错")
        print(f" -> {status_sym} (Rows={res.row_count})")
        await asyncio.sleep(0.2)
    return results


async def main():
    parser = argparse.ArgumentParser(description="同花顺问财全市场通用持续摸测与回归评测 CLI")
    parser.add_argument("--topic", type=str, default="", help="针对指定行业主题执行全套通用元模式摸测 (如 --topic '宠物经济')")
    parser.add_argument("--all-sectors", action="store_true", help="跑全市场 8 大产业全谱系代表性行业自动化回归")
    parser.add_argument("--replay-telemetry", action="store_true", help="从生产遥测账本重放 0 召回查询以验证自愈效果")
    args = parser.parse_args()

    api_key = load_api_key()
    print("=" * 80)
    print("🚀 启动同花顺问财全市场通用持续摸测平台 (Universal iWenCai Probing CLI)")
    print(f"⏰ 当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🔑 API Key 前缀: {api_key[:18]}... (来源: .env/env)")
    print("=" * 80)

    all_results: list[ProbeResult] = []
    async with httpx.AsyncClient(timeout=45) as client:
        if args.replay_telemetry:
            results = await replay_telemetry_queries(client, api_key)
            all_results.extend(results)

        if args.all_sectors:
            print(f"\n🌐 启动全谱系 8 大代表性赛道批量回归矩阵...")
            for s_idx, (sec_name, sec_topic) in enumerate(ALL_SPECTRUM_SECTORS, 1):
                results = await run_topic_probe(client, api_key, sec_topic, prefix=f"S{s_idx:02d}-")
                all_results.extend(results)

        if args.topic:
            results = await run_topic_probe(client, api_key, args.topic)
            all_results.extend(results)

        if not args.topic and not args.all_sectors and not args.replay_telemetry:
            # 默认测试 2 个完全不同性质的赛道：新兴消费（宠物经济）与前沿硬科技（具身智能）
            print("\n💡 未指定参数，默认执行双跨界领域通用元模式摸测：【宠物经济】与【具身智能】")
            res1 = await run_topic_probe(client, api_key, "宠物经济", prefix="PET-")
            res2 = await run_topic_probe(client, api_key, "具身智能", prefix="EMB-")
            all_results.extend(res1 + res2)

    print("\n" + "=" * 80)
    print("🏁 全部通用摸测执行完毕，汇总统计：")
    total = len(all_results)
    success = sum(1 for r in all_results if r.status_code == 200 and r.row_count > 0)
    zero_rows = sum(1 for r in all_results if r.status_code == 200 and r.row_count == 0)
    errors = sum(1 for r in all_results if r.status_code != 200)
    avg_latency = sum(r.latency_ms for r in all_results) / total if total else 0
    print(f"  - 总用例数: {total}")
    print(f"  - 成功命中: {success} ({success/total*100:.1f}%)" if total else "  - 总用例数: 0")
    print(f"  - 命中为0: {zero_rows} (主要是预期中的语法陷阱对照用例)")
    print(f"  - 接口异常: {errors}")
    print(f"  - 平均耗时: {avg_latency:.1f} ms")
    print("=" * 80)

    # 导出通用摸测台账
    out_dir = Path(__file__).resolve().parents[1] / "scratch"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "iwencai_probe_report.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump([r.to_dict() for r in all_results], f, ensure_ascii=False, indent=2)
    print(f"\n📁 结构化通用摸测台账已保存至: {json_path}")


if __name__ == "__main__":
    asyncio.run(main())
