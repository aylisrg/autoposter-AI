"use client";

import { useEffect, useRef, useState } from "react";
import { HelpCircle } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Inline "?" popover for glossing jargon. Hand-rolled (no Radix) to avoid
 * pulling a popover library for a read-only hover/click tooltip.
 *
 * On desktop, hover shows the panel; on click we lock it open until blur or
 * outside click (so users can copy text or read long explanations).
 */
export function InfoPopover({
  children,
  className,
  side = "bottom",
  label,
}: {
  children: React.ReactNode;
  className?: string;
  side?: "top" | "bottom" | "left" | "right";
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  const [locked, setLocked] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!locked) return;
    const handler = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) {
        setLocked(false);
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [locked]);

  const sidePos = {
    top: "bottom-full mb-2 left-1/2 -translate-x-1/2",
    bottom: "top-full mt-2 left-1/2 -translate-x-1/2",
    left: "right-full mr-2 top-1/2 -translate-y-1/2",
    right: "left-full ml-2 top-1/2 -translate-y-1/2",
  }[side];

  return (
    <span ref={ref} className={cn("relative inline-flex", className)}>
      <button
        type="button"
        aria-label={label || "More info"}
        className="inline-flex items-center text-muted-foreground transition-colors hover:text-foreground"
        onMouseEnter={() => !locked && setOpen(true)}
        onMouseLeave={() => !locked && setOpen(false)}
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setLocked((l) => !l);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => !locked && setOpen(false)}
      >
        <HelpCircle className="h-3.5 w-3.5" />
      </button>
      {open && (
        <span
          role="tooltip"
          className={cn(
            "absolute z-50 w-64 rounded-md border bg-popover p-3 text-xs leading-relaxed text-popover-foreground shadow-md",
            sidePos,
          )}
          onMouseEnter={() => setOpen(true)}
          onMouseLeave={() => !locked && setOpen(false)}
        >
          {children}
        </span>
      )}
    </span>
  );
}
