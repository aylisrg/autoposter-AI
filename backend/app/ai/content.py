"""Content generation via Anthropic Claude.

Single entry point: `generate_post(post_type, business_profile, ...)`.

Handles:
- Calling Claude with system + user prompts
- Few-shot injection of past thumbs-up posts of the same type
- Post-processing scrub of residual AI-slop patterns the model might still emit
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from anthropic import Anthropic
from sqlalchemy.orm import Session

from app.ai.prompts.post_types import build_user_prompt
from app.ai.prompts.system import SYSTEM_PROMPT
from app.config import settings
from app.db.models import BusinessProfile, FeedbackRating, Post, PostType

# Patterns we scrub as a safety net even if the prompt already forbids them.
# These are compiled once.
_EM_DASH = re.compile(r"\s*—\s*")
_BANNED_PHRASES = [
    r"\bgame[\s-]?chang(?:er|ing)\b",
    r"\blet'?s\s+unpack\b",
    r"\blet'?s\s+dive\s+in\b",
    r"\bin today'?s\s+(?:ever-evolving|fast-paced|digital)\s+",
    r"\bat the end of the day\b",
    r"\bnavigate\s+the\s+complexit",
    r"\bleverage\b",
    r"\bsynerg",
    r"\bholistic\b",
    r"\bseamless\b",
    r"\btransformative\b",
    r"\brevolutionary\b",
    r"\bcutting[\s-]?edge\b",
    r"\bbest[\s-]?in[\s-]?class\b",
    r"\bworld[\s-]?class\b",
    r"\belevate\s+your\b",
    r"\bunlock\s+the\s+power\s+of\b",
    r"\bharness\s+the\s+power\b",
    r"\bit'?s\s+worth\s+noting\b",
    r"\bit'?s\s+important\s+to\s+note\b",
    r"\bdelve\b",
    r"\btapestry\b",
    r"\bmyriad\b",
    r"\bplethora\b",
    r"\bmultifaceted\b",
    r"\bparadigm\s+shift\b",
]
_BANNED_RE = re.compile("|".join(_BANNED_PHRASES), re.IGNORECASE)


@dataclass
class GeneratedPost:
    text: str
    system_prompt: str
    user_prompt: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    scrubbed: bool  # True if post-processing modified the output


# Claude Sonnet 4.6 pricing per million tokens
_COST_IN = 3.0 / 1_000_000
_COST_OUT = 15.0 / 1_000_000


def _scrub(text: str) -> tuple[str, bool]:
    """Replace AI-slop patterns with cleaner substitutes.

    Returns (cleaned_text, was_modified).
    """
    original = text
    # Em dashes -> comma or period based on context
    text = _EM_DASH.sub(", ", text)
    # Banned phrases -> remove the surrounding sentence is overkill; mark the post for
    # regeneration instead. For now we just flag.
    modified = text != original or bool(_BANNED_RE.search(text))
    return text, modified


def _fetch_few_shot_examples(db: Session, post_type: PostType, limit: int = 3) -> list[str]:
    """Few-shot examples for the Writer.

    Prefers the engagement-ranked store curated by the Analyst (M6). If empty
    (nothing posted yet, or metrics haven't been collected), fall back to
    thumbs-up-rated posts of the same type — M0/M1 behaviour.
    """
    from app.services.few_shot import fetch_few_shot_examples as fetch_engagement_examples

    engagement = fetch_engagement_examples(db, post_type, limit=limit)
    if engagement:
        return engagement

    rows = (
        db.query(Post)
        .join(Post.feedback)
        .filter(Post.post_type == post_type)
        .filter(Post.feedback.any(rating=FeedbackRating.UP))
        .order_by(Post.created_at.desc())
        .limit(limit)
        .all()
    )
    return [r.text for r in rows]


def generate_post(
    db: Session,
    post_type: PostType,
    business_profile: BusinessProfile,
    topic_hint: str | None = None,
    use_few_shot: bool = True,
) -> GeneratedPost:
    """Generate a single post.

    If `use_few_shot` and we have past thumbs-up posts of this type, they're injected
    as assistant examples before the real ask — Claude picks up the user's voice.
    """
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    client = Anthropic(api_key=settings.anthropic_api_key)

    user_prompt = build_user_prompt(post_type, business_profile, topic_hint)

    messages: list[dict] = []
    if use_few_shot:
        examples = _fetch_few_shot_examples(db, post_type, limit=3)
        for ex in examples:
            messages.append({"role": "user", "content": "Write a post of this type."})
            messages.append({"role": "assistant", "content": ex})

    messages.append({"role": "user", "content": user_prompt})

    resp = client.messages.create(
        model=settings.text_model,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=messages,
    )

    raw = resp.content[0].text.strip()
    # Strip any accidental quotes around the whole thing
    if raw.startswith('"') and raw.endswith('"'):
        raw = raw[1:-1]
    if raw.startswith("```") and raw.endswith("```"):
        raw = raw.strip("`").strip()

    cleaned, modified = _scrub(raw)

    input_tokens = resp.usage.input_tokens
    output_tokens = resp.usage.output_tokens
    cost = input_tokens * _COST_IN + output_tokens * _COST_OUT

    return GeneratedPost(
        text=cleaned,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        model=settings.text_model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost,
        scrubbed=modified,
    )


def generate_spintax_variant(
    post_text: str,
    business_profile: BusinessProfile,
) -> str:
    """Generate a reworded version of the same post for a different target.

    Used to ensure no two groups receive the same text — a key anti-spam signal for
    Facebook (identical text across groups is a strong bot indicator).
    """
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    client = Anthropic(api_key=settings.anthropic_api_key)

    prompt = f"""Rewrite the following post in a different way. Keep:
- The same core message and specific facts/numbers.
- The same tone and approximate length.
- The same call-to-action if any.

Change:
- Opening line (completely different).
- Sentence structure and word choice.
- Paragraph breaks.

The goal is that the two versions look like two different people wrote about the \
same topic. NOT a thesaurus swap — a genuine rewrite.

Forbidden: em dashes, "game-changer", "let's unpack", "leverage", "synergy", "delve", \
any AI-cliché. Write like a human.

Original post:
---
{post_text}
---

Language: {business_profile.language}. Return only the rewritten post text.
"""

    resp = client.messages.create(
        model=settings.text_model,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = resp.content[0].text.strip()
    cleaned, _ = _scrub(raw)
    return cleaned
