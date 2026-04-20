"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import {
  ApiError,
  ContentPlan,
  createEmptyPlan,
  deletePlan,
  generatePlan,
  listPlans,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { PageHeader } from "@/components/ui/page-header";
import { InfoPopover } from "@/components/ui/info-popover";
import { EmptyState } from "@/components/ui/empty-state";
import { CalendarDays, Loader2, Sparkles, Trash2 } from "lucide-react";

function todayISO(offsetDays = 0): string {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  d.setHours(0, 0, 0, 0);
  return d.toISOString().slice(0, 10);
}

export default function PlansListPage() {
  const router = useRouter();
  const [plans, setPlans] = useState<ContentPlan[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [goal, setGoal] = useState("");
  const [startDate, setStartDate] = useState(todayISO());
  const [endDate, setEndDate] = useState(todayISO(14));
  const [error, setError] = useState<string | null>(null);

  const refresh = async () => {
    setLoading(true);
    try {
      setPlans(await listPlans());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load plans");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const handleGenerate = async (useAI: boolean) => {
    setError(null);
    if (!name.trim()) {
      setError("Give the calendar a name first.");
      return;
    }
    setCreating(true);
    try {
      const payload = {
        name: name.trim(),
        goal: goal.trim() || null,
        start_date: new Date(startDate + "T00:00:00Z").toISOString(),
        end_date: new Date(endDate + "T23:59:59Z").toISOString(),
      };
      const plan = useAI
        ? await generatePlan(payload)
        : await createEmptyPlan(payload);
      router.push(`/plans/${plan.id}`);
    } catch (e) {
      setError(
        e instanceof ApiError
          ? `${e.status}: ${e.message}`
          : e instanceof Error
            ? e.message
            : "Unknown error",
      );
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm("Delete this calendar? All its slots are removed.")) return;
    await deletePlan(id);
    refresh();
  };

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <PageHeader
        title="Calendar"
        description="A calendar of upcoming posts. Describe a goal and the Planner AI fills in dates, post angles, and hints. You can edit every slot by hand afterwards."
        icon={CalendarDays}
      />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            Make a new calendar
            <InfoPopover label="How does this work?">
              You pick a date range and describe what you want to achieve.
              The Planner agent fills the calendar with post angles spread
              across the days — you review and edit before any of them
              actually get drafted into posts.
            </InfoPopover>
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <Label htmlFor="name">Name</Label>
            <Input
              id="name"
              placeholder='e.g. "July growth push"'
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div>
            <Label htmlFor="goal">Goal (optional but helps a lot)</Label>
            <Textarea
              id="goal"
              rows={2}
              placeholder="Drive sign-ups for the new pricing tier launching July 10."
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="start">Start</Label>
              <Input
                id="start"
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
              />
            </div>
            <div>
              <Label htmlFor="end">End</Label>
              <Input
                id="end"
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
              />
            </div>
          </div>
          {error && (
            <div className="rounded-md bg-destructive/10 text-destructive text-sm p-3">
              {error}
            </div>
          )}
          <div className="flex gap-2 items-center flex-wrap">
            <Button onClick={() => handleGenerate(true)} disabled={creating}>
              {creating ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Sparkles className="h-4 w-4" />
              )}
              Let the AI plan it
              <span className="ml-1.5 text-xs opacity-80">~$0.05</span>
            </Button>
            <Button
              variant="outline"
              onClick={() => handleGenerate(false)}
              disabled={creating}
            >
              Start with an empty calendar
            </Button>
          </div>
        </CardContent>
      </Card>

      <div>
        <h2 className="text-lg font-semibold mb-3">Your calendars</h2>
        {loading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : plans.length === 0 ? (
          <EmptyState
            icon={CalendarDays}
            title="No calendars yet"
            description="Make your first one above — it's the fastest way to fill a month with posts."
          />
        ) : (
          <div className="space-y-2">
            {plans.map((p) => (
              <Card key={p.id} className="hover:bg-accent/40 transition-colors">
                <div className="flex items-center p-4">
                  <Link href={`/plans/${p.id}`} className="flex-1">
                    <div className="flex items-center gap-3 flex-wrap">
                      <span className="font-medium">{p.name}</span>
                      <Badge variant="outline">{p.status}</Badge>
                      <Badge variant="secondary">
                        {p.slots.length} post
                        {p.slots.length === 1 ? "" : "s"} planned
                      </Badge>
                    </div>
                    <div className="text-xs text-muted-foreground mt-1">
                      {new Date(p.start_date).toLocaleDateString()} –{" "}
                      {new Date(p.end_date).toLocaleDateString()}
                    </div>
                    {p.goal && (
                      <div className="text-sm text-muted-foreground mt-1 line-clamp-1">
                        {p.goal}
                      </div>
                    )}
                  </Link>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDelete(p.id);
                    }}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
