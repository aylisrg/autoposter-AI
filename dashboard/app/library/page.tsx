"use client";

import { useEffect, useRef, useState } from "react";
import {
  ApiError,
  MediaAsset,
  deleteMedia,
  listMedia,
  patchMedia,
  tagMedia,
  uploadMedia,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageHeader } from "@/components/ui/page-header";
import { InfoPopover } from "@/components/ui/info-popover";
import { EmptyState } from "@/components/ui/empty-state";
import {
  ImageIcon,
  Loader2,
  Sparkles,
  Trash2,
  Upload,
  X,
} from "lucide-react";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8787";

export default function LibraryPage() {
  const [assets, setAssets] = useState<MediaAsset[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [taggingIds, setTaggingIds] = useState<Set<number>>(new Set());
  const [selected, setSelected] = useState<MediaAsset | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const refresh = async () => {
    setLoading(true);
    try {
      const list = await listMedia();
      setAssets(list);
      if (selected) {
        const updated = list.find((a) => a.id === selected.id) ?? null;
        setSelected(updated);
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
  }, []);

  const handleFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setError(null);
    setUploading(true);
    try {
      for (const file of Array.from(files)) {
        await uploadMedia(file);
      }
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const handleTag = async (assetId: number) => {
    setError(null);
    setTaggingIds((prev) => new Set(prev).add(assetId));
    try {
      await tagMedia(assetId);
      await refresh();
    } catch (e) {
      setError(
        e instanceof ApiError
          ? `${e.status}: ${e.message}`
          : e instanceof Error
            ? e.message
            : "Tag failed",
      );
    } finally {
      setTaggingIds((prev) => {
        const next = new Set(prev);
        next.delete(assetId);
        return next;
      });
    }
  };

  const handleDelete = async (assetId: number) => {
    if (!confirm("Delete this image? The file is removed from disk."))
      return;
    await deleteMedia(assetId);
    setSelected(null);
    refresh();
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    handleFiles(e.dataTransfer.files);
  };

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <PageHeader
        title="Media Library"
        description="Pictures you've uploaded, ready for reuse. Tag them with AI and autoposter will suggest the best match for each planned post."
        icon={ImageIcon}
      />

      {error && (
        <div className="rounded-md bg-destructive/10 text-destructive text-sm p-3">
          {error}
        </div>
      )}

      <Card
        onDragOver={(e) => e.preventDefault()}
        onDrop={onDrop}
        className="border-dashed border-2 p-8 flex flex-col items-center justify-center text-center cursor-pointer hover:bg-accent/20 transition"
        onClick={() => inputRef.current?.click()}
      >
        <input
          ref={inputRef}
          type="file"
          accept="image/jpeg,image/png,image/webp,image/gif"
          multiple
          hidden
          onChange={(e) => handleFiles(e.target.files)}
        />
        {uploading ? (
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        ) : (
          <Upload className="h-6 w-6 text-muted-foreground" />
        )}
        <div className="mt-2 font-medium">
          {uploading ? "Uploading…" : "Drop images here, or click to browse"}
        </div>
        <div className="text-xs text-muted-foreground mt-1">
          JPEG, PNG, WebP, or GIF · up to 10 MB each
        </div>
      </Card>

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
        {loading ? (
          <p className="text-sm text-muted-foreground col-span-full">
            Loading…
          </p>
        ) : assets.length === 0 ? (
          <div className="col-span-full">
            <EmptyState
              icon={ImageIcon}
              title="No images yet"
              description="Upload your first picture above. Once you tag them with AI, autoposter picks the best match for each planned post."
            />
          </div>
        ) : (
          assets.map((a) => (
            <Card
              key={a.id}
              className={`overflow-hidden cursor-pointer hover:ring-2 hover:ring-primary/50 transition ${
                selected?.id === a.id ? "ring-2 ring-primary" : ""
              }`}
              onClick={() => setSelected(a)}
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={`${API_BASE}/static/${a.local_path}`}
                alt={a.ai_caption ?? a.filename}
                className="w-full aspect-square object-cover"
              />
              <CardContent className="p-2 space-y-1">
                <div className="text-xs text-muted-foreground line-clamp-2 min-h-[2.5em]">
                  {a.ai_caption ?? "No AI caption yet"}
                </div>
                <div className="flex flex-wrap gap-1">
                  {(a.ai_tags ?? []).slice(0, 3).map((t) => (
                    <Badge key={t} variant="secondary" className="text-[10px]">
                      {t}
                    </Badge>
                  ))}
                  {(a.ai_tags ?? []).length === 0 && (
                    <Badge variant="outline" className="text-[10px]">
                      untagged
                    </Badge>
                  )}
                </div>
              </CardContent>
            </Card>
          ))
        )}
      </div>

      {selected && (
        <Card className="sticky bottom-6 bg-card/95 backdrop-blur">
          <CardContent className="p-4 flex items-center gap-4">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={`${API_BASE}/static/${selected.local_path}`}
              alt=""
              className="w-24 h-24 object-cover rounded-md"
            />
            <div className="flex-1 min-w-0">
              <div className="font-medium truncate">{selected.filename}</div>
              <div className="text-xs text-muted-foreground">
                {selected.width}×{selected.height} ·{" "}
                {(selected.size_bytes / 1024).toFixed(0)} KB
              </div>
              <div className="text-sm mt-1 line-clamp-2">
                {selected.ai_caption ?? "No caption yet — tap Tag with AI."}
              </div>
              <div className="flex flex-wrap gap-1 mt-1 items-center">
                <span className="text-[10px] text-muted-foreground flex items-center gap-0.5">
                  AI tags
                  <InfoPopover>
                    Claude Vision reads the image and picks short, generic
                    tags (e.g. "kitchen", "close-up", "hero-shot"). The
                    planner uses these to match images to post topics.
                  </InfoPopover>
                </span>
                {(selected.ai_tags ?? []).map((t) => (
                  <Badge key={t} variant="secondary" className="text-[10px]">
                    {t}
                  </Badge>
                ))}
              </div>
              <UserTagsEditor
                asset={selected}
                onSaved={(next) => {
                  setSelected(next);
                  refresh();
                }}
              />
            </div>
            <div className="flex flex-col gap-2">
              <Button
                size="sm"
                variant="secondary"
                onClick={() => handleTag(selected.id)}
                disabled={taggingIds.has(selected.id)}
                title="Claude Vision describes the image (~$0.003)"
              >
                {taggingIds.has(selected.id) ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <Sparkles className="h-3 w-3" />
                )}
                Tag with AI
              </Button>
              <Button
                size="sm"
                variant="destructive"
                onClick={() => handleDelete(selected.id)}
              >
                <Trash2 className="h-3 w-3" />
                Delete
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setSelected(null)}
              >
                <X className="h-3 w-3" />
                Close
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function UserTagsEditor({
  asset,
  onSaved,
}: {
  asset: MediaAsset;
  onSaved: (a: MediaAsset) => void;
}) {
  const [val, setVal] = useState((asset.tags_user ?? []).join(", "));
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setVal((asset.tags_user ?? []).join(", "));
  }, [asset.id]);

  const save = async () => {
    setBusy(true);
    try {
      const next = await patchMedia(asset.id, {
        tags_user: val
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean),
      });
      onSaved(next);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-2 flex gap-2 items-end">
      <div className="flex-1">
        <Label className="text-[10px] flex items-center gap-0.5">
          Your tags (comma-separated)
          <InfoPopover>
            Your own keywords — brand names, campaign names, shoot dates.
            They're searched alongside the AI tags when matching images to
            posts.
          </InfoPopover>
        </Label>
        <Input
          value={val}
          onChange={(e) => setVal(e.target.value)}
          placeholder="launch, hero-image, june-campaign"
          className="h-7 text-xs"
        />
      </div>
      <Button size="sm" variant="outline" onClick={save} disabled={busy}>
        Save
      </Button>
    </div>
  );
}
