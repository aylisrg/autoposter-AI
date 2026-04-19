"""End-to-end-ish smoke test for the M0 REST surface.

Stubs:
- Anthropic Claude -> generate_post returns a canned GeneratedPost.
- Gemini -> generate_image is not called (generate_image=False here).
- Facebook extension bridge -> FacebookPlatform.publish returns a success dict.

Golden path:
    PUT /api/business-profile            -> 200, row saved
    POST /api/targets                    -> 201
    POST /api/posts/generate             -> 201, draft stored
    POST /api/posts/{id}/publish         -> 200, variant status=posted
"""
from __future__ import annotations

from datetime import UTC
from unittest.mock import patch

import pytest

from app.ai.content import GeneratedPost
from app.db.models import PostStatus, PostType
from app.platforms.base import PublishResult


@pytest.fixture()
def fake_generate_post(monkeypatch):
    """Replace Claude call with a canned reply — no API key needed."""

    def fake(**kwargs):
        return GeneratedPost(
            text="Hey, we just shipped a thing. Check it out.",
            system_prompt="stub",
            user_prompt="stub",
            model="stub-model",
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.001,
            scrubbed=False,
        )

    monkeypatch.setattr("app.api.posts.generate_post", fake, raising=True)


@pytest.fixture()
def fake_spintax(monkeypatch):
    monkeypatch.setattr(
        "app.api.posts.generate_spintax_variant",
        lambda text, profile: text + " (variant)",
        raising=True,
    )


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "version" in body


def test_profile_404_when_missing(client):
    r = client.get("/api/business-profile")
    assert r.status_code == 404


def test_profile_upsert(client):
    payload = {
        "name": "Acme",
        "description": "We make things.",
        "tone": "casual",
        "length": "medium",
        "emoji_density": "light",
    }
    r = client.put("/api/business-profile", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == 1
    assert body["name"] == "Acme"

    # Second upsert updates the same row
    payload["name"] = "Acme Inc."
    r2 = client.put("/api/business-profile", json=payload)
    assert r2.status_code == 200
    assert r2.json()["id"] == 1
    assert r2.json()["name"] == "Acme Inc."


def test_target_crud(client):
    payload = {
        "platform_id": "facebook",
        "external_id": "https://www.facebook.com/groups/123",
        "name": "Test Group",
        "tags": ["test"],
    }
    r = client.post("/api/targets", json=payload)
    assert r.status_code == 201, r.text
    tid = r.json()["id"]

    # Duplicate external_id rejected
    r_dup = client.post("/api/targets", json=payload)
    assert r_dup.status_code == 409

    r_list = client.get("/api/targets")
    assert len(r_list.json()) == 1

    r_get = client.get(f"/api/targets/{tid}")
    assert r_get.status_code == 200

    r_patch = client.patch(f"/api/targets/{tid}", json={"active": False})
    assert r_patch.json()["active"] is False

    r_del = client.delete(f"/api/targets/{tid}")
    assert r_del.status_code == 204
    assert client.get(f"/api/targets/{tid}").status_code == 404


def test_generate_requires_profile(client, fake_generate_post):
    r = client.post(
        "/api/posts/generate",
        json={"post_type": "informative", "generate_image": False},
    )
    assert r.status_code == 400


def test_full_publish_flow(client, fake_generate_post, fake_spintax):
    # 1. Profile — turn off review so generate() returns DRAFT directly
    r = client.put(
        "/api/business-profile",
        json={
            "name": "Acme",
            "description": "We make things.",
            "review_before_posting": False,
        },
    )
    assert r.status_code == 200

    # 2. Target
    r = client.post(
        "/api/targets",
        json={
            "platform_id": "facebook",
            "external_id": "https://www.facebook.com/groups/abc",
            "name": "Group A",
        },
    )
    assert r.status_code == 201, r.text
    target_id = r.json()["id"]

    # 3. Generate draft
    r = client.post(
        "/api/posts/generate",
        json={
            "post_type": "informative",
            "generate_image": False,
            "use_few_shot": False,
        },
    )
    assert r.status_code == 201, r.text
    post = r.json()
    assert post["status"] == PostStatus.DRAFT.value
    assert post["text"].startswith("Hey")
    post_id = post["id"]

    # 4. Publish now — patch FacebookPlatform.publish to avoid touching the bridge.
    async def fake_publish(self, post, target, humanizer=None):
        return PublishResult(
            ok=True,
            external_post_id=f"https://www.facebook.com/groups/{target.id}/posts/fake",
        )

    with patch(
        "app.platforms.facebook.FacebookPlatform.publish",
        new=fake_publish,
    ):
        r = client.post(
            f"/api/posts/{post_id}/publish",
            json={"target_ids": [target_id], "generate_spintax": False},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == PostStatus.POSTED.value
    assert len(body["variants"]) == 1
    assert body["variants"][0]["status"] == PostStatus.POSTED.value
    assert body["variants"][0]["external_post_id"]


def test_schedule_flow(client, fake_generate_post):
    # Setup
    client.put(
        "/api/business-profile",
        json={"name": "Acme", "description": "We make things."},
    )
    t = client.post(
        "/api/targets",
        json={
            "platform_id": "facebook",
            "external_id": "https://www.facebook.com/groups/xyz",
            "name": "Group X",
        },
    ).json()

    # Create a draft directly (no AI call)
    draft = client.post(
        "/api/posts",
        json={
            "post_type": PostType.STORY.value,
            "text": "Scheduled ahead.",
        },
    ).json()

    # Schedule it 1h from now
    from datetime import datetime, timedelta

    sched_at = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    r = client.post(
        f"/api/posts/{draft['id']}/schedule",
        json={
            "target_ids": [t["id"]],
            "scheduled_for": sched_at,
            "generate_spintax": False,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == PostStatus.SCHEDULED.value
    assert len(body["variants"]) == 1
    assert body["variants"][0]["status"] == PostStatus.SCHEDULED.value


def test_feedback(client):
    # Need a post to attach feedback to
    p = client.post(
        "/api/posts",
        json={"post_type": "engagement", "text": "What do you think?"},
    ).json()

    r = client.post(
        "/api/feedback",
        json={"post_id": p["id"], "rating": "up", "comment": "nice"},
    )
    assert r.status_code == 201, r.text

    r_list = client.get(f"/api/feedback/by-post/{p['id']}")
    assert r_list.status_code == 200
    assert len(r_list.json()) == 1
    assert r_list.json()[0]["rating"] == "up"


def test_media_upload_rejects_bad_mime(client):
    resp = client.post(
        "/api/media/upload",
        files={"file": ("x.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 400


def test_media_upload_accepts_png(client, tmp_path, monkeypatch):
    # Redirect the uploads dir to tmp to not pollute the repo during tests
    import app.api.media as media_mod

    test_dir = tmp_path / "uploads"
    monkeypatch.setattr(media_mod, "UPLOADS_DIR", test_dir, raising=True)
    test_dir.mkdir(parents=True, exist_ok=True)

    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\rIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01\x5b\xb7\xc0*"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    resp = client.post(
        "/api/media/upload",
        files={"file": ("a.png", png_bytes, "image/png")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mime"] == "image/png"
    assert body["url"].startswith("/static/images/uploads/")


def test_status_endpoint(client):
    r = client.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    # Scheduler is stubbed to no-op start() so it reports not running
    assert "scheduler_running" in body
    assert "extension_connected" in body
