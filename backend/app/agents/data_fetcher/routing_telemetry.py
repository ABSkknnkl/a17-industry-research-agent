'''Structured routing telemetry for Agent 1 (P0-5, 2026-08-31 方案).

最小侵入观测层，是 P1（观测驱动的仲裁与词表外置）的一切前提：

- 只追加 JSONL（artifacts/routing_telemetry/YYYYMMDD.jsonl），不入库、
  不改现有事件表、不参与任何路由决策；
- 任何 IO/序列化失败都静默吞掉——观测层绝不能弄挂 Agent 1 主链路；
- 默认只落文本的 SHA-256 哈希 + 结构特征（实体数/指标数/技能），
  原文开关 ROUTING_TELEMETRY_RAW_TEXT=true 才落原文（本地调试用，
  生产保持关闭）；
- 四类事件对应方案 P0-5 的四个点位：
  1. decomposition  拆解完成（build_intent_plan 出口）
  2. route_decision 语义路由决策（OpenAICompatibleSemanticRouter.route 出口）
  3. skill_call     技能调用收口（executor 收口处）
  4. clarification  澄清门（_build_partial_intent_results / 用户改写回流）

2026-09-01 方案（第一刀/第二刀）新增三类仲裁事件：
  5. llm_veto               LLM 显式否决（周审否决率，健康区间 5%-20%）
  6. advisory_passed        澄清门 advisory 放行
  7. derivative_suspected   派生词否定表降级（L1 不 lock，交 L2）

run_id/revision 通过 bind_run() 绑定（service 层每次 run 调用一次），
保证每条记录可关联到 run。
'''

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_RUN_ID: str | None = None
_REVISION: int = 0

_TRUE_TOKENS = frozenset({"1", "true", "yes", "on"})


def bind_run(run_id: str | None, revision: int = 0) -> None:
    """Bind the current run identity so every record is run-correlated."""

    global _RUN_ID, _REVISION
    _RUN_ID = run_id
    _REVISION = revision


def _raw_text_enabled() -> bool:
    return os.environ.get("ROUTING_TELEMETRY_RAW_TEXT", "").strip().lower() in _TRUE_TOKENS


def _telemetry_dir() -> Path:
    override = os.environ.get("ROUTING_TELEMETRY_DIR", "").strip()
    if override:
        return Path(override)
    # backend/app/agents/data_fetcher/routing_telemetry.py -> 项目根/artifacts
    root = Path(__file__).resolve().parents[4]
    return root / "artifacts" / "routing_telemetry"


def _hash_text(value: str | None) -> str:
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _text_field(value: str | None) -> dict[str, Any]:
    """Default: SHA-256 prefix only; raw text only behind the env switch."""

    if not value:
        return {"sha256": ""}
    field: dict[str, Any] = {"sha256": _hash_text(value)}
    if _raw_text_enabled():
        field["raw"] = value[:500]
    return field


def _append(event: dict[str, Any]) -> None:
    """Best-effort JSONL append; telemetry must never break the pipeline."""

    try:
        directory = _telemetry_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "run_id": _RUN_ID,
            "revision": _REVISION,
            **event,
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")
    except Exception:  # noqa: BLE001 - observation layer must stay silent
        pass


def record_decomposition(plan: Any) -> None:
    """Point 1: decomposition complete (拆解完成).

    plan 哈希、子需求数、各子需求（文本哈希+实体+指标+技能+来源）、
    低置信被拒数（warnings 里 llm_low_confidence_not_executed 计数）。
    """

    try:
        subs = list(getattr(plan, "sub_requirements", []) or [])
        payload = {
            "event": "decomposition",
            "parser_mode": getattr(plan, "parser_mode", None),
            "complexity": getattr(plan, "complexity", None),
            "plan_hash": _hash_text(
                json.dumps(
                    [
                        [sub.requirement_id, sub.normalized_text]
                        for sub in subs
                    ],
                    ensure_ascii=False,
                )
            ),
            "sub_count": len(subs),
            "analysis_note_count": len(getattr(plan, "analysis_notes", []) or []),
            "low_confidence_rejected": sum(
                1
                for warning in getattr(plan, "warnings", []) or []
                if str(warning).startswith("llm_low_confidence_not_executed")
            ),
            "subs": [
                {
                    "requirement_id": sub.requirement_id,
                    "text": _text_field(sub.normalized_text),
                    "intent_type": sub.intent_type,
                    "entity_count": len(sub.entities),
                    "entities": [e.name for e in sub.entities][:20],
                    "metric_count": len(sub.metrics),
                    "metrics": [
                        m.normalized_name or m.original_name for m in sub.metrics
                    ][:20],
                    "candidate_skills": list(sub.candidate_skills)[:8],
                    "source": sub.source,
                }
                for sub in subs
            ][:12],
        }
        _append(payload)
    except Exception:  # noqa: BLE001
        pass


def record_route_decision(
    text: str,
    *,
    skill: str | None,
    confidence: float | None,
    below_threshold: bool = False,
    layer: str = "semantic",
) -> None:
    """Point 2: route decision (路由决策).

    layer=semantic 为 L2 语义路由决策（含低于阈值回退）；
    layer=deterministic 为 metric_registry 确定性命中（P0-4 之后
    主链路大多走此层，miss 分析必须能看到它）。
    """

    _append(
        {
            "event": "route_decision",
            "text": _text_field(text),
            "skill": skill,
            "confidence": confidence,
            "below_threshold": below_threshold,
            "layer": layer,
        }
    )


def record_skill_call(
    *,
    skill: str,
    query: str,
    status: str,
    returned_rows: int,
    cleaned_rows: int,
    quarantined_rows: int = 0,
    task_id: str | None = None,
    fallback_from: str | None = None,
    fallback_depth: int = 0,
) -> None:
    """Point 3: skill call settled (技能空调用观测, executor 收口).

    文档通道降级链（2026-09-04）：``fallback_from``/``fallback_depth`` 记录
    降级留痕，用于计算降级触发率/挽救率/证据采用率。主调用保持
    ``fallback_from=None, fallback_depth=0``。
    """

    _append(
        {
            "event": "skill_call",
            "task_id": task_id,
            "skill": skill,
            "query": _text_field(query),
            "status": status,
            "returned_rows": returned_rows,
            "cleaned_rows": cleaned_rows,
            "quarantined_rows": quarantined_rows,
            "fallback_from": fallback_from,
            "fallback_depth": fallback_depth,
        }
    )


def record_clarification(
    question: str,
    *,
    unresolved_fragments: list[str] | None = None,
    action: str | None = None,
    rewritten_text: str | None = None,
) -> None:
    """Point 4: clarification gate (澄清门) or user follow-up (改写回流)."""

    _append(
        {
            "event": "clarification",
            "question": _text_field(question),
            "unresolved_fragments": [
                _text_field(fragment) for fragment in (unresolved_fragments or [])[:12]
            ],
            "action": action,
            "rewritten_text": _text_field(rewritten_text),
        }
    )


def record_llm_veto(
    text: str,
    *,
    requirement_id: str | None = None,
    reason: str | None = None,
) -> None:
    """Point 5: LLM 显式否决（2026-09-01 方案第一刀·改动点 1）。

    周度审查否决率：健康区间 5%-20%；>30% 说明 LLM 在滥用否决权，
    触发拆解 prompt 审查。
    """

    _append(
        {
            "event": "llm_veto",
            "requirement_id": requirement_id,
            "text": _text_field(text),
            "reason": (reason or "")[:200] or None,
        }
    )


def record_advisory_passed(
    question: str,
    *,
    unresolved_fragments: list[str] | None = None,
) -> None:
    """Point 6: 澄清门 advisory 放行（第一刀·改动点 3）。

    有技能可接但置信度不足/参数欠完整的碎片放行执行；证据标
    low_confidence，不计入核心数据组完整性判定。
    """

    _append(
        {
            "event": "advisory_passed",
            "question": _text_field(question),
            "unresolved_fragments": [
                _text_field(fragment) for fragment in (unresolved_fragments or [])[:12]
            ],
        }
    )


def record_derivative_suspected(
    text: str,
    *,
    metric: str,
    alias: str,
    derivative: str,
) -> None:
    """Point 7: 派生词否定表降级（第二刀）。

    L1 命中 alias 但窗口内检出派生词 → 不 lock，交 L2 语义层判。
    """

    _append(
        {
            "event": "derivative_suspected",
            "text": _text_field(text),
            "metric": metric,
            "alias": alias,
            "derivative": derivative,
        }
    )
