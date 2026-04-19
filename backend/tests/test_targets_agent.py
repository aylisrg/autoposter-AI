"""M3 Targets Agent + API tests.

We stub Claude (`score_targets`, `cluster_targets`) and the extension bridge so
nothing hits the network. Real SQLite + real FastAPI routing.
"""
from __future__ import annotations

import pytest

from app.agents.targets import ClusterAssignment, ClusterResult, ScoreResult, TargetScore


@pytest.fixture()
def profile_ready(client):
    """Seed a BusinessProfile so /score and /cluster don't 400."""
    r = client.put(
        "/api/business-profile",
        json={
            "name": "Garden Nook",
            "description": "Indoor gardening supplies for apartment dwellers.",
            "target_audience": "Urban renters who grow herbs on windowsills.",
        },
    )
    assert r.status_code == 200, r.text


@pytest.fixture()
def fake_agent(monkeypatch):
    """Return a (score_spy, cluster_spy) pair — tests inject scripted behaviour."""

    class Spy:
        calls: list
        script: object

        def __init__(self) -> None:
            self.calls = []
            self.script = None

    score_spy = Spy()
    cluster_spy = Spy()

    def fake_score(profile, targets):
        score_spy.calls.append([t.id for t in targets])
        if callable(score_spy.script):
            return score_spy.script(profile, targets)
        return ScoreResult(
            scores=[
                TargetScore(target_id=t.id, score=70 if "garden" in t.name.lower() else 20,
                            reasoning=f"auto-{t.name}")
                for t in targets
            ],
            input_tokens=500,
            output_tokens=200,
            cost_usd=0.005,
        )

    def fake_cluster(profile, targets):
        cluster_spy.calls.append([t.id for t in targets])
        if callable(cluster_spy.script):
            return cluster_spy.script(profile, targets)
        # Naive split: first half -> list A, second half -> list B.
        half = len(targets) // 2 or 1
        return ClusterResult(
            lists=[
                ClusterAssignment(
                    list_name="Urban gardeners",
                    target_ids=[t.id for t in targets[:half]],
                ),
                ClusterAssignment(
                    list_name="General cooks",
                    target_ids=[t.id for t in targets[half:]],
                ),
            ],
            cost_usd=0.004,
        )

    monkeypatch.setattr("app.api.targets.score_targets", fake_score, raising=True)
    monkeypatch.setattr("app.api.targets.cluster_targets", fake_cluster, raising=True)
    return score_spy, cluster_spy


# ---------- agent unit-ish tests (no API) ----------


def test_score_result_clamps_and_filters_unknown_ids(monkeypatch):
    """If Claude returns an out-of-range score or unknown id, we clamp/drop it."""
    from app.agents import targets as agent_mod

    def stub_call(system, user):
        return (
            '{"scores":['
            '{"id": 1, "score": 150, "reasoning": "over"},'
            '{"id": 2, "score": -20, "reasoning": "under"},'
            '{"id": 999, "score": 50, "reasoning": "unknown"}'
            "]}",
            10,
            5,
        )

    monkeypatch.setattr(agent_mod, "_call_claude", stub_call, raising=True)

    class FakeTarget:
        def __init__(self, tid):
            self.id = tid
            self.name = f"t{tid}"
            self.platform_id = "facebook"
            self.category = None
            self.description_snippet = None
            self.member_count = None

    class FakeProfile:
        name = "X"
        description = "Y"
        products = None
        target_audience = None
        language = "en"

    result = agent_mod.score_targets(FakeProfile(), [FakeTarget(1), FakeTarget(2)])
    # id=999 should be dropped; 150→100; -20→0.
    by_id = {s.target_id: s.score for s in result.scores}
    assert by_id == {1: 100, 2: 0}


def test_cluster_leftover_goes_to_other(monkeypatch):
    from app.agents import targets as agent_mod

    def stub_call(system, user):
        return (
            '{"lists":[{"name":"A","target_ids":[1]}]}',
            10,
            5,
        )

    monkeypatch.setattr(agent_mod, "_call_claude", stub_call, raising=True)

    class FakeTarget:
        def __init__(self, tid):
            self.id = tid
            self.name = f"t{tid}"
            self.platform_id = "facebook"
            self.category = None
            self.description_snippet = None
            self.member_count = None

    class FakeProfile:
        name = "X"
        description = "Y"
        products = None
        target_audience = None
        language = "en"

    result = agent_mod.cluster_targets(
        FakeProfile(), [FakeTarget(1), FakeTarget(2), FakeTarget(3)]
    )
    # id=1 is in A; 2 and 3 go to "Other".
    names = [lg.list_name for lg in result.lists]
    assert "Other" in names
    other = next(lg for lg in result.lists if lg.list_name == "Other")
    assert sorted(other.target_ids) == [2, 3]


def test_cluster_single_target_shortcircuits(monkeypatch):
    """With ≤1 target, cluster should skip Claude entirely."""
    from app.agents import targets as agent_mod

    called = {"n": 0}

    def stub_call(system, user):
        called["n"] += 1
        raise AssertionError("should not be called")

    monkeypatch.setattr(agent_mod, "_call_claude", stub_call, raising=True)

    class FakeTarget:
        id = 1
        name = "x"
        platform_id = "facebook"
        category = None
        description_snippet = None
        member_count = None

    class FakeProfile:
        name = "X"
        description = "Y"
        products = None
        target_audience = None
        language = "en"

    result = agent_mod.cluster_targets(FakeProfile(), [FakeTarget()])
    assert called["n"] == 0
    assert len(result.lists) == 1
    assert result.lists[0].list_name == "All targets"


# ---------- API tests ----------


def _mk_target(client, external_id: str, name: str, source: str = "scraped_suggested"):
    return client.post(
        "/api/targets",
        json={
            "platform_id": "facebook",
            "external_id": external_id,
            "name": name,
            "source": source,
        },
    ).json()


def test_manual_create_auto_approves(client):
    t = _mk_target(client, "https://www.facebook.com/groups/1", "Manual Group", source="manual")
    assert t["review_status"] == "approved"


def test_scraped_create_is_pending(client):
    t = _mk_target(
        client, "https://www.facebook.com/groups/2", "Scraped Group",
        source="scraped_suggested",
    )
    assert t["review_status"] == "pending"


def test_score_endpoint_populates_relevance(client, profile_ready, fake_agent):
    t1 = _mk_target(client, "https://fb/groups/a", "Herb garden lovers")
    t2 = _mk_target(client, "https://fb/groups/b", "Random car club")
    r = client.post("/api/targets/score", json={"target_ids": []})
    assert r.status_code == 200, r.text
    body = r.json()
    assert {s["target_id"] for s in body["scored"]} == {t1["id"], t2["id"]}
    # Now the rows should have scores + reasoning.
    reloaded = client.get("/api/targets").json()
    by_name = {t["name"]: t for t in reloaded}
    assert by_name["Herb garden lovers"]["relevance_score"] == 70
    assert by_name["Random car club"]["relevance_score"] == 20


def test_score_endpoint_respects_explicit_ids(client, profile_ready, fake_agent):
    t1 = _mk_target(client, "https://fb/groups/a", "Herb garden lovers")
    _mk_target(client, "https://fb/groups/b", "Random car club")
    spy, _cluster = fake_agent
    r = client.post("/api/targets/score", json={"target_ids": [t1["id"]]})
    assert r.status_code == 200
    assert spy.calls[-1] == [t1["id"]]


def test_score_requires_profile(client, fake_agent):
    """Without a BusinessProfile, /score should 400."""
    _mk_target(client, "https://fb/groups/a", "G")
    r = client.post("/api/targets/score", json={"target_ids": []})
    assert r.status_code == 400


def test_bulk_review_approve_and_reject(client):
    t1 = _mk_target(client, "https://fb/groups/a", "A")
    t2 = _mk_target(client, "https://fb/groups/b", "B")
    r = client.post(
        "/api/targets/bulk-review",
        json={"target_ids": [t1["id"], t2["id"]], "review_status": "approved"},
    )
    assert r.status_code == 200
    for row in r.json():
        assert row["review_status"] == "approved"

    r = client.post(
        "/api/targets/bulk-review",
        json={"target_ids": [t2["id"]], "review_status": "rejected"},
    )
    assert r.status_code == 200
    assert r.json()[0]["review_status"] == "rejected"


def test_cluster_writes_list_name_on_approved(client, profile_ready, fake_agent):
    t1 = _mk_target(client, "https://fb/groups/a", "A")
    t2 = _mk_target(client, "https://fb/groups/b", "B")
    t3 = _mk_target(client, "https://fb/groups/c", "C")
    t4 = _mk_target(client, "https://fb/groups/d", "D")
    client.post(
        "/api/targets/bulk-review",
        json={
            "target_ids": [t1["id"], t2["id"], t3["id"], t4["id"]],
            "review_status": "approved",
        },
    )
    r = client.post("/api/targets/cluster", json={"target_ids": []})
    assert r.status_code == 200, r.text
    lists = r.json()["lists"]
    assert len(lists) == 2
    # All four targets should now have a list_name.
    reloaded = client.get("/api/targets").json()
    assert all(t["list_name"] in {"Urban gardeners", "General cooks"} for t in reloaded)


def test_list_filters_by_review_status(client):
    t1 = _mk_target(client, "https://fb/groups/a", "A", source="scraped_suggested")
    _mk_target(client, "https://fb/groups/b", "B", source="manual")  # auto-approved
    r = client.get("/api/targets?review_status=pending").json()
    assert [t["id"] for t in r] == [t1["id"]]
    r = client.get("/api/targets?review_status=approved").json()
    assert t1["id"] not in [t["id"] for t in r]


def test_discover_endpoint_calls_bridge(client, monkeypatch):
    """/discover should call the extension bridge and upsert pending targets."""
    async def fake_request(payload, timeout=60):
        assert payload["type"] == "list_suggested_groups"
        return {
            "ok": True,
            "groups": [
                {
                    "url": "https://fb/groups/new1",
                    "external_id": "https://fb/groups/new1",
                    "name": "Urban gardeners club",
                    "member_count": 15000,
                    "description": "For apartment gardeners",
                },
                {
                    "external_id": "https://fb/groups/new2",
                    "name": "Pest control tips",
                    "member_count": 8000,
                },
            ],
        }

    from app.ws import extension_bridge as br
    monkeypatch.setattr(br.bridge, "request", fake_request, raising=True)
    r = client.post("/api/targets/discover")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 2
    assert body["updated"] == 0
    # Both should be pending.
    rows = client.get("/api/targets?review_status=pending").json()
    assert len(rows) == 2
    assert rows[0]["description_snippet"] == "For apartment gardeners" or \
        rows[1]["description_snippet"] == "For apartment gardeners"


def test_discover_second_call_updates(client, monkeypatch):
    """Re-running discover on the same url should update, not duplicate."""
    async def fake_request(payload, timeout=60):
        return {
            "ok": True,
            "groups": [
                {
                    "external_id": "https://fb/groups/same",
                    "name": "Updated name",
                    "member_count": 42,
                }
            ],
        }

    from app.ws import extension_bridge as br
    monkeypatch.setattr(br.bridge, "request", fake_request, raising=True)

    r1 = client.post("/api/targets/discover").json()
    r2 = client.post("/api/targets/discover").json()
    assert r1["created"] == 1 and r1["updated"] == 0
    assert r2["created"] == 0 and r2["updated"] == 1
    rows = client.get("/api/targets").json()
    assert len(rows) == 1
    assert rows[0]["name"] == "Updated name"
    assert rows[0]["member_count"] == 42
