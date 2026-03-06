# Signal Timing Visibility — Design Doc

**Date:** 2026-03-06
**Status:** Approved
**Scope:** Signal pipeline lag + staleness ratio on signal card and narrative panel

---

## Problem

The signal panel shows a static timestamp (`05:10`) with no context about:
1. How long the pipeline took to fire the signal after bar close (pipeline lag)
2. Whether the signal is stale relative to how many bar periods have elapsed (staleness)

The narrative panel has the same staleness blindness. A narrative generated 3 bar periods ago
may not reflect current market state.

Both data points are already captured in PostgreSQL — they are not flowing to the SSE stream
or being rendered in the UI.

---

## Renaissance Framing

- **Show raw numbers, not invented thresholds.** Color coding with arbitrary cutoffs (<1s green,
  >3s red) is aesthetic, not empirical. We show the data as-is and add a TODO to derive
  percentile-based thresholds once N > 100 signals with outcomes.
- **Staleness ratio is timeframe-agnostic.** `elapsed / bar_period` means the same thing across
  all TFs. `1.4×` on 5m = `1.4×` on 1m. The interpretation is consistent.
- **LLM inference time is deferred.** Narrative lag (signal → LLM → output) is 5–30s by design.
  Surfacing it as a latency metric without a baseline would be misleading. Track it via
  `llm_calls` hypertable; correlate with quality when N is sufficient.
- **This is hypothesis generation.** The hypothesis: high pipeline lag correlates with worse
  signal outcomes. Test it via `signal_ledger JOIN signal_lifecycle` once N > 100. The display
  generates the observation; the model produces the answer.

---

## Design

### Staleness Ratio

```
staleness_ratio = (now - signal_timestamp_ms) / bar_period_ms
```

- `signal_timestamp` = bar close time (already in `SignalData.timestamp`)
- `bar_period_ms` = TF in minutes × 60000
- Shown only when > 1.0× (one full bar has elapsed since signal fired)
- Hidden when < 1.0× (signal is still "current")

### Pipeline Lag

```
pipeline_lag_s = signal_computed_at - bar_close_ts  (seconds)
```

- `signal_computed_at` = when `signal_generator_service` fired the signal (already in `signal_ledger`)
- `bar_close_ts` = when the bar actually closed (already in `intelligence_features`, threaded through service)
- Currently NOT in Redis stream message — requires one backend change

### Display (SignalPanel)

```
SIG  5m  05:10 +0.8s  LONG  TrendF  87%
     E 5823.50 · SL 5810.00 · T1 5840.00  2.1R
     1.4× stale
```

- `+0.8s` — pipeline lag, shown inline after bar time; dim/muted color
- `1.4×` — staleness ratio; shown on row 3 only when > 1.0×; amber-dim > 1.0×, red-dim > 2.0×
  (thresholds are provisional — see TODO below)
- Both fields are optional: if `signal_computed_at` is missing (backfill signals), lag is hidden

### Display (NarrativePanel)

```
NARRATIVE  5m  1.4× stale  | Bullish bias — price testing demand zone...
```

- Same staleness ratio formula, same thresholds
- No pipeline lag (LLM inference time deferred)
- No backend change needed — `NarrativeData.timestamp` already available client-side

---

## Changes Required

### Backend — `services/signal_generator_service.py`

Add `signal_computed_at` and `bar_close_ts` to the Redis stream `message` dict before `xadd`:

```python
if signal_computed_at:
    message["signal_computed_at"] = signal_computed_at.isoformat()
if bar_close_ts:
    message["bar_close_ts"] = bar_close_ts.isoformat()
```

Verify `bar_close_ts` is in scope at the publish site (threaded through `_process_bar`).

### Backend — `src/api/routes/signals.py`

Expose `signal_computed_at` in REST response:
- Add `sl.signal_computed_at` to both SELECT queries (with and without features)
- Add to `_build_signal_row` output dict

### Frontend — `dashboard/src/lib/types.ts`

Extend `SignalData`:

```ts
signal_computed_at?: string;  // ISO — when generator fired
bar_close_ts?: string;        // ISO — when bar closed
pipeline_lag_s?: number;      // computed client-side: signal_computed_at - bar_close_ts
```

### Frontend — `dashboard/src/lib/format.ts` (or new `timing.ts`)

Shared utility used by both `SignalPanel` and `NarrativePanel`:

```ts
/** Returns staleness ratio (elapsed / bar_period). Returns null if < 1.0. */
export function stalenessRatio(timestamp: string, tfMinutes: number): number | null

/** Returns pipeline lag in seconds. Returns null if either timestamp missing. */
export function pipelineLagS(signalComputedAt: string, barCloseTs: string): number | null
```

### Frontend — `dashboard/src/hooks/use-market-stream.ts`

Parse `signal_computed_at` and `bar_close_ts` from SSE signal payload into `SignalData`.
Compute `pipeline_lag_s` at parse time (avoids recomputing on every render).

### Frontend — `dashboard/src/components/signal-panel.tsx`

- Add `+Xs` lag display inline after bar time on row 1
- Add `N.N× stale` on row 3 (below entry/stop/target row) when staleness > 1.0×
- Both fields conditionally rendered — absent for backfill signals

### Frontend — `dashboard/src/components/narrative-panel.tsx` (or `narrative-elevated.tsx`)

- Add `N.N× stale` inline in narrative header when staleness > 1.0×
- Use shared `stalenessRatio()` utility

---

## What Is NOT in This Scope

- CIS bucket breakdown / regime suppression visibility (separate design)
- LLM inference time on narratives (deferred until N > 100 with quality scores)
- Historical signal latency stats panel
- Percentile-based color thresholds (deferred — see TODO below)

---

## TODO (Future)

```
// TODO(v1.4-feedback): Replace provisional staleness thresholds (1.0×, 2.0×) and lag
// thresholds with percentile bands computed from signal_ledger once N > 100 signals
// have resolved outcomes. Run: SELECT percentile_cont(0.9) WITHIN GROUP (ORDER BY
// pipeline_lag_ms) FROM signal_ledger WHERE signal_computed_at IS NOT NULL;
// Hypothesis: high lag (>p90) correlates with worse signal_quality outcomes.
```

---

## Tests

- Unit: `stalenessRatio()` and `pipelineLagS()` with fixed timestamps
- Unit: `_build_signal_row` includes `signal_computed_at` in response
- Unit: signal generator Redis message dict contains `signal_computed_at` and `bar_close_ts`
- Integration: SSE signal payload contains new fields end-to-end
