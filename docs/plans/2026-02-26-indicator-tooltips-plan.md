# Indicator Tooltips Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add CSS-only hover tooltips to all I1–I7 indicators and fields in both the compact indicator grid and the drill panel, showing a static description + value-contextual interpretation.

**Architecture:** Three parts — (1) a reusable `<Tooltip>` wrapper component using Tailwind `group/group-hover` with opacity transition, zero JS; (2) a pure-function content file `indicator-tooltips.ts` with static descriptions and value-range context; (3) wiring into `<M>` in `indicator-grid.tsx` and `<KV>` in `drill-panel.tsx`. No new npm dependencies.

**Tech Stack:** React/TypeScript, Tailwind CSS 4.2.1 (already installed), Next.js 16.

---

## Task 1: Create the `<Tooltip>` wrapper component

This is a pure presentational component. No logic — just CSS hover behavior.

**Files:**
- Create: `dashboard/src/components/tooltip.tsx`

**Step 1: Create the file**

```tsx
// dashboard/src/components/tooltip.tsx
"use client";

import type { ReactNode } from "react";

export interface TooltipContent {
  /** One-line description of what this indicator measures. */
  description: string;
  /** Value-contextual interpretation, e.g. "Overbought — momentum may be fading." Null = omit. */
  context: string | null;
}

interface TooltipProps {
  children: ReactNode;
  tooltip: TooltipContent;
}

/**
 * CSS-only hover tooltip. Wraps children in a relative container and shows
 * a styled tooltip above on hover using Tailwind group/group-hover.
 * Zero JS, zero re-renders.
 */
export function Tooltip({ children, tooltip }: TooltipProps) {
  return (
    <span className="group relative inline-flex">
      {children}
      <span
        className="pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 mb-2 z-[9999]
                   w-52 rounded px-2.5 py-2 flex flex-col gap-1
                   border shadow-xl
                   opacity-0 group-hover:opacity-100 transition-opacity duration-150"
        style={{
          backgroundColor: "var(--bg-base)",
          borderColor: "var(--border-default)",
        }}
      >
        <span className="text-[0.55rem] leading-snug" style={{ color: "var(--text-secondary)" }}>
          {tooltip.description}
        </span>
        {tooltip.context && (
          <span
            className="text-[0.55rem] leading-snug font-medium border-t pt-1"
            style={{
              color: "var(--text-primary)",
              borderColor: "var(--border-subtle)",
            }}
          >
            {tooltip.context}
          </span>
        )}
      </span>
    </span>
  );
}
```

**Step 2: Verify it compiles**

```bash
cd dashboard && npx tsc --noEmit 2>&1 | head -20
```
Expected: 0 errors (file is not yet imported anywhere)

**Step 3: Commit**

```bash
git add dashboard/src/components/tooltip.tsx
git commit -m "feat(tooltip): add CSS-only Tooltip wrapper component"
```

---

## Task 2: Create `indicator-tooltips.ts` content file

Pure functions mapping indicator names + current values to `TooltipContent`. No I/O, no side effects — all string lookups and simple range checks.

**Files:**
- Create: `dashboard/src/lib/indicator-tooltips.ts`

**Step 1: Create the file**

```typescript
// dashboard/src/lib/indicator-tooltips.ts
import type { TooltipContent } from "@/components/tooltip";

// ─── I1 Indicator tooltips ────────────────────────────────────────────────────

export function rsiTooltip(value?: number | null): TooltipContent {
  const description = "Relative Strength Index (0–100). Momentum oscillator measuring speed and magnitude of price moves.";
  if (value == null) return { description, context: null };
  if (value > 70) return { description, context: `${value.toFixed(1)} — Overbought. Momentum may be fading; watch for reversal.` };
  if (value < 30) return { description, context: `${value.toFixed(1)} — Oversold. Selling may be exhausted; potential bounce.` };
  return { description, context: `${value.toFixed(1)} — Neutral zone. No extreme momentum pressure.` };
}

export function macdTooltip(histogram?: number | null): TooltipContent {
  const description = "MACD (12/26/9). Difference between 12-EMA and 26-EMA, smoothed by a 9-EMA signal line.";
  if (histogram == null) return { description, context: null };
  if (histogram > 0) return { description, context: "Histogram positive — bullish momentum building." };
  if (histogram < 0) return { description, context: "Histogram negative — bearish momentum building." };
  return { description, context: "Histogram at zero — momentum neutral / crossover." };
}

export function stochTooltip(k?: number | null): TooltipContent {
  const description = "Stochastic Oscillator (14,3). Compares close to the 14-bar range. K=fast line, D=3-bar smoothed.";
  if (k == null) return { description, context: null };
  if (k > 80) return { description, context: `K ${k.toFixed(0)} — Overbought. Watch for K crossing below D as exit signal.` };
  if (k < 20) return { description, context: `K ${k.toFixed(0)} — Oversold. Watch for K crossing above D as entry signal.` };
  return { description, context: `K ${k.toFixed(0)} — Mid-range. No overbought/oversold signal.` };
}

export function cciTooltip(value?: number | null): TooltipContent {
  const description = "Commodity Channel Index. Measures deviation from average price. ±100 are key thresholds.";
  if (value == null) return { description, context: null };
  if (value > 100) return { description, context: `${value.toFixed(0)} — Above +100: overbought / strong trend.` };
  if (value < -100) return { description, context: `${value.toFixed(0)} — Below −100: oversold / strong down-trend.` };
  return { description, context: `${value.toFixed(0)} — Between ±100: mean-reversion zone.` };
}

export function williamsRTooltip(value?: number | null): TooltipContent {
  const description = "Williams %R (−100 to 0). Inverted oscillator — readings near 0 are overbought, near −100 are oversold.";
  if (value == null) return { description, context: null };
  if (value > -20) return { description, context: `${value.toFixed(0)} — Overbought territory (near 0).` };
  if (value < -80) return { description, context: `${value.toFixed(0)} — Oversold territory (near −100).` };
  return { description, context: `${value.toFixed(0)} — Mid-range. No extreme reading.` };
}

export function atrTooltip(): TooltipContent {
  return {
    description: "Average True Range (14). Measures bar-to-bar volatility in price points. Higher = wider moves expected.",
    context: null,
  };
}

export function bbTooltip(): TooltipContent {
  return {
    description: "Bollinger Bands (20 SMA ± 2σ). Shows lower–upper boundary. Price near upper band = extended; near lower = depressed.",
    context: null,
  };
}

export function mfiTooltip(value?: number | null): TooltipContent {
  const description = "Money Flow Index (0–100). Volume-weighted RSI — measures buying vs. selling pressure.";
  if (value == null) return { description, context: null };
  if (value > 80) return { description, context: `${value.toFixed(1)} — Overbought on volume. Distribution likely.` };
  if (value < 20) return { description, context: `${value.toFixed(1)} — Oversold on volume. Accumulation likely.` };
  return { description, context: `${value.toFixed(1)} — Neutral flow. No volume-pressure extreme.` };
}

export function obvTooltip(): TooltipContent {
  return {
    description: "On-Balance Volume. Cumulative volume flow indicator. Rising OBV = accumulation; falling = distribution.",
    context: null,
  };
}

export function vwapTooltip(): TooltipContent {
  return {
    description: "Volume Weighted Average Price. Session fair value — heavily referenced by institutional traders for entries and exits.",
    context: null,
  };
}

export function sma20Tooltip(): TooltipContent {
  return {
    description: "SMA 20. Simple Moving Average over 20 bars. Short-term trend reference — price above = near-term bullish bias.",
    context: null,
  };
}

export function sma50Tooltip(): TooltipContent {
  return {
    description: "SMA 50. Simple Moving Average over 50 bars. Medium-term trend. Key institutional reference level.",
    context: null,
  };
}

export function ema13Tooltip(): TooltipContent {
  return {
    description: "EMA 13. Fast exponential moving average. Reacts quickly to momentum shifts; crossover with EMA 21 signals short-term entries.",
    context: null,
  };
}

export function ema21Tooltip(): TooltipContent {
  return {
    description: "EMA 21. Fibonacci exponential moving average. Trend confirmation; acts as dynamic support/resistance.",
    context: null,
  };
}

// ─── I3 Structure tooltips ────────────────────────────────────────────────────

export function trendIntegrityTooltip(value?: number | null): TooltipContent {
  const description = "Trend integrity (0–1). How consistently price is making higher highs/lower lows. Higher = cleaner trend.";
  if (value == null) return { description, context: null };
  if (value > 0.7) return { description, context: `${(value * 100).toFixed(0)}% — Strong, well-defined trend.` };
  if (value > 0.4) return { description, context: `${(value * 100).toFixed(0)}% — Moderate trend with some chop.` };
  return { description, context: `${(value * 100).toFixed(0)}% — Weak trend — consolidation or reversal likely.` };
}

export function supportResistanceTooltip(kind: "support" | "resistance"): TooltipContent {
  return {
    description: kind === "support"
      ? "Nearest structural support level. Price area where buyers have historically stepped in."
      : "Nearest structural resistance level. Price area where sellers have historically emerged.",
    context: null,
  };
}

export function levelStrengthTooltip(kind: "support" | "resistance", value?: number | null): TooltipContent {
  const description = `${kind === "support" ? "Support" : "Resistance"} strength (0–1). Based on touch count and hold history. Higher = more significant level.`;
  if (value == null) return { description, context: null };
  if (value > 0.7) return { description, context: `${value.toFixed(2)} — Strong level. Multiple tests and holds.` };
  if (value > 0.4) return { description, context: `${value.toFixed(2)} — Moderate level. Some validation.` };
  return { description, context: `${value.toFixed(2)} — Weak level. Limited test history.` };
}

// ─── I4 Context tooltips ──────────────────────────────────────────────────────

export function volRegimeTooltip(regime?: string | null): TooltipContent {
  const description = "Volatility regime from GARCH model: low, normal, high, or extreme.";
  const contextMap: Record<string, string> = {
    low: "Low — price moving in tight ranges. Breakout potential building.",
    normal: "Normal — typical session volatility. Standard position sizing appropriate.",
    high: "High — wider bars, elevated risk. Reduce size or widen stops.",
    extreme: "Extreme — crisis-level volatility. Caution: slippage and whipsaws likely.",
  };
  return { description, context: regime ? (contextMap[regime] ?? regime) : null };
}

export function atrPercentileTooltip(value?: number | null): TooltipContent {
  const description = "ATR percentile vs. 90-day history. Shows where current volatility ranks relative to recent past.";
  if (value == null) return { description, context: null };
  const pct = Math.round(value * 100);
  if (pct > 80) return { description, context: `${pct}th percentile — Elevated volatility. Wider-than-normal moves.` };
  if (pct < 20) return { description, context: `${pct}th percentile — Compressed volatility. Breakout may be building.` };
  return { description, context: `${pct}th percentile — Normal volatility range.` };
}

export function volExpandingTooltip(expanding?: boolean | null): TooltipContent {
  const description = "Whether volatility is actively expanding (true) or contracting (false).";
  if (expanding == null) return { description, context: null };
  return {
    description,
    context: expanding
      ? "Expanding — momentum is increasing. Breakout environment."
      : "Contracting — energy compressing. Potential coil before next move.",
  };
}

export function trendRegimeTooltip(regime?: string | null): TooltipContent {
  const description = "Kalman filter trend regime across 5 levels: strong_up, weak_up, neutral, weak_down, strong_down.";
  const contextMap: Record<string, string> = {
    strong_up: "Strong uptrend — price making sustained higher highs.",
    weak_up: "Weak uptrend — bullish bias but momentum unconvincing.",
    neutral: "No clear trend — mean-reversion environment.",
    weak_down: "Weak downtrend — bearish bias but momentum unconvincing.",
    strong_down: "Strong downtrend — price making sustained lower lows.",
  };
  return { description, context: regime ? (contextMap[regime] ?? regime) : null };
}

export function momentumBiasTooltip(value?: number | null): TooltipContent {
  const description = "Net momentum bias (−1 to +1). Aggregates multiple momentum signals into a single directional score.";
  if (value == null) return { description, context: null };
  if (value > 0.2) return { description, context: `+${value.toFixed(2)} — Bullish momentum bias.` };
  if (value < -0.2) return { description, context: `${value.toFixed(2)} — Bearish momentum bias.` };
  return { description, context: `${value.toFixed(2)} — Momentum neutral.` };
}

// ─── I5 Pattern tooltips ──────────────────────────────────────────────────────

export function rsiDivTooltip(divergence?: string | null): TooltipContent {
  const description = "RSI Divergence. Price and RSI moving in opposite directions — often precedes reversals.";
  const contextMap: Record<string, string> = {
    bullish: "Bullish divergence: price made a lower low but RSI made a higher low. Bearish momentum weakening.",
    bearish: "Bearish divergence: price made a higher high but RSI made a lower high. Bullish momentum weakening.",
  };
  return { description, context: divergence ? (contextMap[divergence] ?? null) : null };
}

export function bbSqueezeTooltip(active?: boolean | null, count?: number | null): TooltipContent {
  const description = "Bollinger Band squeeze. Bands contracting to unusually tight levels — energy building for a breakout.";
  if (active == null) return { description, context: null };
  if (!active) return { description, context: "No squeeze — bands at normal width." };
  return { description, context: `Squeeze active for ${count ?? 0} bars — the longer it holds, the bigger the potential breakout.` };
}

export function volDivTooltip(divergence?: string | null): TooltipContent {
  const description = "Volume divergence. Volume trend opposing price direction — suggests the move lacks conviction.";
  const contextMap: Record<string, string> = {
    bullish: "Bullish volume divergence: rising volume on up-moves, declining on down-moves. Buyers are committed.",
    bearish: "Bearish volume divergence: rising volume on down-moves, declining on up-moves. Sellers are committed.",
  };
  return { description, context: divergence ? (contextMap[divergence] ?? null) : null };
}

export function i5ConfluenceTooltip(value?: number | null): TooltipContent {
  const description = "I5 pattern confluence (0–1). Agreement across RSI divergence, BB squeeze, and volume divergence signals.";
  if (value == null) return { description, context: null };
  if (value > 0.7) return { description, context: `${value.toFixed(2)} — High confluence. Multiple pattern signals aligned.` };
  if (value > 0.4) return { description, context: `${value.toFixed(2)} — Moderate confluence. Partial signal agreement.` };
  return { description, context: `${value.toFixed(2)} — Low confluence. Patterns not confirming each other.` };
}

// ─── SMC tooltips ─────────────────────────────────────────────────────────────

export function bosTooltip(): TooltipContent {
  return {
    description: "Break of Structure (BOS). Price broke through a prior swing high (bullish) or low (bearish), confirming trend direction.",
    context: null,
  };
}

export function chochTooltip(): TooltipContent {
  return {
    description: "Change of Character (CHoCH). A BOS in the opposite direction of the prior trend — early warning of trend reversal.",
    context: null,
  };
}

export function fvgTooltip(): TooltipContent {
  return {
    description: "Fair Value Gap (FVG). An imbalance candle where price moved too fast, leaving a gap. Price tends to return and fill it.",
    context: null,
  };
}

export function orderBlockTooltip(): TooltipContent {
  return {
    description: "Order Block. The last opposing candle before a strong impulse move — marks an institutional supply (bearish) or demand (bullish) zone.",
    context: null,
  };
}

export function sweepTooltip(reclaimed?: boolean | null): TooltipContent {
  const description = "Liquidity Sweep. Price briefly extended beyond a key level to trigger stop orders, then reversed.";
  if (reclaimed == null) return { description, context: null };
  return {
    description,
    context: reclaimed
      ? "Level reclaimed — strong reversal signal. Smart money filled liquidity and reversed."
      : "Level not yet reclaimed — sweep may extend further before reversal.",
  };
}

export function hmmRegimeTooltip(regime?: number | null, prob?: number | null): TooltipContent {
  const description = "HMM Market Regime. Hidden Markov Model probability of ranging (0), trending up (1), or trending down (2).";
  if (regime == null) return { description, context: null };
  const labels = ["Ranging", "Trending up", "Trending down"];
  const label = labels[regime] ?? `Regime ${regime}`;
  const pct = prob != null ? ` (${(prob * 100).toFixed(0)}% confidence)` : "";
  return { description, context: `${label}${pct}.` };
}

export function liquidityLevelTooltip(kind: "BSL" | "SSL"): TooltipContent {
  return {
    description: kind === "BSL"
      ? "Buy-Side Liquidity (BSL). Cluster of stop-loss orders above recent swing highs. Price is often drawn to these levels before reversing."
      : "Sell-Side Liquidity (SSL). Cluster of stop-loss orders below recent swing lows. Price may target these before reversing.",
    context: null,
  };
}

// ─── I6 Confluence tooltips ───────────────────────────────────────────────────

export function ctfScoreTooltip(value?: number | null): TooltipContent {
  const description = "Cross-Timeframe (CTF) confluence score (0–1). How aligned 1m, 5m, 15m, and 1h are in trend direction and structure.";
  if (value == null) return { description, context: null };
  if (value > 0.7) return { description, context: `${value.toFixed(2)} — Strong multi-timeframe alignment. High-probability setup zone.` };
  if (value > 0.4) return { description, context: `${value.toFixed(2)} — Moderate alignment. Some timeframes conflicted.` };
  return { description, context: `${value.toFixed(2)} — Weak alignment. Timeframes disagree — lower-conviction environment.` };
}

export function ctfTfsAlignedTooltip(count?: number | null): TooltipContent {
  const description = "Timeframes aligned (out of 4: 1m/5m/15m/1h). How many are pointing in the same direction.";
  if (count == null) return { description, context: null };
  if (count >= 4) return { description, context: "All 4 timeframes aligned — maximum confluence." };
  if (count >= 3) return { description, context: "3 of 4 timeframes aligned — strong but not unanimous." };
  if (count >= 2) return { description, context: "2 of 4 aligned — mixed signals." };
  return { description, context: "1 or fewer aligned — timeframes conflicting." };
}

export function ctfTrendAlignTooltip(value?: number | null): TooltipContent {
  const description = "Trend alignment (0–1). Consistency of trend direction across all monitored timeframes.";
  if (value == null) return { description, context: null };
  if (value > 0.7) return { description, context: `${value.toFixed(2)} — Trends aligned across timeframes.` };
  if (value > 0.4) return { description, context: `${value.toFixed(2)} — Partial trend alignment.` };
  return { description, context: `${value.toFixed(2)} — Trend conflicted across timeframes.` };
}

export function ctfStructureAlignTooltip(value?: number | null): TooltipContent {
  return {
    description: "Structure alignment (0–1). Agreement on Break of Structure (BOS) and CHoCH events across timeframes.",
    context: value != null
      ? value > 0.6
        ? `${value.toFixed(2)} — Structure confirming across TFs.`
        : `${value.toFixed(2)} — Structure mixed across TFs.`
      : null,
  };
}

export function ctfRegimeAgreementTooltip(value?: number | null): TooltipContent {
  return {
    description: "Regime agreement (0–1). How many timeframes share the same volatility and trend regime.",
    context: value != null
      ? value > 0.6
        ? `${value.toFixed(2)} — Regimes consistent across TFs — stable environment.`
        : `${value.toFixed(2)} — Regimes mixed — market transitioning.`
      : null,
  };
}
```

**Step 2: Verify it compiles**

```bash
cd dashboard && npx tsc --noEmit 2>&1 | head -20
```
Expected: 0 errors

**Step 3: Commit**

```bash
git add dashboard/src/lib/indicator-tooltips.ts
git commit -m "feat(tooltip): add indicator-tooltips.ts — static descriptions + value-contextual content for I1-I7"
```

---

## Task 3: Wire tooltips into `indicator-grid.tsx`

Update the `<M>` component to accept a `TooltipContent` prop and wrap with `<Tooltip>` when provided. Remove the `title` prop (replaced by the styled tooltip). Update all `<M>` call sites with the appropriate tooltip functions.

**Files:**
- Modify: `dashboard/src/components/indicator-grid.tsx`

**Step 1: Replace the file contents**

The new `indicator-grid.tsx`:

```tsx
"use client";

import type { IndicatorData } from "@/lib/types";
import { fmtNum, oscClass, dirClass } from "@/lib/format";
import { Tooltip, type TooltipContent } from "@/components/tooltip";
import {
  rsiTooltip, macdTooltip, stochTooltip, cciTooltip, williamsRTooltip,
  atrTooltip, bbTooltip, mfiTooltip, obvTooltip, vwapTooltip,
  sma20Tooltip, sma50Tooltip, ema13Tooltip, ema21Tooltip,
} from "@/lib/indicator-tooltips";

interface IndicatorGridProps {
  indicators: IndicatorData | null;
}

export function IndicatorGrid({ indicators }: IndicatorGridProps) {
  const ind = indicators;

  return (
    <div className="divide-y divide-[var(--border-subtle)]">
      {/* Momentum */}
      <Zone label="MTM">
        <M
          label="RSI"
          value={fmtNum(ind?.rsi, 1)}
          cls={oscClass(ind?.rsi)}
          tooltip={rsiTooltip(ind?.rsi)}
        />
        <M
          label="MACD"
          value={fmtNum(ind?.macd, 2)}
          cls={dirClass(ind?.macd_histogram)}
          tooltip={macdTooltip(ind?.macd_histogram)}
        />
        <M
          label="Stoch"
          value={`${fmtNum(ind?.stoch_k, 0)}/${fmtNum(ind?.stoch_d, 0)}`}
          cls={oscClass(ind?.stoch_k, 80, 20)}
          tooltip={stochTooltip(ind?.stoch_k)}
        />
        <M
          label="CCI"
          value={fmtNum(ind?.cci, 0)}
          cls={dirClass(ind?.cci)}
          tooltip={cciTooltip(ind?.cci)}
        />
        <M
          label="W%R"
          value={fmtNum(ind?.williams_r, 0)}
          cls={oscClass(
            ind?.williams_r !== undefined ? -ind.williams_r : undefined,
            70,
            30
          )}
          tooltip={williamsRTooltip(ind?.williams_r)}
        />
      </Zone>

      {/* Volatility & Trend */}
      <Zone label="VOL">
        <M label="ATR" value={fmtNum(ind?.atr, 2)} tooltip={atrTooltip()} />
        <M
          label="BB"
          value={`${fmtNum(ind?.bb_lower, 0)}–${fmtNum(ind?.bb_upper, 0)}`}
          tooltip={bbTooltip()}
        />
        <M
          label="SMA20"
          value={fmtNum(ind?.sma_20, 0)}
          cls="text-[var(--text-accent)]"
          tooltip={sma20Tooltip()}
        />
        <M
          label="SMA50"
          value={fmtNum(ind?.sma_50, 0)}
          cls="text-[var(--text-accent)]"
          tooltip={sma50Tooltip()}
        />
        <M
          label="EMA13"
          value={fmtNum(ind?.ema_13, 0)}
          cls="text-[var(--text-accent)]"
          tooltip={ema13Tooltip()}
        />
        <M
          label="EMA21"
          value={fmtNum(ind?.ema_21, 0)}
          cls="text-[var(--text-accent)]"
          tooltip={ema21Tooltip()}
        />
      </Zone>

      {/* Volume */}
      <Zone label="VLME">
        <M
          label="MFI"
          value={fmtNum(ind?.mfi, 1)}
          cls={oscClass(ind?.mfi, 80, 20)}
          tooltip={mfiTooltip(ind?.mfi)}
        />
        <M label="OBV" value={fmtNum(ind?.obv, 0)} tooltip={obvTooltip()} />
        <M
          label="VWAP"
          value={fmtNum(ind?.vwap, 2)}
          cls="text-[var(--blue)]"
          tooltip={vwapTooltip()}
        />
      </Zone>
    </div>
  );
}

function Zone({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="px-2 py-1">
      <div className="flex items-start gap-2">
        <span className="zone-label shrink-0 pt-px w-10">{label}</span>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5">
          {children}
        </div>
      </div>
    </div>
  );
}

function M({
  label,
  value,
  cls = "text-[var(--text-accent)]",
  tooltip,
}: {
  label: string;
  value: string;
  cls?: string;
  tooltip?: TooltipContent;
}) {
  const inner = (
    <span className="inline-flex items-baseline gap-1 whitespace-nowrap">
      <span className="text-[0.55rem] font-medium uppercase tracking-wider text-[var(--text-muted)]">
        {label}
      </span>
      <span className={`font-data text-[0.7rem] font-medium ${cls}`}>
        {value}
      </span>
    </span>
  );

  if (!tooltip) return inner;
  return <Tooltip tooltip={tooltip}>{inner}</Tooltip>;
}
```

**Step 2: Build check**

```bash
cd dashboard && npm run build 2>&1 | tail -20
```
Expected: `✓ Compiled successfully` with 0 TypeScript errors. Fix any type errors before proceeding.

**Step 3: Commit**

```bash
git add dashboard/src/components/indicator-grid.tsx
git commit -m "feat(tooltip): wire tooltips into indicator-grid — all I1 indicators covered"
```

---

## Task 4: Wire tooltips into `drill-panel.tsx`

Update the `<KV>` component to accept an optional `tooltip` prop. Wrap the label span in `<Tooltip>` when provided. Add tooltip calls to all I1–I7 sections.

**Files:**
- Modify: `dashboard/src/components/drill-panel.tsx`

**Step 1: Replace the file contents**

The new `drill-panel.tsx`:

```tsx
// dashboard/src/components/drill-panel.tsx
"use client";

import { X } from "lucide-react";
import type { SymbolData, SignalData } from "@/lib/types";
import { fmtPrice, fmtNum } from "@/lib/format";
import { Tooltip, type TooltipContent } from "@/components/tooltip";
import {
  rsiTooltip, macdTooltip, stochTooltip, atrTooltip, vwapTooltip, mfiTooltip,
  ema13Tooltip, ema21Tooltip,
  trendIntegrityTooltip, supportResistanceTooltip, levelStrengthTooltip,
  volRegimeTooltip, atrPercentileTooltip, volExpandingTooltip,
  trendRegimeTooltip, momentumBiasTooltip,
  rsiDivTooltip, bbSqueezeTooltip, volDivTooltip, i5ConfluenceTooltip,
  bosTooltip, chochTooltip, fvgTooltip, orderBlockTooltip, sweepTooltip,
  hmmRegimeTooltip, liquidityLevelTooltip,
  ctfScoreTooltip, ctfTfsAlignedTooltip, ctfTrendAlignTooltip,
  ctfStructureAlignTooltip, ctfRegimeAgreementTooltip,
} from "@/lib/indicator-tooltips";

interface DrillPanelProps {
  symbol: string;
  timeframe: string;
  data: SymbolData;
  signal: SignalData | null;
  onClose: () => void;
}

export function DrillPanel({ symbol, timeframe, data, signal, onClose }: DrillPanelProps) {
  const intel = data.intelligenceByTf[timeframe] ?? null;
  const structure = intel?.structure ?? null;
  const context = intel?.context ?? null;
  const patterns = intel?.patterns ?? null;
  const smc = intel?.smartMoney ?? null;
  const confluence = intel?.confluence ?? null;
  const indicators = data.indicatorsByTf[timeframe] ?? null;

  return (
    <>
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

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-3">
          {/* I7 Signal */}
          <Section label="I7 Signal">
            {signal ? (
              <SignalDetail signal={signal} />
            ) : (
              <Empty>No signal for {timeframe} — signals are generated on 1m</Empty>
            )}
          </Section>

          {/* I3 Structure */}
          <Section label="I3 Structure">
            {structure ? (
              <Grid>
                <KV label="Trend" value={structure.swing_trend ?? "—"} />
                <KV
                  label="Integrity"
                  value={structure.trend_integrity != null ? `${(structure.trend_integrity * 100).toFixed(0)}%` : "—"}
                  tooltip={trendIntegrityTooltip(structure.trend_integrity)}
                />
                <KV
                  label="Support"
                  value={fmtPrice(structure.nearest_support)}
                  tooltip={supportResistanceTooltip("support")}
                />
                <KV
                  label="Resistance"
                  value={fmtPrice(structure.nearest_resistance)}
                  tooltip={supportResistanceTooltip("resistance")}
                />
                <KV
                  label="Support str"
                  value={fmtNum(structure.support_strength, 2)}
                  tooltip={levelStrengthTooltip("support", structure.support_strength)}
                />
                <KV
                  label="Resist str"
                  value={fmtNum(structure.resistance_strength, 2)}
                  tooltip={levelStrengthTooltip("resistance", structure.resistance_strength)}
                />
              </Grid>
            ) : <Empty>Awaiting {timeframe} intelligence</Empty>}
          </Section>

          {/* I4 Context */}
          <Section label="I4 Context">
            {context ? (
              <Grid>
                <KV
                  label="Vol regime"
                  value={context.volatility_regime ?? "—"}
                  tooltip={volRegimeTooltip(context.volatility_regime)}
                />
                <KV
                  label="ATR pctile"
                  value={context.atr_percentile != null ? `${(context.atr_percentile * 100).toFixed(0)}%` : "—"}
                  tooltip={atrPercentileTooltip(context.atr_percentile)}
                />
                <KV
                  label="Vol expan"
                  value={context.vol_expanding != null ? (context.vol_expanding ? "yes" : "no") : "—"}
                  tooltip={volExpandingTooltip(context.vol_expanding)}
                />
                <KV
                  label="Trend"
                  value={context.trend_regime ?? "—"}
                  tooltip={trendRegimeTooltip(context.trend_regime)}
                />
                <KV
                  label="Mom bias"
                  value={context.momentum_bias != null ? fmtNum(context.momentum_bias, 2) : "—"}
                  tooltip={momentumBiasTooltip(context.momentum_bias)}
                />
                <KV label="Mom dir" value={context.momentum_direction ?? "—"} />
              </Grid>
            ) : <Empty>Awaiting {timeframe} intelligence</Empty>}
          </Section>

          {/* I5 Patterns */}
          <Section label="I5 Patterns">
            {patterns ? (
              <Grid>
                <KV
                  label="RSI div"
                  value={patterns.rsi_divergence ?? "none"}
                  tooltip={rsiDivTooltip(patterns.rsi_divergence)}
                />
                <KV label="RSI conf" value={fmtNum(patterns.rsi_div_confidence, 2)} />
                <KV
                  label="BB squeeze"
                  value={patterns.bb_squeeze != null ? (patterns.bb_squeeze ? `yes (${patterns.squeeze_count ?? 0}b)` : "no") : "—"}
                  tooltip={bbSqueezeTooltip(patterns.bb_squeeze, patterns.squeeze_count)}
                />
                <KV
                  label="Vol div"
                  value={patterns.volume_divergence ?? "none"}
                  tooltip={volDivTooltip(patterns.volume_divergence)}
                />
                <KV
                  label="Confluence"
                  value={patterns.confluence_score != null ? fmtNum(patterns.confluence_score, 2) : "—"}
                  tooltip={i5ConfluenceTooltip(patterns.confluence_score)}
                />
              </Grid>
            ) : <Empty>Awaiting {timeframe} intelligence</Empty>}
          </Section>

          {/* SMC */}
          <Section label="Smart Money">
            {smc ? (
              <Grid>
                <KV
                  label="BOS"
                  value={smc.bos_detected ? `${(smc.bos_direction ?? 0) > 0 ? "bullish" : "bearish"} @ ${fmtPrice(smc.bos_level)}` : "none"}
                  tooltip={bosTooltip()}
                />
                <KV
                  label="CHoCH"
                  value={smc.choch_detected ? `${(smc.choch_direction ?? 0) > 0 ? "bullish" : "bearish"}` : "none"}
                  tooltip={chochTooltip()}
                />
                <KV
                  label="FVG"
                  value={(smc.fvg_type ?? 0) !== 0 ? `${(smc.fvg_type ?? 0) > 0 ? "bull" : "bear"} ${fmtPrice(smc.fvg_bottom)}–${fmtPrice(smc.fvg_top)}` : "none"}
                  tooltip={fvgTooltip()}
                />
                <KV
                  label="Order blk"
                  value={(smc.ob_type ?? 0) !== 0 ? `${(smc.ob_type ?? 0) > 0 ? "bull" : "bear"} @ ${fmtPrice(smc.ob_bottom)}` : "none"}
                  tooltip={orderBlockTooltip()}
                />
                <KV
                  label="Sweep"
                  value={smc.sweep_detected ? `${(smc.sweep_type ?? 0) > 0 ? "bullish" : "bearish"}${smc.sweep_reclaimed ? " ✓reclaimed" : ""}` : "none"}
                  tooltip={sweepTooltip(smc.sweep_reclaimed)}
                />
                <KV
                  label="HMM regime"
                  value={smc.hmm_regime != null ? `${["ranging","up","down"][smc.hmm_regime] ?? smc.hmm_regime} (${((smc.hmm_regime_prob ?? 0) * 100).toFixed(0)}%)` : "—"}
                  tooltip={hmmRegimeTooltip(smc.hmm_regime, smc.hmm_regime_prob)}
                />
                <KV
                  label="BSL"
                  value={smc.bsl_level != null ? `${fmtPrice(smc.bsl_level)} (${fmtNum(smc.bsl_dist_atr, 1)} ATR)` : "—"}
                  tooltip={liquidityLevelTooltip("BSL")}
                />
                <KV
                  label="SSL"
                  value={smc.ssl_level != null ? `${fmtPrice(smc.ssl_level)} (${fmtNum(smc.ssl_dist_atr, 1)} ATR)` : "—"}
                  tooltip={liquidityLevelTooltip("SSL")}
                />
              </Grid>
            ) : <Empty>Awaiting {timeframe} intelligence</Empty>}
          </Section>

          {/* I6 Cross-TF Confluence */}
          <Section label="I6 Confluence">
            {confluence ? (
              <Grid>
                <KV
                  label="CTF score"
                  value={fmtNum(confluence.ctf_score, 2)}
                  tooltip={ctfScoreTooltip(confluence.ctf_score)}
                />
                <KV
                  label="TFs aligned"
                  value={`${confluence.ctf_timeframes_aligned ?? 0}/4`}
                  tooltip={ctfTfsAlignedTooltip(confluence.ctf_timeframes_aligned)}
                />
                <KV
                  label="Trend align"
                  value={fmtNum(confluence.ctf_trend_alignment, 2)}
                  tooltip={ctfTrendAlignTooltip(confluence.ctf_trend_alignment)}
                />
                <KV
                  label="Structure"
                  value={fmtNum(confluence.ctf_structure_alignment, 2)}
                  tooltip={ctfStructureAlignTooltip(confluence.ctf_structure_alignment)}
                />
                <KV
                  label="Regime agr"
                  value={fmtNum(confluence.ctf_regime_agreement, 2)}
                  tooltip={ctfRegimeAgreementTooltip(confluence.ctf_regime_agreement)}
                />
              </Grid>
            ) : <Empty>Awaiting {timeframe} intelligence</Empty>}
          </Section>

          {/* I1 Indicators */}
          <Section label="I1 Indicators">
            {indicators ? (
              <Grid>
                <KV
                  label="RSI"
                  value={fmtNum(indicators.rsi, 1)}
                  tooltip={rsiTooltip(indicators.rsi)}
                />
                <KV
                  label="MACD"
                  value={fmtNum(indicators.macd, 2)}
                  tooltip={macdTooltip(indicators.macd_histogram)}
                />
                <KV
                  label="Stoch K/D"
                  value={`${fmtNum(indicators.stoch_k, 1)} / ${fmtNum(indicators.stoch_d, 1)}`}
                  tooltip={stochTooltip(indicators.stoch_k)}
                />
                <KV
                  label="ATR"
                  value={fmtNum(indicators.atr, 2)}
                  tooltip={atrTooltip()}
                />
                <KV
                  label="VWAP"
                  value={fmtPrice(indicators.vwap)}
                  tooltip={vwapTooltip()}
                />
                <KV
                  label="MFI"
                  value={fmtNum(indicators.mfi, 1)}
                  tooltip={mfiTooltip(indicators.mfi)}
                />
                <KV
                  label="EMA 13/21"
                  value={`${fmtPrice(indicators.ema_13)} / ${fmtPrice(indicators.ema_21)}`}
                  tooltip={ema13Tooltip()}
                />
              </Grid>
            ) : <Empty>Awaiting {timeframe} indicators</Empty>}
          </Section>
        </div>
      </div>
    </>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="text-[0.55rem] font-semibold uppercase tracking-widest text-[var(--text-muted)] mb-1.5">
        {label}
      </h3>
      <div
        className="rounded px-3 py-2"
        style={{ backgroundColor: "var(--bg-elevated)" }}
      >
        {children}
      </div>
    </div>
  );
}

function Grid({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-1">
      {children}
    </div>
  );
}

function KV({
  label,
  value,
  tooltip,
}: {
  label: string;
  value: string;
  tooltip?: TooltipContent;
}) {
  const labelEl = (
    <span className="text-[0.55rem] text-[var(--text-muted)] shrink-0">{label}</span>
  );

  return (
    <div className="flex items-baseline justify-between gap-1 min-w-0">
      {tooltip ? (
        <Tooltip tooltip={tooltip}>{labelEl}</Tooltip>
      ) : (
        labelEl
      )}
      <span className="text-[0.6rem] font-data text-[var(--text-secondary)] truncate text-right">
        {value}
      </span>
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <span className="text-[0.6rem] italic text-[var(--text-muted)]">{children}</span>
  );
}

function SignalDetail({ signal }: { signal: SignalData }) {
  const isLong = signal.direction === "long";
  const target = signal.profit_target ?? null;
  const rr = signal.risk_reward_ratio ?? 0;
  const dirColor = isLong ? "var(--green)" : "var(--red)";
  const timeStr = signal.timestamp
    ? new Date(signal.timestamp).toLocaleTimeString([], {
        hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
      })
    : "—";

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2 flex-wrap">
        <span
          className="inline-flex px-2 py-0.5 rounded text-[0.6rem] font-bold uppercase tracking-widest"
          style={{ backgroundColor: isLong ? "var(--green-dim)" : "var(--red-dim)", color: dirColor }}
        >
          {isLong ? "LONG" : "SHORT"}
        </span>
        <span className="text-[0.6rem] text-[var(--text-secondary)]">{signal.signal_type.replace(/_/g, " ")}</span>
        <span className="text-[0.6rem] font-bold font-data" style={{ color: dirColor }}>{(signal.confidence * 100).toFixed(0)}%</span>
        <span className="text-[0.55rem] text-[var(--text-muted)]">{signal.timeframe} · {timeStr}</span>
      </div>
      <Grid>
        <KV label="Entry" value={fmtPrice(signal.entry_price)} />
        <KV label="Stop loss" value={fmtPrice(signal.stop_loss)} />
        {target !== null && <KV label="Profit target" value={fmtPrice(target)} />}
        {rr > 0 && <KV label="Risk/Reward" value={`${fmtNum(rr, 1)}R`} />}
        <KV label="Regime" value={signal.regime_context} />
        <KV label="Plugin" value={signal.setup_plugin.replace(/^trad_/, "")} />
      </Grid>
    </div>
  );
}
```

**Step 2: Build check**

```bash
cd dashboard && npm run build 2>&1 | tail -20
```
Expected: `✓ Compiled successfully` — 0 errors. Fix any errors before proceeding.

**Step 3: Commit**

```bash
git add dashboard/src/components/drill-panel.tsx
git commit -m "feat(tooltip): wire tooltips into drill-panel — I1-I7 all covered"
```

---

## Task 5: Verify in dev server

**Step 1: Start dev server if not running**

```bash
cd dashboard && npm run dev -- --port 3000 --hostname 0.0.0.0 > /tmp/dash.log 2>&1 &
```

**Step 2: Open dashboard and verify**

1. Open `http://localhost:3000` in browser
2. Hover over any indicator label in a symbol card (RSI, MACD, Stoch, etc.) — tooltip should appear above
3. Check tooltip shows: description (grey) + contextual line (white, after separator) when value is at an extreme
4. Click a symbol to open drill panel — hover field labels in I3–I7 sections — tooltips appear
5. Check that tooltips don't get clipped by card overflow (if they do, report for follow-up)
6. Verify no layout shifts — other elements don't move when tooltip appears

**Step 3: Check browser console for errors**

Open DevTools console — should be clean (no React warnings or errors).

**Step 4: Final commit**

```bash
git add -A
git commit -m "feat(tooltip): indicator tooltips complete — CSS-only, I1-I7, static+contextual content"
```

---

## Success Checklist

- [ ] `<Tooltip>` component created with CSS-only hover, no JS, opacity fade
- [ ] `indicator-tooltips.ts` covers all 14 I1 indicators + all I3-I7 drill panel fields
- [ ] `indicator-grid.tsx` wired — all 14 indicators have tooltip
- [ ] `drill-panel.tsx` wired — all I1-I7 fields with meaningful tooltips
- [ ] `npm run build` passes 0 TypeScript errors
- [ ] Hovering indicator label shows styled dark tooltip above element
- [ ] Contextual line appears only when value crosses a threshold (RSI > 70 etc.)
- [ ] No new npm dependencies added
- [ ] No layout shift, no z-index conflicts with drill panel overlay
