# Homepage Refinement Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Refine the IndicAgent landing page — hero tightened with more visible animation + live stats, intelligence pillars explainer, signal cards enriched with regime/ADX/killzone/AMD/SMC context, and TF-aware signal filtering that surfaces fresh 5m/15m signals.

**Architecture:** Pure frontend changes. All new fields (ADX, killzone, AMD phase, GARCH vol regime, demand/supply zones) are already computed by the backend and present in the SSE stream JSONB tiers — we just need to map them in the hook and display them in the UI. No backend changes. No new API routes.

**Tech Stack:** Next.js 14, TypeScript, Tailwind CSS, existing CSS variables (`var(--surface-card)` etc.), `useMarketStream` hook, `SymbolData` type tree.

**Note on testing:** Dashboard has no test runner configured (`tsconfig.json` excludes `__tests__/`). Verification is TypeScript build (`npm run build`) + visual inspection. Run `npm run build` after each task to catch type errors early.

---

### Task 1: Extend types — IndicatorData, ContextData, SmartMoneyData

**Files:**
- Modify: `dashboard/src/lib/types.ts`

**What's missing:**
- `IndicatorData` lacks: `adx`, `plus_di`, `minus_di`
- `ContextData` lacks: killzone fields (`in_killzone`, `killzone_name`, `minutes_until_next_killzone`), `garch_vol_regime`
- `SmartMoneyData` lacks: `amd_phase`, `in_demand_zone`, `in_supply_zone`

**Step 1: Add ADX fields to IndicatorData** (after the `vwap` and `volume_sma` lines, around line 57)

```typescript
// Trend Strength
adx?: number;          // ADX 14
plus_di?: number;      // +DI 14 (bullish directional)
minus_di?: number;     // -DI 14 (bearish directional)
```

**Step 2: Add killzone + GARCH fields to ContextData** (after the `momentum_direction` line, around line 98)

```typescript
// Killzone / Session timing
in_killzone?: boolean;
killzone_name?: string;          // "London" | "NY AM" | "NY PM" | "Asia" | null
minutes_until_next_killzone?: number;
// GARCH vol regime
garch_vol_regime?: number;       // 0=low, 1=normal, 2=high
```

**Step 3: Add AMD phase + zone fields to SmartMoneyData** (after `pool_count`, around line 172)

```typescript
// AMD Phase (Wyckoff)
amd_phase?: "accumulation" | "manipulation" | "distribution" | "unknown";
// Demand / Supply zones
in_demand_zone?: boolean;
in_supply_zone?: boolean;
```

**Step 4: Verify TypeScript compiles**

```bash
cd dashboard && npm run build 2>&1 | tail -20
```

Expected: no new errors.

**Step 5: Commit**

```bash
git add dashboard/src/lib/types.ts
git commit -m "feat(dashboard): extend types with ADX, killzone, AMD phase, GARCH, demand/supply zone fields"
```

---

### Task 2: Map new fields in use-market-stream.ts hook

**Files:**
- Modify: `dashboard/src/hooks/use-market-stream.ts`

**Step 1: Add ADX mapping in the `indicator_data` event handler** (around line 403, inside the `mapped` object)

```typescript
// Add after vwap: n("vwap"),
adx: n("adx_14"),
plus_di: n("plus_di_14"),
minus_di: n("minus_di_14"),
```

**Step 2: Add GARCH vol regime + killzone fields to `context` in `parseIntelligence()`**

Find the `context: ContextData = {` block (around line 121). Add after `momentum_direction`:

```typescript
garch_vol_regime: i4.garch_vol_regime != null ? Number(i4.garch_vol_regime) : undefined,
in_killzone: (
  nf(i4.in_london_killzone) > 0 ||
  nf(i4.in_ny_killzone) > 0 ||
  nf(i4.in_ny_am_killzone) > 0 ||
  nf(i4.in_ny_pm_killzone) > 0 ||
  nf(i4.in_asia_killzone) > 0
) || undefined,
killzone_name: typeof i4.killzone_name === "string" && i4.killzone_name ? i4.killzone_name : undefined,
minutes_until_next_killzone: i4.minutes_until_next_killzone ?? undefined,
```

**Note:** The killzone fields live in the i4 tier of the intelligence stream (`event.i4` in `parseIntelligence`). Confirmed in `src/intelligence/schemas.py:306-307`.

**Step 3: Add AMD phase + demand/supply zone fields to `smartMoney` in `parseIntelligence()`**

Find the `smartMoney: SmartMoneyData = {` block. Add after `pool_count`:

```typescript
amd_phase: typeof smc.amd_phase === "string" && smc.amd_phase !== "unknown"
  ? smc.amd_phase as SmartMoneyData["amd_phase"]
  : undefined,
in_demand_zone: smc.in_demand_zone != null ? nf(smc.in_demand_zone) > 0 : undefined,
in_supply_zone: smc.in_supply_zone != null ? nf(smc.in_supply_zone) > 0 : undefined,
```

**Step 4: Build check**

```bash
cd dashboard && npm run build 2>&1 | tail -20
```

Expected: no errors.

**Step 5: Commit**

```bash
git add dashboard/src/hooks/use-market-stream.ts
git commit -m "feat(dashboard): map ADX, killzone, AMD phase, GARCH vol regime, demand/supply zone fields from SSE stream"
```

---

### Task 3: Signal card intelligence context row

**Files:**
- Modify: `dashboard/src/components/landing/signal-card.tsx`

The signal card already receives `data: SymbolData`. Intelligence context (context, smartMoney) is at `data.context` and `data.smartMoney`. Indicators are at `data.indicatorsByTf[signal.timeframe]`.

**Step 1: Add a helper to derive the intelligence context for display**

Add this function before the `SignalCard` component (after the `useFormattedTimestamp` hook):

```typescript
/** Derive compact intelligence context labels from SymbolData. Returns only truthy items. */
function useIntelCtx(data: SymbolData, timeframe: string): string[] {
  const ctx = data.context;
  const smc = data.smartMoney;
  const ind = data.indicatorsByTf?.[timeframe];
  const tags: string[] = [];

  // Regime (HMM preferred, fallback to trend_regime)
  if (smc?.hmm_regime != null) {
    const label = smc.hmm_regime === 1 ? "TRENDING ↑" : smc.hmm_regime === 2 ? "TRENDING ↓" : "RANGING";
    tags.push(label);
  } else if (ctx?.trend_regime && ctx.trend_regime !== "neutral") {
    tags.push(ctx.trend_regime.replace("_", " ").toUpperCase());
  }

  // ADX (only show if meaningful: > 20)
  if (ind?.adx != null && ind.adx > 20) {
    const di = ind.plus_di != null && ind.minus_di != null
      ? (ind.plus_di > ind.minus_di ? " ↑" : " ↓")
      : "";
    tags.push(`ADX ${Math.round(ind.adx)}${di}`);
  }

  // Killzone
  if (ctx?.in_killzone && ctx.killzone_name) {
    tags.push(ctx.killzone_name.toUpperCase());
  }

  // AMD phase
  if (smc?.amd_phase) {
    const label = smc.amd_phase === "accumulation" ? "ACCUM" : smc.amd_phase === "manipulation" ? "MANIP" : "DIST";
    tags.push(label);
  }

  // GARCH vol regime
  if (ctx?.garch_vol_regime != null && ctx.garch_vol_regime >= 2) {
    tags.push("VOL ↑");
  }

  // SMC zone
  if (smc?.in_demand_zone) tags.push("IN DEMAND");
  else if (smc?.in_supply_zone) tags.push("IN SUPPLY");

  return tags;
}
```

**Step 2: Call the hook inside `SignalCard`**

Inside the `SignalCard` function body, after the existing `useMemo` calls:

```typescript
const intelTags = useIntelCtx(data, signal.timeframe);
```

**Step 3: Add the intelligence context row to the JSX**

Find the price strip `</div>` closing tag (after the T1/T2 section, before the footer div `{/* Footer: signal type tags + narrative */}`). Insert between them:

```tsx
{/* Intelligence context row */}
{intelTags.length > 0 && (
  <div
    className="py-1 border-b flex flex-wrap gap-1"
    style={{ borderColor: "var(--border-subtle)" }}
  >
    {intelTags.map((tag) => (
      <span
        key={tag}
        className="text-[0.6rem] px-1.5 py-px rounded font-medium leading-none"
        style={{
          background: "var(--bg-elevated)",
          color: tag.includes("DEMAND") || tag.includes("↑")
            ? "var(--green)"
            : tag.includes("SUPPLY") || tag.includes("↓")
              ? "var(--red)"
              : tag === "MANIP"
                ? "#f59e0b"
                : "var(--text-secondary)",
        }}
      >
        {tag}
      </span>
    ))}
  </div>
)}
```

**Step 4: Build check**

```bash
cd dashboard && npm run build 2>&1 | tail -20
```

**Step 5: Commit**

```bash
git add dashboard/src/components/landing/signal-card.tsx
git commit -m "feat(dashboard): add intelligence context row to landing signal card (regime, ADX, killzone, AMD, vol, SMC zone)"
```

---

### Task 4: Hero section — tighten, animation visible, stat pills, CTA

**Files:**
- Modify: `dashboard/src/components/landing/hero-section.tsx`

**Step 1: Rewrite `hero-section.tsx`**

Replace the entire file content:

```tsx
"use client";

import Link from "next/link";
import { PipelineAnimation } from "./pipeline-animation";
import { ArrowRight } from "lucide-react";

interface HeroStatPillProps {
  label: string;
  live?: boolean;
}

function HeroStatPill({ label, live }: HeroStatPillProps) {
  return (
    <div
      className="flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium"
      style={{
        background: "rgba(78, 214, 200, 0.08)",
        border: "1px solid rgba(78, 214, 200, 0.2)",
        color: "var(--text-secondary)",
      }}
    >
      {live && (
        <span
          className="w-1.5 h-1.5 rounded-full animate-pulse"
          style={{ background: "var(--accent-cyan)" }}
        />
      )}
      {label}
    </div>
  );
}

interface HeroSectionProps {
  activeSignalCount: number;
}

export function HeroSection({ activeSignalCount }: HeroSectionProps) {
  return (
    <section
      className="relative flex flex-col items-center justify-center px-6 py-16 overflow-hidden"
      style={{
        minHeight: "50vh",
        background: "var(--landing-bg-gradient)",
      }}
    >
      {/* Animation — primary visual, higher opacity */}
      <div className="absolute inset-0" style={{ opacity: 0.65 }}>
        <PipelineAnimation />
      </div>

      {/* Content overlay */}
      <div className="relative z-10 max-w-3xl mx-auto text-center space-y-6">
        {/* Headline */}
        <div className="space-y-3">
          <h1
            className="text-5xl md:text-6xl font-bold leading-tight"
            style={{
              color: "var(--text-primary)",
              fontFamily: "var(--font-display)",
            }}
          >
            Real-Time Market Intelligence
          </h1>
          <p
            className="text-base md:text-lg"
            style={{ color: "var(--text-secondary)" }}
          >
            8-tier intelligence pipeline · 88 plugins · GLM-5 AI narratives · 24 instruments
          </p>
        </div>

        {/* Live stat pills */}
        <div className="flex flex-wrap items-center justify-center gap-2">
          <HeroStatPill label="24 Instruments" live />
          <HeroStatPill
            label={activeSignalCount > 0 ? `${activeSignalCount} Active Signals` : "Signals Live"}
            live
          />
          <HeroStatPill label="CIS Scoring" live />
          <HeroStatPill label="GLM-5 Narratives" live />
        </div>

        {/* Primary CTA */}
        <Link
          href="/dashboard"
          className="inline-flex items-center gap-2 px-8 py-3 rounded-lg font-semibold text-base transition-all duration-200 hover:scale-105"
          style={{
            background: "var(--accent-cyan)",
            color: "#0A0E14",
            boxShadow: "0 4px 20px rgba(78, 214, 200, 0.35)",
          }}
        >
          Open Dashboard
          <ArrowRight size={18} />
        </Link>
      </div>
    </section>
  );
}
```

**Step 2: Update `landing/page.tsx` to pass `activeSignalCount` to `HeroSection`**

The page already has `filteredSignals` computed. Pass the count:

```tsx
<HeroSection activeSignalCount={filteredSignals.length} />
```

**Step 3: Build check**

```bash
cd dashboard && npm run build 2>&1 | tail -20
```

**Step 4: Commit**

```bash
git add dashboard/src/components/landing/hero-section.tsx
git commit -m "feat(dashboard): refine hero — tighten height, raise animation opacity, add live stat pills and primary CTA"
```

---

### Task 5: Intelligence Pillars section

**Files:**
- Create: `dashboard/src/components/landing/intelligence-pillars.tsx`
- Modify: `dashboard/src/app/landing/page.tsx`

**Step 1: Create `intelligence-pillars.tsx`**

```tsx
export function IntelligencePillars() {
  const pillars = [
    {
      icon: "🧠",
      title: "Tiered Intelligence",
      body: "I1→I8 pipeline. 88 plugins: technical indicators, volatility models, Smart Money Concepts, pattern detection, signal generation, and AI narrative. Regime-aware gating at every layer.",
    },
    {
      icon: "📊",
      title: "CIS + Adaptive Scoring",
      body: "Composite Intelligence Score with regime-aware gating. Shadow signals feed adaptive weight learning — every suppressed signal trains the model. Confidence-gated signal selection.",
    },
    {
      icon: "🤖",
      title: "GLM-5 Narratives",
      body: "Per-signal LLM analysis via GLM-5. Group synthesis across 6 asset classes. Confidence-gated (>0.7) and staleness-aware. Falls back to local Ollama when needed.",
    },
  ];

  return (
    <section className="px-6 py-10">
      <div className="max-w-5xl mx-auto grid grid-cols-1 md:grid-cols-3 gap-4">
        {pillars.map((p) => (
          <div
            key={p.title}
            className="p-5 rounded-lg border"
            style={{
              background: "var(--surface-card)",
              borderColor: "var(--border-subtle)",
            }}
          >
            <div className="text-2xl mb-3">{p.icon}</div>
            <h3
              className="text-sm font-semibold mb-2"
              style={{
                color: "var(--text-primary)",
                fontFamily: "var(--font-display)",
              }}
            >
              {p.title}
            </h3>
            <p className="text-xs leading-relaxed" style={{ color: "var(--text-secondary)" }}>
              {p.body}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}
```

**Step 2: Add `IntelligencePillars` to `landing/page.tsx`**

Import it and add between `<HeroSection />` and the signals `<section>`:

```tsx
import { IntelligencePillars } from "@/components/landing/intelligence-pillars";
// ...
<HeroSection activeSignalCount={filteredSignals.length} />
<IntelligencePillars />
<section className="px-6 py-12"> {/* signals section */}
```

**Step 3: Build check**

```bash
cd dashboard && npm run build 2>&1 | tail -20
```

**Step 4: Commit**

```bash
git add dashboard/src/components/landing/intelligence-pillars.tsx dashboard/src/app/landing/page.tsx
git commit -m "feat(dashboard): add intelligence pillars section (tiered intelligence, CIS adaptive scoring, GLM-5 narratives)"
```

---

### Task 6: TF-aware signal filtering + signals section cleanup

**Files:**
- Modify: `dashboard/src/app/landing/page.tsx`

**Step 1: Replace the staleness filter logic in `filteredSignals`**

Replace the existing `const oneHourAgo = Date.now() - 3_600_000;` and its usage with TF-aware logic:

```typescript
// TF-aware staleness windows (ms) and long-TF caps
const TF_STALENESS_MS: Record<string, number> = {
  "1m":  15 * 60_000,
  "5m":  30 * 60_000,
  "15m": 60 * 60_000,
  "1h":  4 * 3_600_000,
  "4h":  8 * 3_600_000,
  "1d":  24 * 3_600_000,
};
const TF_MAX_SHOWN: Record<string, number> = {
  "1h": 3,
  "4h": 2,
  "1d": 1,
};
const longTfCounts: Record<string, number> = {};

const now = Date.now();
```

Then in the signal staleness check, replace:
```typescript
if (isNaN(signalTs) || signalTs < oneHourAgo) return;
```
With:
```typescript
const stalenessMs = TF_STALENESS_MS[tf] ?? 3_600_000;
if (isNaN(signalTs) || now - signalTs > stalenessMs) return;

// Cap long-TF signals
if (TF_MAX_SHOWN[tf] != null) {
  longTfCounts[tf] = (longTfCounts[tf] ?? 0);
  if (longTfCounts[tf] >= TF_MAX_SHOWN[tf]) return;
  longTfCounts[tf]++;
}
```

**Step 2: Remove the CTA from the signals section header**

The `"Enter Full Dashboard"` link is now in the hero. In the signals section header, replace:
```tsx
<Link href="/dashboard" className="..." style={{...}}>
  Enter Full Dashboard
  <ArrowRight size={18} />
</Link>
```
With a smaller secondary link:
```tsx
<Link
  href="/dashboard"
  className="text-sm font-medium flex items-center gap-1 hover:opacity-80 transition-opacity"
  style={{ color: "var(--accent-cyan)" }}
>
  View all <ArrowRight size={14} />
</Link>
```

**Step 3: Remove the `ArrowRight` import if no longer used at the same size (check usage)**

```bash
grep -n "ArrowRight" dashboard/src/app/landing/page.tsx
```

If still used (for the secondary link), keep it. Otherwise remove the import.

**Step 4: Build check**

```bash
cd dashboard && npm run build 2>&1 | tail -20
```

**Step 5: Commit**

```bash
git add dashboard/src/app/landing/page.tsx
git commit -m "feat(dashboard): TF-aware signal staleness filtering (5m=30min, 15m=1h, 1h≤3, 4h≤2) + secondary CTA in signals header"
```

---

### Task 7: Cleanup — remove feature-cards and pipeline architecture section

**Files:**
- Delete: `dashboard/src/components/landing/feature-cards.tsx`
- Modify: `dashboard/src/app/landing/page.tsx` (remove bottom pipeline section)
- Modify: `dashboard/src/components/landing/hero-section.tsx` (already rewritten in Task 4 — FeatureCards import removed)

**Step 1: Delete `feature-cards.tsx`**

```bash
rm dashboard/src/components/landing/feature-cards.tsx
```

**Step 2: Remove the "Intelligence Pipeline Architecture" section from `landing/page.tsx`**

Delete the entire `<section>` block at the bottom of `LandingPage` (the Layer 1–4 cards):

```tsx
// DELETE THIS ENTIRE BLOCK:
<section className="px-6 py-12 border-t">
  <div className="max-w-5xl mx-auto">
    <h2 ...>Intelligence Pipeline Architecture</h2>
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4" ...>
      {[...].map(...)}
    </div>
  </div>
</section>
```

**Step 3: Build check — verify no orphaned imports**

```bash
cd dashboard && npm run build 2>&1 | tail -20
```

Expected: clean build, no references to `feature-cards` or `FeatureCards`.

**Step 4: Commit**

```bash
git add -u dashboard/src/components/landing/feature-cards.tsx dashboard/src/app/landing/page.tsx
git commit -m "chore(dashboard): remove feature-cards component and pipeline architecture section (replaced by intelligence pillars)"
```

---

### Task 8: Visual verification

**Step 1: Start dev server**

```bash
cd dashboard && npm run dev -- --port 3000 --hostname 0.0.0.0 > /tmp/dash.log 2>&1 &
sleep 3 && tail -5 /tmp/dash.log
```

**Step 2: Check these visually**

- [ ] Hero: animation visible at ~65% opacity, not buried under cards
- [ ] Hero: headline + subline + 4 stat pills + large "Open Dashboard →" CTA
- [ ] Intelligence Pillars: 3 dark cards below hero, before signals
- [ ] Signal cards: intelligence context row visible (regime, ADX, killzone where active)
- [ ] Signals grid: dominated by 5m/15m cards, max 3 × 1h, max 2 × 4h
- [ ] Signals section header: small "View all →" secondary link only (no big CTA)
- [ ] Bottom pipeline section: gone
- [ ] Feature cards: gone

**Step 3: Stop dev server after verification**

```bash
pkill -f "next dev" || true
```
