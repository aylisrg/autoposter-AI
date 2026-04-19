"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import {
  Calendar,
  CalendarDays,
  CheckSquare,
  Home,
  Image as ImageIcon,
  ListChecks,
  PenSquare,
  ShieldCheck,
  Users,
} from "lucide-react";

const NAV = [
  { href: "/profile", label: "Business Profile", icon: Home },
  { href: "/targets", label: "Targets", icon: Users },
  { href: "/plans", label: "Content Plans", icon: CalendarDays },
  { href: "/library", label: "Media Library", icon: ImageIcon },
  { href: "/compose", label: "Compose", icon: PenSquare },
  { href: "/review", label: "Review", icon: CheckSquare },
  { href: "/queue", label: "Queue", icon: ListChecks },
  { href: "/humanizer", label: "Humanizer", icon: ShieldCheck },
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
      <nav className="flex-1 p-2 space-y-1">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active =
            pathname === href || pathname.startsWith(href + "/");
          return (
            <Link
              key={href}
              href={href}
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
