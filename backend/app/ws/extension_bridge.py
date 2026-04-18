"""WebSocket bridge between backend and Chrome extension.

The extension opens a single persistent WebSocket to the backend. All commands
(publish, list_groups) are sent as JSON messages with a `request_id`, and the
extension replies with the same `request_id`. We correlate via asyncio.Future.

This module is the TRUSTED side (backend). The extension side lives in
`extension/src/background.ts`.

Message shape (backend -> extension):
    {"type": "publish", "request_id": "...", "target_url": "...", "text": "...", ...}

Response shape (extension -> backend):
    {"request_id": "...", "ok": true, ...} OR {"request_id": "...", "ok": false, "error": "..."}
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

log = logging.getLogger("ws.bridge")


class ExtensionBridge:
    """Singleton holding the current extension WS connection and pending requests."""

    def __init__(self) -> None:
        self._socket: WebSocket | None = None
        self._pending: dict[str, asyncio.Future[dict]] = {}
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._socket is not None

    async def attach(self, socket: WebSocket) -> None:
        """Called when the extension connects."""
        async with self._lock:
            if self._socket is not None:
                # Extension reconnected — drop old future set with error
                for fut in self._pending.values():
                    if not fut.done():
                        fut.set_exception(RuntimeError("Extension reconnected"))
                self._pending.clear()
            self._socket = socket
        log.info("Extension connected")

    async def detach(self) -> None:
        async with self._lock:
            self._socket = None
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(RuntimeError("Extension disconnected"))
            self._pending.clear()
        log.info("Extension disconnected")

    async def handle_message(self, raw: str) -> None:
        """Called by WS handler for each incoming message from the extension."""
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("Extension sent non-JSON: %s", raw[:200])
            return
        rid = msg.get("request_id")
        if rid and rid in self._pending:
            fut = self._pending.pop(rid)
            if not fut.done():
                fut.set_result(msg)
        else:
            # Unsolicited message (e.g., a status ping) — ignore for now
            log.debug("Unsolicited extension message: %s", msg.get("type"))

    async def request(self, payload: dict[str, Any], timeout: float = 60.0) -> dict:
        """Send a command to the extension and await its response."""
        if not self._socket:
            raise RuntimeError("Extension not connected. Is the Chrome extension loaded and open?")
        rid = payload.get("request_id")
        if not rid:
            raise ValueError("payload must include request_id")

        fut: asyncio.Future[dict] = asyncio.get_event_loop().create_future()
        self._pending[rid] = fut
        try:
            await self._socket.send_text(json.dumps(payload))
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._pending.pop(rid, None)


# Module-level singleton
bridge = ExtensionBridge()
