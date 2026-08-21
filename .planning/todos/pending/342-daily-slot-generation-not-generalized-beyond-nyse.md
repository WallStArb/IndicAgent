# 342 - `1d` slot generation only fixed for NYSE; futures/fx/crypto share the same latent bug

**Filed:** 2026-08-21
**Source:** `/simplify`'s altitude-angle review of todo 300's fix
(`src/core/bar_normalizer.py`'s `_slots_nyse_daily()`).

## What

Todo 300 fixed `generate_session_slots()`'s `1d` gap-detection bug for `session_id == "nyse"`
only -- `1d` bars for futures/fx/crypto instruments still fall through to the generic
interval-stepped path (`_TF_MINUTES`-driven, session-open-anchored), which has the same
structural defect this todo's sibling fixed: a `1d` bar is one midnight-anchored row per
trading/calendar day for every session type, not an interval-stepped intraday grid, and nothing
in `_slots_always_open`/`_slots_fx`/`_slots_futures` accounts for that.

**Confirmed live 2026-08-21, before deciding to scope todo 300 to NYSE only:** zero
futures/fx `1d` rows exist in `market_data_ohlcv` today, so this is currently dormant, not an
active data-integrity bug. But nothing prevents it from being triggered -- `src/providers/ibkr.py`
already treats `1d` as a fully generic timeframe for every asset class
(`_MAX_CHUNK_DAYS["1d"] = 7300`, no asset-class restriction), and
`infrastructure_run_historical_pipeline.py`'s `--timeframes` CLI arg takes `1d` freely for any
instrument. The moment a `1d` backfill is ever run against a futures or FX instrument, gap
detection will silently report 100% missing again -- reproducing todo 300 verbatim for a new
session type, the exact same "silent wrong answer" class this project's principles single out.

## Why not fixed alongside todo 300

Generalizing now would mean writing daily-slot logic for CME_Equity/CBOT_Equity/CFE calendars
(via `_slots_futures`'s existing per-exchange `mcal` mechanism) and for `fx_24_5`/`crypto_24_7`
(weekday-rule/always-open, no calendar), with **no live `1d` data of any kind to test the result
against** -- a real correctness risk to accept without evidence, not a mechanical extension.
Todo 300 itself was scoped, tested, and verified against real reproduction data
(`market_data_ohlcv`'s actual stored NYSE `1d` timestamps); this generalization has no
equivalent ground truth to verify against yet.

## Fix shape (not yet decided)

Generalize the dispatch in `generate_session_slots()` to branch on `timeframe == "1d"` as its
own top-level case (not `and session_id == "nyse"`), parameterized by whichever calendar/rule
each session already uses to build its intraday windows:
- `nyse`/`futures_24_5`: one midnight-UTC slot per `mcal` schedule row (todo 300's
  `_slots_nyse_daily` already does this for NYSE; `_slots_futures`'s existing
  `_FUTURES_EXCHANGE_TO_PMC` per-exchange calendar selection generalizes the same pattern).
- `fx_24_5`/`crypto_24_7`: one slot per calendar day matching the existing weekday-rule/
  always-open predicate, collapsed from `_TF_MINUTES`-interval-stepping to one-per-day.

Real test coverage requires either live `1d` futures/fx data to reproduce against, or an
explicit design decision to test purely against the calendar/rule logic itself (no storage
reproduction available) -- worth deciding which before implementing.

## Where

- `src/core/bar_normalizer.py` -- `generate_session_slots()` (the dispatch), `_slots_nyse_daily`
  (the NYSE-only precedent to generalize from), `_slots_futures`/`_slots_fx`/`_slots_always_open`
  (the session types still on the buggy interval-stepped path for `1d`)
- Sibling fix: `completed/300-detect-gaps-1d-slot-timestamp-misaligned-with-storage.md`
