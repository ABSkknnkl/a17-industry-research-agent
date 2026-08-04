"""ASGI request-size guard applied before FastAPI body validation."""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.security.audit import SecurityEventType, security_audit_log


class RequestBodyLimitMiddleware:
    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self._app = app
        self._max_bytes = max_bytes

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        event = security_audit_log.record(
            SecurityEventType.INPUT_TOO_LARGE,
            risk_level="medium",
            reason_code="request_body_limit",
            outcome="request_blocked",
        )
        response = JSONResponse(
            status_code=413,
            content={
                "detail": {
                    "code": "INPUT_TOO_LARGE",
                    "trace_id": event.trace_id,
                }
            },
        )
        await response(scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") not in {"POST", "PUT", "PATCH"}:
            await self._app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        raw_length = headers.get(b"content-length")
        if raw_length is not None:
            try:
                if int(raw_length) > self._max_bytes:
                    await self._reject(scope, receive, send)
                    return
            except ValueError:
                await self._reject(scope, receive, send)
                return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] != "http.request":
                await self._app(scope, _single_message_receive(message), send)
                return
            body.extend(message.get("body", b""))
            if len(body) > self._max_bytes:
                await self._reject(scope, receive, send)
                return
            if not message.get("more_body", False):
                break

        delivered = False

        async def replay_receive() -> Message:
            nonlocal delivered
            if delivered:
                return {"type": "http.disconnect"}
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self._app(scope, replay_receive, send)


def _single_message_receive(message: Message) -> Receive:
    delivered = False

    async def receive() -> Message:
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return message

    return receive
