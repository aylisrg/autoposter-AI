"""Tests for Content Planner Agent + /api/plans endpoints.

Stubs:
- `propose_plan` → canned list of 3 SlotProposals.
- `refine_plan` → canned RefinementResult.
- `generate_post` → canned GeneratedPost (same fixture as test_api_smoke).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.agents.planner import (
    PlanProposal,
    RefinementResult,
    SlotProposal,
    _extract_json,
    _parse_slots,
)
from app.ai.content import GeneratedPost
from app.db.models import PlanStatus, PostType, SlotStatus


@pytest.fixture()
def profile(client):
    """Ensure a business profile exists for planner endpoints."""
    r = client.put(
        "/api/business-profile",
        json={
            "name": "Acme",
            "description": "We make things.",
            "posts_per_day": 2,
            "post_type_ratios": {"informative": 0.5, "engagement": 0.5},
        },
    )
    assert r.status_code == 200
    return r.json()


@pytest.fixture()
def fake_propose(monkeypatch):
    """Stub the Claude-calling planner with 3 canned slots."""

    def fake(business_profile, start_date, end_date, goal=None):
        base = start_date.replace(hour=10, minute=0, second=0, microsecond=0)
        return PlanProposal(
            slots=[
                SlotProposal(
                    scheduled_for=base,
                    post_type=PostType.INFORMATIVE,
                    topic_hint="How to spot overwatered basil in 10 seconds",
                    rationale="Value-first opener",
                ),
                SlotProposal(
                    scheduled_for=base + timedelta(days=1, hours=3),
                    post_type=PostType.ENGAGEMENT,
                    topic_hint="Ask what herb they most struggle with",
                    rationale="Drive comments",
                ),
                SlotProposal(
                    scheduled_for=base + timedelta(days=2),
                    post_type=PostType.STORY,
                    topic_hint="Time a customer asked us about rosemary in winter",
                    rationale="Humanize the brand",
                ),
            ],
            summary="Value-first week with one engagement and one story.",
            input_tokens=200,
            output_tokens=400,
            cost_usd=0.007,
        )

    monkeypatch.setattr("app.api.plans.propose_plan", fake, raising=True)


@pytest.fixture()
def fake_refine(monkeypatch):
    def fake(business_profile, start_date, end_date, current_slots, chat_history, user_message):
        # Respond as if we moved everything to evenings; return 2 new slots.
        base = start_date.replace(hour=18, minute=0, second=0, microsecond=0)
        return RefinementResult(
            slots=[
                SlotProposal(
                    scheduled_for=base,
                    post_type=PostType.ENGAGEMENT,
                    topic_hint="Evening question post",
                    rationale="Audience active after work",
                ),
                SlotProposal(
                    scheduled_for=base + timedelta(days=1),
                    post_type=PostType.INFORMATIVE,
                    topic_hint="Quick evening tip",
                    rationale="Pairs with engagement slot",
                ),
            ],
            summary="Shifted to evening slots.",
            input_tokens=50,
            output_tokens=100,
            cost_usd=0.0015,
            reply="Moved everything to evenings as requested.",
            assistant_history_entry={
                "role": "assistant",
                "content": "Moved everything to evenings as requested.",
            },
        )

    monkeypatch.setattr("app.api.plans.refine_plan", fake, raising=True)


@pytest.fixture()
def fake_generate_post(monkeypatch):
    def fake(**kwargs):
        return GeneratedPost(
            text="Basil looks sad? Dump the saucer water.",
            system_prompt="stub",
            user_prompt="stub",
            model="stub-model",
            input_tokens=50,
            output_tokens=30,
            cost_usd=0.0006,
            scrubbed=False,
        )

    monkeypatch.setattr("app.api.plans.generate_post", fake, raising=True)


# ---------- unit tests on the agent helpers ----------


def test_extract_json_handles_fences():
    raw = "```json\n{\"slots\": [], \"summary\": \"\"}\n```"
    assert _extract_json(raw) == {"slots": [], "summary": ""}


def test_extract_json_plain():
    assert _extract_json(' {"slots": [], "summary": "x"} ') == {
        "slots": [],
        "summary": "x",
    }


def test_parse_slots_rejects_bad_post_type():
    with pytest.raises(ValueError, match="invalid post_type"):
        _parse_slots(
            {
                "slots": [
                    {
                        "scheduled_for": "2025-07-12T10:00:00Z",
                        "post_type": "not_a_real_type",
                    }
                ]
            }
        )


def test_parse_slots_utc_normalization():
    out = _parse_slots(
        {
            "slots": [
                {
                    "scheduled_for": "2025-07-12T10:00:00Z",
                    "post_type": "informative",
                    "topic_hint": "hi",
                    "rationale": "r",
                }
            ]
        }
    )
    assert len(out) == 1
    assert out[0].scheduled_for.tzinfo is UTC
    assert out[0].post_type == PostType.INFORMATIVE


# ---------- API tests ----------


def test_generate_plan_requires_profile(client, fake_propose):
    start = datetime.now(UTC).replace(microsecond=0)
    end = start + timedelta(days=7)
    r = client.post(
        "/api/plans/generate",
        json={
            "name": "Week 1",
            "goal": "Steady engagement",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        },
    )
    assert r.status_code == 400


def test_generate_plan_happy_path(client, profile, fake_propose):
    start = datetime.now(UTC).replace(microsecond=0)
    end = start + timedelta(days=7)
    r = client.post(
        "/api/plans/generate",
        json={
            "name": "Week 1",
            "goal": "Steady engagement",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "Week 1"
    assert body["status"] == PlanStatus.DRAFT.value
    assert len(body["slots"]) == 3
    # Slots come back ordered by scheduled_for asc
    sched_dates = [s["scheduled_for"] for s in body["slots"]]
    assert sched_dates == sorted(sched_dates)
    assert body["slots"][0]["post_type"] == PostType.INFORMATIVE.value
    assert body["slots"][0]["status"] == SlotStatus.PLANNED.value
    assert body["generation_cost_usd"] > 0


def test_plan_list_and_get(client, profile, fake_propose):
    start = datetime.now(UTC).replace(microsecond=0)
    end = start + timedelta(days=5)
    r = client.post(
        "/api/plans/generate",
        json={
            "name": "P1",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        },
    )
    plan_id = r.json()["id"]

    all_plans = client.get("/api/plans").json()
    assert len(all_plans) == 1
    assert all_plans[0]["id"] == plan_id

    single = client.get(f"/api/plans/{plan_id}")
    assert single.status_code == 200
    assert len(single.json()["slots"]) == 3


def test_plan_patch(client, profile, fake_propose):
    start = datetime.now(UTC).replace(microsecond=0)
    end = start + timedelta(days=3)
    plan_id = client.post(
        "/api/plans/generate",
        json={"name": "Temp", "start_date": start.isoformat(), "end_date": end.isoformat()},
    ).json()["id"]

    r = client.patch(
        f"/api/plans/{plan_id}",
        json={"name": "Renamed", "status": PlanStatus.ACTIVE.value},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Renamed"
    assert r.json()["status"] == PlanStatus.ACTIVE.value


def test_plan_delete(client, profile, fake_propose):
    start = datetime.now(UTC).replace(microsecond=0)
    end = start + timedelta(days=3)
    plan_id = client.post(
        "/api/plans/generate",
        json={"name": "DelMe", "start_date": start.isoformat(), "end_date": end.isoformat()},
    ).json()["id"]

    r = client.delete(f"/api/plans/{plan_id}")
    assert r.status_code == 204
    assert client.get(f"/api/plans/{plan_id}").status_code == 404


def test_slot_crud(client, profile, fake_propose):
    start = datetime.now(UTC).replace(microsecond=0)
    end = start + timedelta(days=3)
    plan = client.post(
        "/api/plans/generate",
        json={"name": "X", "start_date": start.isoformat(), "end_date": end.isoformat()},
    ).json()

    # Manually add a slot
    new_slot_at = (start + timedelta(days=1, hours=2)).isoformat()
    r = client.post(
        f"/api/plans/{plan['id']}/slots",
        json={
            "scheduled_for": new_slot_at,
            "post_type": PostType.HOT_TAKE.value,
            "topic_hint": "Unpopular opinion about overwatering",
        },
    )
    assert r.status_code == 201, r.text
    new_slot = r.json()
    assert new_slot["post_type"] == PostType.HOT_TAKE.value

    # Patch — drag-n-drop to a new time
    moved_to = (start + timedelta(days=2, hours=5)).isoformat()
    r = client.patch(
        f"/api/plans/slots/{new_slot['id']}",
        json={"scheduled_for": moved_to, "notes": "moved in drag-n-drop"},
    )
    assert r.status_code == 200
    assert r.json()["scheduled_for"].startswith(moved_to[:19])
    assert r.json()["notes"] == "moved in drag-n-drop"

    # Delete
    assert client.delete(f"/api/plans/slots/{new_slot['id']}").status_code == 204


def test_plan_chat_updates_slots(client, profile, fake_propose, fake_refine):
    start = datetime.now(UTC).replace(microsecond=0)
    end = start + timedelta(days=5)
    plan = client.post(
        "/api/plans/generate",
        json={"name": "ChatPlan", "start_date": start.isoformat(), "end_date": end.isoformat()},
    ).json()

    r = client.post(
        f"/api/plans/{plan['id']}/chat",
        json={"message": "Move everything to evenings"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["updated"] is True
    assert "evenings" in body["reply"]
    assert len(body["plan"]["slots"]) == 2  # fake_refine returned 2 slots
    assert len(body["plan"]["chat_history"]) >= 3  # initial assistant + user + assistant


def test_generate_post_from_slot(client, profile, fake_propose, fake_generate_post):
    start = datetime.now(UTC).replace(microsecond=0)
    end = start + timedelta(days=3)
    plan = client.post(
        "/api/plans/generate",
        json={"name": "GenPlan", "start_date": start.isoformat(), "end_date": end.isoformat()},
    ).json()
    slot_id = plan["slots"][0]["id"]

    r = client.post(f"/api/plans/slots/{slot_id}/generate-post")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["slot"]["status"] == SlotStatus.GENERATED.value
    assert body["slot"]["post_id"] == body["post"]["id"]
    assert body["post"]["text"].startswith("Basil")

    # Regenerate is blocked until slot's post is deleted
    r2 = client.post(f"/api/plans/slots/{slot_id}/generate-post")
    assert r2.status_code == 409
