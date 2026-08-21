from datetime import UTC, datetime

import pytest

from src.core.bar_normalizer import (
    SOURCE_DERIVED_1M,
    SOURCE_SYNTHETIC_FILL,
    generate_session_slots,
    normalize_bars,
)

UTC = UTC


def ts(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=UTC)


class TestCrypto24_7:
    def test_fills_every_slot_no_gaps(self):
        start = ts("2026-03-10 00:00:00")
        end = ts("2026-03-10 00:05:00")
        slots = generate_session_slots("crypto_24_7", "PAXOS", "1m", start, end)
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
        end = ts("2026-03-14 12:02:00")
        slots = generate_session_slots("crypto_24_7", "PAXOS", "1m", start, end)
        assert len(slots) == 3


class TestFx24_5:
    def test_weekday_slots_included(self):
        # Monday 2026-03-09 00:00 UTC — FX open
        start = ts("2026-03-09 00:00:00")
        end = ts("2026-03-09 00:02:00")
        slots = generate_session_slots("fx_24_5", "IDEALPRO", "1m", start, end)
        assert len(slots) == 3

    def test_saturday_excluded(self):
        # Saturday 2026-03-14 — FX closed
        start = ts("2026-03-14 12:00:00")
        end = ts("2026-03-14 12:05:00")
        slots = generate_session_slots("fx_24_5", "IDEALPRO", "1m", start, end)
        assert slots == []

    def test_sunday_excluded(self):
        # Sunday 2026-03-15 — FX closed
        start = ts("2026-03-15 10:00:00")
        end = ts("2026-03-15 10:05:00")
        slots = generate_session_slots("fx_24_5", "IDEALPRO", "1m", start, end)
        assert slots == []


class TestNyse:
    def test_regular_trading_day_premarket_filled(self):
        # 2026-03-10 is a Tuesday — regular trading day
        # 09:00 UTC = 04:00 ET — pre-market window starts
        start = ts("2026-03-10 09:00:00")
        end = ts("2026-03-10 09:02:00")
        slots = generate_session_slots("nyse", "SMART", "1m", start, end)
        assert len(slots) == 3

    def test_regular_trading_day_afterhours_filled(self):
        # 22:00 UTC = 18:00 ET — within after-hours window (ends 20:00 ET = 01:00 UTC next day)
        start = ts("2026-03-10 22:00:00")
        end = ts("2026-03-10 22:02:00")
        slots = generate_session_slots("nyse", "SMART", "1m", start, end)
        assert len(slots) == 3

    def test_overnight_gap_excluded(self):
        # 02:00 UTC = 22:00 ET previous day — outside 4am-8pm ET window
        start = ts("2026-03-10 02:00:00")
        end = ts("2026-03-10 02:05:00")
        slots = generate_session_slots("nyse", "SMART", "1m", start, end)
        assert slots == []

    def test_market_holiday_excluded(self):
        # 2026-01-19 is MLK Day — NYSE closed
        start = ts("2026-01-19 14:30:00")  # 9:30 ET — would be RTH open
        end = ts("2026-01-19 14:35:00")
        slots = generate_session_slots("nyse", "SMART", "1m", start, end)
        assert slots == []

    def test_weekend_excluded(self):
        start = ts("2026-03-14 14:30:00")  # Saturday
        end = ts("2026-03-14 14:35:00")
        slots = generate_session_slots("nyse", "SMART", "1m", start, end)
        assert slots == []


class TestNyse1d:
    """todo 300: 1d bars are stored midnight-UTC-anchored (one row per trading day), not
    session-open-anchored like every intraday timeframe -- generate_session_slots must
    special-case timeframe='1d' for session_id='nyse' to match that storage convention.
    """

    def test_trading_days_return_midnight_utc_slots(self):
        # 2026-03-10/11 are consecutive Tue/Wed trading days
        start = ts("2026-03-10 00:00:00")
        end = ts("2026-03-11 00:00:00")
        slots = generate_session_slots("nyse", "SMART", "1d", start, end)
        assert slots == [ts("2026-03-10 00:00:00"), ts("2026-03-11 00:00:00")]

    def test_matches_market_data_ohlcv_storage_convention(self):
        # The exact reproduction from todo 300's filing: 2016-10-18/19 expected slots
        # must equal market_data_ohlcv's actual stored 00:00:00 UTC timestamps, not
        # _slots_nyse's 04:00 ET (08:00 UTC) session-open anchor.
        start = ts("2016-10-18 00:00:00")
        end = ts("2016-10-19 00:00:00")
        slots = generate_session_slots("nyse", "SMART", "1d", start, end)
        assert slots == [ts("2016-10-18 00:00:00"), ts("2016-10-19 00:00:00")]

    def test_market_holiday_excluded(self):
        # 2026-01-19 is MLK Day — NYSE closed, no 1d slot expected
        start = ts("2026-01-19 00:00:00")
        end = ts("2026-01-19 00:00:00")
        slots = generate_session_slots("nyse", "SMART", "1d", start, end)
        assert slots == []

    def test_weekend_excluded(self):
        start = ts("2026-03-14 00:00:00")  # Saturday
        end = ts("2026-03-15 00:00:00")  # Sunday
        slots = generate_session_slots("nyse", "SMART", "1d", start, end)
        assert slots == []

    def test_half_day_still_yields_one_slot(self):
        # 2026-11-27 is the day after Thanksgiving — NYSE half-day, still one 1d bar
        start = ts("2026-11-27 00:00:00")
        end = ts("2026-11-27 00:00:00")
        slots = generate_session_slots("nyse", "SMART", "1d", start, end)
        assert slots == [ts("2026-11-27 00:00:00")]


class TestFutures24_5:
    def test_cme_weekday_session_filled(self):
        # Tuesday 2026-03-10 02:00 UTC — CME Globex open
        start = ts("2026-03-10 02:00:00")
        end = ts("2026-03-10 02:02:00")
        slots = generate_session_slots("futures_24_5", "CME", "1m", start, end)
        assert len(slots) == 3

    def test_cbot_weekday_session_filled(self):
        start = ts("2026-03-10 02:00:00")
        end = ts("2026-03-10 02:02:00")
        slots = generate_session_slots("futures_24_5", "CBOT", "1m", start, end)
        assert len(slots) == 3

    def test_weekend_excluded(self):
        # Saturday 2026-03-14 — Globex closed
        start = ts("2026-03-14 12:00:00")
        end = ts("2026-03-14 12:05:00")
        slots = generate_session_slots("futures_24_5", "CME", "1m", start, end)
        assert slots == []

    def test_unknown_exchange_raises(self):
        with pytest.raises((KeyError, ValueError)):
            generate_session_slots(
                "futures_24_5",
                "UNKNOWN_XYZ",
                "1m",
                ts("2026-03-10 02:00:00"),
                ts("2026-03-10 02:05:00"),
            )


def make_bar(timestamp: str, close: float, source: str = "historical_backfill") -> dict:
    t = datetime.fromisoformat(timestamp).replace(tzinfo=UTC)
    return {
        "timestamp": t,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 100,
        "source": source,
    }


class TestNormalizeBars:
    def test_no_gaps_returns_unchanged(self):
        bars = [
            make_bar("2026-03-10 14:00:00", 100.0),
            make_bar("2026-03-10 14:01:00", 101.0),
            make_bar("2026-03-10 14:02:00", 102.0),
        ]
        result = normalize_bars(
            bars,
            "SPY",
            "1m",
            ts("2026-03-10 14:00:00"),
            ts("2026-03-10 14:02:00"),
        )
        assert len(result) == 3
        assert all(b["source"] == "historical_backfill" for b in result)

    def test_gap_filled_with_prev_close(self):
        bars = [
            make_bar("2026-03-10 14:00:00", 100.0),
            # 14:01 missing
            make_bar("2026-03-10 14:02:00", 102.0),
        ]
        result = normalize_bars(
            bars,
            "SPY",
            "1m",
            ts("2026-03-10 14:00:00"),
            ts("2026-03-10 14:02:00"),
        )
        assert len(result) == 3
        synthetic = result[1]
        assert synthetic["timestamp"] == ts("2026-03-10 14:01:00")
        assert synthetic["open"] == 100.0
        assert synthetic["high"] == 100.0
        assert synthetic["low"] == 100.0
        assert synthetic["close"] == 100.0
        assert synthetic["volume"] == 0
        assert synthetic["source"] == SOURCE_SYNTHETIC_FILL

    def test_no_prev_close_gap_at_start_skipped(self):
        # First two bars missing — no prev_close to fill from
        bars = [make_bar("2026-03-10 14:02:00", 102.0)]
        result = normalize_bars(
            bars,
            "SPY",
            "1m",
            ts("2026-03-10 14:00:00"),
            ts("2026-03-10 14:02:00"),
        )
        # 14:00 and 14:01 have no prev_close — skipped
        assert len(result) == 1
        assert result[0]["timestamp"] == ts("2026-03-10 14:02:00")

    def test_source_preserved_on_real_bars(self):
        bars = [
            make_bar("2026-03-10 14:00:00", 100.0, source=SOURCE_DERIVED_1M),
            make_bar("2026-03-10 14:01:00", 101.0, source="historical_backfill"),
        ]
        result = normalize_bars(
            bars,
            "SPY",
            "1m",
            ts("2026-03-10 14:00:00"),
            ts("2026-03-10 14:01:00"),
        )
        assert result[0]["source"] == SOURCE_DERIVED_1M
        assert result[1]["source"] == "historical_backfill"

    def test_weekend_gap_filled_with_synthetic(self):
        # Canonical grid: every slot filled regardless of session — synthetic_fill marks non-trading
        bars = [
            make_bar("2026-03-13 01:00:00", 100.0),
            make_bar("2026-03-16 09:00:00", 101.0),
        ]
        result = normalize_bars(
            bars,
            "SPY",
            "1m",
            ts("2026-03-13 01:00:00"),
            ts("2026-03-16 09:00:00"),
        )
        # All 1m slots filled — real bars at start/end, synthetic in between
        expected_slots = (
            int((ts("2026-03-16 09:00:00") - ts("2026-03-13 01:00:00")).total_seconds() / 60) + 1
        )
        assert len(result) == expected_slots
        assert result[0]["source"] == "historical_backfill"
        assert result[-1]["source"] == "historical_backfill"
        assert result[1]["source"] == SOURCE_SYNTHETIC_FILL

    def test_idempotent(self):
        bars = [
            make_bar("2026-03-10 14:00:00", 100.0),
            make_bar("2026-03-10 14:02:00", 102.0),
        ]
        result1 = normalize_bars(
            bars,
            "SPY",
            "1m",
            ts("2026-03-10 14:00:00"),
            ts("2026-03-10 14:02:00"),
        )
        result2 = normalize_bars(
            result1,
            "SPY",
            "1m",
            ts("2026-03-10 14:00:00"),
            ts("2026-03-10 14:02:00"),
        )
        assert len(result1) == len(result2)
        for b1, b2 in zip(result1, result2, strict=True):
            assert b1["timestamp"] == b2["timestamp"]
            assert b1["source"] == b2["source"]

    def test_fills_across_weekend(self):
        bars = [
            make_bar("2026-03-14 12:00:00", 50000.0),
            make_bar("2026-03-14 12:02:00", 50010.0),
        ]
        result = normalize_bars(
            bars,
            "BTC",
            "1m",
            ts("2026-03-14 12:00:00"),
            ts("2026-03-14 12:02:00"),
        )
        assert len(result) == 3
        assert result[1]["source"] == SOURCE_SYNTHETIC_FILL
