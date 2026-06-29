"""Tests for BaseBatch._setup_pool JSONB codec registration.

Verifies that BaseBatch._setup_pool calls database_manager.create_pool (which registers
JSONB codecs and pool metrics) rather than bare asyncpg.create_pool (which leaves JSONB
unregistered and silently passes bytes-type values instead of dicts).

The CLAUDE.md invariant: asyncpg JSONB -> dict (no json.dumps/json.loads). Any code path
that calls bare asyncpg.create_pool bypasses the codec and breaks this invariant.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.agent.base_batch import BaseBatch


class _ConcreteBaseBatch(BaseBatch):
    """Minimal concrete subclass for testing BaseBatch lifecycle."""

    job_name = "test-job"
    compute_version = "0.0.1"

    async def execute(self, pool) -> None:
        pass


# ---------------------------------------------------------------------------
# Test: _setup_pool uses database_manager.create_pool, not bare asyncpg.create_pool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_setup_pool_uses_database_manager_create_pool():
    """_setup_pool must delegate to database_manager.create_pool.

    Rationale: database_manager.create_pool registers JSONB codecs via init=_setup_codecs
    and emits pool size gauges. Bare asyncpg.create_pool skips both, leaving JSONB
    unregistered — asyncpg then raises a codec error or silently passes bytes on JSONB
    column writes instead of dict.
    """
    batch = _ConcreteBaseBatch(db_dsn="postgresql://test/db")
    mock_pool = MagicMock()

    with (
        patch("src.core.agent.base_batch.create_pool", new_callable=AsyncMock) as mock_create_pool,
        patch("asyncpg.create_pool", new_callable=AsyncMock) as mock_bare_asyncpg,
    ):
        mock_create_pool.return_value = mock_pool
        await batch._setup_pool()

        # Must have called create_pool from database_manager
        mock_create_pool.assert_called_once()
        call_kwargs = mock_create_pool.call_args

        # First positional arg is the DSN
        assert (
            call_kwargs.args[0] == "postgresql://test/db"
            or call_kwargs.kwargs.get("database_url") == "postgresql://test/db"
        )

        # pool_name must be set (database_manager.create_pool uses it for gauge labels)
        assert call_kwargs.kwargs.get("pool_name") == "test-job"

        # Bare asyncpg.create_pool must NOT have been called
        mock_bare_asyncpg.assert_not_called()

    assert batch._pool is mock_pool


@pytest.mark.asyncio
async def test_setup_pool_does_not_call_bare_asyncpg():
    """Verify bare asyncpg.create_pool is never called by _setup_pool.

    This is the complement to test_setup_pool_uses_database_manager_create_pool —
    it checks the negative: no stray asyncpg.create_pool call escapes the database_manager
    wrapper.
    """
    batch = _ConcreteBaseBatch(db_dsn="postgresql://test/db")

    with (
        patch("src.core.agent.base_batch.create_pool", new_callable=AsyncMock) as mock_dm_create,
        patch("asyncpg.create_pool", new_callable=AsyncMock) as mock_bare,
    ):
        mock_dm_create.return_value = MagicMock()
        await batch._setup_pool()
        mock_bare.assert_not_called()
