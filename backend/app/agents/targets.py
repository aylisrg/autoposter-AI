"""Target Agent (M3).

Two capabilities:

1. `score_targets(profile, targets)` — given the BusinessProfile and a batch of
   unscored (or stale) Targets, returns a relevance_score 0–100 and a short
   reasoning per target. Used to help the user decide which scraped groups are
   worth posting to.

2. `cluster_targets(profile, targets)` — reads the currently approved targets and
   groups them into a handful of named lists (e.g. "Urban gardeners", "Pest /
   disease help", "Permaculture & off-grid"). Returns a mapping
   {target_id: list_name}. The caller persists via Target.list_name.

Both operations call Claude once with a structured-JSON prompt. Cost is logged but
the caller decides whether to store it.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from anthropic import Anthropic

from app.agents import MalformedLLMResponse
from app.config import settings
from app.db.models import BusinessProfile, Target

log = logging.getLogger("agents.targets")

# Claude Sonnet 4.6 pricing per million tokens (kept in sync with planner.py).
_COST_IN = 3.0 / 1_000_000
_COST_OUT = 15.0 / 1_000_000


SCORE_SYSTEM = """You are a careful B2C/B2B marketing analyst judging whether a given \
social-media community is a good fit for a business's content.

Given a business profile and a LIST of candidate communities (Facebook groups, subreddits, \
etc.), return an integer relevance_score from 0 to 100 and a one-sentence reasoning for \
each. 100 = the business's exact target audience hangs out here; 0 = completely unrelated.

## Output
Return a single JSON object:
{
  "scores": [
    {"id": 12, "score": 85, "reasoning": "Active urban-gardening community; matches your \
target audience of apartment dwellers who grow herbs indoors."},
    {"id": 13, "score": 20, "reasoning": "General cooking group; only ~5% of members would \
care about indoor gardening supplies."}
  ]
}

Guidelines:
- Be numeric and honest. Don't inflate scores to be polite.
- If description is missing, rely on name + member_count + category.
- Big groups with loose fit can still score low — relevance > reach.
- Keep reasoning to ONE sentence, concrete (mention what overlaps or doesn't).
"""


CLUSTER_SYSTEM = """You are helping a solo business owner organize their list of \
communities into 3–6 named segments.

Given a list of approved targets, cluster them into meaningful groups and name each group \
with a short human-readable label (e.g. "Urban gardeners", "Permaculture & off-grid", \
"Pest & disease help"). Every target gets exactly ONE label.

## Output
Return a single JSON object:
{
  "lists": [
    {"name": "Urban gardeners", "target_ids": [3, 7, 12]},
    {"name": "Permaculture & off-grid", "target_ids": [4, 9]}
  ]
}

Guidelines:
- 3–6 clusters is the sweet spot; fewer if targets are homogeneous, more if very diverse.
- Labels are short (2–4 words), title-case, human-facing.
- Every id from input MUST appear exactly once across all clusters.
- If two groups feel the same, merge them.
"""


@dataclass
class TargetScore:
    target_id: int
    score: int
    reasoning: str


@dataclass
class ScoreResult:
    scores: list[TargetScore]
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class ClusterAssignment:
    list_name: str
    target_ids: list[int]


@dataclass
class ClusterResult:
    lists: list[ClusterAssignment] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    first = text.find("{")
    last = text.rfind("}")
    if first == -1 or last == -1 or first > last:
        raise MalformedLLMResponse(
            f"No JSON object in model response: {text[:200]!r}"
        )
    snippet = text[first : last + 1]
    try:
        return json.loads(snippet)
    except json.JSONDecodeError as exc:
        raise MalformedLLMResponse(
            f"Targets agent returned malformed JSON: {exc.msg} (snippet: {snippet[:200]!r})"
        ) from exc


def _call_claude(system: str, user: str) -> tuple[str, int, int]:
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    client = Anthropic(api_key=settings.anthropic_api_key)
    resp = client.messages.create(
        model=settings.text_model,
        max_tokens=2500,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return resp.content[0].text, resp.usage.input_tokens, resp.usage.output_tokens


def _profile_block(bp: BusinessProfile) -> str:
    audience = bp.target_audience or "(not set)"
    products = bp.products or "(not set)"
    return (
        f"Name: {bp.name}\n"
        f"What they do: {bp.description}\n"
        f"Products: {products}\n"
        f"Target audience: {audience}\n"
        f"Language: {bp.language}\n"
    )


def _targets_block(targets: list[Target]) -> str:
    rows = []
    for t in targets:
        rows.append(
            {
                "id": t.id,
                "name": t.name,
                "platform": t.platform_id,
                "category": t.category,
                "description": t.description_snippet,
                "member_count": t.member_count,
            }
        )
    return json.dumps(rows, ensure_ascii=False, indent=2)


def score_targets(profile: BusinessProfile, targets: list[Target]) -> ScoreResult:
    """Ask Claude to score a batch of targets for relevance to the business.

    Returns ScoreResult; caller applies scores/reasoning to the DB rows.
    """
    if not targets:
        return ScoreResult(scores=[])
    user = (
        "## Business\n" + _profile_block(profile) + "\n## Candidate communities\n"
        + _targets_block(targets) + "\n\nReturn the JSON scores now."
    )
    raw, in_tok, out_tok = _call_claude(SCORE_SYSTEM, user)
    data = _extract_json(raw)
    raw_scores = data.get("scores") or []
    if not isinstance(raw_scores, list):
        raise ValueError("'scores' must be a list")

    out: list[TargetScore] = []
    known_ids = {t.id for t in targets}
    for row in raw_scores:
        if not isinstance(row, dict):
            continue
        tid = row.get("id")
        if tid not in known_ids:
            log.warning("Target agent returned unknown id=%s, skipping", tid)
            continue
        try:
            score = int(row.get("score", 0))
        except (TypeError, ValueError):
            continue
        score = max(0, min(100, score))
        out.append(
            TargetScore(
                target_id=tid,
                score=score,
                reasoning=str(row.get("reasoning", "")).strip(),
            )
        )
    cost = in_tok * _COST_IN + out_tok * _COST_OUT
    return ScoreResult(scores=out, input_tokens=in_tok, output_tokens=out_tok, cost_usd=cost)


def cluster_targets(profile: BusinessProfile, targets: list[Target]) -> ClusterResult:
    """Group approved targets into 3–6 named segments.

    The business profile is included so Claude can pick labels that match the owner's
    mental model (e.g. if you sell gardening tools, it'll pick plant-focused labels).
    """
    if len(targets) < 2:
        # Degenerate — single-bucket cluster. Cheap, no API call.
        return ClusterResult(
            lists=[ClusterAssignment(list_name="All targets", target_ids=[t.id for t in targets])]
        )
    user = (
        "## Business\n" + _profile_block(profile) + "\n## Targets to cluster\n"
        + _targets_block(targets) + "\n\nReturn the JSON clusters now."
    )
    raw, in_tok, out_tok = _call_claude(CLUSTER_SYSTEM, user)
    data = _extract_json(raw)
    raw_lists = data.get("lists") or []
    if not isinstance(raw_lists, list):
        raise ValueError("'lists' must be a list")

    assignments: list[ClusterAssignment] = []
    seen: set[int] = set()
    known = {t.id for t in targets}
    for row in raw_lists:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name", "")).strip() or "Unlabeled"
        ids_raw = row.get("target_ids") or []
        clean_ids: list[int] = []
        for raw_id in ids_raw:
            try:
                tid = int(raw_id)
            except (TypeError, ValueError):
                continue
            if tid in known and tid not in seen:
                clean_ids.append(tid)
                seen.add(tid)
        if clean_ids:
            assignments.append(ClusterAssignment(list_name=name, target_ids=clean_ids))

    # Anything unplaced goes to "Other" so we don't silently lose targets.
    leftover = [t.id for t in targets if t.id not in seen]
    if leftover:
        assignments.append(ClusterAssignment(list_name="Other", target_ids=leftover))

    cost = in_tok * _COST_IN + out_tok * _COST_OUT
    return ClusterResult(
        lists=assignments, input_tokens=in_tok, output_tokens=out_tok, cost_usd=cost
    )
