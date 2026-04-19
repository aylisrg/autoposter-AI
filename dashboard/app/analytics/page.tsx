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
import { Badge } from "@/components/ui/badge";
import {
  applyProposal,
  collectMetricsNow,
  generateAnalystReport,
  getAnalyticsSummary,
  getTopPerformers,
  listAnalystReports,
  listProposals,
  refreshFewShotStore,
  rejectProposal,
  type AnalystReport,
  type AnalyticsSummary,
  type OptimizerProposal,
  type TopPerformer,
} from "@/lib/api";
import { formatDate } from "@/lib/utils";
import {
  BarChart3,
  CheckCircle2,
  RefreshCw,
  Sparkles,
  TrendingDown,
  TrendingUp,
  XCircle,
} from "lucide-react";

export default function AnalyticsPage() {
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [top, setTop] = useState<TopPerformer[]>([]);
  const [bottom, setBottom] = useState<TopPerformer[]>([]);
  const [reports, setReports] = useState<AnalystReport[]>([]);
  const [proposals, setProposals] = useState<OptimizerProposal[]>([]);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const refresh = async () => {
    setLoading(true);
    try {
      const [s, t, b, r, p] = await Promise.all([
        getAnalyticsSummary(7),
        getTopPerformers(7, 5, false),
        getTopPerformers(7, 5, true),
        listAnalystReports(),
        listProposals(),
      ]);
      setSummary(s);
      setTop(t);
      setBottom(b);
      setReports(r);
      setProposals(p);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const collect = async () => {
    setWorking("collect");
    setMsg(null);
    try {
      const r = await collectMetricsNow();
      setMsg(
        `Collected: touched ${r.variants_touched} variants, ${r.rows_created} new rows.`,
      );
      await refresh();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setWorking(null);
    }
  };

  const runReport = async () => {
    setWorking("report");
    setMsg(null);
    try {
      const r = await generateAnalystReport({ days: 7 });
      setMsg(`New report #${r.id} — cost $${r.cost_usd.toFixed(4)}.`);
      await refresh();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setWorking(null);
    }
  };

  const refreshFewShot = async () => {
    setWorking("fewshot");
    setMsg(null);
    try {
      const r = await refreshFewShotStore();
      setMsg(`Few-shot store: ${r.inserted} examples.`);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setWorking(null);
    }
  };

  const onApply = async (id: number) => {
    await applyProposal(id);
    await refresh();
  };

  const onReject = async (id: number) => {
    await rejectProposal(id);
    await refresh();
  };

  if (loading) return <div>Loading…</div>;

  return (
    <div className="space-y-6 max-w-6xl">
      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <CardTitle className="flex items-center gap-2">
                <BarChart3 className="h-5 w-5" />
                Analytics — Last 7 days
              </CardTitle>
              <CardDescription>
                KPIs + AI-driven insights. Analyst runs weekly (Sunday 21:00
                UTC). You can trigger it manually here.
              </CardDescription>
            </div>
            <div className="flex gap-2">
              <Button size="sm" variant="outline" onClick={collect} disabled={!!working}>
                <RefreshCw className="h-4 w-4 mr-1" />
                Collect metrics
              </Button>
              <Button size="sm" variant="outline" onClick={refreshFewShot} disabled={!!working}>
                Refresh few-shot
              </Button>
              <Button size="sm" onClick={runReport} disabled={!!working}>
                <Sparkles className="h-4 w-4 mr-1" />
                Run Analyst
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {msg && (
            <div className="text-sm mb-3 rounded bg-muted px-3 py-2">{msg}</div>
          )}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <Kpi label="Posts" value={summary?.posts ?? 0} />
            <Kpi label="Likes" value={summary?.likes ?? 0} />
            <Kpi label="Comments" value={summary?.comments ?? 0} />
            <Kpi label="Shares" value={summary?.shares ?? 0} />
            <Kpi
              label="Avg score"
              value={(summary?.avg_engagement_score ?? 0).toFixed(1)}
            />
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <TrendingUp className="h-5 w-5" /> Top performers
            </CardTitle>
            <CardDescription>Highest engagement_score in window.</CardDescription>
          </CardHeader>
          <CardContent>
            <PerformersList items={top} empty="No posts with metrics yet." />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <TrendingDown className="h-5 w-5" /> Bottom performers
            </CardTitle>
            <CardDescription>Post types / angles to reconsider.</CardDescription>
          </CardHeader>
          <CardContent>
            <PerformersList items={bottom} empty="Nothing collected yet." />
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Optimizer proposals</CardTitle>
          <CardDescription>
            Small safe changes (posting window, ratios) may auto-apply when
            confidence ≥ 0.75. Others wait for you.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {proposals.length === 0 ? (
            <div className="text-sm text-muted-foreground">No proposals.</div>
          ) : (
            <div className="space-y-2">
              {proposals.map((p) => (
                <div
                  key={p.id}
                  className="rounded border p-3 flex items-start justify-between gap-3 flex-wrap"
                >
                  <div className="flex-1 min-w-0 space-y-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <Badge
                        variant={
                          p.status === "applied"
                            ? "success"
                            : p.status === "rejected"
                              ? "outline"
                              : "warning"
                        }
                      >
                        {p.status}
                      </Badge>
                      {p.auto_applied && (
                        <Badge variant="secondary">auto</Badge>
                      )}
                      <span className="font-medium">{p.field}</span>
                      <span className="text-xs text-muted-foreground">
                        confidence {(p.confidence * 100).toFixed(0)}%
                      </span>
                    </div>
                    <div className="text-sm text-muted-foreground">
                      {p.reasoning}
                    </div>
                    <div className="text-xs">
                      <code className="bg-muted px-1 rounded">
                        {JSON.stringify(p.current_value)}
                      </code>
                      {" → "}
                      <code className="bg-muted px-1 rounded">
                        {JSON.stringify(p.proposed_value)}
                      </code>
                    </div>
                  </div>
                  {p.status === "pending" && (
                    <div className="flex gap-1">
                      <Button
                        size="sm"
                        onClick={() => onApply(p.id)}
                        disabled={!!working}
                      >
                        <CheckCircle2 className="h-4 w-4 mr-1" />
                        Apply
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => onReject(p.id)}
                        disabled={!!working}
                      >
                        <XCircle className="h-4 w-4 mr-1" />
                        Reject
                      </Button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Recent Analyst reports</CardTitle>
        </CardHeader>
        <CardContent>
          {reports.length === 0 ? (
            <div className="text-sm text-muted-foreground">
              No reports yet. Click "Run Analyst" to generate one.
            </div>
          ) : (
            <div className="space-y-3">
              {reports.map((r) => (
                <div key={r.id} className="rounded border p-3 space-y-2">
                  <div className="flex items-center gap-2 text-xs text-muted-foreground flex-wrap">
                    <span>#{r.id}</span>
                    <span>
                      {formatDate(r.period_start)} → {formatDate(r.period_end)}
                    </span>
                    <span>${r.cost_usd.toFixed(4)}</span>
                    <span>{r.model}</span>
                  </div>
                  <div className="text-sm whitespace-pre-wrap">{r.summary}</div>
                  {r.body.patterns && r.body.patterns.length > 0 && (
                    <details className="text-xs">
                      <summary className="cursor-pointer">
                        {r.body.patterns.length} patterns
                      </summary>
                      <ul className="list-disc pl-5 pt-1 space-y-0.5">
                        {r.body.patterns.map((line, i) => (
                          <li key={i}>{line}</li>
                        ))}
                      </ul>
                    </details>
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

function Kpi({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded border p-3 bg-card">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-2xl font-semibold">{value}</div>
    </div>
  );
}

function PerformersList({
  items,
  empty,
}: {
  items: TopPerformer[];
  empty: string;
}) {
  if (items.length === 0)
    return <div className="text-sm text-muted-foreground">{empty}</div>;
  return (
    <div className="space-y-2">
      {items.map((p) => (
        <div key={p.post_id} className="rounded border p-2 bg-card">
          <div className="flex items-center gap-2 text-xs">
            <Badge variant="outline">{p.post_type}</Badge>
            <span className="font-medium">
              score {p.engagement_score.toFixed(1)}
            </span>
            {p.posted_at && (
              <span className="text-muted-foreground">
                {formatDate(p.posted_at)}
              </span>
            )}
          </div>
          <div className="text-sm mt-1 line-clamp-2">{p.text_preview}</div>
        </div>
      ))}
    </div>
  );
}
