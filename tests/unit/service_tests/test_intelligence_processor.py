"""Tests for the Intelligence Processor Service.

Unit tests that exercise service initialization, config loading, bar decoding,
the full I1→I3→I4→I5 calculation pipeline, and graceful shutdown — all without
requiring Redis or any other infrastructure.
"""

from collections import deque
from datetime import datetime
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest

from src.intelligence.plugins import registry
from src.intelligence.register_plugins import register_all_plugins


def _make_bar_history(n: int = 150) -> deque:
    """Build a synthetic bar history deque with realistic price action."""
    rng = np.random.default_rng(42)
    close = 5000.0 + np.cumsum(rng.normal(0, 2, n))
    spread = np.abs(close) * 0.002
    high = close + spread
    low = close - spread
    open_ = close + rng.normal(0, 0.5, n)
    high = np.maximum(high, np.maximum(open_, close))
    low = np.minimum(low, np.minimum(open_, close))
    volume = rng.integers(500, 5000, n).astype(float)

    history: deque = deque(maxlen=200)
    base_ts = datetime(2026, 2, 10, 9, 30, 0)
    for i in range(n):
        history.append(
            {
                "timestamp": base_ts.replace(minute=30 + i % 30, second=i % 60),
                "open": float(open_[i]),
                "high": float(high[i]),
                "low": float(low[i]),
                "close": float(close[i]),
                "volume": int(volume[i]),
            }
        )
    return history


def _get_service(config_file: str | None = None):
    """Instantiate the service with mocked signal handlers."""
    with patch("services.intelligence_processor_service.signal.signal"):
        from services.intelligence_processor_service import IntelligenceProcessorService

        return IntelligenceProcessorService(config_file)


class TestServiceInitialization:
    def test_defaults(self):
        svc = _get_service()
        assert svc.running is False
        assert svc.shutdown_requested is False
        assert svc.consumer_group.startswith("intelligence_processor_")
        assert len(svc.bar_history) == 0

    def test_config_structure(self):
        svc = _get_service()
        assert "redis" in svc.config
        assert "service" in svc.config
        assert "logging" in svc.config
        assert isinstance(svc.config["service"]["symbols"], list)
        assert isinstance(svc.config["service"]["timeframes"], list)
        assert svc.config["service"]["min_history_bars"] == 120


class TestBarProcessing:
    @pytest.mark.asyncio
    async def test_bar_decode_and_history(self):
        svc = _get_service()
        svc.redis_client = AsyncMock()

        fields = {
            b"timestamp": b"2026-02-10T10:00:00",
            b"open": b"5000.0",
            b"high": b"5010.0",
            b"low": b"4990.0",
            b"close": b"5005.0",
            b"volume": b"1234",
        }

        await svc._process_single_bar("ESU5", "1m", fields, "test_stream", b"1-0")

        key = "ESU5:1m"
        assert len(svc.bar_history[key]) == 1
        bar = svc.bar_history[key][0]
        assert bar["close"] == 5005.0
        assert bar["volume"] == 1234
        assert svc._total_bars == 1
        svc.redis_client.xack.assert_called_once()


class TestIntelligenceCalculation:
    @pytest.mark.asyncio
    async def test_insufficient_history_skips(self):
        svc = _get_service()
        svc.bar_history["ESU5:1m"] = deque(maxlen=200)
        for i in range(10):
            svc.bar_history["ESU5:1m"].append(
                {
                    "timestamp": datetime(2026, 2, 10, 10, i),
                    "open": 5000.0,
                    "high": 5010.0,
                    "low": 4990.0,
                    "close": 5000.0,
                    "volume": 1000,
                }
            )

        result = await svc._calculate_intelligence("ESU5", "1m", datetime.now())
        assert result == {}

    @pytest.mark.asyncio
    async def test_produces_output(self):
        svc = _get_service()
        svc.bar_history["ESU5:1m"] = _make_bar_history(150)

        result = await svc._calculate_intelligence("ESU5", "1m", datetime.now())

        assert isinstance(result, dict)
        assert len(result) > 0
        # I3 outputs
        assert "swing_high" in result
        assert "trend_direction" in result
        assert "trend_strength" in result
        # I4 outputs
        assert "vol_regime" in result
        assert "trend_regime" in result
        # I5 outputs
        assert "rsi_div_bullish" in result
        assert "confluence_score" in result

    @pytest.mark.asyncio
    async def test_feature_accumulation_across_tiers(self):
        """I3 outputs appear in features before I4 runs."""
        svc = _get_service()
        svc.bar_history["ESU5:1m"] = _make_bar_history(150)

        result = await svc._calculate_intelligence("ESU5", "1m", datetime.now())

        # trend_direction from I3 should have been visible to I4 TrendRegime
        # We verify this indirectly: TrendRegime produces trend_confidence,
        # which uses I3 blending when trend_direction is present.
        assert "trend_confidence" in result
        assert isinstance(result["trend_confidence"], float)


class TestPluginRegistration:
    def test_plugin_lists_match_registry(self):
        """All plugin names in I1/I3/I4/I5 lists exist in the registry."""
        register_all_plugins()

        from services.intelligence_processor_service import (
            I1_PLUGINS,
            I3_PLUGINS,
            I4_PLUGINS,
            I5_PLUGINS,
        )

        registered_indicators = set(registry.list_indicators())
        registered_patterns = set(registry.list_patterns())

        for name in I1_PLUGINS:
            assert name in registered_indicators, f"I1 plugin {name!r} not in registry"

        for name in I3_PLUGINS + I4_PLUGINS + I5_PLUGINS:
            assert name in registered_patterns, f"Pattern plugin {name!r} not in registry"


class TestGracefulShutdown:
    @pytest.mark.asyncio
    async def test_stop_sets_flags(self):
        svc = _get_service()
        svc.redis_client = AsyncMock()

        await svc.stop()

        assert svc.running is False
        assert svc.shutdown_requested is True
        svc.redis_client.aclose.assert_called_once()
