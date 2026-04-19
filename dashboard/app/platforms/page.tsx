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
  addManualCredential,
  deletePlatformCredential,
  getMetaOAuthUrl,
  listPlatformCredentials,
  type PlatformCredential,
} from "@/lib/api";
import { formatDate } from "@/lib/utils";
import { Link2, Plus, Trash2 } from "lucide-react";

export default function PlatformsPage() {
  const [creds, setCreds] = useState<PlatformCredential[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [manualOpen, setManualOpen] = useState(false);
  const [form, setForm] = useState<{
    platform_id: "instagram" | "threads";
    account_id: string;
    username: string;
    access_token: string;
  }>({
    platform_id: "instagram",
    account_id: "",
    username: "",
    access_token: "",
  });

  const refresh = async () => {
    setLoading(true);
    try {
      const rows = await listPlatformCredentials();
      setCreds(rows);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load credentials");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const startOAuth = async () => {
    try {
      const { url } = await getMetaOAuthUrl();
      window.location.href = url;
    } catch (e) {
      setError(e instanceof Error ? e.message : "OAuth URL failed");
    }
  };

  const saveManual = async () => {
    try {
      await addManualCredential({
        platform_id: form.platform_id,
        account_id: form.account_id.trim(),
        username: form.username.trim() || undefined,
        access_token: form.access_token.trim(),
      });
      setForm({
        platform_id: "instagram",
        account_id: "",
        username: "",
        access_token: "",
      });
      setManualOpen(false);
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    }
  };

  const remove = async (id: number) => {
    if (!confirm("Disconnect this account?")) return;
    await deletePlatformCredential(id);
    refresh();
  };

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Platforms</h1>
        <p className="text-muted-foreground">
          Connect Instagram and Threads via Meta OAuth. Facebook Groups live in
          the extension settings.
        </p>
      </div>

      {error && (
        <Card className="border-destructive">
          <CardContent className="pt-6 text-sm text-destructive">
            {error}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Connect Meta</CardTitle>
          <CardDescription>
            Logs into Facebook, lists your Pages, and stores a long-lived token
            for the first Instagram Business account it finds.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex gap-2">
          <Button onClick={startOAuth}>
            <Link2 className="mr-2 h-4 w-4" /> Connect via OAuth
          </Button>
          <Button variant="outline" onClick={() => setManualOpen((v) => !v)}>
            <Plus className="mr-2 h-4 w-4" />
            {manualOpen ? "Cancel manual" : "Paste token manually"}
          </Button>
        </CardContent>
      </Card>

      {manualOpen && (
        <Card>
          <CardHeader>
            <CardTitle>Manual credential</CardTitle>
            <CardDescription>
              For CLI users who already obtained a long-lived token elsewhere
              (Graph API Explorer, Postman, etc).
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 md:grid-cols-2">
            <div>
              <Label>Platform</Label>
              <select
                className="w-full rounded-md border bg-background p-2 text-sm"
                value={form.platform_id}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    platform_id: e.target.value as "instagram" | "threads",
                  }))
                }
              >
                <option value="instagram">Instagram</option>
                <option value="threads">Threads</option>
              </select>
            </div>
            <div>
              <Label>Account ID (numeric)</Label>
              <Input
                value={form.account_id}
                onChange={(e) =>
                  setForm((f) => ({ ...f, account_id: e.target.value }))
                }
                placeholder="17841400000000000"
              />
            </div>
            <div>
              <Label>Username (optional)</Label>
              <Input
                value={form.username}
                onChange={(e) =>
                  setForm((f) => ({ ...f, username: e.target.value }))
                }
              />
            </div>
            <div className="md:col-span-2">
              <Label>Long-lived access token</Label>
              <Input
                value={form.access_token}
                onChange={(e) =>
                  setForm((f) => ({ ...f, access_token: e.target.value }))
                }
                placeholder="EAAG..."
              />
            </div>
            <div className="md:col-span-2">
              <Button
                onClick={saveManual}
                disabled={!form.account_id || !form.access_token}
              >
                Save
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Connected accounts</CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : creds.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No connected accounts yet.
            </p>
          ) : (
            <div className="space-y-2">
              {creds.map((c) => (
                <div
                  key={c.id}
                  className="flex items-center justify-between rounded-lg border p-3 text-sm"
                >
                  <div className="flex flex-col">
                    <div className="flex items-center gap-2">
                      <Badge variant="outline">{c.platform_id}</Badge>
                      <span className="font-medium">
                        {c.username || c.account_id}
                      </span>
                    </div>
                    <span className="text-xs text-muted-foreground">
                      id {c.account_id} · updated {formatDate(c.updated_at)}
                    </span>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => remove(c.id)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
