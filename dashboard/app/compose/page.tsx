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

const POST_TYPES: PostType[] = [
  "informative",
  "soft_sell",
  "hard_sell",
  "engagement",
  "story",
  "motivational",
  "testimonial",
  "hot_take",
  "seasonal",
];

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
      setMessage(`Uploaded ${res.filename} (${(res.size_bytes / 1024).toFixed(0)} KB).`);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const onGenerate = async (withImage: boolean) => {
    setBusy(withImage ? "Generating text + image…" : "Generating text…");
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
      setMessage("Text is empty.");
      return;
    }
    if (selectedTargetIds.size === 0) {
      setMessage("Select at least one target.");
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
        `Publish result: ${ok}/${result.variants.length} posted.` +
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
      setMessage("Pick a date/time.");
      return;
    }
    if (selectedTargetIds.size === 0) {
      setMessage("Select at least one target.");
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
      setMessage(`Scheduled for ${new Date(scheduledFor).toLocaleString()}.`);
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

  return (
    <div className="space-y-4 max-w-4xl">
      <Card>
        <CardHeader>
          <CardTitle>Compose a post</CardTitle>
          <CardDescription>
            Generate a draft with Claude, edit it, attach an image, pick
            targets, then publish now or schedule.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="space-y-1.5">
              <Label>Post type</Label>
              <Select
                value={postType}
                onChange={(e) => setPostType(e.target.value as PostType)}
              >
                {POST_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
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
              Generate text (Claude)
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={!!busy}
              onClick={() => onGenerate(true)}
            >
              Generate text + image (Gemini)
            </Button>
            <Button
              type="button"
              variant="ghost"
              disabled={!!busy}
              onClick={resetDraft}
            >
              New draft
            </Button>
          </div>

          <div className="space-y-1.5">
            <Label>Post text</Label>
            <Textarea
              rows={8}
              value={text}
              onChange={(e) => {
                setText(e.target.value);
                if (draft) setDraft(null); // text edited → force re-create on publish
              }}
            />
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label>First comment (optional)</Label>
              <Textarea
                rows={2}
                value={firstComment}
                onChange={(e) => setFirstComment(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label>CTA URL (optional)</Label>
              <Input
                type="url"
                value={ctaUrl}
                onChange={(e) => setCtaUrl(e.target.value)}
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
          <CardTitle>Targets</CardTitle>
          <CardDescription>
            Select one or more. Multi-target posts get auto-spintaxed to
            avoid identical text across groups.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {targets.length === 0 ? (
            <div className="text-sm text-muted-foreground">
              No active targets. Add some on the Targets page.
            </div>
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
          <CardTitle>Publish</CardTitle>
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
