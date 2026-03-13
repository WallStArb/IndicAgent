# tests/unit/core/test_trading_session.py
from datetime import datetime, time, timezone
import pytest
from zoneinfo import ZoneInfo

UTC = timezone.utc


# --- Helpers ---

def utc(y, mo, d, h, mi) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=UTC)


# --- is_open: NYSE (09:30-16:00 ET, Mon-Fri) ---

class TestNYSEIsOpen:
    """NYSE: open 09:30-16:00 ET, Mon-Fri, no breaks."""

    def setup_method(self):
        from src.core.models import EXCHANGE_SESSIONS
        self.session = EXCHANGE_SESSIONS["nyse"]

    def test_open_at_930_et(self):
        # 2026-03-10 is Tuesday; 09:30 ET = 14:30 UTC (EST, UTC-5)
        assert self.session.is_open(utc(2026, 3, 10, 14, 30)) is True

    def test_closed_before_930_et(self):
        assert self.session.is_open(utc(2026, 3, 10, 14, 29)) is False

    def test_closed_at_1600_et(self):
        # 16:00 ET = 21:00 UTC
        assert self.session.is_open(utc(2026, 3, 10, 21, 0)) is False

    def test_closed_on_saturday(self):
        # 2026-03-14 is Saturday
        assert self.session.is_open(utc(2026, 3, 14, 15, 0)) is False

    def test_dst_transition_march_2026(self):
        # US DST starts 2026-03-08 02:00 → clocks spring forward to 03:00
        # Before DST: 09:30 ET (EST) = 14:30 UTC
        # After DST:  09:30 ET (EDT) = 13:30 UTC
        # Tuesday 2026-03-10 is post-DST: 09:30 ET = 13:30 UTC
        assert self.session.is_open(utc(2026, 3, 10, 13, 30)) is True
        assert self.session.is_open(utc(2026, 3, 10, 14, 30)) is True  # 10:30 ET — still open

    def test_dst_transition_exact_boundary(self):
        # 2026-03-08 is DST switchover Sunday — market closed anyway
        # Monday 2026-03-09: first post-DST trading day
        # 09:30 EDT = UTC-4, so 09:30 ET = 13:30 UTC
        assert self.session.is_open(utc(2026, 3, 9, 13, 30)) is True
        # Under old hardcoded UTC-5: 14:30 UTC would be 09:30, but that's wrong post-DST
        # 14:30 UTC post-DST = 10:30 EDT — still open, so this also passes
        assert self.session.is_open(utc(2026, 3, 9, 16, 59)) is True  # 12:59 EDT
        assert self.session.is_open(utc(2026, 3, 9, 20, 0)) is False  # 16:00 EDT = closed


class TestFutures245IsOpen:
    """Futures 24/5: 18:00-17:00 Chicago, Mon-Fri + Sun, midnight wrap."""

    def setup_method(self):
        from src.core.models import CONTINUOUS_SESSIONS
        self.session = CONTINUOUS_SESSIONS["futures_24_5"]

    def test_open_at_open_time(self):
        # Sunday 2026-03-08 18:00 Chicago (CST UTC-6) = Sunday 00:00 UTC 2026-03-09
        assert self.session.is_open(utc(2026, 3, 9, 0, 0)) is True

    def test_closed_after_close_time(self):
        # Friday 17:00 Chicago CST = Friday 23:00 UTC
        assert self.session.is_open(utc(2026, 3, 13, 23, 0)) is False

    def test_closed_on_saturday(self):
        # Saturday is dark for futures
        assert self.session.is_open(utc(2026, 3, 14, 10, 0)) is False

    def test_open_sunday_pre_session_start(self):
        # Sunday 17:59 Chicago = before 18:00 open → closed
        assert self.session.is_open(utc(2026, 3, 8, 23, 59)) is False


class TestAllDaySession:
    """FX 24/5: open_time == close_time → all-day on trading days."""

    def setup_method(self):
        from src.core.models import CONTINUOUS_SESSIONS
        self.session = CONTINUOUS_SESSIONS["fx_24_5"]

    def test_open_any_time_on_weekday(self):
        assert self.session.is_open(utc(2026, 3, 10, 3, 0)) is True

    def test_closed_on_saturday(self):
        assert self.session.is_open(utc(2026, 3, 14, 12, 0)) is False


class TestTradingBreaks:
    """TSE has lunch break 11:30-12:30 JST."""

    def setup_method(self):
        from src.core.models import EXCHANGE_SESSIONS
        self.session = EXCHANGE_SESSIONS["tse"]

    def test_open_before_break(self):
        # Tuesday; 11:00 JST = 02:00 UTC
        assert self.session.is_open(utc(2026, 3, 10, 2, 0)) is True
        assert self.session.in_trading_break(utc(2026, 3, 10, 2, 0)) is False

    def test_in_break(self):
        # 11:30 JST = 02:30 UTC
        assert self.session.is_open(utc(2026, 3, 10, 2, 30)) is True   # still "open"
        assert self.session.in_trading_break(utc(2026, 3, 10, 2, 30)) is True

    def test_after_break(self):
        # 12:30 JST = 03:30 UTC
        assert self.session.is_open(utc(2026, 3, 10, 3, 30)) is True
        assert self.session.in_trading_break(utc(2026, 3, 10, 3, 30)) is False

    def test_no_break_on_nyse(self):
        from src.core.models import EXCHANGE_SESSIONS
        nyse = EXCHANGE_SESSIONS["nyse"]
        assert nyse.in_trading_break(utc(2026, 3, 10, 15, 0)) is False


class TestElapsedFraction:
    def test_all_day_returns_none(self):
        from src.core.models import CONTINUOUS_SESSIONS
        fx = CONTINUOUS_SESSIONS["fx_24_5"]
        assert fx.elapsed_fraction(utc(2026, 3, 10, 12, 0)) is None

    def test_closed_returns_none(self):
        from src.core.models import EXCHANGE_SESSIONS
        nyse = EXCHANGE_SESSIONS["nyse"]
        # Before open
        assert nyse.elapsed_fraction(utc(2026, 3, 10, 14, 0)) is None  # 09:00 ET — before 09:30

    def test_open_returns_0_at_open(self):
        from src.core.models import EXCHANGE_SESSIONS
        nyse = EXCHANGE_SESSIONS["nyse"]
        # 09:30 ET = 14:30 UTC (EST, pre-DST check date: 2026-03-03)
        result = nyse.elapsed_fraction(utc(2026, 3, 3, 14, 30))
        assert result is not None
        assert abs(result) < 0.01  # near 0.0

    def test_approaches_1_at_close(self):
        from src.core.models import EXCHANGE_SESSIONS
        nyse = EXCHANGE_SESSIONS["nyse"]
        # 15:59 ET = 20:59 UTC (EST, 2026-03-03)
        result = nyse.elapsed_fraction(utc(2026, 3, 3, 20, 59))
        assert result is not None
        assert result > 0.99

    def test_tse_break_excluded_from_denominator(self):
        """Break duration should be excluded so elapsed_frac < 1.0 at market close."""
        from src.core.models import EXCHANGE_SESSIONS
        tse = EXCHANGE_SESSIONS["tse"]
        # TSE open 09:00 JST, close 15:30 JST = 6.5h total, minus 1h break = 5.5h denominator
        # At 14:30 JST (just before power hour): elapsed ~= (14:30 - 09:00) - 1h break = 4.5h
        # frac ~= 4.5 / 5.5 ~= 0.818
        # 14:30 JST = 05:30 UTC
        result = tse.elapsed_fraction(utc(2026, 3, 10, 5, 30))
        assert result is not None
        assert 0.80 < result < 0.85
