"""M7 — Instagram + Threads via Meta Graph API.

Mocks all HTTP calls to `app.platforms.meta_graph` so tests stay hermetic.
Verifies:
- adapt_content truncation + hashtag cap (IG) / length-aware trim (Threads)
- InstagramPlatform.publish dispatches create→publish→returns external_id
- ThreadsPlatform.publish handles text-only + text+image
- Credential CRUD endpoints (list/delete) + manual POST
- OAuth URL endpoint refuses without app_id
- _platform_for registry returns the right subclass
- Metrics round-trip for IG/Threads via `fetch_metrics`
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.db.models import (
    Post,
    PostStatus,
    PostType,
    PlatformCredential,
    Target,
)
from app.platforms.instagram import (
    IG_CAPTION_MAX,
    IG_HASHTAG_MAX,
    InstagramPlatform,
    _trim_hashtags,
)
from app.platforms.registry import PLATFORMS, get_platform
from app.platforms.threads import THREADS_MAX, ThreadsPlatform


# ---------- adapt_content ----------


def test_instagram_adapt_truncates_to_2200_chars():
    ig = InstagramPlatform()
    long_text = "a" * (IG_CAPTION_MAX + 500)
    adapted = ig.adapt_content(long_text)
    assert len(adapted) == IG_CAPTION_MAX
    assert adapted.endswith("\u2026")


def test_instagram_adapt_caps_hashtags_at_30():
    tags = " ".join(f"#tag{i}" for i in range(45))
    text = f"Hello world! {tags}"
    adapted = InstagramPlatform().adapt_content(text)
    assert adapted.count("#") == IG_HASHTAG_MAX


def test_trim_hashtags_preserves_first_n():
    text = "hi #one #two #three #four"
    out = _trim_hashtags(text, max_tags=2)
    # Only first two survive.
    assert "#one" in out
    assert "#two" in out
    assert "#three" not in out
    assert "#four" not in out


def test_threads_adapt_truncates_to_500_chars_on_word_boundary():
    # 600 chars of "foo bar" — ensure we chop near a space.
    text = ("foo bar " * 100).strip()
    out = ThreadsPlatform().adapt_content(text)
    assert len(out) <= THREADS_MAX
    assert out.endswith("\u2026")
    assert "  " not in out  # no double-space garbage


def test_threads_adapt_leaves_hashtags_alone():
    text = "news drop " + " ".join(f"#tag{i}" for i in range(10))
    out = ThreadsPlatform().adapt_content(text)
    assert out.count("#") == 10


# ---------- Registry ----------


def test_registry_has_four_platforms():
    assert set(PLATFORMS.keys()) == {"facebook", "instagram", "threads", "linkedin"}


def test_get_platform_returns_correct_subclass():
    assert get_platform("instagram").__class__.__name__ == "InstagramPlatform"
    assert get_platform("threads").__class__.__name__ == "ThreadsPlatform"
    assert get_platform("facebook").__class__.__name__ == "FacebookPlatform"
    assert get_platform("nope") is None


# ---------- Publishing (mocked) ----------


def _make_cred(db, platform_id: str, account_id: str, token: str = "tkn_XYZ"):
    row = PlatformCredential(
        platform_id=platform_id,
        account_id=account_id,
        username=f"{platform_id}_user",
        access_token=token,
        extra={},
    )
    db.add(row)
    db.commit()
    return row


def _make_target(db, platform_id: str, external_id: str):
    t = Target(platform_id=platform_id, external_id=external_id, name=f"{platform_id} target")
    db.add(t)
    db.commit()
    return t


@pytest.mark.asyncio
async def test_instagram_publish_dispatches_create_and_publish(db):
    _make_cred(db, "instagram", "IG123")
    target = _make_target(db, "instagram", "IG123")
    post = Post(
        post_type=PostType.INFORMATIVE,
        status=PostStatus.DRAFT,
        text="Hello from tests",
        image_url="https://cdn.example.com/img.jpg",
    )

    with patch("app.platforms.instagram.meta_graph.ig_create_container") as create_mock, patch(
        "app.platforms.instagram.meta_graph.ig_publish_container"
    ) as publish_mock:
        create_mock.return_value = "CRE123"
        publish_mock.return_value = "MEDIA999"
        platform = InstagramPlatform(db=db)
        result = await platform.publish(post, target)

    assert result.ok
    assert result.external_post_id == "MEDIA999"
    create_mock.assert_called_once()
    kwargs = create_mock.call_args.kwargs
    assert kwargs["ig_user_id"] == "IG123"
    assert kwargs["access_token"] == "tkn_XYZ"
    assert kwargs["image_url"] == "https://cdn.example.com/img.jpg"


@pytest.mark.asyncio
async def test_instagram_publish_requires_public_image_url(db):
    _make_cred(db, "instagram", "IG123")
    target = _make_target(db, "instagram", "IG123")
    post = Post(
        post_type=PostType.INFORMATIVE,
        status=PostStatus.DRAFT,
        text="No image",
        image_url=None,
    )
    platform = InstagramPlatform(db=db)
    result = await platform.publish(post, target)
    assert not result.ok
    assert "publicly-reachable" in result.error


@pytest.mark.asyncio
async def test_instagram_publish_fails_without_credential(db):
    target = _make_target(db, "instagram", "IG999")
    post = Post(
        post_type=PostType.INFORMATIVE,
        status=PostStatus.DRAFT,
        text="hi",
        image_url="https://cdn.example.com/i.jpg",
    )
    platform = InstagramPlatform(db=db)
    result = await platform.publish(post, target)
    assert not result.ok
    assert "credential" in result.error.lower()


@pytest.mark.asyncio
async def test_threads_publish_text_only(db):
    _make_cred(db, "threads", "TH123")
    target = _make_target(db, "threads", "TH123")
    post = Post(
        post_type=PostType.INFORMATIVE,
        status=PostStatus.DRAFT,
        text="Short thought",
        image_url=None,
    )
    with patch("app.platforms.threads.meta_graph.threads_create_container") as create_mock, patch(
        "app.platforms.threads.meta_graph.threads_publish_container"
    ) as publish_mock:
        create_mock.return_value = "TCRE"
        publish_mock.return_value = "TMEDIA"
        result = await ThreadsPlatform(db=db).publish(post, target)

    assert result.ok
    assert result.external_post_id == "TMEDIA"
    # image_url should be None (text-only)
    assert create_mock.call_args.kwargs["image_url"] is None


@pytest.mark.asyncio
async def test_threads_publish_with_image(db):
    _make_cred(db, "threads", "TH123")
    target = _make_target(db, "threads", "TH123")
    post = Post(
        post_type=PostType.INFORMATIVE,
        status=PostStatus.DRAFT,
        text="Image post",
        image_url="https://cdn.example.com/pic.jpg",
    )
    with patch("app.platforms.threads.meta_graph.threads_create_container") as create_mock, patch(
        "app.platforms.threads.meta_graph.threads_publish_container"
    ) as publish_mock:
        create_mock.return_value = "TCRE"
        publish_mock.return_value = "TMEDIA"
        result = await ThreadsPlatform(db=db).publish(post, target)

    assert result.ok
    assert create_mock.call_args.kwargs["image_url"] == "https://cdn.example.com/pic.jpg"


@pytest.mark.asyncio
async def test_threads_drops_non_public_image(db):
    _make_cred(db, "threads", "TH123")
    target = _make_target(db, "threads", "TH123")
    post = Post(
        post_type=PostType.INFORMATIVE,
        status=PostStatus.DRAFT,
        text="With local path",
        image_url="/static/images/uploads/foo.jpg",
    )
    with patch("app.platforms.threads.meta_graph.threads_create_container") as create_mock, patch(
        "app.platforms.threads.meta_graph.threads_publish_container"
    ) as publish_mock:
        create_mock.return_value = "TCRE"
        publish_mock.return_value = "TMEDIA"
        result = await ThreadsPlatform(db=db).publish(post, target)

    assert result.ok
    # Local path gets silently dropped → image_url kwarg is None.
    assert create_mock.call_args.kwargs["image_url"] is None


# ---------- Metrics ----------


@pytest.mark.asyncio
async def test_instagram_fetch_metrics_maps_keys(db):
    _make_cred(db, "instagram", "IG555")
    with patch("app.platforms.instagram.meta_graph.ig_insights") as mock:
        mock.return_value = {"likes": 10, "comments": 3, "reach": 200}
        out = await InstagramPlatform(db=db).fetch_metrics("MEDIA_X")
    assert out == {"likes": 10, "comments": 3, "reach": 200}


@pytest.mark.asyncio
async def test_threads_fetch_metrics_maps_replies_and_reposts(db):
    _make_cred(db, "threads", "TH555")
    with patch("app.platforms.threads.meta_graph.threads_insights") as mock:
        mock.return_value = {"likes": 4, "comments": 1, "shares": 2, "reach": 500}
        out = await ThreadsPlatform(db=db).fetch_metrics("MEDIA_X")
    assert out["likes"] == 4
    assert out["comments"] == 1
    assert out["shares"] == 2
    assert out["reach"] == 500


# ---------- API: OAuth URL + credentials CRUD ----------


def test_oauth_url_requires_app_id(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "meta_app_id", "", raising=False)
    r = client.get("/api/meta/oauth/url")
    assert r.status_code == 400


def test_oauth_url_with_app_id_returns_login_url(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "meta_app_id", "123456", raising=False)
    r = client.get("/api/meta/oauth/url")
    assert r.status_code == 200
    body = r.json()
    assert "facebook.com" in body["url"]
    assert "client_id=123456" in body["url"]
    assert "state=" in body["url"]
    assert len(body["state"]) > 16


def test_manual_credential_upsert_and_list(client):
    payload = {
        "platform_id": "instagram",
        "account_id": "IG777",
        "username": "testbiz",
        "access_token": "LONG_TOKEN_1",
    }
    r = client.post("/api/meta/credentials", json=payload)
    assert r.status_code == 200
    cred = r.json()
    assert cred["platform_id"] == "instagram"
    assert cred["account_id"] == "IG777"
    # Token is never returned.
    assert "access_token" not in cred

    # Upsert = same (platform, account) just updates, no new row.
    payload["access_token"] = "LONG_TOKEN_2"
    r2 = client.post("/api/meta/credentials", json=payload)
    assert r2.status_code == 200
    assert r2.json()["id"] == cred["id"]

    listing = client.get("/api/platform-credentials").json()
    assert len(listing) == 1


def test_manual_credential_rejects_unknown_platform(client):
    r = client.post(
        "/api/meta/credentials",
        json={
            "platform_id": "vkontakte",
            "account_id": "X",
            "access_token": "t",
        },
    )
    assert r.status_code == 400


def test_delete_credential(client):
    r = client.post(
        "/api/meta/credentials",
        json={
            "platform_id": "threads",
            "account_id": "TH_DEL",
            "access_token": "t",
        },
    )
    cid = r.json()["id"]
    assert client.delete(f"/api/platform-credentials/{cid}").status_code == 204
    assert client.delete(f"/api/platform-credentials/{cid}").status_code == 404


# ---------- list_targets ----------


@pytest.mark.asyncio
async def test_instagram_list_targets_returns_credential_account(db):
    _make_cred(db, "instagram", "IG_LT", token="tok")
    out = await InstagramPlatform(db=db).list_targets()
    assert len(out) == 1
    assert out[0]["external_id"] == "IG_LT"


@pytest.mark.asyncio
async def test_threads_list_targets_empty_without_credential(db):
    out = await ThreadsPlatform(db=db).list_targets()
    assert out == []
