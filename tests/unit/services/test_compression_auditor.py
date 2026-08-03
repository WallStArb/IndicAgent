"""Unit tests for CompressionAuditor (todo 233).

Uses __new__ pattern to bypass __init__ and isolate tested behaviour, same
convention as test_bar_auditor.py. Tests cover:
- _run_audit: no drift found -> no remediation attempted
- _run_audit: drift found -> remediation attempted per hypertable, correct SQL params
- _run_audit: exception is caught, logged, and does not propagate
- _remediate: success path calls CALL run_job(job_id)
- _remediate: one hypertable's failure is isolated and does not raise
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _wire_pool_acquire(conn) -> AsyncMock:
    """Return an AsyncMock pool whose `async with pool.acquire() as conn:` yields
    `conn` — a bare AsyncMock().acquire() returns a coroutine, which does NOT support
    the async context manager protocol, so `.acquire` must be a MagicMock with
    `__aenter__`/`__aexit__` wired explicitly on its return value."""
    mock_pool = AsyncMock()
    mock_pool.acquire = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_pool


def _make_agent_stub():
    """Create a CompressionAuditor via __new__ with minimal attributes for unit tests."""
    from services.compression_auditor import CompressionAuditor

    agent = CompressionAuditor.__new__(CompressionAuditor)
    agent.name = "compression_auditor"
    agent.settings = MagicMock(env_name="development")
    agent.logger = MagicMock()
    agent.logger.warning = MagicMock()
    agent.logger.info = MagicMock()
    agent.logger.error = MagicMock()
    agent._agent_attrs = {"agent": "compression_auditor"}
    agent._last_msg_ts_attrs = {"agent_id": "compression_auditor"}
    agent._config = AsyncMock()
    agent._config.get = AsyncMock(
        side_effect=lambda key, default: {
            "infra.compression_auditor.check_interval_seconds": 21600,
            "infra.compression_auditor.grace_period_hours": 24,
        }.get(key, default)
    )
    return agent


class TestRunAuditNoDrift:
    @pytest.mark.asyncio
    async def test_no_rows_means_no_remediation(self):
        """_run_audit with an empty drift query result attempts zero remediations."""
        agent = _make_agent_stub()
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        agent._db_pool = _wire_pool_acquire(mock_conn)

        with patch.object(agent, "_remediate", new=AsyncMock()) as mock_remediate:
            await agent._run_audit()

        mock_remediate.assert_not_called()
        agent.logger.error.assert_not_called()

    @pytest.mark.asyncio
    async def test_grace_period_passed_as_timedelta(self):
        """The configured grace_period_hours is passed to the drift query as a
        datetime.timedelta — NOT a string. asyncpg's binary protocol negotiates the
        parameter's server-side type from the query's `::interval` cast and encodes
        it via its interval codec, which requires a timedelta-like object; a plain
        string round-trips fine through a mock but raises
        "'str' object has no attribute 'days'" against real asyncpg/Postgres. This
        exact regression shipped once already (caught only by watching the deployed
        daemon's real log output, not by this test suite) — do not weaken this back
        to a string assertion."""
        from datetime import timedelta

        agent = _make_agent_stub()
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        agent._db_pool = _wire_pool_acquire(mock_conn)

        await agent._run_audit()

        call_args = mock_conn.fetch.call_args
        assert call_args[0][1] == timedelta(hours=24.0)
        assert isinstance(call_args[0][1], timedelta)


class TestRunAuditWithDrift:
    @pytest.mark.asyncio
    async def test_drift_rows_trigger_remediation_per_hypertable(self):
        """Each overdue hypertable in the query result gets its own _remediate call."""
        agent = _make_agent_stub()
        rows = [
            {
                "job_id": 1068,
                "hypertable_name": "alpha_events",
                "compress_after": "30 days",
                "overdue_chunks": 79,
            },
            {
                "job_id": 1067,
                "hypertable_name": "ensemble_alpha",
                "compress_after": "30 days",
                "overdue_chunks": 80,
            },
        ]
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=rows)
        agent._db_pool = _wire_pool_acquire(mock_conn)

        with patch.object(agent, "_remediate", new=AsyncMock()) as mock_remediate:
            await agent._run_audit()

        assert mock_remediate.call_count == 2
        called_tables = {c.kwargs["hypertable"] for c in mock_remediate.call_args_list}
        assert called_tables == {"alpha_events", "ensemble_alpha"}

    @pytest.mark.asyncio
    async def test_audit_error_is_caught_and_logged_not_raised(self):
        """A DB failure in _run_audit is caught, logged, and does not propagate."""
        agent = _make_agent_stub()
        agent._db_pool = MagicMock()
        agent._db_pool.acquire = MagicMock(side_effect=RuntimeError("connection lost"))

        await agent._run_audit()  # must not raise

        agent.logger.error.assert_called_once()
        assert agent.logger.error.call_args[0][0] == "compression_auditor.audit_error"


class TestRemediate:
    @pytest.mark.asyncio
    async def test_success_calls_run_job_with_job_id(self):
        """_remediate issues CALL run_job($1) with the hypertable's job_id."""
        agent = _make_agent_stub()
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        pool = _wire_pool_acquire(mock_conn)

        await agent._remediate(conn_pool=pool, hypertable="alpha_events", job_id=1068)

        mock_conn.execute.assert_called_once_with("CALL run_job($1)", 1068)
        agent.logger.info.assert_called_once()
        assert agent.logger.info.call_args[0][0] == "compression_auditor.remediation_complete"

    @pytest.mark.asyncio
    async def test_failure_is_isolated_and_does_not_raise(self):
        """One hypertable's remediation failure is logged, not re-raised."""
        agent = _make_agent_stub()
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(side_effect=RuntimeError("lock timeout"))
        pool = _wire_pool_acquire(mock_conn)

        await agent._remediate(
            conn_pool=pool, hypertable="ensemble_alpha", job_id=1067
        )  # must not raise

        agent.logger.error.assert_called_once()
        assert agent.logger.error.call_args[0][0] == "compression_auditor.remediation_error"

    @pytest.mark.asyncio
    async def test_one_failing_hypertable_does_not_block_others(self):
        """_run_audit remediates every drifted hypertable even if an earlier one fails."""
        agent = _make_agent_stub()
        rows = [
            {"job_id": 1, "hypertable_name": "a", "compress_after": "7 days", "overdue_chunks": 1},
            {"job_id": 2, "hypertable_name": "b", "compress_after": "7 days", "overdue_chunks": 1},
        ]
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=rows)
        agent._db_pool = _wire_pool_acquire(mock_conn)

        real_remediate = agent._remediate

        async def _flaky_remediate(*, conn_pool, hypertable, job_id):
            if hypertable == "a":
                raise RuntimeError("boom")
            await real_remediate(conn_pool=conn_pool, hypertable=hypertable, job_id=job_id)

        with patch.object(agent, "_remediate", new=AsyncMock(side_effect=_flaky_remediate)):
            await agent._run_audit()  # must not raise despite "a" failing

        # "a"'s failure is isolated to its own row and logged distinctly...
        assert any(
            call.args[0] == "compression_auditor.row_processing_error"
            for call in agent.logger.error.call_args_list
        )
        # ...while "b" still got remediated in the same cycle (not skipped/blocked).
        assert any(
            call.args[0] == "compression_auditor.remediation_complete"
            for call in agent.logger.info.call_args_list
        )
