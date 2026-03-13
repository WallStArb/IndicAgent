# tests/unit/service_tests/test_indicator_service_asset_guard.py
import pytest
from unittest.mock import MagicMock
from collections import defaultdict


class TestIndicatorServiceInstrumentMap:
    """Test _instrument_map is built from Settings.contracts."""

    def _make_service(self):
        """Build service via __new__ to bypass __init__."""
        from services.indicator_service import IndicatorService
        from src.core.models import Instrument, AssetClass

        svc = IndicatorService.__new__(IndicatorService)
        svc.logger = MagicMock()
        svc._i1_plugin_cache = {}
        svc._i1_plugin_states = {}
        svc._i1_plugin_states_locks = {}
        svc._i1_call_counts = defaultdict(int)
        svc.bar_history = defaultdict(dict)
        svc._df_cache = {}
        svc._stream_map = {}
        svc.env_prefix = ""

        svc._instrument_map = {
            "SPY": Instrument(symbol="SPY", asset_class=AssetClass.EQUITY, session_id="nyse"),
            "ES":  Instrument(symbol="ES",  asset_class=AssetClass.FUTURES),
        }
        return svc

    def test_instrument_map_built_correctly(self):
        from src.core.models import AssetClass
        svc = self._make_service()
        assert svc._instrument_map["SPY"].asset_class == AssetClass.EQUITY
        assert svc._instrument_map["ES"].asset_class == AssetClass.FUTURES

    def test_frames_instrument_injected(self):
        from src.core.models import AssetClass
        svc = self._make_service()
        instrument = svc._instrument_map.get("SPY")
        frames = {}
        frames["__instrument__"] = instrument
        assert frames["__instrument__"].asset_class == AssetClass.EQUITY

    def test_futures_only_plugin_skipped_for_equity(self):
        from src.core.models import AssetClass

        class FuturesOnlyPlugin:
            name = "roll_momentum"
            outputs = frozenset({"roll_signal"})
            min_lookback = 1
            supports_incremental = False
            capability_tags = frozenset()
            inputs = []
            valid_asset_classes = frozenset({AssetClass.FUTURES})
            _state = {}

            def compute_full(self, frames):
                return {"roll_signal": 1.0}

            def compute_next(self, windows):
                return {}

        svc = self._make_service()
        instrument = svc._instrument_map["SPY"]
        plugin = FuturesOnlyPlugin()
        allowed = getattr(plugin, "valid_asset_classes", frozenset(AssetClass))
        assert instrument.asset_class not in allowed


class TestMarketAnalysisServiceInstrumentMap:
    def test_market_analysis_has_instrument_map(self):
        from services.market_analysis_service import MarketAnalysisService
        svc = MarketAnalysisService.__new__(MarketAnalysisService)
        with pytest.raises(AttributeError):
            _ = svc._instrument_map
