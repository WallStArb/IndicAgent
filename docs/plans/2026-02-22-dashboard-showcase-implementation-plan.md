# Dashboard Intelligence Showcase — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Evolve the existing IndicAgent dashboard into a progressive-disclosure intelligence showcase — calm at the surface, arbitrarily deep when drilled.

**Architecture:** Five disclosure levels (L0→L4) layered onto the existing `SymbolCard` component. L0 visible to all; L1 expands inline; L2–L3 open a slide-in panel from the right. All new components consume existing `SymbolData` types — no backend changes required for Phases 1–3.

**Tech Stack:** Next.js 15.4, React 19, TypeScript, Tailwind v4, Lucide React, existing CSS vars in `globals.css`. No test framework — verify with TypeScript compilation (`npm run build`) and visual check in `npm run dev`.

---

## Phase 1 — Level 0 Showcase Layer

*Everything in Phase 1 works with existing SSE data. No backend changes.*

---

### Task 1: `ConfidenceRing` component

**Files:**
- Create: `dashboard/src/components/confidence-ring.tsx`

**What it does:** SVG circular ring showing unified confidence score (0–100). Derived from `ctf_score` and `signal.confidence`. Color shifts grey → teal → green/red based on level and signal direction. Pulses softly when confidence > 80.

**Step 1: Create the component**

```tsx
// dashboard/src/components/confidence-ring.tsx
"use client";

import type { ConfluenceData, SignalData } from "@/lib/types";

interface ConfidenceRingProps {
  confluence: ConfluenceData | null;
  signal: SignalData | null;
  price: number;
}

/** Derive a 0–100 confidence score from I6 + I7 data */
function deriveConfidence(
  confluence: ConfluenceData | null,
  signal: SignalData | null
): number {
  const ctf = confluence?.ctf_score ?? 0; // -1 to +1
  const sig = signal?.confidence ?? 0;    // 0 to 1
  // Weight: 60% CTF alignment, 40% signal confidence
  const raw = Math.abs(ctf) * 0.6 + sig * 0.4;
  return Math.round(Math.min(raw, 1) * 100);
}

export function ConfidenceRing({ confluence, signal, price }: ConfidenceRingProps) {
  const score = deriveConfidence(confluence, signal);
  const isLong = signal?.direction === "long";
  const isShort = signal?.direction === "short";
  const hasSignal = signal !== null;

  // Ring color
  const ringColor =
    score < 40
      ? "var(--border-bright)"
      : score < 65
        ? "var(--cyan)"
        : hasSignal && isLong
          ? "var(--green)"
          : hasSignal && isShort
            ? "var(--red)"
            : "var(--cyan)";

  const shouldPulse = score > 80;

  // SVG ring math
  const R = 36;
  const C = 2 * Math.PI * R;
  const filled = (score / 100) * C;
  const dash = `${filled} ${C - filled}`;

  return (
    <div className="flex flex-col items-center gap-1 py-3">
      <div
        className={`relative ${shouldPulse ? "ring-pulse" : ""}`}
        style={{ width: 96, height: 96 }}
      >
        <svg width={96} height={96} className="-rotate-90" style={{ position: "absolute" }}>
          {/* Track */}
          <circle
            cx={48} cy={48} r={R}
            fill="none"
            stroke="var(--bg-elevated)"
            strokeWidth={6}
          />
          {/* Fill */}
          <circle
            cx={48} cy={48} r={R}
            fill="none"
            stroke={ringColor}
            strokeWidth={6}
            strokeDasharray={dash}
            strokeLinecap="round"
            style={{ transition: "stroke-dasharray 0.4s ease, stroke 0.4s ease" }}
          />
        </svg>
        {/* Center content */}
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span
            className="text-xs font-bold font-data leading-none"
            style={{ color: ringColor }}
          >
            {score}
          </span>
          <span className="text-[0.45rem] text-[var(--text-muted)] uppercase tracking-widest">
            conf
          </span>
        </div>
      </div>

      {/* Price below ring */}
      <span className="text-sm font-bold font-data text-[var(--text-primary)]">
        {price > 0 ? price.toFixed(2) : "—"}
      </span>

      {/* Direction badge */}
      {hasSignal && (
        <span
          className="text-[0.5rem] font-bold uppercase tracking-widest px-1.5 py-0 rounded"
          style={{
            backgroundColor: isLong ? "var(--green-dim)" : "var(--red-dim)",
            color: isLong ? "var(--green)" : "var(--red)",
          }}
        >
          {isLong ? "LONG" : "SHORT"}
        </span>
      )}
    </div>
  );
}
```

**Step 2: Add `ring-pulse` animation to `globals.css`**

Open `dashboard/src/app/globals.css` and add after the existing `live-pulse` rule:

```css
@keyframes ring-pulse {
  0%, 100% { filter: drop-shadow(0 0 4px currentColor); opacity: 1; }
  50% { filter: drop-shadow(0 0 10px currentColor); opacity: 0.85; }
}
.ring-pulse {
  animation: ring-pulse 2s ease-in-out infinite;
}
```

**Step 3: Verify TypeScript compiles**

```bash
cd dashboard && npm run build 2>&1 | tail -20
```
Expected: no TypeScript errors (may have unrelated warnings)

**Step 4: Commit**

```bash
git add dashboard/src/components/confidence-ring.tsx dashboard/src/app/globals.css
git commit -m "feat(dashboard): ConfidenceRing — L0 confidence score visualization"
```

---

### Task 2: `RegimeAmbiance` wrapper

**Files:**
- Create: `dashboard/src/components/regime-ambiance.tsx`

**What it does:** Wraps the card body with a subtle background gradient tint reflecting GARCH volatility regime. 8–12% opacity max — registers subconsciously, never garish.

**Step 1: Create the component**

```tsx
// dashboard/src/components/regime-ambiance.tsx
"use client";

import type { ContextData } from "@/lib/types";

interface RegimeAmbianceProps {
  context: ContextData | null;
  children: React.ReactNode;
}

const REGIME_GRADIENT: Record<string, string> = {
  low:     "radial-gradient(ellipse at top, rgba(76, 154, 255, 0.06) 0%, transparent 70%)",
  normal:  "none",
  high:    "radial-gradient(ellipse at top, rgba(255, 179, 71, 0.08) 0%, transparent 70%)",
  extreme: "radial-gradient(ellipse at top, rgba(255, 71, 87, 0.10) 0%, transparent 70%)",
};

export function RegimeAmbiance({ context, children }: RegimeAmbianceProps) {
  const regime = context?.volatility_regime ?? "normal";
  const gradient = REGIME_GRADIENT[regime] ?? "none";

  return (
    <div
      style={{
        background: gradient,
        transition: "background 1.5s ease",
      }}
    >
      {children}
    </div>
  );
}
```

**Step 2: Verify build**

```bash
cd dashboard && npm run build 2>&1 | tail -5
```

**Step 3: Commit**

```bash
git add dashboard/src/components/regime-ambiance.tsx
git commit -m "feat(dashboard): RegimeAmbiance — GARCH vol regime background tint"
```

---

### Task 3: `SignalBanner` component

**Files:**
- Create: `dashboard/src/components/signal-banner.tsx`

**What it does:** Slim banner that appears at the top of a SymbolCard when `signal.confidence > 0.75`. Shows direction, signal type, confidence %, entry price, and stop. Clickable — calls `onDrillDown()` to open Level 2.

**Step 1: Create the component**

```tsx
// dashboard/src/components/signal-banner.tsx
"use client";

import type { SignalData } from "@/lib/types";
import { fmtPrice, fmtNum } from "@/lib/format";
import { TrendingUp, TrendingDown, ChevronRight } from "lucide-react";

interface SignalBannerProps {
  signal: SignalData | null;
  onDrillDown?: () => void;
}

const HIGH_CONFIDENCE_THRESHOLD = 0.75;

export function SignalBanner({ signal, onDrillDown }: SignalBannerProps) {
  if (!signal || signal.confidence < HIGH_CONFIDENCE_THRESHOLD) return null;

  const isLong = signal.direction === "long";
  const color = isLong ? "var(--green)" : "var(--red)";
  const dimColor = isLong ? "var(--green-dim)" : "var(--red-dim)";
  const Icon = isLong ? TrendingUp : TrendingDown;

  return (
    <button
      onClick={onDrillDown}
      className="w-full flex items-center gap-2 px-2 py-1 cursor-pointer"
      style={{
        backgroundColor: dimColor,
        borderBottom: `1px solid ${color}33`,
      }}
    >
      <Icon size={10} style={{ color }} />
      <span
        className="text-[0.55rem] font-bold uppercase tracking-widest"
        style={{ color }}
      >
        {isLong ? "LONG" : "SHORT"}
      </span>
      <span className="text-[0.55rem] text-[var(--text-muted)]">
        {signal.signal_type.replace(/_/g, " ")}
      </span>
      <span className="text-[0.55rem] font-data font-bold" style={{ color }}>
        {fmtNum(signal.confidence * 100, 0)}%
      </span>
      <span className="text-[0.5rem] text-[var(--text-muted)] font-data">
        {fmtPrice(signal.entry_price)} → {fmtPrice(signal.stop_loss)}
      </span>
      <ChevronRight size={8} className="ml-auto text-[var(--text-muted)]" />
    </button>
  );
}
```

**Step 2: Verify build**

```bash
cd dashboard && npm run build 2>&1 | tail -5
```

**Step 3: Commit**

```bash
git add dashboard/src/components/signal-banner.tsx
git commit -m "feat(dashboard): SignalBanner — high-confidence signal strip"
```

---

### Task 4: `NarrativeElevated` component

**Files:**
- Create: `dashboard/src/components/narrative-elevated.tsx`

**What it does:** When signal confidence > 0.75 AND narrative is < 5 minutes old, renders an elevated narrative block at the top of the SymbolCard — the AI voice becomes dominant. At rest (low confidence or stale), renders nothing so the existing `NarrativePanel` footer handles it.

**Step 1: Create the component**

```tsx
// dashboard/src/components/narrative-elevated.tsx
"use client";

import type { NarrativeData, SignalData } from "@/lib/types";

interface NarrativeElevatedProps {
  narrative: NarrativeData | null;
  signal: SignalData | null;
}

const FRESH_THRESHOLD_MS = 5 * 60 * 1000; // 5 minutes
const CONFIDENCE_THRESHOLD = 0.75;

export function NarrativeElevated({ narrative, signal }: NarrativeElevatedProps) {
  if (!narrative || !signal) return null;

  const isFresh = Date.now() - narrative.receivedAt < FRESH_THRESHOLD_MS;
  const isHighConfidence = signal.confidence >= CONFIDENCE_THRESHOLD;

  if (!isFresh || !isHighConfidence) return null;

  const isBullish = narrative.action_bias === "bullish";
  const accentColor = isBullish ? "var(--green)" : "var(--red)";

  return (
    <div
      className="px-3 py-2.5 flex flex-col gap-1.5"
      style={{
        borderLeft: `2px solid ${accentColor}`,
        borderBottom: "1px solid var(--border-subtle)",
        background: isBullish
          ? "linear-gradient(135deg, rgba(0,220,130,0.04) 0%, transparent 60%)"
          : "linear-gradient(135deg, rgba(255,71,87,0.04) 0%, transparent 60%)",
      }}
    >
      {/* Header */}
      <div className="flex items-center gap-2">
        <span
          className="text-[0.5rem] font-bold uppercase tracking-widest"
          style={{ color: accentColor }}
        >
          AI · {narrative.action_bias.toUpperCase()}
        </span>
        <span className="text-[0.45rem] text-[var(--text-muted)]">
          {narrative.timeframe.toUpperCase()}
        </span>
      </div>

      {/* Narrative prose */}
      <p className="text-[0.65rem] text-[var(--text-secondary)] leading-relaxed m-0">
        {narrative.narrative}
      </p>
    </div>
  );
}
```

**Step 2: Verify build**

```bash
cd dashboard && npm run build 2>&1 | tail -5
```

**Step 3: Commit**

```bash
git add dashboard/src/components/narrative-elevated.tsx
git commit -m "feat(dashboard): NarrativeElevated — AI narrative rises when high confidence"
```

---

### Task 5: Refactor `SymbolCard` to use Level 0 components

**Files:**
- Modify: `dashboard/src/components/trading-dashboard.tsx`

**What it does:** Replace the `SymbolCard`'s current layout (PriceHero at top) with the new Level 0 stack: `ConfidenceRing` + `RegimeAmbiance` wrapper + `SignalBanner` + `NarrativeElevated`. The existing tier panels (I3→I7) remain below as before. Also pass `narratives` down to `SymbolCard`.

**Step 1: Update `SymbolCard` signature and imports**

In `trading-dashboard.tsx`, update the `SymbolCard` function. First update the import block at the top of the file:

```tsx
// Add these imports (keep existing ones)
import { ConfidenceRing } from "./confidence-ring";
import { RegimeAmbiance } from "./regime-ambiance";
import { SignalBanner } from "./signal-banner";
import { NarrativeElevated } from "./narrative-elevated";
import type { NarrativeData } from "@/lib/types";
```

**Step 2: Update `SymbolCard` to accept narrative**

Replace the `SymbolCard` function signature and body:

```tsx
function SymbolCard({
  data,
  narrative,
}: {
  data: SymbolData;
  narrative: NarrativeData | null;
}) {
  return (
    <div
      className="flex flex-col surface rounded overflow-hidden"
      style={{
        boxShadow:
          data.signal && data.signal.confidence > 0.75
            ? data.signal.direction === "long"
              ? "0 0 0 1px var(--green-dim)"
              : "0 0 0 1px var(--red-dim)"
            : undefined,
        transition: "box-shadow 0.5s ease",
      }}
    >
      {/* L0: Confidence ring + price */}
      <div className="bg-[var(--bg-elevated)] border-b border-[var(--border-subtle)]">
        <ConfidenceRing
          confluence={data.confluence}
          signal={data.signal}
          price={data.tick.price}
        />
      </div>

      {/* L0: High-confidence signal banner */}
      <SignalBanner signal={data.signal} />

      {/* L0: Elevated AI narrative (only when high confidence + fresh) */}
      <NarrativeElevated narrative={narrative} signal={data.signal} />

      {/* L0: Regime ambiance wraps the tier stack */}
      <RegimeAmbiance context={data.context}>
        {/* Intelligence tiers — existing panels unchanged */}
        <IndicatorGrid indicators={data.indicators} />
        <div className="border-t border-[var(--border-subtle)]">
          <StructurePanel structure={data.structure} />
        </div>
        <div className="border-t border-[var(--border-subtle)]">
          <ContextPanel context={data.context} />
        </div>
        <div className="border-t border-[var(--border-subtle)]">
          <PatternPanel patterns={data.patterns} />
        </div>
        <div className="border-t border-[var(--border-subtle)]">
          <SmartMoneyPanel smartMoney={data.smartMoney} />
        </div>
        <div className="border-t border-[var(--border-subtle)]">
          <ConfluencePanel confluence={data.confluence} />
        </div>
        <div className="border-t border-[var(--border-subtle)]">
          <SignalPanel signal={data.signal} />
        </div>
      </RegimeAmbiance>
    </div>
  );
}
```

**Step 3: Update `TradingDashboard` to pass narrative to each card**

In the `TradingDashboard` main return, update the `symbols.map` block:

```tsx
{symbols.map((sym) => {
  const data = symbolData[sym];
  if (!data) return null;
  // Find freshest narrative for this symbol across any timeframe
  const narrative =
    Object.values(narratives)
      .filter((n) => n.symbol === sym)
      .sort((a, b) => b.receivedAt - a.receivedAt)[0] ?? null;
  return <SymbolCard key={sym} data={data} narrative={narrative} />;
})}
```

**Step 4: Remove `PriceHero` import** (no longer used in SymbolCard)

Remove `import { PriceHero } from "./price-hero";` from the import block.

**Step 5: Visual check in dev**

```bash
cd dashboard && npm run dev
```

Open http://localhost:3000. Verify:
- Each card shows a confidence ring at top
- High-confidence signals show green/red banner
- Low confidence cards remain calm (grey ring, no banner)
- Elevated narrative appears when signal > 75% + fresh

**Step 6: Build check**

```bash
cd dashboard && npm run build 2>&1 | tail -10
```

**Step 7: Commit**

```bash
git add dashboard/src/components/trading-dashboard.tsx
git commit -m "feat(dashboard): wire Level 0 showcase layer — ConfidenceRing, RegimeAmbiance, SignalBanner, NarrativeElevated"
```

---

## Phase 2 — Level 1: Cross-Timeframe Matrix

*Requires subscribing to all 6 timeframes simultaneously per symbol.*

---

### Task 6: Extend `useMarketStream` for multi-TF signal tracking

**Files:**
- Modify: `dashboard/src/hooks/use-market-stream.ts`
- Modify: `dashboard/src/lib/types.ts`

**Step 1: Add `PerTfSignal` type to `types.ts`**

Add after the `SignalData` interface:

```ts
/** Per-timeframe signal direction for cross-TF matrix */
export interface PerTfSignal {
  direction: "long" | "short" | null;
  confidence: number;
  updatedAt: number;
}

export type TfSignalMap = Record<string, PerTfSignal>; // key = timeframe string "1m" etc.
```

Add `tfSignals` to `SymbolData`:

```ts
export interface SymbolData {
  // ... existing fields ...
  tfSignals: TfSignalMap; // per-TF signal direction for matrix
}
```

**Step 2: Update `emptySymbolData` in `use-market-stream.ts`**

```ts
function emptySymbolData(symbol: string): SymbolData {
  return {
    // ... existing fields ...
    tfSignals: {},
  };
}
```

**Step 3: Subscribe to all timeframes in `useMarketStream`**

The hook currently subscribes to one `timeframe` at a time. Change the SSE URL to subscribe to all timeframes (backend already supports comma-separated):

```ts
// In useMarketStream, replace the URL construction:
const ALL_TFS = "1m,5m,15m,1h,4h,1d";
const url = `${base}/api/sse/events?symbols=${encodeURIComponent(symbolsCsv)}&timeframe=${encodeURIComponent(ALL_TFS)}`;
```

**Step 4: Update `signal_data` handler to track per-TF signals**

Replace the existing `signal_data` listener:

```ts
es.addEventListener("signal_data", (evt) => {
  const { payload } = JSON.parse(evt.data);
  const sym = contractToBase(payload.symbol || "");
  if (!sym) return;
  const dir = parseInt(String(payload.direction || "0"));
  const tf = String(payload.timeframe || timeframe);

  setSymbolData((prev) => {
    const old = prev[sym];
    if (!old) return prev;

    // Update tfSignals for this specific timeframe
    const tfSignal: PerTfSignal = {
      direction: dir > 0 ? "long" : dir < 0 ? "short" : null,
      confidence: parseFloat(String(payload.confidence || "0")),
      updatedAt: Date.now(),
    };

    // Only update the card-level signal for the user's selected timeframe
    const isSelectedTf = tf === timeframe;
    const signal: SignalData | null = isSelectedTf && dir !== 0
      ? {
          direction: dir > 0 ? "long" : "short",
          signal_type: String(payload.signal_type || ""),
          setup_plugin: String(payload.setup_plugin || ""),
          confidence: parseFloat(String(payload.confidence || "0")),
          entry_price: parseFloat(String(payload.entry_price || "0")),
          stop_loss: parseFloat(String(payload.stop_loss || "0")),
          regime_context: String(payload.regime_context || ""),
          timestamp: String(payload.timestamp || ""),
        }
      : old.signal;

    return {
      ...prev,
      [sym]: {
        ...old,
        signal: signal ?? old.signal,
        tfSignals: { ...old.tfSignals, [tf]: tfSignal },
        lastUpdate: Date.now(),
      },
    };
  });
  touch();
});
```

**Step 5: Build check**

```bash
cd dashboard && npm run build 2>&1 | tail -10
```

**Step 6: Commit**

```bash
git add dashboard/src/hooks/use-market-stream.ts dashboard/src/lib/types.ts
git commit -m "feat(dashboard): multi-TF signal tracking in useMarketStream for cross-TF matrix"
```

---

### Task 7: `TimeframeMatrix` component

**Files:**
- Create: `dashboard/src/components/timeframe-matrix.tsx`

**What it does:** Compact pill row — one pill per timeframe — colored by signal direction. "CONFLUENCE" badge when 4+ agree. Tapping a pill emits `onSelectTf`.

**Step 1: Create the component**

```tsx
// dashboard/src/components/timeframe-matrix.tsx
"use client";

import type { TfSignalMap, ConfluenceData } from "@/lib/types";
import { TIMEFRAMES } from "@/lib/types";

interface TimeframeMatrixProps {
  tfSignals: TfSignalMap;
  confluence: ConfluenceData | null;
  activeTf: string;
  onSelectTf: (tf: string) => void;
}

const STALE_THRESHOLD_MS = 5 * 60 * 1000;

export function TimeframeMatrix({
  tfSignals,
  confluence,
  activeTf,
  onSelectTf,
}: TimeframeMatrixProps) {
  const aligned = confluence?.ctf_timeframes_aligned ?? 0;
  const showConfluence = aligned >= 4;

  return (
    <div className="px-2 py-2 flex items-center gap-1.5 flex-wrap border-b border-[var(--border-subtle)]">
      <span className="text-[0.5rem] font-semibold uppercase tracking-widest text-[var(--text-muted)] shrink-0">
        TF
      </span>

      {TIMEFRAMES.map(({ value, short }) => {
        const sig = tfSignals[value];
        const isStale = sig && Date.now() - sig.updatedAt > STALE_THRESHOLD_MS;
        const direction = sig && !isStale ? sig.direction : null;
        const isActive = activeTf === value;

        const bgColor =
          direction === "long"
            ? "var(--green-dim)"
            : direction === "short"
              ? "var(--red-dim)"
              : "var(--bg-elevated)";

        const textColor =
          direction === "long"
            ? "var(--green)"
            : direction === "short"
              ? "var(--red)"
              : "var(--text-muted)";

        return (
          <button
            key={value}
            onClick={() => onSelectTf(value)}
            className="rounded px-1.5 py-0.5 text-[0.5rem] font-bold uppercase tracking-wider cursor-pointer transition-all duration-150"
            style={{
              backgroundColor: bgColor,
              color: textColor,
              outline: isActive ? `1px solid ${textColor}` : "none",
              opacity: isStale ? 0.4 : 1,
            }}
          >
            {short}
          </button>
        );
      })}

      {showConfluence && (
        <span
          className="ml-auto text-[0.45rem] font-bold uppercase tracking-widest px-1.5 py-0.5 rounded"
          style={{
            backgroundColor:
              (confluence?.ctf_score ?? 0) > 0
                ? "var(--green-dim)"
                : "var(--red-dim)",
            color:
              (confluence?.ctf_score ?? 0) > 0
                ? "var(--green)"
                : "var(--red)",
          }}
        >
          CONFLUENCE {aligned}/6
        </span>
      )}
    </div>
  );
}
```

**Step 2: Wire into `SymbolCard`**

In `trading-dashboard.tsx`, add `TimeframeMatrix` to `SymbolCard`. Add state for the selected drill timeframe:

```tsx
import { TimeframeMatrix } from "./timeframe-matrix";
import { useState } from "react"; // already imported
```

Update `SymbolCard` to add `drillTf` state and insert `TimeframeMatrix` between `NarrativeElevated` and `RegimeAmbiance`:

```tsx
function SymbolCard({ data, narrative }: { data: SymbolData; narrative: NarrativeData | null }) {
  const [drillTf, setDrillTf] = useState<string>("5m");

  return (
    <div className="flex flex-col surface rounded overflow-hidden" /* ... box shadow ... */>
      {/* L0 */}
      <div className="bg-[var(--bg-elevated)] border-b border-[var(--border-subtle)]">
        <ConfidenceRing confluence={data.confluence} signal={data.signal} price={data.tick.price} />
      </div>
      <SignalBanner signal={data.signal} />
      <NarrativeElevated narrative={narrative} signal={data.signal} />

      {/* L1: Cross-TF matrix — always visible */}
      <TimeframeMatrix
        tfSignals={data.tfSignals}
        confluence={data.confluence}
        activeTf={drillTf}
        onSelectTf={setDrillTf}
      />

      {/* Existing tier stack */}
      <RegimeAmbiance context={data.context}>
        {/* ... unchanged tier panels ... */}
      </RegimeAmbiance>
    </div>
  );
}
```

**Step 3: Visual check**

```bash
cd dashboard && npm run dev
```

Verify: each card shows TF pills row. Greenlit TFs have signal. CONFLUENCE badge appears when 4+ agree.

**Step 4: Build check + commit**

```bash
cd dashboard && npm run build 2>&1 | tail -5
git add dashboard/src/components/timeframe-matrix.tsx dashboard/src/components/trading-dashboard.tsx
git commit -m "feat(dashboard): TimeframeMatrix — Level 1 cross-TF convergence view"
```

---

## Phase 3 — Drill-Down Shell (Levels 2–3)

---

### Task 8: Slide-in drill panel shell

**Files:**
- Create: `dashboard/src/components/drill-panel.tsx`
- Modify: `dashboard/src/components/trading-dashboard.tsx`

**What it does:** A slide-in overlay panel that opens from the right side of the screen when the user taps "drill down". Contains Level 2 (tier breakdown) and Level 3 (plugin audit). Closes with back button or clicking outside.

**Step 1: Create `DrillPanel` shell**

```tsx
// dashboard/src/components/drill-panel.tsx
"use client";

import { X } from "lucide-react";
import type { SymbolData } from "@/lib/types";

interface DrillPanelProps {
  symbol: string;
  timeframe: string;
  data: SymbolData;
  onClose: () => void;
}

export function DrillPanel({ symbol, timeframe, data, onClose }: DrillPanelProps) {
  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Panel */}
      <div
        className="fixed top-0 right-0 bottom-0 z-50 w-full max-w-md flex flex-col"
        style={{
          backgroundColor: "var(--bg-surface)",
          borderLeft: "1px solid var(--border-default)",
        }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-4 py-3 shrink-0"
          style={{ borderBottom: "1px solid var(--border-subtle)" }}
        >
          <div className="flex items-center gap-2">
            <span className="text-sm font-bold text-[var(--text-primary)] font-data">
              {symbol}
            </span>
            <span
              className="text-[0.55rem] font-semibold px-1.5 py-0.5 rounded"
              style={{
                backgroundColor: "var(--bg-elevated)",
                color: "var(--text-secondary)",
              }}
            >
              {timeframe.toUpperCase()}
            </span>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded cursor-pointer text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
          >
            <X size={14} />
          </button>
        </div>

        {/* Level 2: Tier breakdown */}
        <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-3">
          <TierBreakdown data={data} />
        </div>
      </div>
    </>
  );
}

/** Level 2: I3→I7 tier breakdown — shows each tier's status + brief reason */
function TierBreakdown({ data }: { data: SymbolData }) {
  const tiers = [
    {
      label: "I3 Structure",
      value: data.structure
        ? `Trend: ${data.structure.swing_trend ?? "—"} · Integrity: ${((data.structure.trend_integrity ?? 0) * 100).toFixed(0)}%`
        : null,
    },
    {
      label: "I4 Context",
      value: data.context
        ? `Vol: ${data.context.volatility_regime ?? "—"} · Trend: ${data.context.trend_regime ?? "—"}`
        : null,
    },
    {
      label: "I5 Patterns",
      value: data.patterns
        ? `Confluence: ${((data.patterns.confluence_score ?? 0) * 100).toFixed(0)}% · RSI div: ${data.patterns.rsi_divergence ?? "none"}`
        : null,
    },
    {
      label: "SMC",
      value: data.smartMoney
        ? [
            data.smartMoney.bos_detected ? `BOS ${data.smartMoney.bos_direction > 0 ? "▲" : "▼"}` : null,
            data.smartMoney.choch_detected ? "CHoCH" : null,
            data.smartMoney.fvg_type !== 0 ? `FVG ${data.smartMoney.fvg_type > 0 ? "bull" : "bear"}` : null,
            data.smartMoney.sweep_detected ? "Sweep" : null,
          ]
            .filter(Boolean)
            .join(" · ") || "—"
        : null,
    },
    {
      label: "I6 Confluence",
      value: data.confluence
        ? `CTF score: ${(data.confluence.ctf_score ?? 0).toFixed(2)} · ${data.confluence.ctf_timeframes_aligned ?? 0}/4 TFs`
        : null,
    },
    {
      label: "I7 Signal",
      value: data.signal
        ? `${data.signal.direction.toUpperCase()} · ${data.signal.signal_type} · ${(data.signal.confidence * 100).toFixed(0)}% conf`
        : "No signal",
    },
  ];

  return (
    <div className="flex flex-col gap-1">
      <h3 className="text-[0.55rem] font-semibold uppercase tracking-widest text-[var(--text-muted)] mb-2">
        Intelligence Breakdown
      </h3>
      {tiers.map((tier) => (
        <div
          key={tier.label}
          className="flex items-start gap-3 px-3 py-2 rounded"
          style={{ backgroundColor: "var(--bg-elevated)" }}
        >
          <span className="text-[0.55rem] font-bold text-[var(--text-muted)] shrink-0 w-20">
            {tier.label}
          </span>
          <span className="text-[0.6rem] text-[var(--text-secondary)] flex-1">
            {tier.value ?? (
              <span className="italic text-[var(--text-muted)]">Awaiting data</span>
            )}
          </span>
        </div>
      ))}
    </div>
  );
}
```

**Step 2: Wire drill panel into `SymbolCard`**

In `trading-dashboard.tsx`, add drill panel state and wire the "drill down" action:

```tsx
import { DrillPanel } from "./drill-panel";

// In SymbolCard, add drill state:
const [isDrilling, setIsDrilling] = useState(false);

// Add drill panel below the card closing tag:
return (
  <>
    <div className="flex flex-col surface rounded overflow-hidden ..." >
      {/* ... all existing content ... */}
      {/* Make SignalBanner trigger drill */}
      <SignalBanner signal={data.signal} onDrillDown={() => setIsDrilling(true)} />

      {/* Make TimeframeMatrix TF tap also open drill */}
      <TimeframeMatrix
        tfSignals={data.tfSignals}
        confluence={data.confluence}
        activeTf={drillTf}
        onSelectTf={(tf) => { setDrillTf(tf); setIsDrilling(true); }}
      />
      {/* ... rest unchanged ... */}
    </div>

    {isDrilling && (
      <DrillPanel
        symbol={data.symbol}
        timeframe={drillTf}
        data={data}
        onClose={() => setIsDrilling(false)}
      />
    )}
  </>
);
```

**Step 3: Visual check**

```bash
cd dashboard && npm run dev
```

Verify: tapping the signal banner or a TF pill opens the slide-in panel. Tier breakdown shows I3→I7 data. Closes on X or backdrop click.

**Step 4: Build + commit**

```bash
cd dashboard && npm run build 2>&1 | tail -5
git add dashboard/src/components/drill-panel.tsx dashboard/src/components/trading-dashboard.tsx
git commit -m "feat(dashboard): DrillPanel — Level 2 slide-in tier breakdown"
```

---

## Phase 4 — Deployment

---

### Task 9: Cloudflare Tunnel setup

**Files:**
- Create: `dashboard/.env.local` (gitignored — do not commit)
- Create: `production/cloudflare/tunnel-config.yml`

**Step 1: Install cloudflared**

```bash
# On Ubuntu/Debian
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o /tmp/cloudflared.deb
sudo dpkg -i /tmp/cloudflared.deb
cloudflared --version
```

**Step 2: Authenticate and create tunnel**

```bash
cloudflared tunnel login
cloudflared tunnel create indicagent
# Note the tunnel UUID from output
```

**Step 3: Create tunnel config**

```bash
mkdir -p production/cloudflare
```

Create `production/cloudflare/tunnel-config.yml`:

```yaml
tunnel: <YOUR_TUNNEL_UUID>
credentials-file: /home/bg/.cloudflared/<YOUR_TUNNEL_UUID>.json

ingress:
  - hostname: indicagent.<YOUR_SUBDOMAIN>.workers.dev
    service: http://localhost:8000
  - service: http_status:404
```

**Step 4: Add DNS route**

```bash
cloudflared tunnel route dns indicagent indicagent.<YOUR_SUBDOMAIN>.workers.dev
```

**Step 5: Run tunnel**

```bash
cloudflared tunnel run --config production/cloudflare/tunnel-config.yml indicagent
```

Verify: `curl https://indicagent.<YOUR_SUBDOMAIN>.workers.dev/health` returns 200.

**Step 6: Set dashboard env**

Create `dashboard/.env.local`:

```
NEXT_PUBLIC_API_BASE_URL=https://indicagent.<YOUR_SUBDOMAIN>.workers.dev
```

**Step 7: Production build + start**

```bash
cd dashboard && npm run build && npm start
# Dashboard runs on localhost:3000, connects to backend via Cloudflare Tunnel
```

**Step 8: Commit tunnel config (not credentials, not .env.local)**

```bash
git add production/cloudflare/tunnel-config.yml
git commit -m "infra: Cloudflare Tunnel config for public dashboard deployment"
```

---

### Task 10: Serve dashboard via Cloudflare Pages (optional alternative)

*Skip if serving dashboard locally is sufficient.*

**Step 1: Add dashboard to Cloudflare Pages via git**

- Connect repo to Cloudflare Pages
- Build command: `cd dashboard && npm run build`
- Output directory: `dashboard/.next`
- Set env var `NEXT_PUBLIC_API_BASE_URL` to the tunnel URL

**Step 2: Update tunnel config to also serve dashboard on a subdomain** (if desired)

Add to `tunnel-config.yml`:
```yaml
  - hostname: dash.indicagent.<YOUR_SUBDOMAIN>.workers.dev
    service: http://localhost:3000
```

---

## Out of Scope (deferred)

- **Level 3 Plugin Audit** — requires `GET /api/audit/{symbol}/{timeframe}` backend endpoint returning per-plugin values and gate results. Wire into `DrillPanel` as a second tab once endpoint exists.
- **Level 4 Raw Calculation View** — requires sparkline library (Lightweight Charts) and per-bar calculation history endpoint.
- **Debug route** (`/debug`) — signal ledger query, indicator health, reference comparison.
- **Candlestick charting** — Lightweight Charts integration.

---

## Quick Reference — CSS Vars

```
--green / --green-dim    long signals
--red / --red-dim        short signals
--amber / --amber-dim    neutral / warning
--cyan / --cyan-dim      moderate confidence
--blue / --blue-dim      informational
--bg-base                deepest background
--bg-surface             card backgrounds
--bg-elevated            inner surfaces
--text-primary/secondary/muted   text hierarchy
```
