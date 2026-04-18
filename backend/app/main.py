"""FastAPI entry point.

Run: `uvicorn app.main:app --reload --port 8787`

What's wired up in this skeleton:
- DB init on startup
- /healthz
- /ws/ext — WebSocket endpoint for the Chrome extension
- /static — serves generated images from data/images/

What's NOT yet wired (add as you build each slice):
- REST endpoints for business profile, posts, targets, feedback
- Scheduler startup
- Auth (not needed for localhost-personal; add for cloud)
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.db import init_db
from app.ws.extension_bridge import bridge

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting backend on port %d", settings.backend_port)
    init_db()
    yield
    log.info("Shutting down")


app = FastAPI(title="autoposter-AI backend", version="0.1.0", lifespan=lifespan)

# CORS — dashboard on :3000 needs to hit API on :8787 from browser
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "chrome-extension://*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve generated images
images_dir = Path("data/images")
images_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory="data"), name="static")


@app.get("/healthz")
def healthz() -> dict:
    return {
        "ok": True,
        "extension_connected": bridge.connected,
        "version": "0.1.0",
    }


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
