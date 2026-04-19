"""M2 Media Library tests.

We stub `tag_image` (Claude Vision) so tests don't hit the API.
Real file I/O is kept — Pillow reads PNG dimensions, disk writes go to tmp_path.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.ai.vision import TagResult, media_relevance_score
from app.db.models import PostType  # noqa: E402

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01\x5b\xb7\xc0*"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture()
def redirect_uploads(tmp_path, monkeypatch):
    import app.api.media as media_mod

    test_dir = tmp_path / "uploads"
    test_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(media_mod, "UPLOADS_DIR", test_dir, raising=True)
    # `data/...` prefix is still used for local_path; make the `data/` root a tmp too.
    # Ensure delete/tag endpoints can find files via Path("data")/local_path:
    monkeypatch.chdir(tmp_path)
    # Re-create the structure so local_path "images/uploads/..." resolves under data/.
    (tmp_path / "data" / "images").mkdir(parents=True, exist_ok=True)
    real_uploads = tmp_path / "data" / "images" / "uploads"
    real_uploads.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(media_mod, "UPLOADS_DIR", real_uploads, raising=True)
    return real_uploads


@pytest.fixture()
def fake_tag(monkeypatch):
    """Avoid touching Anthropic API."""

    def fake(path, mime=None):
        return TagResult(
            caption="A close-up of basil leaves on a wooden table.",
            tags=["basil", "herbs", "kitchen", "food"],
            cost_usd=0.0015,
        )

    monkeypatch.setattr("app.api.media.tag_image", fake, raising=True)


# ---------- unit tests ----------


def test_relevance_score_basic_overlap():
    s = media_relevance_score(
        slot_post_type="informative",
        slot_topic_hint="how to spot overwatered basil quickly",
        asset_tags=["basil", "kitchen"],
        asset_caption="Pot of basil on a windowsill",
    )
    assert s > 0


def test_relevance_score_no_overlap():
    s = media_relevance_score(
        slot_post_type="story",
        slot_topic_hint="customer won a marathon",
        asset_tags=["keyboard", "laptop"],
        asset_caption="A workspace with monitors",
    )
    assert s == 0.0


def test_relevance_score_handles_empty():
    assert (
        media_relevance_score(
            slot_post_type="engagement",
            slot_topic_hint=None,
            asset_tags=[],
            asset_caption=None,
        )
        == 0.0
    )


# ---------- API tests ----------


def test_upload_persists_and_lists(client, redirect_uploads):
    resp = client.post(
        "/api/media/upload",
        files={"file": ("pic.png", PNG_BYTES, "image/png")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] > 0
    assert body["width"] == 1 and body["height"] == 1
    assert body["url"].startswith("/static/images/uploads/")

    listing = client.get("/api/media").json()
    assert len(listing) == 1
    assert listing[0]["id"] == body["id"]
    assert listing[0]["ai_tags"] == []


def test_get_and_patch_tags(client, redirect_uploads):
    aid = client.post(
        "/api/media/upload",
        files={"file": ("a.png", PNG_BYTES, "image/png")},
    ).json()["id"]

    r = client.patch(f"/api/media/{aid}", json={"tags_user": ["seasonal", "launch"]})
    assert r.status_code == 200
    assert r.json()["tags_user"] == ["seasonal", "launch"]


def test_delete_removes_file_and_row(client, redirect_uploads):
    upload = client.post(
        "/api/media/upload",
        files={"file": ("a.png", PNG_BYTES, "image/png")},
    ).json()
    aid = upload["id"]
    listing_before = client.get("/api/media").json()
    file_path = redirect_uploads / upload["filename"]
    assert file_path.exists()

    r = client.delete(f"/api/media/{aid}")
    assert r.status_code == 204
    assert client.get(f"/api/media/{aid}").status_code == 404
    assert len(client.get("/api/media").json()) == len(listing_before) - 1


def test_tag_endpoint_stores_caption_and_tags(client, redirect_uploads, fake_tag):
    aid = client.post(
        "/api/media/upload",
        files={"file": ("basil.png", PNG_BYTES, "image/png")},
    ).json()["id"]

    r = client.post(f"/api/media/{aid}/tag")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "basil" in body["tags"]
    assert body["caption"]

    asset = client.get(f"/api/media/{aid}").json()
    assert "basil" in asset["ai_tags"]
    assert asset["tagged_at"] is not None


def _make_plan_with_slot(client, topic_hint: str, post_type: PostType):
    client.put(
        "/api/business-profile",
        json={"name": "Acme", "description": "We make things."},
    )
    start = datetime.now(UTC).replace(microsecond=0)
    end = start + timedelta(days=3)
    plan = client.post(
        "/api/plans",
        json={
            "name": "Pilot",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        },
    ).json()
    slot = client.post(
        f"/api/plans/{plan['id']}/slots",
        json={
            "scheduled_for": (start + timedelta(hours=3)).isoformat(),
            "post_type": post_type.value,
            "topic_hint": topic_hint,
        },
    ).json()
    return plan, slot


def test_attach_to_slot(client, redirect_uploads, fake_tag):
    aid = client.post(
        "/api/media/upload",
        files={"file": ("a.png", PNG_BYTES, "image/png")},
    ).json()["id"]
    _, slot = _make_plan_with_slot(client, "basil care", PostType.INFORMATIVE)

    r = client.post(f"/api/media/{aid}/attach-to-slot/{slot['id']}")
    assert r.status_code == 200

    # Slot should now reference the asset
    # (slots live under /api/plans/slots/... — patch lets us read via another fetch)
    # Easiest check: suggest endpoint won't dedupe an already-attached asset,
    # but here we verify by re-reading the plan.
    # Fetch plan detail via /api/plans/{id}
    # Use the plan id from slot
    # Instead just check the relational state via media_asset_id property on slot
    # — we can see it via the plan's slots list.
    plan_id = slot["plan_id"]
    plan_after = client.get(f"/api/plans/{plan_id}").json()
    assert plan_after["slots"][0]["media_asset_id"] == aid


def test_suggest_for_slot_ranks_by_tag_overlap(client, redirect_uploads, fake_tag):
    # Two assets, different tag sets
    aid1 = client.post(
        "/api/media/upload",
        files={"file": ("a.png", PNG_BYTES, "image/png")},
    ).json()["id"]
    # Asset 2: upload a second one with no tags — should score 0
    client.post(
        "/api/media/upload",
        files={"file": ("b.png", PNG_BYTES, "image/png")},
    )
    # Tag asset 1 (fake returns basil/herbs/kitchen tags)
    client.post(f"/api/media/{aid1}/tag")

    _, slot = _make_plan_with_slot(client, "basil care tips for kitchen", PostType.INFORMATIVE)

    r = client.get(f"/api/media/suggest-for-slot/{slot['id']}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 1  # only asset 1 has any overlap
    assert body[0]["asset"]["id"] == aid1
    assert body[0]["score"] > 0


def test_suggest_empty_when_no_tags(client, redirect_uploads):
    # Upload but never tag
    client.post(
        "/api/media/upload",
        files={"file": ("a.png", PNG_BYTES, "image/png")},
    )
    _, slot = _make_plan_with_slot(client, "anything", PostType.STORY)
    assert client.get(f"/api/media/suggest-for-slot/{slot['id']}").json() == []


def test_upload_still_rejects_bad_mime(client, redirect_uploads):
    r = client.post(
        "/api/media/upload",
        files={"file": ("x.txt", b"hi", "text/plain")},
    )
    assert r.status_code == 400
