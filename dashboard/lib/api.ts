/**
 * Typed fetch wrapper for the backend REST API.
 *
 * Base URL comes from NEXT_PUBLIC_API_URL (set in .env.local).
 * Falls back to http://localhost:8787 for local dev.
 */

const BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8787";

export type PostType =
  | "informative"
  | "soft_sell"
  | "hard_sell"
  | "engagement"
  | "story"
  | "motivational"
  | "testimonial"
  | "hot_take"
  | "seasonal";

export type PostStatus =
  | "draft"
  | "pending_review"
  | "scheduled"
  | "posting"
  | "posted"
  | "failed"
  | "skipped";

export type Tone = "professional" | "casual" | "fun";
export type Length = "short" | "medium" | "long";
export type EmojiDensity = "none" | "light" | "medium" | "heavy";

export interface BusinessProfile {
  id: number;
  name: string;
  description: string;
  website_url: string | null;
  products: string | null;
  target_audience: string | null;
  call_to_action_url: string | null;
  tone: Tone;
  length: Length;
  emoji_density: EmojiDensity;
  language: string;
  post_type_ratios: Record<string, number>;
  posting_window_start_hour: number;
  posting_window_end_hour: number;
  timezone: string;
  posts_per_day: number;
  review_before_posting: boolean;
  created_at: string;
  updated_at: string;
}

export type TargetReviewStatus = "pending" | "approved" | "rejected";

export interface Target {
  id: number;
  platform_id: string;
  external_id: string;
  name: string;
  tags: string[];
  list_name: string | null;
  member_count: number | null;
  active: boolean;
  created_at: string;
  description_snippet: string | null;
  category: string | null;
  source: string;
  relevance_score: number | null;
  ai_reasoning: string | null;
  review_status: TargetReviewStatus;
}

export interface PostVariant {
  id: number;
  post_id: number;
  target_id: number;
  text: string;
  status: PostStatus;
  scheduled_for: string | null;
  posted_at: string | null;
  external_post_id: string | null;
  error: string | null;
}

export interface Post {
  id: number;
  post_type: PostType;
  status: PostStatus;
  text: string;
  image_url: string | null;
  image_prompt: string | null;
  first_comment: string | null;
  cta_url: string | null;
  scheduled_for: string | null;
  posted_at: string | null;
  generation_model: string | null;
  generation_cost_usd: number | null;
  created_at: string;
  variants: PostVariant[];
}

export interface StatusOut {
  ok: boolean;
  version: string;
  extension_connected: boolean;
  scheduler_running: boolean;
  next_scheduled_post_at: string | null;
  pending_posts: number;
}

class ApiError extends Error {
  constructor(public status: number, public body: unknown, message: string) {
    super(message);
  }
}

async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const url = path.startsWith("http") ? path : `${BASE}${path}`;
  const resp = await fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
  });
  if (!resp.ok) {
    let body: unknown;
    try {
      body = await resp.json();
    } catch {
      body = await resp.text();
    }
    const detail =
      typeof body === "object" && body && "detail" in body
        ? String((body as { detail: unknown }).detail)
        : resp.statusText;
    throw new ApiError(resp.status, body, detail);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

// ---------- Status ----------

export const getStatus = () => request<StatusOut>("/api/status");

// ---------- BusinessProfile ----------

export const getBusinessProfile = () =>
  request<BusinessProfile>("/api/business-profile").catch((e) => {
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  });

export const upsertBusinessProfile = (payload: Partial<BusinessProfile>) =>
  request<BusinessProfile>("/api/business-profile", {
    method: "PUT",
    body: JSON.stringify(payload),
  });

// ---------- Targets ----------

export const listTargets = (params?: { active_only?: boolean }) => {
  const q = params?.active_only ? "?active_only=true" : "";
  return request<Target[]>(`/api/targets${q}`);
};

export const createTarget = (payload: {
  platform_id?: string;
  external_id: string;
  name: string;
  tags?: string[];
  list_name?: string;
  active?: boolean;
}) =>
  request<Target>("/api/targets", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const deleteTarget = (id: number) =>
  request<void>(`/api/targets/${id}`, { method: "DELETE" });

export const patchTarget = (id: number, patch: Partial<Target>) =>
  request<Target>(`/api/targets/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });

export const syncTargets = () =>
  request<Target[]>("/api/targets/sync", { method: "POST" });

export const listTargetsFiltered = (params: {
  platform_id?: string;
  active_only?: boolean;
  review_status?: TargetReviewStatus;
  list_name?: string;
}) => {
  const q = new URLSearchParams();
  if (params.platform_id) q.set("platform_id", params.platform_id);
  if (params.active_only) q.set("active_only", "true");
  if (params.review_status) q.set("review_status", params.review_status);
  if (params.list_name) q.set("list_name", params.list_name);
  const qs = q.toString();
  return request<Target[]>(`/api/targets${qs ? "?" + qs : ""}`);
};

export interface TargetDiscoverResult {
  created: number;
  updated: number;
  targets: Target[];
}

export const discoverTargets = () =>
  request<TargetDiscoverResult>("/api/targets/discover", { method: "POST" });

export interface TargetScoreResponse {
  scored: Array<{ target_id: number; score: number; reasoning: string }>;
  cost_usd: number;
}

export const scoreTargets = (target_ids: number[] = []) =>
  request<TargetScoreResponse>("/api/targets/score", {
    method: "POST",
    body: JSON.stringify({ target_ids }),
  });

export interface TargetClusterResponse {
  lists: Array<{ list_name: string; target_ids: number[] }>;
  cost_usd: number;
}

export const clusterTargets = (target_ids: number[] = []) =>
  request<TargetClusterResponse>("/api/targets/cluster", {
    method: "POST",
    body: JSON.stringify({ target_ids }),
  });

export const bulkReviewTargets = (
  target_ids: number[],
  review_status: TargetReviewStatus,
) =>
  request<Target[]>("/api/targets/bulk-review", {
    method: "POST",
    body: JSON.stringify({ target_ids, review_status }),
  });

// ---------- Posts ----------

export const listPosts = (status?: PostStatus) => {
  const q = status ? `?status_filter=${status}` : "";
  return request<Post[]>(`/api/posts${q}`);
};

export const getPost = (id: number) => request<Post>(`/api/posts/${id}`);

export const createPost = (payload: {
  post_type: PostType;
  text: string;
  image_url?: string | null;
  image_prompt?: string | null;
  first_comment?: string | null;
  cta_url?: string | null;
  scheduled_for?: string | null;
}) =>
  request<Post>("/api/posts", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const patchPost = (id: number, patch: Partial<Post>) =>
  request<Post>(`/api/posts/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });

export const deletePost = (id: number) =>
  request<void>(`/api/posts/${id}`, { method: "DELETE" });

export const generatePost = (payload: {
  post_type: PostType;
  topic_hint?: string;
  generate_image?: boolean;
  use_few_shot?: boolean;
}) =>
  request<Post>("/api/posts/generate", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const publishPost = (
  id: number,
  payload: {
    target_ids: number[];
    generate_spintax?: boolean;
  },
) =>
  request<{ post_id: number; status: PostStatus; variants: PostVariant[] }>(
    `/api/posts/${id}/publish`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );

export const schedulePost = (
  id: number,
  payload: {
    target_ids: number[];
    scheduled_for: string;
    generate_spintax?: boolean;
  },
) =>
  request<Post>(`/api/posts/${id}/schedule`, {
    method: "POST",
    body: JSON.stringify(payload),
  });

// ---------- Feedback ----------

export const sendFeedback = (payload: {
  post_id: number;
  rating: "up" | "down";
  comment?: string;
}) =>
  request<unknown>("/api/feedback", {
    method: "POST",
    body: JSON.stringify(payload),
  });

// ---------- Media ----------

export interface MediaUploadResult {
  id: number;
  url: string;
  filename: string;
  mime: string;
  size_bytes: number;
  width: number | null;
  height: number | null;
}

export async function uploadMedia(file: File): Promise<MediaUploadResult> {
  const form = new FormData();
  form.append("file", file);
  const resp = await fetch(`${BASE}/api/media/upload`, {
    method: "POST",
    body: form,
  });
  if (!resp.ok) {
    throw new Error(`Upload failed: ${resp.status} ${resp.statusText}`);
  }
  return resp.json();
}

export interface MediaAsset {
  id: number;
  kind: "image" | "video";
  mime: string;
  local_path: string;
  filename: string;
  size_bytes: number;
  width: number | null;
  height: number | null;
  duration_sec: number | null;
  ai_caption: string | null;
  ai_tags: string[];
  tags_user: string[];
  tagged_at: string | null;
  created_at: string;
}

export const listMedia = () => request<MediaAsset[]>("/api/media");
export const getMedia = (id: number) => request<MediaAsset>(`/api/media/${id}`);
export const deleteMedia = (id: number) =>
  request<void>(`/api/media/${id}`, { method: "DELETE" });

export const patchMedia = (id: number, patch: { tags_user?: string[] }) =>
  request<MediaAsset>(`/api/media/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });

export const tagMedia = (id: number) =>
  request<{ caption: string; tags: string[]; cost_usd: number }>(
    `/api/media/${id}/tag`,
    { method: "POST" },
  );

export const attachMediaToSlot = (assetId: number, slotId: number) =>
  request<MediaAsset>(`/api/media/${assetId}/attach-to-slot/${slotId}`, {
    method: "POST",
  });

export const suggestMediaForSlot = (slotId: number, limit = 3) =>
  request<{ asset: MediaAsset; score: number }[]>(
    `/api/media/suggest-for-slot/${slotId}?limit=${limit}`,
  );

// ---------- Content Plans (M1) ----------

export type PlanStatus = "draft" | "active" | "archived";
export type SlotStatus =
  | "planned"
  | "generated"
  | "scheduled"
  | "posted"
  | "skipped";

export interface PlanSlot {
  id: number;
  plan_id: number;
  scheduled_for: string;
  post_type: PostType;
  topic_hint: string | null;
  rationale: string | null;
  status: SlotStatus;
  post_id: number | null;
  notes: string | null;
  created_at: string;
}

export interface ContentPlan {
  id: number;
  name: string;
  goal: string | null;
  start_date: string;
  end_date: string;
  status: PlanStatus;
  generation_params: Record<string, unknown>;
  chat_history: { role: "user" | "assistant"; content: string }[];
  generation_cost_usd: number;
  created_at: string;
  updated_at: string;
  slots: PlanSlot[];
}

export const listPlans = (status?: PlanStatus) => {
  const q = status ? `?status_filter=${status}` : "";
  return request<ContentPlan[]>(`/api/plans${q}`);
};

export const getPlan = (id: number) => request<ContentPlan>(`/api/plans/${id}`);

export const generatePlan = (payload: {
  name: string;
  goal?: string | null;
  start_date: string;
  end_date: string;
}) =>
  request<ContentPlan>("/api/plans/generate", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const createEmptyPlan = (payload: {
  name: string;
  goal?: string | null;
  start_date: string;
  end_date: string;
}) =>
  request<ContentPlan>("/api/plans", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const patchPlan = (
  id: number,
  patch: { name?: string; goal?: string | null; status?: PlanStatus },
) =>
  request<ContentPlan>(`/api/plans/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });

export const deletePlan = (id: number) =>
  request<void>(`/api/plans/${id}`, { method: "DELETE" });

export const chatPlan = (id: number, message: string) =>
  request<{ reply: string; updated: boolean; plan: ContentPlan }>(
    `/api/plans/${id}/chat`,
    {
      method: "POST",
      body: JSON.stringify({ message }),
    },
  );

export const createSlot = (
  planId: number,
  payload: {
    scheduled_for: string;
    post_type: PostType;
    topic_hint?: string | null;
    rationale?: string | null;
    notes?: string | null;
  },
) =>
  request<PlanSlot>(`/api/plans/${planId}/slots`, {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const patchSlot = (
  slotId: number,
  patch: {
    scheduled_for?: string;
    post_type?: PostType;
    topic_hint?: string | null;
    rationale?: string | null;
    notes?: string | null;
    status?: SlotStatus;
  },
) =>
  request<PlanSlot>(`/api/plans/slots/${slotId}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });

export const deleteSlot = (slotId: number) =>
  request<void>(`/api/plans/slots/${slotId}`, { method: "DELETE" });

export const generatePostFromSlot = (slotId: number) =>
  request<{ slot: PlanSlot; post: Post }>(
    `/api/plans/slots/${slotId}/generate-post`,
    { method: "POST" },
  );

export { ApiError };
