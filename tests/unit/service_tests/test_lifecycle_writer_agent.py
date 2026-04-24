"""Unit tests for LifecycleWriterAgent.

Uses ServiceClass.__new__(ServiceClass) pattern to bypass __init__ (per CLAUDE.md).
Tests structural contract, buffer accumulation, flush grouping by transition type,
error handling, and buffer preservation on failure.
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from prometheus_client import Counter, Gauge, Histogram

# Module-level test metrics to avoid duplicate registration
_TEST_EVENTS = Counter("test_lwa_events_total", "Events (test)")
_TEST_WRITTEN = Counter("test_lwa_written_total", "Transitions written (test)")
_TEST_ERRORS = Counter("test_lwa_errors_total", "Errors (test)")
_TEST_LATENCY = Histogram("test_lwa_latency_seconds", "Latency (test)", ["agent_id"])
_TEST_LAG = Gauge("test_lwa_lag", "Lag (test)", ["agent_id"])
_TEST_DEPTH = Gauge("test_lwa_depth", "Depth (test)")


def _make_agent():
    """Build a minimal LifecycleWriterAgent bypassing __init__."""
    from services.lifecycle_writer_agent import LifecycleWriterAgent

    agent = LifecycleWriterAgent.__new__(LifecycleWriterAgent)
    agent.logger = MagicMock()
    agent._settings = MagicMock()
    agent._settings.database_url = "postgresql://postgres@localhost/indicagent"
    agent._settings.kafka_bootstrap_servers = "localhost:19092"
    agent._settings.env_name = "development"
    agent._db = MagicMock()
    agent._consumer = AsyncMock()
    agent._repo = MagicMock()
    agent._repo.batch_execute = AsyncMock()
    agent._buffer = []
    agent._last_flush = 0.0
    agent._events_consumed = _TEST_EVENTS
    agent._transitions_written = _TEST_WRITTEN
    agent._write_errors = _TEST_ERRORS
    agent._batch_latency = _TEST_LATENCY.labels(agent_id="test")
    agent._consumer_lag = _TEST_LAG.labels(agent_id="test")
    agent._buffer_depth_gauge = _TEST_DEPTH
    agent._buffer_overflow_total = MagicMock()
    agent._flush_latency = MagicMock()
    agent._commit_latency = MagicMock()
    agent._parse_failures_total = MagicMock()
    agent._flush_errors_total = MagicMock()
    agent._commit_errors_total = MagicMock()
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


class TestLifecycleWriterAgentStructure:
    def test_class_name(self):
        source = open("services/lifecycle_writer_agent.py").read()
        assert "LifecycleWriterAgent" in source

    def test_inherits_base_writer_agent(self):
        source = open("services/lifecycle_writer_agent.py").read()
        assert "BaseWriterAgent" in source

    def test_no_compute_logic(self):
        """WriterAgent must contain zero lifecycle evaluation logic."""
        source = open("services/lifecycle_writer_agent.py").read()
        assert "evaluate_signal" not in source
        assert "compute_chandelier" not in source

    def test_uses_signal_ledger_repository(self):
        source = open("services/lifecycle_writer_agent.py").read()
        assert "SignalLedgerRepository" in source


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
        """Two activations + one exit -> two batch_execute calls."""
        agent = _make_agent()
        batch = [
            _make_transition("activation", "sig-001", data={"activation_price": 100.0}),
            _make_transition("exit", "sig-002", data={"exit_price": 105.0}),
            _make_transition("activation", "sig-003", data={"activation_price": 200.0}),
        ]
        await agent._flush_batch(batch)

        # Should be called twice: once for "activation" (2 items), once for "exit" (1 item)
        assert agent._repo.batch_execute.call_count == 2
        calls = agent._repo.batch_execute.call_args_list
        types_called = {c[0][0] for c in calls}
        assert types_called == {"activation", "exit"}
        # Verify counts per group and signal_id merged into data
        for c in calls:
            ttype, items = c[0][0], c[0][1]
            if ttype == "activation":
                assert len(items) == 2
                assert items[0]["signal_id"] == "sig-001"
                assert items[0]["activation_price"] == 100.0
            elif ttype == "exit":
                assert len(items) == 1
                assert items[0]["signal_id"] == "sig-002"
                assert items[0]["exit_price"] == 105.0

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
        agent = _make_agent()
        agent._repo.batch_execute = AsyncMock(side_effect=Exception("db down"))
        agent._buffer.extend([
            _make_transition("activation", "sig-001"),
            _make_transition("exit", "sig-002"),
        ])
        await agent._do_flush()
        # Buffer should NOT be cleared on error
        assert len(agent._buffer) == 2


# ---------------------------------------------------------------------------
# batch_execute on repository
# ---------------------------------------------------------------------------


class TestSignalLedgerRepositoryBatchExecute:
    @pytest.mark.asyncio
    async def test_batch_execute_activation_uses_execute_batch(self):
        """Verify activation transitions use execute_batch with activation SQL."""
        from unittest.mock import MagicMock

        db = MagicMock()
        db.execute_batch = AsyncMock()
        from src.persistence.repository.signal_ledger_repository import (
            SignalLedgerRepository,
        )

        repo = SignalLedgerRepository(db)
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
        db.execute_batch.assert_called_once()
        call_args = db.execute_batch.call_args
        sql = call_args[0][0]
        assert "activation_price" in sql
        assert "activated_at" in sql

    @pytest.mark.asyncio
    async def test_batch_execute_exit_uses_execute_batch(self):
        """Verify exit transitions use execute_batch with exit SQL."""
        from unittest.mock import MagicMock

        db = MagicMock()
        db.execute_batch = AsyncMock()
        from src.persistence.repository.signal_ledger_repository import (
            SignalLedgerRepository,
        )

        repo = SignalLedgerRepository(db)
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
        db.execute_batch.assert_called_once()
        sql = db.execute_batch.call_args[0][0]
        assert "exit_at" in sql
        assert "outcome" in sql

    @pytest.mark.asyncio
    async def test_batch_execute_empty_items_is_noop(self):
        from unittest.mock import MagicMock

        db = MagicMock()
        db.execute_batch = AsyncMock()
        from src.persistence.repository.signal_ledger_repository import (
            SignalLedgerRepository,
        )

        repo = SignalLedgerRepository(db)
        await repo.batch_execute("activation", [])
        db.execute_batch.assert_not_called()

    @pytest.mark.asyncio
    async def test_batch_execute_chandelier_update(self):
        """Verify chandelier_update transitions are handled."""
        from unittest.mock import MagicMock

        db = MagicMock()
        db.execute_batch = AsyncMock()
        from src.persistence.repository.signal_ledger_repository import (
            SignalLedgerRepository,
        )

        repo = SignalLedgerRepository(db)
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
        db.execute_batch.assert_called_once()

    @pytest.mark.asyncio
    async def test_batch_execute_mae_mfe_update(self):
        """Verify mae_mfe_update transitions are handled."""
        from unittest.mock import MagicMock

        db = MagicMock()
        db.execute_batch = AsyncMock()
        from src.persistence.repository.signal_ledger_repository import (
            SignalLedgerRepository,
        )

        repo = SignalLedgerRepository(db)
        items = [
            {
                "signal_id": "sig-001",
                "mae": -0.3,
                "mfe": 0.8,
            }
        ]
        await repo.batch_execute("mae_mfe_update", items)
        db.execute_batch.assert_called_once()
        sql = db.execute_batch.call_args[0][0]
        assert "mae" in sql.lower()

    @pytest.mark.asyncio
    async def test_batch_execute_shadow_outcome(self):
        """Verify shadow_outcome transitions are handled."""
        from unittest.mock import MagicMock

        db = MagicMock()
        db.execute_batch = AsyncMock()
        from src.persistence.repository.signal_ledger_repository import (
            SignalLedgerRepository,
        )

        repo = SignalLedgerRepository(db)
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
        db.execute_batch.assert_called_once()
        sql = db.execute_batch.call_args[0][0]
        assert "shadow_outcome" in sql

    @pytest.mark.asyncio
    async def test_batch_execute_unknown_type_raises(self):
        """Unknown transition type should raise ValueError."""
        from unittest.mock import MagicMock

        db = MagicMock()
        db.execute_batch = AsyncMock()
        from src.persistence.repository.signal_ledger_repository import (
            SignalLedgerRepository,
        )

        repo = SignalLedgerRepository(db)
        with pytest.raises(ValueError, match="Unknown transition_type"):
            await repo.batch_execute("unknown_type", [{"signal_id": "sig-001"}])
