from datetime import UTC, datetime

import pytest

from src.core.bar_normalizer import _generate_session_slots

UTC = UTC


def ts(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=UTC)


class TestCrypto24_7:
    def test_fills_every_slot_no_gaps(self):
        start = ts("2026-03-10 00:00:00")
        end   = ts("2026-03-10 00:05:00")
        slots = _generate_session_slots("crypto_24_7", "PAXOS", "1m", start, end)
        assert slots == [
            ts("2026-03-10 00:00:00"),
            ts("2026-03-10 00:01:00"),
            ts("2026-03-10 00:02:00"),
            ts("2026-03-10 00:03:00"),
            ts("2026-03-10 00:04:00"),
            ts("2026-03-10 00:05:00"),
        ]

    def test_weekend_included(self):
        # Saturday/Sunday — crypto trades
        start = ts("2026-03-14 12:00:00")  # Saturday
        end   = ts("2026-03-14 12:02:00")
        slots = _generate_session_slots("crypto_24_7", "PAXOS", "1m", start, end)
        assert len(slots) == 3


class TestFx24_5:
    def test_weekday_slots_included(self):
        # Monday 2026-03-09 00:00 UTC — FX open
        start = ts("2026-03-09 00:00:00")
        end   = ts("2026-03-09 00:02:00")
        slots = _generate_session_slots("fx_24_5", "IDEALPRO", "1m", start, end)
        assert len(slots) == 3

    def test_saturday_excluded(self):
        # Saturday 2026-03-14 — FX closed
        start = ts("2026-03-14 12:00:00")
        end   = ts("2026-03-14 12:05:00")
        slots = _generate_session_slots("fx_24_5", "IDEALPRO", "1m", start, end)
        assert slots == []

    def test_sunday_excluded(self):
        # Sunday 2026-03-15 — FX closed
        start = ts("2026-03-15 10:00:00")
        end   = ts("2026-03-15 10:05:00")
        slots = _generate_session_slots("fx_24_5", "IDEALPRO", "1m", start, end)
        assert slots == []


class TestNyse:
    def test_regular_trading_day_premarket_filled(self):
        # 2026-03-10 is a Tuesday — regular trading day
        # 09:00 UTC = 04:00 ET — pre-market window starts
        start = ts("2026-03-10 09:00:00")
        end   = ts("2026-03-10 09:02:00")
        slots = _generate_session_slots("nyse", "SMART", "1m", start, end)
        assert len(slots) == 3

    def test_regular_trading_day_afterhours_filled(self):
        # 22:00 UTC = 18:00 ET — within after-hours window (ends 20:00 ET = 01:00 UTC next day)
        start = ts("2026-03-10 22:00:00")
        end   = ts("2026-03-10 22:02:00")
        slots = _generate_session_slots("nyse", "SMART", "1m", start, end)
        assert len(slots) == 3

    def test_overnight_gap_excluded(self):
        # 02:00 UTC = 22:00 ET previous day — outside 4am-8pm ET window
        start = ts("2026-03-10 02:00:00")
        end   = ts("2026-03-10 02:05:00")
        slots = _generate_session_slots("nyse", "SMART", "1m", start, end)
        assert slots == []

    def test_market_holiday_excluded(self):
        # 2026-01-19 is MLK Day — NYSE closed
        start = ts("2026-01-19 14:30:00")  # 9:30 ET — would be RTH open
        end   = ts("2026-01-19 14:35:00")
        slots = _generate_session_slots("nyse", "SMART", "1m", start, end)
        assert slots == []

    def test_weekend_excluded(self):
        start = ts("2026-03-14 14:30:00")  # Saturday
        end   = ts("2026-03-14 14:35:00")
        slots = _generate_session_slots("nyse", "SMART", "1m", start, end)
        assert slots == []


class TestFutures24_5:
    def test_cme_weekday_session_filled(self):
        # Tuesday 2026-03-10 02:00 UTC — CME Globex open
        start = ts("2026-03-10 02:00:00")
        end   = ts("2026-03-10 02:02:00")
        slots = _generate_session_slots("futures_24_5", "CME", "1m", start, end)
        assert len(slots) == 3

    def test_cbot_weekday_session_filled(self):
        start = ts("2026-03-10 02:00:00")
        end   = ts("2026-03-10 02:02:00")
        slots = _generate_session_slots("futures_24_5", "CBOT", "1m", start, end)
        assert len(slots) == 3

    def test_weekend_excluded(self):
        # Saturday 2026-03-14 — Globex closed
        start = ts("2026-03-14 12:00:00")
        end   = ts("2026-03-14 12:05:00")
        slots = _generate_session_slots("futures_24_5", "CME", "1m", start, end)
        assert slots == []

    def test_unknown_exchange_raises(self):
        with pytest.raises((KeyError, ValueError)):
            _generate_session_slots("futures_24_5", "UNKNOWN_XYZ", "1m",
                                    ts("2026-03-10 02:00:00"),
                                    ts("2026-03-10 02:05:00"))
