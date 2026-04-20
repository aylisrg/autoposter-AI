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
  refreshPlatformCredential,
  runExtensionSmoke,
  type ExtensionSmokeReport,
  type PlatformCredential,
} from "@/lib/api";
import { formatDate } from "@/lib/utils";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Link2,
  Plus,
  RefreshCw,
  Trash2,
  XCircle,
} from "lucide-react";

// Meta tokens live ~60 days. We surface the state in three buckets so the
// user knows whether to worry: >14 days = safe (green), 1-14 = refresh soon
// (amber), <=0 = already expired, publishes will 401 (red).
type ExpiryBucket = "safe" | "soon" | "expired" | "unknown";

function expiryBucket(days: number | null): ExpiryBucket {
  if (days == null) return "unknown";
  if (days <= 0) return "expired";
  if (days <= 14) return "soon";
  return "safe";
}

function expiryBadgeVariant(
  bucket: ExpiryBucket,
): "outline" | "success" | "warning" | "destructive" {
  switch (bucket) {
    case "safe":
      return "success";
    case "soon":
      return "warning";
    case "expired":
      return "destructive";
    default:
      return "outline";
  }
}

function expiryLabel(days: number | null): string {
  if (days == null) return "expiry unknown";
  if (days <= 0) return `expired ${-days}d ago`;
  if (days === 1) return "expires tomorrow";
  return `expires in ${days}d`;
}

export default function PlatformsPage() {
  const [creds, setCreds] = useState<PlatformCredential[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [manualOpen, setManualOpen] = useState(false);
  const [refreshingId, setRefreshingId] = useState<number | null>(null);
  const [smokeReport, setSmokeReport] = useState<ExtensionSmokeReport | null>(
    null,
  );
  const [smokeError, setSmokeError] = useState<string | null>(null);
  const [smokeRunning, setSmokeRunning] = useState(false);
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

  const refreshToken = async (id: number) => {
    setRefreshingId(id);
    try {
      await refreshPlatformCredential(id);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Refresh failed");
    } finally {
      setRefreshingId(null);
    }
  };

  const runSmoke = async () => {
    setSmokeRunning(true);
    setSmokeError(null);
    setSmokeReport(null);
    try {
      const { report } = await runExtensionSmoke();
      setSmokeReport(report);
    } catch (e) {
      setSmokeError(e instanceof Error ? e.message : "Smoke test failed");
    } finally {
      setSmokeRunning(false);
    }
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
          <CardTitle>Facebook extension health</CardTitle>
          <CardDescription>
            Probes whether the content script can still find FB's composer,
            post button, and comment editor. Run this on a{" "}
            <code>facebook.com/groups/...</code> tab when publishes start
            silently failing — FB changes its DOM periodically.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <Button onClick={runSmoke} disabled={smokeRunning} variant="outline">
            <Activity
              className={`mr-2 h-4 w-4 ${smokeRunning ? "animate-pulse" : ""}`}
            />
            {smokeRunning ? "Probing…" : "Run smoke test"}
          </Button>
          {smokeError && (
            <p className="text-sm text-destructive">{smokeError}</p>
          )}
          {smokeReport && <SmokeReportView report={smokeReport} />}
        </CardContent>
      </Card>

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
              {creds.map((c) => {
                const bucket = expiryBucket(c.days_until_expiry);
                const isMeta =
                  c.platform_id === "instagram" ||
                  c.platform_id === "threads";
                return (
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
                        {isMeta && (
                          <Badge variant={expiryBadgeVariant(bucket)}>
                            {expiryLabel(c.days_until_expiry)}
                          </Badge>
                        )}
                      </div>
                      <span className="text-xs text-muted-foreground">
                        id {c.account_id} · updated {formatDate(c.updated_at)}
                      </span>
                    </div>
                    <div className="flex items-center gap-1">
                      {isMeta && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => refreshToken(c.id)}
                          disabled={refreshingId === c.id}
                          title="Refresh Meta token now"
                        >
                          <RefreshCw
                            className={`h-4 w-4 ${
                              refreshingId === c.id ? "animate-spin" : ""
                            }`}
                          />
                        </Button>
                      )}
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => remove(c.id)}
                      >
                        <Trash2 className="h-4 w-4" />
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

function SmokeReportView({ report }: { report: ExtensionSmokeReport }) {
  const checks: Array<{ label: string; value: boolean; critical?: boolean }> = [
    { label: "On a group page", value: report.is_group_page, critical: true },
    { label: "Logged in", value: report.is_logged_in, critical: true },
    {
      label: "No checkpoint / captcha",
      value: !report.checkpoint_detected,
      critical: true,
    },
    { label: "Composer trigger found", value: report.composer_trigger, critical: true },
    { label: "Composer editor when open", value: report.composer_editor_when_open },
    { label: "Post button when open", value: report.post_button_when_open },
    {
      label: "Photo/Video button when open",
      value: report.photo_video_button_when_open,
    },
    { label: "Comment button on article", value: report.comment_button_on_article },
    { label: "Comment editor on article", value: report.comment_editor_on_article },
  ];
  return (
    <div className="space-y-2 rounded-lg border p-3 text-sm">
      <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
        <span>locale: {report.locale}</span>
        <span>·</span>
        <span>articles: {report.articles_detected}</span>
        <span>·</span>
        <span>groups: {report.groups_detected}</span>
      </div>
      <ul className="space-y-1">
        {checks.map((c) => (
          <li key={c.label} className="flex items-center gap-2">
            {c.value ? (
              <CheckCircle2 className="h-4 w-4 text-green-600" />
            ) : c.critical ? (
              <XCircle className="h-4 w-4 text-destructive" />
            ) : (
              <AlertTriangle className="h-4 w-4 text-amber-500" />
            )}
            <span className={c.value ? "" : c.critical ? "text-destructive" : ""}>
              {c.label}
            </span>
          </li>
        ))}
      </ul>
      {report.warnings.length > 0 && (
        <div className="mt-2 rounded-md border border-amber-500/40 bg-amber-500/5 p-2 text-xs">
          <div className="mb-1 font-medium text-amber-600">Warnings</div>
          <ul className="list-disc space-y-0.5 pl-5">
            {report.warnings.map((w) => (
              <li key={w} className="font-mono">
                {w}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
