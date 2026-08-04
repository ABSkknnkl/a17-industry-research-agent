"""Structured security events that never persist raw suspicious content."""

import hashlib
import json
import logging
from datetime import UTC, datetime
from enum import StrEnum
from threading import Lock
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict


class SecurityEventType(StrEnum):
    AUTH_FAILED = "AUTH_FAILED"
    RUN_ACCESS_DENIED = "RUN_ACCESS_DENIED"
    REVIEW_ACCESS_DENIED = "REVIEW_ACCESS_DENIED"
    PROMPT_INJECTION_SUSPECTED = "PROMPT_INJECTION_SUSPECTED"
    INPUT_TOO_LARGE = "INPUT_TOO_LARGE"
    RATE_LIMITED = "RATE_LIMITED"
    OUTPUT_POLICY_BLOCKED = "OUTPUT_POLICY_BLOCKED"


class SecurityEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    occurred_at: datetime
    event_type: SecurityEventType
    owner_id: str | None
    run_id: str | None
    stage: str | None
    risk_level: Literal["low", "medium", "high"]
    reason_code: str
    outcome: str
    trace_id: str
    content_sha256: str | None = None
    content_length: int = 0


class SecurityAuditLog:
    """Process-local event sink; production can replace it with a repository."""

    def __init__(self) -> None:
        self._events: list[SecurityEvent] = []
        self._lock = Lock()
        self._logger = logging.getLogger("app.security")

    @staticmethod
    def _content_metadata(content: Any | None) -> tuple[str | None, int]:
        if content is None:
            return None, 0
        serialized = (
            content
            if isinstance(content, str)
            else json.dumps(content, ensure_ascii=False, sort_keys=True, default=str)
        )
        encoded = serialized.encode("utf-8")
        return hashlib.sha256(encoded).hexdigest(), len(encoded)

    def record(
        self,
        event_type: SecurityEventType,
        *,
        owner_id: str | None = None,
        run_id: str | None = None,
        stage: str | None = None,
        risk_level: Literal["low", "medium", "high"] = "medium",
        reason_code: str,
        outcome: str,
        content: Any | None = None,
    ) -> SecurityEvent:
        digest, length = self._content_metadata(content)
        event = SecurityEvent(
            event_id=str(uuid4()),
            occurred_at=datetime.now(UTC),
            event_type=event_type,
            owner_id=owner_id,
            run_id=run_id,
            stage=stage,
            risk_level=risk_level,
            reason_code=reason_code,
            outcome=outcome,
            trace_id=str(uuid4()),
            content_sha256=digest,
            content_length=length,
        )
        with self._lock:
            self._events.append(event)
        self._logger.warning(event.model_dump_json())
        return event

    def snapshot(self) -> tuple[SecurityEvent, ...]:
        with self._lock:
            return tuple(self._events)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


security_audit_log = SecurityAuditLog()
