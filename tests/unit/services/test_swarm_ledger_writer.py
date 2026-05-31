"""Unit tests for SwarmLedgerWriter (Phase 80, D-07).

Tests verify:
- test_projection_success: UPDATE 1 -> success metric incremented
- test_projection_retry_then_success: UPDATE 0 then UPDATE 1 -> retry then success
- test_projection_miss_after_all_retries: all UPDATE 0 -> miss metric after exhausting retries
- test_invalid_event_skipped: event missing signal_id is logged and skipped
- test_original_confidence_column_untouched_in_sql: source file audit
"""

from __future__ import annotations

import pathlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_writer():
    """Build SwarmLedgerWriter bypassing __init__ (CLAUDE.md __new__ pattern)."""
    from services.swarm_ledger_writer import SwarmLedgerWriter

    w = SwarmLedgerWriter.__new__(SwarmLedgerWriter)
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
    mock_conn.fetchval = AsyncMock(return_value=1)  # signal_ledger row always visible
    mock_conn.execute = AsyncMock(side_effect=lambda *a, **kw: next(results_iter))
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool


def _mock_pool_with_fk_errors(fk_error_count: int) -> MagicMock:
    """Pool mock where fetchval returns None N times (row not ready) then 1 (ready)."""
    call_count = 0

    async def fetchval_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return None if call_count <= fk_error_count else 1

    mock_conn = AsyncMock()
    mock_conn.fetchval = AsyncMock(side_effect=fetchval_side_effect)
    mock_conn.execute = AsyncMock(return_value=None)
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool


def _mock_pool_always_fk_error(attempts: int) -> MagicMock:
    """Pool mock where fetchval always returns None (row never visible)."""
    mock_conn = AsyncMock()
    mock_conn.fetchval = AsyncMock(return_value=None)
    mock_conn.execute = AsyncMock(return_value=None)
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool


@pytest.mark.asyncio
async def test_projection_success() -> None:
    w = _make_writer()
    w._pool = _mock_pool(["INSERT 1"])
    with patch("services.swarm_ledger_writer.SWARM_SIGNAL_LEDGER_UPDATE_TOTAL") as mock_c:
        await w._apply_projection("sig-1", 0.8, 0.64, 4)
    # OTel counter: .add(1, {"status": "success"}) must have been called
    mock_c.add.assert_called_once_with(1, {"status": "success"})


@pytest.mark.asyncio
async def test_projection_retry_then_success(monkeypatch) -> None:
    """First attempt raises ForeignKeyViolationError (FK race), second succeeds."""
    w = _make_writer()
    w._pool = _mock_pool_with_fk_errors(fk_error_count=1)
    import services.swarm_ledger_writer as mod

    monkeypatch.setattr(mod.asyncio, "sleep", AsyncMock())
    with patch("services.swarm_ledger_writer.SWARM_SIGNAL_LEDGER_UPDATE_TOTAL") as mock_c:
        await w._apply_projection("sig-2", 0.7, 0.56, 4)
    calls = [c.args for c in mock_c.add.call_args_list]
    assert (1, {"status": "retry"}) in calls
    assert (1, {"status": "success"}) in calls


@pytest.mark.asyncio
async def test_projection_miss_after_all_retries(monkeypatch) -> None:
    """All attempts raise ForeignKeyViolationError — exhausted retries -> miss."""
    w = _make_writer()
    w._pool = _mock_pool_always_fk_error(attempts=5)
    import services.swarm_ledger_writer as mod

    monkeypatch.setattr(mod.asyncio, "sleep", AsyncMock())
    with patch("services.swarm_ledger_writer.SWARM_SIGNAL_LEDGER_UPDATE_TOTAL") as mock_c:
        await w._apply_projection("sig-3", 0.5, 0.4, 3)
    mock_c.add.assert_called_with(1, {"status": "miss"})


@pytest.mark.asyncio
async def test_invalid_event_skipped() -> None:
    w = _make_writer()
    w._pool = _mock_pool([])  # should never be called
    await w._handle_event({"swarm_multiplier": 0.5})  # missing signal_id
    # No exception raised; logger.warning called
    w.logger.warning.assert_called()


# ---------------------------------------------------------------------------
# Phase-105 regression: enable_auto_commit=False + manual commit after success
# ---------------------------------------------------------------------------


def test_consumer_constructed_with_auto_commit_disabled() -> None:
    """KafkaConsumerClient must be constructed with enable_auto_commit=False.

    Phase-105 HF-7: auto_commit=True is the default and would silently advance
    offsets even on transient DB failures, causing data loss.

    Source inspection is the correct approach here — the constructor kwarg is a
    static choice made at the call site, not a runtime value that needs mocking.
    """
    import inspect

    import services.swarm_ledger_writer as mod

    source = inspect.getsource(mod.SwarmLedgerWriter._setup)
    assert "enable_auto_commit=False" in source, (
        "SwarmLedgerWriter._setup() must construct KafkaConsumerClient with "
        "enable_auto_commit=False to prevent automatic offset advancement on transient DB failures"
    )


@pytest.mark.asyncio
async def test_consumer_commit_called_after_successful_handle() -> None:
    """consumer.commit() must be called after a successful _handle_event().

    Phase-105 HF-7 regression: manual commit-after-success ensures offsets only
    advance when the DB write succeeded. Without this, a crash mid-write would
    cause offset advancement without data persistence (silent data loss).
    """

    w = _make_writer()

    # A valid payload that _handle_event will process successfully
    valid_payload = {
        "signal_id": "00000000-0000-0000-0000-000000000001",
        "swarm_multiplier": 1.2,
        "adjusted_confidence": 0.75,
        "swarm_agent_count": 3,
    }

    # Mock consumer: yields one message then stops
    async def one_message():
        yield ("test_topic", None, valid_payload)

    mock_consumer = MagicMock()
    mock_consumer.messages = one_message
    mock_consumer.commit = AsyncMock()
    mock_consumer.stop = AsyncMock()
    w._consumer = mock_consumer

    # Stop event fires after one iteration (consumer is exhausted by generator)
    import asyncio

    w._stop_event = asyncio.Event()

    # _apply_projection succeeds (returns True via _handle_event)
    w._pool = _mock_pool(["INSERT 1"])

    with patch("services.swarm_ledger_writer.SWARM_SIGNAL_LEDGER_UPDATE_TOTAL"):
        await w._run()

    # commit() must have been called after the successful _handle_event
    mock_consumer.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_consumer_commit_not_called_when_handle_raises() -> None:
    """consumer.commit() must NOT be called when _handle_event() raises.

    Transient DB failures must not advance the Kafka offset — the message
    must be re-delivered for retry on next consumer restart.
    """

    w = _make_writer()

    valid_payload = {
        "signal_id": "00000000-0000-0000-0000-000000000002",
        "swarm_multiplier": 1.1,
        "adjusted_confidence": 0.65,
        "swarm_agent_count": 2,
    }

    async def one_message():
        yield ("test_topic", None, valid_payload)

    mock_consumer = MagicMock()
    mock_consumer.messages = one_message
    mock_consumer.commit = AsyncMock()
    mock_consumer.stop = AsyncMock()
    w._consumer = mock_consumer

    import asyncio

    w._stop_event = asyncio.Event()

    # Patch _apply_projection to raise a transient DB error
    async def fail_projection(*args, **kwargs):
        raise RuntimeError("DB connection lost")

    w._apply_projection = fail_projection

    await w._run()

    # commit() must NOT have been called — transient failure → no offset advance
    mock_consumer.commit.assert_not_awaited()


def test_original_confidence_column_untouched_in_sql() -> None:
    src = pathlib.Path("services/swarm_ledger_writer.py").read_text()
    # UPSERT must write the three AI enrichment columns
    assert "adjusted_confidence" in src
    assert "swarm_multiplier" in src
    assert "swarm_agent_count" in src
    # Must NOT modify the original `confidence` column on signal_ledger
    assert "SET confidence" not in src
    # Must target signal_ai_enrichment (AI-SEP-01), not signal_ledger
    assert "signal_ai_enrichment" in src
    assert "UPDATE signal_ledger" not in src
