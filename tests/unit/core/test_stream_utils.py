"""Unit tests for src.core.stream_utils.ensure_consumer_group_with_reset.

Covers the boolean return contract that signal_generator_service depends on
to decide whether to rewind warmup bars.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
import redis.asyncio as redis

from src.core.stream_utils import ensure_consumer_group_with_reset

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fresh_creation_returns_true():
    """xgroup_create succeeds → returns True; xgroup_setid is NOT called."""
    mock_client = AsyncMock()
    mock_client.xgroup_create = AsyncMock(return_value=True)
    mock_client.xgroup_setid = AsyncMock()

    result = await ensure_consumer_group_with_reset(
        mock_client, "indicators:ES:1m", "test_group"
    )

    assert result is True
    mock_client.xgroup_create.assert_awaited_once_with(
        "indicators:ES:1m", "test_group", "$", mkstream=True
    )
    mock_client.xgroup_setid.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_busygroup_returns_false_and_resets():
    """xgroup_create raises BUSYGROUP → returns False; xgroup_setid called with correct args."""
    mock_client = AsyncMock()
    mock_client.xgroup_create = AsyncMock(
        side_effect=redis.ResponseError("BUSYGROUP Consumer Group name already exists")
    )
    mock_client.xgroup_setid = AsyncMock()

    result = await ensure_consumer_group_with_reset(
        mock_client, "indicators:ES:1m", "test_group", start_id="$"
    )

    assert result is False
    mock_client.xgroup_setid.assert_awaited_once_with(
        "indicators:ES:1m", "test_group", "$"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_non_busygroup_error_is_reraised():
    """Non-BUSYGROUP ResponseError is re-raised; xgroup_setid NOT called."""
    mock_client = AsyncMock()
    mock_client.xgroup_create = AsyncMock(
        side_effect=redis.ResponseError("WRONGTYPE Operation against a key holding the wrong kind")
    )
    mock_client.xgroup_setid = AsyncMock()

    with pytest.raises(redis.ResponseError, match="WRONGTYPE"):
        await ensure_consumer_group_with_reset(
            mock_client, "indicators:ES:1m", "test_group"
        )

    mock_client.xgroup_setid.assert_not_awaited()
