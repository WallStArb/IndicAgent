# Price Hero Redesign

Date: 2026-02-25
Status: Approved

## Problem

The current price hero is split across two components — a price block in `trading-dashboard.tsx` and a `PriceHero` component below it. This creates:

- Session data duplicated across two visual zones
- Session range bar on its own full row (too heavy)
- Bid/Ask buried below the session range bar instead of near the price
- Bar H/L/vol row adding noise (bar-level, not session-level)
- VWAP showing `—` (not flowing — also in indicator grid)

## Design

### Layout

```
┌─ Card header ──────────────────────────────────────┐
│  E-Mini S&P 500  ESH6                    [ESH6]    │
├─ Price block ──────────────────────────────────────┤
│  5978.50  +5.25 (+0.09%)  vol 1.2M    SHORT 73%   │
│  Bid 5978.25  Ask 5978.50  spd 0.25   as of 10:45  │
│  O 5970.25  H 5983.50  L 5965.00  ━━●━━━━━━━      │
└────────────────────────────────────────────────────┘
```

**Line 1 — Live price:**
- Big flashing price (green/red vs session open, flash animation on tick)
- Session change: `+5.25 (+0.09%)` coloured green/red
- Session volume: `vol 1.2M` (accumulated from bar volumes, reset on new session date)
- LONG/SHORT confidence badge top-right — unchanged from current

**Line 2 — Market depth:**
- Bid / Ask / spread
- `as of HH:MM` timestamp pushed right (bar/indicator freshness)

**Line 3 — Session envelope:**
- Session O/H/L (`O 5970 H 5983 L 5965`)
- Small inline range bar showing where last price sits in session range (compact, half current height)

### What's Removed
- Standalone session range bar row (replaced by inline range bar on OHL line)
- Bar H/L/vol/VWAP row (bar-level noise; VWAP also in indicator grid)
- Bar range bar (bar-level, not session-level)

### Signals & Ambient — Unchanged
- LONG/SHORT badge with confidence % stays top-right of price block
- Card glow (green/red border when confidence >75%) unchanged

## Implementation

### Files Modified
- `dashboard/src/lib/types.ts` — add `sessionVolume: number` to `SessionState`
- `dashboard/src/hooks/use-market-stream.ts` — accumulate `sessionVolume` in `market_data` handler (sum `bar.volume`, reset on new session date)
- `dashboard/src/components/price-hero.tsx` — rewrite to 3-line layout
- `dashboard/src/components/trading-dashboard.tsx` — remove inline price block, render unified `PriceHero`

### Session Volume
Accumulated from `bar.volume` each 1m bar. Reset to 0 on `isNewSession`. No TWS daemon changes needed — bar volumes already flow through `market_data` SSE events.

### No-Data State
All fields show `—` until first data arrives. Volume shows `—` until first bar.
