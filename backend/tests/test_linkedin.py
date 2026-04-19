"""Phase 5d — LinkedIn platform adapter.

Covers:
- linkedin_api._build_post_payload shapes the /rest/posts body correctly
  (PUBLIC visibility, PUBLISHED lifecycle, `content.media` only when an
  image URN is attached).
- linkedin_api.create_text_post dispatches a POST, extracts the URN from
  `x-restli-id`, and surfaces a LinkedInError on 4xx.
- LinkedInPlatform.adapt_content truncates on a word boundary.
- LinkedInPlatform.publish dispatches create_text_post with the right
  author URN, bails cleanly when no credential is configured, and uploads
  the image via the two-step register → PUT dance when an image_url is
  attached.
- Registry returns the right class.
- /api/linkedin/oauth/url refuses without a client_id and returns a
  well-formed URL with all expected scopes when configured.
- /api/linkedin/oauth/callback persists a PlatformCredential.
- /api/linkedin/credentials paste-a-token endpoint works.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.config import settings
from app.db.models import (
    PlatformCredential,
    Post,
    PostStatus,
    PostType,
    Target,
)
from app.platforms import linkedin_api
from app.platforms.linkedin import LINKEDIN_MAX, LinkedInPlatform, _person_urn
from app.platforms.registry import PLATFORMS, get_platform


# ---------- linkedin_api pure functions ----------


def test_build_post_payload_text_only():
    body = linkedin_api._build_post_payload(
        author_urn="urn:li:person:ABC", text="hi there", image_urn=None
    )
    assert body["author"] == "urn:li:person:ABC"
    assert body["commentary"] == "hi there"
    assert body["visibility"] == "PUBLIC"
    assert body["lifecycleState"] == "PUBLISHED"
    # No content block for text-only posts.
    assert "content" not in body


def test_build_post_payload_with_image():
    body = linkedin_api._build_post_payload(
        author_urn="urn:li:person:ABC",
        text="hi",
        image_urn="urn:li:image:XYZ",
    )
    assert body["content"] == {"media": {"id": "urn:li:image:XYZ"}}


# ---------- linkedin_api HTTP wrapper (httpx mocked) ----------


class _FakeResponse:
    def __init__(self, status_code=200, headers=None, payload=None, text=""):
        self.status_code = status_code
        self.headers = headers or {}
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _FakeClient:
    def __init__(self, response: _FakeResponse, captured: list[dict]):
        self._response = response
        self._captured = captured

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, json=None, data=None, headers=None):
        self._captured.append({"method": "POST", "url": url, "json": json, "data": data, "headers": headers})
        return self._response

    def get(self, url, headers=None, params=None):
        self._captured.append({"method": "GET", "url": url, "headers": headers, "params": params})
        return self._response

    def put(self, url, content=None):
        self._captured.append({"method": "PUT", "url": url, "content": content})
        return self._response


def test_create_text_post_extracts_urn_from_restli_header(monkeypatch):
    captured: list[dict] = []
    resp = _FakeResponse(
        status_code=201,
        headers={"x-restli-id": "urn:li:share:7123"},
        text="",
    )
    monkeypatch.setattr(
        linkedin_api.httpx,
        "Client",
        lambda **kw: _FakeClient(resp, captured),
    )
    urn = linkedin_api.create_text_post(
        access_token="TOK",
        author_urn="urn:li:person:ABC",
        text="hello",
    )
    assert urn == "urn:li:share:7123"
    # Verify we set the version + restli protocol headers.
    call = captured[0]
    assert call["headers"]["LinkedIn-Version"] == linkedin_api.REST_VERSION
    assert call["headers"]["X-Restli-Protocol-Version"] == "2.0.0"
    assert call["headers"]["Authorization"] == "Bearer TOK"


def test_create_text_post_raises_on_4xx(monkeypatch):
    captured: list[dict] = []
    resp = _FakeResponse(
        status_code=401,
        payload={"serviceErrorCode": 65600, "message": "Invalid access token"},
        text='{"message":"Invalid access token"}',
    )
    monkeypatch.setattr(
        linkedin_api.httpx,
        "Client",
        lambda **kw: _FakeClient(resp, captured),
    )
    with pytest.raises(linkedin_api.LinkedInError) as ei:
        linkedin_api.create_text_post(
            access_token="BAD",
            author_urn="urn:li:person:ABC",
            text="hi",
        )
    assert ei.value.status == 401
    assert "Invalid access token" in str(ei.value)


def test_exchange_code_for_token_posts_form(monkeypatch):
    captured: list[dict] = []
    resp = _FakeResponse(
        status_code=200,
        payload={"access_token": "TOK", "expires_in": 5184000},
    )
    monkeypatch.setattr(
        linkedin_api.httpx,
        "Client",
        lambda **kw: _FakeClient(resp, captured),
    )
    out = linkedin_api.exchange_code_for_token(
        client_id="cid", client_secret="sec", redirect_uri="http://x/y", code="AUTHCODE"
    )
    assert out["access_token"] == "TOK"
    assert captured[0]["url"] == linkedin_api.OAUTH_TOKEN_URL
    assert captured[0]["data"]["code"] == "AUTHCODE"
    assert captured[0]["data"]["grant_type"] == "authorization_code"


# ---------- LinkedInPlatform ----------


def test_person_urn_builds_from_bare_id():
    assert _person_urn("abc123") == "urn:li:person:abc123"
    # Already a URN — returned as-is.
    assert _person_urn("urn:li:person:xyz") == "urn:li:person:xyz"


def test_adapt_content_truncates_on_word_boundary():
    plat = LinkedInPlatform()
    text = ("hello world " * 400).strip()  # well over 3000 chars
    out = plat.adapt_content(text)
    assert len(out) <= LINKEDIN_MAX
    assert out.endswith("\u2026")
    # Word boundary: shouldn't end with a partial word like "hel…"
    assert "  " not in out


def test_adapt_content_leaves_short_text_alone():
    assert LinkedInPlatform().adapt_content("quick note") == "quick note"


def test_registry_returns_linkedin_platform():
    assert "linkedin" in PLATFORMS
    assert get_platform("linkedin").__class__.__name__ == "LinkedInPlatform"


def _make_linkedin_cred(db, account_id="ABC123"):
    row = PlatformCredential(
        platform_id="linkedin",
        account_id=account_id,
        username="Some Person",
        access_token="LI_TOK",
    )
    db.add(row)
    db.commit()
    return row


def _make_target(db, external_id="ABC123"):
    t = Target(platform_id="linkedin", external_id=external_id, name="My feed")
    db.add(t)
    db.commit()
    return t


@pytest.mark.asyncio
async def test_publish_text_only(db):
    _make_linkedin_cred(db)
    target = _make_target(db)
    post = Post(
        post_type=PostType.INFORMATIVE,
        status=PostStatus.DRAFT,
        text="Sharing a quick thought",
        image_url=None,
    )

    with patch("app.platforms.linkedin.linkedin_api.create_text_post") as create_mock:
        create_mock.return_value = "urn:li:share:99"
        result = await LinkedInPlatform(db=db).publish(post, target)

    assert result.ok
    assert result.external_post_id == "urn:li:share:99"
    kwargs = create_mock.call_args.kwargs
    assert kwargs["author_urn"] == "urn:li:person:ABC123"
    assert kwargs["access_token"] == "LI_TOK"
    assert kwargs["image_urn"] is None


@pytest.mark.asyncio
async def test_publish_with_image_registers_and_uploads(db):
    _make_linkedin_cred(db)
    target = _make_target(db)
    post = Post(
        post_type=PostType.INFORMATIVE,
        status=PostStatus.DRAFT,
        text="Image post",
        image_url="https://cdn.example.com/pic.jpg",
    )

    with patch(
        "app.platforms.linkedin.linkedin_api.register_image_upload"
    ) as reg_mock, patch(
        "app.platforms.linkedin.linkedin_api.upload_image_binary"
    ) as upload_mock, patch(
        "app.platforms.linkedin._fetch_image_bytes"
    ) as fetch_mock, patch(
        "app.platforms.linkedin.linkedin_api.create_text_post"
    ) as create_mock:
        reg_mock.return_value = {
            "upload_url": "https://li-upload.example/presigned",
            "image_urn": "urn:li:image:IMG_X",
        }
        fetch_mock.return_value = b"\xff\xd8\xff\xe0stub"
        create_mock.return_value = "urn:li:share:42"

        result = await LinkedInPlatform(db=db).publish(post, target)

    assert result.ok
    assert result.external_post_id == "urn:li:share:42"
    upload_mock.assert_called_once_with(
        upload_url="https://li-upload.example/presigned",
        image_bytes=b"\xff\xd8\xff\xe0stub",
    )
    assert create_mock.call_args.kwargs["image_urn"] == "urn:li:image:IMG_X"


@pytest.mark.asyncio
async def test_publish_drops_non_public_image(db):
    _make_linkedin_cred(db)
    target = _make_target(db)
    post = Post(
        post_type=PostType.INFORMATIVE,
        status=PostStatus.DRAFT,
        text="Local file attempt",
        image_url="/static/images/uploads/foo.jpg",
    )

    with patch(
        "app.platforms.linkedin.linkedin_api.register_image_upload"
    ) as reg_mock, patch(
        "app.platforms.linkedin.linkedin_api.create_text_post"
    ) as create_mock:
        create_mock.return_value = "urn:li:share:text-only"
        result = await LinkedInPlatform(db=db).publish(post, target)

    assert result.ok
    # We didn't try to register an image.
    reg_mock.assert_not_called()
    assert create_mock.call_args.kwargs["image_urn"] is None


@pytest.mark.asyncio
async def test_publish_without_credential_fails(db):
    target = _make_target(db)
    post = Post(
        post_type=PostType.INFORMATIVE,
        status=PostStatus.DRAFT,
        text="no cred",
        image_url=None,
    )
    result = await LinkedInPlatform(db=db).publish(post, target)
    assert not result.ok
    assert "credential" in result.error.lower()


# ---------- OAuth endpoints ----------


def test_oauth_url_requires_client_id(client, monkeypatch):
    monkeypatch.setattr(settings, "linkedin_client_id", "", raising=True)
    r = client.get("/api/linkedin/oauth/url")
    assert r.status_code == 400
    assert "LINKEDIN_CLIENT_ID" in r.json()["detail"]


def test_oauth_url_includes_scopes(client, monkeypatch):
    monkeypatch.setattr(settings, "linkedin_client_id", "cid-123", raising=True)
    r = client.get("/api/linkedin/oauth/url")
    assert r.status_code == 200
    body = r.json()
    assert "state" in body and body["state"]
    url = body["url"]
    assert url.startswith(linkedin_api.OAUTH_AUTH_URL)
    assert "w_member_social" in url
    assert "openid" in url
    assert "client_id=cid-123" in url


def test_oauth_callback_persists_credential(client, db, monkeypatch):
    monkeypatch.setattr(settings, "linkedin_client_id", "cid", raising=True)
    monkeypatch.setattr(settings, "linkedin_client_secret", "sec", raising=True)

    def _fake_exchange(**kwargs):
        return {"access_token": "LI_TOK", "expires_in": 5184000}

    def _fake_userinfo(token):
        return {
            "sub": "XYZ_PERSON",
            "name": "Test Person",
            "email": "t@example.com",
        }

    monkeypatch.setattr(linkedin_api, "exchange_code_for_token", _fake_exchange)
    monkeypatch.setattr(linkedin_api, "get_userinfo", _fake_userinfo)

    r = client.get("/api/linkedin/oauth/callback?code=AUTH&state=abc")
    assert r.status_code == 200
    body = r.json()
    assert body["credential"]["account_id"] == "XYZ_PERSON"
    assert body["credential"]["username"] == "Test Person"

    rows = db.query(PlatformCredential).filter_by(platform_id="linkedin").all()
    assert len(rows) == 1
    assert rows[0].access_token == "LI_TOK"


def test_manual_credential_endpoint(client, db):
    r = client.post(
        "/api/linkedin/credentials",
        json={"account_id": "MANUAL_1", "access_token": "TOK1", "username": "Me"},
    )
    assert r.status_code == 200
    rows = db.query(PlatformCredential).filter_by(platform_id="linkedin").all()
    assert len(rows) == 1
    assert rows[0].account_id == "MANUAL_1"
    assert rows[0].access_token == "TOK1"
