"""Unit tests for kafka_init_topics.py topic creation script (Wave 0 stubs)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from production.scripts.kafka_init_topics import create_topics


@pytest.mark.asyncio
async def test_create_topics_calls_admin_client() -> None:
    """create_topics() calls AIOKafkaAdminClient.start() then create_topics() with 11 NewTopic objects."""
    mock_admin = AsyncMock()
    mock_admin.start = AsyncMock()
    mock_admin.create_topics = AsyncMock()
    mock_admin.close = AsyncMock()

    with patch(
        "production.scripts.kafka_init_topics.AIOKafkaAdminClient", return_value=mock_admin
    ) as mock_cls:
        await create_topics("localhost:19092", env_name="dev")

        mock_cls.assert_called_once_with(bootstrap_servers="localhost:19092")
        mock_admin.start.assert_awaited_once()
        mock_admin.create_topics.assert_awaited_once()

        # Verify exactly 11 topics were passed
        call_args = mock_admin.create_topics.call_args
        topics_list = call_args[0][0]
        assert len(topics_list) == 11


@pytest.mark.asyncio
async def test_create_topics_idempotent() -> None:
    """TopicAlreadyExistsError (and 'already exists' errors) are caught and do not raise."""
    from aiokafka.errors import TopicAlreadyExistsError

    mock_admin = AsyncMock()
    mock_admin.start = AsyncMock()
    mock_admin.create_topics = AsyncMock(side_effect=TopicAlreadyExistsError())
    mock_admin.close = AsyncMock()

    with patch(
        "production.scripts.kafka_init_topics.AIOKafkaAdminClient", return_value=mock_admin
    ):
        # Should not raise
        await create_topics("localhost:19092", env_name="dev")
        mock_admin.close.assert_awaited_once()
