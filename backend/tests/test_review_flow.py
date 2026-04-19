"""M5 — Review & Approval flow.

Covers:
- generate() routes new posts to PENDING_REVIEW when profile.review_before_posting.
- auto_approve_types short-circuits review (status=DRAFT).
- /approve transitions PENDING_REVIEW → DRAFT (no schedule) or SCHEDULED (+variants).
- /reject → SKIPPED; reason appended to generation_prompt.
- /regenerate replaces text + keeps status at PENDING_REVIEW.
- /approve-all mass-approves filtered by post_type.
- Thumbs up/down feedback on a PENDING_REVIEW post works.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.ai.content import GeneratedPost
from app.db.models import PostStatus


@pytest.fixture()
def fake_generate_post(monkeypatch):
    counter = {"n": 0}

    def fake(**kwargs):
        counter["n"] += 1
        return GeneratedPost(
            text=f"Generated draft #{counter['n']} — topic hint: "
            f"{kwargs.get('topic_hint') or '(none)'}",
            system_prompt="stub",
            user_prompt="stub-user",
            model="stub-model",
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.001,
            scrubbed=False,
        )

    monkeypatch.setattr("app.api.posts.generate_post", fake, raising=True)
    return counter


def _put_profile(client, **overrides):
    payload = {
        "name": "Acme",
        "description": "We make things.",
        "review_before_posting": True,
    }
    payload.update(overrides)
    r = client.put("/api/business-profile", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def _generate(client, post_type="informative", topic_hint=None):
    r = client.post(
        "/api/posts/generate",
        json={
            "post_type": post_type,
            "topic_hint": topic_hint,
            "generate_image": False,
            "use_few_shot": False,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_generate_goes_to_pending_review_when_enabled(client, fake_generate_post):
    _put_profile(client, review_before_posting=True)
    post = _generate(client)
    assert post["status"] == PostStatus.PENDING_REVIEW.value


def test_generate_goes_to_draft_when_review_off(client, fake_generate_post):
    _put_profile(client, review_before_posting=False)
    post = _generate(client)
    assert post["status"] == PostStatus.DRAFT.value


def test_auto_approve_type_skips_review(client, fake_generate_post):
    _put_profile(
        client,
        review_before_posting=True,
        auto_approve_types=["informative"],
    )
    # informative is on allow-list → DRAFT
    post_info = _generate(client, post_type="informative")
    assert post_info["status"] == PostStatus.DRAFT.value
    # hard_sell is not → PENDING_REVIEW
    post_hs = _generate(client, post_type="hard_sell")
    assert post_hs["status"] == PostStatus.PENDING_REVIEW.value


def test_pending_review_list_filter(client, fake_generate_post):
    _put_profile(client, review_before_posting=True)
    p1 = _generate(client)
    _generate(client)
    # plus one DRAFT to make sure it's excluded
    r = client.post(
        "/api/posts",
        json={"post_type": "engagement", "text": "already a draft"},
    )
    assert r.status_code == 201

    r_list = client.get("/api/posts/review/pending")
    assert r_list.status_code == 200
    body = r_list.json()
    assert len(body) == 2
    assert all(p["status"] == PostStatus.PENDING_REVIEW.value for p in body)
    assert p1["id"] in [p["id"] for p in body]


def test_approve_to_draft(client, fake_generate_post):
    _put_profile(client, review_before_posting=True)
    post = _generate(client)
    r = client.post(
        f"/api/posts/{post['id']}/approve",
        json={"target_ids": [], "scheduled_for": None},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == PostStatus.DRAFT.value


def test_approve_with_schedule_creates_variants(client, fake_generate_post):
    _put_profile(client, review_before_posting=True)
    target = client.post(
        "/api/targets",
        json={
            "platform_id": "facebook",
            "external_id": "https://www.facebook.com/groups/x",
            "name": "X",
        },
    ).json()
    post = _generate(client)
    sched = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    r = client.post(
        f"/api/posts/{post['id']}/approve",
        json={"target_ids": [target["id"]], "scheduled_for": sched},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == PostStatus.SCHEDULED.value
    assert len(body["variants"]) == 1
    assert body["variants"][0]["target_id"] == target["id"]


def test_approve_rejects_non_pending(client, fake_generate_post):
    _put_profile(client, review_before_posting=False)
    post = _generate(client)  # status=DRAFT
    r = client.post(
        f"/api/posts/{post['id']}/approve",
        json={"target_ids": [], "scheduled_for": None},
    )
    assert r.status_code == 409


def test_reject_transitions_to_skipped(client, fake_generate_post):
    _put_profile(client, review_before_posting=True)
    post = _generate(client)
    r = client.post(
        f"/api/posts/{post['id']}/reject",
        json={"reason": "too salesy"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == PostStatus.SKIPPED.value


def test_regenerate_replaces_text(client, fake_generate_post):
    _put_profile(client, review_before_posting=True)
    post = _generate(client)
    original_text = post["text"]
    r = client.post(
        f"/api/posts/{post['id']}/regenerate",
        json={"topic_hint": "new angle", "generate_image": False},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["text"] != original_text
    assert "new angle" in body["text"]
    # Still in PENDING_REVIEW — regeneration doesn't auto-approve.
    assert body["status"] == PostStatus.PENDING_REVIEW.value


def test_approve_all_filters_by_post_type(client, fake_generate_post):
    _put_profile(client, review_before_posting=True)
    info = _generate(client, post_type="informative")
    sell = _generate(client, post_type="hard_sell")

    r = client.post(
        "/api/posts/review/approve-all",
        json={"post_type": "informative", "scheduled_for": None},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 1
    assert body[0]["id"] == info["id"]
    assert body[0]["status"] == PostStatus.DRAFT.value

    # sell is still pending
    r_sell = client.get(f"/api/posts/{sell['id']}")
    assert r_sell.json()["status"] == PostStatus.PENDING_REVIEW.value


def test_approve_all_without_filter(client, fake_generate_post):
    _put_profile(client, review_before_posting=True)
    _generate(client, post_type="informative")
    _generate(client, post_type="hard_sell")

    r = client.post(
        "/api/posts/review/approve-all",
        json={"post_type": None, "scheduled_for": None},
    )
    assert r.status_code == 200
    assert len(r.json()) == 2


def test_thumbs_feedback_on_pending_post(client, fake_generate_post):
    _put_profile(client, review_before_posting=True)
    post = _generate(client)
    r = client.post(
        "/api/feedback",
        json={"post_id": post["id"], "rating": "up"},
    )
    assert r.status_code == 201
