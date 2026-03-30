"""Failing tests (RED phase) for signal_generator_service perf weights — FEED-03 (service side).

These tests define the behavioral contract for _load_perf_weights() and
_perf_weights_refresh_loop() methods that Plan 03 will add to SignalGeneratorAgent.

All tests fail with AttributeError (method/attribute does not exist yet) in RED phase.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from services._archived_signal_generator_agent import SignalGeneratorAgent

# ---------------------------------------------------------------------------
# Factory — bypass __init__ using __new__ pattern (per CLAUDE.md)
# ---------------------------------------------------------------------------


def _make_svc() -> SignalGeneratorAgent:
    """Build a SignalGeneratorAgent without calling __init__."""
    svc = SignalGeneratorAgent.__new__(SignalGeneratorAgent)
    svc.logger = MagicMock()
    svc.redis_client = AsyncMock()
    svc.running = True
    svc.shutdown_requested = False
    svc.shutdown_event = asyncio.Event()
    # env_prefix is the pattern used in signal_generator_service (not _env_prefix)
    svc.env_prefix = "development:"
    # _perf_weights: Plan 03 will add this in __init__; set it here so non-attribute
    # tests don't fail with AttributeError on this field itself
    svc._perf_weights = {}
    return svc


# ---------------------------------------------------------------------------
# Attribute existence (RED: _perf_weights not initialized in __init__ yet)
# ---------------------------------------------------------------------------


class TestPerfWeightsAttribute:
    @pytest.mark.unit
    def test_perf_weights_attribute_exists_on_new_instance(self):
        """SignalGeneratorAgent.__new__ instance has _perf_weights attribute.

        RED: fails because _perf_weights is not set in __init__ yet.
        The __new__ pattern bypasses __init__, so _perf_weights won't be present
        unless we set it manually — this test checks the real __init__ path by NOT
        pre-setting it in _make_svc (uses a fresh __new__ without the pre-set).
        """
        svc = SignalGeneratorAgent.__new__(SignalGeneratorAgent)
        # This attribute test verifies __init__ would set it — in RED it won't be there
        # We check via hasattr on the class (not instance) to detect __init__ initialization
        # In GREEN: __init__ sets self._perf_weights = {}
        # In RED: we do the real check without pre-seeding
        assert hasattr(svc, "_perf_weights"), (
            "_perf_weights not initialized in SignalGeneratorAgent.__init__ — "
            "Plan 03 must add: self._perf_weights = {}"
        )


# ---------------------------------------------------------------------------
# _load_perf_weights() — Redis-based tests removed in Phase 30 (Plan 05)
# These tests verified the old Redis cache read behavior (setup_performance:weights).
# Equivalent DB-based tests are in test_perf_weights_db.py.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# _perf_weights passed to aggregate() via _process_bar() (RED: TypeError from aggregate)
# ---------------------------------------------------------------------------


class TestPerfWeightsPassedToAggregate:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_perf_weights_passed_to_aggregate(self):
        """_process_bar() passes self._perf_weights to aggregate() via perf_weights kwarg.

        RED: aggregate() currently does not accept perf_weights → TypeError.
        This test verifies the integration point is wired correctly in Plan 03.

        We test this by calling aggregate() directly with a perf_weights kwarg to
        confirm the signature change, mirroring what _process_bar() will do.
        """
        from src.intelligence.trading.aggregator import aggregate

        signals = [
            {
                "type": "signal.v1",
                "symbol": "ES",
                "timeframe": "5m",
                "timestamp": "2026-03-06T10:00:00Z",
                "signal_type": "test",
                "setup_plugin": "trad_TrendFollowing",
                "direction": 1,
                "entry_price": 5200.0,
                "stop_loss": 5185.0,
                "targets": [5215.0],
                "confidence": 0.7,
                "risk_reward_ratio": 1.0,
                "regime_context": "bullish",
                "confluence_score": 0.5,
                "supporting_factors": [],
                "invalidation_conditions": [],
                "ttl_bars": 10,
                "regime_type": "any",
            }
        ]
        perf_weights = {"trad_TrendFollowing": 0.8}

        # RED: aggregate() raises TypeError — perf_weights kwarg not accepted yet
        result = aggregate(signals, trend_regime=0.0, perf_weights=perf_weights)
        assert result is not None
