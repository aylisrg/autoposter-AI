"""Audit-log helper.

Security-sensitive mutations emit one line via the `audit` logger. When
`LOG_JSON=true` these land as structured JSON records — easy to tail, grep, or
ship to a sink. In human-readable mode they still carry the same fields as
record extras and render as `<timestamp> [audit] <message>` with the extras
visible to anything reading LogRecord.__dict__ (e.g., pytest caplog).

Rules:
- Never include the actual secret (access token, PIN, Fernet key).
- Keep payloads small — just the identifiers needed to correlate.
- Use stable action verbs ("created", "updated", "deleted") so downstream
  consumers can filter on them.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("audit")


def audit_event(action: str, resource: str, **fields: Any) -> None:
    """Emit an audit record.

    Args:
        action: "created" | "updated" | "deleted" | custom verb.
        resource: logical resource name, e.g. "platform_credential".
        **fields: any additional identifiers (id, platform_id, account_id).
            MUST NOT contain secrets.
    """
    extras: dict[str, Any] = {
        "event": "audit",
        "audit_action": action,
        "audit_resource": resource,
    }
    for key, value in fields.items():
        if value is None:
            continue
        extras[key] = value
    log.info("%s %s", resource, action, extra=extras)
