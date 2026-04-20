"""Platform error hierarchy.

Every adapter — Meta Graph, LinkedIn REST, the browser-extension bridge — used
to raise its own ad-hoc exception type and the scheduler had no good way to
tell "token expired, give up" apart from "429, try again later". This module
is the single vocabulary the scheduler reads.

Taxonomy:
- `PlatformError` — base. Anything raised by a platform adapter inherits this.
- `TransientError` — temporary; re-issuing the same request later should work.
  Network blips, 5xx, throttling without an explicit Retry-After.
- `RateLimitError(TransientError)` — we were explicitly rate-limited.
  `retry_after` (seconds) is the platform's hint; None means "figure it out
  yourself, default backoff is fine."
- `AuthError` — credentials expired or revoked. The user must re-auth; no
  number of retries will help. Final FAILED.
- `ValidationError` — the platform rejected the payload (text too long, image
  format wrong, URL not publicly reachable). Retrying the identical payload is
  pointless — give up and surface the reason.

The hierarchy is consumed by `app.scheduler.jobs._publish_one`: transient →
schedule a retry, terminal → mark FAILED. Platform adapters translate their
wire-level error objects (MetaError, LinkedInError) into one of these before
the exception escapes the adapter layer.
"""
from __future__ import annotations


class PlatformError(Exception):
    """Base for every publish-path error the scheduler cares about.

    Subclasses set `transient` so callers don't have to pattern-match on the
    concrete class to decide retry vs. fail.
    """

    transient: bool = False


class TransientError(PlatformError):
    """Temporary failure. Worth retrying with backoff."""

    transient = True


class RateLimitError(TransientError):
    """We hit a platform rate limit.

    `retry_after` is the server's hint in seconds (e.g. the `Retry-After`
    header) or None if no hint was given. Schedulers should prefer the hint
    over their default backoff when present.
    """

    def __init__(self, message: str, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class AuthError(PlatformError):
    """Credentials are bad/expired — re-auth required before any retry."""


class ValidationError(PlatformError):
    """Platform rejected the payload. Retrying the same input won't help."""
