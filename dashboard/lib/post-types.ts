/**
 * Shared human-readable labels for the PostType enum.
 *
 * Backend stores enum values like "soft_sell". UI should always render the
 * labeled version. Keep in sync with `backend/app/db/models.py :: PostType`.
 */
export const POST_TYPE_LABELS: Record<string, string> = {
  informative: "Informative",
  soft_sell: "Soft sell",
  hard_sell: "Hard sell",
  engagement: "Engagement",
  story: "Story",
  motivational: "Motivational",
  testimonial: "Testimonial",
  hot_take: "Hot take",
  seasonal: "Seasonal",
};

export const POST_TYPE_DESCRIPTIONS: Record<string, string> = {
  informative: "Teaches something useful — a fact, tip, or how-to.",
  soft_sell: "Value-first post that mentions the product subtly.",
  hard_sell: "Direct offer with a clear call-to-action.",
  engagement: "Ends with a question that invites comments.",
  story: "A short story — customer, founder, or product moment.",
  motivational: "A punchy quote or mindset idea for the audience.",
  testimonial: "Reframed customer review or praise.",
  hot_take: "Opinionated stance on an industry topic.",
  seasonal: "Tied to a holiday, season, or timely event.",
};

export function labelForPostType(value: string): string {
  return POST_TYPE_LABELS[value] || value;
}

export const POST_TYPE_OPTIONS = Object.entries(POST_TYPE_LABELS).map(
  ([value, label]) => ({
    value,
    label,
    description: POST_TYPE_DESCRIPTIONS[value],
  }),
);
