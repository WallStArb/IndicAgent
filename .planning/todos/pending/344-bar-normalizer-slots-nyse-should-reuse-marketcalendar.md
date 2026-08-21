# 344 - `_slots_nyse` (intraday) still maintains its own NYSE calendar, unlike the new `_slots_nyse_daily`

**Filed:** 2026-08-21
**Source:** `/simplify`'s simplification-angle review of the full session's code diff (todo 300's
follow-up).

## What

Todo 300's fix added `_slots_nyse_daily()` to `src/core/bar_normalizer.py`, which correctly
reuses `MarketCalendar.is_trading_day()` (`src/core/market_calendar.py`'s cached singleton)
instead of re-deriving NYSE trading days from `pandas_market_calendars` directly -- its own
docstring argues this avoids "two independently-derived [NYSE calendar] definitions that could
silently disagree."

But the pre-existing sibling `_slots_nyse()` (intraday path, lines ~162-192) still maintains its
own separate NYSE calendar: a module-level `_NYSE_CAL` global, lazily built via
`mcal.get_calendar("NYSE")`, whose `.schedule()` call independently re-derives trading days AND
hours from `pandas_market_calendars` -- completely apart from `MarketCalendar`'s own
`_build_daily_sessions("NYSE")` that now backs `_slots_nyse_daily`.

**Concrete cost:** the file now documents, in its own new code, the exact risk it argues against
("two independently-derived NYSE definitions") while its neighboring function still embodies
that risk. If `_NYSE_CAL.schedule()` and `MarketCalendar`'s pre-built dict ever diverge (mcal
version behavior change, holiday-calendar edge case), intraday (`_slots_nyse`) and daily
(`_slots_nyse_daily`) slot generation for the same exchange could disagree about which days are
trading days, with nothing forcing them back into sync.

## Why not fixed alongside todo 300

`_slots_nyse` needs more than a yes/no trading-day check -- it also needs the day's market
open/close times (for the intraday window-stepping `_slots_from_windows` consumes) and
`_slots_nyse`'s own half-day-detection logic (`pmc_close_et.hour < 16` check). `MarketCalendar`'s
public API (`is_trading_day`/`is_trading_minute`/`is_trading_bar`) exposes none of that --
migrating `_slots_nyse` to source through `MarketCalendar` would require adding new accessor
methods to `MarketCalendar` itself (e.g. `session_open_close(exchange, date) ->
tuple[datetime, datetime] | None`), a real API-surface expansion to a shared Ring 0 module used
elsewhere, not a same-session drive-by fix.

**Additional finding, same review:** `MarketCalendar`'s pre-built dict only covers
`_PMC_RANGE_START = "2005-01-01"` through `2035-12-31` (`src/core/market_calendar.py:39-40`);
`is_trading_day` returns `False` (not an error) for any date outside that range, so
`_slots_nyse_daily` would silently produce zero expected slots for any `1d` gap-detection call
with a `start` before 2005-01-01, while `_slots_nyse` (unrestricted live `mcal` query) would
correctly compute slots for the same range. **Confirmed NOT a live issue as of 2026-08-21**: the
earliest `1d` row in `market_data_ohlcv` is 2006-03-22 (`AAPL`), safely after the 2005 floor for
every symbol in the corpus today. Worth re-checking if this project's history horizon is ever
extended earlier than 2005, or fixed as part of whatever accessor 344's fix shape below adds.

## Fix shape (not yet decided)

1. Add an accessor to `MarketCalendar` exposing `(market_open, market_close)` for a given
   exchange/date (or expose its internal `_daily_sessions` dict read-only), sourced from the same
   pre-built dict `is_trading_day` already reads.
2. Repoint `_slots_nyse` to use that accessor instead of its own `_NYSE_CAL`/`.schedule()` call,
   preserving the existing half-day-detection logic (just fed from the new accessor's
   `market_close` instead of a fresh `schedule()` row).
3. Remove `_NYSE_CAL`'s module-level cache from `bar_normalizer.py` once `_slots_nyse` no longer
   needs it directly (leaves `_slots_futures`' separate `_FUTURES_CAL_CACHE` untouched --
   `MarketCalendar` only covers NYSE/CME_Equity exchanges, not the full futures exchange set).

## Where

- `src/core/bar_normalizer.py` -- `_slots_nyse`, `_NYSE_CAL`, `_slots_nyse_daily` (the precedent)
- `src/core/market_calendar.py` -- `MarketCalendar`, `_build_daily_sessions` (would need the new
  accessor)
