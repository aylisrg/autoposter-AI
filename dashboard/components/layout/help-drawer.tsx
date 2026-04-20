"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import { HelpCircle, X } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Floating "?" button, bottom-right. Clicking opens a right-side drawer with
 * route-specific help + glossary. ESC or outside-click closes it.
 *
 * Kept intentionally copy-only (no data fetching) so it stays fast on every
 * page and doesn't hit the backend.
 */

type HelpEntry = {
  title: string;
  body: React.ReactNode;
};

const GLOSSARY: HelpEntry[] = [
  {
    title: "Destination",
    body: (
      <>
        A place autoposter can publish to — a Facebook group, an Instagram
        Business account, a LinkedIn page. Manage them on{" "}
        <Link href="/destinations" className="text-primary hover:underline">
          Destinations
        </Link>
        .
      </>
    ),
  },
  {
    title: "Angle",
    body: (
      <>
        The kind of post you want: teaching, selling, storytelling. Called{" "}
        <code className="rounded bg-muted px-1">post_type</code> in the API.
      </>
    ),
  },
  {
    title: "Slot",
    body: (
      <>
        A planned spot for a future post — a date, time, and angle. No text
        is written until you tap <em>Draft with AI</em>.
      </>
    ),
  },
  {
    title: "Spintax / rewrites",
    body: (
      <>
        When you publish to more than one destination, autoposter rewrites the
        post slightly for each so networks don't flag duplicate text.
      </>
    ),
  },
  {
    title: "First comment",
    body: (
      <>
        Facebook and Instagram penalize posts that contain outbound links.
        Autoposter works around it by adding a first comment with the link
        right after publishing.
      </>
    ),
  },
  {
    title: "Engagement score",
    body: (
      <>
        One number that combines likes, comments, and shares (comments
        weighted most). Higher is better — used to pick winning examples for
        future drafts.
      </>
    ),
  },
  {
    title: "Analyst AI",
    body: (
      <>
        Runs weekly (Sunday 21:00 UTC) on your recent numbers. It writes a
        short summary and proposes tweaks to your profile settings.
      </>
    ),
  },
  {
    title: "Few-shot examples",
    body: (
      <>
        Your best-performing recent posts saved as reference. The writer AI
        reads them before drafting new posts so new drafts match your voice.
      </>
    ),
  },
];

const ROUTE_HELP: { match: (p: string) => boolean; entry: HelpEntry }[] = [
  {
    match: (p) => p === "/" || p === "",
    entry: {
      title: "Home",
      body: (
        <>
          What autoposter is doing right now and the one thing it needs
          from you next. The page updates every 15 seconds.
        </>
      ),
    },
  },
  {
    match: (p) => p.startsWith("/queue") || p.startsWith("/review"),
    entry: {
      title: "Posts",
      body: (
        <>
          Every post autoposter knows about. Use the tabs: drafts wait for
          approval, scheduled are queued for later, posted have already gone
          out, failed need your attention. Click any one to see variants per
          destination.
        </>
      ),
    },
  },
  {
    match: (p) => p.startsWith("/compose"),
    entry: {
      title: "New post",
      body: (
        <>
          Three steps: write it (yourself or with AI), pick where it goes,
          then publish now or schedule. Multi-destination posts are rewritten
          automatically.
        </>
      ),
    },
  },
  {
    match: (p) => p.startsWith("/analytics"),
    entry: {
      title: "Results",
      body: (
        <>
          Last 7 days of numbers. Top/bottom performers come from the
          engagement score. AI summaries and suggestions live at the bottom.
        </>
      ),
    },
  },
  {
    match: (p) => p.startsWith("/plans"),
    entry: {
      title: "Calendar",
      body: (
        <>
          Ask the Planner AI for a calendar of posts over a date range, or
          start from an empty one. Each slot is just a plan — actual text is
          only drafted when you tap <em>Draft with AI</em>.
        </>
      ),
    },
  },
  {
    match: (p) => p.startsWith("/library"),
    entry: {
      title: "Media Library",
      body: (
        <>
          Upload pictures you'll reuse. Tag them with AI so the Planner can
          auto-suggest the best image for each planned post.
        </>
      ),
    },
  },
  {
    match: (p) => p.startsWith("/destinations") || p.startsWith("/targets"),
    entry: {
      title: "Destinations",
      body: (
        <>
          Where your posts land — Facebook groups, Instagram accounts,
          LinkedIn pages. You can add them by hand, sync joined groups from
          the extension, or let the Targets AI discover relevant ones for
          you.
        </>
      ),
    },
  },
  {
    match: (p) => p.startsWith("/profile"),
    entry: {
      title: "Your business",
      body: (
        <>
          Context the AI uses every time it drafts a post. The more you fill
          in, the more relevant the drafts.
        </>
      ),
    },
  },
  {
    match: (p) => p.startsWith("/platforms"),
    entry: {
      title: "Connections",
      body: (
        <>
          How autoposter talks to each network. Meta (Instagram / Threads)
          uses the official API. Facebook Groups go through the Chrome
          extension — Facebook has no official API for them.
        </>
      ),
    },
  },
  {
    match: (p) => p.startsWith("/settings/posting-behavior") || p.startsWith("/humanizer"),
    entry: {
      title: "Posting behavior",
      body: (
        <>
          Tuning knobs for how human the automation feels — typing speed,
          pause-between-posts, days off. Stricter settings = less chance of
          Facebook flagging you.
        </>
      ),
    },
  },
];

export function HelpDrawer() {
  const [open, setOpen] = useState(false);
  const pathname = usePathname() ?? "/";

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  const routeEntry = ROUTE_HELP.find((r) => r.match(pathname))?.entry;

  return (
    <>
      <button
        type="button"
        aria-label="Open help"
        onClick={() => setOpen(true)}
        className="fixed bottom-4 right-4 z-40 flex h-10 w-10 items-center justify-center rounded-full border bg-card shadow-md transition-colors hover:bg-accent"
      >
        <HelpCircle className="h-5 w-5" />
      </button>

      {open && (
        <>
          <div
            aria-hidden="true"
            className="fixed inset-0 z-40 bg-background/40 backdrop-blur-[2px]"
            onClick={() => setOpen(false)}
          />
          <aside
            role="dialog"
            aria-label="Help"
            className={cn(
              "fixed right-0 top-0 z-50 flex h-screen w-full max-w-sm flex-col border-l bg-card shadow-xl",
            )}
          >
            <div className="flex items-center justify-between border-b p-4">
              <div className="flex items-center gap-2">
                <HelpCircle className="h-5 w-5" />
                <span className="font-semibold">Help</span>
              </div>
              <button
                type="button"
                onClick={() => setOpen(false)}
                aria-label="Close help"
                className="rounded-md p-1 hover:bg-accent"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="flex-1 space-y-6 overflow-y-auto p-4 text-sm">
              {routeEntry && (
                <section>
                  <h3 className="mb-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    On this page
                  </h3>
                  <div className="space-y-1">
                    <div className="font-medium">{routeEntry.title}</div>
                    <div className="text-muted-foreground leading-relaxed">
                      {routeEntry.body}
                    </div>
                  </div>
                </section>
              )}
              <section>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  Glossary
                </h3>
                <ul className="space-y-3">
                  {GLOSSARY.map((e) => (
                    <li key={e.title}>
                      <div className="font-medium">{e.title}</div>
                      <div className="text-muted-foreground leading-relaxed">
                        {e.body}
                      </div>
                    </li>
                  ))}
                </ul>
              </section>
              <section className="border-t pt-4 text-xs text-muted-foreground">
                Something unclear?{" "}
                <a
                  href="https://github.com/anthropics/claude-code/issues"
                  className="text-primary hover:underline"
                  target="_blank"
                  rel="noreferrer"
                >
                  Open an issue
                </a>{" "}
                with the page name and the thing that confused you.
              </section>
            </div>
          </aside>
        </>
      )}
    </>
  );
}
