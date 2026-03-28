"""Tests for Kafka trace context propagation in kafka_utils.py."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient, _KafkaHeadersCarrier

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _MockMessage:
    def __init__(self, topic, key, value, headers=None):
        self.topic = topic
        self.key = key
        self.value = value
        self.headers = headers


class _MockConsumer:
    """Async iterable mock for AIOKafkaConsumer.

    Defines __aiter__ at class level so dunder lookup works correctly.
    AsyncMock with instance-level __aiter__ silently yields 0 iterations.
    """

    def __init__(self, *messages):
        self._messages = messages
        self._started = False
        self._stopped = False

    async def start(self) -> None:
        self._started = True

    async def stop(self) -> None:
        self._stopped = True

    async def commit(self) -> None:
        pass

    async def seek_to_beginning(self) -> None:
        pass

    def __aiter__(self):
        return self._aiter()

    async def _aiter(self):
        for msg in self._messages:
            yield msg


# ---------------------------------------------------------------------------
# _KafkaHeadersCarrier unit tests
# ---------------------------------------------------------------------------


def test_carrier_set_and_get() -> None:
    """set()/get() round-trip stores and retrieves a single header value."""
    carrier = _KafkaHeadersCarrier()
    carrier.set("traceparent", "00-abc-def-01")
    assert carrier.get("traceparent") == ["00-abc-def-01"]


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


def test_carrier_to_aiokafka_headers() -> None:
    """to_aiokafka_headers() encodes str values as UTF-8 bytes."""
    carrier = _KafkaHeadersCarrier()
    carrier.set("traceparent", "00-abc-def-01")
    headers = carrier.to_aiokafka_headers()
    assert headers == [("traceparent", b"00-abc-def-01")]


# ---------------------------------------------------------------------------
# KafkaProducerClient.publish() tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_sends_headers() -> None:
    """publish() passes headers kwarg to send_and_wait containing injected traceparent."""
    client = KafkaProducerClient.__new__(KafkaProducerClient)
    client._bootstrap = "localhost:9092"
    client._producer = AsyncMock()
    client._producer.send_and_wait = AsyncMock()

    def mock_inject(carrier, context=None):
        carrier.set("traceparent", "00-tid-sid-01")

    with patch("src.core.kafka_utils.inject", side_effect=mock_inject):
        await client.publish("test.topic", {"key": "val"}, key="k")

    client._producer.send_and_wait.assert_called_once()
    call_kwargs = client._producer.send_and_wait.call_args[1]
    assert "headers" in call_kwargs
    headers_dict = dict(call_kwargs["headers"])
    assert "traceparent" in headers_dict
    assert headers_dict["traceparent"] == b"00-tid-sid-01"


@pytest.mark.asyncio
async def test_publish_no_active_span_sends_empty_headers() -> None:
    """publish() without active span sends empty headers list (no crash, real no-op SDK)."""
    client = KafkaProducerClient.__new__(KafkaProducerClient)
    client._bootstrap = "localhost:9092"
    client._producer = AsyncMock()
    client._producer.send_and_wait = AsyncMock()

    # Real inject call with no active span — injects nothing into carrier
    await client.publish("test.topic", {"key": "val"})

    client._producer.send_and_wait.assert_called_once()
    call_kwargs = client._producer.send_and_wait.call_args[1]
    assert "headers" in call_kwargs
    # Empty list when no traceparent to inject
    assert isinstance(call_kwargs["headers"], list)


@pytest.mark.asyncio
async def test_publish_signature_unchanged_with_key() -> None:
    """publish() still accepts (topic, msg, key) positional args."""
    client = KafkaProducerClient.__new__(KafkaProducerClient)
    client._bootstrap = "localhost:9092"
    client._producer = AsyncMock()
    client._producer.send_and_wait = AsyncMock()

    await client.publish("my.topic", {"data": 1}, key="ES:1m")

    call_args = client._producer.send_and_wait.call_args
    assert call_args[0][0] == "my.topic"
    assert call_args[1]["key"] == b"ES:1m"


@pytest.mark.asyncio
async def test_publish_signature_unchanged_without_key() -> None:
    """publish() works with key=None (no key routing)."""
    client = KafkaProducerClient.__new__(KafkaProducerClient)
    client._bootstrap = "localhost:9092"
    client._producer = AsyncMock()
    client._producer.send_and_wait = AsyncMock()

    await client.publish("my.topic", {"data": 1})

    call_args = client._producer.send_and_wait.call_args
    assert call_args[1]["key"] is None


# ---------------------------------------------------------------------------
# KafkaConsumerClient.messages() tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_messages_extracts_traceparent() -> None:
    """messages() calls extract with the carrier built from msg.headers."""
    client = KafkaConsumerClient.__new__(KafkaConsumerClient)
    msg = _MockMessage(
        topic="test.topic",
        key=b"ES:1m",
        value=json.dumps({"bar": 1}).encode(),
        headers=[("traceparent", b"00-tid-sid-01")],
    )
    client._consumer = _MockConsumer(msg)

    mock_ctx = MagicMock()
    mock_token = MagicMock()

    with (
        patch("src.core.kafka_utils.extract", return_value=mock_ctx) as mock_extract,
        patch("src.core.kafka_utils.otel_context.attach", return_value=mock_token) as mock_attach,
        patch("src.core.kafka_utils.otel_context.detach") as mock_detach,
    ):
        results = []
        async for topic, key, payload in client.messages():
            results.append((topic, key, payload))

    assert len(results) == 1
    # extract was called with a carrier that contains traceparent
    mock_extract.assert_called_once()
    carrier_arg = mock_extract.call_args[0][0]
    assert carrier_arg.get("traceparent") == ["00-tid-sid-01"]
    # attach was called with the extracted context
    mock_attach.assert_called_once_with(mock_ctx)
    # detach was called with the token returned by attach
    mock_detach.assert_called_once_with(mock_token)


@pytest.mark.asyncio
async def test_messages_no_headers_no_crash() -> None:
    """messages() with headers=None yields normally without error."""
    client = KafkaConsumerClient.__new__(KafkaConsumerClient)
    msg = _MockMessage(
        topic="test.topic",
        key=b"ES:1m",
        value=json.dumps({"bar": 1}).encode(),
        headers=None,
    )
    client._consumer = _MockConsumer(msg)

    results = []
    async for topic, key, payload in client.messages():
        results.append((topic, key, payload))

    assert len(results) == 1
    assert results[0] == ("test.topic", "ES:1m", {"bar": 1})


@pytest.mark.asyncio
async def test_messages_empty_headers_no_crash() -> None:
    """messages() with headers=[] yields normally without error."""
    client = KafkaConsumerClient.__new__(KafkaConsumerClient)
    msg = _MockMessage(
        topic="test.topic",
        key=b"ES:1m",
        value=json.dumps({"bar": 1}).encode(),
        headers=[],
    )
    client._consumer = _MockConsumer(msg)

    results = []
    async for topic, key, payload in client.messages():
        results.append((topic, key, payload))

    assert len(results) == 1


@pytest.mark.asyncio
async def test_messages_yield_tuple_unchanged() -> None:
    """messages() yields (str, str | None, dict) — no signature change."""
    client = KafkaConsumerClient.__new__(KafkaConsumerClient)
    msg = _MockMessage(
        topic="my.topic",
        key=b"ES:1m",
        value=json.dumps({"price": 5250.0}).encode(),
        headers=[],
    )
    client._consumer = _MockConsumer(msg)

    results = []
    async for topic, key, payload in client.messages():
        results.append((topic, key, payload))

    assert len(results) == 1
    topic, key, payload = results[0]
    assert isinstance(topic, str)
    assert isinstance(key, str)  # decoded from bytes
    assert isinstance(payload, dict)
    assert payload["price"] == 5250.0


@pytest.mark.asyncio
async def test_messages_yield_tuple_no_key() -> None:
    """messages() yields key=None when message has no key."""
    client = KafkaConsumerClient.__new__(KafkaConsumerClient)
    msg = _MockMessage(
        topic="my.topic",
        key=None,
        value=json.dumps({"price": 5250.0}).encode(),
        headers=[],
    )
    client._consumer = _MockConsumer(msg)

    results = []
    async for topic, key, payload in client.messages():
        results.append((topic, key, payload))

    assert len(results) == 1
    _, key, _ = results[0]
    assert key is None


@pytest.mark.asyncio
async def test_messages_context_detached_after_processing() -> None:
    """otel_context.detach called exactly once per message after yield resumes."""
    client = KafkaConsumerClient.__new__(KafkaConsumerClient)
    msg1 = _MockMessage(
        topic="t",
        key=None,
        value=json.dumps({}).encode(),
        headers=[("traceparent", b"00-aaa-bbb-01")],
    )
    msg2 = _MockMessage(
        topic="t",
        key=None,
        value=json.dumps({}).encode(),
        headers=[("traceparent", b"00-ccc-ddd-01")],
    )
    client._consumer = _MockConsumer(msg1, msg2)

    mock_token = MagicMock()
    with (
        patch("src.core.kafka_utils.extract", return_value=MagicMock()),
        patch("src.core.kafka_utils.otel_context.attach", return_value=mock_token),
        patch("src.core.kafka_utils.otel_context.detach") as mock_detach,
    ):
        count = 0
        async for _topic, _key, _payload in client.messages():
            count += 1

    assert count == 2
    # detach called once per message
    assert mock_detach.call_count == 2
