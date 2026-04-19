"""M8 — Production polish: PIN auth, Fernet encryption, backups, observability.

- Fernet round-trip + backwards-compat with legacy plaintext.
- PlatformCredential.access_token transparently encrypts at rest.
- Dashboard PIN middleware blocks /api/*, allows /healthz + /api/auth/*.
- Successful login sets a session cookie that unlocks /api/*.
- /metrics returns Prometheus exposition text with request counters.
- Backup creates a zip with app.db inside.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from app.db.models import PlatformCredential
from app.security import (
    _FERNET_PREFIX,
    decrypt_str,
    encrypt_str,
)


# ---------- Fernet ----------


def test_fernet_roundtrip():
    token = encrypt_str("hello-world")
    assert token.startswith(_FERNET_PREFIX)
    assert decrypt_str(token) == "hello-world"


def test_fernet_passthrough_on_legacy_plaintext():
    # Values without the fernet: prefix are returned unchanged.
    assert decrypt_str("plain-old-token") == "plain-old-token"


def test_fernet_encrypts_only_once():
    encrypted = encrypt_str("s3cret")
    re_encrypted = encrypt_str(encrypted)
    # Second call is a no-op — still decrypts to the original.
    assert decrypt_str(re_encrypted) == "s3cret"


def test_fernet_empty_string_is_passthrough():
    assert encrypt_str("") == ""


# ---------- PlatformCredential encryption ----------


def test_credential_access_token_encrypted_at_rest(db):
    c = PlatformCredential(
        platform_id="instagram",
        account_id="IG_ENC",
        access_token="SUPER_SECRET_TOKEN",
    )
    db.add(c)
    db.commit()
    db.refresh(c)

    # Raw column stores the ciphertext prefix.
    assert c.access_token_encrypted.startswith(_FERNET_PREFIX)
    # Property returns the plaintext.
    assert c.access_token == "SUPER_SECRET_TOKEN"


def test_credential_reads_legacy_plaintext(db):
    """A row that was written before M8 still reads OK."""
    c = PlatformCredential(
        platform_id="threads",
        account_id="TH_OLD",
        access_token="LEGACY_PLAIN",
    )
    db.add(c)
    db.commit()
    # Simulate old plaintext by overwriting the raw column.
    c.access_token_encrypted = "LEGACY_PLAIN"
    db.commit()
    db.refresh(c)
    assert c.access_token == "LEGACY_PLAIN"


# ---------- PIN auth ----------


def test_auth_disabled_when_pin_empty(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "dashboard_pin", "", raising=False)
    r = client.get("/api/auth/status")
    assert r.status_code == 200
    body = r.json()
    assert body["auth_required"] is False
    assert body["authenticated"] is True


def test_auth_blocks_without_pin(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "dashboard_pin", "1234", raising=False)
    r = client.get("/api/posts")
    assert r.status_code == 401


def test_auth_allows_with_header(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "dashboard_pin", "1234", raising=False)
    r = client.get("/api/posts", headers={"X-Dashboard-Pin": "1234"})
    assert r.status_code == 200


def test_auth_allows_with_cookie_after_login(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "dashboard_pin", "1234", raising=False)
    r = client.post("/api/auth/login", json={"pin": "1234"})
    assert r.status_code == 200
    # Cookie is set by TestClient automatically.
    r2 = client.get("/api/posts")
    assert r2.status_code == 200


def test_auth_rejects_wrong_pin(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "dashboard_pin", "1234", raising=False)
    r = client.post("/api/auth/login", json={"pin": "wrong"})
    assert r.status_code == 401


def test_healthz_bypasses_auth(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "dashboard_pin", "1234", raising=False)
    assert client.get("/healthz").status_code == 200


# ---------- Observability ----------


def test_metrics_endpoint_returns_exposition_format(client):
    # Fire a couple of requests to populate counters.
    client.get("/healthz")
    client.get("/api/status")
    r = client.get("/metrics")
    assert r.status_code == 200
    body = r.text
    assert "# TYPE http_requests_total counter" in body
    assert "http_requests_total{" in body


def test_request_id_header_added(client):
    r = client.get("/healthz")
    assert "x-request-id" in {k.lower() for k in r.headers.keys()}
    assert len(r.headers["X-Request-ID"]) >= 8


def test_request_id_echoes_client_supplied(client):
    r = client.get("/healthz", headers={"X-Request-ID": "my-trace-123"})
    assert r.headers["X-Request-ID"] == "my-trace-123"


# ---------- Backups ----------


def test_backup_run_creates_zip_with_app_db(tmp_path, monkeypatch):
    # Point db_url + backup_dir at the tmp filesystem.
    from app.config import settings
    from app.services import backups

    db_file = tmp_path / "app.db"
    # Make a small sqlite file to snapshot.
    import sqlite3

    con = sqlite3.connect(str(db_file))
    con.execute("CREATE TABLE t (id INTEGER)")
    con.execute("INSERT INTO t VALUES (1)")
    con.commit()
    con.close()

    backup_dir = tmp_path / "backups"
    monkeypatch.setattr(settings, "db_url", f"sqlite:///{db_file}", raising=False)
    monkeypatch.setattr(settings, "backup_dir", str(backup_dir), raising=False)

    out = backups.run_backup()
    assert out.exists()
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        assert "app.db" in names


def test_backup_prune_removes_old_archives(tmp_path, monkeypatch):
    import os
    import time

    from app.config import settings
    from app.services import backups

    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    monkeypatch.setattr(settings, "backup_dir", str(backup_dir), raising=False)
    monkeypatch.setattr(settings, "backup_keep_days", 1, raising=False)

    # An old file (2 days) and a fresh file.
    old = backup_dir / "autoposter-2020-01-01T00-00-00Z.zip"
    old.write_bytes(b"PK\x05\x06" + b"\x00" * 18)
    os.utime(old, (time.time() - 2 * 24 * 3600, time.time() - 2 * 24 * 3600))
    fresh = backup_dir / "autoposter-2099-01-01T00-00-00Z.zip"
    fresh.write_bytes(b"PK\x05\x06" + b"\x00" * 18)

    pruned = backups.prune_old_backups(backup_dir)
    assert pruned == 1
    assert not old.exists()
    assert fresh.exists()
