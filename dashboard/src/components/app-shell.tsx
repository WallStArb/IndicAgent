"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { DEFAULT_REFRESH_MS, RefreshContext } from "@/hooks/use-api";
import { fetchJson } from "@/lib/api";
import type { UiConfig } from "@/lib/types";
import { cn } from "@/lib/utils";

// One entry per DAG stage page (design: docs/plans/2026-10-26-dashboard-v35-cockpit-design.md).
// Entries without an href are later slices, listed so the shape of the cockpit is visible.
const NAV: { label: string; href?: string }[] = [
  { label: "Pipeline", href: "/" },
  { label: "Data" },
  { label: "Instruments" },
  { label: "Concepts" },
  { label: "Research" },
  { label: "Books" },
  { label: "System", href: "/system" },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  // One read of the APR poll interval for every page (ui.dashboard.refresh_seconds).
  const [refreshMs, setRefreshMs] = useState(DEFAULT_REFRESH_MS);
  useEffect(() => {
    fetchJson<UiConfig>("/api/pipeline/config")
      .then((c) => setRefreshMs(c.refresh_seconds * 1000))
      .catch(() => {}); // keep the default; each page shows its own poll errors
  }, []);
  return (
    <RefreshContext.Provider value={refreshMs}>
    <div className="h-screen flex bg-[var(--bg-base)] text-[var(--text-primary)]">
      <nav className="w-44 shrink-0 border-r border-[var(--border-subtle)] bg-[var(--bg-surface)] flex flex-col">
        <div className="px-4 py-4 text-sm font-semibold tracking-tight">
          Indic<span className="text-[var(--accent-cyan)]">Agent</span>
        </div>
        <ul className="flex-1 px-2 space-y-0.5 text-sm">
          {NAV.map((item) =>
            item.href ? (
              <li key={item.label}>
                <Link
                  href={item.href}
                  className={cn(
                    "block rounded px-2 py-1.5 transition-colors",
                    pathname === item.href
                      ? "bg-[var(--bg-elevated)] text-[var(--text-primary)]"
                      : "text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]",
                  )}
                >
                  {item.label}
                </Link>
              </li>
            ) : (
              <li
                key={item.label}
                className="flex items-center justify-between px-2 py-1.5 text-[var(--text-muted)]"
              >
                {item.label}
                <span className="text-[0.6rem] uppercase tracking-wider">next</span>
              </li>
            ),
          )}
        </ul>
        <div className="px-4 py-3 text-[0.65rem] text-[var(--text-muted)]">read-only, UTC</div>
      </nav>
      <main className="flex-1 overflow-auto">{children}</main>
    </div>
    </RefreshContext.Provider>
  );
}
