"""Characterization tests for per-key lock acquisition and release behavior.

Tests document and pin the locking contract added in Phase 18 — do not modify without
understanding the concurrent state isolation design.

Phase 43 update: MarketAnalysisService migrated from asyncio.Lock to threading.Lock
to support asyncio.to_thread() plugin execution. IndicatorComputeAgent retains asyncio.Lock.

Phase 52.2 update: IndicatorService renamed to IndicatorComputeAgent.
MarketAnalysisService tests skipped — services/market_analysis_service.py no longer
exists (consolidated into feature_compute_agent in v2.0 DAG refactor).
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from services.indicator_compute_agent import IndicatorComputeAgent


@pytest.mark.unit
class TestPerKeyLockCharacterization:
    """Pin the per-key lock contract for IndicatorComputeAgent (asyncio.Lock)."""

    @pytest.mark.skip(
        reason=(
            "market_analysis_service.py no longer exists — consolidated into"
            " feature_compute_agent (v2.0 DAG refactor)"
        )
    )
    def test_same_key_returns_same_lock_market_analysis(self):
        """_get_state_lock() is idempotent: same key must return the exact same lock object."""
        pass

    def test_different_keys_return_different_locks_indicator(self):
        """_get_state_lock() must return distinct locks for distinct keys."""
        svc = IndicatorComputeAgent.__new__(IndicatorComputeAgent)
        svc._stop_event = asyncio.Event()
        svc.name = "test"
        svc.logger = MagicMock()
        svc._i1_plugin_states_locks = {}
        key_a = ("RSI", "ES", "1m")
        key_b = ("RSI", "NQ", "1m")
        lock_a = svc._get_state_lock(key_a)
        lock_b = svc._get_state_lock(key_b)
        assert lock_a is not lock_b

    @pytest.mark.skip(
        reason=(
            "market_analysis_service.py no longer exists — consolidated into"
            " feature_compute_agent (v2.0 DAG refactor)"
        )
    )
    def test_held_lock_blocks_concurrent_waiter(self):
        """A threading.Lock held by one thread must block a second thread until released."""
        pass

    @pytest.mark.skip(
        reason=(
            "market_analysis_service.py no longer exists — consolidated into"
            " feature_compute_agent (v2.0 DAG refactor)"
        )
    )
    def test_lock_not_held_after_with_exits(self):
        """threading.Lock must be free (not locked) after with block completes normally."""
        pass

    @pytest.mark.asyncio
    async def test_lock_released_after_async_with_exits(self):
        """asyncio.Lock (IndicatorComputeAgent) must be free after async with completes."""
        svc = IndicatorComputeAgent.__new__(IndicatorComputeAgent)
        svc._stop_event = asyncio.Event()
        svc.name = "test"
        svc.logger = MagicMock()
        svc._i1_plugin_states_locks = {}
        key = ("GARCH", "ES", "1m")
        lock = svc._get_state_lock(key)

        async with lock:
            pass  # normal exit

        assert not lock.locked()
