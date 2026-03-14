"""Unit tests for KafkaProducerClient and KafkaConsumerClient (Wave 0 stubs)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient


@pytest.mark.asyncio
async def test_producer_client_start_and_stop() -> None:
    """KafkaProducerClient.start() creates and starts AIOKafkaProducer; stop() stops it."""
    mock_producer = AsyncMock()

    with patch("src.core.kafka_utils.AIOKafkaProducer", return_value=mock_producer) as mock_cls:
        client = KafkaProducerClient(bootstrap_servers="localhost:19092")
        await client.start()
        mock_cls.assert_called_once_with(bootstrap_servers="localhost:19092")
        mock_producer.start.assert_awaited_once()

        await client.stop()
        mock_producer.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_producer_client_publish() -> None:
    """publish() calls send_and_wait with correct topic, JSON-encoded value, and key bytes."""
    mock_producer = AsyncMock()

    with patch("src.core.kafka_utils.AIOKafkaProducer", return_value=mock_producer):
        client = KafkaProducerClient(bootstrap_servers="localhost:19092")
        await client.start()

        msg = {"symbol": "ES", "tf": "1m", "rsi_14": 58.3}
        await client.publish("dev.indicators", msg, key="ES:1m")

        mock_producer.send_and_wait.assert_awaited_once()
        call_args = mock_producer.send_and_wait.call_args
        assert call_args[0][0] == "dev.indicators"
        assert call_args[1]["value"] == json.dumps(msg).encode()
        assert call_args[1]["key"] == b"ES:1m"


@pytest.mark.asyncio
async def test_consumer_client_start_and_stop() -> None:
    """KafkaConsumerClient.start() starts AIOKafkaConsumer; stop() stops it."""
    mock_consumer = AsyncMock()

    with patch("src.core.kafka_utils.AIOKafkaConsumer", return_value=mock_consumer):
        client = KafkaConsumerClient(
            "dev.indicators",
            bootstrap_servers="localhost:19092",
            group_id="test_group",
        )
        await client.start()
        mock_consumer.start.assert_awaited_once()

        await client.stop()
        mock_consumer.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_consumer_client_messages_yields_tuples() -> None:
    """messages() yields (topic, key_str, payload_dict); key is None when msg.key is None."""
    mock_msg_with_key = MagicMock()
    mock_msg_with_key.topic = "dev.indicators"
    mock_msg_with_key.key = b"ES:1m"
    mock_msg_with_key.value = json.dumps({"rsi_14": 58.3}).encode()

    mock_msg_no_key = MagicMock()
    mock_msg_no_key.topic = "dev.llm.calls"
    mock_msg_no_key.key = None
    mock_msg_no_key.value = json.dumps({"model": "qwen"}).encode()

    async def mock_aiter(self):  # type: ignore[override]
        yield mock_msg_with_key
        yield mock_msg_no_key

    mock_consumer = AsyncMock()
    mock_consumer.__aiter__ = mock_aiter

    with patch("src.core.kafka_utils.AIOKafkaConsumer", return_value=mock_consumer):
        client = KafkaConsumerClient(
            "dev.indicators",
            bootstrap_servers="localhost:19092",
            group_id="test_group",
        )
        await client.start()

        results = []
        async for item in client.messages():
            results.append(item)

        assert len(results) == 2
        topic1, key1, payload1 = results[0]
        assert topic1 == "dev.indicators"
        assert key1 == "ES:1m"
        assert payload1 == {"rsi_14": 58.3}

        topic2, key2, payload2 = results[1]
        assert topic2 == "dev.llm.calls"
        assert key2 is None
        assert payload2 == {"model": "qwen"}
