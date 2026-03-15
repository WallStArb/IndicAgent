// dashboard/src/components/skeleton-card.tsx
"use client";

import { symbolConfig } from "@/lib/symbol-config";

/** Stable placeholder card rendered while waiting for first SSE data.
 *  Same outer dimensions as SymbolCard so the layout doesn't jump on hydration. */
export function SkeletonCard({ symbol }: { symbol: string }) {
  const info = symbolConfig.getSymbolInfo(symbol);
  const displayName = info?.display_name ?? symbol;
  const contract = info?.contract ?? symbol;

  return (
    <div className="flex flex-col surface rounded overflow-hidden opacity-50">
      {/* Header row */}
      <div className="flex items-center justify-between px-3 pt-1.5 pb-0.5 bg-[var(--bg-elevated)]">
        <div className="flex items-baseline gap-2">
          <span className="text-sm font-bold text-[var(--text-primary)] tracking-tight">{displayName}</span>
          <span className="text-[0.6rem] font-semibold text-[var(--text-muted)] uppercase tracking-wider">{symbol}</span>
        </div>
        <span className="text-[0.55rem] font-medium text-[var(--text-muted)] bg-[var(--bg-base)] px-1.5 py-0.5 rounded">
          {contract}
        </span>
      </div>

      {/* Price area skeleton */}
      <div className="bg-[var(--bg-elevated)] border-b border-[var(--border-subtle)] px-3 py-3">
        <div className="flex items-baseline gap-3">
          {/* Big price shimmer */}
          <div className="h-6 w-24 rounded bg-[var(--bg-hover)] animate-pulse" />
          <div className="h-3.5 w-14 rounded bg-[var(--bg-hover)] animate-pulse" />
          <div className="h-3.5 w-14 rounded bg-[var(--bg-hover)] animate-pulse" />
        </div>
        <div className="mt-2 flex gap-2">
          <div className="h-2.5 w-10 rounded bg-[var(--bg-hover)] animate-pulse" />
          <div className="h-2.5 w-10 rounded bg-[var(--bg-hover)] animate-pulse" />
          <div className="h-2.5 w-10 rounded bg-[var(--bg-hover)] animate-pulse" />
          <div className="flex-1 h-2.5 rounded bg-[var(--bg-hover)] animate-pulse" />
        </div>
      </div>

      {/* TF matrix shimmer */}
      <div className="flex items-center gap-1.5 px-2 py-2 border-b border-[var(--border-subtle)] bg-[var(--bg-elevated)]">
        {["1m","5m","15m","1H","4H","1D"].map((tf) => (
          <div key={tf} className="h-4 w-6 rounded bg-[var(--bg-hover)] animate-pulse" />
        ))}
      </div>

      {/* Tier rows shimmer */}
      {[40, 32, 28, 32, 28, 32].map((h, i) => (
        <div
          key={i}
          className="px-2 border-t border-[var(--border-subtle)]"
          style={{ height: `${h}px` }}
        >
          <div className="flex items-center gap-2 h-full">
            <div className="h-2.5 w-8 rounded bg-[var(--bg-hover)] animate-pulse" />
            <div className="flex-1 h-2.5 rounded bg-[var(--bg-hover)] animate-pulse" />
          </div>
        </div>
      ))}
    </div>
  );
}
