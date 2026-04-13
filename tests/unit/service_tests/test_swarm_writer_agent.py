"""Unit tests for SwarmWriterAgent. Uses __new__ pattern (per CLAUDE.md).

Updated for Phase 68-02: SwarmWriterAgent inherits from BaseWriterAgent.
Tests _parse_payload, _flush_batch, and DLQ routing.
"""
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
    agent._producer.publish = AsyncMock()
    agent._settings = MagicMock()
    agent._settings.env_name = "test"
    agent.logger = MagicMock()
    agent._buffer = []
    agent._buffer_depth_gauge = MagicMock()
    agent._buffer_overflow_total = MagicMock()
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
async def test_flush_batch_inserts_to_shadow_table():
    agent = _make_agent()
    conn = AsyncMock()
    agent._pool.acquire = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=conn), __aexit__=AsyncMock()
        )
    )

    payload = _make_agent_result_payload()
    await agent._flush_batch([payload])

    conn.executemany.assert_awaited_once()
    call_args = conn.executemany.call_args
    sql = call_args[0][0]
    assert "alpha_multiplier_shadow" in sql


def test_parse_payload_returns_none_for_malformed():
    agent = _make_agent()

    bad_payload = {"not_a_valid": "agent_result"}
    result = agent._parse_payload(bad_payload)

    assert result is None


def test_parse_payload_returns_list_for_valid():
    agent = _make_agent()

    payload = _make_agent_result_payload()
    result = agent._parse_payload(payload)

    assert result is not None
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0] == payload


def test_inherits_base_writer_agent():
    from services.swarm_writer_agent import SwarmWriterAgent
    from src.core.agent.base_writer import BaseWriterAgent

    assert issubclass(SwarmWriterAgent, BaseWriterAgent)


@pytest.mark.asyncio
async def test_do_flush_on_db_failure_preserves_buffer():
    agent = _make_agent()
    conn = AsyncMock()
    conn.executemany = AsyncMock(side_effect=Exception("DB connection refused"))
    ctx_mgr = AsyncMock()
    ctx_mgr.__aenter__ = AsyncMock(return_value=conn)
    ctx_mgr.__aexit__ = AsyncMock(return_value=False)
    agent._pool.acquire = MagicMock(return_value=ctx_mgr)

    payload = _make_agent_result_payload()
    agent._buffer = [payload]

    await agent._do_flush()

    # Buffer preserved on error
    assert len(agent._buffer) == 1
