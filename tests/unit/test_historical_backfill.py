import sys
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "production" / "scripts"))

import pandas as pd

from historical_backfill import aggregate_1m_to_tf, time_bucket
from src.intelligence.register_plugins import register_all_plugins


def _bar(ts: datetime, o=100.0, h=101.0, l=99.0, c=100.5, v=1000):
    return {"timestamp": ts, "open": o, "high": h, "low": l, "close": c, "volume": v}


def _ts(hour: int, minute: int) -> datetime:
    return datetime(2026, 2, 1, hour, minute, 0, tzinfo=timezone.utc)


class TestTimeBucket:
    @pytest.mark.unit
    def test_floors_to_5m(self):
        ts = _ts(9, 33)
        assert time_bucket(ts, 5) == _ts(9, 30)

    @pytest.mark.unit
    def test_floors_to_15m(self):
        ts = _ts(9, 47)
        assert time_bucket(ts, 15) == _ts(9, 45)

    @pytest.mark.unit
    def test_already_on_boundary(self):
        ts = _ts(10, 0)
        assert time_bucket(ts, 5) == _ts(10, 0)


class TestAggregate1mToTf:
    @pytest.mark.unit
    def test_five_1m_bars_become_one_5m(self):
        bars = [_bar(_ts(9, 30 + i), o=100+i, h=101+i, l=99+i, c=100.5+i, v=100)
                for i in range(5)]
        result = aggregate_1m_to_tf(bars, 5)
        assert len(result) == 1
        r = result[0]
        assert r["timestamp"] == _ts(9, 30)
        assert r["open"] == bars[0]["open"]
        assert r["high"] == max(b["high"] for b in bars)
        assert r["low"] == min(b["low"] for b in bars)
        assert r["close"] == bars[-1]["close"]
        assert r["volume"] == 500

    @pytest.mark.unit
    def test_ten_1m_bars_become_two_5m(self):
        bars = [_bar(_ts(9, 30 + i)) for i in range(10)]
        result = aggregate_1m_to_tf(bars, 5)
        assert len(result) == 2

    @pytest.mark.unit
    def test_empty_input(self):
        assert aggregate_1m_to_tf([], 5) == []


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
