---
created: 2026-03-09T00:32:22.070Z
title: Seed signal generator bar history from DB on startup
area: general
files:
  - services/signal_generator_service.py
---

## Problem

After every restart, the signal generator waits ~50 minutes for live 1m bars to fill `bar_history` before it fires any signals. This is painful on weekend market reopens (Sunday 6pm ET) and after any service restart. The data exists in `intelligence_features` (TimescaleDB hypertable) — we're just not using it at startup.

Discovered during: Sunday market reopen 2026-03-08. Signal generator was SIGKILL'd at 20:12 ET (timed out on shutdown) and the 50-bar warmup meant no signals until ~21:00.

## Solution

On startup, before entering the live stream loop, query `intelligence_features` for the last N bars per (symbol, timeframe) and inject them into `bar_history` (and any other per-symbol state like `_plugin_states`). This eliminates the warmup delay entirely.

Key considerations:
- Query `intelligence_features` for last 60+ rows per `(symbol, feature_tf)` ordered by `feature_ts DESC`
- Reconstruct the dict format expected by `bar_history` from the JSONB feature columns
- Must run before `xreadgroup` loop starts, not block the event loop (run as async startup task)
- Consumer group should still start at `$` (current position) — backfill is for warmup only, not reprocessing
- Also consider seeding `indicator_service` bar_history from `market_data_ohlcv` for the same reason (separate todo candidate)
- See `CONCERNS.md` line 38: "Stateful plugins (GARCH, Kalman) lose warm-up state" — separate concern, this todo is specifically about the 50-bar minimum for signal firing
