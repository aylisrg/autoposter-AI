"""Daily backup — zip the SQLite DB + media assets to `settings.backup_dir`.

The scheduler calls `run_backup()` once a day (cron 03:00 UTC). We keep the
last N archives (`settings.backup_keep_days`) and prune older ones.

Backup layout:
    data/backups/autoposter-2026-04-19T03-00-00Z.zip
        ├─ app.db
        └─ images/...        (only if `data/images` exists)

SQLite needs a consistent snapshot — we use the `.backup` method via a direct
sqlite3 connection, which works while the app is running.
"""
from __future__ import annotations

import logging
import sqlite3
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from app.config import settings

log = logging.getLogger("services.backups")


def _iter_files(root: Path):
    for p in root.rglob("*"):
        if p.is_file():
            yield p


def _sqlite_path() -> Path:
    """Resolve the SQLite DB path from the db_url. Supports
    `sqlite:///./data/app.db` and absolute forms.
    """
    url = settings.db_url
    if not url.startswith("sqlite"):
        raise RuntimeError(f"Backups only support sqlite; got {url}")
    # Strip sqlite:///, keep whatever's left. The triple slash convention
    # means a relative path starts with "./".
    remainder = url.split("sqlite:///", 1)[-1]
    return Path(remainder).resolve()


def run_backup() -> Path:
    """Create a zip archive and return its path."""
    backup_root = Path(settings.backup_dir)
    backup_root.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    out_path = backup_root / f"autoposter-{stamp}.zip"

    db_path = _sqlite_path()
    # Use sqlite .backup for a consistent snapshot. Connect read-only via URI.
    snap_path = backup_root / f".{stamp}-app.db"
    src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    dst = sqlite3.connect(str(snap_path))
    try:
        with dst:
            src.backup(dst)
    finally:
        src.close()
        dst.close()

    images = Path("data/images")
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(snap_path, arcname="app.db")
        if images.exists():
            for f in _iter_files(images):
                zf.write(f, arcname=str(f.relative_to(Path("data"))))
    try:
        snap_path.unlink()
    except OSError:
        pass

    prune_old_backups(backup_root)
    log.info("Backup written to %s (%.1f MB)", out_path, out_path.stat().st_size / 1e6)
    return out_path


def prune_old_backups(root: Path) -> int:
    """Delete archives older than `settings.backup_keep_days`. Returns count."""
    cutoff = time.time() - settings.backup_keep_days * 24 * 3600
    pruned = 0
    for p in root.glob("autoposter-*.zip"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
                pruned += 1
        except OSError:
            continue
    return pruned
