"""Unit tests for SwarmWriterAgent. Uses __new__ pattern (per CLAUDE.md)."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest


def _make_agent():
    from services.swarm_writer_agent import SwarmWriterAgent

    agent = SwarmWriterAgent.__new__(SwarmWriterAgent)
    agent._pool = MagicMock()
    agent._producer = MagicMock()
    agent._settings = MagicMock()
    agent._settings.env_name = "test"
    agent.logger = MagicMock()
    return agent


def _make_agent_result_payload(
    agent_id: str = "test_agent",
    multiplier: float = 1.2,
    confidence: float = 0.85,
    path: str = "path_a",
    shadow_only: bool = True,
    regime: int = 1,
):
    return {
        "signal_id": str(uuid4()),
        "agent_id": agent_id,
        "symbol": "ESM6",
        "tf": "1m",
        "ts": datetime.now(UTC).isoformat(),
        "multiplier": multiplier,
        "confidence": confidence,
        "path": path,
        "shadow_only": shadow_only,
        "hmm_regime": regime,
        "features": None,
        "latency_ms": 12.5,
    }


@pytest.mark.asyncio
async def test_write_single_row_inserts_to_shadow_table():
    agent = _make_agent()
    conn = AsyncMock()
    agent._pool.acquire = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=conn), __aexit__=AsyncMock()
        )
    )

    payload = _make_agent_result_payload()
    await agent._write_batch([payload])

    conn.executemany.assert_awaited_once()
    call_args = conn.executemany.call_args
    sql = call_args[0][0]
    assert "alpha_multiplier_shadow" in sql


@pytest.mark.asyncio
async def test_malformed_payload_sent_to_dlq():
    agent = _make_agent()
    agent._producer.publish = AsyncMock()

    bad_payload = {"not_a_valid": "agent_result"}
    await agent._handle_message(bad_payload)

    agent._producer.publish.assert_awaited_once()
    call_args = agent._producer.publish.call_args
    assert "dlq" in call_args[0][0]


@pytest.mark.asyncio
async def test_db_failure_sends_to_dlq():
    agent = _make_agent()
    conn = AsyncMock()
    conn.executemany = AsyncMock(side_effect=Exception("DB connection refused"))
    # __aexit__ must return False so the exception propagates (default AsyncMock
    # returns truthy, which suppresses the exception — per CLAUDE.md mock gotcha)
    ctx_mgr = AsyncMock()
    ctx_mgr.__aenter__ = AsyncMock(return_value=conn)
    ctx_mgr.__aexit__ = AsyncMock(return_value=False)
    agent._pool.acquire = MagicMock(return_value=ctx_mgr)
    agent._producer.publish = AsyncMock()

    payload = _make_agent_result_payload()
    await agent._write_batch([payload])

    agent._producer.publish.assert_awaited_once()
    dlq_topic = agent._producer.publish.call_args[0][0]
    assert "dlq" in dlq_topic
