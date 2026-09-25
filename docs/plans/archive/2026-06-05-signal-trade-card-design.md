# Signal Trade Card — Design Spec

**Date:** 2026-06-05
**Status:** approved
**Scope:** Redesign the I7 Signal body in `drill-panel.tsx` — replace flat KV pairs with a purpose-built trade card that surfaces all four layers of signal intelligence at a glance.

---

## Problem

The current `signal-detail.tsx` renders entry, stop, and targets as flat key-value grid rows. Four categories of information are either absent or buried:

1. **R-multiple ladder** — no visual relationship between entry, stop, and targets
2. **Entry zone** — "perfect entry band" present in `SignalData` but not shown
3. **CIS breakdown** — bucket scores (trend/momentum/structure/etc.) absent entirely
4. **Setup edge** — win rate and avg R present in `SignalData` but not shown

---

## Architecture

### What stays unchanged

- `SignalDetailHeader` — direction badge, signal type, confidence %, timeframe, timestamp
- `SignalConfidencePipeline` — raw → filtered → calibrated confidence pipeline
- `SignalSwarmBreakdown` — AI swarm analysis (already lazy-fetched)
- `DrillPanel` structure — no changes outside the `Section` containing `SignalDetail`

### New component: `signal-trade-card.tsx`

`signal-detail.tsx` body is replaced with `<SignalTradeCard signal={signal} />`.

`SignalTradeCard` is composed of three sub-components rendered top-to-bottom, each separated by a thin divider:

```
<TradePriceLadder signal={signal} />
<CISBucketBreakdown signalId={signal.signal_id} />
<SetupEdgeLine signal={signal} />
```

---

## Block 1 — TradePriceLadder

**File:** `src/components/signal/signal-trade-card.tsx` (internal sub-component)

**Data source:** `SignalData` — no fetch required.

**Layout:** Vertical list of price levels sorted high → low. Direction-aware — for SHORT, stop appears above entry and targets appear below. For LONG, targets appear above entry and stop appears below.

**Row format per level:**

```
[dot] [LABEL]  [price]  [+/-R]  [target label]
```

- Dot color: green for targets, `var(--blue)` for entry, red for stop
- Label: `T3`, `T2`, `T1`, `ENTRY`, `SL`
- Price: `font-data`, right-aligned
- R value: `+2.1R` green / `-1.0R` red; omitted for entry row
- Target label: right-aligned muted text from `target_labels[]` (e.g., "S/R", "Fib 0.236", "BSL") — omitted if absent

**Entry zone band:** When `entry_zone_low` and `entry_zone_high` are present, both edges are inserted as `zone_edge` price levels in the ladder (sorted to their natural price position). Each renders with a left-border accent (green/red), diamond dot, and R-multiple. The `zone_high` row additionally shows `IN ZONE` (green) or `WAIT` (amber) badge based on `zone_valid_at_signal`. Rows between the zone bounds are lightly shaded using `var(--green-dim)` / `var(--red-dim)`. This two-row design shows both zone edge prices as discrete tradeable levels rather than collapsing to a single range label.

**Framing badge:** Top-right of the block — `structural` in green or `ATR fallback` in amber — derived from `framing_method`.

---

## Block 2 — CISBucketBreakdown

**File:** `src/components/signal/signal-trade-card.tsx` (internal sub-component)

**Data source:** Lazy fetch from `/api/signals/detail/{signal_id}` on mount. Same pattern as `SignalSwarmBreakdown`. Skeleton bars (grey, 60% and 40% width) shown while loading.

**Header row:** `CIS` label left, total score right — `cis_score` from `SignalData` (available immediately, no wait). Color: green if positive, red if negative.

**Bucket rows:** 6 bars — `trend`, `momentum`, `structure`, `institutional`, `regime`, `pattern`. Sorted by absolute magnitude (highest influence first). Each row:

```
[name 10ch]  [████░░░░░░]  [+0.72]
```

- Bar fill: green if positive, red if negative. Width = `abs(val) * 100%` capped at 100%.
- Value right-aligned, monospace, colored green/red.
- If fetch fails or returns null: `"No CIS breakdown available"` in muted italic.

---

## Block 3 — SetupEdgeLine

**File:** `src/components/signal/signal-trade-card.tsx` (internal sub-component)

**Data source:** `SignalData` — `setup_win_rate`, `setup_avg_pnl_r`. No fetch required.

**Render condition:** Only rendered if `setup_win_rate != null`. Silent if no sample data (< 30 bars).

**Layout:** Single compact row:

```
[plugin name]   Win [64%]   Avg [+1.2R]
```

- Plugin name: strip `trad_`, `ind_`, `smc_` prefix, muted text
- Win %: green if ≥ 50%, amber if 40–49%, red if < 40%
- Avg R: green if > 0, red if ≤ 0

---

## File Changes

| File | Action |
|------|--------|
| `src/components/signal/signal-trade-card.tsx` | Create — contains `SignalTradeCard`, `TradePriceLadder`, `CISBucketBreakdown`, `SetupEdgeLine` |
| `src/components/signal/signal-detail.tsx` | Update — replace body with `<SignalTradeCard />`, keep header + confidence pipeline + swarm |
| `src/components/signal/index.ts` | No change — `SignalDetail` export stays, internal implementation changes |

No other files change. The `signal-detail-panel.tsx` on the ledger page is untouched — it already has its own `PriceLadder` impl.

---

## Data Flow

```
SignalData (SSE stream)
  └── TradePriceLadder      — entry/stop/targets/zone/R-multiples (zero latency)
  └── SetupEdgeLine         — win rate / avg R (zero latency)
  └── CISBucketBreakdown    — bucket_scores (one fetch, ~50ms)
       └── /api/signals/detail/{signal_id}
```

---

## Non-Goals

- No changes to `signal-detail-panel.tsx` (ledger page) — it already has a price ladder
- No changes to `RecentSignals` / `recent-signal-card.tsx`
- No changes to `SignalScorecard`
- No new API endpoints — existing `/api/signals/detail/{id}` is sufficient
