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
import { Loader2, Pause, Play, ShieldCheck, Trash2 } from "lucide-react";

const STATUS_COLORS = {
  healthy: "border-green-300 text-green-800",
  warning: "border-amber-300 text-amber-800",
  checkpoint: "border-red-400 text-red-800",
  shadow_ban_suspected: "border-red-400 text-red-800",
  paused: "border-muted-foreground text-muted-foreground",
} as const;

export default function HumanizerPage() {
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
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5" /> Humanizer & Safety
          </CardTitle>
          <CardDescription>
            Controls how "human" the browser interaction feels. Typing speed,
            mouse paths, scheduling jitter, and the automatic cool-down when
            something goes wrong.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <section className="grid md:grid-cols-2 gap-4">
            <Field label="Typing WPM min">
              <Input
                type="number"
                value={profile.typing_wpm_min}
                onChange={(e) => update({ typing_wpm_min: +e.target.value })}
              />
            </Field>
            <Field label="Typing WPM max">
              <Input
                type="number"
                value={profile.typing_wpm_max}
                onChange={(e) => update({ typing_wpm_max: +e.target.value })}
              />
            </Field>
            <Field label="Mistake rate (0–1)">
              <Input
                type="number"
                step="0.005"
                value={profile.mistake_rate}
                onChange={(e) => update({ mistake_rate: +e.target.value })}
              />
            </Field>
            <Field label="Mouse path curvature (0–1)">
              <Input
                type="number"
                step="0.05"
                value={profile.mouse_path_curvature}
                onChange={(e) =>
                  update({ mouse_path_curvature: +e.target.value })
                }
              />
            </Field>
            <Field label="Sentence pause min (ms)">
              <Input
                type="number"
                value={profile.pause_between_sentences_ms_min}
                onChange={(e) =>
                  update({ pause_between_sentences_ms_min: +e.target.value })
                }
              />
            </Field>
            <Field label="Sentence pause max (ms)">
              <Input
                type="number"
                value={profile.pause_between_sentences_ms_max}
                onChange={(e) =>
                  update({ pause_between_sentences_ms_max: +e.target.value })
                }
              />
            </Field>
            <Field label="Idle scroll before post (sec, min)">
              <Input
                type="number"
                value={profile.idle_scroll_before_post_sec_min}
                onChange={(e) =>
                  update({ idle_scroll_before_post_sec_min: +e.target.value })
                }
              />
            </Field>
            <Field label="Idle scroll before post (sec, max)">
              <Input
                type="number"
                value={profile.idle_scroll_before_post_sec_max}
                onChange={(e) =>
                  update({ idle_scroll_before_post_sec_max: +e.target.value })
                }
              />
            </Field>
            <Field label="Schedule jitter (± minutes)">
              <Input
                type="number"
                value={profile.schedule_jitter_minutes}
                onChange={(e) =>
                  update({ schedule_jitter_minutes: +e.target.value })
                }
              />
            </Field>
            <Field label="Failure threshold for auto-pause">
              <Input
                type="number"
                value={profile.consecutive_failures_threshold}
                onChange={(e) =>
                  update({ consecutive_failures_threshold: +e.target.value })
                }
              />
            </Field>
            <Field label="Auto-pause duration (minutes)">
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
          <CardTitle>Smart pause</CardTitle>
          <CardDescription>
            When active the scheduler sits idle — no posting happens until it
            expires or you resume.
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
                Active
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
            Per-platform running tally of failures / successes. Non-healthy
            platforms are skipped until the counter resets with a new success.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {health.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No activity yet.
            </p>
          ) : (
            <table className="w-full text-sm">
              <thead className="border-b bg-muted/50">
                <tr className="text-left">
                  <th className="py-2 px-3">Platform</th>
                  <th className="py-2 px-3">Status</th>
                  <th className="py-2 px-3">Fail streak</th>
                  <th className="py-2 px-3">Last fail</th>
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
                        {h.status}
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
          <CardTitle>Blackout dates</CardTitle>
          <CardDescription>
            Days where the scheduler stays quiet (vacations, holidays, known
            brand-risky days).
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
                    <td colSpan={3} className="p-4 text-muted-foreground">
                      No blackout dates.
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
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <Label className="text-xs">{label}</Label>
      {children}
    </div>
  );
}
