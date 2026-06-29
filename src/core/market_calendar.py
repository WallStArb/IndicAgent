"""
Market Calendar — Immutable lookup table for exchange trading hours.

Renaissance Principles:
- Data integrity is paramount
- Single source of truth for trading hours
- Pre-computed, not runtime-calculated
- Auditable back to exchange specifications
- DST-aware via timezone conversion

Source Documentation:
- NYSE: https://www.nyse.com/markets/hours-trading
- CME Globex: https://www.cmegroup.com/markets/trading-hours.html
- NASDAQ: https://www.nasdaq.com/trading/trading-hours
"""

from datetime import date
from zoneinfo import ZoneInfo

import pandas as pd

# =============================================================================
# IMMUTABLE LOOKUP TABLES
# =============================================================================
# These are pre-computed from exchange specifications.
# To add an exchange: add row to _TRADING_SESSIONS + update _EXCHANGE_TIMEZONES
# To add holidays: add row to _HOLIDAYS (with source reference)

_TRADING_SESSIONS = pd.DataFrame(
    {
        "exchange": [
            "NYSE",  # New York Stock Exchange
            "NASDAQ",  # NASDAQ (same hours as NYSE)
            "ARCA",  # NYSE Arca (ETFs)
            "BATS",  # CBOE BATS (equities/ETFs)
            "CME",  # CME Group (futures)
            "CBOT",  # CBOT (futures)
            "COMEX",  # COMEX (metals futures)
            "NYMEX",  # NYMEX (energy futures)
            "ICE",  # Intercontinental Exchange
        ],
        "phase": [
            "regular",
            "regular",
            "regular",
            "regular",  # Equities: regular session only
            "regular",
            "regular",
            "regular",
            "regular",
            "regular",  # Futures: regular session
        ],
        "day_of_week": [
            "Mon-Fri",
            "Mon-Fri",
            "Mon-Fri",
            "Mon-Fri",  # Equities: Monday-Friday
            "Mon-Fri",
            "Mon-Fri",
            "Mon-Fri",
            "Mon-Fri",
            "Mon-Fri",  # Futures: Monday-Friday
        ],
        "open_time": [
            "09:30",
            "09:30",
            "09:30",
            "09:30",  # Equities: 9:30 AM ET
            "09:00",
            "09:00",
            "09:00",
            "09:00",
            "20:00",  # Futures varies
        ],
        "close_time": [
            "16:00",
            "16:00",
            "16:00",
            "16:00",  # Equities: 4:00 PM ET
            "17:00",
            "17:00",
            "17:00",
            "17:00",
            "16:00",  # Futures varies
        ],
        "timezone": [
            "America/New_York",
            "America/New_York",
            "America/New_York",
            "America/New_York",
            "America/Chicago",
            "America/Chicago",
            "America/Chicago",
            "America/Chicago",
            "America/New_York",
        ],
    }
)

# Exchange timezone mapping (for quick lookup)
_EXCHANGE_TIMEZONES = {
    "NYSE": ZoneInfo("America/New_York"),
    "NASDAQ": ZoneInfo("America/New_York"),
    "ARCA": ZoneInfo("America/New_York"),
    "BATS": ZoneInfo("America/New_York"),
    "CME": ZoneInfo("America/Chicago"),
    "CBOT": ZoneInfo("America/Chicago"),
    "COMEX": ZoneInfo("America/Chicago"),
    "NYMEX": ZoneInfo("America/Chicago"),
    "ICE": ZoneInfo("America/New_York"),
}

# NYSE holidays (source: https://www.nyse.com/markets/holidays-trading)
# Format: YYYY-MM-DD
_NYSE_HOLIDAYS = {
    # 2024
    "2024-01-01",  # New Year's Day
    "2024-01-15",  # Martin Luther King Jr. Day
    "2024-02-19",  # Presidents' Day
    "2024-03-29",  # Good Friday
    "2024-05-27",  # Memorial Day
    "2024-06-19",  # Juneteenth
    "2024-07-04",  # Independence Day
    "2024-09-02",  # Labor Day
    "2024-11-28",  # Thanksgiving Day
    "2024-12-25",  # Christmas Day
    # 2025 (projected, verify when dates released)
    "2025-01-01",  # New Year's Day
    "2025-01-20",  # Martin Luther King Jr. Day
    "2025-02-17",  # Presidents' Day
    "2025-04-18",  # Good Friday
    "2025-05-26",  # Memorial Day
    "2025-06-19",  # Juneteenth
    "2025-07-04",  # Independence Day
    "2025-09-01",  # Labor Day
    "2025-11-27",  # Thanksgiving Day
    "2025-12-25",  # Christmas Day
}

# CME holidays (source: https://www.cmegroup.com/trading-hours/holidays)
# Note: CME has different holidays than NYSE
_CME_HOLIDAYS = {
    # 2024
    "2024-01-01",  # New Year's Day
    "2024-01-15",  # Martin Luther King Jr. Day
    "2024-02-19",  # Presidents' Day
    "2024-05-27",  # Memorial Day
    "2024-06-19",  # Juneteenth
    "2024-07-04",  # Independence Day
    "2024-09-02",  # Labor Day
    "2024-11-28",  # Thanksgiving Day
    "2024-12-25",  # Christmas Day
    # 2025 (projected)
    "2025-01-01",  # New Year's Day
    "2025-01-20",  # Martin Luther King Jr. Day
    "2025-02-17",  # Presidents' Day
    "2025-05-26",  # Memorial Day
    "2025-06-19",  # Juneteenth
    "2025-07-04",  # Independence Day
    "2025-09-01",  # Labor Day
    "2025-11-27",  # Thanksgiving Day
    "2025-12-25",  # Christmas Day
}

# Holiday lookup by exchange
_EXCHANGE_HOLIDAYS = {
    "NYSE": _NYSE_HOLIDAYS,
    "NASDAQ": _NYSE_HOLIDAYS,
    "ARCA": _NYSE_HOLIDAYS,
    "BATS": _NYSE_HOLIDAYS,
    "CME": _CME_HOLIDAYS,
    "CBOT": _CME_HOLIDAYS,
    "COMEX": _CME_HOLIDAYS,
    "NYMEX": _CME_HOLIDAYS,
    "ICE": _NYSE_HOLIDAYS,  # ICE US follows NYSE holidays
}


class MarketCalendar:
    """
    Immutable market calendar lookup.

    O(1) lookup for: is this timestamp within regular trading hours?

    Usage:
        calendar = MarketCalendar()
        is_trading = calendar.is_trading_minute('NYSE', pd.Timestamp('2024-06-28 10:30:00', tz='UTC'))
    """

    __slots__ = ("_sessions", "_exchange_timezones", "_exchange_holidays")

    def __init__(self) -> None:
        self._sessions = _TRADING_SESSIONS
        self._exchange_timezones = _EXCHANGE_TIMEZONES
        self._exchange_holidays = _EXCHANGE_HOLIDAYS

    def is_trading_minute(
        self,
        exchange: str,
        timestamp: pd.Timestamp,
        phase: str = "regular",
    ) -> bool:
        """
        Return True if timestamp is within exchange trading hours.

        Args:
            exchange: Exchange code (NYSE, NASDAQ, CME, etc.)
            timestamp: Timestamp to check (should be timezone-aware)
            phase: Trading phase ('regular', 'pre-market', 'post-market')

        Returns:
            True if timestamp is within trading hours, False otherwise

        Complexity: O(1) - simple lookup and comparison
        """
        if exchange not in self._exchange_timezones:
            # Unknown exchange — conservative: assume not trading
            return False

        # Check holiday
        date_str = timestamp.date().isoformat()
        if date_str in self._exchange_holidays.get(exchange, set()):
            return False

        # Check weekday (Mon=0, Fri=4)
        weekday = timestamp.weekday()
        if weekday >= 5:  # Saturday (5) or Sunday (6)
            return False

        # Get session parameters
        tz = self._exchange_timezones[exchange]

        mask = (self._sessions["exchange"] == exchange) & (self._sessions["phase"] == phase)
        sessions = self._sessions[mask]

        if sessions.empty:
            return False

        session = sessions.iloc[0]

        # Parse session times
        open_local = pd.to_datetime(session["open_time"], format="%H:%M").time()
        close_local = pd.to_datetime(session["close_time"], format="%H:%M").time()

        # Convert timestamp to exchange local time
        ts_local = timestamp.tz_convert(tz)
        ts_time = ts_local.time()

        # Check if within session [open, close)
        return open_local <= ts_time < close_local

    def get_session_boundaries(
        self,
        exchange: str,
        date_obj: date,
        phase: str = "regular",
    ) -> tuple[pd.Timestamp, pd.Timestamp] | None:
        """
        Return the open and close timestamps for a trading session.

        Args:
            exchange: Exchange code
            date_obj: Date to query
            phase: Trading phase

        Returns:
            (open_timestamp, close_timestamp) in UTC, or None if no session
        """
        if exchange not in self._exchange_timezones:
            return None

        # Check holiday
        date_str = date_obj.isoformat()
        if date_str in self._exchange_holidays.get(exchange, set()):
            return None

        # Check weekday
        if date_obj.weekday() >= 5:
            return None

        tz = self._exchange_timezones[exchange]
        mask = (self._sessions["exchange"] == exchange) & (self._sessions["phase"] == phase)
        sessions = self._sessions[mask]

        if sessions.empty:
            return None

        session = sessions.iloc[0]
        open_local = pd.to_datetime(session["open_time"], format="%H:%M").time()
        close_local = pd.to_datetime(session["close_time"], format="%H:%M").time()

        # Construct timestamps in local timezone, then convert to UTC
        open_ts = pd.Timestamp(
            date_obj.year,
            date_obj.month,
            date_obj.day,
            open_local.hour,
            open_local.minute,
            tzinfo=tz,
        )
        close_ts = pd.Timestamp(
            date_obj.year,
            date_obj.month,
            date_obj.day,
            close_local.hour,
            close_local.minute,
            tzinfo=tz,
        )

        return open_ts.tz_convert("UTC"), close_ts.tz_convert("UTC")

    def is_regular_equity_session(self, exchange: str, timestamp: pd.Timestamp) -> bool:
        """
        Convenience method for equities (NYSE/NASDAQ/ARCA/BATS) regular session.

        This is the primary method used by FeatureFactory for ETF filtering.
        """
        return self.is_trading_minute(exchange, timestamp, phase="regular")


# Singleton instance (immutable, safe to share)
_calendar_instance: MarketCalendar | None = None


def get_market_calendar() -> MarketCalendar:
    """Return the singleton MarketCalendar instance."""
    global _calendar_instance
    if _calendar_instance is None:
        _calendar_instance = MarketCalendar()
    return _calendar_instance
