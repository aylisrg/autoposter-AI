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
import { Textarea } from "@/components/ui/textarea";
import { Select } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { PageHeader } from "@/components/ui/page-header";
import { InfoPopover } from "@/components/ui/info-popover";
import { EmptyState } from "@/components/ui/empty-state";
import { POST_TYPE_OPTIONS, POST_TYPE_DESCRIPTIONS } from "@/lib/post-types";
import {
  createPost,
  generatePost,
  listTargets,
  publishPost,
  schedulePost,
  uploadMedia,
  type Post,
  type PostType,
  type Target,
} from "@/lib/api";
import { PenSquare, Sparkles, Users } from "lucide-react";

export default function ComposePage() {
  const [targets, setTargets] = useState<Target[]>([]);
  const [selectedTargetIds, setSelectedTargetIds] = useState<Set<number>>(
    new Set(),
  );
  const [draft, setDraft] = useState<Post | null>(null);
  const [text, setText] = useState("");
  const [firstComment, setFirstComment] = useState("");
  const [ctaUrl, setCtaUrl] = useState("");
  const [postType, setPostType] = useState<PostType>("informative");
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [topicHint, setTopicHint] = useState("");
  const [scheduledFor, setScheduledFor] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    listTargets({ active_only: true }).then(setTargets).catch(() => {});
  }, []);

  const toggleTarget = (id: number) => {
    setSelectedTargetIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const onUpload = async (file: File) => {
    setBusy("Uploading image…");
    try {
      const res = await uploadMedia(file);
      setImageUrl(res.url);
      setMessage(
        `Uploaded ${res.filename} (${(res.size_bytes / 1024).toFixed(0)} KB).`,
      );
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const onGenerate = async (withImage: boolean) => {
    setBusy(
      withImage ? "Writing text + generating image…" : "Writing text…",
    );
    setMessage(null);
    try {
      const d = await generatePost({
        post_type: postType,
        topic_hint: topicHint || undefined,
        generate_image: withImage,
        use_few_shot: true,
      });
      setDraft(d);
      setText(d.text);
      setImageUrl(d.image_url);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const ensureDraft = async (): Promise<Post> => {
    if (draft) {
      return draft;
    }
    const d = await createPost({
      post_type: postType,
      text,
      image_url: imageUrl,
      first_comment: firstComment || null,
      cta_url: ctaUrl || null,
    });
    setDraft(d);
    return d;
  };

  const onPublishNow = async () => {
    if (!text.trim()) {
      setMessage("Write something first.");
      return;
    }
    if (selectedTargetIds.size === 0) {
      setMessage("Pick at least one destination.");
      return;
    }
    setBusy("Publishing…");
    setMessage(null);
    try {
      const d = await ensureDraft();
      const result = await publishPost(d.id, {
        target_ids: [...selectedTargetIds],
        generate_spintax: selectedTargetIds.size > 1,
      });
      const ok = result.variants.filter((v) => v.status === "posted").length;
      const failed = result.variants.filter((v) => v.status === "failed");
      setMessage(
        `Posted to ${ok}/${result.variants.length}.` +
          (failed.length
            ? ` Failures: ${failed.map((f) => f.error).join("; ")}`
            : ""),
      );
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const onSchedule = async () => {
    if (!scheduledFor) {
      setMessage("Pick a date and time.");
      return;
    }
    if (selectedTargetIds.size === 0) {
      setMessage("Pick at least one destination.");
      return;
    }
    setBusy("Scheduling…");
    setMessage(null);
    try {
      const d = await ensureDraft();
      await schedulePost(d.id, {
        target_ids: [...selectedTargetIds],
        scheduled_for: new Date(scheduledFor).toISOString(),
        generate_spintax: selectedTargetIds.size > 1,
      });
      setMessage(
        `Scheduled for ${new Date(scheduledFor).toLocaleString()}.`,
      );
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const resetDraft = () => {
    setDraft(null);
    setText("");
    setFirstComment("");
    setCtaUrl("");
    setImageUrl(null);
    setMessage(null);
  };

  const multi = selectedTargetIds.size > 1;

  return (
    <div className="space-y-4 p-6 max-w-4xl">
      <PageHeader
        title="New post"
        description="Write it, pick where it goes, then publish now or schedule it. Claude can draft the text for you; Gemini can draw the picture."
        icon={PenSquare}
      />

      <Card>
        <CardHeader>
          <CardTitle>1. Write the post</CardTitle>
          <CardDescription>
            Pick an angle, give a hint, then let Claude draft it — or type it
            yourself.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="space-y-1.5">
              <div className="flex items-center gap-1">
                <Label>Angle</Label>
                <InfoPopover label="What's an angle?">
                  The kind of post you want: teaching something, telling a
                  story, pushing an offer. The AI tailors the tone to match.
                  <span className="mt-2 block text-muted-foreground">
                    Current: {POST_TYPE_DESCRIPTIONS[postType] ?? ""}
                  </span>
                </InfoPopover>
              </div>
              <Select
                value={postType}
                onChange={(e) => setPostType(e.target.value as PostType)}
              >
                {POST_TYPE_OPTIONS.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5 md:col-span-2">
              <Label>Topic hint (optional)</Label>
              <Input
                value={topicHint}
                onChange={(e) => setTopicHint(e.target.value)}
                placeholder="e.g. launch of our new pricing tier"
              />
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={!!busy}
              onClick={() => onGenerate(false)}
            >
              <Sparkles className="mr-2 h-4 w-4" />
              Write with AI{" "}
              <span className="ml-1.5 text-xs text-muted-foreground">
                ~$0.01
              </span>
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={!!busy}
              onClick={() => onGenerate(true)}
            >
              <Sparkles className="mr-2 h-4 w-4" />
              Write + draw image
              <span className="ml-1.5 text-xs text-muted-foreground">
                ~$0.05
              </span>
            </Button>
            <Button
              type="button"
              variant="ghost"
              disabled={!!busy}
              onClick={resetDraft}
            >
              Clear
            </Button>
          </div>

          <div className="space-y-1.5">
            <Label>Post text</Label>
            <Textarea
              rows={8}
              value={text}
              onChange={(e) => {
                setText(e.target.value);
                if (draft) setDraft(null);
              }}
              placeholder="Write your post here, or use 'Write with AI' above."
            />
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <div className="flex items-center gap-1">
                <Label>First comment (optional)</Label>
                <InfoPopover label="What's a first comment?">
                  Some networks (Facebook, Instagram) tuck links into the
                  first comment so they don't hurt the post's reach. Paste
                  your link here and autoposter will add it right after
                  publishing.
                </InfoPopover>
              </div>
              <Textarea
                rows={2}
                value={firstComment}
                onChange={(e) => setFirstComment(e.target.value)}
                placeholder="Optional — often a link the reader can follow."
              />
            </div>
            <div className="space-y-1.5">
              <Label>Call-to-action URL (optional)</Label>
              <Input
                type="url"
                value={ctaUrl}
                onChange={(e) => setCtaUrl(e.target.value)}
                placeholder="https://example.com/pricing"
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <Label>Image</Label>
            <div className="flex items-center gap-3">
              <Input
                type="file"
                accept="image/*"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) onUpload(f);
                }}
              />
              {imageUrl && (
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => setImageUrl(null)}
                >
                  Remove
                </Button>
              )}
            </div>
            {imageUrl && (
              <div className="mt-2 rounded-md border p-2 inline-block">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={imageUrl}
                  alt="preview"
                  className="max-h-48 rounded"
                />
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            2. Pick destinations
            {multi && (
              <InfoPopover label="Why rewrites?">
                When you pick two or more destinations, autoposter rewrites
                the post slightly for each (same meaning, different words) so
                the networks don't flag duplicate text.
              </InfoPopover>
            )}
          </CardTitle>
          <CardDescription>
            Pick one or more places to publish. Multi-destination posts get
            auto-rewritten so platforms don't flag identical copies.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {targets.length === 0 ? (
            <EmptyState
              icon={Users}
              title="No active destinations"
              description="Add a Facebook group, Instagram account, or other destination first."
              cta={{ label: "Add destinations", href: "/destinations" }}
            />
          ) : (
            <div className="flex flex-wrap gap-2">
              {targets.map((t) => {
                const on = selectedTargetIds.has(t.id);
                return (
                  <button
                    key={t.id}
                    type="button"
                    onClick={() => toggleTarget(t.id)}
                    className={
                      "rounded-md border px-3 py-1.5 text-sm transition-colors " +
                      (on
                        ? "bg-primary text-primary-foreground border-primary"
                        : "hover:bg-accent")
                    }
                  >
                    {t.name}
                    <Badge variant="outline" className="ml-2">
                      {t.platform_id}
                    </Badge>
                  </button>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>3. Publish or schedule</CardTitle>
          <CardDescription>
            Post now, or pick a time and autoposter will do it for you.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-end gap-3">
            <Button disabled={!!busy} onClick={onPublishNow}>
              {busy ?? "Publish now"}
            </Button>
            <div className="space-y-1.5">
              <Label>Schedule for</Label>
              <Input
                type="datetime-local"
                value={scheduledFor}
                onChange={(e) => setScheduledFor(e.target.value)}
              />
            </div>
            <Button
              variant="outline"
              disabled={!!busy || !scheduledFor}
              onClick={onSchedule}
            >
              Schedule
            </Button>
          </div>
          {message && (
            <div className="text-sm rounded-md border bg-muted/40 p-3 whitespace-pre-wrap">
              {message}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
