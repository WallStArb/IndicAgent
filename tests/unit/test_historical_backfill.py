import sys
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "production" / "scripts"))

import pandas as pd

from src.intelligence.register_plugins import register_all_plugins


def _bar(ts: datetime, o=100.0, h=101.0, l=99.0, c=100.5, v=1000):
    return {"timestamp": ts, "open": o, "high": h, "low": l, "close": c, "volume": v}


def _ts(hour: int, minute: int) -> datetime:
    return datetime(2026, 2, 1, hour, minute, 0, tzinfo=timezone.utc)


class TestRunI1Plugins:
    @pytest.mark.unit
    def test_returns_empty_when_insufficient_bars(self):
        from historical_backfill import run_i1_plugins, MIN_BARS
        history = deque([_bar(_ts(9, i)) for i in range(MIN_BARS - 1)], maxlen=200)
        result = run_i1_plugins(history, "ESH6", "5m")
        assert result == {}

    @pytest.mark.unit
    def test_returns_features_dict_when_enough_bars(self):
        from historical_backfill import run_i1_plugins, MIN_BARS
        history = deque(
            [_bar(_ts(9, 0) if i == 0 else _ts(9 + i // 60, i % 60))
             for i in range(MIN_BARS)],
            maxlen=200
        )
        # With real plugins registered, we should get some numeric features
        register_all_plugins()
        result = run_i1_plugins(history, "ESH6", "5m")
        # At minimum should have some keys (plugins may skip on low data but dict is returned)
        assert isinstance(result, dict)

    @pytest.mark.unit
    def test_plugin_exception_does_not_propagate(self):
        from historical_backfill import run_i1_plugins, MIN_BARS
        history = deque([_bar(_ts(9, i)) for i in range(MIN_BARS)], maxlen=200)
        register_all_plugins()
        # Should not raise even if some plugins fail internally
        result = run_i1_plugins(history, "FAKE", "5m")
        assert isinstance(result, dict)


class TestRunAnalysisPipeline:
    @pytest.mark.unit
    def test_returns_dict(self):
        from historical_backfill import run_analysis_pipeline
        register_all_plugins()
        df = pd.DataFrame([_bar(_ts(9, i)) for i in range(60)])
        frames = {"main": df, "features": {"rsi_14": 55.0, "atr_14": 2.5}}
        intel_cache: dict = {}
        result = run_analysis_pipeline(frames, intel_cache, "ESH6", "5m")
        assert isinstance(result, dict)

    @pytest.mark.unit
    def test_populates_intelligence_cache(self):
        from historical_backfill import run_analysis_pipeline
        register_all_plugins()
        df = pd.DataFrame([_bar(_ts(9, i)) for i in range(60)])
        frames = {"main": df, "features": {"rsi_14": 55.0}}
        intel_cache: dict = {}
        run_analysis_pipeline(frames, intel_cache, "ESH6", "5m")
        assert "ESH6" in intel_cache
        assert "5m" in intel_cache["ESH6"]

    @pytest.mark.unit
    def test_plugin_exception_does_not_propagate(self):
        from historical_backfill import run_analysis_pipeline
        frames = {"main": pd.DataFrame(), "features": {}}
        intel_cache: dict = {}
        # Empty DataFrame may cause some plugins to raise — should not propagate
        result = run_analysis_pipeline(frames, intel_cache, "ESH6", "5m")
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
            selected_signal=None, all_ranked=[], num_signals_fired=0,
            num_agreeing=0, num_conflicting=0, resolution_method="no_signal",
        )
        entries = _build_ledger_entries(result, "ESH6", "5m", _ts(9, 30), {})
        assert entries == []


class TestFetchAndStoreBars:
    @pytest.mark.unit
    def test_fetch_1m_bars_queries_correct_table(self):
        from unittest.mock import MagicMock
        from historical_backfill import fetch_1m_bars
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            (datetime(2026, 2, 1, 9, 30, tzinfo=timezone.utc), 100.0, 101.0, 99.0, 100.5, 1000)
        ]
        rows = fetch_1m_bars(mock_conn, "ESH6", days=1)
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
        bars = [{"timestamp": _ts(9, 30), "open": 100.0, "high": 101.0,
                  "low": 99.0, "close": 100.5, "volume": 1000}]
        with patch("psycopg2.extras.execute_batch"):
            store_bars(mock_conn, bars, symbol="ESH6", timeframe="5m")
        mock_conn.commit.assert_called_once()
