# Signal Trade Card Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat KV-pair signal body in the drill panel with a purpose-built trade card showing a price ladder, CIS bucket breakdown, and setup edge in one scannable view.

**Architecture:** New file `signal-trade-card.tsx` contains three sub-components (`TradePriceLadder`, `CISBucketBreakdown`, `SetupEdgeLine`) composed into `SignalTradeCard`. `signal-detail.tsx` keeps its outer structure (header, confidence pipeline, swarm) but replaces the middle section with `<SignalTradeCard signal={signal} />`. `CISBucketBreakdown` lazy-fetches bucket scores from `/api/signals/detail/{id}` — same pattern as `SignalSwarmBreakdown`.

**Tech Stack:** React 19, TypeScript, Tailwind CSS v4, Next.js 16, `lucide-react`, existing `@/lib/format` + `@/lib/signal-utils` + `@/lib/api` utilities.

---

## File Map

| File | Action |
|------|--------|
| `dashboard/src/components/signal/signal-trade-card.tsx` | Create — `SignalTradeCard`, `TradePriceLadder`, `CISBucketBreakdown`, `SetupEdgeLine` |
| `dashboard/src/components/signal/signal-detail.tsx` | Modify — replace middle section with `<SignalTradeCard />` |

---

## Task 1: Create `signal-trade-card.tsx` with `TradePriceLadder` and `SetupEdgeLine`

These two sub-components require zero fetches — all data is in `SignalData`.

**Files:**
- Create: `dashboard/src/components/signal/signal-trade-card.tsx`

- [ ] **Step 1: Create the file with `TradePriceLadder`**

The ladder builds a sorted list of price levels (SL, ENTRY, T1/T2/T3, zone edges) and renders them high → low. The entry zone renders as a shaded band inserted between its price bounds.

```tsx
"use client";

import { useState, useEffect } from "react";
import type { SignalData } from "@/lib/types";
import { fmtPrice, fmtNum } from "@/lib/format";
import { abbreviatePlugin } from "@/lib/signal-utils";
import { getApiBase } from "@/lib/api";

const BUCKET_ORDER = ["trend", "momentum", "structure", "institutional", "regime", "pattern"];

// ── Price Ladder ──────────────────────────────────────────────────────────────

type LevelKind = "target" | "entry" | "stop" | "zone_edge";

type LevelItem = {
  id: string;
  kind: LevelKind;
  label: string;
  price: number;
  r: number | null;
  targetLabel?: string;
  zoneEdge?: "high" | "low";
  inZone?: boolean;
};

function buildLevels(signal: SignalData): LevelItem[] {
  const {
    direction, entry_price: entry, stop_loss: stop,
    profit_target: t1, profit_target_2: t2, profit_target_3: t3,
    target_labels, rr_t1, rr_t2, rr_t3,
    entry_zone_low, entry_zone_high, zone_valid_at_signal,
  } = signal;

  const isLong = direction === "long";
  const risk = Math.abs(entry - stop);
  const rAt = (p: number): number =>
    risk > 0 ? (isLong ? (p - entry) / risk : (entry - p) / risk) : 0;

  const items: LevelItem[] = [
    { id: "entry", kind: "entry", label: "ENTRY", price: entry, r: null },
    { id: "sl", kind: "stop", label: "SL", price: stop, r: -1 },
  ];

  if (t1 != null) items.push({ id: "t1", kind: "target", label: "T1", price: t1, r: rr_t1 ?? rAt(t1), targetLabel: target_labels?.[0] });
  if (t2 != null) items.push({ id: "t2", kind: "target", label: "T2", price: t2, r: rr_t2 ?? rAt(t2), targetLabel: target_labels?.[1] });
  if (t3 != null) items.push({ id: "t3", kind: "target", label: "T3", price: t3, r: rr_t3 ?? rAt(t3), targetLabel: target_labels?.[2] });

  if (entry_zone_high != null) {
    items.push({ id: "zone_h", kind: "zone_edge", label: "ZONE", price: entry_zone_high, r: rAt(entry_zone_high), zoneEdge: "high", inZone: zone_valid_at_signal });
  }
  if (entry_zone_low != null) {
    items.push({ id: "zone_l", kind: "zone_edge", label: "ZONE", price: entry_zone_low, r: rAt(entry_zone_low), zoneEdge: "low", inZone: zone_valid_at_signal });
  }

  return items.sort((a, b) => b.price - a.price);
}

const DOT_COLOR: Record<LevelKind, string> = {
  target: "var(--green)",
  entry: "var(--blue)",
  stop: "var(--red)",
  zone_edge: "var(--amber)",
};

const LABEL_COLOR: Record<LevelKind, string> = {
  target: "var(--green)",
  entry: "var(--text-primary)",
  stop: "var(--red)",
  zone_edge: "var(--amber)",
};

function TradePriceLadder({ signal }: { signal: SignalData }) {
  const levels = buildLevels(signal);
  const { framing_method, direction } = signal;
  const isLong = direction === "long";

  // Detect if a level is "between" zone bounds for background shading
  const zoneHigh = signal.entry_zone_high;
  const zoneLow = signal.entry_zone_low;
  const inZoneBand = (price: number) =>
    zoneHigh != null && zoneLow != null && price <= zoneHigh && price >= zoneLow;

  return (
    <div>
      {/* Header row */}
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[0.48rem] font-bold uppercase tracking-widest text-[var(--text-muted)]">
          Price Ladder
        </span>
        {framing_method && (
          <span
            className="text-[0.45rem] font-bold uppercase tracking-widest px-1.5 py-0.5 rounded"
            style={{
              color: framing_method === "structural" ? "var(--green)" : "var(--amber)",
              border: `1px solid ${framing_method === "structural" ? "var(--green)" : "var(--amber)"}`,
              opacity: 0.7,
            }}
          >
            {framing_method === "structural" ? "structural" : "ATR fallback"}
          </span>
        )}
      </div>

      {/* Level rows */}
      <div className="flex flex-col gap-0">
        {levels.map((item) => {
          const isZoneEdge = item.kind === "zone_edge";
          const shaded = inZoneBand(item.price) && !isZoneEdge;

          return (
            <div
              key={item.id}
              className="flex items-center gap-2 text-[0.58rem] font-data px-1 py-0.5 rounded"
              style={{
                background: shaded
                  ? isLong ? "rgba(0,220,130,0.06)" : "rgba(255,71,87,0.06)"
                  : isZoneEdge ? isLong ? "rgba(0,220,130,0.08)" : "rgba(255,71,87,0.08)"
                  : undefined,
                borderLeft: isZoneEdge ? `2px solid ${isLong ? "var(--green)" : "var(--red)"}` : "2px solid transparent",
              }}
            >
              {/* Dot */}
              <span className="text-[0.5rem] shrink-0" style={{ color: DOT_COLOR[item.kind] }}>
                {item.kind === "entry" ? "●" : item.kind === "zone_edge" ? "◇" : "○"}
              </span>

              {/* Label */}
              <span
                className="w-[28px] font-bold text-[0.55rem] shrink-0"
                style={{ color: LABEL_COLOR[item.kind] }}
              >
                {item.label}
              </span>

              {/* Price */}
              <span className="flex-1 text-[var(--text-secondary)]">
                {fmtPrice(item.price)}
              </span>

              {/* Target label (e.g. "S/R", "Fib 0.236") */}
              {item.targetLabel && (
                <span className="text-[0.48rem] text-[var(--text-muted)] truncate max-w-[60px] text-right">
                  {item.targetLabel.split(" ")[0]}
                </span>
              )}

              {/* R multiple */}
              {item.r != null && (
                <span
                  className="text-[0.55rem] font-bold w-[36px] text-right shrink-0"
                  style={{ color: item.r >= 0 ? "var(--green)" : "var(--red)" }}
                >
                  {item.r >= 0 ? "+" : ""}{fmtNum(item.r, 1)}R
                </span>
              )}

              {/* Zone badge (IN ZONE / WAIT) — only on zone_high edge */}
              {isZoneEdge && item.zoneEdge === "high" && (
                <span
                  className="text-[0.42rem] font-bold uppercase tracking-widest px-1 py-0.5 rounded shrink-0"
                  style={{
                    color: item.inZone ? "var(--green)" : "var(--amber)",
                    border: `1px solid ${item.inZone ? "var(--green)" : "var(--amber)"}`,
                    opacity: 0.85,
                  }}
                >
                  {item.inZone ? "IN ZONE" : "WAIT"}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Setup Edge ────────────────────────────────────────────────────────────────

function SetupEdgeLine({ signal }: { signal: SignalData }) {
  const { setup_win_rate: wr, setup_avg_pnl_r: avgR, setup_plugin } = signal;
  if (wr == null) return null;

  const winColor = wr >= 0.5 ? "var(--green)" : wr >= 0.4 ? "var(--amber)" : "var(--red)";
  const avgRColor = avgR != null && avgR > 0 ? "var(--green)" : "var(--red)";

  return (
    <div className="flex items-center gap-3 text-[0.55rem] font-data">
      <span className="text-[var(--text-muted)] truncate flex-1">
        {abbreviatePlugin(setup_plugin)}
      </span>
      <span>
        Win{" "}
        <span className="font-bold" style={{ color: winColor }}>
          {fmtNum(wr * 100, 1)}%
        </span>
      </span>
      {avgR != null && (
        <span>
          Avg{" "}
          <span className="font-bold" style={{ color: avgRColor }}>
            {avgR >= 0 ? "+" : ""}{fmtNum(avgR, 2)}R
          </span>
        </span>
      )}
    </div>
  );
}

// ── CIS Bucket Breakdown (lazy fetch) ─────────────────────────────────────────

// Defined in Task 2 — placeholder export keeps TypeScript happy during Task 1
function CISBucketBreakdown({ signalId, cisScore }: { signalId?: string; cisScore?: number | null }) {
  return (
    <div className="text-[0.52rem] italic text-[var(--text-muted)]">
      {signalId ? "Loading CIS…" : "No CIS data"}
    </div>
  );
}

// ── SignalTradeCard ───────────────────────────────────────────────────────────

export function SignalTradeCard({ signal }: { signal: SignalData }) {
  return (
    <div className="flex flex-col gap-3">
      <TradePriceLadder signal={signal} />
      <div className="border-t border-[var(--border-subtle)]" />
      <CISBucketBreakdown signalId={signal.signal_id} cisScore={signal.cis_score} />
      <div className="border-t border-[var(--border-subtle)]" />
      <SetupEdgeLine signal={signal} />
    </div>
  );
}
```

- [ ] **Step 2: TypeScript check**

```bash
cd /home/bg/dev/indicagent/dashboard && npx tsc --noEmit 2>&1 | head -40
```

Expected: no errors. If there are errors, fix them before continuing.

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/components/signal/signal-trade-card.tsx
git commit -m "feat(dashboard): add signal-trade-card with price ladder and setup edge"
```

---

## Task 2: Implement `CISBucketBreakdown` with lazy fetch

Replace the placeholder `CISBucketBreakdown` in `signal-trade-card.tsx` with the real implementation. The detail API returns `bucket_scores: Record<string, number> | null` alongside other fields.

**Files:**
- Modify: `dashboard/src/components/signal/signal-trade-card.tsx`

- [ ] **Step 1: Replace the placeholder `CISBucketBreakdown` function**

Find and replace the entire `CISBucketBreakdown` function (the placeholder from Task 1) with:

```tsx
function CISBucketBreakdown({ signalId, cisScore }: { signalId?: string; cisScore?: number | null }) {
  const [buckets, setBuckets] = useState<Record<string, number> | null | "loading">("loading");

  useEffect(() => {
    if (!signalId) { setBuckets(null); return; }
    fetch(`${getApiBase()}/api/signals/detail/${signalId}`)
      .then(r => r.ok ? r.json() : null)
      .then(d => setBuckets(d?.bucket_scores ?? null))
      .catch(() => setBuckets(null));
  }, [signalId]);

  const scoreColor = cisScore != null
    ? cisScore >= 0 ? "var(--green)" : "var(--red)"
    : "var(--text-muted)";

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[0.48rem] font-bold uppercase tracking-widest text-[var(--text-muted)]">
          CIS Breakdown
        </span>
        {cisScore != null && (
          <span className="text-[0.55rem] font-bold font-data" style={{ color: scoreColor }}>
            {cisScore >= 0 ? "+" : ""}{fmtNum(cisScore, 2)}
          </span>
        )}
      </div>

      {/* Skeleton while loading */}
      {buckets === "loading" && (
        <div className="flex flex-col gap-1">
          {[60, 40, 75, 30, 50, 45].map((w, i) => (
            <div key={i} className="flex items-center gap-1.5">
              <div className="w-[68px] h-2 rounded bg-[var(--bg-elevated)] animate-pulse" />
              <div className="flex-1 h-1.5 rounded bg-[var(--bg-elevated)] animate-pulse" style={{ maxWidth: `${w}%` }} />
              <div className="w-[28px] h-2 rounded bg-[var(--bg-elevated)] animate-pulse" />
            </div>
          ))}
        </div>
      )}

      {/* No data */}
      {buckets === null && (
        <span className="text-[0.52rem] italic text-[var(--text-muted)]">No CIS breakdown</span>
      )}

      {/* Bucket bars */}
      {buckets !== null && buckets !== "loading" && (() => {
        const sorted = BUCKET_ORDER
          .filter(k => k in buckets)
          .map(k => ({ key: k, val: buckets[k] }))
          .sort((a, b) => Math.abs(b.val) - Math.abs(a.val));

        return (
          <div className="flex flex-col gap-1">
            {sorted.map(({ key, val }) => (
              <div key={key} className="flex items-center gap-1.5">
                <span className="text-[0.48rem] text-[var(--text-muted)] w-[68px] shrink-0 capitalize">
                  {key}
                </span>
                <div className="flex-1 h-1.5 rounded overflow-hidden bg-[var(--bg-elevated)]">
                  <div
                    className="h-full rounded"
                    style={{
                      width: `${Math.min(100, Math.abs(val) * 100)}%`,
                      backgroundColor: val >= 0 ? "var(--green)" : "var(--red)",
                    }}
                  />
                </div>
                <span
                  className="text-[0.5rem] font-data w-[32px] text-right shrink-0 font-bold"
                  style={{ color: val >= 0 ? "var(--green)" : "var(--red)" }}
                >
                  {val >= 0 ? "+" : ""}{fmtNum(val, 2)}
                </span>
              </div>
            ))}
          </div>
        );
      })()}
    </div>
  );
}
```

- [ ] **Step 2: TypeScript check**

```bash
cd /home/bg/dev/indicagent/dashboard && npx tsc --noEmit 2>&1 | head -40
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/components/signal/signal-trade-card.tsx
git commit -m "feat(dashboard): implement CIS bucket breakdown with lazy fetch"
```

---

## Task 3: Wire `SignalTradeCard` into `signal-detail.tsx`

Replace the flat KV-pair body in `signal-detail.tsx` with `<SignalTradeCard />`. Keep header, confidence pipeline, and swarm breakdown.

**Files:**
- Modify: `dashboard/src/components/signal/signal-detail.tsx`

- [ ] **Step 1: Rewrite `signal-detail.tsx`**

Replace the entire file content with:

```tsx
"use client";

import type { SignalData } from "@/lib/types";
import { SignalDetailHeader } from "./signal-detail-header";
import { SignalConfidencePipeline } from "./signal-confidence-pipeline";
import { SignalTradeCard } from "./signal-trade-card";
import { SignalSwarmBreakdown } from "./signal-swarm-breakdown";

export function SignalDetail({ signal }: { signal: SignalData }) {
  const isLong = signal.direction === "long";
  const dirColor = isLong ? "var(--green)" : "var(--red)";

  return (
    <div className="flex flex-col gap-3">
      <SignalDetailHeader signal={signal} dirColor={dirColor} />
      <SignalConfidencePipeline signal={signal} />
      <div className="border-t border-[var(--border-subtle)]" />
      <SignalTradeCard signal={signal} />
      {signal.signal_id && (
        <div className="border-t border-[var(--border-subtle)] pt-2">
          <SignalSwarmBreakdown signalId={signal.signal_id} />
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: TypeScript check**

```bash
cd /home/bg/dev/indicagent/dashboard && npx tsc --noEmit 2>&1 | head -40
```

Expected: no errors.

- [ ] **Step 3: Start dev server and verify visually**

```bash
cd /home/bg/dev/indicagent/dashboard && npm run dev
```

Open http://localhost:3000, click any row with a signal (ES, NQ on 5m), open the drill panel. Verify:
- Price ladder shows SL / ENTRY / T1 / T2 rows sorted high → low
- Each row has dot, label, price, and R value (e.g. `+2.1R`)
- Framing badge appears top-right of ladder (`structural` green / `ATR fallback` amber)
- Entry zone band appears with `IN ZONE` or `WAIT` badge if zone data present
- CIS buckets load with skeleton then render bars sorted by magnitude
- Setup edge line shows win % and avg R (or is absent if no sample data)
- Swarm breakdown remains at bottom

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/components/signal/signal-detail.tsx
git commit -m "feat(dashboard): wire signal-trade-card into drill panel — price ladder, CIS buckets, setup edge"
```

---

## Task 4: Done-coding SOP

- [ ] **Step 1: Run code-simplifier agent** on changed files (`signal-trade-card.tsx`, `signal-detail.tsx`)

- [ ] **Step 2: Run /review**

- [ ] **Step 3: Run Python unit tests** (frontend has no test suite)

```bash
cd /home/bg/dev/indicagent && .venv/bin/pytest tests/unit/ -q
```

Expected: all pass (no Python files changed; verifying nothing broken).

- [ ] **Step 4: Fast-forward merge and push**

```bash
git checkout main && git merge --ff-only <feature-branch>
git push origin main
```
