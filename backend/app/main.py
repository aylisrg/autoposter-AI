"""FastAPI entry point.

Run: `uvicorn app.main:app --reload --port 8787`

Startup order:
1. init_db() — create tables if missing.
2. scheduler.start() — kick off APScheduler tick loop.
3. include_router(api_router) — mount /api/* and /healthz.

The Chrome extension connects to /ws/ext for command dispatch.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.agents import MalformedLLMResponse
from app.api import api_router
from app.config import settings
from app.db import init_db
from app.observability import (
    RequestContextMiddleware,
    configure_logging,
    register_gauge_sampler,
    render_prometheus,
)
from app.scheduler import scheduler
from app.security import DashboardAuthMiddleware
from app.services import health as health_samplers
from app.ws.extension_bridge import bridge

# Register live-sampled gauges for /metrics. Must happen at import time so the
# first scrape after startup already has everything wired.
register_gauge_sampler(health_samplers.sample_extension_status)
register_gauge_sampler(health_samplers.sample_backup_age)
register_gauge_sampler(health_samplers.sample_scheduler_depth)

configure_logging(json_output=settings.log_json, level=logging.INFO)
log = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting backend on port %d", settings.backend_port)
    init_db()
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        log.info("Shutting down")


app = FastAPI(title="autoposter-AI backend", version="0.1.0", lifespan=lifespan)

# CORS — dashboard on :3000 needs to hit API on :8787 from browser.
# allow_origin_regex handles chrome-extension:// (origin wildcard not supported
# in allow_origins).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_origin_regex=r"chrome-extension://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Request IDs + access log + counters (runs after CORS since middlewares
# register LIFO).
app.add_middleware(RequestContextMiddleware)
# PIN auth — no-op when DASHBOARD_PIN is empty (dev default).
app.add_middleware(DashboardAuthMiddleware)

# Serve generated images and user uploads
images_dir = Path("data/images")
images_dir.mkdir(parents=True, exist_ok=True)
uploads_dir = images_dir / "uploads"
uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory="data"), name="static")

app.include_router(api_router)


@app.exception_handler(MalformedLLMResponse)
async def _malformed_llm_handler(request: Request, exc: MalformedLLMResponse) -> JSONResponse:
    """LLM returned something we couldn't parse — treat as upstream (502)."""
    log.warning("Malformed LLM response on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=502,
        content={"detail": "Upstream LLM returned malformed output. Try again."},
    )


@app.get("/metrics", include_in_schema=False)
def prometheus_metrics() -> Response:
    """Prometheus scrape endpoint. Plain text exposition format."""
    return Response(
        content=render_prometheus(),
        media_type="text/plain; version=0.0.4",
    )


# Allowed Origin prefixes for /ws/ext. Only the Chrome extension (or a local
# dev tool explicitly connecting without an Origin header, e.g. curl/websocat
# during debugging) should ever reach this endpoint — any browser page would
# send its own Origin header and must not be able to drive the bridge.
_WS_ALLOWED_ORIGIN_PREFIXES = ("chrome-extension://", "moz-extension://")


def _ws_origin_allowed(origin: str) -> bool:
    if not origin:
        # No Origin header — typically non-browser clients (test tools). Allow
        # these so local debugging stays easy; a malicious browser page cannot
        # omit Origin.
        return True
    return origin.startswith(_WS_ALLOWED_ORIGIN_PREFIXES)


@app.websocket("/ws/ext")
async def extension_ws(socket: WebSocket) -> None:
    """The Chrome extension connects here and we send it commands."""
    origin = socket.headers.get("origin", "")
    if not _ws_origin_allowed(origin):
        log.warning("Rejecting /ws/ext connection from origin %r", origin)
        await socket.close(code=1008)  # 1008 = policy violation
        return
    await socket.accept()
    await bridge.attach(socket)
    try:
        while True:
            raw = await socket.receive_text()
            await bridge.handle_message(raw)
    except WebSocketDisconnect:
        await bridge.detach()
    except Exception as e:
        log.exception("WS handler crashed: %s", e)
        await bridge.detach()
