"""Per-post-type user-prompt templates.

Each function takes the business context and returns the user message for Claude.
The system message (system.py) handles voice, anti-slop, and formatting — these
handle the strategic angle of each post type.

Format convention: each prompt ends with "Write the post now. Only the post text."
to ensure clean output.
"""
from app.db.models import BusinessProfile, EmojiDensity, Length, PostType, Tone

# Human-readable labels
POST_TYPE_LABELS: dict[PostType, str] = {
    PostType.INFORMATIVE: "Informative",
    PostType.SOFT_SELL: "Soft Sell",
    PostType.HARD_SELL: "Hard Sell",
    PostType.ENGAGEMENT: "Engagement",
    PostType.STORY: "Story / Personal",
    PostType.MOTIVATIONAL: "Motivational",
    PostType.TESTIMONIAL: "Testimonial",
    PostType.HOT_TAKE: "Hot Take",
    PostType.SEASONAL: "Seasonal / Trending",
}


def _voice_block(bp: BusinessProfile) -> str:
    """Shared block of voice+business context inserted into every prompt."""
    emoji_map = {
        EmojiDensity.NONE: "No emojis at all.",
        EmojiDensity.LIGHT: "Max 1 emoji in the whole post, only if it genuinely fits.",
        EmojiDensity.MEDIUM: "1-3 emojis spread naturally, never two in a row.",
        EmojiDensity.HEAVY: "3-6 emojis, but still tasteful — no walls of them.",
    }
    length_map = {
        Length.SHORT: "Short (1-3 sentences, ~250 chars).",
        Length.MEDIUM: "Medium (2-4 short paragraphs, ~600 chars).",
        Length.LONG: "Long (4-7 short paragraphs, ~1400 chars). Use line breaks for rhythm.",
    }
    tone_map = {
        Tone.PROFESSIONAL: "Professional but human. Clear, measured, no slang.",
        Tone.CASUAL: "Casual, like talking to a friend who cares about this topic.",
        Tone.FUN: "Playful, a bit cheeky, willing to be funny. Still credible.",
    }
    return f"""## Business context
Name: {bp.name}
What they do: {bp.description}
{"Products/services: " + bp.products if bp.products else ""}
{"Target audience: " + bp.target_audience if bp.target_audience else ""}
{"CTA link: " + bp.call_to_action_url if bp.call_to_action_url else ""}

## Voice
- Tone: {tone_map[bp.tone]}
- Length: {length_map[bp.length]}
- Emoji: {emoji_map[bp.emoji_density]}
- Language: {bp.language} (write the post in this language).
"""


def informative(bp: BusinessProfile, topic_hint: str | None = None) -> str:
    return f"""{_voice_block(bp)}

## Task: Informative post
Share one specific, useful tip or piece of info your audience can use TODAY. Not \
generic advice. Something you'd tell a friend who asked you for help.

Rules for this type:
- Start with a concrete observation or claim, not a question.
- Give the useful bit FAST. Don't bury it.
- No sales pitch. This is pure value-give.
- End with a small practical takeaway, not a CTA.

{"Topic hint: " + topic_hint if topic_hint else "Pick any relevant topic from the business."}

Write the post now. Only the post text.
"""


def soft_sell(bp: BusinessProfile, topic_hint: str | None = None) -> str:
    return f"""{_voice_block(bp)}

## Task: Soft sell post
Lead with something genuinely useful or interesting, THEN mention the offer naturally \
at the end. The reader shouldn't feel sold to — they should feel informed, and then \
optionally curious about what the business offers.

Rules for this type:
- First 80% of the post: pure value. Insight, observation, story, or tip.
- Last 20%: natural mention of what the business does, in a way that flows from what \
came before. Not a sales slogan.
- Include the CTA URL if one is set, but only in the soft-mention at the end.
- No "DM me!" or "Link in bio!" — that's hard sell.

{"Angle hint: " + topic_hint if topic_hint else ""}

Write the post now. Only the post text.
"""


def hard_sell(bp: BusinessProfile, topic_hint: str | None = None) -> str:
    return f"""{_voice_block(bp)}

## Task: Hard sell post
Direct promotion of what the business offers. The reader knows this is a pitch, but \
it should still be interesting to read. Not a flyer, not a slogan.

Rules for this type:
- State the offer clearly in the first 2 sentences.
- Give ONE concrete reason it matters (specific benefit, specific result, specific \
who-it's-for).
- Call to action at the end: clear, short, with the URL if set.
- Still no buzzwords, no "revolutionary", no "transform your life".
- Sound like a human who is genuinely enthusiastic, not a billboard.

{"Angle: " + topic_hint if topic_hint else ""}

Write the post now. Only the post text.
"""


def engagement(bp: BusinessProfile, topic_hint: str | None = None) -> str:
    return f"""{_voice_block(bp)}

## Task: Engagement post
A post designed to get replies. The question or prompt should be genuinely interesting \
to your audience, not bait.

Rules for this type:
- Ask ONE specific question. Not "what do you think?" — something with bite.
- OR share a strong opinion and invite counter-opinions.
- Must be relevant to your business/audience's world.
- Keep it short. Long engagement posts get fewer replies.
- End with the question or invitation, not with a period on a statement.

{"Topic: " + topic_hint if topic_hint else ""}

Write the post now. Only the post text.
"""


def story(bp: BusinessProfile, topic_hint: str | None = None) -> str:
    return f"""{_voice_block(bp)}

## Task: Story / personal post
A moment from running the business or a personal experience related to the work. \
Humanizes the business. Makes the reader feel they know the person behind it.

Rules for this type:
- Start with a specific scene ("Last Tuesday at 4pm, a client called..." not "I want \
to share a story about...").
- Concrete sensory details — names (or descriptors), places, times, exact words said.
- There should be a small insight, realization, or shift by the end. Not a lecture.
- NO moral-of-the-story preachy ending. Let it breathe.

{"Story hint: " + topic_hint if topic_hint else "Invent a plausible, specific recent moment from the business."}

Write the post now. Only the post text.
"""


def motivational(bp: BusinessProfile, topic_hint: str | None = None) -> str:
    return f"""{_voice_block(bp)}

## Task: Motivational post
Uplifting content relevant to your audience. BUT — the internet is drowning in \
fake-deep motivational posts. Yours must feel earned.

Rules for this type:
- Tie it to something SPECIFIC to your field or a real experience. No "you got this!" \
on its own.
- Avoid quote-tweeting someone famous. Make the point yourself.
- Don't be saccharine. A bit of edge or honesty is better than sugar.
- No "hustle harder" energy. No toxic positivity.

{"Angle: " + topic_hint if topic_hint else ""}

Write the post now. Only the post text.
"""


def testimonial(bp: BusinessProfile, topic_hint: str | None = None) -> str:
    return f"""{_voice_block(bp)}

## Task: Testimonial / results post
Share a client win or result. Written BY the business owner, not in review form.

Rules for this type:
- Describe the situation briefly: who, what problem.
- The result: specific, numeric if possible.
- What made it work (brief — 1 sentence).
- Use first name or a descriptor ("a client in real estate", "a freelance designer"). \
Never make up names; if no real case, frame as "a typical client situation".
- If the business has no real clients yet, skip this post type entirely. Better to \
post nothing than a fake testimonial.

{"Case hint: " + topic_hint if topic_hint else ""}

Write the post now. Only the post text.
"""


def hot_take(bp: BusinessProfile, topic_hint: str | None = None) -> str:
    return f"""{_voice_block(bp)}

## Task: Hot take
A bold opinion relevant to your field. Designed to spark discussion and make people \
think "huh, that's actually a point".

Rules for this type:
- State the opinion in the first sentence. Clearly.
- Give 1-2 specific reasons. Not a manifesto — just enough teeth.
- Must be defensible. No trolling, no hate.
- Avoid the tired hot takes of your industry. Pick something slightly unexpected.
- Invite disagreement at the end, but don't beg for it.

{"Angle: " + topic_hint if topic_hint else ""}

Write the post now. Only the post text.
"""


def seasonal(bp: BusinessProfile, topic_hint: str | None = None) -> str:
    return f"""{_voice_block(bp)}

## Task: Seasonal / trending post
Tie the business to a current holiday, season, or event. Relevant, not forced.

Rules for this type:
- If there's no good natural tie-in, skip this post — never shoehorn.
- Relate the seasonal thing to a specific business insight or offer.
- No generic "Happy Monday" type posts.
- If it's a holiday, respect its actual meaning. No using solemn holidays for sales.

{"Season/event: " + topic_hint if topic_hint else "Pick a plausible current season or upcoming event."}

Write the post now. Only the post text.
"""


PROMPT_BUILDERS = {
    PostType.INFORMATIVE: informative,
    PostType.SOFT_SELL: soft_sell,
    PostType.HARD_SELL: hard_sell,
    PostType.ENGAGEMENT: engagement,
    PostType.STORY: story,
    PostType.MOTIVATIONAL: motivational,
    PostType.TESTIMONIAL: testimonial,
    PostType.HOT_TAKE: hot_take,
    PostType.SEASONAL: seasonal,
}


def build_user_prompt(
    post_type: PostType, bp: BusinessProfile, topic_hint: str | None = None
) -> str:
    return PROMPT_BUILDERS[post_type](bp, topic_hint)
