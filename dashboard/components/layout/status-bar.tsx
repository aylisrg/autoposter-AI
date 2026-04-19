"use client";

import { useEffect, useState } from "react";
import { getStatus, type StatusOut } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export function StatusBar() {
  const [status, setStatus] = useState<StatusOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const s = await getStatus();
        if (!cancelled) {
          setStatus(s);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e));
        }
      }
    };
    tick();
    const id = setInterval(tick, 10_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  if (error) {
    return (
      <div className="flex items-center gap-2 rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm">
        <span className="h-2 w-2 rounded-full bg-destructive" />
        <span className="text-destructive">
          Backend unreachable: {error}
        </span>
      </div>
    );
  }

  if (!status) {
    return (
      <div className="rounded-md border px-3 py-2 text-sm text-muted-foreground">
        Checking backend…
      </div>
    );
  }

  return (
    <div className="flex items-center gap-3 rounded-md border px-3 py-2 text-sm flex-wrap">
      <div className="flex items-center gap-2">
        <span
          className={cn(
            "h-2 w-2 rounded-full",
            status.ok ? "bg-green-500" : "bg-red-500",
          )}
        />
        Backend v{status.version}
      </div>
      <Badge variant={status.extension_connected ? "success" : "outline"}>
        Extension: {status.extension_connected ? "connected" : "offline"}
      </Badge>
      <Badge variant={status.scheduler_running ? "success" : "warning"}>
        Scheduler: {status.scheduler_running ? "running" : "stopped"}
      </Badge>
      <span className="text-muted-foreground ml-auto">
        Pending: {status.pending_posts}
      </span>
    </div>
  );
}
