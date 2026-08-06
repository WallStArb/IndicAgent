from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas_market_calendars as mcal

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ET = ZoneInfo("America/New_York")

# Bar provenance — stored in market_data_ohlcv.source for every bar written.
# Always use these constants; never write raw string literals.
SOURCE_IBKR_NAMED = "ibkr_named"  # Named-contract direct IBKR fetch
SOURCE_IBKR_CONTINUOUS = "ibkr_continuous_adj"  # Continuous back-adjusted IBKR fetch
SOURCE_IBKR_OFFICIAL = "ibkr_official"  # Official 1m bars from TWS reconciliation
SOURCE_IBKR_GENERIC = "ibkr"  # Generic IBKR fetch (RTB / fallback)
SOURCE_IBKR_SEED = "ibkr_seed"  # Historical seed bar from DB backfill (BarMessage bus)
SOURCE_HTF_DERIVED = "htf_derived"  # Aggregated from 1m bars by BarAccumulator (BarMessage bus)
SOURCE_DERIVED_1M = "derived_1m"  # Aggregated from 1m bars in DB (market_data_ohlcv)
SOURCE_SYNTHETIC_FILL = "synthetic_fill"  # Flat fill for canonical grid gaps
SOURCE_UNKNOWN = "unknown"  # Source missing from payload (provider-agnostic fallback)

# Minutes per timeframe
_TF_MINUTES: dict[str, int] = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
}

# IBKR exchange string → pandas_market_calendars calendar name
# Only used for futures (session_id="futures_24_5") where exchange disambiguates.
# Equities always use "SMART" exchange — handled by session_id="nyse" branch.
_FUTURES_EXCHANGE_TO_PMC: dict[str, str] = {
    "CME": "CME_Equity",  # ES, NQ, RTY
    "CBOT": "CBOT_Equity",  # YM, ZB, ZT, ZN, ZF, ZC, ZS, ZW
    "COMEX": "CME_Equity",  # GC, SI, HG  (COMEX is a CME division)
    "NYMEX": "CME_Equity",  # CL, NG      (NYMEX is a CME division)
    "CFE": "CFE",  # VIX futures
}

# Module-level calendar cache — PMC calendar instantiation is expensive.
# Cached once per calendar name, reused across all calls in the same process.
_NYSE_CAL: mcal.MarketCalendar | None = None
_FUTURES_CAL_CACHE: dict[str, mcal.MarketCalendar] = {}

# NYSE session window in ET (pre-market through after-hours)
_NYSE_SESSION_OPEN_HOUR = 4
_NYSE_SESSION_CLOSE_HOUR = 20


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def generate_session_slots(
    session_id: str,
    exchange: str,
    timeframe: str,
    start: datetime,
    end: datetime,
) -> list[datetime]:
    """Return every expected bar timestamp within [start, end] for this session."""
    interval = timedelta(minutes=_TF_MINUTES[timeframe])

    if session_id == "crypto_24_7":
        return _slots_always_open(start, end, interval)

    if session_id == "fx_24_5":
        return _slots_fx(start, end, interval)

    if session_id == "nyse":
        return _slots_nyse(start, end, interval)

    if session_id == "futures_24_5":
        return _slots_futures(exchange, start, end, interval)

    raise ValueError(f"Unknown session_id: {session_id!r}")


def _slots_always_open(start: datetime, end: datetime, interval: timedelta) -> list[datetime]:
    slots = []
    t = start
    while t <= end:
        slots.append(t)
        t += interval
    return slots


def _slots_fx(start: datetime, end: datetime, interval: timedelta) -> list[datetime]:
    """Mon 00:00 UTC through Fri 24:00 UTC (weekday == 0..4).

    Intentional simplification: actual FX opens Sun ~22:00 UTC and closes Fri ~22:00 UTC,
    but we use a day-of-week rule (no PMC calendar for FX). This slightly under-fills
    Sun evening and slightly over-fills Fri evening — acceptable for backfill normalization.
    """
    slots = []
    t = start
    while t <= end:
        if t.weekday() < 5:  # Mon=0 .. Fri=4
            slots.append(t)
        t += interval
    return slots


def _slots_from_windows(
    windows: list[tuple[datetime, datetime]],
    start: datetime,
    end: datetime,
    interval: timedelta,
) -> list[datetime]:
    """Emit interval-stepped slots within each (open, close) window, clipped to [start, end].

    Shared by every schedule-based session type (_slots_nyse, _slots_futures) so the O(n)
    generate-within-window property is a structural invariant rather than a convention
    trusted to survive independent copies. Replaces a prior per-function approach that scanned
    every interval-spaced timestamp across the full [start, end] range against every window --
    O(total_slots x windows), ~10 billion comparisons for a single 5m/20yr NYSE symbol, which
    made multi-year backfills across a large symbol universe computationally infeasible (found
    live-stuck during todo 259's 129-symbol client-id 43 launch, 2026-08-06).

    Converts each window's start to out_tz once, then steps both the comparison clock (in the
    window's own tz) and the output clock (in out_tz) by the same interval in parallel --
    avoids one astimezone() call per emitted slot. Relies on out_tz being a fixed-offset zone
    (UTC, per this codebase's all-timestamps-UTC invariant) so wall-clock stepping equals
    absolute-time stepping with no DST drift.
    """
    out_tz = start.tzinfo
    slots: list[datetime] = []
    for win_open, win_close in windows:
        t = max(win_open, start)
        window_end = min(win_close, end)
        t_out = t.astimezone(out_tz)
        while t <= window_end:
            slots.append(t_out)
            t += interval
            t_out += interval
    return slots


def _slots_nyse(start: datetime, end: datetime, interval: timedelta) -> list[datetime]:
    """NYSE trading days, 04:00–20:00 ET (pre-market through after-hours).
    Half-days: session ends at early_close time instead of 20:00 ET.
    Holidays: entire day excluded.
    """
    global _NYSE_CAL
    if _NYSE_CAL is None:
        _NYSE_CAL = mcal.get_calendar("NYSE")

    start_date = start.astimezone(ET).date()
    end_date = end.astimezone(ET).date()
    # IMPORTANT: tz="America/New_York" is mandatory.
    # Without it, market_close is returned as UTC and the half-day check
    # (pmc_close_et.hour < 16) silently fails.
    schedule = _NYSE_CAL.schedule(
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        tz="America/New_York",
    )

    trading_windows: list[tuple[datetime, datetime]] = []
    for _, row in schedule.iterrows():
        day_et = row["market_open"].date()
        day_open = datetime(
            day_et.year, day_et.month, day_et.day, _NYSE_SESSION_OPEN_HOUR, 0, tzinfo=ET
        )
        pmc_close_et = row["market_close"].astimezone(ET)
        full_close_et = datetime(
            day_et.year, day_et.month, day_et.day, _NYSE_SESSION_CLOSE_HOUR, 0, tzinfo=ET
        )
        # PMC market_close < 16:00 ET means it's a half-day — honour early close
        day_close = pmc_close_et if pmc_close_et.hour < 16 else full_close_et
        trading_windows.append((day_open, day_close))

    return _slots_from_windows(trading_windows, start, end, interval)


def _slots_futures(
    exchange: str,
    start: datetime,
    end: datetime,
    interval: timedelta,
) -> list[datetime]:
    """CME/CBOT/COMEX/NYMEX/CFE Globex sessions via pandas_market_calendars.

    PMC encodes Globex hours including the Sunday maintenance window.
    Returns empty list if PMC has no schedule for the date range.
    """
    pmc_name = _FUTURES_EXCHANGE_TO_PMC[exchange]  # KeyError on unknown exchange

    if pmc_name not in _FUTURES_CAL_CACHE:
        _FUTURES_CAL_CACHE[pmc_name] = mcal.get_calendar(pmc_name)
    cal = _FUTURES_CAL_CACHE[pmc_name]

    start_date = start.astimezone(UTC).date()
    end_date = end.astimezone(UTC).date()

    try:
        schedule = cal.schedule(
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
        )
    except ValueError:
        return []

    if schedule.empty:
        return []

    windows: list[tuple[datetime, datetime]] = []
    for _, row in schedule.iterrows():
        win_open = row["market_open"].to_pydatetime().astimezone(UTC)
        win_close = row["market_close"].to_pydatetime().astimezone(UTC)
        windows.append((win_open, win_close))

    return _slots_from_windows(windows, start, end, interval)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def normalize_bars(
    bars: list[dict],
    symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    session_id: str = "",
    exchange: str = "",
) -> list[dict]:
    """Return bars with synthetic flat fills for every interval slot in [start, end].

    Canonical grid: every interval boundary gets a bar — real or synthetic.
    Synthetic bars: OHLC = prev_close, volume = 0, source = "synthetic_fill".
    If no prev_close is available at the start of a gap, that slot is skipped —
    prices are never fabricated from nothing.

    Args:
        bars:      Sorted list of OHLCV dicts. Each must have keys:
                   timestamp (datetime, UTC-aware), open, high, low, close,
                   volume, source.
        symbol:    Base symbol. Used for logging only.
        timeframe: "1m" | "5m" | "15m" | "1h" | "4h" | "1d"
        start:     Range start, UTC-aware.
        end:       Range end, UTC-aware.
        session_id, exchange: Unused — kept for call-site compatibility.

    Returns:
        Complete list ordered by timestamp. Real bars preserve source.
        Synthetic bars have source="synthetic_fill".
    """
    interval = timedelta(minutes=_TF_MINUTES[timeframe])

    # Build index of incoming bars
    bar_index: dict[datetime, dict] = {}
    for b in bars:
        t = b["timestamp"]
        if t.tzinfo is None:
            t = t.replace(tzinfo=UTC)
        bar_index[t.replace(microsecond=0)] = b

    result: list[dict] = []
    prev_close: float | None = None
    slot = start.replace(microsecond=0)

    while slot <= end:
        if slot in bar_index:
            bar = bar_index[slot]
            result.append(bar)
            prev_close = float(bar["close"])
        else:
            if prev_close is not None:
                result.append(
                    {
                        "timestamp": slot,
                        "open": prev_close,
                        "high": prev_close,
                        "low": prev_close,
                        "close": prev_close,
                        "volume": 0,
                        "source": SOURCE_SYNTHETIC_FILL,
                    }
                )
        slot += interval

    return result
