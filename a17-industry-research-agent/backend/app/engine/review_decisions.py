"""Build and verify the decision snapshot shown in the workbench."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from backend.app.schemas.workflow import ReviewDecision, ReviewRequest, StageResult


class DecisionValidationError(ValueError):
    """The submitted decision does not match the reviewable result."""


def _digest(value: Any) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_decision_package(
    result: StageResult, run_id: str, revision: int, gate_reason: str = "",
) -> dict[str, Any]:
    data = result.data
    risks: dict[str, dict[str, Any]] = {}

    def add(code: str, title: str, *, severity: str = "medium", blocking: bool = False) -> None:
        previous = risks.get(code)
        risks[code] = {
            "code": code,
            "title": title,
            "severity": severity,
            "blocking": blocking or bool(previous and previous["blocking"]),
        }

    explicit = data.get("risks")
    for raw in explicit if isinstance(explicit, list) else []:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or raw.get("description") or raw.get("message") or "审核风险")
        severity = raw.get("severity")
        add(
            str(raw.get("code") or raw.get("risk_code") or f"risk_{_digest(title)[:12]}"),
            title,
            severity=str(severity) if severity in ("low", "medium", "high") else "medium",
            blocking=raw.get("blocking") is True or raw.get("hard_blocked") is True,
        )

    if gate_reason:
        add("stage_progression_blocked", gate_reason, severity="high", blocking=True)
    else:
        quality = data.get("quality") or {}
        if data.get("agent_status") == "partial" or (
            isinstance(quality, dict) and quality.get("passed") is False
        ):
            add("stage_quality_limited", "阶段产物存在质量或覆盖缺口")
        if result.error:
            add(f"result_{_digest(result.error)[:12]}", result.error)
    warnings = data.get("warnings")
    if isinstance(warnings, list):
        for warning in warnings:
            if isinstance(warning, str) and warning.strip():
                add(f"warning_{_digest(warning)[:12]}", warning, severity="low")

    blocking = sorted(code for code, risk in risks.items() if risk["blocking"])
    acknowledgement = sorted(set(risks) - set(blocking))
    snapshot = {
        "run_id": run_id,
        "stage": result.stage,
        "revision": revision,
        "risks": [risks[code] for code in sorted(risks)],
        "blocking_risk_codes": blocking,
        "acknowledgement_required_codes": acknowledgement,
        "recommended_action": "blocked" if blocking else ("accept_with_risks" if acknowledgement else "approve"),
    }
    chain = data.get("chain_delivery") or {}
    digest = _digest({
        **snapshot,
        "release_mode": data.get("release_mode", "formal"),
        "certification_bundle_sha256": chain.get("certification_bundle_sha256") if isinstance(chain, dict) else None,
    })
    return {**snapshot, "decision_id": f"dec_{digest[:24]}", "risk_snapshot_sha256": digest}


def validate_review_request(package: dict[str, Any], req: ReviewRequest) -> ReviewDecision:
    if (req.decision_id != package["decision_id"]
            or req.risk_snapshot_sha256 != package["risk_snapshot_sha256"]):
        raise DecisionValidationError("审核决策已更新，请刷新后重新确认")
    if package["blocking_risk_codes"]:
        raise DecisionValidationError("存在硬阻塞风险，请先处理阻断项")
    action = package["recommended_action"] if req.action == "accept_recommendation" else req.action
    required = package["acknowledgement_required_codes"]
    accepted = sorted(req.accepted_risk_codes or [])
    if action == "accept_with_risks":
        if accepted != required:
            raise DecisionValidationError("风险代码须与当前版本需要确认的项目一致")
    elif required or accepted:
        raise DecisionValidationError("请逐项确认当前风险后再批准")

    return ReviewDecision(
        stage=req.stage,
        run_id=req.run_id,
        revision=req.expected_revision,
        action=action,
        decision_id=package["decision_id"],
        risk_snapshot_sha256=package["risk_snapshot_sha256"],
        accepted_risk_codes=accepted,
        comment=req.comment,
    )
