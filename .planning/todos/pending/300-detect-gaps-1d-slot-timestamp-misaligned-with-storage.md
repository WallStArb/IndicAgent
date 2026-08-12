# 300 - `detect_gaps()`'s 1d expected-slot timestamp never matches stored 1d bars

**Filed:** 2026-08-11
**Source:** Found while investigating why AA's already-complete `1d`/`1h`/`15m` data was
being re-requested from IBKR on every backfill re-run (see [[project_universe_expansion_and_ibkr_recalibration_2026_08_06]]
memory, todo 296's saga). The clustering fix (same session, see that memory) fixed the
5m/15m case; this is a separate, lower-severity bug found along the way.
**Status:** pending, not blocking. Confirmed via direct comparison, not theorized.

## What

`generate_session_slots()`/`_slots_nyse()` (`src/core/bar_normalizer.py`) generates the
expected `1d` timestamp for a trading day at `_NYSE_SESSION_OPEN_HOUR = 4` (04:00 ET,
pre-market open) — this is correct for intraday timeframes (it's the natural first slot
within a stepped session window), but `1d` bars are actually stored at **midnight UTC**
(`market_data_ohlcv.timestamp = 00:00:00+00` for every daily bar, confirmed via direct
query). These two timestamps structurally never match:

```
$ generate_session_slots('nyse', 'SMART', '1d', 2016-10-18, 2016-10-20)
  2016-10-18T08:00:00+00:00   <- expected
  2016-10-19T08:00:00+00:00   <- expected

$ SELECT timestamp FROM market_data_ohlcv WHERE symbol='AA' AND timeframe='1d' ...
  2016-10-18 00:00:00+00      <- actual
  2016-10-19 00:00:00+00      <- actual
```

Because `detect_gaps()` compares expected-slot timestamps against actual-stored timestamps
by exact equality, `1d` gap detection has **never once correctly recognized existing daily
data**, for any symbol, since this comparison logic was written. Every backfill run for
every symbol always reports `1d` as fully missing and re-requests it from IBKR.

Root cause: `_slots_from_windows()` (shared by `_slots_nyse`/`_slots_futures`) treats every
timeframe uniformly as "step through the session window at `interval` spacing starting at
`day_open`" — correct for intraday grids, wrong for `1d`, which by convention is stored as
one date-anchored (midnight) row per trading day, not a session-open-anchored one.

## Why this is lower priority than it sounds

`infra.ibkr.chunk_days.1d = 7300` (migration 302) already fetches a symbol's full 20-year
`1d` history in **one single IBKR request** regardless of how many "gaps" `detect_gaps()`
reports — so this bug does not multiply into the expensive multi-chunk re-fetch pattern the
5m/15m clustering bug caused (todo 296/this session's fix). Practical cost is one redundant
(but `ON CONFLICT DO NOTHING`-safe, cheap) `1d` request per symbol per run, not a
pacing-budget-dominating one. Also confirmed: this session's actual completeness audits (the
`n_tf=5` row-existence SQL used throughout the universe-expansion work) are independent of
`detect_gaps()` and are unaffected by this bug.

## Fix (not yet implemented)

`1d` needs its own slot-generation path: one slot per trading day, anchored at midnight
(matching storage convention), not at `day_open`. Simplest fix: special-case
`timeframe == "1d"` in `generate_session_slots()` to emit `datetime(day.year, day.month,
day.day, 0, 0, tzinfo=UTC)` per trading day directly from the NYSE calendar schedule,
bypassing `_slots_from_windows()`'s session-open-anchored stepping entirely for this one
timeframe.

## Where

- `src/core/bar_normalizer.py` — `generate_session_slots()`, `_slots_nyse()`,
  `_slots_from_windows()`, `_NYSE_SESSION_OPEN_HOUR`
- `scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py` —
  `detect_gaps()` (the caller comparing expected vs. actual)
- Reproduction: `generate_session_slots('nyse', 'SMART', '1d', start, end)` vs. `SELECT
  timestamp FROM market_data_ohlcv WHERE timeframe='1d' LIMIT 5` for any equity symbol
