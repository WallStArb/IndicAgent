"""
Core data models for the Multi-Timeframe Trading Signal Platform.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from datetime import date as _date
from datetime import datetime as _datetime
from enum import StrEnum
from functools import cache
from zoneinfo import ZoneInfo

from pydantic import BaseModel, field_validator


class AssetClass(StrEnum):
    """Asset class classification."""

    FUTURES = "futures"
    EQUITY = "equity"
    CRYPTO = "crypto"
    FX = "fx"
    OPTION = "option"


_ALL_ASSET_CLASSES: frozenset["AssetClass"] = frozenset(AssetClass)


@dataclass(frozen=True)
class TradingSession:
    """Defines when a market is open, including trading breaks and trading days."""

    open_time: time
    close_time: time
    timezone: str
    trading_days: frozenset[int] = frozenset({0, 1, 2, 3, 4})
    trading_breaks: tuple[tuple[time, time], ...] = ()

    def is_open(self, utc_ts: _datetime) -> bool:
        """True if market is open at utc_ts (trading_breaks do NOT close the session)."""
        local = utc_ts.astimezone(ZoneInfo(self.timezone))
        if local.weekday() not in self.trading_days:
            return False
        t = local.time().replace(second=0, microsecond=0)
        if self.open_time == self.close_time:
            return True
        elif self.open_time < self.close_time:
            return self.open_time <= t < self.close_time
        else:
            return t >= self.open_time or t < self.close_time

    def in_trading_break(self, utc_ts: _datetime) -> bool:
        """True if currently in a scheduled intra-session break."""
        if not self.trading_breaks:
            return False
        local = utc_ts.astimezone(ZoneInfo(self.timezone))
        t = local.time().replace(second=0, microsecond=0)
        return any(start <= t < end for start, end in self.trading_breaks)

    def elapsed_fraction(self, utc_ts: _datetime) -> float | None:
        """Fraction of trading day elapsed (0.0→1.0, breaks excluded from denominator).

        Returns None for all-day sessions or when closed.
        """
        if self.open_time == self.close_time:
            return None
        if not self.is_open(utc_ts):
            return None
        local = utc_ts.astimezone(ZoneInfo(self.timezone))
        t = local.time().replace(second=0, microsecond=0)
        anchor = _date(2000, 1, 2)  # Monday anchor for safe time arithmetic
        t_dt = _datetime.combine(anchor, t)
        op_dt = _datetime.combine(anchor, self.open_time)
        cl_dt = _datetime.combine(anchor, self.close_time)
        if self.open_time > self.close_time:  # midnight wrap
            next_day = _date(2000, 1, 3)
            cl_dt = _datetime.combine(next_day, self.close_time)
            if t < self.open_time:
                t_dt = _datetime.combine(next_day, t)
        session_total = (cl_dt - op_dt).total_seconds()
        elapsed = (t_dt - op_dt).total_seconds()
        for brk_start, brk_end in self.trading_breaks:
            bs_dt = _datetime.combine(anchor, brk_start)
            be_dt = _datetime.combine(anchor, brk_end)
            bs_dt = max(bs_dt, op_dt)
            be_dt = min(be_dt, cl_dt)
            if be_dt > bs_dt:
                session_total -= (be_dt - bs_dt).total_seconds()
            if be_dt <= t_dt:
                elapsed -= max(0.0, (be_dt - bs_dt).total_seconds())
            elif bs_dt < t_dt:
                elapsed -= (t_dt - bs_dt).total_seconds()
        if session_total <= 0:
            return None
        return max(0.0, min(1.0, elapsed / session_total))

    def session_window_for_date(
        self, target_date: _date
    ) -> tuple[_datetime | None, _datetime | None]:
        """Return the UTC (start, end) window for target_date's trading session.

        Returns (None, None) for non-trading days.

        All-day sessions (open_time == close_time): returns midnight-to-midnight UTC.
        Same-day sessions (open_time < close_time): converts local open/close to UTC.
        Overnight sessions (open_time > close_time): session starts previous calendar
          day in local time; start = prev_day open_time in UTC, end = target_date
          close_time in UTC.

        Used by BarAuditor to compute expected bar count for completeness checks.
        """
        if target_date.weekday() not in self.trading_days:
            return (None, None)

        # All-day session (open == close, e.g. crypto, fx_24_5)
        if self.open_time == self.close_time:
            start_utc = _datetime(target_date.year, target_date.month, target_date.day, tzinfo=UTC)
            end_utc = start_utc + timedelta(days=1)
            return (start_utc, end_utc)

        tz = ZoneInfo(self.timezone)

        # Same-day session (open < close, e.g. nyse, tse)
        if self.open_time < self.close_time:
            start_local = _datetime.combine(target_date, self.open_time, tzinfo=tz)
            end_local = _datetime.combine(target_date, self.close_time, tzinfo=tz)
            return (start_local.astimezone(UTC), end_local.astimezone(UTC))

        # Overnight session (open > close, e.g. futures_24_5)
        # Session opens on the previous calendar day in local time.
        # prev_day intentionally may not be in trading_days (e.g. CME Sunday opens Saturday 18:00 CST).
        prev_day = target_date - timedelta(days=1)
        start_local = _datetime.combine(prev_day, self.open_time, tzinfo=tz)
        end_local = _datetime.combine(target_date, self.close_time, tzinfo=tz)
        return (start_local.astimezone(UTC), end_local.astimezone(UTC))

    def _break_minutes(self) -> int:
        """Total minutes consumed by intra-session trading breaks."""
        total = 0
        anchor = _date(2000, 1, 2)  # arbitrary date for time arithmetic
        for brk_start, brk_end in self.trading_breaks:
            total += int(
                (
                    _datetime.combine(anchor, brk_end) - _datetime.combine(anchor, brk_start)
                ).total_seconds()
                / 60
            )
        return total

    def expected_bars_for_date(self, target_date: _date) -> int:
        """Expected 1m bar count for target_date's trading session.

        Derives the count from session_window_for_date() minus break minutes.
        Returns 0 for non-trading days.

        Used by BarAuditor for completeness checks.
        """
        window = self.session_window_for_date(target_date)
        if window[0] is None or window[1] is None:
            return 0
        total_minutes = int((window[1] - window[0]).total_seconds() / 60)
        return max(0, total_minutes - self._break_minutes())

    @cache  # noqa: B019 — frozen dataclass, finite module-level instances
    def max_achievable_pct(self) -> float:
        """Structurally achievable bar completeness from session geometry.

        Returns the ratio of active trading minutes to total session window minutes.
        Sessions with no breaks return 1.0. Sessions with encoded breaks return < 1.0.

        Used by BarAuditor to set a realistic completeness ceiling rather than
        flagging break periods as missing bars.
        """
        if self.open_time == self.close_time:
            return 1.0

        # Use a reference week (2026-03-02 = Monday) + weekday offset
        reference_monday = _date(2026, 3, 2)
        test_date: _date | None = None
        for wd in range(7):
            if wd in self.trading_days:
                test_date = reference_monday + timedelta(days=wd)
                break

        if test_date is None:
            return 1.0

        window = self.session_window_for_date(test_date)
        if window[0] is None or window[1] is None:
            return 1.0

        total_window_minutes = (window[1] - window[0]).total_seconds() / 60
        if total_window_minutes <= 0:
            return 1.0

        active_minutes = total_window_minutes - self._break_minutes()
        if active_minutes <= 0:
            return 1.0

        return active_minutes / total_window_minutes


EXCHANGE_SESSIONS: dict[str, "TradingSession"] = {
    "nyse": TradingSession(time(9, 30), time(16, 0), "America/New_York"),
    "lse": TradingSession(time(8, 0), time(16, 30), "Europe/London"),
    "tse": TradingSession(
        time(9, 0),
        time(15, 30),
        "Asia/Tokyo",
        trading_breaks=((time(11, 30), time(12, 30)),),
    ),
    "hkex": TradingSession(
        time(9, 30),
        time(16, 0),
        "Asia/Hong_Kong",
        trading_breaks=((time(12, 0), time(13, 0)),),
    ),
    "sse": TradingSession(
        time(9, 30),
        time(15, 0),
        "Asia/Shanghai",
        trading_breaks=((time(11, 30), time(13, 0)),),
    ),
    "asx": TradingSession(time(10, 0), time(16, 0), "Australia/Sydney"),
}

CONTINUOUS_SESSIONS: dict[str, "TradingSession"] = {
    "futures_24_5": TradingSession(
        time(18, 0),
        time(17, 0),
        "Etc/GMT+6",  # Fixed UTC-6 (CST); CME quotes hours in CST year-round
        trading_days=frozenset({0, 1, 2, 3, 4, 6}),
    ),
    "fx_24_5": TradingSession(
        time(0, 0),
        time(0, 0),
        "UTC",
        trading_days=frozenset({0, 1, 2, 3, 4, 6}),
    ),
    "crypto_24_7": TradingSession(
        time(0, 0),
        time(0, 0),
        "UTC",
        trading_days=frozenset(range(7)),
    ),
}

SESSION_REGISTRY: dict[str, "TradingSession"] = {
    **EXCHANGE_SESSIONS,
    **CONTINUOUS_SESSIONS,
}

MARKET_OVERLAPS: dict[str, tuple[str, str]] = {
    "tokyo_london": ("tse", "lse"),
    "london_ny": ("lse", "nyse"),
    "ny_sydney": ("nyse", "asx"),
}


class Instrument(BaseModel):
    """Generic tradable instrument — provider-agnostic."""

    symbol: str
    name: str = ""
    asset_class: AssetClass = AssetClass.FUTURES
    exchange: str = ""
    sector: str = ""
    tick_size: float = 0
    # Futures-specific — empty/zero for equities and crypto
    base: str = ""
    expiry: str = ""
    point_value: float = 0
    # Escape hatch for provider-specific metadata
    provider_meta: dict = {}
    session_id: str = "futures_24_5"

    @field_validator("session_id")
    @classmethod
    def _validate_session_id(cls, v: str) -> str:
        if v not in SESSION_REGISTRY:
            raise ValueError(f"Unknown session_id {v!r}. Known: {list(SESSION_REGISTRY)}")
        return v

    @property
    def trading_session(self) -> TradingSession:
        return SESSION_REGISTRY[self.session_id]


class Timeframe(StrEnum):
    """Available timeframes."""

    ONE_MINUTE = "1m"
    FIVE_MINUTE = "5m"
    FIFTEEN_MINUTE = "15m"
    THIRTY_MINUTE = "30m"
    ONE_HOUR = "1h"
    FOUR_HOUR = "4h"
    ONE_DAY = "1d"
    ONE_WEEK = "1w"


@dataclass(frozen=True)
class ContractMetadata:
    """Futures contract roll tracking metadata.

    Stores per-contract information for roll chain navigation and
    lifetime filtering. Enables Renaissance-style per-contract data storage
    where continuous series are derived, not baked in.

    Example:
            symbol="ESH6", base_symbol="ES", asset_class=AssetClass.FUTURES,
            expiry_date=datetime(2026, 3, 19, tzinfo=ZoneInfo("America/Chicago")),
            roll_from="ESZ5", roll_to="ESM6",
            roll_date=datetime(2025, 12, 15, tzinfo=ZoneInfo("America/Chicago")),
            roll_gap=-12.5, exchange="CME"
    """

    symbol: str
    base_symbol: str
    asset_class: AssetClass
    expiry_date: datetime | None
    first_notice_date: datetime | None
    roll_from: str | None
    roll_to: str | None
    roll_date: datetime | None
    roll_gap: float | None
    exchange: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
