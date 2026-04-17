"""Tests for ServiceAuditorAgent roll handler with correct RollEvent schema.

The old handler checked event_type=='roll_complete' and used new_expiry/old_expiry
fields — neither of which exist in RollEvent. This file tests the fixed behavior:
- Fires on any valid RollEvent (no event_type gate)
- Deduplicates by (symbol, new_contract)
- Restarts ibkr-provider on first event per (symbol, new_contract)
- Skips duplicates (volume + calendar both fire for same roll)
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.service_auditor_agent import ServiceAuditorAgent


def _make_agent():
    agent = ServiceAuditorAgent.__new__(ServiceAuditorAgent)
    agent.settings = MagicMock(env_name="test")
    agent._handled_rolls = set()
    agent.logger = MagicMock()
    agent._restart_ibkr_provider = AsyncMock()
    agent._dispatch_webhook = AsyncMock()
    return agent


def _roll_payload(detection_method="volume", symbol="ES", old_contract="ESH6", new_contract="ESM6"):
    return {
        "symbol": symbol,
        "old_contract": old_contract,
        "new_contract": new_contract,
        "roll_gap_price": 0.0,
        "roll_gap_pct": 0.0,
        "detection_ts": datetime(2026, 6, 14, 14, 30, tzinfo=UTC).isoformat(),
        "volume_zscore": -2.8 if detection_method == "volume" else 0.0,
        "confirmation_count": 3 if detection_method == "volume" else 0,
        "detection_method": detection_method,
    }


@pytest.mark.asyncio
async def test_fires_on_volume_roll_event():
    """Volume RollEvent triggers ibkr-provider restart (no event_type gate needed)."""
    agent = _make_agent()
    await agent._handle_roll_event(_roll_payload("volume"))
    assert agent._restart_ibkr_provider.call_count == 1


@pytest.mark.asyncio
async def test_fires_on_calendar_roll_event():
    """Calendar RollEvent also triggers ibkr-provider restart."""
    agent = _make_agent()
    await agent._handle_roll_event(_roll_payload("calendar"))
    assert agent._restart_ibkr_provider.call_count == 1


@pytest.mark.asyncio
async def test_dedup_prevents_double_restart_volume_then_calendar():
    """Volume fires first, calendar fires second — restart happens only once."""
    agent = _make_agent()
    await agent._handle_roll_event(_roll_payload("volume"))
    await agent._handle_roll_event(_roll_payload("calendar"))
    assert agent._restart_ibkr_provider.call_count == 1


@pytest.mark.asyncio
async def test_dedup_prevents_double_restart_calendar_then_volume():
    """Calendar fires first, volume fires second — restart happens only once."""
    agent = _make_agent()
    await agent._handle_roll_event(_roll_payload("calendar"))
    await agent._handle_roll_event(_roll_payload("volume"))
    assert agent._restart_ibkr_provider.call_count == 1


@pytest.mark.asyncio
async def test_dedup_key_is_symbol_and_new_contract():
    """Different new_contract values are independent — each triggers a restart."""
    agent = _make_agent()
    await agent._handle_roll_event(_roll_payload("volume", new_contract="ESM6"))
    await agent._handle_roll_event(_roll_payload("volume", new_contract="ESU6"))
    assert agent._restart_ibkr_provider.call_count == 2


@pytest.mark.asyncio
async def test_handled_rolls_contains_symbol_and_new_contract():
    """After handling, (symbol, new_contract) is in _handled_rolls."""
    agent = _make_agent()
    await agent._handle_roll_event(_roll_payload("volume"))
    assert ("ES", "ESM6") in agent._handled_rolls


@pytest.mark.asyncio
async def test_roll_restarts_both_ibkr_provider_and_roll_compute():
    """A roll event restarts both ibkr-provider and roll-compute so symbol map stays fresh."""
    agent = _make_agent()
    agent._restart_roll_compute = AsyncMock()
    await agent._handle_roll_event(_roll_payload("volume"))
    assert agent._restart_ibkr_provider.call_count == 1
    assert agent._restart_roll_compute.call_count == 1
