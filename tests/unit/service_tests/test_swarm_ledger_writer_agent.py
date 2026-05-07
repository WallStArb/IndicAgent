"""Unit tests for SwarmLedgerWriterAgent (Phase 80, D-07).

Tests verify:
- test_projection_success: UPDATE 1 -> success metric incremented
- test_projection_retry_then_success: UPDATE 0 then UPDATE 1 -> retry then success
- test_projection_miss_after_all_retries: all UPDATE 0 -> miss metric after exhausting retries
- test_invalid_event_skipped: event missing signal_id is logged and skipped
- test_original_confidence_column_untouched_in_sql: source file audit
"""

from __future__ import annotations

import pathlib
from unittest.mock import AsyncMock, MagicMock

import pytest
from prometheus_client import REGISTRY


def _make_writer():
    """Build SwarmLedgerWriterAgent bypassing __init__ (CLAUDE.md __new__ pattern)."""
    from services.swarm_ledger_writer_agent import SwarmLedgerWriterAgent

    w = SwarmLedgerWriterAgent.__new__(SwarmLedgerWriterAgent)
    w.settings = MagicMock(
        database_url="postgresql://test",
        kafka_bootstrap_servers="localhost:9092",
        env_name="test",
    )
    w.logger = MagicMock()
    w._pool = None
    w._consumer = None
    return w


def _mock_pool(execute_returns: list[str]) -> MagicMock:
    """Create an asyncpg-pool mock whose conn.execute returns each item in order."""
    results_iter = iter(execute_returns)
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(side_effect=lambda *a, **kw: next(results_iter))
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool


def _counter_value(status: str) -> float:
    return REGISTRY.get_sample_value("swarm_signal_ledger_update_total", {"status": status}) or 0.0


@pytest.mark.asyncio
async def test_projection_success() -> None:
    w = _make_writer()
    w._pool = _mock_pool(["UPDATE 1"])
    before = _counter_value("success")
    await w._apply_projection("sig-1", 0.8, 0.64, 4)
    assert _counter_value("success") == before + 1


@pytest.mark.asyncio
async def test_projection_retry_then_success(monkeypatch) -> None:
    w = _make_writer()
    w._pool = _mock_pool(["UPDATE 0", "UPDATE 1"])
    import services.swarm_ledger_writer_agent as mod

    monkeypatch.setattr(mod.asyncio, "sleep", AsyncMock())
    before_retry = _counter_value("retry")
    before_success = _counter_value("success")
    await w._apply_projection("sig-2", 0.7, 0.56, 4)
    assert _counter_value("retry") == before_retry + 1
    assert _counter_value("success") == before_success + 1


@pytest.mark.asyncio
async def test_projection_miss_after_all_retries(monkeypatch) -> None:
    w = _make_writer()
    # All five attempts return UPDATE 0
    w._pool = _mock_pool(["UPDATE 0"] * 5)
    import services.swarm_ledger_writer_agent as mod

    monkeypatch.setattr(mod.asyncio, "sleep", AsyncMock())
    before_miss = _counter_value("miss")
    await w._apply_projection("sig-3", 0.5, 0.4, 3)
    assert _counter_value("miss") == before_miss + 1


@pytest.mark.asyncio
async def test_invalid_event_skipped() -> None:
    w = _make_writer()
    w._pool = _mock_pool([])  # should never be called
    await w._handle_event({"swarm_multiplier": 0.5})  # missing signal_id
    # No exception raised; logger.warning called
    w.logger.warning.assert_called()


def test_original_confidence_column_untouched_in_sql() -> None:
    src = pathlib.Path("services/swarm_ledger_writer_agent.py").read_text()
    # The UPDATE block must mention only the three new columns
    assert "adjusted_confidence = $2" in src
    assert "swarm_multiplier = $3" in src
    assert "swarm_agent_count = $4" in src
    # And must NOT modify the original `confidence` column
    assert "SET confidence" not in src
