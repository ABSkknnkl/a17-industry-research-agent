"""Bearer authentication without exposing configured tokens."""

import hashlib
import hmac
from collections.abc import Mapping
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, SecretStr

from app.core.config import settings
from app.security.audit import SecurityEventType, security_audit_log


class SecurityPrincipal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    owner_id: str


class BearerAuthenticator:
    """Match SHA-256 token digests using constant-time comparison."""

    def __init__(self, tokens: Mapping[str, SecretStr]) -> None:
        self._token_digests = {
            owner_id: self._digest(secret.get_secret_value()) for owner_id, secret in tokens.items()
        }

    @staticmethod
    def _digest(token: str) -> bytes:
        return hashlib.sha256(token.encode("utf-8")).digest()

    def authenticate(self, token: str) -> SecurityPrincipal | None:
        candidate = self._digest(token)
        for owner_id, expected in self._token_digests.items():
            if hmac.compare_digest(candidate, expected):
                return SecurityPrincipal(owner_id=owner_id)
        return None


bearer_scheme = HTTPBearer(auto_error=False)


def get_authenticator() -> BearerAuthenticator:
    return BearerAuthenticator(settings.API_BEARER_TOKENS)


def require_principal(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
    authenticator: Annotated[BearerAuthenticator, Depends(get_authenticator)],
) -> SecurityPrincipal:
    principal = (
        authenticator.authenticate(credentials.credentials) if credentials is not None else None
    )
    if principal is None:
        security_audit_log.record(
            SecurityEventType.AUTH_FAILED,
            risk_level="medium",
            reason_code="missing_or_invalid_bearer",
            outcome="request_blocked",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return principal
