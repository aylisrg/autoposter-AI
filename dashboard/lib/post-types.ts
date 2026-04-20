/**
 * Shared human-readable labels for the PostType enum.
 *
 * Backend stores enum values like "soft_sell". UI should always render the
 * labeled version. Keep this list in sync with `backend/app/db/models.py ::
 * PostType`.
 */
export const POST_TYPE_LABELS: Record<string, string> = {
  informative: "Informative",
  storytelling: "Storytelling",
  question: "Question to audience",
  poll: "Poll",
  promo: "Promo",
  soft_sell: "Soft sell",
  testimonial: "Testimonial",
  behind_the_scenes: "Behind the scenes",
  hot_take: "Hot take",
};

export const POST_TYPE_DESCRIPTIONS: Record<string, string> = {
  informative: "Short educational post. Shares a useful fact or tip.",
  storytelling: "A brief story — customer, founder, or product moment.",
  question: "Ends with an open question to spark comments.",
  poll: "A short choice question (manual poll on FB).",
  promo: "Direct offer with a clear call-to-action.",
  soft_sell: "Value-first post that mentions the product subtly.",
  testimonial: "Reframed customer review or praise.",
  behind_the_scenes: "A peek at your process, workshop, day.",
  hot_take: "Opinionated stance on an industry topic.",
};

export function labelForPostType(value: string): string {
  return POST_TYPE_LABELS[value] || value;
}

export const POST_TYPE_OPTIONS = Object.entries(POST_TYPE_LABELS).map(
  ([value, label]) => ({ value, label, description: POST_TYPE_DESCRIPTIONS[value] }),
);
