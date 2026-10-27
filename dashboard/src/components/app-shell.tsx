"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import {
  BookOpen,
  Cpu,
  Database,
  FlaskConical,
  Lightbulb,
  ListTree,
  Workflow,
  type LucideIcon,
} from "lucide-react";
import { Logo } from "@/components/cockpit";
import { DEFAULT_INTERVALS, RefreshContext } from "@/hooks/use-api";
import { fetchJson } from "@/lib/api";
import type { UiConfig } from "@/lib/types";
import { cn } from "@/lib/utils";

// One entry per DAG stage page (design: docs/plans/2026-10-26-dashboard-v35-cockpit-design.md).
// Entries without an href are later slices, listed so the shape of the cockpit is visible.
const NAV: { label: string; icon: LucideIcon; href?: string }[] = [
  { label: "Pipeline", icon: Workflow, href: "/" },
  { label: "Data", icon: Database, href: "/data" },
  { label: "Instruments", icon: ListTree, href: "/instruments" },
  { label: "Concepts", icon: Lightbulb, href: "/concepts" },
  { label: "Research", icon: FlaskConical },
  { label: "Books", icon: BookOpen },
  { label: "System", icon: Cpu, href: "/system" },
];

/** A page is current on its own path and below it (an instrument's passport is under Instruments). */
function isCurrent(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}

/** Seconds from the API as a poll interval; a missing or non-positive value keeps the default,
 *  so an API older than the dashboard can never make a page poll in a tight loop. */
function intervalMs(seconds: unknown, fallback: number): number {
  return typeof seconds === "number" && seconds > 0 ? seconds * 1000 : fallback;
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  // One read of the APR poll intervals for every page.
  const [intervals, setIntervals] = useState(DEFAULT_INTERVALS);
  useEffect(() => {
    fetchJson<UiConfig>("/api/pipeline/config")
      .then((c) =>
        setIntervals({
          refresh: intervalMs(c.refresh_seconds, DEFAULT_INTERVALS.refresh),
          passport: intervalMs(c.passport_refresh_seconds, DEFAULT_INTERVALS.passport),
        }),
      )
      .catch(() => {}); // keep the defaults; each page shows its own poll errors
  }, []);
  return (
    <RefreshContext.Provider value={intervals}>
    <div className="h-screen flex flex-col md:flex-row bg-[var(--bg-base)] text-[var(--text-primary)]">
      {/* A sidebar from md up; on a phone a top bar of the built pages. */}
      <nav className="shrink-0 flex items-center md:items-stretch md:flex-col md:w-48 border-b md:border-b-0 md:border-r border-[var(--border-subtle)] bg-[var(--bg-surface)]">
        <div className="flex items-center gap-2.5 px-4 py-3 md:py-5">
          <Logo />
          <span className="font-display text-base font-extrabold tracking-tight">
            Indic<span className="text-[var(--accent-cyan)]">Agent</span>
          </span>
        </div>
        <ul className="flex-1 flex md:block overflow-x-auto px-2 gap-0.5 md:space-y-0.5 text-sm">
          {NAV.map((item) => {
            if (item.href) {
              const current = isCurrent(pathname, item.href);
              return (
                <li key={item.label}>
                  <Link
                    href={item.href}
                    className={cn(
                      "flex items-center gap-2.5 rounded-lg px-2 py-1.5 transition-colors",
                      current
                        ? "bg-[var(--bg-elevated)] text-[var(--text-primary)]"
                        : "text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]",
                    )}
                  >
                    <item.icon size={15} className={current ? "text-[var(--accent-cyan)]" : undefined} />
                    {item.label}
                  </Link>
                </li>
              );
            }
            return (
              <li
                key={item.label}
                className="hidden md:flex items-center gap-2.5 px-2 py-1.5 text-[var(--text-muted)]"
              >
                <item.icon size={15} />
                <span className="flex-1">{item.label}</span>
                <span className="text-[0.6rem] uppercase tracking-wider">next</span>
              </li>
            );
          })}
        </ul>
        <div className="hidden md:block px-4 py-3 text-[0.65rem] text-[var(--text-muted)]">read-only, UTC</div>
      </nav>
      <main className="flex-1 overflow-auto">{children}</main>
    </div>
    </RefreshContext.Provider>
  );
}
