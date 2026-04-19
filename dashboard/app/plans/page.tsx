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
      setError("Give the plan a name.");
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
    if (!confirm("Delete plan? All slots will be removed.")) return;
    await deletePlan(id);
    refresh();
  };

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <CalendarDays className="h-6 w-6" />
          Content Plans
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Let the Planner agent propose a calendar, then edit it in the calendar
          view.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>New plan</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <Label htmlFor="name">Name</Label>
            <Input
              id="name"
              placeholder="e.g. July growth"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div>
            <Label htmlFor="goal">Goal (optional)</Label>
            <Textarea
              id="goal"
              rows={2}
              placeholder="Drive sign-ups for the new product launch."
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
          <div className="flex gap-2">
            <Button
              onClick={() => handleGenerate(true)}
              disabled={creating}
            >
              {creating ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Sparkles className="h-4 w-4" />
              )}
              Generate with AI
            </Button>
            <Button
              variant="outline"
              onClick={() => handleGenerate(false)}
              disabled={creating}
            >
              Create empty
            </Button>
          </div>
        </CardContent>
      </Card>

      <div>
        <h2 className="text-lg font-semibold mb-3">Existing plans</h2>
        {loading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : plans.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No plans yet. Create one above.
          </p>
        ) : (
          <div className="space-y-2">
            {plans.map((p) => (
              <Card key={p.id} className="hover:bg-accent/40 transition-colors">
                <div className="flex items-center p-4">
                  <Link href={`/plans/${p.id}`} className="flex-1">
                    <div className="flex items-center gap-3">
                      <span className="font-medium">{p.name}</span>
                      <Badge variant="outline">{p.status}</Badge>
                      <Badge variant="secondary">
                        {p.slots.length} slot{p.slots.length === 1 ? "" : "s"}
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
