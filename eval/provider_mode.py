"""Provider identity checks used before any paid evaluation call."""

from __future__ import annotations


class ProviderModeError(RuntimeError):
    pass


def validate_provider_identity(*, declared_mode: str, implementation_path: str) -> str:
    """Reject a provider whose implementation contradicts its declared mode."""
    mode = declared_mode.strip().lower()
    implementation = implementation_path.strip().lower()
    is_mock = ".mock" in implementation or "mock" in implementation.rsplit(".", 1)[-1]
    if mode == "live" and is_mock:
        raise ProviderModeError(
            f"provider_mode=live cannot wrap mock implementation: {implementation_path}"
        )
    if mode not in {"live", "replay", "mock"}:
        raise ProviderModeError(f"unknown provider mode: {declared_mode}")
    return mode

