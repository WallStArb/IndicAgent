import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parents[3]))

from src.core.bar_normalizer import SOURCE_DERIVED_1M


def test_aggregate_bars_from_1m_5m_groups_correctly():
    """Five 1m bars in the same 5m window produce one aggregated bar."""
    from scripts.infrastructure.backfill.infrastructure_run_historical_pipeline import (
        aggregate_bars_from_1m,
    )

    base = datetime(2026, 3, 7, 9, 30, 0, tzinfo=UTC)
    bars = [
        {
            "timestamp": base.replace(minute=30 + i),
            "open": 100 + i,
            "high": 105 + i,
            "low": 99 + i,
            "close": 101 + i,
            "volume": 10,
        }
        for i in range(5)
    ]
    result = aggregate_bars_from_1m(bars, "5m")
    assert len(result) == 1
    agg = result[0]
    assert agg["timestamp"] == base.replace(minute=30)
    assert agg["open"] == bars[0]["open"]
    assert agg["close"] == bars[-1]["close"]
    assert agg["high"] == max(b["high"] for b in bars)
    assert agg["low"] == min(b["low"] for b in bars)
    assert agg["volume"] == 50
    assert agg["source"] == SOURCE_DERIVED_1M


def test_aggregate_bars_from_1m_splits_across_windows():
    """Bars spanning two 5m windows produce two aggregated bars."""
    from scripts.infrastructure.backfill.infrastructure_run_historical_pipeline import (
        aggregate_bars_from_1m,
    )

    base = datetime(2026, 3, 7, 9, 33, 0, tzinfo=UTC)
    bars = [
        {
            "timestamp": base.replace(minute=33),
            "open": 100,
            "high": 102,
            "low": 99,
            "close": 101,
            "volume": 5,
        },
        {
            "timestamp": base.replace(minute=34),
            "open": 101,
            "high": 103,
            "low": 100,
            "close": 102,
            "volume": 5,
        },
        {
            "timestamp": base.replace(minute=35),
            "open": 102,
            "high": 104,
            "low": 101,
            "close": 103,
            "volume": 5,
        },
    ]
    result = aggregate_bars_from_1m(bars, "5m")
    assert len(result) == 2
    assert result[0]["timestamp"] == base.replace(minute=30)
    assert result[1]["timestamp"] == base.replace(minute=35)


def test_aggregate_bars_from_1m_daily_floors_to_midnight():
    """1d aggregation floors timestamps to midnight."""
    from scripts.infrastructure.backfill.infrastructure_run_historical_pipeline import (
        aggregate_bars_from_1m,
    )

    bars = [
        {
            "timestamp": datetime(2026, 3, 7, 9, 30, tzinfo=UTC),
            "open": 100,
            "high": 105,
            "low": 99,
            "close": 104,
            "volume": 100,
        },
        {
            "timestamp": datetime(2026, 3, 7, 15, 0, tzinfo=UTC),
            "open": 104,
            "high": 106,
            "low": 103,
            "close": 105,
            "volume": 200,
        },
    ]
    result = aggregate_bars_from_1m(bars, "1d")
    assert len(result) == 1
    assert result[0]["timestamp"] == datetime(2026, 3, 7, 0, 0, tzinfo=UTC)
    assert result[0]["volume"] == 300


def test_aggregate_bars_from_1m_none_volume_treated_as_zero():
    """None volume values (FX has no volume) are treated as 0."""
    from scripts.infrastructure.backfill.infrastructure_run_historical_pipeline import (
        aggregate_bars_from_1m,
    )

    base = datetime(2026, 3, 7, 9, 30, tzinfo=UTC)
    bars = [
        {
            "timestamp": base,
            "open": 1.10,
            "high": 1.11,
            "low": 1.09,
            "close": 1.105,
            "volume": None,
        },
        {
            "timestamp": base.replace(minute=31),
            "open": 1.105,
            "high": 1.112,
            "low": 1.104,
            "close": 1.11,
            "volume": None,
        },
    ]
    result = aggregate_bars_from_1m(bars, "5m")
    assert result[0]["volume"] == 0


def test_aggregate_bars_from_1m_4h_floors_to_4h_boundaries():
    """4h aggregation must group to 00:00, 04:00, 08:00, ... boundaries.

    Bug: the old minute-only floor left ts.hour unchanged, making each hour
    its own bucket and producing 1h bars stored as 4h.
    """
    from scripts.infrastructure.backfill.infrastructure_run_historical_pipeline import (
        aggregate_bars_from_1m,
    )

    def _bar(h: int, m: int, close: float) -> dict:
        return {
            "timestamp": datetime(2026, 3, 7, h, m, tzinfo=UTC),
            "open": close - 0.5,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": 100,
        }

    bars = [
        _bar(0, 0, 100.0),
        _bar(0, 30, 101.0),
        _bar(1, 0, 102.0),
        _bar(2, 0, 103.0),
        _bar(3, 30, 104.0),
        _bar(4, 0, 200.0),
        _bar(5, 0, 201.0),
        _bar(7, 30, 202.0),
    ]
    result = aggregate_bars_from_1m(bars, "4h")
    assert (
        len(result) == 2
    ), f"Expected 2 4h windows, got {len(result)}: {[r['timestamp'] for r in result]}"
    assert result[0]["timestamp"] == datetime(2026, 3, 7, 0, 0, tzinfo=UTC)
    assert result[1]["timestamp"] == datetime(2026, 3, 7, 4, 0, tzinfo=UTC)
    assert result[0]["open"] == bars[0]["open"]
    assert result[0]["close"] == bars[4]["close"]  # last bar in 00:00-03:59 window
    assert result[0]["volume"] == 500  # 5 bars × 100
    assert result[1]["volume"] == 300  # 3 bars × 100


def test_aggregate_bars_from_1m_1h_floors_correctly():
    """1h aggregation: bars at 09:00-09:59 and 10:00-10:59 form two buckets."""
    from scripts.infrastructure.backfill.infrastructure_run_historical_pipeline import (
        aggregate_bars_from_1m,
    )

    bars = [
        {
            "timestamp": datetime(2026, 3, 7, 9, 0, tzinfo=UTC),
            "open": 1,
            "high": 2,
            "low": 0,
            "close": 1.5,
            "volume": 10,
        },
        {
            "timestamp": datetime(2026, 3, 7, 9, 30, tzinfo=UTC),
            "open": 1.5,
            "high": 2,
            "low": 1,
            "close": 2,
            "volume": 20,
        },
        {
            "timestamp": datetime(2026, 3, 7, 10, 0, tzinfo=UTC),
            "open": 2,
            "high": 3,
            "low": 1.5,
            "close": 2.5,
            "volume": 30,
        },
    ]
    result = aggregate_bars_from_1m(bars, "1h")
    assert len(result) == 2
    assert result[0]["timestamp"] == datetime(2026, 3, 7, 9, 0, tzinfo=UTC)
    assert result[1]["timestamp"] == datetime(2026, 3, 7, 10, 0, tzinfo=UTC)


def _ts_bf(hour, minute):
    return datetime(2026, 2, 1, hour, minute, 0, tzinfo=UTC)


class TestFetchAndStoreBars:
    def test_fetch_1m_bars_queries_correct_table(self):
        from scripts.infrastructure.backfill.infrastructure_run_historical_pipeline import (
            fetch_bars,
        )

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            (
                datetime(2026, 2, 1, 9, 30, tzinfo=UTC),
                100.0,
                101.0,
                99.0,
                100.5,
                1000,
                "historical_backfill",
            )
        ]
        rows = fetch_bars(mock_conn, "ESH6", "1m")
        assert len(rows) == 1 and rows[0]["symbol"] == "ESH6" and "timestamp" in rows[0]

    def test_store_bars_calls_execute_batch(self):
        from scripts.infrastructure.backfill.infrastructure_run_historical_pipeline import (
            store_bars,
        )

        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = MagicMock()
        bars = [
            {
                "timestamp": _ts_bf(9, 30),
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 1000,
            }
        ]
        with patch("psycopg2.extras.execute_batch"):
            store_bars(mock_conn, bars, symbol="ESH6", timeframe="5m")
        mock_conn.commit.assert_called_once()


class TestLoadIbkrRetryConfig:
    """todo 050: _load_ibkr_retry_config() overlays infra.ibkr.retry_count /
    retry_backoff_base_s / no_data_confirmation_chunks (migration 235) onto
    ibkr's module-level constants in place, mirroring the existing
    _load_ibkr_chunk_days_config/_load_ibkr_hist_timeout_config pattern.
    """

    def _restore_ibkr_defaults(self):
        from src.providers import ibkr

        ibkr._RETRY_COUNT = 3
        ibkr._RETRY_BACKOFF_BASE_S = 65
        ibkr._NO_DATA_CONFIRMATION_CHUNKS = 2

    def test_overlays_all_three_keys_when_present(self):
        from scripts.infrastructure.backfill.infrastructure_run_historical_pipeline import (
            _load_ibkr_retry_config,
        )
        from src.providers import ibkr

        try:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            mock_cursor.fetchall.return_value = [
                ("infra.ibkr.retry_count", "5"),
                ("infra.ibkr.retry_backoff_base_s", "90"),
                ("infra.ibkr.no_data_confirmation_chunks", "3"),
            ]
            with patch(
                "scripts.infrastructure.backfill.infrastructure_run_historical_pipeline.connect_db",
                return_value=mock_conn,
            ):
                _load_ibkr_retry_config(MagicMock())

            assert ibkr._RETRY_COUNT == 5
            assert ibkr._RETRY_BACKOFF_BASE_S == 90
            assert ibkr._NO_DATA_CONFIRMATION_CHUNKS == 3
        finally:
            self._restore_ibkr_defaults()

    def test_missing_keys_keep_hardcoded_defaults(self):
        from scripts.infrastructure.backfill.infrastructure_run_historical_pipeline import (
            _load_ibkr_retry_config,
        )
        from src.providers import ibkr

        try:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            mock_cursor.fetchall.return_value = []
            with patch(
                "scripts.infrastructure.backfill.infrastructure_run_historical_pipeline.connect_db",
                return_value=mock_conn,
            ):
                _load_ibkr_retry_config(MagicMock())

            assert ibkr._RETRY_COUNT == 3
            assert ibkr._RETRY_BACKOFF_BASE_S == 65
            assert ibkr._NO_DATA_CONFIRMATION_CHUNKS == 2
        finally:
            self._restore_ibkr_defaults()

    def test_db_error_falls_back_to_hardcoded_defaults_without_raising(self):
        from scripts.infrastructure.backfill.infrastructure_run_historical_pipeline import (
            _load_ibkr_retry_config,
        )
        from src.providers import ibkr

        try:
            with patch(
                "scripts.infrastructure.backfill.infrastructure_run_historical_pipeline.connect_db",
                side_effect=Exception("db unreachable"),
            ):
                _load_ibkr_retry_config(MagicMock())  # must not raise

            assert ibkr._RETRY_COUNT == 3
            assert ibkr._RETRY_BACKOFF_BASE_S == 65
            assert ibkr._NO_DATA_CONFIRMATION_CHUNKS == 2
        finally:
            self._restore_ibkr_defaults()


class TestLoadIbkrRateLimitConfig:
    """todo 050: _load_ibkr_rate_limit_config() overlays
    infra.ibkr.rate_limit_max_requests / rate_limit_window_sec (migration 276) onto
    ibkr._IBKR_HIST_RATE_LIMIT / ibkr._IBKR_HIST_WINDOW_S in place, same pattern as
    the sibling loaders above.
    """

    def _restore_ibkr_defaults(self):
        from src.providers import ibkr

        ibkr._IBKR_HIST_RATE_LIMIT = 55
        ibkr._IBKR_HIST_WINDOW_S = 600.0

    def test_overlays_both_keys_when_present(self):
        from scripts.infrastructure.backfill.infrastructure_run_historical_pipeline import (
            _load_ibkr_rate_limit_config,
        )
        from src.providers import ibkr

        try:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            mock_cursor.fetchall.return_value = [
                ("infra.ibkr.rate_limit_max_requests", "40"),
                ("infra.ibkr.rate_limit_window_sec", "300.0"),
            ]
            with patch(
                "scripts.infrastructure.backfill.infrastructure_run_historical_pipeline.connect_db",
                return_value=mock_conn,
            ):
                _load_ibkr_rate_limit_config(MagicMock())

            assert ibkr._IBKR_HIST_RATE_LIMIT == 40
            assert ibkr._IBKR_HIST_WINDOW_S == 300.0
        finally:
            self._restore_ibkr_defaults()

    def test_missing_keys_keep_hardcoded_defaults(self):
        from scripts.infrastructure.backfill.infrastructure_run_historical_pipeline import (
            _load_ibkr_rate_limit_config,
        )
        from src.providers import ibkr

        try:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            mock_cursor.fetchall.return_value = []
            with patch(
                "scripts.infrastructure.backfill.infrastructure_run_historical_pipeline.connect_db",
                return_value=mock_conn,
            ):
                _load_ibkr_rate_limit_config(MagicMock())

            assert ibkr._IBKR_HIST_RATE_LIMIT == 55
            assert ibkr._IBKR_HIST_WINDOW_S == 600.0
        finally:
            self._restore_ibkr_defaults()

    def test_db_error_falls_back_to_hardcoded_defaults_without_raising(self):
        from scripts.infrastructure.backfill.infrastructure_run_historical_pipeline import (
            _load_ibkr_rate_limit_config,
        )
        from src.providers import ibkr

        try:
            with patch(
                "scripts.infrastructure.backfill.infrastructure_run_historical_pipeline.connect_db",
                side_effect=Exception("db unreachable"),
            ):
                _load_ibkr_rate_limit_config(MagicMock())  # must not raise

            assert ibkr._IBKR_HIST_RATE_LIMIT == 55
            assert ibkr._IBKR_HIST_WINDOW_S == 600.0
        finally:
            self._restore_ibkr_defaults()


def _make_mock_conn(fetchall_result=None):
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_cursor.fetchall.return_value = fetchall_result or []
    return mock_conn, mock_cursor


class TestDetectGaps:
    def _mock_conn(self, fetchall_result=None):
        mock_conn, _ = _make_mock_conn(fetchall_result)
        return mock_conn

    def test_cme_futures_over_weekend_no_gaps(self):
        from scripts.infrastructure.backfill.infrastructure_run_historical_pipeline import (
            detect_gaps,
        )

        gaps = detect_gaps(
            self._mock_conn(),
            "ESH6",
            "1h",
            datetime(2026, 1, 3, 0, 0, tzinfo=UTC),
            datetime(2026, 1, 4, 23, 59, tzinfo=UTC),
            "futures_24_5",
            "CME",
        )
        assert gaps == []

    def test_nyse_over_weekend_no_gaps(self):
        from scripts.infrastructure.backfill.infrastructure_run_historical_pipeline import (
            detect_gaps,
        )

        with patch(
            "scripts.infrastructure.backfill.infrastructure_run_historical_pipeline"
            ".generate_session_slots",
            return_value=[],
        ):
            gaps = detect_gaps(
                self._mock_conn(),
                "SPY",
                "5m",
                datetime(2026, 1, 3, 0, 0, tzinfo=UTC),
                datetime(2026, 1, 4, 23, 59, tzinfo=UTC),
                "nyse",
                "NYSE",
            )
        assert gaps == []

    def test_nyse_on_holiday_no_gaps(self):
        from scripts.infrastructure.backfill.infrastructure_run_historical_pipeline import (
            detect_gaps,
        )

        with patch(
            "scripts.infrastructure.backfill.infrastructure_run_historical_pipeline"
            ".generate_session_slots",
            return_value=[],
        ):
            gaps = detect_gaps(
                self._mock_conn(),
                "SPY",
                "5m",
                datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
                datetime(2026, 1, 1, 23, 59, tzinfo=UTC),
                "nyse",
                "NYSE",
            )
        assert gaps == []

    def test_genuine_intraday_gap_detected(self):
        from scripts.infrastructure.backfill.infrastructure_run_historical_pipeline import (
            detect_gaps,
        )

        slots = [datetime(2026, 1, 2, h, 0, tzinfo=UTC) for h in range(15, 19)]
        mock_conn = self._mock_conn(
            [(datetime(2026, 1, 2, 15, 0, tzinfo=UTC),), (datetime(2026, 1, 2, 18, 0, tzinfo=UTC),)]
        )
        with patch(
            "scripts.infrastructure.backfill.infrastructure_run_historical_pipeline"
            ".generate_session_slots",
            return_value=slots,
        ):
            gaps = detect_gaps(
                mock_conn,
                "SPY",
                "1h",
                datetime(2026, 1, 2, 15, 0, tzinfo=UTC),
                datetime(2026, 1, 2, 18, 0, tzinfo=UTC),
                "nyse",
                "NYSE",
            )
        assert len(gaps) == 1
        assert gaps[0] == (
            datetime(2026, 1, 2, 16, 0, tzinfo=UTC),
            datetime(2026, 1, 2, 17, 0, tzinfo=UTC),
        )
