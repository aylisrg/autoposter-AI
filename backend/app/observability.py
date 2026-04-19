"""Observability helpers — request IDs, access log, Prometheus-ish metrics.

No external deps. Structured logs are pipe-separated key=value pairs; easy to
grep and still parseable with a small awk script.

`/metrics` returns a Prometheus exposition-format text body. We count:
- http_requests_total{path,method,status}
- publish_attempts_total{platform,ok}
- metrics_rows_collected_total

Counters live in-process; restarting the backend resets them. Good enough for
a self-hosted tool.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from threading import Lock

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.security import new_request_id

log = logging.getLogger("http")


# ---------- Counters ----------


_lock = Lock()
_counters: dict[str, dict[tuple[tuple[str, str], ...], int]] = defaultdict(dict)


def counter_inc(name: str, labels: dict[str, str] | None = None, by: int = 1) -> None:
    key = tuple(sorted((labels or {}).items()))
    with _lock:
        bucket = _counters[name]
        bucket[key] = bucket.get(key, 0) + by


def _normalize_path(path: str) -> str:
    """Collapse numeric path segments so cardinality stays bounded."""
    parts = []
    for p in path.split("/"):
        if p.isdigit():
            parts.append(":id")
        else:
            parts.append(p)
    return "/".join(parts)


def render_prometheus() -> str:
    """Emit counters in Prometheus exposition format."""
    lines: list[str] = []
    with _lock:
        for name, bucket in _counters.items():
            lines.append(f"# TYPE {name} counter")
            for labels, value in bucket.items():
                if labels:
                    lbl = ",".join(f'{k}="{_escape(v)}"' for k, v in labels)
                    lines.append(f"{name}{{{lbl}}} {value}")
                else:
                    lines.append(f"{name} {value}")
    return "\n".join(lines) + "\n"


def _escape(v: str) -> str:
    return v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


# ---------- Middleware ----------


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attaches a request_id to each request/response; logs access line."""

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or new_request_id()
        start = time.perf_counter()
        request.state.request_id = rid
        try:
            response: Response = await call_next(request)
        except Exception:
            duration = (time.perf_counter() - start) * 1000
            log.exception(
                "rid=%s method=%s path=%s status=500 ms=%.1f",
                rid,
                request.method,
                request.url.path,
                duration,
            )
            counter_inc(
                "http_requests_total",
                {
                    "path": _normalize_path(request.url.path),
                    "method": request.method,
                    "status": "500",
                },
            )
            raise
        duration = (time.perf_counter() - start) * 1000
        response.headers["X-Request-ID"] = rid
        log.info(
            "rid=%s method=%s path=%s status=%d ms=%.1f",
            rid,
            request.method,
            request.url.path,
            response.status_code,
            duration,
        )
        counter_inc(
            "http_requests_total",
            {
                "path": _normalize_path(request.url.path),
                "method": request.method,
                "status": str(response.status_code),
            },
        )
        return response
