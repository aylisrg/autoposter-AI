"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyState } from "@/components/ui/empty-state";
import { InfoPopover } from "@/components/ui/info-popover";
import {
  approvePost,
  approveAllPending,
  deletePost,
  listPendingReview,
  listPosts,
  listTargets,
  patchPost,
  regeneratePost,
  rejectPost,
  sendFeedback,
  type Post,
  type PostStatus,
  type Target,
} from "@/lib/api";
import { labelForPostType } from "@/lib/post-types";
import { formatDate } from "@/lib/utils";
import {
  CheckCircle2,
  ListChecks,
  RefreshCw,
  Send,
  ThumbsDown,
  ThumbsUp,
  Trash2,
  XCircle,
} from "lucide-react";

const STATUS_VARIANT: Record<PostStatus, BadgeProps["variant"]> = {
  draft: "outline",
  pending_review: "warning",
  scheduled: "secondary",
  posting: "warning",
  posted: "success",
  failed: "destructive",
  skipped: "outline",
};

type FilterKey = PostStatus | "all";

const FILTERS: Array<{ key: FilterKey; label: string; hint?: string }> = [
  { key: "all", label: "All" },
  { key: "pending_review", label: "Needs approval", hint: "AI-generated posts waiting on your thumbs-up." },
  { key: "draft", label: "Drafts", hint: "Approved but not yet scheduled anywhere." },
  { key: "scheduled", label: "Scheduled" },
  { key: "posting", label: "Publishing" },
  { key: "posted", label: "Posted" },
  { key: "failed", label: "Failed" },
];

export default function QueuePage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-muted-foreground">Loading…</div>}>
      <QueueInner />
    </Suspense>
  );
}

function QueueInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const urlFilter = (searchParams.get("status") as FilterKey | null) ?? "all";
  const [filter, setFilter] = useState<FilterKey>(urlFilter);
  const [posts, setPosts] = useState<Post[]>([]);
  const [targets, setTargets] = useState<Target[]>([]);
  const [loading, setLoading] = useState(true);

  // Sync filter <-> URL (?status=...).
  useEffect(() => {
    setFilter(urlFilter);
  }, [urlFilter]);

  const setFilterUrl = (next: FilterKey) => {
    const params = new URLSearchParams(searchParams.toString());
    if (next === "all") params.delete("status");
    else params.set("status", next);
    const qs = params.toString();
    router.replace(qs ? `/queue?${qs}` : "/queue");
  };

  const refresh = async () => {
    setLoading(true);
    try {
      const [p, t] = await Promise.all([
        filter === "pending_review"
          ? listPendingReview()
          : listPosts(filter === "all" ? undefined : filter),
        listTargets({ active_only: true }),
      ]);
      setPosts(p);
      setTargets(t);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 15_000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

  const targetNameById = useMemo(() => {
    const m: Record<number, string> = {};
    for (const t of targets) m[t.id] = t.name;
    return m;
  }, [targets]);

  const onDelete = async (id: number) => {
    if (!confirm("Delete this post and its variants?")) return;
    await deletePost(id);
    await refresh();
  };

  const onFeedback = async (id: number, rating: "up" | "down") => {
    await sendFeedback({ post_id: id, rating });
    await refresh();
  };

  return (
    <div className="space-y-4 max-w-6xl">
      <PageHeader
        title="Posts"
        icon={ListChecks}
        description="Everything you've drafted, approved, scheduled, published, or that failed. Use the tabs to narrow down."
      />

      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <CardDescription className="flex items-center gap-1">
              Updates every 15 seconds.
              <InfoPopover label="Variants">
                Each post can be sent to multiple destinations. We call each
                copy a <b>variant</b>. Variants are listed under each post and
                have their own status (scheduled, posting, posted, failed).
              </InfoPopover>
            </CardDescription>
            <div className="flex flex-wrap gap-1 text-sm">
              {FILTERS.map((f) => (
                <Button
                  key={f.key}
                  size="sm"
                  variant={filter === f.key ? "default" : "outline"}
                  onClick={() => setFilterUrl(f.key)}
                  title={f.hint}
                >
                  {f.label}
                </Button>
              ))}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="text-sm text-muted-foreground">Loading…</div>
          ) : posts.length === 0 ? (
            <EmptyState
              icon={ListChecks}
              title={
                filter === "pending_review"
                  ? "No posts waiting for approval"
                  : filter === "failed"
                  ? "No failures"
                  : "Nothing here yet"
              }
              description={
                filter === "pending_review"
                  ? "When the AI drafts a post, it lands here for your sign-off before publishing."
                  : filter === "all"
                  ? "Generate a post on the New post page, or let a Calendar plan create them for you."
                  : undefined
              }
              cta={
                filter === "all" || filter === "pending_review"
                  ? { label: "Draft a post", href: "/compose" }
                  : undefined
              }
              secondaryCta={
                filter === "all" || filter === "pending_review"
                  ? { label: "Open calendar", href: "/plans" }
                  : undefined
              }
            />
          ) : filter === "pending_review" ? (
            <ReviewList
              posts={posts}
              targets={targets}
              onChanged={refresh}
            />
          ) : (
            <div className="space-y-3">
              {posts.map((p) => (
                <div
                  key={p.id}
                  className="rounded-md border p-3 space-y-2 bg-card"
                >
                  <div className="flex items-start justify-between gap-3 flex-wrap">
                    <div className="flex items-center gap-2 flex-wrap">
                      <Badge variant={STATUS_VARIANT[p.status]}>
                        {labelForStatus(p.status)}
                      </Badge>
                      <Badge variant="outline">
                        {labelForPostType(p.post_type)}
                      </Badge>
                      <span className="text-xs text-muted-foreground">
                        #{p.id} · {formatDate(p.created_at)}
                      </span>
                      {p.scheduled_for && (
                        <span className="text-xs text-muted-foreground">
                          scheduled: {formatDate(p.scheduled_for)}
                        </span>
                      )}
                      {p.posted_at && (
                        <span className="text-xs text-muted-foreground">
                          posted: {formatDate(p.posted_at)}
                        </span>
                      )}
                    </div>
                    <div className="flex gap-1">
                      <Button
                        size="icon"
                        variant="ghost"
                        onClick={() => onFeedback(p.id, "up")}
                        title="This post is good"
                      >
                        <ThumbsUp className="h-4 w-4" />
                      </Button>
                      <Button
                        size="icon"
                        variant="ghost"
                        onClick={() => onFeedback(p.id, "down")}
                        title="This post is bad"
                      >
                        <ThumbsDown className="h-4 w-4" />
                      </Button>
                      <Button
                        size="icon"
                        variant="ghost"
                        onClick={() => onDelete(p.id)}
                        title="Delete"
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                  <div className="text-sm whitespace-pre-wrap">{p.text}</div>
                  {p.image_url && (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={p.image_url}
                      alt=""
                      className="max-h-40 rounded border"
                    />
                  )}
                  {p.variants.length > 0 && (
                    <div className="text-xs space-y-1">
                      <div className="text-muted-foreground">
                        Going out to {p.variants.length} destination
                        {p.variants.length === 1 ? "" : "s"}:
                      </div>
                      {p.variants.map((v) => (
                        <div
                          key={v.id}
                          className="flex items-center gap-2 flex-wrap"
                        >
                          <Badge variant={STATUS_VARIANT[v.status]}>
                            {labelForStatus(v.status)}
                          </Badge>
                          <span className="text-muted-foreground">
                            {targetNameById[v.target_id] ?? `destination #${v.target_id}`}
                          </span>
                          {v.external_post_id && (
                            <a
                              href={v.external_post_id}
                              target="_blank"
                              rel="noreferrer"
                              className="underline text-blue-600 break-all"
                            >
                              view on {v.target_id ? "platform" : "link"}
                            </a>
                          )}
                          {v.next_retry_at && v.status === "scheduled" && (
                            <span className="text-muted-foreground">
                              next retry at {formatDate(v.next_retry_at)}
                            </span>
                          )}
                          {v.error && (
                            <span className="text-destructive">{v.error}</span>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function labelForStatus(s: PostStatus): string {
  switch (s) {
    case "pending_review":
      return "needs approval";
    case "draft":
      return "draft";
    case "scheduled":
      return "scheduled";
    case "posting":
      return "publishing";
    case "posted":
      return "posted";
    case "failed":
      return "failed";
    case "skipped":
      return "skipped";
  }
}

// ---------- Review (merged in) ----------

function ReviewList({
  posts,
  targets,
  onChanged,
}: {
  posts: Post[];
  targets: Target[];
  onChanged: () => Promise<void> | void;
}) {
  const [busy, setBusy] = useState<number | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const [targetSel, setTargetSel] = useState<Record<number, Set<number>>>({});

  const approvedTargets = useMemo(
    () => targets.filter((t) => t.review_status === "approved" || t.active),
    [targets],
  );

  // Seed drafts for new posts so dirty-detection works cleanly.
  useEffect(() => {
    setDrafts((prev) => {
      const next = { ...prev };
      for (const post of posts) {
        if (next[post.id] === undefined) next[post.id] = post.text;
      }
      return next;
    });
  }, [posts]);

  const toggleSelected = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleTarget = (postId: number, targetId: number) => {
    setTargetSel((prev) => {
      const cur = new Set(prev[postId] ?? []);
      if (cur.has(targetId)) cur.delete(targetId);
      else cur.add(targetId);
      return { ...prev, [postId]: cur };
    });
  };

  const saveEdit = async (post: Post) => {
    const draft = drafts[post.id];
    if (draft === undefined || draft === post.text) return;
    setBusy(post.id);
    try {
      await patchPost(post.id, { text: draft });
      await onChanged();
    } finally {
      setBusy(null);
    }
  };

  const onApprove = async (post: Post, schedule = false) => {
    const draft = drafts[post.id];
    const targetIds = Array.from(targetSel[post.id] ?? []);
    setBusy(post.id);
    try {
      if (draft !== undefined && draft !== post.text) {
        await patchPost(post.id, { text: draft });
      }
      const scheduled_for = schedule
        ? new Date(Date.now() + 5 * 60 * 1000).toISOString()
        : null;
      await approvePost(post.id, { target_ids: targetIds, scheduled_for });
      await onChanged();
    } finally {
      setBusy(null);
    }
  };

  const onReject = async (post: Post) => {
    const reason =
      prompt("Why are you rejecting this post? (optional)") ?? undefined;
    setBusy(post.id);
    try {
      await rejectPost(post.id, reason);
      await onChanged();
    } finally {
      setBusy(null);
    }
  };

  const onRegenerate = async (post: Post) => {
    const hint = prompt("Topic hint for regeneration (leave blank = same):");
    setBusy(post.id);
    try {
      await regeneratePost(post.id, { topic_hint: hint || null });
      setDrafts((prev) => {
        const next = { ...prev };
        delete next[post.id];
        return next;
      });
      await onChanged();
    } finally {
      setBusy(null);
    }
  };

  const onFeedback = async (post: Post, rating: "up" | "down") => {
    await sendFeedback({ post_id: post.id, rating });
  };

  const onBulkApprove = async () => {
    if (selected.size === 0) {
      if (!confirm(`Approve ALL ${posts.length} pending posts?`)) return;
      await approveAllPending({});
    } else {
      for (const id of selected) {
        const post = posts.find((p) => p.id === id);
        if (!post) continue;
        await onApprove(post, false);
      }
    }
    setSelected(new Set());
    await onChanged();
  };

  const onDelete = async (post: Post) => {
    if (!confirm("Delete this draft?")) return;
    await deletePost(post.id);
    await onChanged();
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="text-sm text-muted-foreground">
          These posts need your sign-off before they can go anywhere.
        </div>
        <Button size="sm" onClick={onBulkApprove} disabled={posts.length === 0}>
          {selected.size > 0
            ? `Approve selected (${selected.size})`
            : "Approve all"}
        </Button>
      </div>
      {posts.map((p) => {
        const dirty = drafts[p.id] !== undefined && drafts[p.id] !== p.text;
        const tSet = targetSel[p.id] ?? new Set<number>();
        return (
          <div
            key={p.id}
            className="rounded-md border p-3 space-y-3 bg-card"
          >
            <div className="flex items-start justify-between gap-2 flex-wrap">
              <label className="flex items-center gap-2 text-xs">
                <input
                  type="checkbox"
                  checked={selected.has(p.id)}
                  onChange={() => toggleSelected(p.id)}
                />
                <Badge variant="warning">needs approval</Badge>
                <Badge variant="outline">{labelForPostType(p.post_type)}</Badge>
                <span className="text-muted-foreground">
                  #{p.id} · {formatDate(p.created_at)}
                </span>
              </label>
              <div className="flex gap-1">
                <Button
                  size="icon"
                  variant="ghost"
                  onClick={() => onFeedback(p, "up")}
                  title="This is a good draft"
                >
                  <ThumbsUp className="h-4 w-4" />
                </Button>
                <Button
                  size="icon"
                  variant="ghost"
                  onClick={() => onFeedback(p, "down")}
                  title="This draft is off"
                >
                  <ThumbsDown className="h-4 w-4" />
                </Button>
              </div>
            </div>
            <Textarea
              rows={6}
              value={drafts[p.id] ?? p.text}
              onChange={(e) =>
                setDrafts((prev) => ({
                  ...prev,
                  [p.id]: e.target.value,
                }))
              }
            />
            {dirty && (
              <div className="flex gap-2 text-xs">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => saveEdit(p)}
                  disabled={busy === p.id}
                >
                  Save edit
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() =>
                    setDrafts((prev) => ({ ...prev, [p.id]: p.text }))
                  }
                >
                  Discard
                </Button>
              </div>
            )}
            {p.image_url && (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={p.image_url}
                alt=""
                className="max-h-48 rounded border"
              />
            )}
            {approvedTargets.length > 0 && (
              <div className="text-xs space-y-1">
                <div className="text-muted-foreground">
                  Send it where? (pick destinations to schedule now, or leave
                  empty to just save as a draft)
                </div>
                <div className="flex flex-wrap gap-2">
                  {approvedTargets.map((t) => (
                    <label
                      key={t.id}
                      className="flex items-center gap-1 rounded border px-2 py-1 cursor-pointer"
                    >
                      <input
                        type="checkbox"
                        checked={tSet.has(t.id)}
                        onChange={() => toggleTarget(p.id, t.id)}
                      />
                      <span>{t.name}</span>
                    </label>
                  ))}
                </div>
              </div>
            )}
            <div className="flex gap-2 flex-wrap">
              <Button
                size="sm"
                variant="secondary"
                onClick={() => onApprove(p, false)}
                disabled={busy === p.id}
              >
                <CheckCircle2 className="h-4 w-4 mr-1" />
                Save as draft
              </Button>
              <Button
                size="sm"
                onClick={() => onApprove(p, true)}
                disabled={busy === p.id || tSet.size === 0}
                title={
                  tSet.size === 0
                    ? "Pick at least one destination above to schedule"
                    : "Send to the selected destinations in 5 minutes"
                }
              >
                <Send className="h-4 w-4 mr-1" />
                Schedule in 5 min
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => onRegenerate(p)}
                disabled={busy === p.id}
              >
                <RefreshCw className="h-4 w-4 mr-1" />
                Regenerate
              </Button>
              <Button
                size="sm"
                variant="destructive"
                onClick={() => onReject(p)}
                disabled={busy === p.id}
              >
                <XCircle className="h-4 w-4 mr-1" />
                Reject
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => onDelete(p)}
                disabled={busy === p.id}
              >
                Delete
              </Button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
