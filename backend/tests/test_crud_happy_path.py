"""Happy-path CRUD tests for the four M0 resources (issue #10)."""
from __future__ import annotations

from app.db.models import PostType


def test_business_profile_crud(client):
    payload = {
        "name": "Acme",
        "description": "We make things.",
        "tone": "casual",
        "length": "medium",
        "emoji_density": "light",
    }
    # GET missing
    assert client.get("/api/business-profile").status_code == 404

    # POST create
    r = client.post("/api/business-profile", json=payload)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "Acme"
    assert body["id"] == 1

    # GET
    r = client.get("/api/business-profile")
    assert r.status_code == 200
    assert r.json()["name"] == "Acme"

    # PATCH
    r = client.patch("/api/business-profile", json={"name": "Acme Updated"})
    assert r.status_code == 200
    assert r.json()["name"] == "Acme Updated"

    # DELETE
    r = client.delete("/api/business-profile")
    assert r.status_code == 204
    assert client.get("/api/business-profile").status_code == 404


def test_target_crud(client):
    payload = {
        "platform_id": "facebook",
        "external_id": "https://www.facebook.com/groups/test",
        "name": "Test Group",
    }
    r = client.post("/api/targets", json=payload)
    assert r.status_code == 201, r.text
    tid = r.json()["id"]

    r = client.get("/api/targets")
    assert r.status_code == 200
    assert any(t["id"] == tid for t in r.json())

    r = client.get(f"/api/targets/{tid}")
    assert r.status_code == 200
    assert r.json()["name"] == "Test Group"

    r = client.patch(f"/api/targets/{tid}", json={"name": "Updated Group"})
    assert r.status_code == 200
    assert r.json()["name"] == "Updated Group"

    r = client.delete(f"/api/targets/{tid}")
    assert r.status_code == 204
    assert client.get(f"/api/targets/{tid}").status_code == 404


def test_post_crud(client):
    payload = {
        "post_type": PostType.INFORMATIVE.value,
        "text": "Hello world",
    }
    r = client.post("/api/posts", json=payload)
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert r.json()["text"] == "Hello world"

    r = client.get("/api/posts")
    assert r.status_code == 200
    assert any(p["id"] == pid for p in r.json())

    r = client.get(f"/api/posts/{pid}")
    assert r.status_code == 200

    r = client.patch(f"/api/posts/{pid}", json={"text": "Updated text"})
    assert r.status_code == 200
    assert r.json()["text"] == "Updated text"

    r = client.delete(f"/api/posts/{pid}")
    assert r.status_code == 204
    assert client.get(f"/api/posts/{pid}").status_code == 404


def test_feedback_crud(client):
    # Need a post first
    post_r = client.post(
        "/api/posts",
        json={"post_type": "informative", "text": "Post for feedback"},
    )
    assert post_r.status_code == 201
    post_id = post_r.json()["id"]

    payload = {"post_id": post_id, "rating": "up", "comment": "Nice"}
    r = client.post("/api/feedback", json=payload)
    assert r.status_code == 201, r.text
    fid = r.json()["id"]
    assert r.json()["rating"] == "up"

    r = client.get(f"/api/feedback/{fid}")
    assert r.status_code == 200
    assert r.json()["comment"] == "Nice"

    r = client.get(f"/api/feedback/by-post/{post_id}")
    assert r.status_code == 200
    assert len(r.json()) == 1

    r = client.patch(f"/api/feedback/{fid}", json={"comment": "Updated"})
    assert r.status_code == 200
    assert r.json()["comment"] == "Updated"

    r = client.delete(f"/api/feedback/{fid}")
    assert r.status_code == 204
    assert client.get(f"/api/feedback/{fid}").status_code == 404
