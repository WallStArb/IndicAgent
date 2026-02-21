# Historical Backfill Pipeline — Design

**Date:** 2026-02-21
**Status:** Approved
**Replaces:** `production/scripts/simple_seeder.py` (retired)

---

## Problem

New machine setup has no historical data. The `simple_seeder.py` only seeds raw OHLCV and has
stale hardcoded Sep 2025 contract expiries. ML calibration (Phase 3) requires 500+ signals in
`signal_ledger` with outcomes — waiting for 17+ days of live collection is impractical when 90
days of historical bars are available from IBKR.

## Goal

Single script that:
1. Fetches historical 1m bars from IBKR for all 14 active instruments
2. Stores them in TimescaleDB (`market_data_ohlcv`)
3. Replays bars through the full I1→I3→I4→I5→SMC→I6→I7 intelligence pipeline
4. Writes generated signals to `signal_ledger` — ready for ML training

---

## Script: `production/scripts/historical_backfill.py`

This becomes the **canonical seeding script** for new machine setup.

### CLI Interface

```bash
# Full pipeline — fetch + replay (default: 90 days, all 14 instruments)
python production/scripts/historical_backfill.py --days 90

# Fetch only — skip intelligence replay
python production/scripts/historical_backfill.py --days 90 --fetch-only

# Replay only — data already in DB, skip IBKR fetch
python production/scripts/historical_backfill.py --replay-only

# Specific symbols
python production/scripts/historical_backfill.py --symbols ESH6,NQH6 --days 30

# Custom IBKR connection
python production/scripts/historical_backfill.py --client-id 56 --days 90
```

---

## Architecture: Two Stages

### Stage 1 — IBKR Fetch + DB Store

- Load contracts from `Settings.contracts` — all 14 H6 instruments, current expiries, no hardcoding
- Connect to IBKR TWS via `ib_insync` synchronously (same as `simple_seeder.py`)
- Request `--days` of 1m bars per contract via `reqHistoricalData` with `useRTH=False`
  (include pre/post-market for metals, energy, rates that trade 23h)
- Upsert into `market_data_ohlcv` with `ON CONFLICT DO NOTHING` — idempotent, safe to re-run
- Rate-limit 2s between contracts to respect IBKR pacing rules
- Print per-contract progress: `ESH6: 57,240 bars fetched, 57,198 stored (42 dupes skipped)`

### Stage 2 — Intelligence Replay

After all bars are stored, iterate symbol × timeframe in chronological order:

**Timeframe aggregation (in Python, no TimescaleDB dependency):**
- Query 1m bars from DB ordered by timestamp ASC
- Bucket into 5m, 15m, 1h bars using time-bucket logic
- Also store aggregated bars in `market_data_ohlcv` (timeframe='5m' etc.) for completeness

**Per-bar replay loop (same logic as live services, no Redis):**

```
for each (symbol, timeframe) pair:
    bar_history = deque(maxlen=200)         # same as indicator_service
    intelligence_cache = {}                  # same as market_analysis_service

    for each bar in chronological order:
        bar_history.append(bar)

        # I1 — run indicator plugins
        features = run_i1_plugins(bar, bar_history)

        if len(bar_history) < min_bars:     # skip until warmed up
            continue

        # Build frames dict (same structure as market_analysis_service)
        frames = {"main": DataFrame(bar_history), "features": features}

        # I3 → I4 → I5 → SMC → I6
        intelligence = run_analysis_pipeline(frames, symbol, timeframe)

        # I7 — run setup plugins, aggregate, write to signal_ledger
        signals = run_i7_plugins(bar, intelligence, bar_history)
        if signals:
            result = aggregate(signals)
            entries = build_ledger_entries(result, symbol, timeframe, bar.timestamp, intelligence)
            insert_signals(db_conn, entries)
```

**Reused from existing services (no duplication):**
- `register_all_plugins()` — loads all 53 plugins
- `registry.get_indicator(name).compute_full(frames)` — I1 execution
- `registry.get_pattern(name).compute_full(frames)` — I3–I7 execution
- `aggregate(signals)` — from `src/intelligence/trading/aggregator.py`
- `build_ledger_entries()` — from `services/signal_generator_service.py` (or extracted to shared module)
- `insert_signals()` — from `src/intelligence/trading/signal_ledger.py`

**Cross-timeframe context:**
- `market_analysis_service` injects `tf_1m`, `tf_5m` etc. frames for I6 confluence plugin
- Replay processes timeframes in order (1m first, then 5m, 15m, 1h) so lower-TF history is
  available when higher-TF runs
- Intelligence cache shared across timeframes per symbol (same as live)

---

## What Gets Written to DB

| Table | Content |
|-------|---------|
| `market_data_ohlcv` | 1m bars + computed 5m/15m/1h aggregated bars |
| `signal_ledger` | Historical signals, `status='pending'`, `pnl_r=NULL` (no lifecycle) |

## What Does NOT Happen

- **No Redis writes** — replay is purely DB-to-DB, no interference with live services
- **No I8 AI narratives** — generated live by `ai_narrative_service` as signals flow
- **No lifecycle tracking** — `pnl_r`, `exit_price`, `exit_reason` stay NULL on historical signals
  (signal_tracker_service only operates on live bars going forward)

---

## Expected Output (90-day run, all 14 instruments)

| Metric | Estimate |
|--------|---------|
| 1m bars fetched | ~490,000 (14 symbols × ~390 bars/trading day × ~90 trading days) |
| Signals generated | ~2,700 (30/day × 90 days) — well past 500+ ML threshold |
| IBKR fetch time | ~15–20 min (rate-limited) |
| Replay time | ~10–15 min (CPU-bound, no I/O wait) |
| Total runtime | ~30 min |

---

## Files

| File | Action |
|------|--------|
| `production/scripts/historical_backfill.py` | **CREATE** — new canonical seeder |
| `production/scripts/simple_seeder.py` | **RETIRE** — superseded (leave in place, add deprecation note) |
| `scripts/historical_to_redis_publisher.py` | **KEEP** — still useful for pushing DB data to Redis for testing |

---

## Retirement Note for `simple_seeder.py`

`simple_seeder.py` is superseded by `historical_backfill.py`. Differences:
- Hardcoded expired Sep 2025 contracts → backfill uses `Settings.contracts` (always current)
- Only 8 of 14 instruments → backfill covers all 14
- No intelligence replay → backfill runs full I1–I7 pipeline
- No multi-timeframe → backfill generates 5m/15m/1h bars too
