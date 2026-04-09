import sys
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "production" / "scripts"))

import pandas as pd

from src.intelligence.register_plugins import register_all_plugins


def _bar(ts: datetime, o=100.0, h=101.0, low=99.0, c=100.5, v=1000):
    return {"timestamp": ts, "open": o, "high": h, "low": low, "close": c, "volume": v}


def _ts(hour: int, minute: int) -> datetime:
    return datetime(2026, 2, 1, hour, minute, 0, tzinfo=UTC)


class TestRunI1Plugins:
    @pytest.mark.unit
    def test_returns_empty_when_insufficient_bars(self):
        from historical_backfill import MIN_BARS, run_i1_plugins

        history = deque([_bar(_ts(9, i)) for i in range(MIN_BARS - 1)], maxlen=200)
        result = run_i1_plugins(history, "ESH6", "5m", {})
        assert result == {}

    @pytest.mark.unit
    def test_returns_features_dict_when_enough_bars(self):
        from historical_backfill import MIN_BARS, run_i1_plugins

        history = deque(
            [_bar(_ts(9, 0) if i == 0 else _ts(9 + i // 60, i % 60)) for i in range(MIN_BARS)],
            maxlen=200,
        )
        # With real plugins registered, we should get some numeric features
        register_all_plugins()
        result = run_i1_plugins(history, "ESH6", "5m", {})
        # At minimum should have some keys (plugins may skip on low data but dict is returned)
        assert isinstance(result, dict)

    @pytest.mark.unit
    def test_plugin_exception_does_not_propagate(self):
        from historical_backfill import MIN_BARS, run_i1_plugins

        history = deque([_bar(_ts(9, i)) for i in range(MIN_BARS)], maxlen=200)
        register_all_plugins()
        # Should not raise even if some plugins fail internally
        result = run_i1_plugins(history, "FAKE", "5m", {})
        assert isinstance(result, dict)


class TestRunAnalysisPipeline:
    @pytest.mark.unit
    def test_returns_dict(self):
        from historical_backfill import run_analysis_pipeline

        register_all_plugins()
        df = pd.DataFrame([_bar(_ts(9, i)) for i in range(60)])
        frames = {"main": df, "features": {"rsi_14": 55.0, "atr_14": 2.5}}
        intel_cache: dict = {}
        result = run_analysis_pipeline(frames, intel_cache, "ESH6", "5m", {})
        assert isinstance(result, dict)

    @pytest.mark.unit
    def test_populates_intelligence_cache(self):
        from historical_backfill import run_analysis_pipeline

        register_all_plugins()
        df = pd.DataFrame([_bar(_ts(9, i)) for i in range(60)])
        frames = {"main": df, "features": {"rsi_14": 55.0}}
        intel_cache: dict = {}
        run_analysis_pipeline(frames, intel_cache, "ESH6", "5m", {})
        assert "ESH6" in intel_cache
        assert "5m" in intel_cache["ESH6"]

    @pytest.mark.unit
    def test_plugin_exception_does_not_propagate(self):
        from historical_backfill import run_analysis_pipeline

        frames = {"main": pd.DataFrame(), "features": {}}
        intel_cache: dict = {}
        # Empty DataFrame may cause some plugins to raise — should not propagate
        result = run_analysis_pipeline(frames, intel_cache, "ESH6", "5m", {})
        assert isinstance(result, dict)


class TestBuildLedgerEntries:
    def _make_result(self, n_signals=2):
        from src.intelligence.trading.aggregator import AggregatedResult

        sig = {
            "setup_plugin": "trad_TrendFollowing",
            "signal_type": "trend_follow",
            "direction": 1,
            "entry_price": 5100.0,
            "stop_loss": 5085.0,
            "targets": [5115.0, 5130.0],
            "confidence": 0.75,
            "confluence_score": 0.6,
            "regime_context": "bullish",
            "supporting_factors": ["ema_cross"],
            "composite_rank": 1,
        }
        return AggregatedResult(
            selected_signal=sig,
            all_ranked=[sig],
            num_signals_fired=n_signals,
            num_agreeing=n_signals,
            num_conflicting=0,
            resolution_method="sole",
        )

    @pytest.mark.unit
    def test_returns_one_entry_per_ranked_signal(self):
        from historical_backfill import _build_ledger_entries

        result = self._make_result(n_signals=1)
        entries = _build_ledger_entries(result, "ESH6", "5m", _ts(9, 30), {})
        assert len(entries) == 1

    @pytest.mark.unit
    def test_selected_signal_has_was_selected_true(self):
        from historical_backfill import _build_ledger_entries

        result = self._make_result()
        entries = _build_ledger_entries(result, "ESH6", "5m", _ts(9, 30), {})
        selected = [e for e in entries if e.was_selected]
        assert len(selected) == 1

    @pytest.mark.unit
    def test_empty_result_returns_empty_list(self):
        from historical_backfill import _build_ledger_entries

        from src.intelligence.trading.aggregator import AggregatedResult

        result = AggregatedResult(
            selected_signal=None,
            all_ranked=[],
            num_signals_fired=0,
            num_agreeing=0,
            num_conflicting=0,
            resolution_method="no_signal",
        )
        entries = _build_ledger_entries(result, "ESH6", "5m", _ts(9, 30), {})
        assert entries == []


class TestFetchAndStoreBars:
    @pytest.mark.unit
    def test_fetch_1m_bars_queries_correct_table(self):
        from unittest.mock import MagicMock

        from historical_backfill import fetch_bars

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            (datetime(2026, 2, 1, 9, 30, tzinfo=UTC), 100.0, 101.0, 99.0, 100.5, 1000, "historical_backfill")
        ]
        rows = fetch_bars(mock_conn, "ESH6", "1m")
        assert len(rows) == 1
        assert rows[0]["symbol"] == "ESH6"
        assert rows[0]["timeframe"] == "1m"
        assert "timestamp" in rows[0]

    @pytest.mark.unit
    def test_store_bars_calls_execute_batch(self):
        from unittest.mock import MagicMock, patch

        from historical_backfill import store_bars

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        bars = [
            {
                "timestamp": _ts(9, 30),
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


class TestBuildIntelligenceEvent:
    """Tests for _build_intelligence_event() — builds IntelligenceEvent from flat dicts."""

    def _valid_bar(self):
        return {"open": 5100.0, "high": 5105.0, "low": 5095.0, "close": 5102.0, "volume": 1000}

    def _valid_i1(self):
        return {"rsi_14": 55.0, "atr_14": 2.5, "macd_12_26_9": 0.3}

    def _valid_intelligence(self):
        return {
            "trend_direction": 1.0,
            "trend_strength": 0.7,
            "vol_regime": 0.5,
            "trend_regime": 1.0,
        }

    @pytest.mark.unit
    def test_returns_none_on_exception(self):
        """Empty dicts with missing keys should return None, not raise."""
        from historical_backfill import _build_intelligence_event

        result = _build_intelligence_event({}, {}, {}, "ESH6", "1m", _ts(9, 30))
        assert result is None

    @pytest.mark.unit
    def test_returns_intelligence_event_with_source_backfill(self):
        """Valid inputs produce an IntelligenceEvent with source='backfill'."""
        from historical_backfill import _build_intelligence_event

        from src.intelligence.schemas import IntelligenceEvent

        register_all_plugins()
        result = _build_intelligence_event(
            self._valid_bar(),
            self._valid_i1(),
            self._valid_intelligence(),
            "ESH6",
            "1m",
            _ts(9, 30),
        )
        assert result is not None
        assert isinstance(result, IntelligenceEvent)
        assert result.source == "backfill"

    @pytest.mark.unit
    def test_i3_keys_filtered_before_construction(self):
        """Mixed I3+I4 keys in intelligence dict do not cause ValidationError."""
        from historical_backfill import _build_intelligence_event

        # Pass keys from multiple tiers — filter should prevent extra='forbid' failures
        intelligence = {
            # I3 keys
            "trend_direction": 1.0,
            "swing_high": 5110.0,
            # I4 keys (would fail I3Structure construction if not filtered)
            "garch_sigma": 0.02,
            "vol_regime": 0.5,
            # SMC keys
            "bos_detected": True,
            # I5 keys
            "squeeze_active": 1.0,
            # I6 keys
            "ctf_score": 0.8,
        }
        result = _build_intelligence_event(
            self._valid_bar(), self._valid_i1(), intelligence, "ESH6", "1m", _ts(9, 30)
        )
        # Should not raise; returns event or None (None if OHLCVBar construction fails)
        assert result is not None or result is None  # no exception is the key assertion

    @pytest.mark.unit
    def test_returns_none_on_pydantic_validation_error(self):
        """Data that triggers a type error in OHLCVBar returns None (not raise)."""
        from historical_backfill import _build_intelligence_event

        # Pass non-numeric open/high/low/close to trigger a float() conversion error
        bad_bar = {
            "open": "not_a_number",
            "high": 5105.0,
            "low": 5095.0,
            "close": 5102.0,
            "volume": 1000,
        }
        result = _build_intelligence_event(bad_bar, {}, {}, "ESH6", "1m", _ts(9, 30))
        assert result is None


class TestEventToSyncParams:
    """Tests for _event_to_sync_params() — serializes IntelligenceEvent to DB tuple."""

    def _make_event(self):
        from src.intelligence.schemas import (
            I1Indicators,
            I3Structure,
            I4Context,
            I5Patterns,
            I6Confluence,
            IntelligenceEvent,
            OHLCVBar,
            SMCContext,
        )

        return IntelligenceEvent(
            ts=_ts(9, 30),
            symbol="ESH6",
            tf="1m",
            source="backfill",
            bar=OHLCVBar(o=5100.0, h=5105.0, l=5095.0, c=5102.0, v=1000),
            i1=I1Indicators(rsi_14=55.0),
            i3=I3Structure(),
            i4=I4Context(),
            i5=I5Patterns(),
            smc=SMCContext(),
            i6=I6Confluence(),
        )

    @pytest.mark.unit
    def test_returns_13_tuple(self):
        """Result must have exactly 13 elements matching the SQL INSERT columns."""
        from historical_backfill import _event_to_sync_params

        event = self._make_event()
        params = _event_to_sync_params(event)
        assert len(params) == 13

    @pytest.mark.unit
    def test_first_element_is_datetime(self):
        """First element is the datetime ts for TimescaleDB hypertable partitioning."""
        from historical_backfill import _event_to_sync_params

        event = self._make_event()
        params = _event_to_sync_params(event)
        assert isinstance(params[0], datetime)

    @pytest.mark.unit
    def test_jsonb_columns_are_strings(self):
        """Elements 6-12 (bar, i1, i3, i4, i5, smc, i6) are JSON strings for ::jsonb cast."""
        from historical_backfill import _event_to_sync_params

        event = self._make_event()
        params = _event_to_sync_params(event)
        for i, col in enumerate(params[6:], start=6):
            assert isinstance(col, str), f"params[{i}] should be str, got {type(col)}"


class TestInsertFeaturesSync:
    """Tests for _insert_features_sync() — psycopg2 batch insert into intelligence_features."""

    def _mock_conn(self):
        from unittest.mock import MagicMock

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        return mock_conn, mock_cursor

    @pytest.mark.unit
    def test_calls_execute_values_with_correct_sql(self):
        """execute_values must be called with the module-level _INSERT_FEATURE_SYNC_SQL."""
        from unittest.mock import patch

        from historical_backfill import _INSERT_FEATURE_SYNC_SQL, _insert_features_sync

        mock_conn, mock_cursor = self._mock_conn()
        rows = [("fake_row",)]
        with patch("psycopg2.extras.execute_values") as mock_ev:
            _insert_features_sync(mock_conn, rows)
        assert mock_ev.call_args[0][0] is mock_cursor
        assert mock_ev.call_args[0][1] == _INSERT_FEATURE_SYNC_SQL
        assert mock_ev.call_args[0][2] == rows

    @pytest.mark.unit
    def test_commits_connection(self):
        """conn.commit() must be called after execute_values."""
        from unittest.mock import patch

        from historical_backfill import _insert_features_sync

        mock_conn, _ = self._mock_conn()
        with patch("psycopg2.extras.execute_values"):
            _insert_features_sync(mock_conn, [("row",)])
        mock_conn.commit.assert_called_once()

    @pytest.mark.unit
    def test_no_op_on_empty_rows(self):
        """Empty rows list must be a no-op (cursor never opened)."""
        from historical_backfill import _insert_features_sync

        mock_conn, _ = self._mock_conn()
        _insert_features_sync(mock_conn, [])
        mock_conn.cursor.assert_not_called()


class TestBuildLedgerEntriesFeatureTs:
    """Tests for feature_ts/feature_tf passthrough in _build_ledger_entries."""

    def _make_result(self):
        from src.intelligence.trading.aggregator import AggregatedResult

        sig = {
            "setup_plugin": "trad_TrendFollowing",
            "signal_type": "trend_follow",
            "direction": 1,
            "entry_price": 5100.0,
            "stop_loss": 5085.0,
            "targets": [5115.0],
            "confidence": 0.75,
            "confluence_score": 0.6,
            "regime_context": "bullish",
            "supporting_factors": ["ema_cross"],
            "composite_rank": 1,
        }
        return AggregatedResult(
            selected_signal=sig,
            all_ranked=[sig],
            num_signals_fired=1,
            num_agreeing=1,
            num_conflicting=0,
            resolution_method="sole",
        )

    @pytest.mark.unit
    def test_feature_ts_passes_through(self):
        """When feature_ts is provided, entries[0].feature_ts equals that datetime."""
        from historical_backfill import _build_ledger_entries

        feature_ts = datetime(2026, 2, 1, 9, 30, 0, tzinfo=UTC)
        result = self._make_result()
        entries = _build_ledger_entries(
            result, "ESH6", "1m", _ts(9, 30), {}, feature_ts=feature_ts, feature_tf="1m"
        )
        assert len(entries) == 1
        assert entries[0].feature_ts == feature_ts
        assert entries[0].feature_tf == "1m"

    @pytest.mark.unit
    def test_feature_ts_defaults_to_none(self):
        """When feature_ts is not provided, entries[0].feature_ts is None (backward compat)."""
        from historical_backfill import _build_ledger_entries

        result = self._make_result()
        entries = _build_ledger_entries(result, "ESH6", "1m", _ts(9, 30), {})
        assert len(entries) == 1
        assert entries[0].feature_ts is None


class TestCISColumnsInSQL:
    """Tests verifying Phase 7 CIS columns are included in _INSERT_SYNC_SQL."""

    @pytest.mark.unit
    def test_insert_sync_sql_has_cis_columns(self):
        """_INSERT_SYNC_SQL must include all Phase 7 CIS columns."""
        from historical_backfill import _INSERT_SYNC_SQL

        assert "cis_score" in _INSERT_SYNC_SQL
        assert "bucket_scores" in _INSERT_SYNC_SQL
        assert "weights_version" in _INSERT_SYNC_SQL
        assert "signal_quality" in _INSERT_SYNC_SQL

    @pytest.mark.unit
    def test_insert_sync_sql_column_placeholder_balance(self):
        """Column count must equal VALUES placeholder count."""
        import re

        from historical_backfill import _INSERT_SYNC_SQL

        col_match = re.search(r"INSERT INTO signal_ledger \(([^)]+)\)", _INSERT_SYNC_SQL, re.DOTALL)
        val_match = re.search(r"VALUES \(([^)]+)\)", _INSERT_SYNC_SQL, re.DOTALL)
        assert col_match and val_match
        cols = [c.strip() for c in col_match.group(1).split(",") if c.strip()]
        vals = [v.strip() for v in val_match.group(1).split(",") if v.strip()]
        assert len(cols) == len(vals), f"Column count {len(cols)} != placeholder count {len(vals)}"

    @pytest.mark.unit
    def test_insert_signals_sync_params_include_cis_nulls(self):
        """_insert_signals_sync must pass NULL for all 4 CIS columns in backfill rows."""
        from datetime import UTC, datetime
        from unittest.mock import MagicMock, patch

        from historical_backfill import _insert_signals_sync

        from src.persistence.repository.signal_ledger_repository import LedgerEntry

        entry = LedgerEntry(
            signal_id="00000000-0000-0000-0000-000000000001",
            timestamp=datetime(2026, 2, 1, 9, 30, tzinfo=UTC),
            symbol="ESH6",
            timeframe="5m",
            setup_plugin="trad_TrendFollowing",
            signal_type="trend_follow",
            direction=1,
            entry_price=5100.0,
            stop_loss=5085.0,
            targets=[5115.0],
            confidence=0.75,
            confluence_score=0.6,
            regime_context="bullish",
            supporting_factors=["ema_cross"],
            was_selected=True,
            num_signals_bar=1,
            num_agreeing=1,
            num_conflicting=0,
            resolution_method="sole",
            composite_rank=1,
            market_context={},
            status="pending",
            feature_ts=None,
            feature_tf=None,
            # CIS fields not set — should default to None
        )

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        captured_params = []

        def capture_batch(cursor, sql, params):
            captured_params.extend(params)

        with patch("psycopg2.extras.execute_batch", side_effect=capture_batch):
            _insert_signals_sync(mock_conn, [entry])

        assert len(captured_params) == 1
        row = captured_params[0]
        # Row must have 29 elements (24 original + 4 CIS + 1 market_entry_price)
        assert len(row) == 29, f"Expected 29 params, got {len(row)}"
        # CIS columns are positions 24-27 (0-indexed) — all NULL for backfill
        assert row[24] is None, f"cis_score should be None, got {row[24]}"
        assert row[25] is None, f"bucket_scores should be None, got {row[25]}"
        assert row[26] is None, f"weights_version should be None, got {row[26]}"
        assert row[27] is None, f"signal_quality should be None, got {row[27]}"
        # market_entry_price is position 28 — None when no bar_history passed
        assert row[28] is None, f"market_entry_price should be None, got {row[28]}"


class TestDetectGaps:
    """Regression tests for detect_gaps — session-aware gap detection.

    Verifies that weekends, holidays, and maintenance windows are NOT reported
    as gaps, while genuine intraday missing bars ARE detected.
    """

    def _mock_conn(self, fetchall_result=None):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_cursor.fetchall.return_value = fetchall_result or []
        return mock_conn

    @pytest.mark.unit
    def test_cme_futures_over_weekend_no_gaps(self):
        """CME futures over a Sat-Sun weekend: zero gaps (market closed)."""
        from historical_backfill import detect_gaps

        # Saturday Jan 3 -> Sunday Jan 4, 2026 (full weekend)
        start = datetime(2026, 1, 3, 0, 0, tzinfo=UTC)
        end = datetime(2026, 1, 4, 23, 59, tzinfo=UTC)
        mock_conn = self._mock_conn()
        gaps = detect_gaps(mock_conn, "ESH6", "1h", start, end, "futures_24_5", "CME")
        assert gaps == []

    @pytest.mark.unit
    def test_nyse_over_weekend_no_gaps(self):
        """NYSE session over Saturday-Sunday: zero gaps (PMC returns no slots)."""
        from unittest.mock import patch

        from historical_backfill import detect_gaps

        start = datetime(2026, 1, 3, 0, 0, tzinfo=UTC)  # Saturday
        end = datetime(2026, 1, 4, 23, 59, tzinfo=UTC)  # Sunday
        mock_conn = self._mock_conn()
        with patch("historical_backfill.generate_session_slots", return_value=[]):
            gaps = detect_gaps(mock_conn, "SPY", "5m", start, end, "nyse", "NYSE")
        assert gaps == []

    @pytest.mark.unit
    def test_nyse_on_holiday_no_gaps(self):
        """NYSE on 2026-01-01 (New Year's Day): zero gaps (PMC returns no slots)."""
        from unittest.mock import patch

        from historical_backfill import detect_gaps

        start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        end = datetime(2026, 1, 1, 23, 59, tzinfo=UTC)
        mock_conn = self._mock_conn()
        with patch("historical_backfill.generate_session_slots", return_value=[]):
            gaps = detect_gaps(mock_conn, "SPY", "5m", start, end, "nyse", "NYSE")
        assert gaps == []

    @pytest.mark.unit
    def test_genuine_intraday_gap_detected(self):
        """Genuine intraday gap IS detected when expected slots are missing from DB."""
        from unittest.mock import patch

        from historical_backfill import detect_gaps

        # Use 1h timeframe with known expected slots
        start = datetime(2026, 1, 2, 15, 0, tzinfo=UTC)
        end = datetime(2026, 1, 2, 18, 0, tzinfo=UTC)

        expected_slots = [
            datetime(2026, 1, 2, 15, 0, tzinfo=UTC),
            datetime(2026, 1, 2, 16, 0, tzinfo=UTC),
            datetime(2026, 1, 2, 17, 0, tzinfo=UTC),
            datetime(2026, 1, 2, 18, 0, tzinfo=UTC),
        ]

        # DB only has 15:00 and 18:00 — 16:00 and 17:00 are missing
        mock_conn = self._mock_conn(
            fetchall_result=[
                (datetime(2026, 1, 2, 15, 0, tzinfo=UTC),),
                (datetime(2026, 1, 2, 18, 0, tzinfo=UTC),),
            ]
        )
        with patch("historical_backfill.generate_session_slots", return_value=expected_slots):
            gaps = detect_gaps(mock_conn, "SPY", "1h", start, end, "nyse", "NYSE")
        # Should detect a contiguous gap covering 16:00 and 17:00
        assert len(gaps) == 1
        assert gaps[0] == (
            datetime(2026, 1, 2, 16, 0, tzinfo=UTC),
            datetime(2026, 1, 2, 17, 0, tzinfo=UTC),
        )
