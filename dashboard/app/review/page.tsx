"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import {
  approvePost,
  approveAllPending,
  deletePost,
  listPendingReview,
  listTargets,
  patchPost,
  regeneratePost,
  rejectPost,
  sendFeedback,
  type Post,
  type Target,
} from "@/lib/api";
import { formatDate } from "@/lib/utils";
import {
  CheckCircle2,
  RefreshCw,
  Send,
  ThumbsDown,
  ThumbsUp,
  XCircle,
} from "lucide-react";

export default function ReviewPage() {
  const [posts, setPosts] = useState<Post[]>([]);
  const [targets, setTargets] = useState<Target[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<number | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const [targetSel, setTargetSel] = useState<Record<number, Set<number>>>({});

  const refresh = async () => {
    setLoading(true);
    try {
      const [p, t] = await Promise.all([
        listPendingReview(),
        listTargets({ active_only: true }),
      ]);
      setPosts(p);
      setTargets(t);
      setDrafts((prev) => {
        // Seed empty drafts so "dirty" detection doesn't fire on every keystroke.
        const next = { ...prev };
        for (const post of p) {
          if (next[post.id] === undefined) next[post.id] = post.text;
        }
        return next;
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const approvedTargets = useMemo(
    () => targets.filter((t) => t.review_status === "approved" || t.active),
    [targets],
  );

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
      await refresh();
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
      await refresh();
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
      await refresh();
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
      await refresh();
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
    await refresh();
  };

  const onDelete = async (post: Post) => {
    if (!confirm("Delete this draft?")) return;
    await deletePost(post.id);
    await refresh();
  };

  return (
    <div className="space-y-4 max-w-6xl">
      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <CardTitle>Review Queue</CardTitle>
              <CardDescription>
                Posts waiting for your approval before they can be scheduled or
                published. Edit inline, regenerate, or bulk-approve.
              </CardDescription>
            </div>
            <div className="flex gap-2">
              <Button size="sm" variant="outline" onClick={refresh}>
                Refresh
              </Button>
              <Button
                size="sm"
                onClick={onBulkApprove}
                disabled={posts.length === 0}
              >
                {selected.size > 0
                  ? `Approve selected (${selected.size})`
                  : "Approve all"}
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="text-sm text-muted-foreground">Loading…</div>
          ) : posts.length === 0 ? (
            <div className="text-sm text-muted-foreground">
              Nothing to review. Either generation is off-queue or every post has
              been handled.
            </div>
          ) : (
            <div className="space-y-4">
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
                        <Badge variant="warning">pending_review</Badge>
                        <Badge variant="outline">{p.post_type}</Badge>
                        <span className="text-muted-foreground">
                          #{p.id} · {formatDate(p.created_at)}
                        </span>
                      </label>
                      <div className="flex gap-1">
                        <Button
                          size="icon"
                          variant="ghost"
                          onClick={() => onFeedback(p, "up")}
                          title="Thumbs up"
                        >
                          <ThumbsUp className="h-4 w-4" />
                        </Button>
                        <Button
                          size="icon"
                          variant="ghost"
                          onClick={() => onFeedback(p, "down")}
                          title="Thumbs down"
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
                          Publish to (optional — leave empty to just approve
                          into DRAFT):
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
                        onClick={() => onApprove(p, false)}
                        disabled={busy === p.id}
                      >
                        <CheckCircle2 className="h-4 w-4 mr-1" />
                        Approve → Draft
                      </Button>
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => onApprove(p, true)}
                        disabled={busy === p.id || tSet.size === 0}
                        title={
                          tSet.size === 0
                            ? "Pick at least one target to schedule"
                            : "Schedule in 5 minutes"
                        }
                      >
                        <Send className="h-4 w-4 mr-1" />
                        Approve → Schedule (+5min)
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
          )}
        </CardContent>
      </Card>
    </div>
  );
}
