"""Phase 2 security/ops additions.

- JSON log formatter emits parseable records with expected fields.
- RequestContextMiddleware attaches structured extras (request_id, method,
  path, status, ms) to its access records.
- PlatformCredential create / update / delete paths each fire an
  `audit_event("created"|"updated"|"deleted", ...)` record tagged with
  platform_id + account_id (never the token value).
- scripts/encrypt_legacy_tokens.py upgrades plaintext rows in-place without
  clobbering already-encrypted ones.
"""
from __future__ import annotations

import json
import logging

from app.db.models import PlatformCredential


# ---------- JSON log formatter ----------


def test_json_formatter_emits_expected_fields():
    from app.observability import JsonFormatter

    record = logging.LogRecord(
        name="http",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request completed",
        args=(),
        exc_info=None,
    )
    record.request_id = "abc123"
    record.method = "GET"
    record.path = "/api/status"
    record.status = 200
    record.ms = 4.2

    line = JsonFormatter().format(record)
    payload = json.loads(line)
    assert payload["level"] == "INFO"
    assert payload["logger"] == "http"
    assert payload["message"] == "request completed"
    assert payload["request_id"] == "abc123"
    assert payload["method"] == "GET"
    assert payload["path"] == "/api/status"
    assert payload["status"] == 200
    assert payload["ms"] == 4.2
    assert "ts" in payload


def test_json_formatter_stringifies_unserialisable_extras():
    from app.observability import JsonFormatter

    class Unserialisable:
        def __repr__(self) -> str:
            return "<Unserialisable>"

    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="hi", args=(), exc_info=None,
    )
    record.blob = Unserialisable()
    payload = json.loads(JsonFormatter().format(record))
    assert payload["blob"] == "<Unserialisable>"


def test_configure_logging_is_idempotent():
    from app.observability import _OUR_HANDLER_MARKER, configure_logging

    configure_logging(json_output=True)
    configure_logging(json_output=False)
    configure_logging(json_output=True)
    root = logging.getLogger()
    # Exactly one of the handlers *we* installed, regardless of any foreign
    # handlers (pytest caplog, uvicorn, etc.) that happen to be attached.
    ours = [h for h in root.handlers if getattr(h, _OUR_HANDLER_MARKER, False)]
    assert len(ours) == 1


# ---------- Access log extras ----------


def test_access_log_carries_structured_extras(client, caplog):
    caplog.set_level(logging.INFO, logger="http")
    r = client.get("/api/status")
    assert r.status_code == 200

    matching = [rec for rec in caplog.records if rec.name == "http" and rec.message == "request completed"]
    assert matching, "expected an http access record"
    rec = matching[-1]
    assert rec.method == "GET"
    assert rec.path == "/api/status"
    assert rec.status == 200
    assert hasattr(rec, "request_id") and rec.request_id
    assert isinstance(rec.ms, float)


# ---------- Credential audit log ----------


def _audit_records(caplog):
    return [rec for rec in caplog.records if rec.name == "audit"]


def test_audit_event_has_expected_fields(caplog):
    caplog.set_level(logging.INFO, logger="audit")
    from app.services.audit import audit_event

    audit_event(
        "created",
        "platform_credential",
        credential_id=7,
        platform_id="instagram",
        account_id="999",
    )
    records = _audit_records(caplog)
    assert len(records) == 1
    rec = records[0]
    assert rec.audit_action == "created"
    assert rec.audit_resource == "platform_credential"
    assert rec.credential_id == 7
    assert rec.platform_id == "instagram"
    assert rec.account_id == "999"


def test_delete_credential_emits_audit_event(client, db, caplog):
    caplog.set_level(logging.INFO, logger="audit")

    row = PlatformCredential(
        platform_id="instagram",
        account_id="acc-1",
        access_token="plain-token",
    )
    db.add(row)
    db.commit()
    cid = row.id

    r = client.delete(f"/api/platform-credentials/{cid}")
    assert r.status_code == 204

    records = _audit_records(caplog)
    assert any(
        getattr(rec, "audit_action", None) == "deleted"
        and getattr(rec, "audit_resource", None) == "platform_credential"
        and getattr(rec, "credential_id", None) == cid
        and getattr(rec, "platform_id", None) == "instagram"
        for rec in records
    )
    # Never log the token value itself.
    for rec in records:
        for value in rec.__dict__.values():
            assert "plain-token" != value


def test_add_manual_credential_emits_audit_event(client, caplog):
    caplog.set_level(logging.INFO, logger="audit")

    payload = {
        "platform_id": "instagram",
        "account_id": "acc-2",
        "access_token": "secret-xyz",
        "username": "biz",
    }
    r = client.post("/api/meta/credentials", json=payload)
    assert r.status_code == 200

    records = _audit_records(caplog)
    created = [rec for rec in records if getattr(rec, "audit_action", None) == "created"]
    assert created, "expected a created audit record"
    assert getattr(created[-1], "platform_id", None) == "instagram"
    assert getattr(created[-1], "account_id", None) == "acc-2"
    # Token must never appear in any audit record's attributes.
    for rec in records:
        for value in rec.__dict__.values():
            assert value != "secret-xyz"


def test_update_credential_reports_changed_fields(client, caplog):
    caplog.set_level(logging.INFO, logger="audit")

    client.post(
        "/api/meta/credentials",
        json={
            "platform_id": "instagram",
            "account_id": "acc-3",
            "access_token": "token-A",
            "username": "old-name",
        },
    )
    caplog.clear()

    r = client.post(
        "/api/meta/credentials",
        json={
            "platform_id": "instagram",
            "account_id": "acc-3",
            "access_token": "token-B",
            "username": "new-name",
        },
    )
    assert r.status_code == 200

    updates = [
        rec
        for rec in _audit_records(caplog)
        if getattr(rec, "audit_action", None) == "updated"
    ]
    assert updates
    changed = updates[-1].changed_fields
    assert "access_token" in changed
    assert "username" in changed


# ---------- Legacy-token migration script ----------


def test_encrypt_legacy_tokens_migrates_plaintext(db, session_maker, monkeypatch, caplog):
    from app.db import session as db_session
    from app.security import _FERNET_PREFIX

    # Two legacy plaintext rows + one already-encrypted row.
    legacy1 = PlatformCredential(platform_id="instagram", account_id="a1")
    legacy1.access_token_encrypted = "plaintext-A"
    legacy2 = PlatformCredential(platform_id="threads", account_id="a2")
    legacy2.access_token_encrypted = "plaintext-B"
    already = PlatformCredential(platform_id="instagram", account_id="a3")
    already.access_token = "safe"  # goes through setter → prefixed
    db.add_all([legacy1, legacy2, already])
    db.commit()

    monkeypatch.setattr(db_session, "SessionLocal", session_maker, raising=True)

    from scripts import encrypt_legacy_tokens

    rc = encrypt_legacy_tokens.main()
    assert rc == 0

    db.expire_all()
    all_rows = db.query(PlatformCredential).all()
    for row in all_rows:
        assert row.access_token_encrypted.startswith(_FERNET_PREFIX)
    # Decrypt round-trips cleanly.
    assert {r.access_token for r in all_rows} == {"plaintext-A", "plaintext-B", "safe"}


def test_encrypt_legacy_tokens_is_idempotent(db, session_maker, monkeypatch):
    from app.db import session as db_session

    row = PlatformCredential(platform_id="instagram", account_id="idem")
    row.access_token_encrypted = "legacy-plain"
    db.add(row)
    db.commit()

    monkeypatch.setattr(db_session, "SessionLocal", session_maker, raising=True)

    from scripts import encrypt_legacy_tokens

    assert encrypt_legacy_tokens.main() == 0
    db.expire_all()
    first_value = db.query(PlatformCredential).one().access_token_encrypted

    # Second run: nothing changes.
    assert encrypt_legacy_tokens.main() == 0
    db.expire_all()
    assert db.query(PlatformCredential).one().access_token_encrypted == first_value


# ---------- Regression: settings has log_json knob ----------


def test_log_json_setting_defaults_false():
    from app.config import settings

    assert settings.log_json is False
