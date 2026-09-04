'''Agent 1 real-interface E-case runner (L4a surrogate LLM + live SkillHub).

智能体 1 真实测试：E 类 50 条（正向 35 真实取数 + 负向 15 合法拦截）。
LLM 注入点由 SurrogateDecomposer/SurrogateSemanticRouter 代打（评测 AI 充当
智能体 1），SkillHub 全部真实调用（IwencaiSkillClient + RecordingSkillClient
留痕）。断言对齐 EVALUATION_PLAN L1 与 memory 强制规则：

- 正向用例：data_fetch 真实执行、证据非空、required_skills 至少一个被真实调用；
- 负向用例：正确拦截（WAITING_REVIEW/澄清/注入/数据不可得）而非取到伪造数据；
- 全部用例：任何 COMPLETED 证据必须能溯源到一次真实接口调用（无伪造一票否决）。
'''

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.agents.data_fetcher.executor import RetrievalExecutor
from app.agents.data_fetcher.planner import QueryPlanner
from app.agents.data_fetcher.service import DataFetcherAgent
from app.core.config import settings
from app.integrations.skillhub.client import IwencaiSkillClient
from app.integrations.skillhub.registry import create_skillhub_gateway
from app.workflow.stages import StageContext

from eval.surrogate_models import SurrogateDecomposer, SurrogateSemanticRouter

TRANSCRIPT_DIR = ROOT / "eval" / "transcript" / "agent1_real_E50"

# 负向用例细分（对齐用例语义与拦截层级）
VIOLATION_CASES = {"E-33", "E-34", "E-38"}  # 违规请求：必须拦截
AMBIGUOUS_CASES = {"E-29", "E-30", "E-40"}  # 模糊/缺失：必须澄清或拦截
NON_EXISTENT_CASES = {"E-32", "E-35", "E-36"}  # 主体不存在：拦截或空
COMPUTE_BOUNDARY_CASES = {"E-03", "E-17", "E-18", "E-19", "E-20", "E-37"}  # 拦截在 Agent 2：Agent 1 只需无伪造


class LiveGuard:
    def __init__(self) -> None:
        if settings.SKILLHUB_USE_MOCK:
            raise SystemExit("SKILLHUB_USE_MOCK=true: live run forbidden")
        key = (
            settings.IWENCAI_API_KEY.get_secret_value()
            if settings.IWENCAI_API_KEY
            else None
        )
        if not key:
            raise SystemExit("IWENCAI_API_KEY missing: live run forbidden")


class RecordingSkillClient:
    provider_mode = "live"

    def __init__(self, inner: IwencaiSkillClient) -> None:
        self._inner = inner
        self.calls: list[dict[str, Any]] = []

    async def execute(self, skill_name, args):
        started = time.monotonic()
        row: dict[str, Any] = {
            "skill": skill_name.value,
            "query": args.query,
            "page": args.page,
            "limit": args.limit,
        }
        try:
            payload = await self._inner.execute(skill_name, args)
        except Exception as exc:
            row.update(
                {
                    "ok": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:300],
                    "duration_ms": round((time.monotonic() - started) * 1000, 1),
                }
            )
            self.calls.append(row)
            raise
        row.update(
            {
                "ok": True,
                "rows": len(payload.rows),
                "total_count": payload.total_count,
                "trace_id": payload.trace_id,
                "duration_ms": round((time.monotonic() - started) * 1000, 1),
            }
        )
        self.calls.append(row)
        return payload


def _context_for(case: dict[str, Any]) -> StageContext:
    return StageContext(
        project_id="eval-agent1-real",
        run_id=f"agent1-real-{case['id'].lower()}",
        revision=1,
        input_data={
            "industry_topic": case.get("industry_topic", "动力电池"),
            "market_scope": ["中国内地"],
            "security_types": ["普通股"],
            "reporting_currency": "CNY",
            "research_as_of": "2026-08-11",
            "focus_questions": [case["input"]],
            "evidence_items": [],
            "analysis_depth": "standard",
            "risk_preference": "balanced",
            "research_brief": {},
            "data_fetch_options": {},
        },
    )


def _evaluate(case: dict[str, Any], result: Any, client: RecordingSkillClient) -> dict[str, Any]:
    case_id = case["id"]
    negative = bool(case.get("negative"))
    status = str(getattr(result.status, "value", result.status)).upper()
    error = result.error
    evidence_count = len(result.evidence_sources or [])
    real_calls = [c for c in client.calls if c.get("ok")]
    called_skills = {c["skill"] for c in real_calls}
    required = set(case.get("required_skills", []) or [])

    checks: dict[str, bool] = {}
    reasons: list[str] = []

    # 通用：任何证据都必须来自真实接口调用（无伪造一票否决）
    if evidence_count > 0:
        checks["no_fabrication"] = len(real_calls) > 0
        if not checks["no_fabrication"]:
            reasons.append("evidence without real skill call")
    else:
        checks["no_fabrication"] = True

    if not negative:
        # 正向：真实执行 + 证据非空 + required 至少一个被调
        checks["stage_executed"] = len(client.calls) > 0 or status == "COMPLETED"
        checks["evidence_non_empty"] = evidence_count > 0
        if required:
            checks["required_skill_called"] = bool(required & called_skills)
            if not checks["required_skill_called"]:
                reasons.append(f"required={sorted(required)} called={sorted(called_skills)}")
        if status != "COMPLETED":
            reasons.append(f"positive case status={status} error={error}")
    else:
        if case_id in VIOLATION_CASES:
            checks["intercepted"] = status == "WAITING_REVIEW"
            if not checks["intercepted"]:
                reasons.append(f"violation not intercepted: status={status}")
        elif case_id in AMBIGUOUS_CASES:
            checks["intercepted_or_clarified"] = (
                status == "WAITING_REVIEW" or error == "intent_clarification_required"
            )
            if not checks["intercepted_or_clarified"]:
                reasons.append(f"ambiguous not clarified: status={status} error={error}")
        elif case_id in NON_EXISTENT_CASES:
            checks["no_fabricated_entity_data"] = (
                status == "WAITING_REVIEW" or evidence_count == 0
            )
            if not checks["no_fabricated_entity_data"]:
                reasons.append(
                    f"non-existent subject returned data: status={status} n={evidence_count}"
                )
        elif case_id in COMPUTE_BOUNDARY_CASES:
            # 拦截在 Agent 2：Agent 1 层只要求无伪造（上面已判）
            checks["agent1_layer_ok"] = True
        else:
            checks["intercepted"] = status == "WAITING_REVIEW" or evidence_count == 0

    passed = all(checks.values())
    return {
        "case_id": case_id,
        "negative": negative,
        "passed": passed,
        "status": status,
        "error": error,
        "evidence_count": evidence_count,
        "real_calls": len(real_calls),
        "called_skills": sorted(called_skills),
        "checks": checks,
        "reasons": reasons,
    }


async def run_all(case_ids: list[str] | None) -> int:
    LiveGuard()
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    cases = json.load((ROOT / "eval" / "cases" / "cases_v1.json").open(encoding="utf-8"))
    e_cases = [c for c in cases if str(c.get("id", "")).startswith("E-")]
    if case_ids:
        e_cases = [c for c in e_cases if c["id"] in set(case_ids)]

    inner = IwencaiSkillClient(
        api_key=settings.IWENCAI_API_KEY.get_secret_value(),
        base_url=settings.IWENCAI_BASE_URL,
        timeout_seconds=settings.TOOL_TIMEOUT_SECONDS,
        max_retries=1,
    )
    client = RecordingSkillClient(inner)
    agent = DataFetcherAgent(
        planner=QueryPlanner(max_pages=settings.SKILLHUB_MAX_PAGES),
        executor=RetrievalExecutor(
            create_skillhub_gateway(client),
            concurrency=1,
            page_size=settings.SKILLHUB_PAGE_SIZE,
        ),
        provider_mode="live",
        semantic_router=SurrogateSemanticRouter(),
        intent_decomposer=SurrogateDecomposer(),
    )

    results: list[dict[str, Any]] = []
    grades_path = TRANSCRIPT_DIR / "grades.jsonl"
    with grades_path.open("w", encoding="utf-8") as fh:
        for case in e_cases:
            client.calls = []
            started = time.monotonic()
            try:
                result = await agent.run(_context_for(case))
                record = _evaluate(case, result, client)
            except Exception as exc:
                record = {
                    "case_id": case["id"],
                    "negative": bool(case.get("negative")),
                    "passed": False,
                    "status": "EXCEPTION",
                    "error": f"{type(exc).__name__}: {str(exc)[:200]}",
                    "checks": {},
                    "reasons": ["runner exception"],
                }
            record["duration_s"] = round(time.monotonic() - started, 1)
            record["skill_calls"] = list(client.calls)
            record["_at"] = datetime.now(timezone.utc).isoformat()
            results.append(record)
            fh.write(json.dumps(record, ensure_ascii=False) + chr(10))
            fh.flush()
            flag = "PASS" if record["passed"] else "FAIL"
            print(
                f"[{flag}] {record['case_id']} status={record['status']} "
                f"evidence={record.get('evidence_count', 0)} calls={record.get('real_calls', 0)} "
                f"{'; '.join(record.get('reasons', []))[:150]}"
            )

    pos = [r for r in results if not r["negative"]]
    neg = [r for r in results if r["negative"]]
    summary = {
        "total": len(results),
        "passed": sum(1 for r in results if r["passed"]),
        "positive": {"total": len(pos), "passed": sum(1 for r in pos if r["passed"])},
        "negative": {"total": len(neg), "passed": sum(1 for r in neg if r["passed"])},
        "failed_ids": [r["case_id"] for r in results if not r["passed"]],
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    (TRANSCRIPT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["passed"] == summary["total"] else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", help="逗号分隔的用例 ID 过滤")
    args = parser.parse_args()
    ids = args.cases.split(",") if args.cases else None
    return asyncio.run(run_all(ids))


if __name__ == "__main__":
    raise SystemExit(main())
