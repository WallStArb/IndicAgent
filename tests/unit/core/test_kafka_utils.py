"""Unit tests for KafkaProducerClient and KafkaConsumerClient (confluent-kafka backed)."""

from __future__ import annotations

import contextlib
from unittest.mock import MagicMock, patch

import orjson
import pytest

from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient, _KafkaHeadersCarrier


def _immediate_delivery(topic, value, key=None, headers=None, on_delivery=None):
    """produce() side_effect that fires on_delivery synchronously, as if the broker
    ack'd instantly -- lets publish()'s `await delivery_future` resolve in tests
    without a real broker."""
    if on_delivery is not None:
        on_delivery(None, MagicMock())


@pytest.mark.asyncio
async def test_producer_client_start_and_stop() -> None:
    """KafkaProducerClient.start() creates confluent_kafka.Producer; stop() flushes it."""
    mock_producer = MagicMock()
    mock_producer.poll.return_value = 0

    with patch("src.core.kafka_utils.Producer", return_value=mock_producer) as mock_cls:
        client = KafkaProducerClient(bootstrap_servers="localhost:19092")
        await client.start()
        mock_cls.assert_called_once_with(
            {
                "bootstrap.servers": "localhost:19092",
                "acks": "all",
                "enable.idempotence": True,
                "compression.type": "lz4",
            }
        )

        await client.stop()
        mock_producer.flush.assert_called_once_with(10.0)


@pytest.mark.asyncio
async def test_producer_client_publish() -> None:
    """publish() calls produce() with correct topic, orjson-encoded value, and key bytes."""
    mock_producer = MagicMock()
    mock_producer.poll.return_value = 0
    mock_producer.produce.side_effect = _immediate_delivery

    with patch("src.core.kafka_utils.Producer", return_value=mock_producer):
        client = KafkaProducerClient(bootstrap_servers="localhost:19092")
        await client.start()

        msg = {"symbol": "ES", "tf": "1m", "rsi_14": 58.3}
        await client.publish("dev.indicators", msg, key="ES:1m")

        mock_producer.produce.assert_called_once()
        call_args = mock_producer.produce.call_args
        assert call_args[0][0] == "dev.indicators"
        assert call_args[1]["value"] == orjson.dumps(msg)
        assert call_args[1]["key"] == b"ES:1m"

        await client.stop()


@pytest.mark.asyncio
async def test_producer_client_publish_serializes_nan_as_null() -> None:
    """orjson silently serializes NaN to `null` (verified empirically against stdlib
    json's non-standard `NaN` literal) -- publish() doesn't need special NaN handling,
    but this pins down the actual on-the-wire behavior so a future orjson upgrade
    changing it would be caught here rather than discovered downstream."""
    mock_producer = MagicMock()
    mock_producer.poll.return_value = 0
    mock_producer.produce.side_effect = _immediate_delivery

    with patch("src.core.kafka_utils.Producer", return_value=mock_producer):
        client = KafkaProducerClient(bootstrap_servers="localhost:19092")
        await client.start()

        await client.publish("dev.indicators", {"rsi_14": float("nan")})

        call_args = mock_producer.produce.call_args
        assert call_args[1]["value"] == b'{"rsi_14":null}'

        await client.stop()


@pytest.mark.asyncio
async def test_consumer_client_start_and_stop() -> None:
    """KafkaConsumerClient.start() subscribes; stop() closes the consumer."""
    mock_consumer = MagicMock()

    with patch("src.core.kafka_utils.Consumer", return_value=mock_consumer):
        client = KafkaConsumerClient(
            "dev.indicators",
            bootstrap_servers="localhost:19092",
            group_id="test_group",
        )
        await client.start()
        mock_consumer.subscribe.assert_called_once_with(["dev.indicators"])

        await client.stop()
        mock_consumer.close.assert_called_once()


@pytest.mark.asyncio
async def test_consumer_client_messages_yields_tuples() -> None:
    """messages() yields (topic, key_str, payload_dict); key is None when msg.key() is None."""
    mock_msg_with_key = MagicMock()
    mock_msg_with_key.topic.return_value = "dev.indicators"
    mock_msg_with_key.key.return_value = b"ES:1m"
    mock_msg_with_key.value.return_value = orjson.dumps({"rsi_14": 58.3})
    mock_msg_with_key.error.return_value = None
    mock_msg_with_key.headers.return_value = None

    mock_msg_no_key = MagicMock()
    mock_msg_no_key.topic.return_value = "dev.llm.calls"
    mock_msg_no_key.key.return_value = None
    mock_msg_no_key.value.return_value = orjson.dumps({"model": "qwen"})
    mock_msg_no_key.error.return_value = None
    mock_msg_no_key.headers.return_value = None

    # _consume_loop_blocking batch-polls via consume(), not one message per poll().
    batches = [[mock_msg_with_key, mock_msg_no_key]]
    call_count = 0

    def _consume(num_messages, timeout):
        # After the one test batch, behave like a real idle consume() timeout
        # (returns []) so the background consume-loop thread just spins gently
        # until the test's aclosing() block sets stop_event.
        nonlocal call_count
        if call_count < len(batches):
            batch = batches[call_count]
            call_count += 1
            return batch
        return []

    mock_consumer = MagicMock()
    mock_consumer.consume.side_effect = _consume

    with patch("src.core.kafka_utils.Consumer", return_value=mock_consumer):
        client = KafkaConsumerClient(
            "dev.indicators",
            bootstrap_servers="localhost:19092",
            group_id="test_group",
        )
        await client.start()

        results = []
        # aclosing() guarantees messages()'s finally block (stop_event.set() +
        # awaiting the background consume task) runs deterministically on exit,
        # rather than relying on GC timing to finalize the async generator.
        async with contextlib.aclosing(client.messages()) as gen:
            async for item in gen:
                results.append(item)
                if len(results) == 2:
                    break

        assert len(results) == 2
        topic1, key1, payload1 = results[0]
        assert topic1 == "dev.indicators"
        assert key1 == "ES:1m"
        assert payload1 == {"rsi_14": 58.3}

        topic2, key2, payload2 = results[1]
        assert topic2 == "dev.llm.calls"
        assert key2 is None
        assert payload2 == {"model": "qwen"}


# ---------------------------------------------------------------------------
# _KafkaHeadersCarrier unit tests
# ---------------------------------------------------------------------------


def test_carrier_set_and_get() -> None:
    """set()/get() round-trip stores and retrieves a single header value."""
    carrier = _KafkaHeadersCarrier()
    carrier.set("traceparent", "00-abc-def-01")
    assert carrier.get("traceparent") == ["00-abc-def-01"]


def test_carrier_setitem_used_by_otel_default_setter() -> None:
    """__setitem__ must work — OTel default_setter calls carrier[key] = value."""
    carrier = _KafkaHeadersCarrier()
    carrier["traceparent"] = "00-abc-def-01"
    assert carrier.get("traceparent") == ["00-abc-def-01"]
    assert carrier.to_confluent_headers() == [("traceparent", b"00-abc-def-01")]


def test_carrier_get_missing_key() -> None:
    """get() returns None for a key that was never set."""
    carrier = _KafkaHeadersCarrier()
    assert carrier.get("nonexistent") is None


def test_carrier_keys() -> None:
    """keys() returns all set header names."""
    carrier = _KafkaHeadersCarrier()
    carrier.set("traceparent", "00-abc-def-01")
    carrier.set("tracestate", "rojo=00f067aa0ba902b7")
    keys = carrier.keys()
    assert "traceparent" in keys
    assert "tracestate" in keys
    assert len(keys) == 2


def test_carrier_to_confluent_headers() -> None:
    """to_confluent_headers() encodes str values as UTF-8 bytes."""
    carrier = _KafkaHeadersCarrier()
    carrier.set("traceparent", "00-abc-def-01")
    headers = carrier.to_confluent_headers()
    assert headers == [("traceparent", b"00-abc-def-01")]
