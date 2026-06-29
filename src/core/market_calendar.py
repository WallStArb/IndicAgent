"""
Market Calendar — O(1) per-bar trading hours lookup backed by pandas_market_calendars.

Design: pre-build a per-date session dict at init from mcal.schedule(). Lookup is
date_str -> (market_open_utc, market_close_utc). Non-trading days (weekends, holidays,
half-day periods after early close) are absent from the dict, so a single dict.get()
handles all exclusion cases — no separate holiday set, no weekday check, no hardcoded
session times.

CME note: CME_Equity sessions have overnight opens (open timestamp falls on the prior
UTC calendar day). is_trading_minute uses bar's UTC date as the dict key, which matches
the trading date for NYSE (opens 14:30 UTC). For CME overnight sessions the UTC date of
the bar may differ from the schedule index; callers currently only use exchange='NYSE'.

Sources:
- NYSE: https://www.nyse.com/markets/hours-trading
- CME Globex: https://www.cmegroup.com/markets/trading-hours.html
"""

from datetime import date

import pandas as pd
import pandas_market_calendars as mcal

# Exchange → pandas_market_calendars calendar name
_EXCHANGE_TO_PMC: dict[str, str] = {
    "NYSE": "NYSE",
    "NASDAQ": "NYSE",
    "ARCA": "NYSE",
    "BATS": "NYSE",
    "ICE": "NYSE",
    "CME": "CME_Equity",
    "CBOT": "CME_Equity",
    "COMEX": "CME_Equity",
    "NYMEX": "CME_Equity",
}

# Covers all historical corpus data (1d goes back to 2006) and projected future bars
_PMC_RANGE_START = "2005-01-01"
_PMC_RANGE_END = "2035-12-31"


def _build_daily_sessions(pmc_name: str) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
    """Return per-trading-date session boundaries from pandas_market_calendars.

    Key: ISO trading date (schedule index). Value: (market_open_utc, market_close_utc).
    Non-trading days are absent.
    """
    cal = mcal.get_calendar(pmc_name)
    schedule = cal.schedule(_PMC_RANGE_START, _PMC_RANGE_END)
    return dict(
        zip(
            schedule.index.strftime("%Y-%m-%d"),
            zip(schedule["market_open"], schedule["market_close"]),
        )
    )


class MarketCalendar:
    """
    Immutable market calendar with O(1) per-date session lookup.

    Usage:
        cal = MarketCalendar()
        cal.is_trading_minute('NYSE', pd.Timestamp('2026-06-29 15:00:00', tz='UTC'))
    """

    __slots__ = ("_daily_sessions",)

    def __init__(self) -> None:
        _sessions_by_pmc = {
            "NYSE": _build_daily_sessions("NYSE"),
            "CME_Equity": _build_daily_sessions("CME_Equity"),
        }
        self._daily_sessions: dict[str, dict[str, tuple[pd.Timestamp, pd.Timestamp]]] = {
            exch: _sessions_by_pmc[pmc] for exch, pmc in _EXCHANGE_TO_PMC.items()
        }

    def is_trading_minute(self, exchange: str, timestamp: pd.Timestamp) -> bool:
        """
        Return True if timestamp falls within exchange regular trading hours.

        For intraday bars (1m, 5m, 15m, 1h). Uses UTC timestamp directly.
        Complexity: O(1) - two dict lookups + Timestamp comparison
        """
        sessions = self._daily_sessions.get(exchange)
        if sessions is None:
            return False

        session = sessions.get(timestamp.strftime("%Y-%m-%d"))
        if session is None:
            return False  # weekend, holiday, or out of covered range

        open_utc, close_utc = session
        return open_utc <= timestamp < close_utc

    def is_trading_day(self, exchange: str, date_obj: date) -> bool:
        """
        Return True if date_obj is a trading day for the exchange.

        For daily bars timestamped at midnight UTC, pass bar_ts.date() (the UTC
        date). IBKR midnight-UTC daily bars have UTC date == trading date (e.g.
        2026-06-29 00:00 UTC is the June 29 bar). Do NOT convert to ET first —
        that yields the prior calendar day, which is never the trading date.
        Complexity: O(1) - two dict lookups
        """
        sessions = self._daily_sessions.get(exchange)
        if sessions is None:
            return False
        return date_obj.isoformat() in sessions

    def is_trading_bar(self, exchange: str, bar_ts: pd.Timestamp, tf: str) -> bool:
        """
        Unified validity check for any timeframe bar.

        Encapsulates tf-specific timestamp semantics so callers need not know
        that 1d bars require is_trading_day(bar_ts.date()) while intraday bars
        require is_trading_minute(bar_ts).
        """
        if tf == "1d":
            return self.is_trading_day(exchange, bar_ts.date())
        return self.is_trading_minute(exchange, bar_ts)


# Singleton — immutable, safe to share across workers
_calendar_instance: MarketCalendar | None = None


def get_market_calendar() -> MarketCalendar:
    """Return the singleton MarketCalendar instance."""
    global _calendar_instance
    if _calendar_instance is None:
        _calendar_instance = MarketCalendar()
    return _calendar_instance
