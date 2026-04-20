"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  getDashboardOverview,
  type DashboardOverview,
  type NextStep,
  type SetupBlock,
  type ActivityBlock,
  type RecentFailure,
} from "@/lib/api";
import { formatDate } from "@/lib/utils";
import {
  AlertTriangle,
  ArrowRight,
  Briefcase,
  CheckCircle2,
  CircleDashed,
  Clock,
  FileEdit,
  Link2,
  ListChecks,
  RefreshCw,
  Send,
  Users,
  XCircle,
} from "lucide-react";

export default function HomePage() {
  const [data, setData] = useState<DashboardOverview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const d = await getDashboardOverview();
        if (!cancelled) {
          setData(d);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e));
        }
      }
    };
    tick();
    const id = setInterval(tick, 15_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  if (error) {
    return (
      <div className="p-6">
        <Card className="border-destructive">
          <CardContent className="pt-6 text-sm text-destructive">
            {error}
          </CardContent>
        </Card>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        Loading dashboard…
      </div>
    );
  }

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Home</h1>
        <p className="text-muted-foreground">
          What autoposter is doing right now, and the one thing we need from
          you next. Updates every 15 seconds.
        </p>
      </div>

      <NextStepCard step={data.next_step} />

      <div className="grid gap-4 md:grid-cols-2">
        <SetupCard setup={data.setup} />
        <ActivityCard activity={data.activity} />
      </div>

      {data.activity.recent_failures.length > 0 && (
        <FailuresCard failures={data.activity.recent_failures} />
      )}
    </div>
  );
}

function NextStepCard({ step }: { step: NextStep }) {
  const allSet = step.id === "all_set";
  const needsAttention = step.id === "resolve_failures";
  return (
    <Card
      className={
        needsAttention
          ? "border-destructive/60"
          : allSet
          ? "border-green-600/40"
          : "border-primary/40"
      }
    >
      <CardHeader>
        <div className="flex items-center gap-2">
          {needsAttention ? (
            <AlertTriangle className="h-5 w-5 text-destructive" />
          ) : allSet ? (
            <CheckCircle2 className="h-5 w-5 text-green-600" />
          ) : (
            <CircleDashed className="h-5 w-5 text-primary" />
          )}
          <CardTitle>
            {allSet ? "Everything running" : "Next step"}
          </CardTitle>
        </div>
        <CardDescription className="text-base">
          <span className="font-medium text-foreground">{step.title}</span>
          <span className="block pt-1">{step.description}</span>
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Link href={step.cta_href}>
          <Button variant={needsAttention ? "destructive" : "default"}>
            {step.cta_label}
            <ArrowRight className="ml-2 h-4 w-4" />
          </Button>
        </Link>
      </CardContent>
    </Card>
  );
}

function SetupCard({ setup }: { setup: SetupBlock }) {
  const items: Array<{
    label: string;
    ok: boolean;
    note?: string;
    href: string;
    icon: React.ComponentType<{ className?: string }>;
  }> = [
    {
      label: "Chrome extension",
      ok: setup.extension_connected,
      note: setup.extension_connected ? "connected" : "install it",
      href: "/platforms",
      icon: Link2,
    },
    {
      label: "Your business",
      ok: setup.has_business_profile,
      note: setup.has_business_profile ? "ready" : "tell the AI who you are",
      href: "/profile",
      icon: Briefcase,
    },
    {
      label: "Accounts linked",
      ok: setup.platforms_connected > 0,
      note:
        setup.platforms_expiring_soon > 0
          ? `${setup.platforms_connected} linked · ${setup.platforms_expiring_soon} expiring soon`
          : setup.platforms_connected === 0
          ? "link at least one"
          : `${setup.platforms_connected} linked`,
      href: "/platforms",
      icon: Link2,
    },
    {
      label: "Destinations",
      ok: setup.targets_active > 0,
      note:
        setup.targets_active === 0
          ? "add a group or account"
          : `${setup.targets_active} active`,
      href: "/destinations",
      icon: Users,
    },
    {
      label: "Calendar",
      ok: setup.plans_active > 0,
      note:
        setup.plans_active === 0
          ? "none running"
          : `${setup.plans_active} active`,
      href: "/plans",
      icon: ListChecks,
    },
  ];
  return (
    <Card>
      <CardHeader>
        <CardTitle>Setup</CardTitle>
        <CardDescription>
          Everything autoposter needs to work end-to-end. Green checks mean
          you're good; click any row to jump there.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="space-y-2 text-sm">
          {items.map((it) => {
            const Icon = it.icon;
            return (
              <li key={it.label}>
                <Link
                  href={it.href}
                  className="flex items-center justify-between rounded-md px-2 py-1.5 hover:bg-accent/60"
                >
                  <div className="flex items-center gap-2">
                    {it.ok ? (
                      <CheckCircle2 className="h-4 w-4 text-green-600" />
                    ) : (
                      <XCircle className="h-4 w-4 text-muted-foreground" />
                    )}
                    <Icon className="h-4 w-4 text-muted-foreground" />
                    <span>{it.label}</span>
                  </div>
                  <span className="text-xs text-muted-foreground">
                    {it.note}
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      </CardContent>
    </Card>
  );
}

function ActivityCard({ activity }: { activity: ActivityBlock }) {
  const hasPublishing = activity.publishing_now !== null;
  const hasNext = activity.next_scheduled !== null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Activity</CardTitle>
        <CardDescription>
          What's queued, what's going out right now, what needs your eye.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {hasPublishing && activity.publishing_now && (
          <div className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/5 p-2">
            <Send className="mt-0.5 h-4 w-4 text-amber-600" />
            <div className="flex-1">
              <div className="font-medium">Publishing now</div>
              <div className="text-xs text-muted-foreground">
                {activity.publishing_now.platform_id} ·{" "}
                {activity.publishing_now.target_name}
              </div>
            </div>
          </div>
        )}
        {hasNext && activity.next_scheduled && (
          <div className="flex items-start gap-2 rounded-md border p-2">
            <Clock className="mt-0.5 h-4 w-4 text-muted-foreground" />
            <div className="flex-1">
              <div className="font-medium">
                Next at {formatDate(activity.next_scheduled.scheduled_for)}
              </div>
              <div className="text-xs text-muted-foreground">
                {activity.next_scheduled.platform_id} ·{" "}
                {activity.next_scheduled.target_name}
              </div>
            </div>
          </div>
        )}
        {!hasPublishing && !hasNext && (
          <div className="rounded-md border border-dashed p-3 text-center text-xs text-muted-foreground">
            Nothing running, nothing scheduled.
          </div>
        )}
        <div className="grid grid-cols-2 gap-2 pt-2 text-xs">
          <StatLink
            href="/queue?status=pending_review"
            icon={FileEdit}
            count={activity.pending_review}
            label="need approval"
          />
          <StatLink
            href="/queue?status=scheduled"
            icon={ListChecks}
            count={activity.scheduled_total}
            label="scheduled"
          />
          <StatLink
            href="/queue?status=posted"
            icon={Send}
            count={activity.posted_today}
            label="posted today"
          />
          <StatLink
            href="/queue?status=failed"
            icon={AlertTriangle}
            count={activity.failed_last_24h}
            label="failed"
            tone={activity.failed_last_24h > 0 ? "warn" : undefined}
          />
        </div>
      </CardContent>
    </Card>
  );
}

function StatLink({
  href,
  icon: Icon,
  count,
  label,
  tone,
}: {
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  count: number;
  label: string;
  tone?: "warn";
}) {
  return (
    <Link
      href={href}
      className="flex items-center gap-2 rounded-md border px-2 py-1.5 hover:bg-accent/60"
    >
      <Icon
        className={`h-4 w-4 ${
          tone === "warn" ? "text-amber-600" : "text-muted-foreground"
        }`}
      />
      <span className="font-mono tabular-nums">{count}</span>
      <span className="text-muted-foreground">{label}</span>
    </Link>
  );
}

function FailuresCard({ failures }: { failures: RecentFailure[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Recent failures</CardTitle>
        <CardDescription>
          <Badge variant="destructive" className="mr-1">
            needs you
          </Badge>{" "}
          means the system will keep failing until you do something (join a
          group, solve a Facebook security check, reconnect an account).{" "}
          <Badge variant="warning" className="mr-1">
            will retry
          </Badge>{" "}
          means it'll try again on its own.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="space-y-2 text-sm">
          {failures.map((f) => (
            <li
              key={f.variant_id}
              className="flex items-start justify-between rounded-md border p-2"
            >
              <div className="flex-1 pr-3">
                <div className="flex items-center gap-2">
                  {f.kind === "permanent" ? (
                    <Badge variant="destructive">needs you</Badge>
                  ) : (
                    <Badge variant="warning">will retry</Badge>
                  )}
                  <span className="font-medium">
                    {f.platform_id} · {f.target_name}
                  </span>
                </div>
                <p className="mt-1 font-mono text-xs text-muted-foreground break-words">
                  {f.error}
                </p>
                {f.kind === "permanent" &&
                  f.error.includes("not_a_group_member") && (
                    <p className="mt-1 text-xs">
                      This account isn't a member of the group. Open it in
                      Facebook, click{" "}
                      <span className="font-medium">Join group</span>, wait
                      for approval if required, then re-queue from the queue
                      page.
                    </p>
                  )}
              </div>
              <Link
                href={`/queue?variant=${f.variant_id}`}
                className="text-xs text-primary hover:underline"
              >
                Open
              </Link>
            </li>
          ))}
        </ul>
        <div className="mt-3 flex justify-end">
          <Link href="/queue?status=failed">
            <Button variant="outline" size="sm">
              <RefreshCw className="mr-2 h-4 w-4" />
              Open queue
            </Button>
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}
