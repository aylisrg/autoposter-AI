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
import { PageHeader } from "@/components/ui/page-header";
import { InfoPopover } from "@/components/ui/info-popover";
import {
  addManualCredential,
  deletePlatformCredential,
  getMetaOAuthUrl,
  getStatus,
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
  Chrome,
  Link2,
  Plus,
  RefreshCw,
  Trash2,
  XCircle,
} from "lucide-react";

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
  const [extensionConnected, setExtensionConnected] = useState<boolean | null>(
    null,
  );
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
      const [rows, status] = await Promise.all([
        listPlatformCredentials(),
        getStatus().catch(() => null),
      ]);
      setCreds(rows);
      setExtensionConnected(status?.extension_connected ?? null);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load credentials");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
    const id = setInterval(() => {
      getStatus()
        .then((s) => setExtensionConnected(s.extension_connected))
        .catch(() => {});
    }, 10_000);
    return () => clearInterval(id);
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
      <PageHeader
        title="Connections"
        description="How autoposter talks to each network. Instagram and Threads go through Meta's official API. Facebook Groups need the Chrome extension — Facebook has no API for groups."
        icon={Link2}
      />

      {error && (
        <Card className="border-destructive">
          <CardContent className="pt-6 text-sm text-destructive">
            {error}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-2">
            <div>
              <CardTitle className="flex items-center gap-2">
                <Chrome className="h-5 w-5" />
                Chrome extension
              </CardTitle>
              <CardDescription>
                Required for Facebook Groups. It signs in as you in a real
                browser tab and posts through the normal UI — Facebook has no
                official API for group posts.
              </CardDescription>
            </div>
            {extensionConnected === true ? (
              <Badge variant="success">connected</Badge>
            ) : extensionConnected === false ? (
              <Badge variant="warning">not detected</Badge>
            ) : (
              <Badge variant="outline">checking…</Badge>
            )}
          </div>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          {extensionConnected === false && (
            <ol className="list-decimal space-y-1 pl-5 text-muted-foreground">
              <li>
                Build it once:{" "}
                <code className="rounded bg-muted px-1">
                  cd extension &amp;&amp; npm install &amp;&amp; npm run build
                </code>
              </li>
              <li>
                Open{" "}
                <code className="rounded bg-muted px-1">
                  chrome://extensions
                </code>{" "}
                → enable <span className="font-medium">Developer mode</span> →{" "}
                <span className="font-medium">Load unpacked</span> → pick{" "}
                <code className="rounded bg-muted px-1">extension/dist</code>.
              </li>
              <li>
                Log in to Facebook in the same Chrome profile. The extension
                opens a persistent WebSocket back to this server.
              </li>
            </ol>
          )}
          {extensionConnected === true && (
            <p className="text-muted-foreground">
              The extension is online and ready to post. If a publish fails
              silently, run the smoke test below — Facebook tweaks its DOM
              every few weeks.
            </p>
          )}
          <div className="flex gap-2">
            <Button onClick={runSmoke} disabled={smokeRunning} variant="outline">
              <Activity
                className={`mr-2 h-4 w-4 ${smokeRunning ? "animate-pulse" : ""}`}
              />
              {smokeRunning ? "Probing…" : "Run health check"}
            </Button>
          </div>
          {smokeError && (
            <p className="text-sm text-destructive">{smokeError}</p>
          )}
          {smokeReport && <SmokeReportView report={smokeReport} />}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Meta (Instagram &amp; Threads)</CardTitle>
          <CardDescription>
            One-click sign-in with Facebook. We read which Pages you manage,
            find the Instagram Business account linked to each, and save a
            long-lived token so autoposter can publish for ~60 days before
            you're asked to sign in again.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          <Button onClick={startOAuth}>
            <Link2 className="mr-2 h-4 w-4" /> Sign in with Facebook
          </Button>
          <Button variant="outline" onClick={() => setManualOpen((v) => !v)}>
            <Plus className="mr-2 h-4 w-4" />
            {manualOpen ? "Cancel" : "I already have a token"}
          </Button>
        </CardContent>
      </Card>

      {manualOpen && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              Paste a token by hand
              <InfoPopover label="What's a long-lived token?">
                A long-lived Meta token is the ~60-day access key that
                autoposter uses to publish. You normally get one via the
                Sign-in button; paste it here only if you generated one in
                Graph API Explorer or Postman yourself.
              </InfoPopover>
            </CardTitle>
            <CardDescription>
              Skip this unless you already generated a long-lived token
              elsewhere.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 md:grid-cols-2">
            <div>
              <Label>Network</Label>
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
              <div className="flex items-center gap-1">
                <Label>Account ID</Label>
                <InfoPopover label="What's an Account ID?">
                  The numeric ID of the Instagram Business account or Threads
                  profile (e.g. <code>17841400000000000</code>). Find it in
                  Graph API Explorer under <em>/me/accounts</em>.
                </InfoPopover>
              </div>
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
                placeholder="@yourhandle"
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
          <CardTitle>Signed-in accounts</CardTitle>
          <CardDescription>
            Meta tokens last ~60 days. Autoposter refreshes them in the
            background; the badge tells you when the next renewal is due.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : creds.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Nothing connected yet. Use the Meta sign-in above.
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
                          title="Renew token now"
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
                        title="Disconnect"
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
  // Plain-English labels for each DOM probe — avoid "composer trigger".
  const checks: Array<{ label: string; value: boolean; critical?: boolean }> =
    [
      { label: "You're on a group page", value: report.is_group_page, critical: true },
      { label: "You're signed in to Facebook", value: report.is_logged_in, critical: true },
      {
        label: "No security check / captcha in the way",
        value: !report.checkpoint_detected,
        critical: true,
      },
    ];
  if (report.is_group_page && report.is_group_member !== null) {
    checks.push({
      label: "You're a member of this group",
      value: report.is_group_member,
      critical: true,
    });
  }
  checks.push(
    { label: "Found the \"Write something…\" box", value: report.composer_trigger, critical: true },
    { label: "Text editor opens when clicked", value: report.composer_editor_when_open },
    { label: "Post button appears", value: report.post_button_when_open },
    {
      label: "Photo / video button appears",
      value: report.photo_video_button_when_open,
    },
    { label: "Comment button on a post", value: report.comment_button_on_article },
    { label: "Comment editor on a post", value: report.comment_editor_on_article },
  );
  return (
    <div className="space-y-2 rounded-lg border p-3 text-sm">
      <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
        <span>locale: {report.locale}</span>
        <span>·</span>
        <span>posts visible: {report.articles_detected}</span>
        <span>·</span>
        <span>groups in sidebar: {report.groups_detected}</span>
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
