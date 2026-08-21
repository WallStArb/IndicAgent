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

## Closed 2026-08-21

Generalized as scoped, with the test-strategy question the todo itself flagged
("no live `1d` data of any kind to test against") resolved by testing purely
against the calendar/weekday-rule logic, not storage reproduction -- explicit,
documented choice, not an oversight.

**Implementation:**

1. `_daily_slots(start, end, is_trading_date)` -- new shared helper (same
   rationale as `_slots_from_windows` sharing the interval-stepped session
   types): factors the day-iteration/midnight-anchoring/bounds-clipping shape
   that `_slots_nyse_daily` had alone, parameterized by a per-date predicate.
2. `_slots_nyse_daily` refactored onto the shared helper (behavior unchanged,
   confirmed by its own existing tests staying green unmodified).
3. `_slots_futures_daily(exchange, start, end)` -- new. Scoped to exchanges
   `MarketCalendar` already covers (CME/CBOT/COMEX/NYMEX, all mapped to the
   CME_Equity PMC calendar). **CFE (VIX futures) deliberately excluded** --
   `MarketCalendar` has no registered calendar for it, so this raises `ValueError`
   rather than silently returning an empty slot list (which would reproduce
   todo 300's exact silent-100%-missing failure for a new exchange). Added
   `MarketCalendar.supports_exchange()` (new public method) so this guard checks
   the real registry instead of hand-maintaining a duplicate exchange list that
   could drift from `MarketCalendar._EXCHANGE_TO_PMC`.
4. `_slots_fx_daily`/`_slots_crypto_daily` -- new, much lower risk (no calendar
   dependency): FX reuses `_slots_fx`'s existing Mon-Fri weekday rule, crypto is
   always-True (never closes).
5. `generate_session_slots()`'s `1d` dispatch widened from `and session_id ==
   "nyse"` to a full branch covering all four session types.

**Not done, deliberately out of scope:** no direct unit tests for
`MarketCalendar.supports_exchange()` itself -- `MarketCalendar` has no dedicated
test file at all (tested only indirectly through `bar_normalizer.py` today), and
creating one for a single new method is a bigger scope decision than this todo
warranted. The new method is exercised end-to-end (not mocked) by the CFE test
below, plus implicitly by every passing CME/CBOT test (which wouldn't pass if
`supports_exchange` returned the wrong answer for a mapped exchange).

**Tests:** `TestFutures1d`/`TestFx1d`/`TestCrypto1d` added to
`test_bar_normalizer.py`, mirroring `TestNyse1d`'s existing pattern (trading-day
slots, weekend exclusion) plus a CFE-raises test proving the exclusion guard
actually fires. 12 new tests, full `tests/unit/` suite green (60 total in this
file). Ruff/black clean.

**Side effect, same session:** working this todo's `vulture` check surfaced
`assert_known_subset()` (`src/core/vocabulary_access.py`) as newly dead code --
a leftover from todo 329's earlier fix the same day, removed its only callers.
Cleaned up as a tail of that fix, not this one; noted in todo 329's own closing
section, not restated here.
