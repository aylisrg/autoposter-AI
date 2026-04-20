"use client";

import { useEffect, useState } from "react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import {
  deletePost,
  listPosts,
  sendFeedback,
  type Post,
  type PostStatus,
} from "@/lib/api";
import { formatDate } from "@/lib/utils";
import { ThumbsDown, ThumbsUp, Trash2 } from "lucide-react";

const STATUS_VARIANT: Record<PostStatus, BadgeProps["variant"]> = {
  draft: "outline",
  pending_review: "warning",
  scheduled: "secondary",
  posting: "warning",
  posted: "success",
  failed: "destructive",
  skipped: "outline",
};

export default function QueuePage() {
  const [posts, setPosts] = useState<Post[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<PostStatus | "all">("all");

  const refresh = async () => {
    setLoading(true);
    try {
      const data = await listPosts(filter === "all" ? undefined : filter);
      setPosts(data);
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
      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <CardTitle>Queue</CardTitle>
              <CardDescription>
                All posts — drafts, scheduled, posted, failed.
              </CardDescription>
            </div>
            <div className="flex gap-1 text-sm">
              {(
                [
                  "all",
                  "draft",
                  "scheduled",
                  "posting",
                  "posted",
                  "failed",
                ] as const
              ).map((f) => (
                <Button
                  key={f}
                  size="sm"
                  variant={filter === f ? "default" : "outline"}
                  onClick={() => setFilter(f)}
                >
                  {f}
                </Button>
              ))}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="text-sm text-muted-foreground">Loading…</div>
          ) : posts.length === 0 ? (
            <div className="text-sm text-muted-foreground">
              Nothing here. Generate a post on the Compose page.
            </div>
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
                        {p.status}
                      </Badge>
                      <Badge variant="outline">{p.post_type}</Badge>
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
                        title="Thumbs up"
                      >
                        <ThumbsUp className="h-4 w-4" />
                      </Button>
                      <Button
                        size="icon"
                        variant="ghost"
                        onClick={() => onFeedback(p.id, "down")}
                        title="Thumbs down"
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
                        Variants ({p.variants.length}):
                      </div>
                      {p.variants.map((v) => (
                        <div
                          key={v.id}
                          className="flex items-center gap-2 flex-wrap"
                        >
                          <Badge variant={STATUS_VARIANT[v.status]}>
                            {v.status}
                          </Badge>
                          <span className="text-muted-foreground">
                            target #{v.target_id}
                          </span>
                          {v.external_post_id && (
                            <a
                              href={v.external_post_id}
                              target="_blank"
                              rel="noreferrer"
                              className="underline text-blue-600 break-all"
                            >
                              open
                            </a>
                          )}
                          {v.next_retry_at && v.status === "scheduled" && (
                            <span className="text-muted-foreground">
                              retry #{v.attempt_count} at{" "}
                              {formatDate(v.next_retry_at)}
                            </span>
                          )}
                          {v.error && (
                            <span className="text-destructive">
                              {v.error}
                            </span>
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
