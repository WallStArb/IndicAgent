"""Tests for shadow signal virtual-activation in SignalTracker.

Shadow signals (is_shadow=True, status='regime_suppressed') must be loaded into
the active index with status='active' so the lifecycle tracker evaluates them
and writes outcomes — enabling the shadow governance promotion gate.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.signal_tracker import SignalTracker
from src.persistence.repository.signal_ledger_repository import SignalStatus


def _make_agent() -> SignalTracker:
    agent = SignalTracker.__new__(SignalTracker)
    agent.logger = MagicMock()
    agent._stop_event = MagicMock()
    agent._stop_event.is_set.return_value = False
    agent._active_index: dict = defaultdict(list)
    agent._active_symbols: set = set()
    agent._signal_ids: set = set()
    agent._signal_states: dict = {}
    agent._point_values: dict = {}
    agent._regime_cache: dict = {}
    agent._producer = AsyncMock()
    agent._transitions_total = MagicMock()
    agent._active_signals_gauge = MagicMock()
    agent.settings = MagicMock(env_name="dev")
    return agent


def _shadow_payload(signal_id: str = "shadow-001") -> dict:
    fire_ts = datetime.now(UTC) - timedelta(minutes=2)
    expires_at = fire_ts + timedelta(minutes=10)
    return {
        "symbol": "ESM6",
        "tf": "1m",
        "bar_ts": fire_ts.isoformat(),
        "signals": [
            {
                "signal_id": signal_id,
                "symbol": "ESM6",
                "timeframe": "1m",
                "timestamp": fire_ts.isoformat(),
                "status": "regime_suppressed",
                "is_shadow": True,
                "direction": 1,
                "entry_price": 5100.0,
                "stop_loss": 5085.0,
                "targets": [5115.0],
                "entry_zone_low": 5095.0,
                "entry_zone_high": 5100.0,
                "ttl_bars": 10,
                "expires_at": expires_at,
            }
        ],
    }


class TestShadowVirtualActivation:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_shadow_signal_enters_active_index_as_active(self):
        """regime_suppressed + is_shadow=True must enter active index with status='active'."""
        agent = _make_agent()
        payload = _shadow_payload("shadow-001")
        await agent._ingest_i7_payload(payload)

        assert "shadow-001" in agent._signal_ids
        state = agent._signal_states.get("shadow-001")
        assert state is not None, "Shadow signal must have a SignalState entry"
        assert (
            state.status == SignalStatus.ACTIVE
        ), f"Shadow signal must be virtually-active in memory, got {state.status!r}"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_non_shadow_regime_suppressed_is_skipped(self):
        """regime_suppressed with is_shadow=False must still be skipped."""
        agent = _make_agent()
        fire_ts = datetime.now(UTC) - timedelta(minutes=2)
        payload = {
            "symbol": "ESM6",
            "tf": "1m",
            "bar_ts": fire_ts.isoformat(),
            "signals": [
                {
                    "signal_id": "live-suppressed-001",
                    "symbol": "ESM6",
                    "timeframe": "1m",
                    "timestamp": fire_ts.isoformat(),
                    "status": "regime_suppressed",
                    "is_shadow": False,
                    "direction": 1,
                    "entry_price": 5100.0,
                    "stop_loss": 5085.0,
                    "targets": [5115.0],
                    "entry_zone_low": 5095.0,
                    "entry_zone_high": 5100.0,
                    "ttl_bars": 10,
                    "expires_at": fire_ts + timedelta(minutes=10),
                }
            ],
        }
        await agent._ingest_i7_payload(payload)

        assert "live-suppressed-001" not in agent._signal_ids

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_shadow_signal_deduped_on_second_ingest(self):
        """Shadow signal already in _signal_ids must be a no-op on re-ingest."""
        agent = _make_agent()
        payload = _shadow_payload("shadow-dedup")
        await agent._ingest_i7_payload(payload)
        count_before = len(agent._signal_ids)
        await agent._ingest_i7_payload(payload)
        assert len(agent._signal_ids) == count_before
