"""Per-platform in-process rate limiter.

Meta-family platforms have published rate limits that are easy to trip when
you schedule a burst of variants. We don't want to rely on upstream 429s
alone — they arrive late, cost us a real request, and often come bundled
with harsher temporary blocks. Instead, keep a client-side sliding window per
platform and refuse (signal retry) before dispatching the HTTP call.

The limiter is intentionally simple:
- One deque[float] of timestamps per platform_id.
- `acquire(platform_id) -> int | None` returns the number of seconds to wait
  before retrying. None means "go ahead, timestamp recorded".
- Defaults tuned conservatively for a single-user tool:
    facebook: 2 per 5 min   (browser extension + FB's bot detection)
    instagram: 1 per hour   (IG publishing is strictly rate-limited)
    threads:  1 per hour
- Thread-safe (Lock-guarded); fine to call from both the scheduler and
  synchronous API request handlers.

State lives in-process — restarting the backend forgets history. That's the
right trade-off for a self-hosted tool; durable state would be overkill.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock


# (max_calls, window_seconds)
_DEFAULT_LIMITS: dict[str, tuple[int, int]] = {
    "facebook": (2, 300),
    "instagram": (1, 3600),
    "threads": (1, 3600),
}


class RateLimiter:
    def __init__(self, limits: dict[str, tuple[int, int]] | None = None) -> None:
        self._limits = dict(limits or _DEFAULT_LIMITS)
        self._history: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def configure(self, platform_id: str, max_calls: int, window_sec: int) -> None:
        """Override the default limit for one platform (tests, advanced users)."""
        self._limits[platform_id] = (max_calls, window_sec)

    def acquire(self, platform_id: str, *, now: float | None = None) -> int | None:
        """Record a call attempt.

        Returns `None` if the attempt is within the limit (and therefore
        allowed — timestamp appended). Returns the number of seconds to wait
        before retrying when the window is full. Platforms with no configured
        limit are always allowed.
        """
        limit = self._limits.get(platform_id)
        if limit is None:
            return None
        max_calls, window = limit
        now_t = time.monotonic() if now is None else now
        cutoff = now_t - window
        with self._lock:
            bucket = self._history[platform_id]
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= max_calls:
                # The oldest timestamp will age out first; that's our wait.
                oldest = bucket[0]
                wait = int(oldest + window - now_t) + 1
                return max(wait, 1)
            bucket.append(now_t)
            return None

    def reset(self, platform_id: str | None = None) -> None:
        """Clear history. Tests use this to get a fresh bucket."""
        with self._lock:
            if platform_id is None:
                self._history.clear()
            else:
                self._history.pop(platform_id, None)


# Module-level singleton. Callers import and use directly.
rate_limiter = RateLimiter()
