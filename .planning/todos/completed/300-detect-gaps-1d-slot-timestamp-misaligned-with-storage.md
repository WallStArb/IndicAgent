## CLOSED 2026-08-21

Fixed as scoped: `generate_session_slots()` now special-cases `timeframe == "1d"` for
`session_id == "nyse"`, delegating to a new `_slots_nyse_daily()` that emits one
midnight-UTC slot per NYSE trading day (matching `market_data_ohlcv`'s actual `1d` storage
convention) instead of falling through to `_slots_nyse`'s session-open-anchored intraday
stepping. Scoped to `nyse` only -- confirmed live (2026-08-21) that zero futures/fx `1d` rows
exist in the DB, so `futures_24_5`/`fx_24_5`/`crypto_24_7` are left on the existing path,
unverified against any real stored convention for those session types (would need its own
investigation if/when those ever get `1d` data).

Caught a real edge case while writing tests: computing the calendar query's date bounds via
`start.astimezone(ET).date()`/`end.astimezone(ET).date()` (matching `_slots_nyse`'s existing
pattern) silently rolls a UTC-midnight `end` back to the previous ET calendar day (ET is behind
UTC), truncating the schedule query one day short. Fixed by querying the calendar in UTC dates
directly instead (a `1d` slot IS a UTC date, no reason to route through ET here) -- the final
`start <= slot <= end` filter still bounds the output precisely regardless of query width.

5 new regression tests (`TestNyse1d` in `tests/unit/core/test_bar_normalizer.py`), including the
exact 2016-10-18/19 reproduction from this todo's own filing. Full `tests/unit/` green,
ruff/black clean. (Correction: the `/code-review medium` agent originally dispatched for this
fix failed on an unrelated API session limit mid-run, not a finding against the code -- reviewed
directly instead before committing.)

**`/simplify` pass, same day:** 4 parallel review agents (reuse/simplification/efficiency/
altitude) converged on one real finding -- `_slots_nyse_daily()` reinvented "is this a NYSE
trading day" from scratch (a fresh `pandas_market_calendars` `schedule()` call per invocation)
when `src/core/market_calendar.py`'s `MarketCalendar.is_trading_day()` already provides exactly
this as an O(1) cached singleton lookup, already used by `backfill_feature_factory.py` for the
identical case. Fixed: `_slots_nyse_daily` now calls `get_market_calendar().is_trading_day()`
per date instead of re-deriving a 20-year schedule DataFrame every call (measured ~38ms/call,
~4.9s aggregate across a 129-symbol backfill run) -- this single change also resolved the
simplification angle's two secondary findings (duplicated calendar-cache boilerplate, a dead
`tz=` kwarg carried over from copy-paste) as a side effect. All 26 `test_bar_normalizer.py` tests
pass unchanged, confirming identical output. The altitude angle's finding (generalize `1d`
slot-generation beyond NYSE to futures/fx/crypto) was judged real but out of scope -- no live
data exists yet to test that generalization against -- split to
[342](../pending/342-daily-slot-generation-not-generalized-beyond-nyse.md).

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
