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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  bulkReviewTargets,
  clusterTargets,
  createTarget,
  deleteTarget,
  discoverTargets,
  listTargets,
  patchTarget,
  scoreTargets,
  syncTargets,
  type Target,
  type TargetReviewStatus,
} from "@/lib/api";
import { formatDate } from "@/lib/utils";
import {
  Check,
  Compass,
  Layers,
  Loader2,
  RefreshCw,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";

type StatusFilter = "all" | TargetReviewStatus;

const STATUS_COLORS: Record<TargetReviewStatus, string> = {
  pending: "bg-amber-100 text-amber-800 border-amber-200",
  approved: "bg-green-100 text-green-800 border-green-200",
  rejected: "bg-red-100 text-red-800 border-red-200",
};

export default function TargetsPage() {
  const [targets, setTargets] = useState<Target[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [filter, setFilter] = useState<StatusFilter>("all");
  const [listFilter, setListFilter] = useState<string>("all");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [form, setForm] = useState({ external_id: "", name: "", tags: "" });

  const refresh = async () => {
    setLoading(true);
    try {
      setTargets(await listTargets());
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const lists = useMemo(() => {
    const set = new Set<string>();
    for (const t of targets) if (t.list_name) set.add(t.list_name);
    return [...set].sort();
  }, [targets]);

  const filtered = useMemo(() => {
    return targets.filter((t) => {
      if (filter !== "all" && t.review_status !== filter) return false;
      if (listFilter === "__none__" && t.list_name) return false;
      if (listFilter !== "all" && listFilter !== "__none__" && t.list_name !== listFilter)
        return false;
      return true;
    });
  }, [targets, filter, listFilter]);

  const allSelected = filtered.length > 0 && filtered.every((t) => selected.has(t.id));
  const toggleAll = () => {
    if (allSelected) {
      const next = new Set(selected);
      for (const t of filtered) next.delete(t.id);
      setSelected(next);
    } else {
      const next = new Set(selected);
      for (const t of filtered) next.add(t.id);
      setSelected(next);
    }
  };
  const toggleOne = (id: number) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  };

  const onCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setMessage(null);
    try {
      await createTarget({
        platform_id: "facebook",
        external_id: form.external_id.trim(),
        name: form.name.trim() || form.external_id.trim(),
        tags: form.tags.split(",").map((t) => t.trim()).filter(Boolean),
        active: true,
      });
      setForm({ external_id: "", name: "", tags: "" });
      await refresh();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    }
  };

  const run = async (key: string, fn: () => Promise<string | void>) => {
    setBusy(key);
    setMessage(null);
    try {
      const result = await fn();
      if (result) setMessage(result);
      await refresh();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const onSync = () =>
    run("sync", async () => {
      const synced = await syncTargets();
      return `Synced ${synced.length} joined groups.`;
    });

  const onDiscover = () =>
    run("discover", async () => {
      const r = await discoverTargets();
      return `Discovered ${r.created} new groups (${r.updated} updated).`;
    });

  const onScore = () =>
    run("score", async () => {
      const ids = selected.size > 0 ? [...selected] : [];
      const r = await scoreTargets(ids);
      return `Scored ${r.scored.length} targets (cost $${r.cost_usd.toFixed(4)}).`;
    });

  const onCluster = () =>
    run("cluster", async () => {
      const r = await clusterTargets();
      return `Organized into ${r.lists.length} lists (cost $${r.cost_usd.toFixed(4)}).`;
    });

  const onBulkReview = (status: TargetReviewStatus) =>
    run("bulk-" + status, async () => {
      if (selected.size === 0) return "Select targets first.";
      await bulkReviewTargets([...selected], status);
      setSelected(new Set());
      return `Marked ${selected.size} targets as ${status}.`;
    });

  const onToggle = async (t: Target) => {
    await patchTarget(t.id, { active: !t.active });
    await refresh();
  };

  const onDelete = async (id: number) => {
    if (!confirm("Delete this target?")) return;
    await deleteTarget(id);
    await refresh();
  };

  return (
    <div className="space-y-4 max-w-6xl">
      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <CardTitle>Targets</CardTitle>
              <CardDescription>
                FB groups, pages, subreddits. Use <strong>Sync</strong> for your joined
                groups, <strong>Discover</strong> to pull suggested groups,{" "}
                <strong>Score</strong> to ask the AI which are a good fit, and{" "}
                <strong>Cluster</strong> to organize approved ones into segments.
              </CardDescription>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" onClick={onSync} disabled={busy === "sync"}>
                <RefreshCw
                  className={"h-4 w-4 " + (busy === "sync" ? "animate-spin" : "")}
                />
                Sync joined
              </Button>
              <Button variant="outline" onClick={onDiscover} disabled={busy === "discover"}>
                <Compass
                  className={"h-4 w-4 " + (busy === "discover" ? "animate-pulse" : "")}
                />
                Discover suggested
              </Button>
              <Button variant="outline" onClick={onScore} disabled={busy === "score"}>
                {busy === "score" ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Sparkles className="h-4 w-4" />
                )}
                Score {selected.size > 0 ? `(${selected.size})` : "pending"}
              </Button>
              <Button variant="outline" onClick={onCluster} disabled={busy === "cluster"}>
                {busy === "cluster" ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Layers className="h-4 w-4" />
                )}
                Cluster approved
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <form
            onSubmit={onCreate}
            className="grid grid-cols-1 md:grid-cols-4 gap-3 items-end"
          >
            <div className="space-y-1.5 md:col-span-2">
              <Label>External URL or ID</Label>
              <Input
                required
                placeholder="https://www.facebook.com/groups/123456789"
                value={form.external_id}
                onChange={(e) => setForm({ ...form, external_id: e.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <Label>Display name</Label>
              <Input
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <Label>Tags (comma sep)</Label>
              <div className="flex gap-2">
                <Input
                  value={form.tags}
                  onChange={(e) => setForm({ ...form, tags: e.target.value })}
                  placeholder="eu, saas"
                />
                <Button type="submit">Add</Button>
              </div>
            </div>
          </form>

          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="text-muted-foreground">Filter:</span>
            {(["all", "pending", "approved", "rejected"] as const).map((s) => (
              <button
                key={s}
                onClick={() => setFilter(s)}
                className={`px-2 py-1 rounded-md border text-xs ${
                  filter === s ? "bg-primary text-primary-foreground" : "bg-background"
                }`}
              >
                {s}
              </button>
            ))}
            {lists.length > 0 && (
              <>
                <span className="text-muted-foreground ml-3">List:</span>
                <select
                  value={listFilter}
                  onChange={(e) => setListFilter(e.target.value)}
                  className="h-8 px-2 text-xs rounded-md border bg-background"
                >
                  <option value="all">All</option>
                  <option value="__none__">No list</option>
                  {lists.map((l) => (
                    <option key={l} value={l}>
                      {l}
                    </option>
                  ))}
                </select>
              </>
            )}
            {selected.size > 0 && (
              <div className="ml-auto flex gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => onBulkReview("approved")}
                  disabled={busy?.startsWith("bulk-")}
                >
                  <Check className="h-3 w-3" />
                  Approve {selected.size}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => onBulkReview("rejected")}
                  disabled={busy?.startsWith("bulk-")}
                >
                  <X className="h-3 w-3" />
                  Reject {selected.size}
                </Button>
              </div>
            )}
          </div>

          {message && <div className="text-sm text-muted-foreground">{message}</div>}

          <div className="rounded-md border overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b bg-muted/50">
                <tr className="text-left">
                  <th className="py-2 px-3 w-8">
                    <input
                      type="checkbox"
                      checked={allSelected}
                      onChange={toggleAll}
                      aria-label="Select all filtered"
                    />
                  </th>
                  <th className="py-2 px-3">Name</th>
                  <th className="py-2 px-3">Score</th>
                  <th className="py-2 px-3">List</th>
                  <th className="py-2 px-3">Status</th>
                  <th className="py-2 px-3">Members</th>
                  <th className="py-2 px-3">Source</th>
                  <th className="py-2 px-3">Active</th>
                  <th className="py-2 px-3 w-12"></th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr>
                    <td colSpan={9} className="p-4 text-muted-foreground">
                      Loading…
                    </td>
                  </tr>
                ) : filtered.length === 0 ? (
                  <tr>
                    <td colSpan={9} className="p-4 text-muted-foreground">
                      No targets match this filter.
                    </td>
                  </tr>
                ) : (
                  filtered.map((t) => (
                    <tr key={t.id} className="border-b last:border-0 align-top">
                      <td className="py-2 px-3">
                        <input
                          type="checkbox"
                          checked={selected.has(t.id)}
                          onChange={() => toggleOne(t.id)}
                        />
                      </td>
                      <td className="py-2 px-3 max-w-[320px]">
                        <div className="font-medium truncate" title={t.name}>
                          {t.name}
                        </div>
                        {t.description_snippet && (
                          <div
                            className="text-xs text-muted-foreground line-clamp-2"
                            title={t.description_snippet}
                          >
                            {t.description_snippet}
                          </div>
                        )}
                        {t.ai_reasoning && (
                          <div
                            className="text-xs text-primary/80 italic mt-1 line-clamp-2"
                            title={t.ai_reasoning}
                          >
                            AI: {t.ai_reasoning}
                          </div>
                        )}
                        <a
                          className="text-[11px] text-muted-foreground underline"
                          href={t.external_id.startsWith("http") ? t.external_id : undefined}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {t.external_id}
                        </a>
                      </td>
                      <td className="py-2 px-3">
                        {t.relevance_score != null ? (
                          <Badge
                            variant="outline"
                            className={
                              t.relevance_score >= 70
                                ? "border-green-400 text-green-800"
                                : t.relevance_score >= 40
                                  ? "border-amber-400 text-amber-800"
                                  : "border-red-300 text-red-700"
                            }
                          >
                            {t.relevance_score}
                          </Badge>
                        ) : (
                          <span className="text-xs text-muted-foreground">—</span>
                        )}
                      </td>
                      <td className="py-2 px-3 text-xs">
                        {t.list_name ?? <span className="text-muted-foreground">—</span>}
                      </td>
                      <td className="py-2 px-3">
                        <Badge
                          variant="outline"
                          className={STATUS_COLORS[t.review_status]}
                        >
                          {t.review_status}
                        </Badge>
                      </td>
                      <td className="py-2 px-3 text-xs">
                        {t.member_count?.toLocaleString() ?? "—"}
                      </td>
                      <td className="py-2 px-3 text-xs text-muted-foreground">
                        {t.source}
                        <div>{formatDate(t.created_at)}</div>
                      </td>
                      <td className="py-2 px-3">
                        <button onClick={() => onToggle(t)} className="cursor-pointer">
                          <Badge variant={t.active ? "success" : "outline"}>
                            {t.active ? "on" : "off"}
                          </Badge>
                        </button>
                      </td>
                      <td className="py-2 px-3">
                        <Button
                          size="icon"
                          variant="ghost"
                          onClick={() => onDelete(t.id)}
                          title="Delete"
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
