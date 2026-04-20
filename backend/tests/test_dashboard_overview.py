"""Guided home dashboard — /api/dashboard/overview.

Covers:
- next_step decision tree (priority order, not every permutation)
- setup counters (platforms connected, expiring soon, active targets,
  active plans)
- activity counters + publishing_now / next_scheduled lookups
- recent_failures classification (permanent vs transient based on FB's
  'not_a_group_member' / 'checkpoint_detected' markers)
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.api.dashboard import _classify_error, _compute_next_step
from app.db.models import (
    BusinessProfile,
    ContentPlan,
    PlanStatus,
    PlatformCredential,
    Post,
    PostStatus,
    PostType,
    PostVariant,
    Target,
)


# ---------- _classify_error ----------


def test_classify_error_permanent_for_not_a_member():
    assert _classify_error("not_a_group_member: join it") == "permanent"


def test_classify_error_permanent_for_checkpoint():
    assert _classify_error("checkpoint_detected: ...") == "permanent"


def test_classify_error_transient_for_generic():
    assert _classify_error("network timeout") == "transient"


def test_classify_error_transient_for_none():
    assert _classify_error(None) == "transient"


# ---------- _compute_next_step decision tree ----------


_COMMON = dict(
    extension_connected=True,
    has_profile=True,
    platforms_connected=1,
    targets_active=1,
    expiring_soon=0,
    pending_review=0,
    plans_active=1,
    scheduled_total=5,
    permanent_failures=0,
)


def test_next_step_permanent_failures_wins_over_everything():
    s = _compute_next_step(**{**_COMMON, "permanent_failures": 2})
    assert s.id == "resolve_failures"
    assert "attention" in s.title


def test_next_step_missing_profile_blocks_before_platform_check():
    s = _compute_next_step(**{**_COMMON, "has_profile": False, "platforms_connected": 0})
    # We push profile when platforms also missing — profile is cheaper to fill.
    assert s.id in {"connect_extension", "create_profile"}
    # Specifically: extension_connected is True here so the extension nudge
    # shouldn't fire; we want profile.
    s2 = _compute_next_step(**{**_COMMON, "has_profile": False})
    assert s2.id == "create_profile"


def test_next_step_no_platforms_pushes_platforms_card():
    s = _compute_next_step(**{**_COMMON, "platforms_connected": 0})
    # Extension is connected, so we don't harass for it first.
    assert s.id == "connect_platform"


def test_next_step_no_extension_and_no_platforms_pushes_extension_first():
    s = _compute_next_step(
        **{
            **_COMMON,
            "extension_connected": False,
            "platforms_connected": 0,
            "has_profile": False,
        }
    )
    assert s.id == "connect_extension"


def test_next_step_no_targets():
    s = _compute_next_step(**{**_COMMON, "targets_active": 0})
    assert s.id == "add_targets"


def test_next_step_pending_review_nudges_review():
    s = _compute_next_step(**{**_COMMON, "pending_review": 3})
    assert s.id == "review_drafts"
    assert "3" in s.title


def test_next_step_no_plans_no_scheduled_pushes_plan():
    s = _compute_next_step(**{**_COMMON, "plans_active": 0, "scheduled_total": 0})
    assert s.id == "generate_plan"


def test_next_step_expiring_tokens_surfaces_only_when_everything_else_ok():
    s = _compute_next_step(**{**_COMMON, "expiring_soon": 1})
    assert s.id == "refresh_tokens"


def test_next_step_all_set():
    s = _compute_next_step(**_COMMON)
    assert s.id == "all_set"


# ---------- Endpoint — setup + activity snapshots ----------


def _make_target(db, name="Test group", **kwargs):
    t = Target(
        platform_id=kwargs.get("platform_id", "facebook"),
        external_id=kwargs.get("external_id", f"https://facebook.com/groups/{name}"),
        name=name,
        active=kwargs.get("active", True),
    )
    db.add(t)
    db.commit()
    return t


def _make_post(db, status=PostStatus.DRAFT, text="Hello"):
    p = Post(post_type=PostType.INFORMATIVE, status=status, text=text)
    db.add(p)
    db.commit()
    return p


def _make_variant(db, post, target, *, status, error=None, scheduled_for=None):
    v = PostVariant(
        post_id=post.id,
        target_id=target.id,
        text=post.text,
        status=status,
        scheduled_for=scheduled_for,
        error=error,
    )
    db.add(v)
    db.commit()
    return v


def test_overview_empty_state_pushes_profile(client, db):
    r = client.get("/api/dashboard/overview")
    assert r.status_code == 200
    data = r.json()
    assert data["setup"]["has_business_profile"] is False
    assert data["setup"]["platforms_connected"] == 0
    assert data["setup"]["targets_active"] == 0
    assert data["next_step"]["id"] in {"connect_extension", "create_profile"}


def test_overview_counts_setup_correctly(client, db):
    db.add(BusinessProfile(name="ACME", description="We sell things"))
    db.add(
        PlatformCredential(
            platform_id="instagram",
            account_id="IG1",
            username="acme",
            access_token="tkn",
            extra={},
            token_expires_at=datetime.now(UTC).replace(tzinfo=None)
            + timedelta(days=3),  # expiring soon (within 7d)
        )
    )
    db.add(
        PlatformCredential(
            platform_id="instagram",
            account_id="IG2",
            username="other",
            access_token="tkn",
            extra={},
            token_expires_at=datetime.now(UTC).replace(tzinfo=None)
            + timedelta(days=30),
        )
    )
    _make_target(db, name="group A")
    _make_target(db, name="group B", active=False)
    db.add(
        ContentPlan(
            name="April",
            status=PlanStatus.ACTIVE,
            start_date=datetime.now(UTC).date(),
            end_date=(datetime.now(UTC) + timedelta(days=7)).date(),
        )
    )
    db.commit()

    data = client.get("/api/dashboard/overview").json()
    setup = data["setup"]
    assert setup["has_business_profile"] is True
    assert setup["platforms_connected"] == 2
    assert setup["platforms_expiring_soon"] == 1
    assert setup["targets_active"] == 1
    assert setup["plans_active"] == 1


def test_overview_activity_lists_publishing_and_next_scheduled(client, db):
    db.add(BusinessProfile(name="ACME", description="x"))
    db.add(
        PlatformCredential(
            platform_id="facebook",
            account_id="FB",
            access_token="t",
            extra={},
        )
    )
    target = _make_target(db, name="ACME group")
    p1 = _make_post(db)
    p2 = _make_post(db)
    # One currently posting.
    _make_variant(db, p1, target, status=PostStatus.POSTING)
    # Two scheduled; earlier one wins.
    soon = datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=30)
    later = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=4)
    _make_variant(db, p2, target, status=PostStatus.SCHEDULED, scheduled_for=later)
    _make_variant(db, p1, target, status=PostStatus.SCHEDULED, scheduled_for=soon)

    data = client.get("/api/dashboard/overview").json()
    assert data["activity"]["publishing_now"] is not None
    assert data["activity"]["publishing_now"]["target_name"] == "ACME group"
    assert data["activity"]["next_scheduled"] is not None
    # Earlier scheduled_for wins.
    assert data["activity"]["next_scheduled"]["scheduled_for"].startswith(
        soon.isoformat()[:16]
    )
    assert data["activity"]["scheduled_total"] == 2


def test_overview_surfaces_not_a_member_failure_as_permanent(client, db):
    db.add(BusinessProfile(name="ACME", description="x"))
    db.add(
        PlatformCredential(
            platform_id="facebook",
            account_id="FB",
            access_token="t",
            extra={},
        )
    )
    target = _make_target(db, name="Private club")
    post = _make_post(db)
    _make_variant(
        db,
        post,
        target,
        status=PostStatus.FAILED,
        error="not_a_group_member: join it first",
    )
    _make_variant(
        db,
        post,
        target,
        status=PostStatus.FAILED,
        error="ETIMEDOUT",
    )

    data = client.get("/api/dashboard/overview").json()
    failures = data["activity"]["recent_failures"]
    assert len(failures) == 2
    kinds = {f["kind"] for f in failures}
    assert kinds == {"permanent", "transient"}
    # Permanent failure must drive next_step.
    assert data["next_step"]["id"] == "resolve_failures"
