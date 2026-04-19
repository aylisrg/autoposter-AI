"""Domain exception hierarchy.

Keep callers shallow: raise the most specific subclass that fits and let the
scheduler / API layer decide whether to retry, surface 4xx, or 5xx.

Tree:
    AutoposterError
    ├── TransientError       — retry-worthy (network blip, 5xx, overload)
    │   └── RateLimitError   — carries `retry_after_sec` when the upstream
    │                          told us how long to back off
    ├── AuthError            — credential invalid/expired; needs user action
    └── ValidationError      — input rejected; won't succeed on retry

This hierarchy doesn't replace existing errors (like `MalformedLLMResponse`
or `MetaError`); it composes with them — specific adapters mix in the tag
they deserve so a single `except TransientError` catches everything worth
retrying regardless of origin.
"""
from __future__ import annotations


class AutoposterError(Exception):
    """Root of the domain hierarchy."""


class TransientError(AutoposterError):
    """Probably goes away on retry (network, 5xx, temp overload)."""


class RateLimitError(TransientError):
    """Upstream asked us to slow down."""

    def __init__(self, message: str, retry_after_sec: int | None = None) -> None:
        super().__init__(message)
        self.retry_after_sec = retry_after_sec


class AuthError(AutoposterError):
    """Credential invalid/expired — user must re-auth. Don't retry blindly."""


class ValidationError(AutoposterError):
    """Upstream rejected the payload; retrying with the same input won't help."""
