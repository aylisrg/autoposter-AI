"""Claude Vision-based tagging for MediaAssets.

Given an image file, we ask Claude for:
- a concrete 1-sentence caption
- 3-8 short semantic tags

These fuel the auto-suggest-for-slot feature: match a slot's topic_hint + post_type
against each asset's tags/caption.

We intentionally don't compute vector embeddings — tags give us 80% of the quality
for 0% of the dependency cost on a vector DB.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from anthropic import Anthropic

from app.config import settings

log = logging.getLogger("ai.vision")

_COST_IN = 3.0 / 1_000_000
_COST_OUT = 15.0 / 1_000_000

_MIME_BY_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

SYSTEM_PROMPT = """You tag images for a business's social media library. You're \
shown one image and you return JSON with a short factual caption and 3-8 tags.

Rules:
- The caption is one sentence, ≤20 words, present tense, concrete. \
  No opinions, no marketing adjectives.
- Tags are lowercase, 1-2 words each, no hashtags, no punctuation.
- Tags should be searchable ("basil", "windowsill", "morning-light", \
"woman-cooking"), not vague ("beautiful", "nice", "cool").

Return ONLY JSON of the form:
{"caption": "...", "tags": ["...", "..."]}"""


@dataclass
class TagResult:
    caption: str
    tags: list[str]
    cost_usd: float


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    first = text.find("{")
    last = text.rfind("}")
    if first == -1 or last == -1:
        raise ValueError(f"No JSON in response: {text[:200]!r}")
    return json.loads(text[first : last + 1])


def tag_image(file_path: Path, mime: str | None = None) -> TagResult:
    """Call Claude with the image, parse tags. Raises if API key missing."""
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set — cannot tag images")
    if mime is None:
        mime = _MIME_BY_EXT.get(file_path.suffix.lower(), "image/jpeg")
    data = file_path.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")

    client = Anthropic(api_key=settings.anthropic_api_key)
    resp = client.messages.create(
        model=settings.text_model,
        max_tokens=400,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": mime, "data": b64},
                    },
                    {"type": "text", "text": "Tag this image."},
                ],
            }
        ],
    )
    raw = resp.content[0].text
    data_json = _extract_json(raw)
    caption = str(data_json.get("caption", "")).strip()
    tags_raw = data_json.get("tags", []) or []
    tags = [str(t).strip().lower() for t in tags_raw if str(t).strip()]
    cost = resp.usage.input_tokens * _COST_IN + resp.usage.output_tokens * _COST_OUT
    return TagResult(caption=caption, tags=tags, cost_usd=cost)


# ---------- Relevance scoring ----------

_WORD_RE = re.compile(r"[a-zA-Zа-яА-ЯёЁ]+")


def _tokenize(text: str | None) -> set[str]:
    if not text:
        return set()
    return {w.lower() for w in _WORD_RE.findall(text) if len(w) >= 3}


def media_relevance_score(
    slot_post_type: str,
    slot_topic_hint: str | None,
    asset_tags: list[str],
    asset_caption: str | None,
) -> float:
    """Jaccard-ish overlap between slot keywords and asset tags+caption.

    Purely lexical — no embeddings. Good enough for v1. Returns 0.0 if nothing \
    matches, up to 1.0.
    """
    slot_tokens = _tokenize(slot_topic_hint) | {slot_post_type.lower()}
    asset_tokens = _tokenize(" ".join(asset_tags) + " " + (asset_caption or ""))
    if not slot_tokens or not asset_tokens:
        return 0.0
    overlap = slot_tokens & asset_tokens
    if not overlap:
        return 0.0
    return len(overlap) / (len(slot_tokens | asset_tokens) ** 0.5 + 1e-9)
