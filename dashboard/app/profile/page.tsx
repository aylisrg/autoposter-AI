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
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { PageHeader } from "@/components/ui/page-header";
import { InfoPopover } from "@/components/ui/info-popover";
import { POST_TYPE_OPTIONS, labelForPostType } from "@/lib/post-types";
import {
  getBusinessProfile,
  upsertBusinessProfile,
  type BusinessProfile,
  type EmojiDensity,
  type Length,
  type Tone,
} from "@/lib/api";
import { Briefcase } from "lucide-react";

const EMPTY: Partial<BusinessProfile> = {
  name: "",
  description: "",
  website_url: "",
  products: "",
  target_audience: "",
  call_to_action_url: "",
  tone: "casual",
  length: "medium",
  emoji_density: "light",
  language: "en",
  posting_window_start_hour: 9,
  posting_window_end_hour: 20,
  timezone: "UTC",
  posts_per_day: 3,
  review_before_posting: true,
};

function FieldLabel({
  children,
  hint,
}: {
  children: React.ReactNode;
  hint?: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-1">
      <Label>{children}</Label>
      {hint && <InfoPopover>{hint}</InfoPopover>}
    </div>
  );
}

export default function ProfilePage() {
  const [form, setForm] = useState<Partial<BusinessProfile>>(EMPTY);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      const existing = await getBusinessProfile();
      if (existing) setForm(existing);
      setLoading(false);
    })();
  }, []);

  const update = <K extends keyof BusinessProfile>(
    key: K,
    value: BusinessProfile[K],
  ) => setForm((f) => ({ ...f, [key]: value }));

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setMessage(null);
    try {
      const saved = await upsertBusinessProfile(form);
      setForm(saved);
      setMessage("Saved.");
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <div className="p-6">Loading…</div>;

  const selectedAuto = (form.auto_approve_types ?? []) as string[];
  const toggleAuto = (value: string) => {
    const set = new Set(selectedAuto);
    if (set.has(value)) set.delete(value);
    else set.add(value);
    update("auto_approve_types", [...set]);
  };

  return (
    <div className="space-y-4 p-6 max-w-3xl">
      <PageHeader
        title="Your business"
        description="Tell the AI who you are. It uses this context every time it drafts a post, so fill in as much as you're comfortable with."
        icon={Briefcase}
      />

      <form onSubmit={save} className="space-y-4">
        <Card>
          <CardHeader>
            <CardTitle>About you</CardTitle>
            <CardDescription>
              The facts a reader would want to know. More detail = more
              relevant drafts.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <Label>Business name</Label>
                <Input
                  value={form.name ?? ""}
                  onChange={(e) => update("name", e.target.value)}
                  required
                />
              </div>
              <div className="space-y-1.5">
                <Label>Website</Label>
                <Input
                  type="url"
                  value={form.website_url ?? ""}
                  onChange={(e) => update("website_url", e.target.value)}
                  placeholder="https://example.com"
                />
              </div>
            </div>

            <div className="space-y-1.5">
              <Label>What you do, in a sentence or two</Label>
              <Textarea
                rows={3}
                required
                value={form.description ?? ""}
                onChange={(e) => update("description", e.target.value)}
                placeholder="We help small restaurants take better food photos with a $19/mo app."
              />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <Label>Products or services</Label>
                <Textarea
                  rows={2}
                  value={form.products ?? ""}
                  onChange={(e) => update("products", e.target.value)}
                  placeholder="Monthly subscription, done-for-you packages, …"
                />
              </div>
              <div className="space-y-1.5">
                <Label>Who you're writing for</Label>
                <Textarea
                  rows={2}
                  value={form.target_audience ?? ""}
                  onChange={(e) =>
                    update("target_audience", e.target.value)
                  }
                  placeholder="Solo restaurant owners, 30–55, who post their own photos."
                />
              </div>
            </div>

            <div className="space-y-1.5">
              <Label>Default link for posts</Label>
              <Input
                type="url"
                value={form.call_to_action_url ?? ""}
                onChange={(e) =>
                  update("call_to_action_url", e.target.value)
                }
                placeholder="https://example.com/pricing"
              />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Voice</CardTitle>
            <CardDescription>
              How drafts should sound. Tweak anytime — this only affects
              future generations.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="space-y-1.5">
                <FieldLabel
                  hint="Professional = polished and neutral. Casual = everyday friend-talk. Fun = emojis, punchlines, exclamation points."
                >
                  Tone
                </FieldLabel>
                <Select
                  value={form.tone ?? "casual"}
                  onChange={(e) => update("tone", e.target.value as Tone)}
                >
                  <option value="professional">Professional</option>
                  <option value="casual">Casual</option>
                  <option value="fun">Fun</option>
                </Select>
              </div>
              <div className="space-y-1.5">
                <FieldLabel hint="Short ≈ 1 paragraph. Medium ≈ 2–3. Long ≈ a mini-article with a hook and a CTA.">
                  Length
                </FieldLabel>
                <Select
                  value={form.length ?? "medium"}
                  onChange={(e) =>
                    update("length", e.target.value as Length)
                  }
                >
                  <option value="short">Short</option>
                  <option value="medium">Medium</option>
                  <option value="long">Long</option>
                </Select>
              </div>
              <div className="space-y-1.5">
                <FieldLabel hint="None = no emojis. Light = 1 per post. Medium = 2–3. Heavy = every other line.">
                  Emoji
                </FieldLabel>
                <Select
                  value={form.emoji_density ?? "light"}
                  onChange={(e) =>
                    update(
                      "emoji_density",
                      e.target.value as EmojiDensity,
                    )
                  }
                >
                  <option value="none">None</option>
                  <option value="light">Light</option>
                  <option value="medium">Medium</option>
                  <option value="heavy">Heavy</option>
                </Select>
              </div>
              <div className="space-y-1.5">
                <FieldLabel hint="ISO-639 code (en, ru, es, de…). The AI writes in this language.">
                  Language
                </FieldLabel>
                <Input
                  value={form.language ?? "en"}
                  onChange={(e) => update("language", e.target.value)}
                />
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Cadence &amp; safety</CardTitle>
            <CardDescription>
              When autoposter is allowed to publish on your behalf.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="space-y-1.5">
                <Label>Earliest hour</Label>
                <Input
                  type="number"
                  min={0}
                  max={23}
                  value={form.posting_window_start_hour ?? 9}
                  onChange={(e) =>
                    update(
                      "posting_window_start_hour",
                      parseInt(e.target.value, 10),
                    )
                  }
                />
              </div>
              <div className="space-y-1.5">
                <Label>Latest hour</Label>
                <Input
                  type="number"
                  min={0}
                  max={23}
                  value={form.posting_window_end_hour ?? 20}
                  onChange={(e) =>
                    update(
                      "posting_window_end_hour",
                      parseInt(e.target.value, 10),
                    )
                  }
                />
              </div>
              <div className="space-y-1.5">
                <FieldLabel hint="IANA timezone name (Europe/Berlin, America/New_York). Windows use this clock.">
                  Timezone
                </FieldLabel>
                <Input
                  value={form.timezone ?? "UTC"}
                  onChange={(e) => update("timezone", e.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <Label>Posts per day</Label>
                <Input
                  type="number"
                  min={1}
                  max={50}
                  value={form.posts_per_day ?? 3}
                  onChange={(e) =>
                    update("posts_per_day", parseInt(e.target.value, 10))
                  }
                />
              </div>
            </div>

            <div className="flex items-start gap-2 text-sm">
              <input
                id="rbp"
                type="checkbox"
                className="mt-1"
                checked={form.review_before_posting ?? true}
                onChange={(e) =>
                  update("review_before_posting", e.target.checked)
                }
              />
              <div>
                <Label htmlFor="rbp">I'll approve each post first</Label>
                <p className="text-xs text-muted-foreground">
                  New drafts wait in the Posts queue until you tap{" "}
                  <span className="font-medium">Approve</span>. Turn this off
                  to let the AI post by itself on its normal schedule.
                </p>
              </div>
            </div>

            <div className="space-y-2">
              <FieldLabel hint="Angles you trust enough to skip the review queue for. Anything not in this list still waits for your approval when 'I'll approve each post first' is on.">
                Auto-approve these angles
              </FieldLabel>
              <div className="flex flex-wrap gap-2">
                {POST_TYPE_OPTIONS.map((opt) => {
                  const on = selectedAuto.includes(opt.value);
                  return (
                    <button
                      key={opt.value}
                      type="button"
                      onClick={() => toggleAuto(opt.value)}
                      className={
                        "rounded-md border px-2.5 py-1 text-xs transition-colors " +
                        (on
                          ? "bg-primary text-primary-foreground border-primary"
                          : "hover:bg-accent")
                      }
                    >
                      {labelForPostType(opt.value)}
                    </button>
                  );
                })}
              </div>
            </div>
          </CardContent>
        </Card>

        <div className="flex items-center gap-3">
          <Button type="submit" disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </Button>
          {message && (
            <span className="text-sm text-muted-foreground">{message}</span>
          )}
        </div>
      </form>
    </div>
  );
}
