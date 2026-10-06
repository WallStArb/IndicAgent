"""Tests for BaseBatch._emit_completion metric emission.

Covers the job_duration_seconds histogram added alongside the existing
job_completed_total counter (D-06). Both must fire with identical {job, status}
attrs on success AND on failure -- _emit_completion runs in run()'s finally
block specifically so a crashed job still reports its duration, not just a
silent gap in the timeline.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.agent.base_batch import BaseBatch
from tests.unit.test_base_batch_jsonb import _ConcreteBaseBatch


@pytest.mark.asyncio
async def test_emit_completion_records_duration_on_success():
    batch = _ConcreteBaseBatch(db_dsn="postgresql://test/db")

    with (
        patch("src.core.agent.base_batch.create_pool", new_callable=AsyncMock) as mock_pool,
        patch("src.core.agent.base_batch.JOB_COMPLETED_TOTAL") as mock_completed,
        patch("src.core.agent.base_batch.JOB_DURATION_SECONDS") as mock_duration,
        patch("src.core.agent.base_batch.flush_and_shutdown_metrics"),
    ):
        mock_pool.return_value = MagicMock(close=AsyncMock())
        await batch.run()

    mock_completed.add.assert_called_once_with(1, {"job": "test-job", "status": "success"})
    mock_duration.record.assert_called_once()
    args, _ = mock_duration.record.call_args
    elapsed_s, attrs = args
    assert elapsed_s >= 0
    assert attrs == {"job": "test-job", "status": "success"}


@pytest.mark.asyncio
async def test_emit_completion_records_duration_on_failure():
    """Duration must still be recorded when execute() raises -- run()'s finally
    block calls _emit_completion regardless of outcome, so a crashed job is
    just as visible in the duration timeline as a successful one."""
    batch = _ConcreteBaseBatch(db_dsn="postgresql://test/db", should_fail=True)

    with (
        patch("src.core.agent.base_batch.create_pool", new_callable=AsyncMock) as mock_pool,
        patch("src.core.agent.base_batch.JOB_COMPLETED_TOTAL") as mock_completed,
        patch("src.core.agent.base_batch.JOB_DURATION_SECONDS") as mock_duration,
        patch("src.core.agent.base_batch.flush_and_shutdown_metrics"),
    ):
        mock_pool.return_value = MagicMock(close=AsyncMock())
        with pytest.raises(RuntimeError, match="boom"):
            await batch.run()

    mock_completed.add.assert_called_once_with(1, {"job": "test-job", "status": "failure"})
    mock_duration.record.assert_called_once()
    args, _ = mock_duration.record.call_args
    elapsed_s, attrs = args
    assert elapsed_s >= 0
    assert attrs == {"job": "test-job", "status": "failure"}


class _StatusBatch(BaseBatch):
    """execute() reports a normal finish that is not plain success (phase 189 plan 04)."""

    job_name = "status-job"
    compute_version = "0.0.1"

    def __init__(self, db_dsn: str, status: str | None, fail: bool = False) -> None:
        super().__init__(db_dsn)
        self._status = status
        self._fail = fail

    async def execute(self, pool) -> None:
        self.completion_status = self._status
        if self._fail:
            raise RuntimeError("boom")


async def _run_capturing(batch: BaseBatch) -> MagicMock:
    with (
        patch("src.core.agent.base_batch.create_pool", new_callable=AsyncMock) as mock_pool,
        patch("src.core.agent.base_batch.JOB_COMPLETED_TOTAL") as mock_completed,
        patch("src.core.agent.base_batch.JOB_DURATION_SECONDS"),
        patch("src.core.agent.base_batch.flush_and_shutdown_metrics"),
    ):
        mock_pool.return_value = MagicMock(close=AsyncMock())
        try:
            await batch.run()
        except RuntimeError:
            pass
    return mock_completed


@pytest.mark.asyncio
async def test_completion_status_defaults_to_success_when_unset():
    mock_completed = await _run_capturing(_StatusBatch("postgresql://test/db", None))
    mock_completed.add.assert_called_once_with(1, {"job": "status-job", "status": "success"})


@pytest.mark.asyncio
async def test_completion_status_set_by_execute_is_emitted():
    mock_completed = await _run_capturing(_StatusBatch("postgresql://test/db", "lock_held"))
    mock_completed.add.assert_called_once_with(1, {"job": "status-job", "status": "lock_held"})


@pytest.mark.asyncio
async def test_completion_status_is_ignored_when_execute_raises():
    mock_completed = await _run_capturing(
        _StatusBatch("postgresql://test/db", "partial", fail=True)
    )
    mock_completed.add.assert_called_once_with(1, {"job": "status-job", "status": "failure"})
