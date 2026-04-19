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
import { WarningBanner } from "@/components/warning-banner";
import {
  getBusinessProfile,
  upsertBusinessProfile,
  type BusinessProfile,
  type EmojiDensity,
  type Length,
  type Tone,
} from "@/lib/api";

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

  if (loading) return <div>Loading…</div>;

  return (
    <div className="space-y-4 max-w-3xl">
      <WarningBanner />
      <Card>
        <CardHeader>
          <CardTitle>Business Profile</CardTitle>
          <CardDescription>
            Context the AI uses when writing. One profile per install (v1).
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={save} className="space-y-4">
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
              <Label>Description</Label>
              <Textarea
                rows={3}
                required
                value={form.description ?? ""}
                onChange={(e) => update("description", e.target.value)}
              />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <Label>Products / services</Label>
                <Textarea
                  rows={2}
                  value={form.products ?? ""}
                  onChange={(e) => update("products", e.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <Label>Target audience</Label>
                <Textarea
                  rows={2}
                  value={form.target_audience ?? ""}
                  onChange={(e) =>
                    update("target_audience", e.target.value)
                  }
                />
              </div>
            </div>

            <div className="space-y-1.5">
              <Label>Default call-to-action URL</Label>
              <Input
                type="url"
                value={form.call_to_action_url ?? ""}
                onChange={(e) =>
                  update("call_to_action_url", e.target.value)
                }
                placeholder="https://example.com/pricing"
              />
            </div>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="space-y-1.5">
                <Label>Tone</Label>
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
                <Label>Length</Label>
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
                <Label>Emoji</Label>
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
                <Label>Language</Label>
                <Input
                  value={form.language ?? "en"}
                  onChange={(e) => update("language", e.target.value)}
                />
              </div>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="space-y-1.5">
                <Label>Window start hour</Label>
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
                <Label>Window end hour</Label>
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
                <Label>Timezone</Label>
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

            <div className="flex items-center gap-2 text-sm">
              <input
                id="rbp"
                type="checkbox"
                checked={form.review_before_posting ?? true}
                onChange={(e) =>
                  update("review_before_posting", e.target.checked)
                }
              />
              <Label htmlFor="rbp">Require review before posting</Label>
            </div>

            <div className="space-y-1.5">
              <Label>
                Auto-approve post types (comma-separated — skip review queue for
                trusted types)
              </Label>
              <Input
                placeholder="e.g. informative, motivational"
                value={(form.auto_approve_types ?? []).join(", ")}
                onChange={(e) =>
                  update(
                    "auto_approve_types",
                    e.target.value
                      .split(",")
                      .map((s) => s.trim())
                      .filter(Boolean),
                  )
                }
              />
            </div>

            <div className="flex items-center gap-3">
              <Button type="submit" disabled={saving}>
                {saving ? "Saving…" : "Save"}
              </Button>
              {message && (
                <span className="text-sm text-muted-foreground">
                  {message}
                </span>
              )}
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
