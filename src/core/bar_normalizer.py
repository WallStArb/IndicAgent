from __future__ import annotations

from datetime import datetime, timedelta, timezone  # noqa: F401
from zoneinfo import ZoneInfo

import pandas_market_calendars as mcal  # noqa: F401

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ET = ZoneInfo("America/New_York")
UTC = timezone.utc

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
    raise NotImplementedError


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
