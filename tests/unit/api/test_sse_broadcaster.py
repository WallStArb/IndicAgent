"""Unit tests for KafkaSSEBroadcaster — topic-indexed fan-out, drop counter, snapshot bound."""

from unittest.mock import MagicMock

import pytest

from src.api.routes.sse import _MAX_LATEST_KEYS, KafkaSSEBroadcaster


class _MockConsumer:
    """Async generator consumer yielding a fixed sequence of (topic, key, payload) tuples."""

    def __init__(self, messages: list[tuple[str, str, dict]]) -> None:
        self._messages = messages

    async def messages(self):
        for msg in self._messages:
            yield msg


@pytest.mark.asyncio
async def test_subscriber_receives_matching_topic():
    broadcaster = KafkaSSEBroadcaster()
    _, sub = broadcaster.subscribe(frozenset(["market.bars"]))

    await broadcaster.run(
        _MockConsumer(
            [
                ("market.bars", "ES:1m", {"price": 5000}),
            ]
        )
    )

    assert sub.queue.qsize() == 1
    item = sub.queue.get_nowait()
    assert item["topic"] == "market.bars"
    assert item["payload"] == {"price": 5000}


@pytest.mark.asyncio
async def test_subscriber_does_not_receive_unsubscribed_topic():
    broadcaster = KafkaSSEBroadcaster()
    _, sub = broadcaster.subscribe(frozenset(["market.bars"]))

    await broadcaster.run(
        _MockConsumer(
            [
                ("intelligence", "ES:1m", {"signal": "buy"}),
            ]
        )
    )

    assert sub.queue.qsize() == 0


@pytest.mark.asyncio
async def test_two_subscribers_each_receive_own_topics():
    broadcaster = KafkaSSEBroadcaster()
    _, sub_a = broadcaster.subscribe(frozenset(["market.bars"]))
    _, sub_b = broadcaster.subscribe(frozenset(["intelligence"]))

    await broadcaster.run(
        _MockConsumer(
            [
                ("market.bars", "ES:1m", {"price": 5000}),
                ("intelligence", "ES:1m", {"signal": "buy"}),
            ]
        )
    )

    assert sub_a.queue.qsize() == 1
    assert sub_a.queue.get_nowait()["topic"] == "market.bars"

    assert sub_b.queue.qsize() == 1
    assert sub_b.queue.get_nowait()["topic"] == "intelligence"


@pytest.mark.asyncio
async def test_unsubscribe_stops_delivery():
    broadcaster = KafkaSSEBroadcaster()
    _, sub = broadcaster.subscribe(frozenset(["market.bars"]))
    broadcaster.unsubscribe(sub)

    await broadcaster.run(
        _MockConsumer(
            [
                ("market.bars", "ES:1m", {"price": 5000}),
            ]
        )
    )

    assert sub.queue.qsize() == 0


@pytest.mark.asyncio
async def test_queue_full_increments_drop_counter(monkeypatch):
    import src.api.routes.sse as sse_module

    mock_counter = MagicMock()
    monkeypatch.setattr(sse_module, "SSE_MESSAGES_DROPPED_TOTAL", mock_counter)

    broadcaster = KafkaSSEBroadcaster()
    _, sub = broadcaster.subscribe(frozenset(["market.bars"]))

    # Fill the queue to capacity
    for i in range(500):
        sub.queue.put_nowait({"topic": "market.bars", "key": f"SYM{i}:1m", "payload": {}})

    await broadcaster.run(
        _MockConsumer(
            [
                ("market.bars", "ES:1m", {"price": 9999}),
            ]
        )
    )

    mock_counter.add.assert_called_once_with(1, {"topic": "market.bars"})


@pytest.mark.asyncio
async def test_latest_snapshot_capped_at_max_keys():
    broadcaster = KafkaSSEBroadcaster()

    messages = [("market.bars", f"SYM{i}:1m", {"price": i}) for i in range(_MAX_LATEST_KEYS + 10)]
    await broadcaster.run(_MockConsumer(messages))

    assert len(broadcaster._latest["market.bars"]) == _MAX_LATEST_KEYS


@pytest.mark.asyncio
async def test_latest_snapshot_updates_existing_key_without_eviction():
    broadcaster = KafkaSSEBroadcaster()

    # Fill to exactly the cap
    messages = [("market.bars", f"SYM{i}:1m", {"v": i}) for i in range(_MAX_LATEST_KEYS)]
    await broadcaster.run(_MockConsumer(messages))

    # Update an existing key — should not grow beyond cap
    await broadcaster.run(_MockConsumer([("market.bars", "SYM0:1m", {"v": 999})]))

    assert len(broadcaster._latest["market.bars"]) == _MAX_LATEST_KEYS
    assert broadcaster._latest["market.bars"]["SYM0:1m"]["payload"] == {"v": 999}


@pytest.mark.asyncio
async def test_ibkr_seed_messages_are_skipped():
    broadcaster = KafkaSSEBroadcaster()
    _, sub = broadcaster.subscribe(frozenset(["market.bars"]))

    await broadcaster.run(
        _MockConsumer(
            [
                ("market.bars", "ES:1m", {"source": "ibkr_seed", "price": 5000}),
                ("market.bars", "ES:1m", {"source": "live", "price": 5001}),
            ]
        )
    )

    assert sub.queue.qsize() == 1
    assert sub.queue.get_nowait()["payload"]["source"] == "live"
