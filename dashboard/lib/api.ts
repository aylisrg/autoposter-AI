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
  auto_approve_types: string[];
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
  attempt_count?: number;
  next_retry_at?: string | null;
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
    credentials: "include",  // send/receive dashboard_session cookie
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

// ---------- Review & Approval (M5) ----------

export const listPendingReview = () =>
  request<Post[]>("/api/posts/review/pending");

export const approvePost = (
  id: number,
  payload: { target_ids?: number[]; scheduled_for?: string | null } = {},
) =>
  request<Post>(`/api/posts/${id}/approve`, {
    method: "POST",
    body: JSON.stringify({
      target_ids: payload.target_ids ?? [],
      scheduled_for: payload.scheduled_for ?? null,
    }),
  });

export const rejectPost = (id: number, reason?: string) =>
  request<Post>(`/api/posts/${id}/reject`, {
    method: "POST",
    body: JSON.stringify({ reason: reason ?? null }),
  });

export const regeneratePost = (
  id: number,
  payload: { topic_hint?: string | null; generate_image?: boolean } = {},
) =>
  request<Post>(`/api/posts/${id}/regenerate`, {
    method: "POST",
    body: JSON.stringify({
      topic_hint: payload.topic_hint ?? null,
      generate_image: payload.generate_image ?? false,
    }),
  });

export const approveAllPending = (payload: {
  post_type?: PostType | null;
  scheduled_for?: string | null;
}) =>
  request<Post[]>("/api/posts/review/approve-all", {
    method: "POST",
    body: JSON.stringify({
      post_type: payload.post_type ?? null,
      scheduled_for: payload.scheduled_for ?? null,
    }),
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
  media_asset_id: number | null;
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

// ---------- Humanizer (M4) ----------

export type SessionHealthStatus =
  | "healthy"
  | "warning"
  | "checkpoint"
  | "shadow_ban_suspected"
  | "paused";

export interface HumanizerProfile {
  id: number;
  typing_wpm_min: number;
  typing_wpm_max: number;
  mistake_rate: number;
  pause_between_sentences_ms_min: number;
  pause_between_sentences_ms_max: number;
  mouse_path_curvature: number;
  idle_scroll_before_post_sec_min: number;
  idle_scroll_before_post_sec_max: number;
  schedule_jitter_minutes: number;
  consecutive_failures_threshold: number;
  smart_pause_minutes: number;
  smart_pause_until: string | null;
  smart_pause_reason: string | null;
}

export interface SessionHealth {
  platform_id: string;
  status: SessionHealthStatus;
  consecutive_failures: number;
  last_failure_at: string | null;
  last_failure_reason: string | null;
  last_success_at: string | null;
}

export interface SmartPauseInfo {
  paused: boolean;
  until: string | null;
  reason: string | null;
}

export interface BlackoutDate {
  id: number;
  date: string;
  reason: string | null;
}

export const getHumanizer = () =>
  request<HumanizerProfile>("/api/humanizer/profile");

export const patchHumanizer = (patch: Partial<HumanizerProfile>) =>
  request<HumanizerProfile>("/api/humanizer/profile", {
    method: "PATCH",
    body: JSON.stringify(patch),
  });

export const listSessionHealth = () =>
  request<SessionHealth[]>("/api/humanizer/session-health");

export const getPauseStatus = () =>
  request<SmartPauseInfo>("/api/humanizer/pause");

export const activatePause = () =>
  request<SmartPauseInfo>("/api/humanizer/pause", { method: "POST" });

export const resumeFromPause = () =>
  request<SmartPauseInfo>("/api/humanizer/resume", { method: "POST" });

export const listBlackouts = () =>
  request<BlackoutDate[]>("/api/humanizer/blackout-dates");

export const addBlackout = (payload: { date: string; reason?: string | null }) =>
  request<BlackoutDate>("/api/humanizer/blackout-dates", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const deleteBlackout = (id: number) =>
  request<void>(`/api/humanizer/blackout-dates/${id}`, { method: "DELETE" });

// ---------- Analytics / Analyst / Optimizer (M6) ----------

export type MetricsWindow = "1h" | "24h" | "7d";

export interface PostMetricsEntry {
  id: number;
  variant_id: number;
  window: MetricsWindow;
  likes: number;
  comments: number;
  shares: number;
  reach: number | null;
  engagement_score: number;
  collected_at: string;
}

export interface AnalyticsSummary {
  period_days: number;
  posts: number;
  likes: number;
  comments: number;
  shares: number;
  avg_engagement_score: number;
}

export interface TopPerformer {
  post_id: number;
  post_type: PostType;
  posted_at: string | null;
  text_preview: string;
  engagement_score: number;
}

export interface AnalystReport {
  id: number;
  period_start: string;
  period_end: string;
  summary: string;
  body: {
    summary?: string;
    top_performers?: Array<{ post_id: number; why: string }>;
    bottom_performers?: Array<{ post_id: number; why: string }>;
    patterns?: string[];
    proposals?: Array<{
      field: string;
      current_value: unknown;
      proposed_value: unknown;
      reasoning: string;
      confidence: number;
    }>;
  };
  cost_usd: number;
  model: string;
  created_at: string;
}

export type ProposalStatus = "pending" | "applied" | "rejected";

export interface OptimizerProposal {
  id: number;
  report_id: number | null;
  field: string;
  current_value: Record<string, unknown>;
  proposed_value: Record<string, unknown>;
  reasoning: string;
  confidence: number;
  status: ProposalStatus;
  auto_applied: boolean;
  applied_at: string | null;
  created_at: string;
}

export const getMetricsForPost = (postId: number) =>
  request<PostMetricsEntry[]>(`/api/metrics/post/${postId}`);

export const collectMetricsNow = () =>
  request<{ variants_touched: number; rows_created: number }>(
    "/api/metrics/collect",
    { method: "POST" },
  );

export const getAnalyticsSummary = (days = 7) =>
  request<AnalyticsSummary>(`/api/analytics/summary?days=${days}`);

export const getTopPerformers = (days = 7, limit = 5, reverse = false) =>
  request<TopPerformer[]>(
    `/api/analytics/top-performers?days=${days}&limit=${limit}&reverse=${reverse}`,
  );

export const listAnalystReports = () =>
  request<AnalystReport[]>("/api/analyst/reports");

export const getAnalystReport = (id: number) =>
  request<AnalystReport>(`/api/analyst/reports/${id}`);

export const generateAnalystReport = (payload: {
  days?: number;
  period_start?: string;
  period_end?: string;
} = {}) =>
  request<AnalystReport>("/api/analyst/generate", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const listProposals = (status?: ProposalStatus) => {
  const q = status ? `?status=${status}` : "";
  return request<OptimizerProposal[]>(`/api/optimizer/proposals${q}`);
};

export const applyProposal = (id: number) =>
  request<OptimizerProposal>(`/api/optimizer/proposals/${id}/apply`, {
    method: "POST",
  });

export const rejectProposal = (id: number) =>
  request<OptimizerProposal>(`/api/optimizer/proposals/${id}/reject`, {
    method: "POST",
  });

export const refreshFewShotStore = () =>
  request<{ inserted: number }>("/api/few-shot/refresh", { method: "POST" });

// ---------- M7: Platforms (Instagram / Threads) ----------

export interface PlatformCredential {
  id: number;
  platform_id: string;
  account_id: string;
  username: string | null;
  token_expires_at: string | null;
  days_until_expiry: number | null;
  extra: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface MetaOAuthUrl {
  url: string;
  state: string;
}

export interface MetaOAuthComplete {
  instagram: PlatformCredential | null;
  threads: PlatformCredential | null;
  message: string;
}

export const getMetaOAuthUrl = () =>
  request<MetaOAuthUrl>("/api/meta/oauth/url");

export const addManualCredential = (payload: {
  platform_id: "instagram" | "threads";
  account_id: string;
  username?: string;
  access_token: string;
}) =>
  request<PlatformCredential>("/api/meta/credentials", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const listPlatformCredentials = () =>
  request<PlatformCredential[]>("/api/platform-credentials");

export const deletePlatformCredential = (id: number) =>
  request<void>(`/api/platform-credentials/${id}`, { method: "DELETE" });

export const refreshPlatformCredential = (id: number) =>
  request<PlatformCredential>(`/api/platform-credentials/${id}/refresh`, {
    method: "POST",
  });

// ---------- Extension smoke (fail-loud diagnostics) ----------

export interface ExtensionSmokeReport {
  locale: string;
  url: string;
  is_group_page: boolean;
  is_logged_in: boolean;
  checkpoint_detected: boolean;
  // null = not on a group page (or couldn't tell)
  is_group_member: boolean | null;
  composer_trigger: boolean;
  composer_editor_when_open: boolean;
  post_button_when_open: boolean;
  photo_video_button_when_open: boolean;
  comment_button_on_article: boolean;
  comment_editor_on_article: boolean;
  groups_detected: number;
  articles_detected: number;
  warnings: string[];
}

export const runExtensionSmoke = () =>
  request<{ ok: true; report: ExtensionSmokeReport }>("/api/extension/smoke", {
    method: "POST",
  });

// ---------- Dashboard overview (guided home) ----------

export type NextStepId =
  | "connect_extension"
  | "create_profile"
  | "connect_platform"
  | "add_targets"
  | "generate_plan"
  | "review_drafts"
  | "resolve_failures"
  | "refresh_tokens"
  | "all_set";

export interface NextStep {
  id: NextStepId;
  title: string;
  description: string;
  cta_label: string;
  cta_href: string;
}

export interface SetupBlock {
  backend_ok: boolean;
  extension_connected: boolean;
  scheduler_running: boolean;
  has_business_profile: boolean;
  platforms_connected: number;
  platforms_expiring_soon: number;
  targets_active: number;
  plans_active: number;
}

export interface PublishingNow {
  variant_id: number;
  post_id: number;
  target_name: string;
  platform_id: string;
  started_at: string | null;
}

export interface NextScheduled {
  variant_id: number;
  post_id: number;
  target_name: string;
  platform_id: string;
  scheduled_for: string;
}

export interface RecentFailure {
  variant_id: number;
  post_id: number;
  target_name: string;
  platform_id: string;
  error: string;
  updated_at: string;
  kind: "permanent" | "transient";
}

export interface ActivityBlock {
  publishing_now: PublishingNow | null;
  next_scheduled: NextScheduled | null;
  pending_review: number;
  failed_last_24h: number;
  scheduled_total: number;
  posted_today: number;
  drafts: number;
  recent_failures: RecentFailure[];
}

export interface DashboardOverview {
  next_step: NextStep;
  setup: SetupBlock;
  activity: ActivityBlock;
}

export const getDashboardOverview = () =>
  request<DashboardOverview>("/api/dashboard/overview");

// ---------- M8: Auth ----------

export interface AuthStatus {
  auth_required: boolean;
  authenticated: boolean;
}

export const getAuthStatus = () =>
  request<AuthStatus>("/api/auth/status");

export const login = (pin: string) =>
  request<AuthStatus>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ pin }),
  });

export const logout = () =>
  request<AuthStatus>("/api/auth/logout", { method: "POST" });

export { ApiError };
