"""Content Planner Agent.

Given a BusinessProfile, a date range, and an optional goal, Claude returns a list of
PlanSlot proposals (date+time, post_type, topic_hint, rationale). The agent also
supports conversational refinement: the user chats "move Thursday's post to Friday
evening and make it an engagement post" and the agent returns a patched plan.

Design notes:
- We call Claude with a single JSON-response prompt. If it doesn't parse, we retry once
  and then surface the error.
- Scheduling heuristics (posting window, posts_per_day, weekday spread) are ENCODED IN
  THE PROMPT, not applied after the fact. That keeps Claude's distribution choices
  coherent with the business profile instead of being re-shuffled by us.
- The agent never writes actual post text. It only proposes slots. Generating the post
  is a separate step (calls `generate_post` in `ai.content`).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from anthropic import Anthropic

from app.agents import MalformedLLMResponse
from app.config import settings
from app.db.models import BusinessProfile, PostType

log = logging.getLogger("agents.planner")

# Claude Sonnet 4.6 pricing per million tokens
_COST_IN = 3.0 / 1_000_000
_COST_OUT = 15.0 / 1_000_000

_VALID_POST_TYPES = {pt.value for pt in PostType}


SYSTEM_PROMPT = """You are a content planner for a real business's social media.

Your job: given the business profile, a date range, and an optional goal, design a \
content calendar. You propose SLOTS (date + time + post type + topic hint + short \
rationale). You NEVER write the actual post text; that's a separate step.

## Strict rules
1. Output MUST be a single JSON object with this shape:
   {
     "slots": [
       {"scheduled_for": "2025-07-12T10:30:00Z", "post_type": "informative", \
"topic_hint": "...", "rationale": "..."},
       ...
     ],
     "summary": "1-2 sentence overall strategy for this plan."
   }
2. `post_type` MUST be one of: informative, soft_sell, hard_sell, engagement, story, \
motivational, testimonial, hot_take, seasonal.
3. All `scheduled_for` timestamps must be in ISO 8601 with a "Z" suffix (UTC).
4. Respect the posting window: only schedule inside [posting_window_start_hour, \
posting_window_end_hour] in the business's local timezone, converted to UTC.
5. Respect posts_per_day: MAX this many slots on any single calendar day.
6. Respect post_type_ratios if provided (e.g. {"informative": 0.4, "soft_sell": 0.3, \
"engagement": 0.2, "story": 0.1}). The mix across all slots should roughly match.
7. Spread slots across weekdays — never cluster all posts on one day.
8. Each `topic_hint` must be SPECIFIC. Not "share a tip" — say what tip, e.g. "how to \
spot overwatered basil in 10 seconds". The writer uses this as a brief.
9. Return NO markdown code fences, NO commentary, JUST the JSON object.
10. Do not include hashtags or emojis in topic_hint — that's the writer's job.

## Quality bar
- Each slot should feel like a different angle, not 14 riffs on the same idea.
- Seasonal slots only when there's a genuine tie-in to the date range.
- Testimonials: include only if the goal allows it (the business may not have cases \
yet).
- Hot takes: at most 1 per week.
- Stories: include 1-2 to humanize the brand.
"""


@dataclass
class SlotProposal:
    scheduled_for: datetime
    post_type: PostType
    topic_hint: str | None
    rationale: str | None


@dataclass
class PlanProposal:
    slots: list[SlotProposal]
    summary: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    raw_response: str = ""


@dataclass
class RefinementResult(PlanProposal):
    reply: str = ""  # Natural-language assistant reply shown in the chat UI
    assistant_history_entry: dict = field(default_factory=dict)


def _extract_json(text: str) -> dict:
    """Pull the JSON object out of a Claude reply that may include stray fences."""
    text = text.strip()
    if text.startswith("```"):
        # Strip ``` blocks
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    # Find first { and last }
    first = text.find("{")
    last = text.rfind("}")
    if first == -1 or last == -1 or first > last:
        raise MalformedLLMResponse(
            f"No JSON object found in model response: {text[:200]!r}"
        )
    snippet = text[first : last + 1]
    try:
        return json.loads(snippet)
    except json.JSONDecodeError as exc:
        raise MalformedLLMResponse(
            f"Model returned malformed JSON: {exc.msg} (snippet: {snippet[:200]!r})"
        ) from exc


def _build_user_prompt(
    bp: BusinessProfile,
    start_date: datetime,
    end_date: datetime,
    goal: str | None,
    existing_slots: list[dict] | None = None,
) -> str:
    ratios_str = (
        json.dumps(bp.post_type_ratios) if bp.post_type_ratios else "(not set — use a natural mix)"
    )
    existing_block = ""
    if existing_slots:
        existing_block = (
            "\n## Existing slots (for reference — rebuild or adjust, not duplicate)\n"
            + json.dumps(existing_slots, default=str, indent=2)
        )
    return f"""## Business
Name: {bp.name}
What they do: {bp.description}
{"Products: " + bp.products if bp.products else ""}
{"Audience: " + bp.target_audience if bp.target_audience else ""}

## Voice
Tone: {bp.tone.value}. Length: {bp.length.value}. Emoji density: {bp.emoji_density.value}.
Language: {bp.language}.

## Schedule constraints
Start: {start_date.isoformat()}
End: {end_date.isoformat()}
Posts per day (max): {bp.posts_per_day}
Posting window (local hours): {bp.posting_window_start_hour}:00 – \
{bp.posting_window_end_hour}:00
Timezone: {bp.timezone}
post_type_ratios: {ratios_str}

## Goal
{goal or "Steady engagement. Mix of value-giving and soft promotion."}
{existing_block}

Return the JSON plan now.
"""


def _parse_slots(data: dict) -> list[SlotProposal]:
    raw_slots = data.get("slots", [])
    if not isinstance(raw_slots, list):
        raise ValueError("'slots' must be a list")
    out: list[SlotProposal] = []
    for i, raw in enumerate(raw_slots):
        if not isinstance(raw, dict):
            raise ValueError(f"Slot {i} is not an object")
        pt_raw = raw.get("post_type")
        if pt_raw not in _VALID_POST_TYPES:
            raise ValueError(f"Slot {i} has invalid post_type: {pt_raw!r}")
        sched_raw = raw.get("scheduled_for")
        if not sched_raw:
            raise ValueError(f"Slot {i} missing scheduled_for")
        sched = datetime.fromisoformat(sched_raw.replace("Z", "+00:00"))
        if sched.tzinfo is None:
            sched = sched.replace(tzinfo=UTC)
        out.append(
            SlotProposal(
                scheduled_for=sched.astimezone(UTC),
                post_type=PostType(pt_raw),
                topic_hint=raw.get("topic_hint"),
                rationale=raw.get("rationale"),
            )
        )
    return out


def _call_claude(messages: list[dict], system: str = SYSTEM_PROMPT) -> tuple[str, int, int]:
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    client = Anthropic(api_key=settings.anthropic_api_key)
    resp = client.messages.create(
        model=settings.text_model,
        max_tokens=4000,
        system=system,
        messages=messages,
    )
    return resp.content[0].text, resp.usage.input_tokens, resp.usage.output_tokens


def propose_plan(
    business_profile: BusinessProfile,
    start_date: datetime,
    end_date: datetime,
    goal: str | None = None,
) -> PlanProposal:
    """Initial plan generation. Returns N SlotProposals."""
    if end_date <= start_date:
        raise ValueError("end_date must be after start_date")
    if (end_date - start_date) > timedelta(days=60):
        raise ValueError("Plan range must be ≤ 60 days")

    user_prompt = _build_user_prompt(business_profile, start_date, end_date, goal)
    raw, in_tok, out_tok = _call_claude([{"role": "user", "content": user_prompt}])
    try:
        data = _extract_json(raw)
    except Exception:
        log.warning("First planner JSON parse failed, retrying once")
        raw, in_tok2, out_tok2 = _call_claude(
            [
                {"role": "user", "content": user_prompt},
                {"role": "assistant", "content": raw},
                {
                    "role": "user",
                    "content": (
                        "Your response wasn't valid JSON. Respond again with ONLY the "
                        "JSON object, no prose."
                    ),
                },
            ]
        )
        in_tok += in_tok2
        out_tok += out_tok2
        data = _extract_json(raw)

    slots = _parse_slots(data)
    cost = in_tok * _COST_IN + out_tok * _COST_OUT
    return PlanProposal(
        slots=slots,
        summary=data.get("summary", ""),
        input_tokens=in_tok,
        output_tokens=out_tok,
        cost_usd=cost,
        raw_response=raw,
    )


def refine_plan(
    business_profile: BusinessProfile,
    start_date: datetime,
    end_date: datetime,
    current_slots: list[dict],
    chat_history: list[dict],
    user_message: str,
) -> RefinementResult:
    """Conversational refinement.

    `chat_history` is the prior transcript (list of {role, content} dicts).
    `current_slots` is the current saved state of the plan's slots.
    `user_message` is the new user turn.

    The agent may either:
    - Answer in natural language without changing the plan (returns an empty `slots`).
    - Propose a new slot list that replaces the current one.

    To disambiguate: the agent ALWAYS returns JSON with:
      {"reply": "...", "updated": bool, "slots": [...] | null, "summary": "..."}
    """
    system = SYSTEM_PROMPT + """

## Refinement mode
You're in a chat with the user about their existing plan. They may ask questions, \
request edits, or approve what's there.

Always respond with JSON:
{
  "reply": "Short natural-language reply to the user, ≤3 sentences.",
  "updated": true | false,
  "slots": <same shape as before, or null if updated=false>,
  "summary": "If updated, a 1-sentence new overall strategy. Else null."
}

Set `updated`=false when the user just asks a question or you want clarification.
Set `updated`=true only when you're replacing the entire slot list with a new one.
"""
    user_prompt = _build_user_prompt(
        business_profile, start_date, end_date, goal=None, existing_slots=current_slots
    )

    messages: list[dict] = [{"role": "user", "content": user_prompt}]
    # Replay prior chat history
    for turn in chat_history:
        role = turn.get("role")
        content = turn.get("content")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_message})

    raw, in_tok, out_tok = _call_claude(messages, system=system)
    data = _extract_json(raw)

    reply = data.get("reply", "")
    updated = bool(data.get("updated", False))
    slots: list[SlotProposal] = []
    if updated:
        slots = _parse_slots(data)

    cost = in_tok * _COST_IN + out_tok * _COST_OUT
    return RefinementResult(
        slots=slots,
        summary=data.get("summary") or "",
        input_tokens=in_tok,
        output_tokens=out_tok,
        cost_usd=cost,
        raw_response=raw,
        reply=reply,
        assistant_history_entry={"role": "assistant", "content": reply},
    )
