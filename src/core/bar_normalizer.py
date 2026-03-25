from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone  # noqa: F401
from zoneinfo import ZoneInfo

import pandas_market_calendars as mcal  # noqa: F401

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ET = ZoneInfo("America/New_York")
UTC = UTC

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
    "CME": "CME_Equity",   # ES, NQ, RTY
    "CBOT": "CBOT",        # YM, ZB, ZT, ZN, ZF, ZC, ZS, ZW
    "COMEX": "CME",        # GC, SI, HG  (COMEX is a CME division)
    "NYMEX": "CME",        # CL, NG      (NYMEX is a CME division)
    "CFE": "CBOE",         # VIX futures
}


# ---------------------------------------------------------------------------
# Internal helpers (implemented in later tasks)
# ---------------------------------------------------------------------------

def _generate_session_slots(
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
    """Mon 00:00 UTC through Fri 24:00 UTC (weekday == 0..4)."""
    slots = []
    t = start
    while t <= end:
        if t.weekday() < 5:  # Mon=0 .. Fri=4
            slots.append(t)
        t += interval
    return slots


def _slots_nyse(start: datetime, end: datetime, interval: timedelta) -> list[datetime]:
    """NYSE trading days, 04:00–20:00 ET (pre-market through after-hours).
    Half-days: session ends at early_close time instead of 20:00 ET.
    Holidays: entire day excluded.
    """
    cal = mcal.get_calendar("NYSE")

    start_date = start.astimezone(ET).date()
    end_date = end.astimezone(ET).date()
    # IMPORTANT: tz="America/New_York" is mandatory.
    # Without it, market_close is returned as UTC and the half-day check
    # (pmc_close_et.hour < 16) silently fails.
    schedule = cal.schedule(
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        tz="America/New_York",
    )

    SESSION_OPEN_ET  = {"hour": 4,  "minute": 0}
    SESSION_CLOSE_ET = {"hour": 20, "minute": 0}

    trading_windows: list[tuple[datetime, datetime]] = []
    for _, row in schedule.iterrows():
        day_et = row["market_open"].date()
        day_open = datetime(day_et.year, day_et.month, day_et.day,
                            SESSION_OPEN_ET["hour"], SESSION_OPEN_ET["minute"],
                            tzinfo=ET)
        pmc_close_et = row["market_close"].astimezone(ET)
        full_close_et = datetime(day_et.year, day_et.month, day_et.day,
                                 SESSION_CLOSE_ET["hour"], SESSION_CLOSE_ET["minute"],
                                 tzinfo=ET)
        is_half_day = pmc_close_et.hour < 16
        day_close = pmc_close_et if is_half_day else full_close_et
        trading_windows.append((day_open, day_close))

    slots = []
    t = start
    while t <= end:
        t_et = t.astimezone(ET)
        for win_open, win_close in trading_windows:
            if win_open <= t_et <= win_close:
                slots.append(t)
                break
        t += interval
    return slots


def _slots_futures(
    exchange: str,
    start: datetime,
    end: datetime,
    interval: timedelta,
) -> list[datetime]:
    raise NotImplementedError


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def normalize_bars(
    bars: list[dict],
    symbol: str,
    timeframe: str,
    session_id: str,
    exchange: str,
    start: datetime,
    end: datetime,
) -> list[dict]:
    """Return bars with synthetic flat fills for every open-session slot missing
    from the input.

    Synthetic bars: OHLC = prev_close, volume = 0, source = "synthetic_fill".
    If no prev_close is available at the start of a gap, that gap is skipped —
    prices are never fabricated from nothing.

    Args:
        bars:       Sorted list of OHLCV dicts. Each must have keys:
                    timestamp (datetime, UTC-aware), open, high, low, close,
                    volume, source.
        symbol:     Base symbol (e.g. "ES", "SPY"). Used for logging only.
        timeframe:  "1m" | "5m" | "15m" | "1h" | "4h" | "1d"
        session_id: Instrument session type. Valid values:
                    "futures_24_5", "nyse", "crypto_24_7", "fx_24_5"
        exchange:   IBKR exchange string from Instrument.exchange
                    (e.g. "CME", "CBOT", "SMART", "IDEALPRO", "PAXOS").
                    Required for futures to select the right PMC calendar.
        start:      Range start, UTC-aware.
        end:        Range end, UTC-aware.

    Returns:
        Complete list ordered by timestamp. Real bars preserve source.
        Synthetic bars have source="synthetic_fill".
    """
    raise NotImplementedError
