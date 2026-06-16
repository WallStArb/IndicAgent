"""Unit tests for LifecycleWriter.

Uses ServiceClass.__new__(ServiceClass) pattern to bypass __init__ (per CLAUDE.md).
Tests structural contract, buffer accumulation, flush grouping by transition type,
error handling, and buffer preservation on failure.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_agent():
    """Build a minimal LifecycleWriter bypassing __init__."""
    from services.lifecycle_writer import LifecycleWriter

    agent = LifecycleWriter.__new__(LifecycleWriter)
    agent.logger = MagicMock()
    agent._settings = MagicMock()
    agent._settings.database_url = "postgresql://postgres@localhost/indicagent"
    agent._settings.kafka_bootstrap_servers = "localhost:19092"
    agent._settings.env_name = "development"
    agent._db = MagicMock()
    agent._db.execute_command = AsyncMock(return_value="UPDATE 1")
    agent._consumer = AsyncMock()
    agent._repo = MagicMock()
    agent._repo.batch_execute = AsyncMock()
    agent._repo.update_signal_status = AsyncMock()
    agent._repo.update_frame_details = AsyncMock()
    agent._buffer = []
    agent._last_flush = 0.0
    agent._events_consumed = MagicMock()
    agent._transitions_written = MagicMock()
    agent._write_errors = MagicMock()
    agent._batch_latency_attrs = {"agent_id": "lifecycle_writer_agent"}
    agent._consumer_lag = MagicMock()
    agent._buffer_depth_gauge = MagicMock()
    agent._buffer_overflow_total = MagicMock()
    agent._flush_latency = MagicMock()
    agent._commit_latency = MagicMock()
    agent._parse_failures_total = MagicMock()
    agent._flush_errors_total = MagicMock()
    agent._commit_errors_total = MagicMock()
    # Tracer required by BaseWriter._do_flush() span context manager
    span_ctx = MagicMock()
    span_ctx.__enter__ = MagicMock(return_value=MagicMock())
    span_ctx.__exit__ = MagicMock(return_value=False)
    agent.tracer = MagicMock()
    agent.tracer.start_as_current_span = MagicMock(return_value=span_ctx)
    return agent


def _make_transition(
    transition_type: str = "activation",
    signal_id: str = "sig-001",
    symbol: str = "ES",
    timeframe: str = "1m",
    data: dict | None = None,
) -> dict:
    """Build a minimal lifecycle transition dict (as consumed from Kafka)."""
    return {
        "transition_type": transition_type,
        "signal_id": signal_id,
        "symbol": symbol,
        "timeframe": timeframe,
        "bar_ts": datetime.now(UTC).isoformat(),
        "data": data or {},
    }


# ---------------------------------------------------------------------------
# Structural contract — read source and assert patterns
# ---------------------------------------------------------------------------


class TestLifecycleWriterStructure:
    def test_class_name(self):
        source = open("services/lifecycle_writer.py").read()
        assert "LifecycleWriter" in source

    def test_inherits_base_writer_agent(self):
        source = open("services/lifecycle_writer.py").read()
        assert "BaseWriter" in source

    def test_no_compute_logic(self):
        """WriterAgent must contain zero lifecycle evaluation logic."""
        source = open("services/lifecycle_writer.py").read()
        assert "evaluate_signal" not in source
        assert "compute_chandelier" not in source

    def test_uses_signal_events_repository(self):
        """lifecycle_writer now imports SignalEventsRepository (3-table schema)."""
        source = open("services/lifecycle_writer.py").read()
        assert "SignalEventsRepository" in source
        assert "update_signal_status" in source
        assert "update_frame_details" in source


# ---------------------------------------------------------------------------
# Buffer accumulation
# ---------------------------------------------------------------------------


class TestBufferAccumulation:
    def test_buffer_accumulates_transitions(self):
        agent = _make_agent()
        agent._buffer.append(_make_transition("activation", "sig-001"))
        agent._buffer.append(_make_transition("exit", "sig-002"))
        assert len(agent._buffer) == 2

    def test_buffer_starts_empty(self):
        agent = _make_agent()
        assert len(agent._buffer) == 0


# ---------------------------------------------------------------------------
# Flush behavior — grouping by type (via _flush_batch)
# ---------------------------------------------------------------------------


class TestFlushGroupsByType:
    @pytest.mark.asyncio
    async def test_flush_groups_by_type(self):
        """Phase 130: activation and exit route through update_signal_status/update_frame_details.

        Two activations + one exit: both handled by _flush_activation_items and
        _flush_exit_items respectively, which call update_signal_status + update_frame_details.
        batch_execute is used for chandelier_update, mae_mfe_update, shadow_outcome,
        market_resolution only.
        """
        agent = _make_agent()
        agent._repo.update_signal_status = AsyncMock()
        agent._repo.update_frame_details = AsyncMock()
        batch = [
            _make_transition("activation", "sig-001", data={"activation_price": 100.0}),
            _make_transition("exit", "sig-002", data={"exit_price": 105.0, "status": "expired"}),
            _make_transition("activation", "sig-003", data={"activation_price": 200.0}),
        ]
        await agent._flush_batch(batch)

        # Phase 130: activation calls update_signal_status("active") per item
        # exit calls update_signal_status(status) per item
        # Total: 2 activation status + 1 exit status = 3 update_signal_status calls
        assert agent._repo.update_signal_status.await_count == 3
        # batch_execute not called for activation or exit (they use dedicated methods now)
        assert agent._repo.batch_execute.await_count == 0

    @pytest.mark.asyncio
    async def test_do_flush_clears_buffer_on_success(self):
        agent = _make_agent()
        agent._buffer.append(_make_transition("activation", "sig-001"))
        await agent._do_flush()
        assert len(agent._buffer) == 0

    @pytest.mark.asyncio
    async def test_do_flush_empty_buffer_is_noop(self):
        agent = _make_agent()
        await agent._do_flush()
        agent._repo.batch_execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_do_flush_handles_db_error_buffer_preserved(self):
        """Phase 130: update_signal_status raising leaves buffer intact for retry."""
        agent = _make_agent()
        agent._repo.update_signal_status = AsyncMock(side_effect=Exception("db down"))
        agent._buffer.extend(
            [
                _make_transition("activation", "sig-001"),
                _make_transition("exit", "sig-002"),
            ]
        )
        await agent._do_flush()
        # Buffer should NOT be cleared on error (BaseWriter._do_flush retry logic)
        assert len(agent._buffer) == 2


# ---------------------------------------------------------------------------
# batch_execute on repository
# ---------------------------------------------------------------------------


class TestSignalLedgerRepositoryBatchExecute:
    """Tests for SignalEventsRepository.batch_execute (Phase 130: 3-table schema).

    Phase 130 rewrite: batch_execute now routes lifecycle transitions to
    update_signal_status (signal_events) + update_frame_details (trade_frames.frame_details)
    via execute_command per item, not execute_batch SQL.
    """

    def _make_repo(self):
        from src.persistence.repository.signal_ledger_repository import (
            SignalLedgerRepository,
        )

        db = MagicMock()
        db.execute_command = AsyncMock()
        db.execute_batch = AsyncMock()
        return SignalLedgerRepository(db), db

    @pytest.mark.asyncio
    async def test_batch_execute_activation_calls_execute_command(self):
        """Activation transitions update signal_events.status + trade_frames.frame_details."""
        repo, db = self._make_repo()
        now = datetime.now(UTC)
        items = [
            {
                "signal_id": "sig-001",
                "activated_at": now,
                "activation_price": 5000.0,
                "zone_entry_pct": 0.5,
                "bars_to_activation": 3,
            }
        ]
        await repo.batch_execute("activation", items)
        # Two execute_command calls: update_signal_status + update_frame_details
        assert db.execute_command.await_count == 2

    @pytest.mark.asyncio
    async def test_batch_execute_exit_calls_execute_command(self):
        """Exit transitions update signal_events.status."""
        repo, db = self._make_repo()
        now = datetime.now(UTC)
        items = [
            {
                "signal_id": "sig-001",
                "status": "expired",
                "exit_at": now,
                "exit_price": 5010.0,
                "exit_reason": "ttl_expired",
                "pnl_r": 0.5,
                "pnl_dollars": 100.0,
                "signal_quality": 0.7,
                "mae": -0.3,
                "mfe": 0.8,
                "bars_in_trade": 10,
                "outcome": "target_1",
            }
        ]
        await repo.batch_execute("exit", items)
        # At least one execute_command call for status update
        assert db.execute_command.await_count >= 1

    @pytest.mark.asyncio
    async def test_batch_execute_empty_items_is_noop(self):
        repo, db = self._make_repo()
        await repo.batch_execute("activation", [])
        db.execute_command.assert_not_awaited()
        db.execute_batch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_batch_execute_chandelier_update(self):
        """chandelier_update transitions persist to trade_frames.frame_details."""
        repo, db = self._make_repo()
        items = [
            {
                "signal_id": "sig-001",
                "trailing_stop_price": [{"ts": "2026-01-01T00:00:00Z", "price": 4990.0}],
                "trailing_stop_tightening_rate": 0.02,
                "staleness_score": 0.5,
                "staleness_trigger_reason": "no_new_high",
                "chandelier_vol_source": "garch_sigma",
            }
        ]
        await repo.batch_execute("chandelier_update", items)
        # update_frame_details called via execute_command
        assert db.execute_command.await_count >= 1

    @pytest.mark.asyncio
    async def test_batch_execute_mae_mfe_update(self):
        """mae_mfe_update transitions persist to trade_frames.frame_details."""
        repo, db = self._make_repo()
        items = [
            {
                "signal_id": "sig-001",
                "mae": -0.3,
                "mfe": 0.8,
            }
        ]
        await repo.batch_execute("mae_mfe_update", items)
        assert db.execute_command.await_count >= 1

    @pytest.mark.asyncio
    async def test_batch_execute_shadow_outcome(self):
        """shadow_outcome transitions persist to trade_frames.frame_details."""
        repo, db = self._make_repo()
        now = datetime.now(UTC)
        items = [
            {
                "signal_id": "sig-001",
                "shadow_tracking_start_ts": now,
                "shadow_mae": -0.2,
                "shadow_mfe": 0.5,
                "shadow_outcome": "target_1",
            }
        ]
        await repo.batch_execute("shadow_outcome", items)
        assert db.execute_command.await_count >= 1

    @pytest.mark.asyncio
    async def test_batch_execute_unknown_type_raises(self):
        """Unknown transition type should raise ValueError."""
        repo, db = self._make_repo()
        with pytest.raises(ValueError, match="Unknown transition_type"):
            await repo.batch_execute("unknown_type", [{"signal_id": "sig-001"}])
