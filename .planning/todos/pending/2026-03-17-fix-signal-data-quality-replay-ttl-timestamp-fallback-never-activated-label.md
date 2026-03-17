---
created: 2026-03-17T10:41:47.251Z
title: Fix signal data quality — replay TTL, timestamp fallback, never_activated label
area: general
files:
  - src/core/service_utils.py
  - services/signal_generator_service.py
  - production/scripts/lifecycle_replay.py
  - src/api/routes/signals.py:188,198
  - dashboard/src/components/signals/signal-ledger.tsx
  - tests/unit/scripts/test_lifecycle_replay.py
  - tests/unit/api_tests/test_signals_routes.py
  - production/migrations/035_stop_basis_and_divergence_stack.sql
---

## Problem

Five data quality issues discovered during post-Phase-32 audit:

1. **98% of signals show "-" for time in dashboard** — `signal_computed_at` is intentionally NULL for backfill (migration 014, "live-only"). `feature_ts` (bar close timestamp, 100% populated) is not used as fallback. Fix: `COALESCE(sl.signal_computed_at, sl.feature_ts)` in `/signals/recent` SELECT + ORDER BY.

2. **Lifecycle replay uses TTL=10 for all historical signals** — `ttl_bars` is not a DB column; `sig.get("ttl_bars", 10)` always falls back to 10. Per-TF TTLs from Phase 32-01 (`1m=20, 5m=12, 15m=8, 1h=6`) are never applied during replay. 1m signals are the most affected — evaluated with half the intended window. All 1m outcomes are wrong and need a re-replay after the fix.

3. **`bars_in_trade` always NULL for TTL-expired active signals** — hardcoded `None` in replay write path for TTL exits regardless of zone activation state. For signals that activated then hit TTL, should be `int((exit_at - activated_at) / tf_secs)`.

4. **`never_activated` pnl_r looks like a win (+14.2R)** — lifecycle_tracker correctly computes hypothetical pnl_r at TTL expiry as an entry-efficiency metric. Dashboard shows it identically to realized pnl_r. Fix: prefix with `~` in LedgerRow when `outcome === "never_activated"`.

5. **Migration 035 not applied** — Phase 32-01 DB schema (stop_basis, fire-time snapshots, chandelier columns) was committed but migration not run on live DB.

## Solution

Full plan at: `docs/superpowers/plans/2026-03-17-signal-data-quality-fixes.md`

Summary:
1. Move `TF_TTL_BARS` to `src/core/service_utils.py` (single source of truth; replay imports from there)
2. In lifecycle_replay `_process_symbol_tf`, inject `sig["ttl_bars"] = TF_TTL_BARS.get(timeframe, 10)` on each signal after DB fetch
3. Fix `bars_in_trade` for activated TTL exits in end-of-bars loop
4. `COALESCE(sl.signal_computed_at, sl.feature_ts)` in `/signals/recent` SELECT + ORDER BY
5. Dashboard: prefix `~` for `never_activated` pnl_r in LedgerRow
6. Apply migration 035 to live DB
7. Reset 1m signal outcomes and re-run lifecycle_replay --timeframes 1m
