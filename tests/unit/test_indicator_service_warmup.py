"""Tests for indicator service warmup dedup + TF-aware min_history logic."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from unittest.mock import MagicMock, patch


def _make_service():
    with patch("services.indicator_service.start_metrics_server"), \
         patch("services.indicator_service.counter", return_value=MagicMock(inc=MagicMock())), \
         patch("services.indicator_service.gauge", return_value=MagicMock(set=MagicMock())), \
         patch("services.indicator_service.get_active_contracts", return_value=["ESH6"]), \
         patch("services.indicator_service.Settings"):
        from services.indicator_service import IndicatorService
        svc = IndicatorService.__new__(IndicatorService)
        svc.config = {
            "service": {
                "symbols": ["ESH6"],
                "timeframes": ["1m", "5m", "15m", "1h", "4h", "1d"],
                "min_history_bars": 120,
                "processing_interval": 0.1,
            }
        }
        svc.bar_history = {}
        svc._bar_history_max = 200
        return svc


def test_min_bars_for_tf_returns_120_for_1m():
    svc = _make_service()
    assert svc._min_bars_for_tf("1m") == 120


def test_min_bars_for_tf_returns_26_for_5m():
    svc = _make_service()
    assert svc._min_bars_for_tf("5m") == 26


def test_min_bars_for_tf_returns_26_for_1h():
    svc = _make_service()
    assert svc._min_bars_for_tf("1h") == 26


def test_min_bars_for_tf_returns_26_for_1d():
    svc = _make_service()
    assert svc._min_bars_for_tf("1d") == 26


def test_warmup_read_multiplier_is_5x():
    svc = _make_service()
    assert svc._WARMUP_READ_MULTIPLIER == 5


def test_stochastic_accepts_all_timeframes():
    from src.intelligence.indicators.stochastic import StochasticPlugin
    plugin = StochasticPlugin()
    for spec in plugin.inputs:
        assert spec.timeframe != "1m", (
            "Stochastic InputSpec has hardcoded timeframe='1m'; "
            "should be '.*' to work on all timeframes"
        )
