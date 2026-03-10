"""Characterization tests for per-key asyncio.Lock acquisition and release behavior.

Tests document and pin the locking contract added in Phase 18 — do not modify without
understanding the concurrent state isolation design.
"""

import asyncio

import pytest

from services.indicator_service import IndicatorService
from services.market_analysis_service import MarketAnalysisService


@pytest.mark.unit
class TestPerKeyLockCharacterization:
    """Pin the per-key asyncio.Lock contract for MarketAnalysisService and IndicatorService."""

    def test_same_key_returns_same_lock_market_analysis(self):
        """_get_state_lock() is idempotent: same key must return the exact same lock object."""
        svc = MarketAnalysisService.__new__(MarketAnalysisService)
        svc._plugin_states_locks = {}
        key = ("RSI", "ES", "1m")
        lock1 = svc._get_state_lock(key)
        lock2 = svc._get_state_lock(key)
        assert lock1 is lock2

    def test_different_keys_return_different_locks_indicator(self):
        """_get_state_lock() must return distinct locks for distinct keys."""
        svc = IndicatorService.__new__(IndicatorService)
        svc._i1_plugin_states_locks = {}
        key_a = ("RSI", "ES", "1m")
        key_b = ("RSI", "NQ", "1m")
        lock_a = svc._get_state_lock(key_a)
        lock_b = svc._get_state_lock(key_b)
        assert lock_a is not lock_b

    @pytest.mark.asyncio
    async def test_held_lock_blocks_concurrent_waiter(self):
        """A lock held by one coroutine must block a second coroutine until released."""
        svc = MarketAnalysisService.__new__(MarketAnalysisService)
        svc._plugin_states_locks = {}
        key = ("HMM", "ES", "5m")
        lock = svc._get_state_lock(key)

        execution_order = []

        async def holder():
            async with lock:
                execution_order.append("holder_entered")
                await asyncio.sleep(0.01)
                execution_order.append("holder_exited")

        async def waiter():
            await asyncio.sleep(0.001)  # let holder acquire first
            async with lock:
                execution_order.append("waiter_entered")

        await asyncio.gather(holder(), waiter())

        assert execution_order == ["holder_entered", "holder_exited", "waiter_entered"]

    @pytest.mark.asyncio
    async def test_lock_released_after_async_with_exits(self):
        """Lock must be free (not locked) after async with block completes normally."""
        svc = IndicatorService.__new__(IndicatorService)
        svc._i1_plugin_states_locks = {}
        key = ("GARCH", "ES", "1m")
        lock = svc._get_state_lock(key)

        async with lock:
            pass  # normal exit

        assert not lock.locked()
