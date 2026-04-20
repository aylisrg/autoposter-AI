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
import { EmptyState } from "@/components/ui/empty-state";
import { InfoPopover } from "@/components/ui/info-popover";
import {
  activatePause,
  addBlackout,
  deleteBlackout,
  getHumanizer,
  getPauseStatus,
  HumanizerProfile,
  listBlackouts,
  listSessionHealth,
  patchHumanizer,
  resumeFromPause,
  SessionHealth,
  type BlackoutDate,
  type SmartPauseInfo,
} from "@/lib/api";
import { formatDate } from "@/lib/utils";
import {
  CalendarX,
  Loader2,
  Pause,
  Play,
  ShieldCheck,
  Trash2,
} from "lucide-react";

const STATUS_COLORS = {
  healthy: "border-green-300 text-green-800",
  warning: "border-amber-300 text-amber-800",
  checkpoint: "border-red-400 text-red-800",
  shadow_ban_suspected: "border-red-400 text-red-800",
  paused: "border-muted-foreground text-muted-foreground",
} as const;

const STATUS_LABEL: Record<SessionHealth["status"], string> = {
  healthy: "healthy",
  warning: "warning",
  checkpoint: "security check",
  shadow_ban_suspected: "suspected shadow ban",
  paused: "paused",
};

export default function PostingBehaviorPage() {
  const [profile, setProfile] = useState<HumanizerProfile | null>(null);
  const [health, setHealth] = useState<SessionHealth[]>([]);
  const [pause, setPause] = useState<SmartPauseInfo | null>(null);
  const [blackouts, setBlackouts] = useState<BlackoutDate[]>([]);
  const [saving, setSaving] = useState(false);
  const [newBlackout, setNewBlackout] = useState({ date: "", reason: "" });

  const refresh = async () => {
    const [p, h, ps, bs] = await Promise.all([
      getHumanizer(),
      listSessionHealth(),
      getPauseStatus(),
      listBlackouts(),
    ]);
    setProfile(p);
    setHealth(h);
    setPause(ps);
    setBlackouts(bs);
  };

  useEffect(() => {
    refresh();
  }, []);

  const update = (patch: Partial<HumanizerProfile>) => {
    if (!profile) return;
    setProfile({ ...profile, ...patch });
  };

  const save = async () => {
    if (!profile) return;
    setSaving(true);
    try {
      const next = await patchHumanizer({
        typing_wpm_min: profile.typing_wpm_min,
        typing_wpm_max: profile.typing_wpm_max,
        mistake_rate: profile.mistake_rate,
        pause_between_sentences_ms_min: profile.pause_between_sentences_ms_min,
        pause_between_sentences_ms_max: profile.pause_between_sentences_ms_max,
        mouse_path_curvature: profile.mouse_path_curvature,
        idle_scroll_before_post_sec_min: profile.idle_scroll_before_post_sec_min,
        idle_scroll_before_post_sec_max: profile.idle_scroll_before_post_sec_max,
        schedule_jitter_minutes: profile.schedule_jitter_minutes,
        consecutive_failures_threshold: profile.consecutive_failures_threshold,
        smart_pause_minutes: profile.smart_pause_minutes,
      });
      setProfile(next);
    } finally {
      setSaving(false);
    }
  };

  const onPause = async () => {
    const p = await activatePause();
    setPause(p);
  };

  const onResume = async () => {
    const p = await resumeFromPause();
    setPause(p);
  };

  const addBo = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newBlackout.date) return;
    const iso = new Date(newBlackout.date).toISOString();
    await addBlackout({ date: iso, reason: newBlackout.reason || null });
    setNewBlackout({ date: "", reason: "" });
    setBlackouts(await listBlackouts());
  };

  if (!profile) {
    return (
      <div className="p-6 flex items-center gap-2 text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading…
      </div>
    );
  }

  return (
    <div className="space-y-4 max-w-4xl">
      <PageHeader
        title="Posting behavior"
        icon={ShieldCheck}
        description="Makes the Chrome extension type, click, and pause like a real person on Facebook. Higher values are safer but slower. The defaults are calibrated for low-risk daily use — leave them alone until you see warnings in Session health."
      />

      <Card>
        <CardHeader>
          <CardTitle>Typing &amp; clicking</CardTitle>
          <CardDescription>
            How the extension types text and moves the mouse when publishing.
            Lower numbers are faster and look more like a bot.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <section className="grid md:grid-cols-2 gap-4">
            <Field
              label="Typing speed — slower edge"
              hint={
                <>
                  <b>Words per minute</b> at the slower end of the random range. Human typists average 40-60 wpm.
                </>
              }
              unit="wpm"
            >
              <Input
                type="number"
                value={profile.typing_wpm_min}
                onChange={(e) => update({ typing_wpm_min: +e.target.value })}
              />
            </Field>
            <Field label="Typing speed — faster edge" unit="wpm">
              <Input
                type="number"
                value={profile.typing_wpm_max}
                onChange={(e) => update({ typing_wpm_max: +e.target.value })}
              />
            </Field>
            <Field
              label="Typo rate"
              hint="Chance of a single-char mistake per keystroke. A value of 0.01 means about 1 typo per 100 chars (it gets auto-corrected)."
            >
              <Input
                type="number"
                step="0.005"
                value={profile.mistake_rate}
                onChange={(e) => update({ mistake_rate: +e.target.value })}
              />
            </Field>
            <Field
              label="Mouse path curvature"
              hint="0 = straight line (robotic), 1 = very curved. 0.4-0.6 looks natural."
            >
              <Input
                type="number"
                step="0.05"
                value={profile.mouse_path_curvature}
                onChange={(e) =>
                  update({ mouse_path_curvature: +e.target.value })
                }
              />
            </Field>
            <Field label="Pause between sentences — shorter edge" unit="ms">
              <Input
                type="number"
                value={profile.pause_between_sentences_ms_min}
                onChange={(e) =>
                  update({ pause_between_sentences_ms_min: +e.target.value })
                }
              />
            </Field>
            <Field label="Pause between sentences — longer edge" unit="ms">
              <Input
                type="number"
                value={profile.pause_between_sentences_ms_max}
                onChange={(e) =>
                  update({ pause_between_sentences_ms_max: +e.target.value })
                }
              />
            </Field>
            <Field
              label="Scroll before posting — shorter edge"
              unit="sec"
              hint="Before hitting Publish, the extension scrolls the group feed for a random duration so it looks like a person reading before posting."
            >
              <Input
                type="number"
                value={profile.idle_scroll_before_post_sec_min}
                onChange={(e) =>
                  update({ idle_scroll_before_post_sec_min: +e.target.value })
                }
              />
            </Field>
            <Field label="Scroll before posting — longer edge" unit="sec">
              <Input
                type="number"
                value={profile.idle_scroll_before_post_sec_max}
                onChange={(e) =>
                  update({ idle_scroll_before_post_sec_max: +e.target.value })
                }
              />
            </Field>
          </section>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Schedule &amp; safety</CardTitle>
          <CardDescription>
            When to randomize timings and when to pause everything after
            failures.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <section className="grid md:grid-cols-2 gap-4">
            <Field
              label="Randomize posting times by up to"
              unit="± minutes"
              hint="A scheduled post won't fire exactly at the minute — it'll shift by a random amount up to this many minutes in either direction. Kills telltale patterns like 'always posts at :00'."
            >
              <Input
                type="number"
                value={profile.schedule_jitter_minutes}
                onChange={(e) =>
                  update({ schedule_jitter_minutes: +e.target.value })
                }
              />
            </Field>
            <Field
              label="Pause after this many failures in a row"
              hint="If the extension hits this many consecutive failures, it stops posting and waits out the cool-down below. Stops you from burning an account on a repeatable error."
            >
              <Input
                type="number"
                value={profile.consecutive_failures_threshold}
                onChange={(e) =>
                  update({ consecutive_failures_threshold: +e.target.value })
                }
              />
            </Field>
            <Field label="Cool-down after auto-pause" unit="minutes">
              <Input
                type="number"
                value={profile.smart_pause_minutes}
                onChange={(e) =>
                  update({ smart_pause_minutes: +e.target.value })
                }
              />
            </Field>
          </section>
          <Button onClick={save} disabled={saving}>
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            Save
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Manual pause</CardTitle>
          <CardDescription>
            Stop all posting right now (e.g. you're about to do a real-life
            campaign and don't want automated noise on top). Scheduled posts
            stay scheduled; they fire when you resume.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {pause?.paused ? (
            <div className="flex items-center gap-3">
              <Badge variant="outline" className="border-red-400 text-red-700">
                Paused
              </Badge>
              <span className="text-sm text-muted-foreground">
                until {pause.until ? formatDate(pause.until) : "?"}
                {pause.reason && ` — ${pause.reason}`}
              </span>
              <Button size="sm" variant="outline" onClick={onResume}>
                <Play className="h-3 w-3" />
                Resume now
              </Button>
            </div>
          ) : (
            <div className="flex items-center gap-3">
              <Badge
                variant="outline"
                className="border-green-400 text-green-800"
              >
                Running
              </Badge>
              <Button size="sm" variant="outline" onClick={onPause}>
                <Pause className="h-3 w-3" />
                Pause posting
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Session health</CardTitle>
          <CardDescription>
            A running tally of how the automation is doing on each platform.
            When a platform turns non-healthy, the scheduler skips it until a
            fresh success clears the counter.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {health.length === 0 ? (
            <EmptyState
              icon={ShieldCheck}
              title="No activity yet"
              description="Once posts start flowing, per-platform health shows up here: green when happy, amber when wobbly, red if Facebook asked for a security check."
            />
          ) : (
            <table className="w-full text-sm">
              <thead className="border-b bg-muted/50">
                <tr className="text-left">
                  <th className="py-2 px-3">Platform</th>
                  <th className="py-2 px-3">Status</th>
                  <th className="py-2 px-3">Failures in a row</th>
                  <th className="py-2 px-3">Last failure</th>
                  <th className="py-2 px-3">Last success</th>
                </tr>
              </thead>
              <tbody>
                {health.map((h) => (
                  <tr key={h.platform_id} className="border-b last:border-0">
                    <td className="py-2 px-3 font-medium">{h.platform_id}</td>
                    <td className="py-2 px-3">
                      <Badge
                        variant="outline"
                        className={STATUS_COLORS[h.status]}
                      >
                        {STATUS_LABEL[h.status]}
                      </Badge>
                    </td>
                    <td className="py-2 px-3">{h.consecutive_failures}</td>
                    <td
                      className="py-2 px-3 text-xs text-muted-foreground"
                      title={h.last_failure_reason ?? ""}
                    >
                      {h.last_failure_at ? formatDate(h.last_failure_at) : "—"}
                    </td>
                    <td className="py-2 px-3 text-xs text-muted-foreground">
                      {h.last_success_at ? formatDate(h.last_success_at) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Days off</CardTitle>
          <CardDescription>
            Dates when the scheduler should stay quiet — vacations, holidays,
            anything where automated posting would look weird.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <form
            onSubmit={addBo}
            className="grid grid-cols-1 md:grid-cols-3 gap-3 items-end"
          >
            <Field label="Date">
              <Input
                type="date"
                value={newBlackout.date}
                onChange={(e) =>
                  setNewBlackout({ ...newBlackout, date: e.target.value })
                }
              />
            </Field>
            <Field label="Reason (optional)">
              <Input
                value={newBlackout.reason}
                onChange={(e) =>
                  setNewBlackout({ ...newBlackout, reason: e.target.value })
                }
                placeholder="vacation, holiday, …"
              />
            </Field>
            <Button type="submit">Add</Button>
          </form>
          <div className="rounded-md border">
            <table className="w-full text-sm">
              <thead className="border-b bg-muted/50">
                <tr className="text-left">
                  <th className="py-2 px-3">Date</th>
                  <th className="py-2 px-3">Reason</th>
                  <th className="py-2 px-3 w-12"></th>
                </tr>
              </thead>
              <tbody>
                {blackouts.length === 0 ? (
                  <tr>
                    <td colSpan={3} className="p-6">
                      <EmptyState
                        icon={CalendarX}
                        title="No days off set"
                        description="Add dates above to silence the scheduler on specific days."
                      />
                    </td>
                  </tr>
                ) : (
                  blackouts.map((b) => (
                    <tr key={b.id} className="border-b last:border-0">
                      <td className="py-2 px-3">{formatDate(b.date)}</td>
                      <td className="py-2 px-3">{b.reason ?? "—"}</td>
                      <td className="py-2 px-3">
                        <Button
                          size="icon"
                          variant="ghost"
                          onClick={async () => {
                            await deleteBlackout(b.id);
                            setBlackouts(await listBlackouts());
                          }}
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

function Field({
  label,
  children,
  hint,
  unit,
}: {
  label: string;
  children: React.ReactNode;
  hint?: React.ReactNode;
  unit?: string;
}) {
  return (
    <div className="space-y-1.5">
      <Label className="flex items-center gap-1 text-xs">
        {label}
        {unit && <span className="text-muted-foreground">({unit})</span>}
        {hint && <InfoPopover label={label}>{hint}</InfoPopover>}
      </Label>
      {children}
    </div>
  );
}
