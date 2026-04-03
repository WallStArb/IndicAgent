"""Unit tests for ContractMetadataWriterAgent.

Tests cover:
- Startup seeding logic (happy path + existing row skip)
- Roll event processing (happy path, DLQ routing, idempotency)
- DRY_RUN mode
- Topic properties

All DB operations mocked via AsyncMock — no live DB required.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.contract_metadata_writer_agent import ContractMetadataWriterAgent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_valid_roll_payload(
    old_contract: str = "ESH6",
    new_contract: str = "ESM6",
    symbol: str = "ES",
) -> dict:
    """Build a valid RollEvent dict."""
    return {
        "symbol": symbol,
        "old_contract": old_contract,
        "new_contract": new_contract,
        "roll_gap_price": -0.25,
        "roll_gap_pct": -0.0042,
        "detection_ts": datetime.now(UTC).isoformat(),
        "volume_zscore": 2.5,
        "confirmation_count": 3,
    }


def _make_conn_mock(old_row: dict | None = None) -> AsyncMock:
    """Build a mocked asyncpg connection with transaction support."""
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value="INSERT 0 1")
    conn.fetchrow = AsyncMock(return_value=old_row)

    # transaction() must work as an async context manager
    @asynccontextmanager
    async def _transaction():
        yield

    conn.transaction = _transaction
    return conn


def _make_pool_mock(old_row: dict | None = None) -> AsyncMock:
    """Build a mocked asyncpg pool whose acquire() returns a mock connection."""
    conn = _make_conn_mock(old_row=old_row)

    pool = AsyncMock()

    @asynccontextmanager
    async def _acquire():
        yield conn

    pool.acquire = _acquire
    pool._conn = conn  # store for assertion access
    return pool


@pytest.fixture
def agent():
    """Create agent bypassing __init__ (Phase 52.2 __new__ pattern)."""
    a = ContractMetadataWriterAgent.__new__(ContractMetadataWriterAgent)
    a.name = "contract_metadata_writer_agent"
    a.logger = MagicMock()
    a._settings = MagicMock()
    a._settings.kafka_bootstrap_servers = "localhost:19092"
    a._env_name = ""
    a._dry_run = False
    a._db_pool = _make_pool_mock(
        old_row={"base_symbol": "ES", "exchange": "CME"}
    )
    a._kafka_producer = AsyncMock()
    a._kafka_consumer = AsyncMock()
    # Cache labeled metric children
    a._rolls_processed = MagicMock()
    a._roll_errors = MagicMock()
    a._seeds_inserted = MagicMock()
    # _processing_latency must work as a context manager via .time()
    latency_ctx = MagicMock()
    latency_ctx.__enter__ = MagicMock(return_value=None)
    latency_ctx.__exit__ = MagicMock(return_value=False)
    latency_mock = MagicMock()
    latency_mock.time = MagicMock(return_value=latency_ctx)
    a._processing_latency = latency_mock
    a._last_roll_ts = MagicMock()
    return a


# ---------------------------------------------------------------------------
# Seed tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_missing_contracts_inserts_futures(agent):
    """Seeder increments _seeds_inserted for each successfully inserted row."""
    from src.core.models import AssetClass, Instrument

    instruments = [
        Instrument(symbol="ESM6", base="ES", exchange="CME", asset_class=AssetClass.FUTURES),
        Instrument(symbol="NQM6", base="NQ", exchange="CME", asset_class=AssetClass.FUTURES),
    ]

    conn = _make_conn_mock()
    conn.execute = AsyncMock(return_value="INSERT 0 1")

    pool = AsyncMock()

    @asynccontextmanager
    async def _acquire():
        yield conn

    pool.acquire = _acquire
    agent._db_pool = pool

    with patch(
        "services.contract_metadata_writer_agent.get_active_contracts",
        return_value=instruments,
    ):
        await agent._seed_missing_contracts()

    assert agent._seeds_inserted.inc.call_count == 2


@pytest.mark.asyncio
async def test_seed_missing_contracts_skips_existing(agent):
    """Seeder does NOT increment _seeds_inserted when ON CONFLICT DO NOTHING fires."""
    from src.core.models import AssetClass, Instrument

    instruments = [
        Instrument(symbol="ESM6", base="ES", exchange="CME", asset_class=AssetClass.FUTURES),
    ]

    conn = _make_conn_mock()
    # "INSERT 0 0" = conflict — row already existed
    conn.execute = AsyncMock(return_value="INSERT 0 0")

    pool = AsyncMock()

    @asynccontextmanager
    async def _acquire():
        yield conn

    pool.acquire = _acquire
    agent._db_pool = pool

    with patch(
        "services.contract_metadata_writer_agent.get_active_contracts",
        return_value=instruments,
    ):
        await agent._seed_missing_contracts()

    agent._seeds_inserted.inc.assert_not_called()


# ---------------------------------------------------------------------------
# Roll event happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_roll_event_valid(agent):
    """Valid RollEvent: atomic UPDATE+INSERT executed, ContractUpdateEvent published."""
    payload = _make_valid_roll_payload()

    conn = _make_conn_mock(old_row={"base_symbol": "ES", "exchange": "CME"})

    pool = AsyncMock()

    @asynccontextmanager
    async def _acquire():
        yield conn

    pool.acquire = _acquire
    agent._db_pool = pool

    await agent._handle_roll_event(payload)

    # Two execute calls: UPDATE old + UPSERT new
    assert conn.execute.call_count == 2
    # ContractUpdateEvent published to contract_updates topic
    agent._kafka_producer.publish.assert_called_once()
    publish_call = agent._kafka_producer.publish.call_args
    assert "roll.dlq" not in publish_call[0][0]  # not sent to DLQ
    assert publish_call[0][1]["new_contract"] == "ESM6"
    # rolls_processed incremented
    agent._rolls_processed.inc.assert_called_once()


@pytest.mark.asyncio
async def test_handle_roll_event_idempotent(agent):
    """Calling _handle_roll_event twice with same payload causes no errors."""
    payload = _make_valid_roll_payload()

    conn = _make_conn_mock(old_row={"base_symbol": "ES", "exchange": "CME"})

    pool = AsyncMock()

    @asynccontextmanager
    async def _acquire():
        yield conn

    pool.acquire = _acquire
    agent._db_pool = pool

    await agent._handle_roll_event(payload)
    await agent._handle_roll_event(payload)

    assert agent._rolls_processed.inc.call_count == 2
    agent._roll_errors.inc.assert_not_called()


# ---------------------------------------------------------------------------
# DLQ routing tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_roll_event_invalid_payload_to_dlq(agent):
    """Malformed payload (missing required fields) → DLQ, roll_errors incremented."""
    bad_payload = {"symbol": "ES", "foo": "bar"}  # missing old_contract, new_contract, etc.

    await agent._handle_roll_event(bad_payload)

    agent._roll_errors.inc.assert_called_once()
    agent._kafka_producer.publish.assert_called_once()
    dlq_topic = agent._kafka_producer.publish.call_args[0][0]
    assert "dlq" in dlq_topic


@pytest.mark.asyncio
async def test_handle_roll_event_empty_contract_to_dlq(agent):
    """RollEvent with empty new_contract → DLQ, roll_errors incremented."""
    payload = _make_valid_roll_payload(new_contract="")

    await agent._handle_roll_event(payload)

    agent._roll_errors.inc.assert_called_once()
    agent._kafka_producer.publish.assert_called_once()
    dlq_topic = agent._kafka_producer.publish.call_args[0][0]
    assert "dlq" in dlq_topic
    # No DB transaction was started
    agent._db_pool._conn.execute.assert_not_called()


@pytest.mark.asyncio
async def test_handle_roll_event_unknown_old_contract_to_dlq(agent):
    """old_contract not in contract_metadata → DLQ, no DB write."""
    payload = _make_valid_roll_payload()

    # fetchrow returns None = old_contract unknown
    conn = _make_conn_mock(old_row=None)

    pool = AsyncMock()

    @asynccontextmanager
    async def _acquire():
        yield conn

    pool.acquire = _acquire
    agent._db_pool = pool

    await agent._handle_roll_event(payload)

    agent._roll_errors.inc.assert_called_once()
    agent._kafka_producer.publish.assert_called_once()
    dlq_topic = agent._kafka_producer.publish.call_args[0][0]
    assert "dlq" in dlq_topic
    # No execute calls (no UPDATE/INSERT)
    conn.execute.assert_not_called()


# ---------------------------------------------------------------------------
# Exchange copy test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_roll_event_exchange_copied_from_old_row(agent):
    """exchange on new contract row is copied from old_contract's DB row."""
    payload = _make_valid_roll_payload()

    conn = _make_conn_mock(old_row={"base_symbol": "ES", "exchange": "CME"})

    pool = AsyncMock()

    @asynccontextmanager
    async def _acquire():
        yield conn

    pool.acquire = _acquire
    agent._db_pool = pool

    await agent._handle_roll_event(payload)

    # Second execute call is the UPSERT for new contract
    upsert_call = conn.execute.call_args_list[1]
    # The positional args after the SQL string include exchange at position 3 ($3)
    upsert_args = upsert_call[0]  # positional tuple
    # args: (sql, new_contract, base_symbol, exchange, old_contract, detection_ts, count)
    assert upsert_args[3] == "CME"


# ---------------------------------------------------------------------------
# DRY_RUN test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dry_run_skips_db_write(agent):
    """DRY_RUN=true: DB transaction not called, ContractUpdateEvent published with dry_run=True."""
    agent._dry_run = True
    payload = _make_valid_roll_payload()

    conn = _make_conn_mock(old_row={"base_symbol": "ES", "exchange": "CME"})

    pool = AsyncMock()

    @asynccontextmanager
    async def _acquire():
        yield conn

    pool.acquire = _acquire
    agent._db_pool = pool

    await agent._handle_roll_event(payload)

    # No UPDATE or INSERT executed
    conn.execute.assert_not_called()
    # ContractUpdateEvent still published (with dry_run flag)
    agent._kafka_producer.publish.assert_called_once()
    publish_args = agent._kafka_producer.publish.call_args[0]
    assert publish_args[1].get("dry_run") is True
    assert "dlq" not in publish_args[0]  # not sent to DLQ


# ---------------------------------------------------------------------------
# Topic property tests
# ---------------------------------------------------------------------------


def test_topics_consumed_returns_roll_events(agent):
    """topics_consumed includes the roll events topic."""
    topics = agent.topics_consumed
    assert len(topics) == 1
    assert "roll" in topics[0]


def test_topics_produced_returns_contract_updates_and_dlq(agent):
    """topics_produced includes both contract_update and roll.dlq topics."""
    topics = agent.topics_produced
    assert len(topics) == 2
    topic_str = " ".join(topics)
    assert "contract_update" in topic_str
    assert "dlq" in topic_str
