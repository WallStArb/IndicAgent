# Signal Banner Redesign Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Shrink the `OutcomeBadge` for banner use and redesign `SignalBanner` into a two-line layout with clear signal hierarchy.

**Architecture:** Two isolated component edits. `signal-panel.tsx` gains a `small` boolean prop on `OutcomeBadge`. `signal-banner.tsx` replaces its single-row token soup with a structured two-line layout — trade info on line 1, context on line 2.

**Tech Stack:** React, TypeScript, Tailwind CSS. No backend changes. No test runner in dashboard (`tsconfig.json` excludes `__tests__`), so verification is lint + visual confirmation in dev server.

**Spec:** `docs/superpowers/specs/2026-03-12-signal-banner-redesign.md`

---

## Chunk 1: OutcomeBadge small prop

### Task 1: Add `small` prop to `OutcomeBadge`

**Files:**
- Modify: `dashboard/src/components/signal-panel.tsx`

- [ ] **Step 1: Read the current file**

```bash
cat dashboard/src/components/signal-panel.tsx
```

- [ ] **Step 2: Add `small` prop**

Replace `OutcomeBadgeProps` and the className logic:

```tsx
interface OutcomeBadgeProps {
  outcome?: string;
  small?: boolean;
}

function OutcomeBadge({ outcome, small }: OutcomeBadgeProps) {
  if (!outcome) return null;

  const label = OUTCOME_LABEL_MAP[outcome] ?? outcome.toUpperCase();

  const colorClass =
    label.includes("HIT") || label.includes("TARGET")
      ? "bg-green-600"
      : label === "STOPPED"
        ? "bg-red-600"
        : "bg-gray-600";

  const sizeClass = small
    ? "text-[0.45rem] px-1 py-0.5 rounded-sm"
    : "text-xs px-2 py-1 rounded";

  return (
    <div className={`${colorClass} ${sizeClass} text-white font-bold inline-block`}>
      {label}
    </div>
  );
}
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd dashboard && npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors related to `signal-panel.tsx`.

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/components/signal-panel.tsx
git commit -m "feat(dashboard): add small prop to OutcomeBadge for banner use"
```

---

## Chunk 2: SignalBanner two-line layout

### Task 2: Rewrite SignalBanner layout

**Files:**
- Modify: `dashboard/src/components/signal-banner.tsx`

- [ ] **Step 1: Read the current file**

```bash
cat dashboard/src/components/signal-banner.tsx
```

- [ ] **Step 2: Add `fmtSignalType` helper and rewrite the JSX**

Replace the full file with the content below. **Note:** this intentionally removes the `Tooltip` wrappers and the `signal-tooltips` import block that existed in the old single-row layout — the new two-line structure provides hierarchy without tooltips on every token. It also removes the `barCloseStr`, `bar_close_price`, and `market_price_at_signal` display tokens (superseded by the cleaner line 2).

```tsx
// dashboard/src/components/signal-banner.tsx
"use client";

import type { SignalData } from "@/lib/types";
import { fmtPrice, fmtPriceRange, fmtNum, fmtTimeHMS, fmtLagSeconds, pipelineLagS } from "@/lib/format";
import { TrendingUp, TrendingDown, ChevronRight } from "lucide-react";
import { useMemo } from "react";
import { deriveBarCloseIso } from "@/lib/timeframe-utils";
import { OutcomeBadge } from "@/components/signal-panel";

interface SignalBannerProps {
  signal: SignalData | null;
  onDrillDown?: () => void;
}

const HIGH_CONFIDENCE_THRESHOLD = 0.75;

function fmtSignalType(raw: string): string {
  return raw.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function SignalBanner({ signal, onDrillDown }: SignalBannerProps) {
  const isLong = signal?.direction === "long";
  const color = isLong ? "var(--green)" : "var(--red)";
  const dimColor = isLong ? "var(--green-dim)" : "var(--red-dim)";
  const Icon = isLong ? TrendingUp : TrendingDown;

  const barCloseIso = useMemo(
    () => signal ? deriveBarCloseIso(signal.bar_close_ts, signal.timestamp, signal.timeframe) : undefined,
    [signal?.bar_close_ts, signal?.timestamp, signal?.timeframe]
  );
  const signalTimeStr = useMemo(() => fmtTimeHMS(signal?.signal_computed_at), [signal?.signal_computed_at]);
  const ttsS = useMemo(
    () => signal ? (pipelineLagS(signal.signal_computed_at, barCloseIso) ?? (signal.pipeline_lag_s ?? null)) : null,
    [signal?.signal_computed_at, barCloseIso, signal?.pipeline_lag_s]
  );
  const ttsStr = useMemo(() => fmtLagSeconds(ttsS), [ttsS]);

  if (!signal || signal.confidence < HIGH_CONFIDENCE_THRESHOLD) return null;

  const hasZone = signal.entry_zone_low != null && signal.entry_zone_high != null;
  const hasLine2 = hasZone || !!signalTimeStr;

  return (
    <div className={signal.resolved ? "opacity-50" : undefined}>
      <button
        onClick={onDrillDown}
        className="w-full flex flex-col px-2 py-1 cursor-pointer"
        style={{
          backgroundColor: dimColor,
          borderBottom: `1px solid ${color}33`,
        }}
      >
        {/* Line 1: trade info */}
        <div className="flex items-center gap-1.5 w-full">
          {signal.resolved && <OutcomeBadge outcome={signal.outcome} small />}
          <Icon size={10} style={{ color }} />
          <span
            className="text-[0.55rem] font-bold uppercase tracking-widest"
            style={{ color }}
          >
            {isLong ? "LONG" : "SHORT"}
          </span>
          <span className="text-[0.55rem] font-data" style={{ color }}>
            @ {fmtPrice(signal.entry_price)}
          </span>
          <span className="text-[0.5rem] text-[var(--text-muted)]">
            ({fmtNum(signal.confidence * 100, 0)}% {fmtSignalType(signal.signal_type)})
          </span>
          <span className="text-[0.5rem] text-[var(--text-muted)]">
            | SL: {fmtPrice(signal.stop_loss)}
          </span>
          {signal.profit_target != null && (
            <span className="text-[0.5rem] text-[var(--text-muted)]">
              | T1: {fmtPrice(signal.profit_target)}
              {signal.rr_t1 != null && ` (${fmtNum(signal.rr_t1, 1)}R)`}
            </span>
          )}
          <ChevronRight size={8} className="ml-auto text-[var(--text-muted)]" />
        </div>

        {/* Line 2: zone + timing context */}
        {hasLine2 && (
          <div className="flex items-center gap-1 text-[0.45rem] font-data text-[var(--text-muted)] opacity-70 mt-0.5">
            {hasZone && (
              <span>Zone: {fmtPriceRange(signal.entry_zone_low!, signal.entry_zone_high!)}</span>
            )}
            {hasZone && signalTimeStr && (
              <span className="opacity-50">|</span>
            )}
            {signalTimeStr && (
              <span>
                Sig: {signalTimeStr}
                {ttsStr && ` (${ttsStr})`}
              </span>
            )}
          </div>
        )}
      </button>
    </div>
  );
}
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd dashboard && npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors.

- [ ] **Step 4: Visual verification in dev server**

Dev server is running at http://localhost:3000. Open the dashboard and confirm:
- Line 1 shows: direction icon + `SHORT @ {price} ({confidence}% {Type}) | SL: {price} | T1: {price} ({R}R)`
- Line 2 shows (muted): `Zone: {low}–{high} | Sig: {time} (+Xs)` when zone/signal time available
- Resolved signals: small badge visible, banner at 50% opacity
- Drill-panel `OutcomeBadge` still renders at full size (no `small` prop passed there)

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/components/signal-banner.tsx
git commit -m "feat(dashboard): two-line signal banner — trade info + zone/timing context"
```
