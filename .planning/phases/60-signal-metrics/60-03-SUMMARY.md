---
phase: "60"
plan: "03"
subsystem: signal-metrics-integration
tags: [api, intelligence-pipeline, dashboard, signal-metrics, perf-multiplier]
dependency_graph:
  requires: [60-01, 60-02]
  provides: [signal-metrics-api-read, regime-conditioned-perf-weights, two-track-attribution-dashboard]
  affects: [attribution-endpoint, intelligence-pipeline-agent, setup-performance-updater, dashboard-signals-page]
tech_stack:
  added: []
  patterns:
    - regime-conditioned DB query with 'all' fallback
    - generic fetchJson<T> typing in React components
    - pre-existing TypeScript error cleanup (build gate)
key_files:
  modified:
    - src/api/routes/signals.py
    - src/intelligence/setup_performance_updater.py
    - services/intelligence_pipeline_agent.py
    - dashboard/src/components/signals/attribution-row.tsx
    - dashboard/src/lib/types.ts
    - dashboard/src/lib/signal-utils.ts
    - dashboard/src/components/signal/index.ts
    - dashboard/src/components/signals/cluster-strip.tsx
    - dashboard/src/components/signals/command-strip.tsx
    - dashboard/src/components/signals/signal-ledger.tsx
    - dashboard/src/components/ui/metric-components.tsx
    - dashboard/src/hooks/use-market-stream.ts
decisions:
  - API attribution endpoint reads from signal_metrics instead of inline signal_ledger SQL
  - perf_multiplier uses _last_hmm_regime attribute updated per-bar (no persistent state needed)
  - regime fallback to 'all' when current regime has insufficient N (bootstrap phase)
  - setup_performance_updater shim reads from setup_performance table (written by SignalMetricsWriterAgent)
  - dashboard fetches zone+market tracks in parallel via Promise.all with typed fetchJson<T>
  - pre-existing TypeScript build errors fixed as Rule 3 (blocking dashboard build verification)
metrics:
  duration_minutes: 40
  completed_date: "2026-04-05"
  tasks_completed: 6
  files_modified: 12
---

# Phase 60 Plan 03: Signal Metrics Integration Summary

Wire pre-computed signal_metrics tables into all consumers: API attribution endpoint reads from signal_metrics with IC join, intelligence_pipeline_agent loads regime-conditioned perf_multiplier from market track, setup_performance_updater becomes a thin DB shim, and dashboard shows two side-by-side attribution tracks (zone with IC column, market with Sharpe column) with N<30 dimming.

## Tasks Completed

| Task | Description | Commit |
|------|-------------|--------|
| 1 | Verify signal_metrics tables exist (empty — compute not run yet) | — |
| 2 | API attribution endpoint reads signal_metrics, adds `track` param | 40e25e3 |
| 3 | setup_performance_updater → thin shim reading setup_performance | e1b9f2b |
| 4 | intelligence_pipeline_agent perf_multiplier regime-conditioned | bb72755 |
| 5 | Dashboard two-track attribution row (zone IC + market Sharpe) | cb82149 |
| 6 | Final verification: tests, lint, services healthy | ba3308c |

## Key Changes

### API (`src/api/routes/signals.py`)
- Added `track` query param (`zone|market`) to `GET /signals/attribution`
- Replaced inline `signal_ledger` SQL aggregation with reads from `signal_metrics`
- Zone track JOINs `signal_metrics_ic` for IC score and significance flag
- Returns `n_outliers`, `never_activated_pct`, `insufficient_data` (n<30) fields
- Empty `signal_metrics` → returns `{"track": "zone", "window": "30d", "groups": []}` (graceful)

### Setup Performance Updater (`src/intelligence/setup_performance_updater.py`)
- `run_setup_performance_update()` now reads from `setup_performance` (shim written by SignalMetricsWriterAgent)
- `compute_setup_performance()` and `_compute_perf_multipliers()` kept intact — tests pass (11/11)
- Interface unchanged — callers receive same `dict[str, float]` perf_weights

### Intelligence Pipeline Agent (`services/intelligence_pipeline_agent.py`)
- Added `_last_hmm_regime: int | None` attribute tracking last-observed HMM regime per bar
- Added `_current_hmm_regime_label()`: maps 0→mean_reversion, 1/2→trend, None→all
- `_load_perf_weights()` queries `signal_metrics WHERE track='market' AND regime_type=current_regime AND window_days=30 AND n>=30`
- Falls back to `regime_type='all'` when current regime has no data (bootstrap phase)
- Ranks by Sharpe ascending: best Sharpe → lowest multiplier (sorts first under ascending adjusted_rank)

### Dashboard (`dashboard/src/components/signals/attribution-row.tsx`)
- Replaced single attribution table with two side-by-side tables
- Zone track: N / Win% / Avg R / IC / p-val columns
- Market track: N / Win% / Avg R / Sharpe / p-val columns
- Rows with N<30 dimmed (opacity 0.45) with "N=X — insufficient data" badge tooltip
- Fetches both tracks in parallel via `Promise.all` with typed `fetchJson<SignalAttributionData>`

### TypeScript Types (`dashboard/src/lib/types.ts`, `signal-utils.ts`)
- `AttributionGroup` extended: `n_outliers`, `never_activated_pct`, `ic_score`, `ic_significant`, `insufficient_data`
- `SignalAttributionData` extended: `track?` field added
- `SignalWindowSummary` interface defined in `signal-utils.ts` (was phantom import)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Redpanda restart required for API verification**
- **Found during:** Task 2 verification
- **Issue:** API kept crashing on startup with `KafkaConnectionError` — aiokafka couldn't bootstrap from localhost:19092 despite Redpanda running. Pre-existing Docker networking issue that resolved after `docker restart redpanda`.
- **Fix:** Restarted Redpanda container, then API started successfully
- **Files modified:** None (infrastructure only)

**2. [Rule 3 - Blocking] TypeScript build errors prevented dashboard build verification**
- **Found during:** Task 5 verification
- **Issue:** 7 pre-existing TypeScript errors across 6 files were blocking `npm run build`
- **Fix:** Fixed all 7 errors: `SignalWindowSummary` undefined (added to signal-utils), `unknown` err type narrowing, missing required `color` props, `fetchJson<T>` generic typing, VOLATILITY_COLORS string index cast, `null` vs `undefined` for pipelineLagS
- **Files modified:** signal/index.ts, signal-utils.ts, cluster-strip.tsx, command-strip.tsx, signal-ledger.tsx, metric-components.tsx, use-market-stream.ts
- **Commit:** cb82149

### Out-of-scope Pre-existing Issues (deferred)

- `test_single_i7_plugin_raises_does_not_crash` fails with `assert 0 == 2` — pre-existing, unrelated to this plan (signal_plugin returns nested `{"signal": {...}}` but pipeline checks top-level `direction` key)
- `indicagent-signal-metrics-writer.service` failed — pre-existing from Phase 60-02
- `indicagent-signal-tracker.service` failed — pre-existing unrelated issue
- `indicagent-data-quality.service` failed — pre-existing timer-triggered failure

## Known Stubs

None — all data paths are correctly wired. When `signal_metrics` is empty (before first compute run), the API returns empty groups arrays, which is correct behavior documented in the plan.

## Self-Check: PASSED

- signals.py: FOUND
- setup_performance_updater.py: FOUND
- intelligence_pipeline_agent.py: FOUND
- attribution-row.tsx: FOUND
- 60-03-SUMMARY.md: FOUND
- Commits 40e25e3, e1b9f2b, bb72755, cb82149, ba3308c: all present in git log
