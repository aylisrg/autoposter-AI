"""One-shot migration: encrypt any legacy plaintext `PlatformCredential` rows.

Pre-M8 credentials were stored as plaintext in the `access_token` column.
M8 introduced Fernet-at-rest encryption with a `fernet:v1:` prefix; the
`PlatformCredential.access_token` property-setter transparently encrypts on
write. Rows written pre-M8 remain decryptable (the decrypt helper returns
non-prefixed values as-is), so they keep working — but they stay on disk in
plaintext until the next update.

Run this script once after upgrading to M8+ to sweep all such rows into the
encrypted format. Idempotent: skip rows that already carry the prefix.

    cd backend && python -m scripts.encrypt_legacy_tokens

Exit codes:
    0 — success (count printed; zero is fine)
    1 — DB init / access error
"""
from __future__ import annotations

import logging
import sys

from app.db import session as db_session
from app.db.models import PlatformCredential
from app.security import _FERNET_PREFIX  # internal but stable — used by encrypt_str


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    log = logging.getLogger("encrypt_legacy_tokens")

    # Late-bind SessionLocal so tests that monkeypatch it are respected.
    try:
        db = db_session.SessionLocal()
    except Exception as exc:  # noqa: BLE001
        log.error("Could not open DB session: %s", exc)
        return 1

    try:
        rows = db.query(PlatformCredential).all()
        log.info("Scanning %d credential row(s)", len(rows))
        migrated = 0
        skipped = 0
        for row in rows:
            stored = row.access_token_encrypted
            if not stored:
                skipped += 1
                continue
            if stored.startswith(_FERNET_PREFIX):
                skipped += 1
                continue
            # Assign through the property to trigger encrypt_str.
            row.access_token = stored
            migrated += 1
        if migrated:
            db.commit()
        log.info(
            "Migration complete: migrated=%d already_encrypted_or_empty=%d",
            migrated,
            skipped,
        )
        return 0
    except Exception as exc:  # noqa: BLE001
        log.exception("Migration failed: %s", exc)
        db.rollback()
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
