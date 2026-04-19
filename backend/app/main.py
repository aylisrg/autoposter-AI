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

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import api_router
from app.config import settings
from app.db import init_db
from app.scheduler import scheduler
from app.ws.extension_bridge import bridge

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
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

# Serve generated images and user uploads
images_dir = Path("data/images")
images_dir.mkdir(parents=True, exist_ok=True)
uploads_dir = images_dir / "uploads"
uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory="data"), name="static")

app.include_router(api_router)


@app.websocket("/ws/ext")
async def extension_ws(socket: WebSocket) -> None:
    """The Chrome extension connects here and we send it commands."""
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
