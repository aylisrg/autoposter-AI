"use client";

import { use, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  ApiError,
  ContentPlan,
  MediaAsset,
  PlanSlot,
  PostType,
  attachMediaToSlot,
  chatPlan,
  createSlot,
  deleteSlot,
  generatePostFromSlot,
  getPlan,
  patchSlot,
  suggestMediaForSlot,
} from "@/lib/api";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8787";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { InfoPopover } from "@/components/ui/info-popover";
import { POST_TYPE_OPTIONS, labelForPostType } from "@/lib/post-types";
import {
  ArrowLeft,
  Loader2,
  Plus,
  Send,
  Sparkles,
  Trash2,
  Wand2,
} from "lucide-react";

const POST_TYPES = POST_TYPE_OPTIONS as {
  value: PostType;
  label: string;
  description?: string;
}[];

const SLOT_STATUS_LABEL: Record<string, string> = {
  planned: "just planned",
  drafted: "draft ready",
  scheduled: "scheduled",
  posted: "posted",
  skipped: "skipped",
};

const TYPE_COLORS: Record<PostType, string> = {
  informative: "bg-blue-500/20 border-blue-500/40 text-blue-700 dark:text-blue-300",
  soft_sell: "bg-emerald-500/20 border-emerald-500/40 text-emerald-700 dark:text-emerald-300",
  hard_sell: "bg-red-500/20 border-red-500/40 text-red-700 dark:text-red-300",
  engagement: "bg-purple-500/20 border-purple-500/40 text-purple-700 dark:text-purple-300",
  story: "bg-amber-500/20 border-amber-500/40 text-amber-700 dark:text-amber-300",
  motivational: "bg-orange-500/20 border-orange-500/40 text-orange-700 dark:text-orange-300",
  testimonial: "bg-teal-500/20 border-teal-500/40 text-teal-700 dark:text-teal-300",
  hot_take: "bg-pink-500/20 border-pink-500/40 text-pink-700 dark:text-pink-300",
  seasonal: "bg-cyan-500/20 border-cyan-500/40 text-cyan-700 dark:text-cyan-300",
};

function dayKey(iso: string): string {
  return new Date(iso).toISOString().slice(0, 10);
}

function buildDayBuckets(plan: ContentPlan): { date: Date; slots: PlanSlot[] }[] {
  const start = new Date(plan.start_date);
  const end = new Date(plan.end_date);
  start.setHours(0, 0, 0, 0);
  end.setHours(0, 0, 0, 0);
  const days: { date: Date; slots: PlanSlot[] }[] = [];
  for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
    const day = new Date(d);
    days.push({ date: day, slots: [] });
  }
  for (const slot of plan.slots) {
    const key = dayKey(slot.scheduled_for);
    const bucket = days.find(
      (b) => b.date.toISOString().slice(0, 10) === key,
    );
    if (bucket) bucket.slots.push(slot);
    else days.push({ date: new Date(slot.scheduled_for), slots: [slot] });
  }
  return days;
}

function toLocalDateTimeInput(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => n.toString().padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(
    d.getHours(),
  )}:${pad(d.getMinutes())}`;
}

export default function PlanDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const planId = Number(id);

  const [plan, setPlan] = useState<ContentPlan | null>(null);
  const [selectedSlot, setSelectedSlot] = useState<PlanSlot | null>(null);
  const [loading, setLoading] = useState(true);
  const [chatMessage, setChatMessage] = useState("");
  const [chatBusy, setChatBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [addingAt, setAddingAt] = useState<Date | null>(null);
  const [viewMode, setViewMode] = useState<"month" | "week" | "list">("month");
  const chatEndRef = useRef<HTMLDivElement>(null);

  const refresh = async () => {
    try {
      const p = await getPlan(planId);
      setPlan(p);
      if (selectedSlot) {
        const still = p.slots.find((s) => s.id === selectedSlot.id) ?? null;
        setSelectedSlot(still);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Load failed");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [planId]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [plan?.chat_history.length]);

  const days = useMemo(() => (plan ? buildDayBuckets(plan) : []), [plan]);

  const handleChatSend = async () => {
    if (!chatMessage.trim() || !plan) return;
    setChatBusy(true);
    setError(null);
    const msg = chatMessage;
    setChatMessage("");
    try {
      const res = await chatPlan(plan.id, msg);
      setPlan(res.plan);
    } catch (e) {
      setError(
        e instanceof ApiError
          ? `${e.status}: ${e.message}`
          : e instanceof Error
            ? e.message
            : "Chat failed",
      );
      setChatMessage(msg);
    } finally {
      setChatBusy(false);
    }
  };

  const handleSlotPatch = async (
    slotId: number,
    patch: Parameters<typeof patchSlot>[1],
  ) => {
    try {
      await patchSlot(slotId, patch);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Patch failed");
    }
  };

  const handleSlotDelete = async (slotId: number) => {
    if (!confirm("Delete this slot?")) return;
    await deleteSlot(slotId);
    setSelectedSlot(null);
    refresh();
  };

  const handleSlotAdd = async (data: {
    scheduled_for: string;
    post_type: PostType;
    topic_hint: string;
  }) => {
    if (!plan) return;
    await createSlot(plan.id, {
      scheduled_for: new Date(data.scheduled_for).toISOString(),
      post_type: data.post_type,
      topic_hint: data.topic_hint || null,
    });
    setAddingAt(null);
    refresh();
  };

  const handleGeneratePost = async (slotId: number) => {
    setError(null);
    try {
      const res = await generatePostFromSlot(slotId);
      setSelectedSlot(res.slot);
      await refresh();
    } catch (e) {
      setError(
        e instanceof ApiError
          ? `${e.status}: ${e.message}`
          : e instanceof Error
            ? e.message
            : "Generation failed",
      );
    }
  };

  const handleRegenerateSlot = async (slot: PlanSlot) => {
    if (!plan) return;
    setError(null);
    setChatBusy(true);
    const when = new Date(slot.scheduled_for).toLocaleString();
    const msg = `Regenerate a fresh post_type and topic_hint for the single slot scheduled around ${when}. Keep the same date and approximate time. Return the updated plan.`;
    try {
      const res = await chatPlan(plan.id, msg);
      setPlan(res.plan);
      const updated = res.plan.slots.find((s) => s.id === slot.id);
      if (updated) setSelectedSlot(updated);
    } catch (e) {
      setError(
        e instanceof ApiError
          ? `${e.status}: ${e.message}`
          : e instanceof Error
            ? e.message
            : "Regenerate failed",
      );
    } finally {
      setChatBusy(false);
    }
  };

  const handleDragStart = (e: React.DragEvent, slotId: number) => {
    e.dataTransfer.setData("slot-id", String(slotId));
  };

  const handleDrop = async (e: React.DragEvent, day: Date) => {
    e.preventDefault();
    const slotId = Number(e.dataTransfer.getData("slot-id"));
    if (!slotId || !plan) return;
    const slot = plan.slots.find((s) => s.id === slotId);
    if (!slot) return;
    // Keep hour/min, change date
    const existing = new Date(slot.scheduled_for);
    const next = new Date(day);
    next.setHours(existing.getHours(), existing.getMinutes(), 0, 0);
    await handleSlotPatch(slotId, { scheduled_for: next.toISOString() });
  };

  if (loading && !plan) {
    return <div className="p-6">Loading plan…</div>;
  }
  if (!plan) {
    return (
      <div className="p-6">
        <p>Plan not found.</p>
        <Link href="/plans" className="text-primary underline">
          Back to plans
        </Link>
      </div>
    );
  }

  return (
    <div className="flex h-[calc(100vh-3rem)]">
      {/* Left: calendar */}
      <div className="flex-1 p-6 overflow-y-auto">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <Link
              href="/plans"
              className="text-sm text-muted-foreground hover:text-foreground flex items-center gap-1 mb-1"
            >
              <ArrowLeft className="h-3 w-3" />
              Back
            </Link>
            <h1 className="text-xl font-bold flex items-center gap-1">
              {plan.name}
              <InfoPopover label="What's a slot?">
                A slot is a planned spot for a future post — a date, a time,
                and what angle to take. Nothing is drafted yet. Tap{" "}
                <span className="font-medium">Generate post</span> when
                you're ready.
              </InfoPopover>
            </h1>
            <div className="text-xs text-muted-foreground mt-1">
              {new Date(plan.start_date).toLocaleDateString()} –{" "}
              {new Date(plan.end_date).toLocaleDateString()} ·{" "}
              {plan.slots.length} slots · AI cost so far $
              {plan.generation_cost_usd.toFixed(4)}
            </div>
          </div>
          <Badge variant="outline">{plan.status}</Badge>
        </div>

        <ColorLegend />

        <div className="mb-4 flex gap-2">
          <Button
            variant={viewMode === "month" ? "default" : "outline"}
            size="sm"
            onClick={() => setViewMode("month")}
          >
            Month
          </Button>
          <Button
            variant={viewMode === "week" ? "default" : "outline"}
            size="sm"
            onClick={() => setViewMode("week")}
          >
            Week
          </Button>
          <Button
            variant={viewMode === "list" ? "default" : "outline"}
            size="sm"
            onClick={() => setViewMode("list")}
          >
            List
          </Button>
        </div>

        {error && (
          <div className="mb-4 rounded-md bg-destructive/10 text-destructive text-sm p-3">
            {error}
          </div>
        )}

        {viewMode === "list" ? (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
            {days.map(({ date, slots }) => (
              <DayCard
                key={date.toISOString()}
                date={date}
                slots={slots}
                onDrop={handleDrop}
                onAdd={() => {
                  const at = new Date(date);
                  at.setHours(10, 0, 0, 0);
                  setAddingAt(at);
                }}
                onSelect={setSelectedSlot}
                onDragStart={handleDragStart}
              />
            ))}
          </div>
        ) : viewMode === "week" ? (
          <WeekView
            days={days}
            onDrop={handleDrop}
            onAdd={(d) => {
              const at = new Date(d);
              at.setHours(10, 0, 0, 0);
              setAddingAt(at);
            }}
            onSelect={setSelectedSlot}
            onDragStart={handleDragStart}
          />
        ) : (
          <MonthView
            days={days}
            onDrop={handleDrop}
            onAdd={(d) => {
              const at = new Date(d);
              at.setHours(10, 0, 0, 0);
              setAddingAt(at);
            }}
            onSelect={setSelectedSlot}
            onDragStart={handleDragStart}
          />
        )}
      </div>

      {/* Right: inspector + chat */}
      <div className="w-[420px] border-l flex flex-col bg-card/40">
        {/* Inspector */}
        <div className="border-b p-4 max-h-[50%] overflow-y-auto">
          <div className="text-xs uppercase tracking-wide text-muted-foreground mb-2">
            Slot inspector
          </div>
          {addingAt ? (
            <AddSlotForm
              date={addingAt}
              onCancel={() => setAddingAt(null)}
              onSave={handleSlotAdd}
            />
          ) : selectedSlot ? (
            <SlotEditor
              slot={selectedSlot}
              onPatch={(p) => handleSlotPatch(selectedSlot.id, p)}
              onDelete={() => handleSlotDelete(selectedSlot.id)}
              onGenerate={() => handleGeneratePost(selectedSlot.id)}
              onRegenerate={() => handleRegenerateSlot(selectedSlot)}
              onAttached={() => refresh()}
            />
          ) : (
            <p className="text-sm text-muted-foreground">
              Tap a slot to edit it, or drag it to another day to reschedule.
            </p>
          )}
        </div>

        {/* Chat with Planner */}
        <div className="flex-1 flex flex-col">
          <div className="px-4 py-2 border-b text-xs uppercase tracking-wide text-muted-foreground flex items-center gap-2">
            <Wand2 className="h-3 w-3" />
            Chat with the planner
          </div>
          <div className="flex-1 overflow-y-auto p-4 space-y-2 text-sm">
            {plan.chat_history.length === 0 && (
              <p className="text-muted-foreground text-xs italic">
                Ask in plain English — "swap Wednesday for Thursday", "add
                two hot-takes next week", "space these out more".
              </p>
            )}
            {plan.chat_history.map((t, i) => (
              <div
                key={i}
                className={
                  t.role === "user"
                    ? "ml-8 rounded-md bg-primary/10 px-3 py-2"
                    : "mr-8 rounded-md bg-muted px-3 py-2"
                }
              >
                <div className="text-[10px] uppercase tracking-wide opacity-60 mb-0.5">
                  {t.role}
                </div>
                <div className="whitespace-pre-wrap">{t.content}</div>
              </div>
            ))}
            <div ref={chatEndRef} />
          </div>
          <div className="border-t p-3">
            <div className="flex gap-2">
              <Textarea
                rows={2}
                placeholder='e.g. "Move Thursday to Friday evening"'
                value={chatMessage}
                onChange={(e) => setChatMessage(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    handleChatSend();
                  }
                }}
                disabled={chatBusy}
              />
              <Button
                onClick={handleChatSend}
                disabled={chatBusy || !chatMessage.trim()}
                size="icon"
              >
                {chatBusy ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Send className="h-4 w-4" />
                )}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function ColorLegend() {
  return (
    <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
      <span>Colors by angle:</span>
      {POST_TYPES.map((t) => (
        <span
          key={t.value}
          className={`rounded border px-1.5 py-0.5 ${TYPE_COLORS[t.value as PostType]}`}
        >
          {t.label}
        </span>
      ))}
    </div>
  );
}


function DayCard({
  date,
  slots,
  onDrop,
  onAdd,
  onSelect,
  onDragStart,
}: {
  date: Date;
  slots: PlanSlot[];
  onDrop: (e: React.DragEvent, day: Date) => void;
  onAdd: () => void;
  onSelect: (s: PlanSlot) => void;
  onDragStart: (e: React.DragEvent, id: number) => void;
}) {
  return (
    <Card
      className="min-h-[140px]"
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => onDrop(e, date)}
    >
      <CardHeader className="p-3 pb-1 flex flex-row items-center justify-between">
        <div className="text-sm font-medium">
          {date.toLocaleDateString(undefined, {
            weekday: "short",
            month: "short",
            day: "numeric",
          })}
        </div>
        <Button variant="ghost" size="icon" className="h-6 w-6" onClick={onAdd}>
          <Plus className="h-3 w-3" />
        </Button>
      </CardHeader>
      <CardContent className="p-3 pt-1 space-y-1">
        {slots.length === 0 && (
          <div className="text-xs text-muted-foreground italic">
            Nothing planned. Drag a slot or tap + to add.
          </div>
        )}
        {slots.map((slot) => (
          <SlotChip
            key={slot.id}
            slot={slot}
            onSelect={onSelect}
            onDragStart={onDragStart}
          />
        ))}
      </CardContent>
    </Card>
  );
}

function SlotChip({
  slot,
  onSelect,
  onDragStart,
}: {
  slot: PlanSlot;
  onSelect: (s: PlanSlot) => void;
  onDragStart: (e: React.DragEvent, id: number) => void;
}) {
  return (
    <button
      draggable
      onDragStart={(e) => onDragStart(e, slot.id)}
      onClick={() => onSelect(slot)}
      className={`w-full text-left text-xs rounded border px-2 py-1.5 cursor-grab hover:shadow-sm transition ${TYPE_COLORS[slot.post_type]}`}
    >
      <div className="font-medium">
        {new Date(slot.scheduled_for).toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
        })}
        {" · "}
        {POST_TYPES.find((t) => t.value === slot.post_type)?.label ?? slot.post_type}
      </div>
      {slot.topic_hint && (
        <div className="text-[11px] opacity-80 line-clamp-2 mt-0.5">
          {slot.topic_hint}
        </div>
      )}
      {slot.status !== "planned" && (
        <Badge variant="secondary" className="mt-1 text-[10px]">
          {SLOT_STATUS_LABEL[slot.status] ?? slot.status}
        </Badge>
      )}
    </button>
  );
}

function WeekView({
  days,
  onDrop,
  onAdd,
  onSelect,
  onDragStart,
}: {
  days: { date: Date; slots: PlanSlot[] }[];
  onDrop: (e: React.DragEvent, day: Date) => void;
  onAdd: (d: Date) => void;
  onSelect: (s: PlanSlot) => void;
  onDragStart: (e: React.DragEvent, id: number) => void;
}) {
  // Show first 7 days or group into weeks; for simplicity take consecutive days as weeks
  const weeks: typeof days[] = [];
  for (let i = 0; i < days.length; i += 7) {
    weeks.push(days.slice(i, i + 7));
  }
  return (
    <div className="space-y-6">
      {weeks.map((week, wi) => (
        <div key={wi} className="grid grid-cols-7 gap-1">
          {week.map(({ date, slots }) => (
            <div
              key={date.toISOString()}
              className="border rounded min-h-[120px] p-1 bg-card"
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => onDrop(e, date)}
            >
              <div className="text-[10px] font-medium flex justify-between">
                <span>
                  {date.toLocaleDateString(undefined, { weekday: "short", day: "numeric" })}
                </span>
                <button
                  className="text-muted-foreground hover:text-foreground"
                  onClick={() => onAdd(date)}
                >
                  +
                </button>
              </div>
              <div className="space-y-0.5 mt-1">
                {slots.map((slot) => (
                  <SlotChip
                    key={slot.id}
                    slot={slot}
                    onSelect={onSelect}
                    onDragStart={onDragStart}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

function MonthView({
  days,
  onDrop,
  onAdd,
  onSelect,
  onDragStart,
}: {
  days: { date: Date; slots: PlanSlot[] }[];
  onDrop: (e: React.DragEvent, day: Date) => void;
  onAdd: (d: Date) => void;
  onSelect: (s: PlanSlot) => void;
  onDragStart: (e: React.DragEvent, id: number) => void;
}) {
  if (days.length === 0) return null;
  const first = days[0].date;
  const startPad = first.getDay(); // 0 Sun
  const padded: ({ date: Date; slots: PlanSlot[] } | null)[] = [
    ...Array(startPad).fill(null),
    ...days,
  ];
  while (padded.length % 7 !== 0) padded.push(null);
  const weeks: typeof padded[] = [];
  for (let i = 0; i < padded.length; i += 7) {
    weeks.push(padded.slice(i, i + 7));
  }
  const weekdays = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  return (
    <div>
      <div className="grid grid-cols-7 gap-1 mb-1 text-xs text-muted-foreground">
        {weekdays.map((w) => (
          <div key={w} className="text-center font-medium">
            {w}
          </div>
        ))}
      </div>
      <div className="space-y-1">
        {weeks.map((week, wi) => (
          <div key={wi} className="grid grid-cols-7 gap-1">
            {week.map((cell, ci) =>
              cell ? (
                <div
                  key={cell.date.toISOString()}
                  className="border rounded min-h-[100px] p-1 bg-card text-xs"
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={(e) => onDrop(e, cell.date)}
                >
                  <div className="flex justify-between font-medium">
                    <span>{cell.date.getDate()}</span>
                    <button
                      className="text-muted-foreground hover:text-foreground text-[10px]"
                      onClick={() => onAdd(cell.date)}
                    >
                      +
                    </button>
                  </div>
                  <div className="space-y-0.5 mt-1">
                    {cell.slots.slice(0, 3).map((slot) => (
                      <div
                        key={slot.id}
                        draggable
                        onDragStart={(e) => onDragStart(e, slot.id)}
                        onClick={() => onSelect(slot)}
                        className={`truncate rounded px-1 py-0.5 cursor-grab text-[10px] ${TYPE_COLORS[slot.post_type]}`}
                      >
                        {new Date(slot.scheduled_for).toLocaleTimeString([], {
                          hour: "2-digit",
                          minute: "2-digit",
                        })}{" "}
                        {POST_TYPES.find((t) => t.value === slot.post_type)?.label ?? slot.post_type}
                      </div>
                    ))}
                    {cell.slots.length > 3 && (
                      <div className="text-[10px] text-muted-foreground">
                        +{cell.slots.length - 3} more
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                <div key={`empty-${wi}-${ci}`} className="min-h-[100px]" />
              ),
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function SlotEditor({
  slot,
  onPatch,
  onDelete,
  onGenerate,
  onRegenerate,
  onAttached,
}: {
  slot: PlanSlot;
  onPatch: (p: Parameters<typeof patchSlot>[1]) => void;
  onDelete: () => void;
  onGenerate: () => void;
  onRegenerate: () => void;
  onAttached: () => void;
}) {
  const [when, setWhen] = useState(toLocalDateTimeInput(slot.scheduled_for));
  const [postType, setPostType] = useState(slot.post_type);
  const [topicHint, setTopicHint] = useState(slot.topic_hint ?? "");
  const [notes, setNotes] = useState(slot.notes ?? "");
  const [busy, setBusy] = useState(false);
  const [suggestions, setSuggestions] = useState<
    { asset: MediaAsset; score: number }[]
  >([]);
  const [loadingSuggestions, setLoadingSuggestions] = useState(false);

  useEffect(() => {
    setWhen(toLocalDateTimeInput(slot.scheduled_for));
    setPostType(slot.post_type);
    setTopicHint(slot.topic_hint ?? "");
    setNotes(slot.notes ?? "");
    setLoadingSuggestions(true);
    suggestMediaForSlot(slot.id, 3)
      .then(setSuggestions)
      .catch(() => setSuggestions([]))
      .finally(() => setLoadingSuggestions(false));
  }, [slot.id]);

  const handleAttach = async (assetId: number) => {
    await attachMediaToSlot(assetId, slot.id);
    onAttached();
  };

  const save = async () => {
    setBusy(true);
    try {
      await onPatch({
        scheduled_for: new Date(when).toISOString(),
        post_type: postType,
        topic_hint: topicHint || null,
        notes: notes || null,
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-3">
      <div>
        <Label>When</Label>
        <Input
          type="datetime-local"
          value={when}
          onChange={(e) => setWhen(e.target.value)}
        />
      </div>
      <div>
        <Label>Post type</Label>
        <Select
          value={postType}
          onChange={(e) => setPostType(e.target.value as PostType)}
        >
          {POST_TYPES.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </Select>
      </div>
      <div>
        <Label>Topic hint</Label>
        <Textarea
          rows={3}
          value={topicHint}
          onChange={(e) => setTopicHint(e.target.value)}
        />
      </div>
      <div>
        <Label>Notes</Label>
        <Textarea
          rows={2}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
        />
      </div>
      {slot.rationale && (
        <div className="text-xs text-muted-foreground italic">
          Why the planner chose this: {slot.rationale}
        </div>
      )}
      {slot.post_id && (
        <div className="text-xs">
          Draft ready:{" "}
          <Link href="/queue" className="text-primary underline">
            open in Posts
          </Link>
        </div>
      )}
      <div className="border-t pt-3 mt-3">
        <Label className="text-xs flex items-center gap-1">
          Image ideas
          <InfoPopover>
            Autoposter scores images in your Media Library against this
            slot's topic hint and suggests the best three. Tap one to
            attach it to the future post.
          </InfoPopover>
        </Label>
        {loadingSuggestions ? (
          <p className="text-xs text-muted-foreground">Looking…</p>
        ) : suggestions.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            {slot.media_asset_id
              ? "Image already attached."
              : "No matches yet. Tag a few images in the Library first."}
          </p>
        ) : (
          <div className="grid grid-cols-3 gap-2 mt-1">
            {suggestions.map(({ asset, score }) => (
              <button
                key={asset.id}
                type="button"
                onClick={() => handleAttach(asset.id)}
                className={`rounded overflow-hidden border hover:ring-2 hover:ring-primary transition ${
                  slot.media_asset_id === asset.id ? "ring-2 ring-primary" : ""
                }`}
                title={`${asset.ai_caption ?? asset.filename} — score ${score}`}
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={`${API_BASE}/static/${asset.local_path}`}
                  alt=""
                  className="w-full aspect-square object-cover"
                />
              </button>
            ))}
          </div>
        )}
      </div>
      <div className="flex gap-2 flex-wrap">
        <Button onClick={save} disabled={busy} size="sm">
          Save
        </Button>
        <Button
          onClick={onGenerate}
          disabled={busy || !!slot.post_id}
          size="sm"
          variant="secondary"
          title={slot.post_id ? "Already drafted" : "Draft with AI (~$0.01)"}
        >
          <Sparkles className="h-3 w-3" />
          {slot.post_id ? "Drafted" : "Draft with AI"}
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={onRegenerate}
          disabled={busy}
        >
          <Wand2 className="h-3 w-3" />
          Regenerate
        </Button>
        <Button
          onClick={onDelete}
          disabled={busy}
          size="sm"
          variant="destructive"
        >
          <Trash2 className="h-3 w-3" />
          Delete
        </Button>
      </div>
    </div>
  );
}

function AddSlotForm({
  date,
  onCancel,
  onSave,
}: {
  date: Date;
  onCancel: () => void;
  onSave: (data: {
    scheduled_for: string;
    post_type: PostType;
    topic_hint: string;
  }) => Promise<void>;
}) {
  const [when, setWhen] = useState(toLocalDateTimeInput(date.toISOString()));
  const [postType, setPostType] = useState<PostType>("informative");
  const [topicHint, setTopicHint] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    try {
      await onSave({ scheduled_for: when, post_type: postType, topic_hint: topicHint });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-3">
      <div className="text-sm font-medium">New slot</div>
      <div>
        <Label>When</Label>
        <Input
          type="datetime-local"
          value={when}
          onChange={(e) => setWhen(e.target.value)}
        />
      </div>
      <div>
        <Label>Post type</Label>
        <Select
          value={postType}
          onChange={(e) => setPostType(e.target.value as PostType)}
        >
          {POST_TYPES.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </Select>
      </div>
      <div>
        <Label>Topic hint</Label>
        <Textarea
          rows={3}
          placeholder="What angle should the writer take?"
          value={topicHint}
          onChange={(e) => setTopicHint(e.target.value)}
        />
      </div>
      <div className="flex gap-2">
        <Button onClick={submit} disabled={busy} size="sm">
          Add
        </Button>
        <Button onClick={onCancel} size="sm" variant="outline">
          Cancel
        </Button>
      </div>
    </div>
  );
}
