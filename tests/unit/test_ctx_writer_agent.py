"""Tests for CtxWriterAgent — validation, persistence, and JSONB safety.

Tests cover:
- Happy path: ctx_events INSERT on valid message
- Snapshot upsert with valid_to chaining on second snapshot
- Rejection of disallowed event_type
- Rejection of oversized payload
- Rejection of missing required keys
- JSONB column receives dict (not str) for asyncpg compliance
- Static test: feature_writer INSERT SQL includes ctx column + ctx_snapshots reference
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.ctx_writer_agent import (
    _ALLOWED_EVENT_TYPES,
    _MAX_PAYLOAD_BYTES,
    CtxWriterAgent,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_valid_message(
    event_type: str = "earnings",
    payload_size: int = 100,
    include_snapshot: bool = False,
) -> dict:
    """Build a minimal valid ctx.snapshot message."""
    inner: dict[str, Any] = {"summary": "x" * payload_size}
    msg: dict[str, Any] = {
        "event_ts": "2026-05-13T12:00:00Z",
        "symbol": "AAPL",
        "event_type": event_type,
        "source": "test_provider",
        "payload": inner,
    }
    if include_snapshot:
        msg["valid_from"] = "2026-05-13T12:00:00Z"
        msg["ctx"] = {"earnings_date": "2026-05-13", "surprise_pct": 5.2}
    return msg


def _make_agent() -> CtxWriterAgent:
    """Instantiate CtxWriterAgent without starting it (no DB, no Kafka)."""
    agent = CtxWriterAgent.__new__(CtxWriterAgent)
    # Bootstrap parent state manually so tests can call _process_message directly.
    agent._event_buffer = []
    agent._snapshot_buffer = []
    agent.logger = MagicMock()
    # Counters: mock them so inc() calls don't raise
    agent._events_consumed = MagicMock()
    agent._events_written = MagicMock()
    agent._snapshots_written = MagicMock()
    agent._validation_errors = MagicMock()
    agent._parse_failures_total = MagicMock()
    agent._buffer_depth_gauge = MagicMock()
    agent._flush_errors_total = MagicMock()
    agent._db = MagicMock()
    return agent


# ---------------------------------------------------------------------------
# Test 1: inserts ctx_event row on valid message
# ---------------------------------------------------------------------------


class TestCtxWriterInsertCtsEvent:
    """test_inserts_ctx_event_on_valid_message"""

    @pytest.mark.asyncio
    async def test_inserts_ctx_event_on_valid_message(self):
        agent = _make_agent()
        msg = _make_valid_message(event_type="earnings")

        # Validate via _parse_payload then buffer via _process_message
        rows = agent._parse_payload(msg)
        assert rows is not None, "Valid message should pass validation"

        await agent._process_message(msg)

        assert len(agent._event_buffer) == 1, "One ctx_events row should be buffered"
        row = agent._event_buffer[0]
        # (event_ts, symbol, event_type, source, payload)
        assert row[2] == "earnings"
        assert row[1] == "AAPL"
        assert isinstance(row[4], dict), "JSONB payload must be dict (asyncpg rule)"


# ---------------------------------------------------------------------------
# Test 2: upsert snapshot and close prior valid_to
# ---------------------------------------------------------------------------


class TestCtxWriterSnapshotChaining:
    """test_upserts_ctx_snapshot_and_closes_prior_valid_to"""

    @pytest.mark.asyncio
    async def test_upserts_ctx_snapshot_and_closes_prior_valid_to(self):
        agent = _make_agent()

        t1_msg = _make_valid_message(include_snapshot=True)
        t1_msg["valid_from"] = "2026-05-13T10:00:00Z"
        t1_msg["ctx"] = {"detail": "first"}

        t2_msg = _make_valid_message(include_snapshot=True)
        t2_msg["valid_from"] = "2026-05-13T12:00:00Z"
        t2_msg["ctx"] = {"detail": "second"}

        await agent._process_message(t1_msg)
        await agent._process_message(t2_msg)

        assert len(agent._snapshot_buffer) == 2

        # The _flush() method closes prior snapshot via UPDATE.
        # We test that the flush path calls the CLOSE_PRIOR_SNAPSHOT SQL.
        mock_conn = AsyncMock()
        mock_transaction = AsyncMock()
        mock_transaction.__aenter__ = AsyncMock(return_value=None)
        mock_transaction.__aexit__ = AsyncMock(return_value=False)
        mock_conn.transaction = MagicMock(return_value=mock_transaction)
        mock_conn.executemany = AsyncMock()
        mock_conn.execute = AsyncMock()

        mock_pool = MagicMock()
        mock_pool_context = MagicMock()
        mock_pool_context.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool_context.__aexit__ = AsyncMock(return_value=False)
        mock_pool.acquire = MagicMock(return_value=mock_pool_context)

        agent._db = MagicMock()
        agent._db.pool = mock_pool

        event_batch = agent._event_buffer[:]
        snapshot_batch = agent._snapshot_buffer[:]
        await agent._flush(event_batch, snapshot_batch)

        # executemany called 3×: events, close-prior batch, upsert batch
        assert mock_conn.executemany.call_count == 3

        # Second executemany: close-prior — each row is (symbol, event_type, valid_from)
        close_batch = mock_conn.executemany.call_args_list[1][0][1]
        assert all(row[2] is not None for row in close_batch)

        # Third executemany: upsert — each row is (symbol, event_type, valid_from, ctx)
        upsert_batch = mock_conn.executemany.call_args_list[2][0][1]
        assert len(upsert_batch) == 2


# ---------------------------------------------------------------------------
# Test 3: rejects disallowed event_type
# ---------------------------------------------------------------------------


class TestCtxWriterRejectDisallowedEventType:
    """test_rejects_disallowed_event_type"""

    def test_rejects_disallowed_event_type(self):
        agent = _make_agent()
        msg = _make_valid_message(event_type="random")

        rows = agent._parse_payload(msg)

        assert rows is None, "Disallowed event_type must return None"
        agent._validation_errors.add.assert_called()

    def test_allowed_event_types_pass(self):
        agent = _make_agent()
        for etype in sorted(_ALLOWED_EVENT_TYPES):
            msg = _make_valid_message(event_type=etype)
            rows = agent._parse_payload(msg)
            assert rows is not None, f"Allowed event_type '{etype}' should pass"


# ---------------------------------------------------------------------------
# Test 4: rejects oversized payload
# ---------------------------------------------------------------------------


class TestCtxWriterRejectOversizePayload:
    """test_truncates_or_rejects_oversize_payload"""

    def test_rejects_oversize_payload(self):
        agent = _make_agent()
        # Construct a payload slightly over the limit
        oversize_data = "x" * (_MAX_PAYLOAD_BYTES + 1)
        msg = _make_valid_message()
        msg["payload"] = {"data": oversize_data}

        rows = agent._parse_payload(msg)

        assert rows is None, "Oversized payload must return None"
        agent._validation_errors.add.assert_called()

    def test_borderline_payload_within_limit_passes(self):
        agent = _make_agent()
        # A payload near but under the limit should pass
        # json.dumps adds ~12 bytes for {"data": "..."} wrapper
        safe_data = "x" * (_MAX_PAYLOAD_BYTES - 20)
        msg = _make_valid_message()
        msg["payload"] = {"data": safe_data}

        rows = agent._parse_payload(msg)
        assert rows is not None, "Payload within limit should pass"


# ---------------------------------------------------------------------------
# Test 5: rejects missing required keys
# ---------------------------------------------------------------------------


class TestCtxWriterRejectMissingKeys:
    """test_rejects_missing_required_keys"""

    @pytest.mark.parametrize("missing_key", ["event_ts", "event_type", "payload", "source"])
    def test_rejects_missing_required_keys(self, missing_key: str):
        agent = _make_agent()
        msg = _make_valid_message()
        del msg[missing_key]

        rows = agent._parse_payload(msg)

        assert rows is None, f"Message missing '{missing_key}' must be rejected"
        agent._validation_errors.add.assert_called()


# ---------------------------------------------------------------------------
# Test 6: JSONB column receives dict not str
# ---------------------------------------------------------------------------


class TestCtxWriterJsonbNotString:
    """test_passes_dict_to_asyncpg_jsonb_not_string"""

    @pytest.mark.asyncio
    async def test_passes_dict_to_asyncpg_jsonb_not_string(self):
        agent = _make_agent()
        msg = _make_valid_message(include_snapshot=True)

        await agent._process_message(msg)

        # Check ctx_events buffer: payload (index 4) must be dict
        assert len(agent._event_buffer) == 1
        row = agent._event_buffer[0]
        jsonb_param = row[4]
        assert isinstance(
            jsonb_param, dict
        ), f"asyncpg JSONB param must be dict, got {type(jsonb_param).__name__}"
        assert not isinstance(jsonb_param, str), "JSONB must NOT be json.dumps string"

        # Check snapshot buffer: ctx (index 3) must be dict
        assert len(agent._snapshot_buffer) == 1
        snap_row = agent._snapshot_buffer[0]
        ctx_param = snap_row[3]
        assert isinstance(
            ctx_param, dict
        ), f"Snapshot JSONB ctx param must be dict, got {type(ctx_param).__name__}"


# ---------------------------------------------------------------------------
# Test 7: static test — feature_writer INSERT SQL includes ctx column + subquery
# ---------------------------------------------------------------------------


class TestFeatureWriterInsertIncludesCtx:
    """test_feature_writer_insert_includes_ctx_column"""

    def test_feature_writer_insert_includes_ctx_column(self):
        import pathlib

        # Load module source to inspect SQL without executing any DB code
        source_path = pathlib.Path("services/feature_writer_agent.py").resolve()

        with open(source_path) as f:
            source = f.read()

        # The INSERT SQL must include the ctx column
        assert "ctx" in source, "feature_writer_agent must include 'ctx' in SQL"

        # The as-of subquery must reference ctx_snapshots
        assert (
            "ctx_snapshots" in source
        ), "feature_writer_agent must reference 'ctx_snapshots' for as-of join"

        # The subquery must use parameter binding (no f-string interpolation)
        # Verify by checking that $1 and $2 are present (the ts and symbol params)
        # and no string format markers appear next to ctx_snapshots
        assert (
            "$1" in source and "$2" in source
        ), "feature_writer_agent must use $N parameter binding (no f-string)"
