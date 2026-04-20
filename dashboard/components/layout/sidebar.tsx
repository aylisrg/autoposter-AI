"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import {
  BarChart3,
  Briefcase,
  Calendar,
  CalendarDays,
  Home,
  Image as ImageIcon,
  Link2,
  ListChecks,
  PenSquare,
  ShieldCheck,
  Users,
} from "lucide-react";

type Item = {
  href: string;
  label: string;
  hint?: string;
  icon: React.ComponentType<{ className?: string }>;
};

type Section = {
  title: string;
  items: Item[];
};

const NAV: Section[] = [
  {
    title: "Daily",
    items: [
      { href: "/", label: "Home", icon: Home, hint: "What's happening now" },
      {
        href: "/queue",
        label: "Posts",
        icon: ListChecks,
        hint: "Drafts, scheduled, posted, failed",
      },
      {
        href: "/compose",
        label: "New post",
        icon: PenSquare,
        hint: "One-off, AI-assisted",
      },
      {
        href: "/analytics",
        label: "Results",
        icon: BarChart3,
        hint: "How posts are performing",
      },
    ],
  },
  {
    title: "Plan ahead",
    items: [
      {
        href: "/plans",
        label: "Calendar",
        icon: CalendarDays,
        hint: "AI-generated posting schedule",
      },
      {
        href: "/library",
        label: "Media Library",
        icon: ImageIcon,
        hint: "Reusable images",
      },
      {
        href: "/destinations",
        label: "Destinations",
        icon: Users,
        hint: "Where posts are sent",
      },
    ],
  },
  {
    title: "Settings",
    items: [
      {
        href: "/profile",
        label: "Your business",
        icon: Briefcase,
        hint: "Context the AI uses when drafting",
      },
      {
        href: "/platforms",
        label: "Connections",
        icon: Link2,
        hint: "Meta, LinkedIn, Chrome extension",
      },
      {
        href: "/settings/posting-behavior",
        label: "Posting behavior",
        icon: ShieldCheck,
        hint: "How human the automation feels",
      },
    ],
  },
];

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="w-60 border-r bg-card/50 h-screen sticky top-0 flex flex-col">
      <div className="p-4 border-b">
        <div className="flex items-center gap-2">
          <Calendar className="h-5 w-5" />
          <span className="font-semibold">autoposter-AI</span>
        </div>
        <div className="text-xs text-muted-foreground mt-1">
          Local self-hosted v0.1
        </div>
      </div>
      <nav className="flex-1 p-2 space-y-3 overflow-y-auto">
        {NAV.map((section) => (
          <div key={section.title}>
            <div className="px-3 pt-2 pb-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              {section.title}
            </div>
            <div className="space-y-1">
              {section.items.map(({ href, label, icon: Icon, hint }) => {
                const active =
                  pathname === href ||
                  (href !== "/" && pathname.startsWith(href + "/")) ||
                  (href === "/queue" && pathname.startsWith("/review")) ||
                  (href === "/destinations" && pathname.startsWith("/targets")) ||
                  (href === "/settings/posting-behavior" &&
                    pathname.startsWith("/humanizer"));
                return (
                  <Link
                    key={href}
                    href={href}
                    title={hint}
                    className={cn(
                      "flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors",
                      active
                        ? "bg-accent text-accent-foreground font-medium"
                        : "hover:bg-accent/60",
                    )}
                  >
                    <Icon className="h-4 w-4" />
                    {label}
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </nav>
      <div className="p-3 text-xs text-muted-foreground border-t">
        <p className="leading-relaxed">
          Facebook automation breaks their ToS. Use a throwaway account and
          respect rate limits.
        </p>
      </div>
    </aside>
  );
}
