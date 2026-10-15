"""Background AI tagging and embedding for MediaAssets.

After upload we enqueue a FastAPI BackgroundTask that:
1. Calls Claude Vision (Haiku-class) for caption + 5-15 tags.
2. Computes a local embedding of the caption+tags (simple hash-based vector,
   stand-in for voyage-3-lite / BGE-small).
3. Persists ai_tags, ai_caption, embedding, tagged_at.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.ai.vision import tag_image
from app.db.models import MediaAsset
from app.db import session as db_session

log = logging.getLogger("media.tagging")

EMBEDDING_DIM = 32


def compute_local_embedding(text: str) -> list[float]:
    """Deterministic fixed-size embedding from text.

    Uses SHA-256 of overlapping character n-grams projected into EMBEDDING_DIM
    floats in [-1, 1]. Sufficient for tests and as a local stand-in until a
    real voyage / BGE model is wired.
    """
    text = (text or "").lower().strip()
    if not text:
        return [0.0] * EMBEDDING_DIM
    vec = [0.0] * EMBEDDING_DIM
    # Character 3-grams
    padded = f"  {text}  "
    for i in range(len(padded) - 2):
        gram = padded[i : i + 3]
        h = int(hashlib.sha256(gram.encode()).hexdigest(), 16)
        idx = h % EMBEDDING_DIM
        sign = 1.0 if (h // EMBEDDING_DIM) % 2 == 0 else -1.0
        vec[idx] += sign
    # L2 normalize
    norm = sum(x * x for x in vec) ** 0.5
    if norm > 0:
        vec = [x / norm for x in vec]
    return vec


def tag_and_embed_asset(asset_id: int) -> None:
    """Background worker: open own session, tag, embed, commit.

    Safe to call from FastAPI BackgroundTasks. Swallows errors so a tagging
    failure never breaks the upload response.
    """
    db: Session = db_session.SessionLocal()
    try:
        asset = db.get(MediaAsset, asset_id)
        if asset is None:
            log.warning("tag_and_embed: asset %s disappeared", asset_id)
            return
        full_path = Path("data") / asset.local_path
        if not full_path.exists():
            log.warning("tag_and_embed: file missing for asset %s", asset_id)
            return

        result = tag_image(full_path, mime=asset.mime)
        asset.ai_caption = result.caption
        asset.ai_tags = result.tags[:15]  # cap at DoD upper bound
        text_for_embed = f"{result.caption} {' '.join(result.tags)}"
        asset.embedding = compute_local_embedding(text_for_embed)
        asset.tagged_at = datetime.now(UTC)
        db.commit()
        log.info(
            "tagged asset %s: %d tags, embedding dim=%d, cost=$%.4f",
            asset_id,
            len(result.tags),
            len(asset.embedding or []),
            result.cost_usd,
        )
    except Exception:
        log.exception("tag_and_embed failed for asset %s", asset_id)
        db.rollback()
    finally:
        db.close()
