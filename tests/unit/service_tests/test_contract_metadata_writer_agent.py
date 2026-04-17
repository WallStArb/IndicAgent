"""Unit tests for ContractMetadataWriterAgent — TDD for idempotency and roll_events writes.

Tests:
- Duplicate roll event (same base_symbol + new_contract) skips DB promotion
- Duplicate roll event still writes to roll_events with is_authoritative=False
- First roll event writes to roll_events with is_authoritative=True
- _processed_rolls set exists and is initialized empty
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent():
    from services.contract_metadata_writer_agent import ContractMetadataWriterAgent

    agent = ContractMetadataWriterAgent.__new__(ContractMetadataWriterAgent)
    agent.name = "contract_metadata_writer_agent"
    agent.logger = MagicMock()
    agent.settings = MagicMock(env_name="dev")
    agent._dry_run = False
    agent._db_pool = MagicMock()
    agent._kafka_producer = AsyncMock()
    agent._processed_rolls = set()

    agent._rolls_processed = MagicMock()
    agent._roll_errors = MagicMock()
    agent._seeds_inserted = MagicMock()
    agent._processing_latency = MagicMock()
    agent._processing_latency.__enter__ = MagicMock(return_value=None)
    agent._processing_latency.__exit__ = MagicMock(return_value=False)
    agent._last_roll_ts = MagicMock()
    return agent


def _valid_payload(detection_method="volume"):
    return {
        "symbol": "ES",
        "old_contract": "ESH6",
        "new_contract": "ESM6",
        "roll_gap_price": 0.0,
        "roll_gap_pct": 0.0,
        "detection_ts": datetime(2026, 6, 14, 14, 30, tzinfo=UTC).isoformat(),
        "volume_zscore": -2.8,
        "confirmation_count": 3,
        "detection_method": detection_method,
    }


def _make_conn(execute_side_effect=None):
    """asyncpg connection mock with working transaction() context manager."""
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value={"base_symbol": "ES", "exchange": "CME"})
    conn.execute = AsyncMock(side_effect=execute_side_effect)
    mock_txn = MagicMock()
    mock_txn.__aenter__ = AsyncMock(return_value=conn)
    mock_txn.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=mock_txn)
    return conn


def _make_pool(conn):
    pool_ctx = MagicMock()
    pool_ctx.__aenter__ = AsyncMock(return_value=conn)
    pool_ctx.__aexit__ = AsyncMock(return_value=False)
    db_pool = MagicMock()
    db_pool.acquire = MagicMock(return_value=pool_ctx)
    return db_pool


# ---------------------------------------------------------------------------
# Test 1: _processed_rolls set exists
# ---------------------------------------------------------------------------

def test_processed_rolls_set_initialized():
    """ContractMetadataWriterAgent must have _processed_rolls as an empty set."""
    agent = _make_agent()
    assert hasattr(agent, "_processed_rolls")
    assert isinstance(agent._processed_rolls, set)
    assert len(agent._processed_rolls) == 0


# ---------------------------------------------------------------------------
# Test 2: First event — authoritative write + adds to processed_rolls
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_first_roll_event_writes_authoritative_to_roll_events():
    """First roll event writes is_authoritative=True to roll_events."""
    agent = _make_agent()

    roll_inserts = []

    async def capture(sql, *args):
        if "roll_events" in sql:
            roll_inserts.append(args)

    conn = _make_conn(execute_side_effect=capture)
    agent._db_pool = _make_pool(conn)

    with patch("services.contract_metadata_writer_agent.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 6, 14, 14, 30, tzinfo=UTC)
        await agent._handle_roll_event(_valid_payload("volume"))

    assert len(roll_inserts) == 1
    assert True in roll_inserts[0]


@pytest.mark.asyncio
async def test_first_roll_event_adds_to_processed_rolls():
    """After first event, (base_symbol, new_contract) is in _processed_rolls."""
    agent = _make_agent()
    conn = _make_conn()
    agent._db_pool = _make_pool(conn)

    with patch("services.contract_metadata_writer_agent.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 6, 14, 14, 30, tzinfo=UTC)
        await agent._handle_roll_event(_valid_payload("volume"))

    assert ("ES", "ESM6") in agent._processed_rolls


# ---------------------------------------------------------------------------
# Test 3: Duplicate event — skip promotion, write non-authoritative
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_duplicate_roll_event_skips_promotion():
    """Duplicate event skips contract_metadata UPDATE entirely."""
    agent = _make_agent()
    agent._processed_rolls.add(("ES", "ESM6"))

    executed_sqls = []

    async def capture(sql, *args):
        executed_sqls.append(sql)

    conn = _make_conn(execute_side_effect=capture)
    agent._db_pool = _make_pool(conn)

    with patch("services.contract_metadata_writer_agent.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 6, 16, 14, 30, tzinfo=UTC)
        await agent._handle_roll_event(_valid_payload("calendar"))

    for sql in executed_sqls:
        assert "contract_metadata" not in sql, f"Must not touch contract_metadata on duplicate: {sql}"


@pytest.mark.asyncio
async def test_duplicate_roll_event_writes_non_authoritative_to_roll_events():
    """Duplicate event writes is_authoritative=False to roll_events."""
    agent = _make_agent()
    agent._processed_rolls.add(("ES", "ESM6"))

    roll_inserts = []

    async def capture(sql, *args):
        if "roll_events" in sql:
            roll_inserts.append(args)

    conn = _make_conn(execute_side_effect=capture)
    agent._db_pool = _make_pool(conn)

    with patch("services.contract_metadata_writer_agent.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 6, 16, 14, 30, tzinfo=UTC)
        await agent._handle_roll_event(_valid_payload("calendar"))

    assert len(roll_inserts) == 1
    assert False in roll_inserts[0]
