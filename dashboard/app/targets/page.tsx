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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  createTarget,
  deleteTarget,
  listTargets,
  patchTarget,
  syncTargets,
  type Target,
} from "@/lib/api";
import { formatDate } from "@/lib/utils";
import { Trash2, RefreshCw } from "lucide-react";

export default function TargetsPage() {
  const [targets, setTargets] = useState<Target[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
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

  const onCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setMessage(null);
    try {
      await createTarget({
        platform_id: "facebook",
        external_id: form.external_id.trim(),
        name: form.name.trim() || form.external_id.trim(),
        tags: form.tags
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean),
        active: true,
      });
      setForm({ external_id: "", name: "", tags: "" });
      await refresh();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    }
  };

  const onSync = async () => {
    setSyncing(true);
    setMessage(null);
    try {
      const synced = await syncTargets();
      setMessage(`Synced ${synced.length} targets from extension.`);
      await refresh();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setSyncing(false);
    }
  };

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
    <div className="space-y-4 max-w-5xl">
      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-4">
            <div>
              <CardTitle>Targets</CardTitle>
              <CardDescription>
                Places to post to. For FB, use the group URL
                (https://www.facebook.com/groups/...).
              </CardDescription>
            </div>
            <Button
              variant="outline"
              onClick={onSync}
              disabled={syncing}
              type="button"
            >
              <RefreshCw
                className={"h-4 w-4 " + (syncing ? "animate-spin" : "")}
              />
              {syncing ? "Syncing…" : "Sync from extension"}
            </Button>
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
                onChange={(e) =>
                  setForm({ ...form, external_id: e.target.value })
                }
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
                  onChange={(e) =>
                    setForm({ ...form, tags: e.target.value })
                  }
                  placeholder="eu, saas"
                />
                <Button type="submit">Add</Button>
              </div>
            </div>
          </form>
          {message && (
            <div className="text-sm text-muted-foreground">{message}</div>
          )}
          <div className="rounded-md border">
            <table className="w-full text-sm">
              <thead className="border-b bg-muted/50">
                <tr className="text-left">
                  <th className="py-2 px-3">Name</th>
                  <th className="py-2 px-3">Platform</th>
                  <th className="py-2 px-3">External ID</th>
                  <th className="py-2 px-3">Tags</th>
                  <th className="py-2 px-3">Status</th>
                  <th className="py-2 px-3">Added</th>
                  <th className="py-2 px-3 w-20"></th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr>
                    <td colSpan={7} className="p-4 text-muted-foreground">
                      Loading…
                    </td>
                  </tr>
                ) : targets.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="p-4 text-muted-foreground">
                      No targets yet. Add one above or sync from the
                      extension.
                    </td>
                  </tr>
                ) : (
                  targets.map((t) => (
                    <tr key={t.id} className="border-b last:border-0">
                      <td className="py-2 px-3 font-medium">{t.name}</td>
                      <td className="py-2 px-3">{t.platform_id}</td>
                      <td
                        className="py-2 px-3 truncate max-w-[240px]"
                        title={t.external_id}
                      >
                        {t.external_id}
                      </td>
                      <td className="py-2 px-3">
                        <div className="flex flex-wrap gap-1">
                          {t.tags.map((tag) => (
                            <Badge key={tag} variant="secondary">
                              {tag}
                            </Badge>
                          ))}
                        </div>
                      </td>
                      <td className="py-2 px-3">
                        <button
                          onClick={() => onToggle(t)}
                          className="cursor-pointer"
                        >
                          <Badge
                            variant={t.active ? "success" : "outline"}
                          >
                            {t.active ? "active" : "inactive"}
                          </Badge>
                        </button>
                      </td>
                      <td className="py-2 px-3 text-muted-foreground">
                        {formatDate(t.created_at)}
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
