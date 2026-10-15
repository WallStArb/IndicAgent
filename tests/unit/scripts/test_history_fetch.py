import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parents[3]))


def _ts_bf(hour, minute):
    return datetime(2026, 2, 1, hour, minute, 0, tzinfo=UTC)


class TestStoreBars:
    """store_bars offers bar dicts to ohlcv_raw through the raw-first ingress contract (plan 191-05)."""

    @staticmethod
    def _bar(i=0, source="ibkr_named", **over):
        bar = {
            "timestamp": _ts_bf(9, 30) + timedelta(minutes=5 * i),
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 1000,
            "source": source,
        }
        bar.update(over)
        return bar

    @staticmethod
    def _contract(monkeypatch):
        from scripts.infrastructure.backfill import _history_fetch as pipe
        from services.ohlcv_ingress_contract import IngressResult

        calls = []

        def fake(conn, rows, *, caller, request_id, answered_at, params=None):
            calls.append(
                {
                    "rows": list(rows),
                    "caller": caller,
                    "request_id": request_id,
                    "answered_at": answered_at,
                }
            )
            return IngressResult(len(rows), len(rows), 0, 0, 0)

        monkeypatch.setattr(pipe, "apply_raw_contract", fake)
        return calls

    def test_bars_become_raw_rows_with_the_vendor_and_kind_of_their_label(self, monkeypatch):
        from scripts.infrastructure.backfill._history_fetch import store_bars

        calls = self._contract(monkeypatch)
        conn = MagicMock()
        n = store_bars(conn, [self._bar(0), self._bar(1, source="ibkr_venue")], "ESH6", "5m")
        assert n == 2
        (call,) = calls
        assert [(r.vendor, r.kind) for r in call["rows"]] == [("ibkr", "named"), ("ibkr", "venue")]
        assert (call["rows"][0].symbol, call["rows"][0].timeframe) == ("ESH6", "5m")
        assert call["rows"][0].volume == 1000 and isinstance(call["rows"][0].volume, int)
        assert call["caller"] == "ibkr-history-fetch"
        assert call["request_id"] is not None
        assert call["answered_at"].tzinfo is not None  # the answer time, never the DB clock
        conn.transaction.assert_called_once()  # the write is one transaction

    def test_actual_symbol_stores_under_the_contract_symbol(self, monkeypatch):
        from scripts.infrastructure.backfill._history_fetch import store_bars

        calls = self._contract(monkeypatch)
        store_bars(MagicMock(), [self._bar()], "ESM6", "5m", actual_symbol="ESH6")
        assert calls[0]["rows"][0].symbol == "ESH6"

    def test_a_none_volume_stays_none(self, monkeypatch):
        from scripts.infrastructure.backfill._history_fetch import store_bars

        calls = self._contract(monkeypatch)
        store_bars(MagicMock(), [self._bar(volume=None)], "ESH6", "5m")
        assert calls[0]["rows"][0].volume is None

    def test_a_label_without_a_vendor_kind_pair_raises_before_any_write(self, monkeypatch):
        from scripts.infrastructure.backfill._history_fetch import store_bars

        calls = self._contract(monkeypatch)
        with pytest.raises(KeyError, match="no_such_label"):
            store_bars(MagicMock(), [self._bar(source="no_such_label")], "ESH6", "5m")
        assert calls == []

    def test_no_bars_is_a_noop(self, monkeypatch):
        from scripts.infrastructure.backfill._history_fetch import store_bars

        calls = self._contract(monkeypatch)
        assert store_bars(MagicMock(), [], "ESH6", "5m") == 0 and calls == []

    def test_a_bar_forming_when_asked_is_held_back(self, monkeypatch):
        """Second review of 191-07, finding 5: the ad hoc callers pass the time they asked; a
        bar whose block had not ended then is not a complete answer and never reaches raw."""
        from scripts.infrastructure.backfill._history_fetch import store_bars

        calls = self._contract(monkeypatch)
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value.fetchone.return_value = ("1800",)
        first, second = self._bar(0), self._bar(1)
        asked_at = second["timestamp"] + timedelta(minutes=2)
        n = store_bars(conn, [first, second], "ESH6", "5m", asked_at=asked_at, request_end=asked_at)
        assert n == 1 and [r.timestamp for r in calls[0]["rows"]] == [first["timestamp"]]


class TestClusterGapRanges:
    """cluster_gap_ranges() -- found 2026-08-11 via AA (Alcoa Corporation, which
    only trades from 2016-10-18 -- IBKR has nothing before that under this
    contract). Naive min/max bounding across all detect_gaps() ranges turned a
    permanent pre-listing void + a 1-day incremental catch-up into one 20-year
    re-request every single run, even though the middle was already fully
    populated. The write contract keeps it correct, just wasteful of real,
    rate-limited IBKR request budget.
    """

    def test_single_gap_returns_one_window(self):
        from scripts.infrastructure.backfill._history_fetch import (
            cluster_gap_ranges,
        )

        gaps = [(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 5, tzinfo=UTC))]
        assert cluster_gap_ranges(gaps) == gaps

    def test_nearby_gaps_still_coalesce(self):
        # Two gaps a few days apart stay one request -- same behavior as before
        # this fix, avoiding N tiny IBKR requests for genuinely scattered gaps.
        from scripts.infrastructure.backfill._history_fetch import (
            cluster_gap_ranges,
        )

        gaps = [
            (datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC)),
            (datetime(2026, 1, 10, tzinfo=UTC), datetime(2026, 1, 11, tzinfo=UTC)),
        ]
        windows = cluster_gap_ranges(gaps, max_gap_days=90)
        assert windows == [(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 11, tzinfo=UTC))]

    def test_distant_permanent_gap_and_recent_gap_split_into_two_windows(self):
        # The actual AA shape: a ~10-year pre-listing void far from a 1-day
        # catch-up near "now" must NOT collapse into one request re-covering
        # the already-complete decade in between.
        from scripts.infrastructure.backfill._history_fetch import (
            cluster_gap_ranges,
        )

        prelisting_void = (
            datetime(2006, 8, 15, tzinfo=UTC),
            datetime(2016, 10, 17, tzinfo=UTC),
        )
        recent_catchup = (
            datetime(2026, 8, 10, tzinfo=UTC),
            datetime(2026, 8, 11, tzinfo=UTC),
        )
        windows = cluster_gap_ranges([prelisting_void, recent_catchup], max_gap_days=90)
        assert windows == [prelisting_void, recent_catchup]

    def test_empty_gaps_returns_empty(self):
        from scripts.infrastructure.backfill._history_fetch import (
            cluster_gap_ranges,
        )

        assert cluster_gap_ranges([]) == []

    def test_default_reads_module_global_at_call_time_not_def_time(self):
        # A plain `max_gap_days: int = _GAP_CLUSTER_MAX_DAYS` default would bind 90
        # at import time and never see a later _load_gap_cluster_max_days_config()
        # APR overlay. The real default must re-read the module global on every call.
        import scripts.infrastructure.backfill._history_fetch as pipeline

        gaps = [
            (datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC)),
            (datetime(2026, 2, 1, tzinfo=UTC), datetime(2026, 2, 2, tzinfo=UTC)),
        ]
        original = pipeline._GAP_CLUSTER_MAX_DAYS
        try:
            pipeline._GAP_CLUSTER_MAX_DAYS = 5
            # ~31 days apart -- stays split under the lowered threshold.
            assert pipeline.cluster_gap_ranges(gaps) == gaps
            pipeline._GAP_CLUSTER_MAX_DAYS = 90
            # Same gaps, raised threshold -- now coalesce into one window.
            assert pipeline.cluster_gap_ranges(gaps) == [(gaps[0][0], gaps[1][1])]
        finally:
            pipeline._GAP_CLUSTER_MAX_DAYS = original


class TestLoadGapClusterMaxDaysConfig:
    """infra.backfill.gap_cluster_max_days (migration 313) overlays
    _GAP_CLUSTER_MAX_DAYS, mirroring the _load_ibkr_* loader pattern.
    """

    def _restore_default(self):
        import scripts.infrastructure.backfill._history_fetch as pipeline

        pipeline._GAP_CLUSTER_MAX_DAYS = 90

    def test_overlays_value_when_present(self):
        import scripts.infrastructure.backfill._history_fetch as pipeline
        from scripts.infrastructure.backfill._history_fetch import (
            _load_gap_cluster_max_days_config,
        )

        try:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            mock_cursor.fetchone.return_value = ("30",)
            with patch(
                "scripts.infrastructure.backfill._history_fetch.connect_db",
                return_value=mock_conn,
            ):
                _load_gap_cluster_max_days_config(MagicMock())
            assert pipeline._GAP_CLUSTER_MAX_DAYS == 30
        finally:
            self._restore_default()

    def test_missing_key_keeps_default(self):
        import scripts.infrastructure.backfill._history_fetch as pipeline
        from scripts.infrastructure.backfill._history_fetch import (
            _load_gap_cluster_max_days_config,
        )

        try:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            mock_cursor.fetchone.return_value = None
            with patch(
                "scripts.infrastructure.backfill._history_fetch.connect_db",
                return_value=mock_conn,
            ):
                _load_gap_cluster_max_days_config(MagicMock())
            assert pipeline._GAP_CLUSTER_MAX_DAYS == 90
        finally:
            self._restore_default()


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
        from scripts.infrastructure.backfill._history_fetch import (
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
                "scripts.infrastructure.backfill._history_fetch.connect_db",
                return_value=mock_conn,
            ):
                _load_ibkr_retry_config(MagicMock())

            assert ibkr._RETRY_COUNT == 5
            assert ibkr._RETRY_BACKOFF_BASE_S == 90
            assert ibkr._NO_DATA_CONFIRMATION_CHUNKS == 3
        finally:
            self._restore_ibkr_defaults()

    def test_missing_keys_keep_hardcoded_defaults(self):
        from scripts.infrastructure.backfill._history_fetch import (
            _load_ibkr_retry_config,
        )
        from src.providers import ibkr

        try:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            mock_cursor.fetchall.return_value = []
            with patch(
                "scripts.infrastructure.backfill._history_fetch.connect_db",
                return_value=mock_conn,
            ):
                _load_ibkr_retry_config(MagicMock())

            assert ibkr._RETRY_COUNT == 3
            assert ibkr._RETRY_BACKOFF_BASE_S == 65
            assert ibkr._NO_DATA_CONFIRMATION_CHUNKS == 2
        finally:
            self._restore_ibkr_defaults()

    def test_db_error_falls_back_to_hardcoded_defaults_without_raising(self):
        from scripts.infrastructure.backfill._history_fetch import (
            _load_ibkr_retry_config,
        )
        from src.providers import ibkr

        try:
            with patch(
                "scripts.infrastructure.backfill._history_fetch.connect_db",
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
        from scripts.infrastructure.backfill._history_fetch import (
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
                "scripts.infrastructure.backfill._history_fetch.connect_db",
                return_value=mock_conn,
            ):
                _load_ibkr_rate_limit_config(MagicMock())

            assert ibkr._IBKR_HIST_RATE_LIMIT == 40
            assert ibkr._IBKR_HIST_WINDOW_S == 300.0
        finally:
            self._restore_ibkr_defaults()

    def test_missing_keys_keep_hardcoded_defaults(self):
        from scripts.infrastructure.backfill._history_fetch import (
            _load_ibkr_rate_limit_config,
        )
        from src.providers import ibkr

        try:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            mock_cursor.fetchall.return_value = []
            with patch(
                "scripts.infrastructure.backfill._history_fetch.connect_db",
                return_value=mock_conn,
            ):
                _load_ibkr_rate_limit_config(MagicMock())

            assert ibkr._IBKR_HIST_RATE_LIMIT == 55
            assert ibkr._IBKR_HIST_WINDOW_S == 600.0
        finally:
            self._restore_ibkr_defaults()

    def test_db_error_falls_back_to_hardcoded_defaults_without_raising(self):
        from scripts.infrastructure.backfill._history_fetch import (
            _load_ibkr_rate_limit_config,
        )
        from src.providers import ibkr

        try:
            with patch(
                "scripts.infrastructure.backfill._history_fetch.connect_db",
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
        from scripts.infrastructure.backfill._history_fetch import (
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
            vendor="ibkr",
        )
        assert gaps == []

    def test_nyse_over_weekend_no_gaps(self):
        from scripts.infrastructure.backfill._history_fetch import (
            detect_gaps,
        )

        with patch(
            "scripts.infrastructure.backfill._history_fetch" ".expected_grid_slots",
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
                vendor="ibkr",
            )
        assert gaps == []

    def test_nyse_on_holiday_no_gaps(self):
        from scripts.infrastructure.backfill._history_fetch import (
            detect_gaps,
        )

        with patch(
            "scripts.infrastructure.backfill._history_fetch" ".expected_grid_slots",
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
                vendor="ibkr",
            )
        assert gaps == []

    def test_answered_window_slots_are_not_gaps(self):
        from scripts.infrastructure.backfill._history_fetch import (
            detect_gaps,
        )
        from src.intelligence.bars.gap_plan import AnsweredWindows

        slots = [datetime(2026, 1, 2, h, 0, tzinfo=UTC) for h in range(15, 19)]
        # 15:00 stored; the provider answered [16:00, 18:00) with nothing for 16:00 and 17:00.
        answered = AnsweredWindows.from_rows(
            [(datetime(2026, 1, 2, 16, 0, tzinfo=UTC), datetime(2026, 1, 2, 18, 0, tzinfo=UTC))]
        )
        with patch(
            "scripts.infrastructure.backfill._history_fetch" ".expected_grid_slots",
            return_value=slots,
        ):
            gaps = detect_gaps(
                self._mock_conn([(datetime(2026, 1, 2, 15, 0, tzinfo=UTC),)]),
                "SPY",
                "1h",
                datetime(2026, 1, 2, 15, 0, tzinfo=UTC),
                datetime(2026, 1, 2, 18, 0, tzinfo=UTC),
                "nyse",
                "NYSE",
                answered=answered,
                vendor="ibkr",
            )
        # Only the 18:00 slot lies outside the answered window and has no bar.
        assert gaps == [
            (datetime(2026, 1, 2, 18, 0, tzinfo=UTC), datetime(2026, 1, 2, 18, 0, tzinfo=UTC))
        ]

    def test_genuine_intraday_gap_detected(self):
        from scripts.infrastructure.backfill._history_fetch import (
            detect_gaps,
        )

        slots = [datetime(2026, 1, 2, h, 0, tzinfo=UTC) for h in range(15, 19)]
        mock_conn = self._mock_conn(
            [(datetime(2026, 1, 2, 15, 0, tzinfo=UTC),), (datetime(2026, 1, 2, 18, 0, tzinfo=UTC),)]
        )
        with patch(
            "scripts.infrastructure.backfill._history_fetch" ".expected_grid_slots",
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
                vendor="ibkr",
            )
        assert len(gaps) == 1
        assert gaps[0] == (
            datetime(2026, 1, 2, 16, 0, tzinfo=UTC),
            datetime(2026, 1, 2, 17, 0, tzinfo=UTC),
        )


class TestLoadIbkrVenueFallbackConfig:
    """todo 433: _load_ibkr_venue_fallback_config() overlays infra.ibkr.venue_fallback.*
    (migration 374) onto ibkr's module-level constants in place."""

    def test_overlays_keys_and_restores(self):
        from scripts.infrastructure.backfill._history_fetch import (
            _load_ibkr_venue_fallback_config,
        )
        from src.providers import ibkr

        saved = (
            ibkr._VENUE_FALLBACK_EXCHANGES,
            ibkr._VENUE_FALLBACK_TIMEFRAMES,
            ibkr._VENUE_FALLBACK_MIN_GAP_DAYS,
            ibkr._VENUE_FALLBACK_STORE_BARS,
        )
        try:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            mock_cursor.fetchall.return_value = [
                ("infra.ibkr.venue_fallback.exchanges", '["NYSE", "ARCA"]'),
                ("infra.ibkr.venue_fallback.timeframes", '["1d", "1h"]'),
                ("infra.ibkr.venue_fallback.min_gap_days", "10"),
                ("infra.ibkr.venue_fallback.store_bars", "true"),
            ]
            with patch(
                "scripts.infrastructure.backfill._history_fetch.connect_db",
                return_value=mock_conn,
            ):
                _load_ibkr_venue_fallback_config(MagicMock())
            assert ibkr._VENUE_FALLBACK_EXCHANGES == ["NYSE", "ARCA"]
            assert ibkr._VENUE_FALLBACK_TIMEFRAMES == {"1d", "1h"}
            assert ibkr._VENUE_FALLBACK_MIN_GAP_DAYS == 10
            assert ibkr._VENUE_FALLBACK_STORE_BARS is True
        finally:
            (
                ibkr._VENUE_FALLBACK_EXCHANGES,
                ibkr._VENUE_FALLBACK_TIMEFRAMES,
                ibkr._VENUE_FALLBACK_MIN_GAP_DAYS,
                ibkr._VENUE_FALLBACK_STORE_BARS,
            ) = saved


def test_fetch_start_makes_a_full_depth_1d_window_one_request():
    """A 7300-day 1d window must walk in one 7300-day chunk; it used to leave one extra date
    for a second request (todo 433 follow-up, 2026-09-26)."""
    from datetime import UTC, datetime, timedelta

    from scripts.infrastructure.backfill._history_fetch import (
        _fetch_start,
    )

    end = datetime(2026, 9, 26, 11, 5, tzinfo=UTC)
    start = _fetch_start(end, 7300)
    assert start == datetime(2006, 10, 2, tzinfo=UTC)
    chunk_days, n_chunks, chunk_end = 7300, 0, end
    while chunk_end > start:  # the provider walk's chunk arithmetic
        chunk_start = max(chunk_end - timedelta(days=chunk_days - 1), start)
        n_chunks += 1
        chunk_end = chunk_start - timedelta(days=1)
    assert n_chunks == 1


class TestArchiveGridRouting:
    """Plan 12 (D-15/D-06): gap detection expects IBKR's own RTH grid (09:30 partial 1h bar
    then clock hours). Since plan 191-05 there is no archive store path: 15m and 1h are ordinary
    raw rows, and since plan 191-06 the legacy grid difference reads the asking vendor's own
    ohlcv_raw rows for every timeframe."""

    def test_detect_gaps_15m_has_no_archive_branch(self):
        from scripts.infrastructure.backfill._history_fetch import (
            detect_gaps,
        )

        mock_conn, mock_cursor = _make_mock_conn([])
        with patch(
            "scripts.infrastructure.backfill._history_fetch" ".expected_grid_slots",
            return_value=[datetime(2026, 1, 2, 15, 0, tzinfo=UTC)],
        ):
            detect_gaps(
                mock_conn,
                "SPY",
                "15m",
                datetime(2026, 1, 2, 14, 30, tzinfo=UTC),
                datetime(2026, 1, 2, 20, 0, tzinfo=UTC),
                "nyse",
                "NYSE",
                vendor="ibkr",
            )
        sql = mock_cursor.execute.call_args.args[0]
        assert "ohlcv_intraday_raw_archive" not in sql
        assert "FROM ohlcv_raw" in sql

    def test_detect_gaps_reads_only_the_asking_vendors_raw_rows(self):
        from scripts.infrastructure.backfill._history_fetch import (
            detect_gaps,
        )

        mock_conn, mock_cursor = _make_mock_conn([])
        with patch(
            "scripts.infrastructure.backfill._history_fetch" ".expected_grid_slots",
            return_value=[datetime(2026, 1, 2, 15, 0, tzinfo=UTC)],
        ):
            detect_gaps(
                mock_conn,
                "SPY",
                "5m",
                datetime(2026, 1, 2, 14, 30, tzinfo=UTC),
                datetime(2026, 1, 2, 20, 0, tzinfo=UTC),
                "nyse",
                "NYSE",
                vendor="ibkr",
            )
        sql, params = mock_cursor.execute.call_args.args
        assert "FROM ohlcv_raw" in sql and "market_data_ohlcv" not in sql
        assert "vendor = %s" in sql
        assert params[:3] == ("SPY", "5m", "ibkr")

    def test_1h_nyse_expected_slots_are_ibkrs_rth_grid(self):
        """IBKR serves 1h RTH as a 09:30 (13:30 UTC) partial bar then clock
        hours; the old on-the-hour UTC slot generation never expected 13:30,
        so the 42 names missing it were never refetched (plan 12 must-have)."""
        from scripts.infrastructure.backfill._history_fetch import (
            expected_grid_slots,
        )

        slots = expected_grid_slots(
            "nyse",
            "NYSE",
            "1h",
            datetime(2024, 6, 3, 0, 0, tzinfo=UTC),
            datetime(2024, 6, 3, 23, 59, tzinfo=UTC),
        )
        # The 09:30 bar (13:30 UTC), then clock hours: IBKR never stamps 14:30 .. 19:30.
        assert slots == [datetime(2024, 6, 3, 13, 30, tzinfo=UTC)] + [
            datetime(2024, 6, 3, h, 0, tzinfo=UTC) for h in range(14, 20)
        ]

    def test_15m_nyse_expected_slots_are_session_anchored_quarters(self):
        from scripts.infrastructure.backfill._history_fetch import (
            expected_grid_slots,
        )

        slots = expected_grid_slots(
            "nyse",
            "NYSE",
            "15m",
            datetime(2024, 6, 3, 0, 0, tzinfo=UTC),
            datetime(2024, 6, 3, 23, 59, tzinfo=UTC),
        )
        assert slots[0] == datetime(2024, 6, 3, 13, 30, tzinfo=UTC)
        assert slots[-1] == datetime(2024, 6, 3, 19, 45, tzinfo=UTC)
        assert len(slots) == 26

    def test_non_nyse_1h_still_uses_generate_session_slots(self):
        from scripts.infrastructure.backfill._history_fetch import (
            expected_grid_slots,
        )

        with patch(
            "src.intelligence.bars.gap_plan.generate_session_slots",
            return_value=["slots"],
        ) as mock_slots:
            result = expected_grid_slots(
                "futures_24_5",
                "CME",
                "1h",
                datetime(2026, 1, 2, 0, 0, tzinfo=UTC),
                datetime(2026, 1, 2, 23, 59, tzinfo=UTC),
            )
        assert result == ["slots"]
        assert mock_slots.call_count == 1

    def test_missing_1330_slot_is_detected_as_a_gap(self):
        """The 42 names whose 09:30 1h bar is missing: with the RTH grid the
        absent 13:30 slot is a gap and gets refetched (into the archive)."""
        from scripts.infrastructure.backfill._history_fetch import (
            detect_gaps,
        )

        stored = [(datetime(2024, 6, 3, h, 0, tzinfo=UTC),) for h in range(14, 20)]
        mock_conn = self._mock_conn_for(stored)
        gaps = detect_gaps(
            mock_conn,
            "SPY",
            "1h",
            datetime(2024, 6, 3, 13, 30, tzinfo=UTC),
            datetime(2024, 6, 3, 20, 0, tzinfo=UTC),
            "nyse",
            "NYSE",
            vendor="ibkr",
        )
        assert gaps == [
            (datetime(2024, 6, 3, 13, 30, tzinfo=UTC), datetime(2024, 6, 3, 13, 30, tzinfo=UTC))
        ]

    @staticmethod
    def _mock_conn_for(fetchall_result):
        mock_conn, _ = _make_mock_conn(fetchall_result)
        return mock_conn


def test_the_interim_flag_and_module_are_gone():
    """Plan 185-18 task 1a acceptance, CI-enforced: no --real-bars-only flag and
    no _request_coverage reference survive in the helper library, and the interim
    module and its test are deleted (AnsweredWindows lives in gap_plan.py)."""
    source = Path("scripts/infrastructure/backfill/_history_fetch.py").read_text()
    assert "real-bars-only" not in source
    assert "_request_coverage" not in source
    assert not Path("scripts/infrastructure/backfill/_request_coverage.py").exists()
    assert not Path("tests/unit/scripts/test_request_coverage.py").exists()


def test_the_pipeline_cli_lease_and_legacy_ranking_are_gone():
    """Plan 189-08: the former historical pipeline is a helper library. No CLI (main,
    argparse), no ibkr_history_stream lease, no legacy gap ranking (the queue's
    coverage_gap_days replaced it), no backfill_status writer, and no normalize pass
    (plan 185-32). ohlcv_history_fetcher.py is the only IBKR history CLI."""
    from scripts.infrastructure.backfill import _history_fetch as hf

    for name in (
        "main",
        "IBKR_HISTORY_LEASE",
        "EXIT_LEASE_TIMEOUT",
        "_acquire_history_lease",
        "_lease_wait_seconds",
        "_reorder_contracts_by_gap",
        "mark_fetch_complete",
        "run_normalize",
        "normalize_bars",
        "_run_daily_stage",
    ):
        assert not hasattr(hf, name), name
    source = Path("scripts/infrastructure/backfill/_history_fetch.py").read_text()
    for token in ("argparse", "ResourceLease", "ibkr_history_stream", "__main__"):
        assert token not in source, token


def test_store_bars_refuses_1d():
    """Ported from the retired d1-capture test file (plan 189-08). store_bars is the
    fence behind the D1-only path: a forgotten 1d caller fails loudly instead of silently
    writing a non-canonical grid row."""
    from scripts.infrastructure.backfill._history_fetch import store_bars

    bar = {
        "timestamp": datetime(2024, 1, 2, tzinfo=UTC),
        "open": 1.0,
        "high": 1.0,
        "low": 1.0,
        "close": 1.0,
        "volume": 1,
    }
    with pytest.raises(RuntimeError, match="1d"):
        store_bars(MagicMock(), [bar], "SPY", "1d")


class TestCaptureKwargs:
    """Every timeframe reports its requests to the fetch ledger sink; the 1d caller adds its own
    on_observation (the persister's), because only a daily answer's request carries the route and
    what_to_show that decide its raw kind (plan 191-05)."""

    _RUN_ID = "00000000-0000-4000-8000-000000000189"

    def test_requests_and_the_run_id_only(self):
        from scripts.infrastructure.backfill._history_fetch import _capture_kwargs

        sink = MagicMock()
        kwargs = _capture_kwargs(sink, self._RUN_ID)
        assert kwargs == {"on_request": sink.on_request, "fetch_run_id": self._RUN_ID}
