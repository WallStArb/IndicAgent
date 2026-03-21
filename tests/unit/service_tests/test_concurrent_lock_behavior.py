"""Characterization tests for per-key lock acquisition and release behavior.

Tests document and pin the locking contract added in Phase 18 — do not modify without
understanding the concurrent state isolation design.

Phase 43 update: MarketAnalysisService migrated from asyncio.Lock to threading.Lock
to support asyncio.to_thread() plugin execution. IndicatorService retains asyncio.Lock.
"""

import threading
import time

import pytest

from services.indicator_service import IndicatorService
from services.market_analysis_service import MarketAnalysisService


@pytest.mark.unit
class TestPerKeyLockCharacterization:
    """Pin the per-key lock contract for MarketAnalysisService (threading) and IndicatorService (asyncio)."""

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

    def test_held_lock_blocks_concurrent_waiter(self):
        """A threading.Lock held by one thread must block a second thread until released."""
        svc = MarketAnalysisService.__new__(MarketAnalysisService)
        svc._plugin_states_locks = {}
        key = ("HMM", "ES", "5m")
        lock = svc._get_state_lock(key)

        execution_order = []

        def holder():
            with lock:
                execution_order.append("holder_entered")
                time.sleep(0.05)
                execution_order.append("holder_exited")

        def waiter():
            time.sleep(0.01)  # let holder acquire first
            with lock:
                execution_order.append("waiter_entered")

        t1 = threading.Thread(target=holder)
        t2 = threading.Thread(target=waiter)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert execution_order == ["holder_entered", "holder_exited", "waiter_entered"]

    def test_lock_not_held_after_with_exits(self):
        """threading.Lock must be free (not locked) after with block completes normally."""
        svc = MarketAnalysisService.__new__(MarketAnalysisService)
        svc._plugin_states_locks = {}
        key = ("GARCH", "ES", "1m")
        lock = svc._get_state_lock(key)

        with lock:
            pass  # normal exit

        assert not lock.locked()

    @pytest.mark.asyncio
    async def test_lock_released_after_async_with_exits(self):
        """asyncio.Lock (IndicatorService) must be free after async with block completes normally."""
        svc = IndicatorService.__new__(IndicatorService)
        svc._i1_plugin_states_locks = {}
        key = ("GARCH", "ES", "1m")
        lock = svc._get_state_lock(key)

        async with lock:
            pass  # normal exit

        assert not lock.locked()
