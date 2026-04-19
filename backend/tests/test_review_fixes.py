"""Regression tests for the review-main-build fix set.

- /api/auth/login rate-limits after N failed attempts.
- WebSocket /ws/ext rejects browser-page Origins.
- Gemini image generation surfaces a clean error on empty/missing candidates.
- Agent `_extract_json` wraps JSONDecodeError as MalformedLLMResponse.
- Meta Graph `_raise_if_error` populates `retry_after` on 429 / throttling codes.
- Posts/plans endpoints no longer rely on `assert`.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from app.agents import MalformedLLMResponse


# ---------- Login rate-limit ----------


@pytest.fixture()
def _reset_login_failures():
    from app.api import auth as auth_mod

    auth_mod._login_failures.clear()
    yield
    auth_mod._login_failures.clear()


def test_login_rate_limited_after_five_failures(client, monkeypatch, _reset_login_failures):
    from app.config import settings

    monkeypatch.setattr(settings, "dashboard_pin", "1234", raising=False)
    for _ in range(5):
        r = client.post("/api/auth/login", json={"pin": "wrong"})
        assert r.status_code == 401
    r = client.post("/api/auth/login", json={"pin": "wrong"})
    assert r.status_code == 429
    assert "Retry-After" in r.headers


def test_login_success_does_not_count_towards_limit(
    client, monkeypatch, _reset_login_failures
):
    from app.config import settings

    monkeypatch.setattr(settings, "dashboard_pin", "1234", raising=False)
    for _ in range(10):
        r = client.post("/api/auth/login", json={"pin": "1234"})
        assert r.status_code == 200


# ---------- WebSocket Origin check ----------


def test_ws_rejects_browser_origin(client):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            "/ws/ext", headers={"origin": "http://evil.example"}
        ):
            pass
    assert exc_info.value.code == 1008


def test_ws_accepts_chrome_extension_origin(client):
    with client.websocket_connect(
        "/ws/ext", headers={"origin": "chrome-extension://abcdef"}
    ) as ws:
        ws.close()


def test_ws_accepts_missing_origin_for_cli_tools(client):
    # Non-browser clients (tests, websocat) have no Origin — must pass through
    # so local dev is painless.
    with client.websocket_connect("/ws/ext") as ws:
        ws.close()


# ---------- Gemini image error handling ----------


def test_generate_image_raises_when_no_candidates(monkeypatch):
    from app.ai import image as image_mod
    from app.config import settings

    monkeypatch.setattr(settings, "gemini_api_key", "x", raising=False)
    monkeypatch.setattr(settings, "enable_image_gen", True, raising=False)

    class _FakeClient:
        def __init__(self, *a, **kw):
            self.models = SimpleNamespace(
                generate_content=lambda *a, **kw: SimpleNamespace(candidates=[])
            )

    monkeypatch.setattr(image_mod.genai, "Client", _FakeClient)
    with pytest.raises(RuntimeError, match="no candidates"):
        image_mod.generate_image("post text", "biz", "casual")


def test_generate_image_raises_when_parts_have_no_inline_data(monkeypatch):
    from app.ai import image as image_mod
    from app.config import settings

    monkeypatch.setattr(settings, "gemini_api_key", "x", raising=False)
    monkeypatch.setattr(settings, "enable_image_gen", True, raising=False)

    fake_response = SimpleNamespace(
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(parts=[SimpleNamespace(inline_data=None)])
            )
        ]
    )

    class _FakeClient:
        def __init__(self, *a, **kw):
            self.models = SimpleNamespace(
                generate_content=lambda *a, **kw: fake_response
            )

    monkeypatch.setattr(image_mod.genai, "Client", _FakeClient)
    with pytest.raises(RuntimeError, match="no image data"):
        image_mod.generate_image("post text", "biz", "casual")


# ---------- Agent _extract_json ----------


def test_planner_extract_json_wraps_malformed():
    from app.agents.planner import _extract_json

    # Contains { and }, so passes the "found JSON object" check, but is not
    # valid JSON — must now raise MalformedLLMResponse rather than bubble up
    # json.JSONDecodeError.
    with pytest.raises(MalformedLLMResponse, match="malformed JSON"):
        _extract_json('{"slots": [unterminated}')


def test_analyst_extract_json_wraps_malformed():
    from app.agents.analyst import _extract_json

    with pytest.raises(MalformedLLMResponse, match="malformed JSON"):
        _extract_json('```json\n{"a": ,}\n```')


def test_targets_extract_json_wraps_malformed():
    from app.agents.targets import _extract_json

    with pytest.raises(MalformedLLMResponse, match="malformed JSON"):
        _extract_json('{"bogus": ,}')


def test_planner_extract_json_wraps_missing_object():
    from app.agents.planner import _extract_json

    with pytest.raises(MalformedLLMResponse, match="No JSON object"):
        _extract_json("no braces here at all")


def test_planner_extract_json_parses_valid_payload():
    from app.agents.planner import _extract_json

    assert _extract_json('```json\n{"slots": []}\n```') == {"slots": []}


# ---------- Meta Graph Retry-After parsing ----------


def _mock_response(status: int, body: dict | str, headers: dict | None = None) -> httpx.Response:
    payload = body if isinstance(body, str) else json.dumps(body)
    return httpx.Response(
        status_code=status,
        content=payload.encode(),
        headers={"content-type": "application/json", **(headers or {})},
    )


def test_meta_error_includes_retry_after_on_429():
    from app.platforms.meta_graph import MetaError, _raise_if_error

    resp = _mock_response(
        429,
        {"error": {"code": 4, "message": "rate limited"}},
        {"retry-after": "17"},
    )
    with pytest.raises(MetaError) as exc_info:
        _raise_if_error(resp)
    assert exc_info.value.retry_after == 17
    assert "17s" in str(exc_info.value)


def test_meta_error_includes_retry_after_on_throttle_code_4():
    from app.platforms.meta_graph import MetaError, _raise_if_error

    resp = _mock_response(
        200,
        {"error": {"code": 4, "message": "rate limited"}},
        {"retry-after": "30"},
    )
    with pytest.raises(MetaError) as exc_info:
        _raise_if_error(resp)
    assert exc_info.value.retry_after == 30


def test_meta_error_no_retry_after_on_generic_400():
    from app.platforms.meta_graph import MetaError, _raise_if_error

    resp = _mock_response(400, {"error": {"code": 100, "message": "bad field"}})
    with pytest.raises(MetaError) as exc_info:
        _raise_if_error(resp)
    assert exc_info.value.retry_after is None


def test_meta_error_handles_missing_retry_after_header():
    from app.platforms.meta_graph import MetaError, _raise_if_error

    resp = _mock_response(429, {"error": {"code": 4, "message": "nope"}})
    with pytest.raises(MetaError) as exc_info:
        _raise_if_error(resp)
    assert exc_info.value.retry_after is None


# ---------- Asserts removed from posts/plans endpoints ----------


def test_create_post_returns_object_after_commit(client):
    # Success path: the create endpoint used to rely on `assert ... is not None`
    # after commit. Ensure the happy path still returns 201 with the row.
    r = client.post(
        "/api/posts",
        json={"post_type": "informative", "text": "hello world"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["text"] == "hello world"
    assert body["post_type"] == "informative"


# ---------- Malformed LLM surfaces as 502 via exception handler ----------


def test_malformed_llm_response_maps_to_502(client, monkeypatch):
    """If an agent raises MalformedLLMResponse inside an endpoint, the
    app-level handler should return HTTP 502, not 500.
    """
    from app.api import plans as plans_api
    from app.db import session as db_session
    from app.db.models import BusinessProfile, Tone

    # Seed a profile so `/api/plans/generate` passes `_require_profile`.
    s = db_session.SessionLocal()
    try:
        s.add(
            BusinessProfile(
                name="x",
                description="desc",
                tone=Tone.CASUAL,
                posts_per_day=1,
                post_type_ratios={},
                auto_approve_types=[],
                posting_window_start_hour=9,
                posting_window_end_hour=20,
            )
        )
        s.commit()
    finally:
        s.close()

    def _boom(**kwargs):
        raise MalformedLLMResponse("forced")

    # The endpoint imported `propose_plan` by name — patch the attribute on
    # `app.api.plans` where the lookup happens.
    monkeypatch.setattr(plans_api, "propose_plan", _boom)

    r = client.post(
        "/api/plans/generate",
        json={
            "name": "p",
            "goal": None,
            "start_date": "2026-04-20T00:00:00Z",
            "end_date": "2026-04-25T00:00:00Z",
        },
    )
    assert r.status_code == 502
    assert "malformed" in r.json()["detail"].lower()
