"""Tests for ContextWriter — validation, persistence, and JSONB safety.

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

from services.context_writer import (
    _ALLOWED_EVENT_TYPES,
    _MAX_PAYLOAD_BYTES,
    ContextWriter,
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


def _make_agent() -> ContextWriter:
    """Instantiate ContextWriter without starting it (no DB, no Kafka)."""
    agent = ContextWriter.__new__(ContextWriter)
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
        valid, invalid = agent._parse_payload(msg)
        assert valid, "Valid message should pass validation"
        assert not invalid

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

        valid, invalid = agent._parse_payload(msg)

        assert not valid, "Disallowed event_type must return empty valid"
        assert invalid, "Disallowed event_type must return non-empty invalid"
        agent._validation_errors.add.assert_called()

    def test_allowed_event_types_pass(self):
        agent = _make_agent()
        for etype in sorted(_ALLOWED_EVENT_TYPES):
            msg = _make_valid_message(event_type=etype)
            valid, invalid = agent._parse_payload(msg)
            assert valid, f"Allowed event_type '{etype}' should pass"


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

        valid, invalid = agent._parse_payload(msg)

        assert not valid, "Oversized payload must return empty valid"
        assert invalid, "Oversized payload must return non-empty invalid"
        agent._validation_errors.add.assert_called()

    def test_borderline_payload_within_limit_passes(self):
        agent = _make_agent()
        # A payload near but under the limit should pass
        # json.dumps adds ~12 bytes for {"data": "..."} wrapper
        safe_data = "x" * (_MAX_PAYLOAD_BYTES - 20)
        msg = _make_valid_message()
        msg["payload"] = {"data": safe_data}

        valid, invalid = agent._parse_payload(msg)
        assert valid, "Payload within limit should pass"


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

        valid, invalid = agent._parse_payload(msg)

        assert not valid, f"Message missing '{missing_key}' must be rejected"
        assert invalid, f"Message missing '{missing_key}' must have invalid"
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


# ---------------------------------------------------------------------------
# Phase-105 regression: .add() not .inc() on write counters, super()._teardown() called
# ---------------------------------------------------------------------------


class TestCtxWriterFlushUsesAdd:
    """Regression: _flush() must call .add() on write counters, never .inc().

    Phase-105 HF-2: OTel counters expose .add() not .inc(). Calling .inc()
    would raise AttributeError at runtime.
    """

    @pytest.mark.asyncio
    async def test_flush_calls_add_not_inc_on_events_written(self):
        """_flush() calls self._events_written.add(n), never .inc()."""
        agent = _make_agent()

        # Replace write counters with fresh Mocks so we can assert call patterns
        mock_events_written = MagicMock()
        mock_snapshots_written = MagicMock()
        agent._events_written = mock_events_written
        agent._snapshots_written = mock_snapshots_written

        # Build a minimal flush environment — mock the pool/conn
        mock_conn = AsyncMock()
        mock_transaction = AsyncMock()
        mock_transaction.__aenter__ = AsyncMock(return_value=None)
        mock_transaction.__aexit__ = AsyncMock(return_value=False)
        mock_conn.transaction = MagicMock(return_value=mock_transaction)
        mock_conn.executemany = AsyncMock()
        mock_pool = MagicMock()
        mock_pool_ctx = MagicMock()
        mock_pool_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_pool.acquire = MagicMock(return_value=mock_pool_ctx)

        agent._db = MagicMock()
        agent._db.pool = mock_pool

        # One event row in the batch
        event_batch = [(None, "ES", "earnings", "test", {})]
        snapshot_batch: list = []

        await agent._flush(event_batch, snapshot_batch)

        # .add() must have been called with the batch length
        mock_events_written.add.assert_called_once_with(1)
        # .inc() must NEVER be called
        assert (
            not mock_events_written.inc.called
        ), "OTel counter must use .add(), never .inc() — .inc() does not exist on OTel counters"

    @pytest.mark.asyncio
    async def test_flush_calls_add_not_inc_on_snapshots_written(self):
        """_flush() calls self._snapshots_written.add(n), never .inc()."""
        agent = _make_agent()

        mock_events_written = MagicMock()
        mock_snapshots_written = MagicMock()
        agent._events_written = mock_events_written
        agent._snapshots_written = mock_snapshots_written

        mock_conn = AsyncMock()
        mock_transaction = AsyncMock()
        mock_transaction.__aenter__ = AsyncMock(return_value=None)
        mock_transaction.__aexit__ = AsyncMock(return_value=False)
        mock_conn.transaction = MagicMock(return_value=mock_transaction)
        mock_conn.executemany = AsyncMock()
        mock_pool = MagicMock()
        mock_pool_ctx = MagicMock()
        mock_pool_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_pool.acquire = MagicMock(return_value=mock_pool_ctx)

        agent._db = MagicMock()
        agent._db.pool = mock_pool

        event_batch: list = []
        # One snapshot row (symbol, event_type, valid_from, ctx_dict)
        snapshot_batch = [("ES", "earnings", "2026-01-01T00:00:00Z", {})]

        await agent._flush(event_batch, snapshot_batch)

        # .add() must have been called with batch length
        mock_snapshots_written.add.assert_called_once_with(1)
        assert not mock_snapshots_written.inc.called, "OTel counter must use .add(), never .inc()"


class TestCtxWriterTeardownCallsSuper:
    """Regression: _teardown() must call super()._teardown() first.

    Phase-105 HF-11: missing super()._teardown() means BaseWriter's final
    flush and lifecycle cleanup never runs, leaving uncommitted messages.
    """

    @pytest.mark.asyncio
    async def test_teardown_calls_super_teardown(self):
        """_teardown() must invoke super()._teardown() (base lifecycle cleanup)."""
        import inspect

        import services.context_writer as mod

        source = inspect.getsource(mod.ContextWriter._teardown)
        # The fixed version calls super()._teardown()
        assert "super()._teardown()" in source, (
            "ContextWriter._teardown() must call super()._teardown() "
            "to trigger BaseWriter final flush and lifecycle cleanup"
        )

        # Also confirm it is the FIRST await (order matters: base cleanup before custom flush)
        lines = [ln.strip() for ln in source.splitlines() if ln.strip()]
        # Find the first non-docstring meaningful line; strip inline comments
        await_lines = [ln.split("#")[0].rstrip() for ln in lines if ln.startswith("await")]
        assert await_lines, "No await statements in _teardown()"
        assert await_lines[0] == "await super()._teardown()", (
            "super()._teardown() must be the FIRST await in _teardown() "
            f"so BaseWriter flush runs before custom buffer flush; got: {await_lines[0]!r}"
        )


class TestFeatureWriterInsertIncludesCtx:
    """Verifies FeatureVectorWriter (v3.0) INSERT targets feature_vectors, not intelligence_features.

    Updated in 138-P0: feature_writer.py renamed to feature_vector_writer.py.
    v3.0 writes to feature_vectors (54 typed float columns + feature_vector_id UUID).
    The ctx_snapshots as-of join pattern belongs to the v2.x intelligence_features path,
    which was archived in Phase 137.
    """

    def test_feature_writer_insert_includes_ctx_column(self):
        import pathlib

        # Load writer module source to confirm it references the canonical persistence module
        writer_source_path = pathlib.Path("services/feature_vector_writer.py").resolve()
        with open(writer_source_path) as f:
            writer_source = f.read()

        # The writer must reference the feature_vectors table (via import or constant)
        assert (
            "feature_vectors" in writer_source
        ), "feature_vector_writer must INSERT into feature_vectors (v3.0 write path)"

        # The writer delegates SQL to feature_vector_persistence — check that module
        # for $N parameter binding and feature_vector_id (canonical single source of truth).
        persistence_path = pathlib.Path(
            "src/intelligence/features/feature_vector_persistence.py"
        ).resolve()
        with open(persistence_path) as f:
            persistence_source = f.read()

        # Canonical INSERT SQL must use positional parameter binding ($N)
        assert (
            "$1" in persistence_source
        ), "feature_vector_persistence must use $N parameter binding in INSERT SQL"

        # Must include feature_vector_id (content-key, added in 138-P0)
        assert (
            "feature_vector_id" in persistence_source
        ), "feature_vector_persistence must include feature_vector_id column (138-P0)"
