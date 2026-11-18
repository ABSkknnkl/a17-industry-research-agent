"""Restricted LLM-driven dynamic probe for A1 data gaps.

Design contract (from the 2026-11-17 probe review):
- A first-class fetch path for the human review workbench, NOT a background
  fallback and NOT a warm-up. Nothing here runs at import time.
- The LLM only emits a bounded JSON spec (skill/query/page/limit/expected_metric).
  It never generates or executes code. Skill ids are checked against the
  registered SkillHub catalog and a fixed whitelist.
- Normalisation reuses ``DataFusion.fuse``; evidence (record_id + SourceRef)
  is produced by the existing pipeline, so no new probe schema is needed.
- ``ProbeOutcome.as_meta()`` is written into stage data so the frontend can
  distinguish running / success / no_data / failed.

The caller decides *when* to invoke this. Nothing in the automatic A1 loop,
automatic chart replenishment, or module import calls ``run_dynamic_probe``.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Awaitable, Callable

from data_fetcher.config import Settings
from data_fetcher.fusion import DataFusion
from data_fetcher.llm import OpenAICompatibleLLM
from data_fetcher.models import ResearchRecord, SkillTask
from data_fetcher.skillhub import SkillHub

PROBE_SKILLS: tuple[str, ...] = (
    "hithink-industry-query",
    "hithink-macro-query",
    "hithink-finance-query",
    "hithink-business-query",
    "hithink-market-query",
)
DOMAIN_FALLBACK_SKILL = {
    "macro": "hithink-macro-query",
    "industry": "hithink-industry-query",
    "industry_chain": "hithink-industry-query",
    "competitors": "hithink-industry-query",
    "financials": "hithink-finance-query",
}
MAX_ATTEMPTS = 4
MAX_LIMIT = 100

SYSTEM_PROMPT = """你是行业研究系统的数据缺口补采探针，只输出一个 JSON 对象，不编造数据、不生成代码。

可用 skill_id（只能从这里选）：
- hithink-industry-query：行业数据、产业链、竞争格局、行业序列
- hithink-macro-query：宏观指标、月度/年度时间序列、产销、进出口
- hithink-finance-query：个股财务、估值、资产负债与现金流科目
- hithink-business-query：主营业务构成、分产品/分地区收入
- hithink-market-query：行情快照（通常不含历史序列）

任务：根据缺口选择 skill、写 query、设置 page/limit，并给出你期望返回的正式指标名 expected_metric。
系统会执行查询并把原始列结构、指标名、命中数回喂给你；若目标未达到，你必须换正式指标名、换 skill、放宽条件或调整 limit，不得重复上一轮 query。
若 previous_observation.sample_metrics 出现 GDP、最新价等与 expected_metric 无关的指标，说明问财把 query 理解错了，必须改用标准指标名（可用冒号分隔的正式名称，例如「国内零售渗透率:新能源汽车:当月值」）。
宽表列名形如「市净率[20251231]」会由系统自动展开，parser_mode 仅作提示，不写解析代码。

输出 JSON（字段必须齐全）：
{
  "action": "query" | "give_up",
  "skill_id": "...",
  "query": "...",
  "page": 1,
  "limit": 100,
  "expected_metric": "...",
  "parser_mode": "auto|long_table|wide_series|row",
  "reason": "..."
}
"""


@dataclass
class ProbeOutcome:
    status: str  # success | no_data | failed
    records: list[ResearchRecord] = field(default_factory=list)
    attempts: list[dict[str, Any]] = field(default_factory=list)
    message: str = ""

    def as_meta(self) -> dict[str, Any]:
        return {
            "probe_mode": "llm_dynamic",
            "probe_status": self.status,
            "probe_message": self.message,
            "probe_attempts": self.attempts,
            "probe_records": len(self.records),
        }


def _keywords(demand: dict[str, Any]) -> list[str]:
    explicit = demand.get("target_keywords")
    if isinstance(explicit, list):
        return [str(x).strip() for x in explicit if str(x).strip()][:12]
    text = f"{demand.get('query_hint') or ''} {demand.get('reason') or ''}"
    return list(dict.fromkeys(re.findall(r"[\u4e00-\u9fff]{2,6}", text)))[:12]


def _usable(record: ResearchRecord) -> bool:
    return bool(
        record.entity_name and record.metric and record.value is not None
        and record.period_end is not None
    )


def _target_hit(
    records: list[ResearchRecord],
    entities: list[str],
    expected_metric: str,
    keywords: list[str],
) -> tuple[int, int, list[str]]:
    """Return (usable_count, metric_matched_count, observed_metric_names)."""
    candidates = [c for c in [expected_metric, *keywords] if len(c) >= 2]
    usable = 0
    matched = 0
    names: set[str] = set()
    for record in records:
        if not _usable(record):
            continue
        usable += 1
        names.add(str(record.metric))
        if entities and not any(e in str(record.entity_name or "") for e in entities):
            continue
        text = f"{record.metric} {json.dumps(record.raw_fields, ensure_ascii=False, default=str)}"
        if not candidates or any(c in text for c in candidates):
            matched += 1
    return usable, matched, sorted(names)[:8]


def _observation(payload: Any, attempt: dict[str, Any], keywords: list[str]) -> dict[str, Any]:
    columns: list[str] = []
    rows: list[dict[str, Any]] = []
    row_count = None
    if isinstance(payload, dict):
        columns = [str(c.get("key") or "") for c in (payload.get("columns") or [])
                   if isinstance(c, dict)]
        raw = payload.get("datas")
        rows = [r for r in raw[:2] if isinstance(r, dict)] if isinstance(raw, list) else []
        row_count = payload.get("row_count") or payload.get("code_count")
    hint = ""
    if attempt.get("target_hit", 0) == 0:
        hint = (
            "上一轮未命中目标指标，不要重复同一 query。若 sample_metrics 与目标无关，"
            "改用标准/正式指标名或换 skill；返回宽表时提高 limit 并保留期间关键字。"
        )
    return {
        "last_skill_id": attempt.get("skill_id"),
        "last_query": attempt.get("query"),
        "last_parser_mode": attempt.get("parser_mode"),
        "last_row_count": row_count,
        "last_returned_rows": len(rows),
        "columns_head": columns[:25],
        "wide_column_count": sum(1 for c in columns if "[" in c and "]" in c),
        "sample_metrics": attempt.get("sample_metrics", []),
        "last_target_hit": attempt.get("target_hit", 0),
        "expected_keywords": keywords,
        "hard_hint": hint,
    }


async def run_dynamic_probe(
    demand: dict[str, Any],
    as_of: date,
    *,
    max_attempts: int = MAX_ATTEMPTS,
    on_attempt: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    before_call: Callable[[str, dict[str, Any]], Awaitable[bool]] | None = None,
    accept_records: Callable[[list[ResearchRecord]], list[ResearchRecord]] | None = None,
) -> ProbeOutcome:
    """Probe a target with optional persisted request reservations and acceptance rules."""
    from data_fetcher.probe_budget import ProbeBudgetExceeded

    entities = [str(x) for x in (demand.get("entities") or []) if str(x).strip()]
    query_hint = str(demand.get("query_hint") or "").strip()
    keywords = _keywords(demand)
    try:
        min_records = max(1, int(demand.get("min_records") or 1))
    except (TypeError, ValueError):
        min_records = 1
    domain = str(demand.get("domain") or "financials").lower()
    fallback_skill = DOMAIN_FALLBACK_SKILL.get(domain, "hithink-finance-query")

    hub = SkillHub()
    llm = OpenAICompatibleLLM(Settings.from_env())
    if before_call:
        hub.gateway.before_request = before_call
        llm.before_request = before_call
    outcome = ProbeOutcome(status="no_data")
    if not llm.is_available:
        outcome.status = "failed"
        outcome.message = "大模型探针未启用：缺少 LLM_API_KEY / LLM_MODEL 配置"
        return outcome

    seen_queries: set[tuple[str, str]] = set()
    previous_observation: dict[str, Any] | None = None
    try:
        for attempt_no in range(1, max(1, max_attempts) + 1):
            user = {
                "gap": demand.get("reason") or "",
                "query_hint": query_hint,
                "entities": entities,
                "domain": domain,
                "target": {"min_records": min_records, "expected_keywords": keywords},
                "attempt": attempt_no,
                "previous_observation": previous_observation,
            }
            try:
                spec = await llm.generate_json(
                    SYSTEM_PROMPT, json.dumps(user, ensure_ascii=False)
                )
            except ProbeBudgetExceeded:
                raise
            except Exception as exc:
                outcome.attempts.append({"attempt": attempt_no,
                                         "error": f"{type(exc).__name__}: {str(exc)[:160]}"})
                outcome.status = "failed"
                outcome.message = f"大模型探针调用失败：{type(exc).__name__}，本次未取到数据"
                break

            if str(spec.get("action") or "query") == "give_up":
                outcome.attempts.append({"attempt": attempt_no, "action": "give_up",
                                         "reason": str(spec.get("reason") or "")[:160]})
                break

            skill_id = str(spec.get("skill_id") or fallback_skill).strip()
            if skill_id not in PROBE_SKILLS or skill_id not in hub.catalog:
                skill_id = fallback_skill
            query = str(spec.get("query") or "").strip() or query_hint
            if not query:
                outcome.status = "failed"
                outcome.message = "探针未产出有效 query，本次未取到数据"
                break
            try:
                page = max(1, int(spec.get("page") or 1))
                limit = min(MAX_LIMIT, max(1, int(spec.get("limit") or MAX_LIMIT)))
            except (TypeError, ValueError):
                page, limit = 1, MAX_LIMIT
            expected_metric = str(spec.get("expected_metric") or "").strip()
            parser_mode = str(spec.get("parser_mode") or "auto")

            signature = (skill_id, query)
            if signature in seen_queries:
                rejected = {"attempt": attempt_no, "skill_id": skill_id, "query": query,
                            "error": "duplicate_query_rejected", "target_hit": 0,
                            "sample_metrics": []}
                outcome.attempts.append(rejected)
                previous_observation = _observation(None, rejected, keywords)
                previous_observation["hard_hint"] = "上一轮 query 重复，必须换正式指标名或换 skill。"
                if on_attempt:
                    await on_attempt(rejected)
                continue
            seen_queries.add(signature)

            task = SkillTask(
                task_id=f"probe-{attempt_no}-{abs(hash(signature)) % 100000}",
                skill_name=skill_id,
                arguments={"query": query, "page": page, "limit": limit},
                purpose=f"LLM 动态探针补采: {demand.get('reason') or query_hint}"[:120],
                requirement_ids=[],
            )
            try:
                result = await hub.execute_task(task)
                payload = getattr(result, "raw_payload", None)
                records = DataFusion().fuse([result], as_of).all_records()
            except ProbeBudgetExceeded:
                raise
            except Exception as exc:
                audit = {"attempt": attempt_no, "skill_id": skill_id, "query": query,
                         "page": page, "limit": limit, "parser_mode": parser_mode,
                         "error": f"{type(exc).__name__}: {str(exc)[:160]}",
                         "target_hit": 0, "raw_rows": 0, "sample_metrics": []}
                outcome.attempts.append(audit)
                previous_observation = _observation(None, audit, keywords)
                if on_attempt:
                    await on_attempt(audit)
                continue

            usable, hit, sample_metrics = _target_hit(
                records, entities, expected_metric, keywords
            )
            accepted = accept_records(records) if accept_records else None
            if accepted is not None:
                hit = len(accepted)
            audit = {
                "attempt": attempt_no,
                "round": attempt_no,
                "skill_id": skill_id,
                "query": query,
                "page": page,
                "limit": limit,
                "parser_mode": parser_mode,
                "expected_metric": expected_metric,
                "raw_rows": len(getattr(result, "records", None) or []),
                "usable_records": usable,
                "target_hit": hit,
                "sample_metrics": sample_metrics,
                "success": bool(getattr(result, "success", False)),
                "trace_id": getattr(result, "trace_id", None),
                "attempt_trace_ids": getattr(result, "attempt_trace_ids", []),
            }
            outcome.attempts.append(audit)
            if on_attempt:
                await on_attempt(audit)

            if hit >= min_records:
                # 融合层会额外产出 entity_identity 等身份记录，只回传四要素齐全、
                # 实体匹配且指标命中的记录，避免把非指标行并入 dataset。
                candidates = [c for c in [expected_metric, *keywords] if len(c) >= 2]

                def matched(record: ResearchRecord) -> bool:
                    text = f"{record.metric} {json.dumps(record.raw_fields, ensure_ascii=False, default=str)}"
                    entity_ok = not entities or any(
                        e in str(record.entity_name or "") for e in entities
                    )
                    return entity_ok and (not candidates or any(c in text for c in candidates))

                outcome.status = "success"
                outcome.records = accepted if accepted is not None else [
                    r for r in records if _usable(r) and matched(r)
                ]
                outcome.message = (
                    f"大模型动态探针取数成功：{len(outcome.records)} 条结构化记录，"
                    f"{len(outcome.attempts)} 次尝试，命中 {skill_id}"
                )
                break
            previous_observation = _observation(payload, audit, keywords)
    except ProbeBudgetExceeded:
        outcome.status = "budget_exhausted"
        outcome.message = "自动补采请求预算已用完，保留未解决缺口。"
    finally:
        try:
            await hub.gateway.aclose()
        except Exception:
            pass
        try:
            await llm.close()
        except Exception:
            pass

    if outcome.status == "no_data":
        total_raw = sum(int(a.get("raw_rows") or 0) for a in outcome.attempts)
        outcome.message = (
            f"大模型动态探针未取到可用数据（{len(outcome.attempts)} 次尝试，"
            f"原始行 {total_raw} 条）：返回指标与缺口不匹配或数据源无覆盖，"
            "未写入数据集；可调整关键词/领域后重试，或切换静态单点补采。"
        )
    return outcome
