# Price Hero Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Unify the split price block + PriceHero component into a single clean 3-line layout showing live price, bid/ask, and session OHL+range bar with session volume.

**Architecture:** Remove the inline price block from `trading-dashboard.tsx` and rewrite `PriceHero` to own the full price section. Add `sessionVolume` accumulation to the stream hook. The LONG/SHORT badge and card glow remain unchanged.

**Tech Stack:** React, TypeScript, Tailwind CSS, SSE stream hook

**Design doc:** `docs/plans/2026-02-25-price-hero-redesign.md`

---

## Target Layout

```
[5978.50 flash]  [+5.25 (+0.09%)]  [vol 1.2M]   [SHORT 73%]  ← badge unchanged
[Bid 5978.25  Ask 5978.50  spd 0.25              as of 10:45]
[O 5970.25  H 5983.50  L 5965.00  ━━●━━━━━━━━━━━━━━━━━━━]
```

---

### Task 1: Add `sessionVolume` to `SessionState` type

**Files:**
- Modify: `dashboard/src/lib/types.ts`

**Step 1: Add the field**

In `SessionState` (around line 12), add `sessionVolume`:

```typescript
export interface SessionState {
  open: number;
  high: number;
  low: number;
  date: string; // "YYYY-MM-DD" for reset detection
  sessionVolume: number; // accumulated bar volumes for current session
}
```

**Step 2: Fix the initialiser in `use-market-stream.ts`**

Search for `session: { open: 0, high: 0, low: 0, date: "" }` (around line 36) and add the new field:

```typescript
session: { open: 0, high: 0, low: 0, date: "", sessionVolume: 0 },
```

**Step 3: Verify TypeScript compiles**

```bash
cd dashboard && npx tsc --noEmit 2>&1 | head -20
```

Expected: errors only about `sessionVolume` not yet set in `market_data` handler (fixed in Task 2). No other errors.

**Step 4: Commit**

```bash
git add dashboard/src/lib/types.ts dashboard/src/hooks/use-market-stream.ts
git commit -m "feat(price-hero): add sessionVolume to SessionState type"
```

---

### Task 2: Accumulate session volume in the stream hook

**Files:**
- Modify: `dashboard/src/hooks/use-market-stream.ts` (around line 308 — `market_data` handler)

**Step 1: Update the `newSession` block to accumulate volume**

Find the `market_data` SSE handler. The `newSession` object is built around line 308. Update it:

```typescript
const barVol = parseFloat(String(payload.volume || 0));
const isNewSession = barDate !== "" && barDate !== sess.date;
const newSession: SessionState = isNewSession
  ? { open: barOpen, high: barHigh, low: barLow, date: barDate, sessionVolume: barVol }
  : sess.date === ""
    ? { open: barOpen, high: barHigh, low: barLow, date: barDate, sessionVolume: barVol }
    : {
        open: sess.open,
        high: Math.max(sess.high, barHigh),
        low: Math.min(sess.low > 0 ? sess.low : barLow, barLow),
        date: barDate,
        sessionVolume: sess.sessionVolume + barVol,
      };
```

Note: `barVol` replaces the existing `parseFloat(String(payload.volume || 0))` used for `bar.volume` — extract it to a variable instead of repeating.

**Step 2: Verify TypeScript compiles clean**

```bash
cd dashboard && npx tsc --noEmit 2>&1 | head -20
```

Expected: 0 errors.

**Step 3: Commit**

```bash
git add dashboard/src/hooks/use-market-stream.ts
git commit -m "feat(price-hero): accumulate sessionVolume from bar events"
```

---

### Task 3: Rewrite `PriceHero` component

**Files:**
- Modify: `dashboard/src/components/price-hero.tsx`

The component receives `data: SymbolData` and `activeTf: string` (unchanged props).

**Step 1: Replace the full file content**

New layout — 3 lines with inline range bar on OHL row:

```typescript
"use client";

import type { SymbolData } from "@/lib/types";
import { fmtPrice, fmtCompact } from "@/lib/format";

interface PriceHeroProps {
  data: SymbolData;
  activeTf: string;
}

function clampRatio(value: number, lo: number, hi: number): number | null {
  if (hi <= lo) return null;
  return Math.min(1, Math.max(0, (value - lo) / (hi - lo)));
}

function fmtTime(ts: string | number | undefined): string {
  if (!ts) return "";
  try {
    const d = new Date(ts);
    if (isNaN(d.getTime())) return "";
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
  } catch {
    return "";
  }
}

/** Compact inline range bar — dot showing price position within session envelope */
function InlineRangeBar({ ratio }: { ratio: number | null }) {
  return (
    <div className="relative flex-1 h-1 rounded-full bg-[var(--border-subtle)] overflow-visible">
      {ratio === null ? (
        <div className="absolute inset-0 rounded-full bg-[var(--border-default)] opacity-40" />
      ) : (
        <div
          className="absolute top-1/2 -translate-y-1/2 w-1.5 h-1.5 rounded-full bg-[var(--text-accent)] shadow-sm"
          style={{ left: `calc(${ratio * 100}% - 3px)` }}
        />
      )}
    </div>
  );
}

export function PriceHero({ data, activeTf }: PriceHeroProps) {
  const { tick, bar, session } = data;
  const indicators = data.indicatorsByTf[activeTf] ?? null;

  const isEmpty = tick.price === 0 || tick.lastUpdate === 0;
  const price = isEmpty ? 0 : tick.price;
  const bid = isEmpty ? 0 : tick.bid;
  const ask = isEmpty ? 0 : tick.ask;

  const sessionOpen = session.open;
  const chg = sessionOpen > 0 && price > 0 ? price - sessionOpen : null;
  const chgPct = sessionOpen > 0 && price > 0 ? ((price - sessionOpen) / sessionOpen) * 100 : null;

  const sessionRatio = isEmpty || session.high <= session.low
    ? null
    : clampRatio(price, session.low, session.high);

  const indicatorBarTime = fmtTime(indicators?.timestamp);
  const barTime = fmtTime(bar.timestamp);
  const displayTime = indicatorBarTime || barTime;

  const sessionVol = session.sessionVolume > 0 ? fmtCompact(session.sessionVolume) : null;

  function chgColor(v: number | null): string {
    if (v === null) return "text-[var(--text-muted)]";
    if (v > 0) return "text-[var(--green)]";
    if (v < 0) return "text-[var(--red)]";
    return "text-[var(--text-muted)]";
  }

  return (
    <div className="px-3 pt-1.5 pb-2 space-y-1.5">
      {/* Line 1: Big price + session change + volume */}
      <div className="flex items-baseline gap-1.5">
        <span
          key={data.tickFlash ?? "base"}
          className={`font-data text-xl font-semibold leading-none tracking-tight ${
            price > 0 && sessionOpen > 0 && price > sessionOpen
              ? "text-[var(--green)]"
              : price > 0 && sessionOpen > 0 && price < sessionOpen
                ? "text-[var(--red)]"
                : "text-[var(--text-primary)]"
          } ${
            data.tickFlash === "up" ? "price-flash-up" : data.tickFlash === "down" ? "price-flash-down" : ""
          }`}
        >
          {price > 0 ? fmtPrice(price) : "—"}
        </span>
        {chg !== null && (
          <span className={`font-data text-[0.65rem] ${chgColor(chg)}`}>
            {chg >= 0 ? "+" : ""}{chg.toFixed(2)}
            {chgPct !== null && (
              <span className="ml-0.5 opacity-80">
                ({chgPct >= 0 ? "+" : ""}{chgPct.toFixed(2)}%)
              </span>
            )}
          </span>
        )}
        {sessionVol && (
          <span className="font-data text-[0.5rem] text-[var(--text-muted)] ml-1">
            vol {sessionVol}
          </span>
        )}
      </div>

      {/* Line 2: Bid / Ask / spread + timestamp */}
      <div className="flex items-center gap-3 font-data text-[0.6rem]">
        <span>
          <span className="text-[var(--text-muted)]">Bid </span>
          <span className="text-[var(--red)] tabular-nums">
            {isEmpty || bid === 0 ? "—" : fmtPrice(bid)}
          </span>
        </span>
        <span>
          <span className="text-[var(--text-muted)]">Ask </span>
          <span className="text-[var(--green)] tabular-nums">
            {isEmpty || ask === 0 ? "—" : fmtPrice(ask)}
          </span>
        </span>
        {!isEmpty && bid > 0 && ask > 0 && (
          <span className="text-[var(--text-muted)] tabular-nums">
            spd {fmtPrice(ask - bid)}
          </span>
        )}
        {displayTime && (
          <span className="ml-auto font-data text-[0.5rem] text-[var(--text-muted)] opacity-70">
            as of {displayTime}
          </span>
        )}
      </div>

      {/* Line 3: Session O/H/L + inline range bar */}
      {session.high > 0 && (
        <div className="flex items-center gap-2 font-data text-[0.5rem] text-[var(--text-muted)]">
          <span>O&nbsp;{fmtPrice(session.open)}</span>
          <span className="text-[var(--green)]">H&nbsp;{fmtPrice(session.high)}</span>
          <span className="text-[var(--red)]">L&nbsp;{fmtPrice(session.low)}</span>
          <InlineRangeBar ratio={sessionRatio} />
        </div>
      )}
    </div>
  );
}
```

**Step 2: Check TypeScript**

```bash
cd dashboard && npx tsc --noEmit 2>&1 | head -20
```

Expected: 0 errors.

**Step 3: Commit**

```bash
git add dashboard/src/components/price-hero.tsx
git commit -m "feat(price-hero): 3-line layout — price+vol, bid/ask, session OHL+bar"
```

---

### Task 4: Remove inline price block from `trading-dashboard.tsx`

The card currently renders a price block in `trading-dashboard.tsx` (the `flex items-center justify-between` row with big price, session change, and OHL — around lines 222–270) then renders `<PriceHero>` below it. Now that `PriceHero` owns the full price section, remove the old block.

**Files:**
- Modify: `dashboard/src/components/trading-dashboard.tsx`

**Step 1: Remove the old price+signal row**

Delete the entire `{/* Price + signal summary row */}` block (lines ~222–270 — the `<div className="flex items-center justify-between ...">` containing the big price, session change, session OHL, and the LONG/SHORT badge).

**Step 2: Keep the LONG/SHORT badge — move it into the header**

The badge currently floats in the now-deleted price row. Move it into the card header row (the `{/* Header: name + symbol + contract */}` block at lines ~207–220), replacing the contract badge position or adding it alongside:

```tsx
{/* Header: name + symbol + contract + signal badge */}
<div className="flex items-center justify-between px-3 pt-1.5 pb-0.5 bg-[var(--bg-elevated)]">
  <div className="flex items-baseline gap-2">
    <span className="text-sm font-bold text-[var(--text-primary)] tracking-tight">
      {displayName}
    </span>
    <span className="text-[0.6rem] font-semibold text-[var(--text-muted)] uppercase tracking-wider">
      {data.symbol}
    </span>
  </div>
  <div className="flex items-center gap-1.5">
    {hasSignal ? (
      <span
        className="text-[0.6rem] font-bold uppercase tracking-widest px-1.5 py-0.5 rounded"
        style={{
          backgroundColor: isLong ? "var(--green-dim)" : "var(--red-dim)",
          color: isLong ? "var(--green)" : "var(--red)",
        }}
      >
        {isLong ? "LONG" : "SHORT"}
        {confidence !== null && (
          <span className="ml-1 opacity-75">{Math.round(confidence * 100)}%</span>
        )}
      </span>
    ) : null}
    <span className="text-[0.55rem] font-medium text-[var(--text-muted)] bg-[var(--bg-base)] px-1.5 py-0.5 rounded">
      {contract}
    </span>
  </div>
</div>
```

**Step 3: Verify `PriceHero` is still rendered in the price block section**

Confirm the block at line ~272 still reads:
```tsx
<div className="bg-[var(--bg-elevated)] border-b border-[var(--border-subtle)]">
  <PriceHero data={data} activeTf={activeTf} />
</div>
```

**Step 4: Remove now-unused derived values** (if TypeScript flags them):
- `chgSession`, `chgSessionPct` were used in the deleted price row — remove those derivations (~lines 175–176)
- `priceColor()` function — check if still used elsewhere in the component; if not, delete it

**Step 5: TypeScript + lint check**

```bash
cd dashboard && npx tsc --noEmit 2>&1 | head -20
cd dashboard && npx eslint src/components/trading-dashboard.tsx --max-warnings 0
```

Expected: 0 errors, 0 warnings.

**Step 6: Commit**

```bash
git add dashboard/src/components/trading-dashboard.tsx
git commit -m "feat(price-hero): remove old split price block, badge moved to header"
```

---

### Task 5: Visual check in browser

**Step 1: Start dev server if not running**

```bash
# Check if running
cat /tmp/dash.log | tail -5

# If not running:
cd /home/bg/dev/indicagent/dashboard && npm run dev -- --port 3000 --hostname 0.0.0.0 > /tmp/dash.log 2>&1 &
sleep 3 && tail -5 /tmp/dash.log
```

**Step 2: Open http://localhost:3000**

Verify each symbol card shows:
- Line 1: large price with green/red colour + session change + `vol X.XM` (or `—` if no bars yet)
- Line 2: Bid / Ask / spd + `as of HH:MM` right-aligned
- Line 3: `O X  H X  L X` with small inline dot range bar
- Top-right of header: LONG/SHORT badge + contract pill
- Card still glows green/red when confidence >75%
- Flash animation still fires on price tick

**Step 3: Verify no-data state**

Symbols with no data should show `—` for all fields — no crashes, no NaN.

**Step 4: Final commit if any tweaks were made**

```bash
git add -p
git commit -m "fix(price-hero): visual tweaks from browser check"
```
