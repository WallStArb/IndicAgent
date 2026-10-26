import asyncio
import functools
import json
from collections import defaultdict
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from dataclasses import field as dc_field

import structlog
from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from src.observability.metrics import SSE_MESSAGES_DROPPED_TOTAL

from ...core.stream_keys import (
    topic_intelligence,
    topic_intelligence_journal,
    topic_market_bars,
    topic_market_bars_htf,
    topic_signals_aggregated,
)
from .. import dependencies
from ..utils import get_settings as _get_settings

logger = structlog.get_logger(__name__)

router = APIRouter()

_MAX_LATEST_KEYS = 200  # per-topic snapshot cap; prevents unbounded growth on contract rolls


@dataclass(eq=False)
class _Subscription:
    queue: asyncio.Queue = dc_field(repr=False)
    topics: frozenset


# ── KafkaSSEBroadcaster ──────────────────────────────────────────────────────


class KafkaSSEBroadcaster:
    """Fan-out broadcaster: single Kafka consumer → N connected SSE clients.

    Pattern:
      - KafkaConsumerClient.messages() loop → fan-out to all subscribed queues
      - Per-topic deque(maxlen=30) snapshot for new client connections
      - Per-client asyncio.Queue(maxsize=500) for live delivery
    """

    def __init__(self) -> None:
        self._by_topic: dict[str, set] = defaultdict(set)
        # Per-topic, per-message-key: latest message only.
        # Stores the most recent message for every (topic, key) pair so new clients
        # receive complete current state for all symbols/TFs on connect — no matter
        # how many seeded events were published before they connected.
        self._latest: dict[str, dict[str, dict]] = defaultdict(dict)

    @staticmethod
    def _extract_signal_scorecard_payload(payload: dict | str) -> dict | str:
        """Transform intelligence.record payload into signal_scorecard shape.

        intelligence.record is published via KafkaProducerClient which double-serializes
        the BarIntelligenceRecord JSON: json.dumps(record.model_dump_json()).encode().
        After json.loads() in the consumer, payload is a JSON string. Parse it and
        extract ranked_signals into the dashboard-expected shape.

        Falls back to returning the raw payload unchanged on any parse failure.
        """
        # Accept string (double-serialized) or dict (single-serialized or already parsed)
        if isinstance(payload, str):
            try:
                record_dict = json.loads(payload)
            except (ValueError, TypeError):
                return payload
        elif isinstance(payload, dict):
            record_dict = payload
        else:
            return payload

        try:
            ranked = record_dict.get("ranked_signals", [])
            intelligence = record_dict.get("intelligence", {})
            ts = intelligence.get("ts", "") if isinstance(intelligence, dict) else ""
            symbol = intelligence.get("symbol", "") if isinstance(intelligence, dict) else ""
            tf = intelligence.get("tf", "") if isinstance(intelligence, dict) else ""
            return {
                "ts": ts,
                "symbol": symbol,
                "tf": tf,
                "data": json.dumps(ranked),
            }
        except Exception:
            return payload if isinstance(payload, dict) else {}

    async def run(self, consumer: object) -> None:
        """Consume from KafkaConsumerClient and fan-out to all subscribed clients.

        Runs as a background task from lifespan. Stops when consumer stops.
        """
        settings = _get_settings()
        env_name = settings.env_name or ""
        _intelligence_record_topic = topic_intelligence_journal(env_name)

        async for topic, key, payload in consumer.messages():  # type: ignore[union-attr]
            # Skip backfill/seed bars — ibkr_seed source means historical gap-fill data,
            # not live market data. These must not reach dashboard clients.
            if isinstance(payload, dict) and payload.get("source") == "ibkr_seed":
                continue
            # Transform intelligence.record into signal_scorecard payload shape
            # so downstream SSE clients receive the same format as before.
            if topic == _intelligence_record_topic:
                payload = self._extract_signal_scorecard_payload(payload)
            item = {"topic": topic, "key": key, "payload": payload}
            slot = key if key is not None else "__keyless"

            # Size-bounded latest snapshot: evict oldest when topic is full
            topic_latest = self._latest[topic]
            if len(topic_latest) >= _MAX_LATEST_KEYS and slot not in topic_latest:
                oldest = next(iter(topic_latest))
                del topic_latest[oldest]
            topic_latest[slot] = item

            # Fan-out only to subscriptions that requested this topic — O(matching)
            for sub in list(self._by_topic.get(topic, ())):
                try:
                    sub.queue.put_nowait(item)
                except asyncio.QueueFull:
                    SSE_MESSAGES_DROPPED_TOTAL.add(1, {"topic": topic})

    def subscribe(self, topics: frozenset) -> tuple[dict, _Subscription]:
        """Register a new SSE client.

        Returns:
            (latest_dict, sub): latest dict (topic → {key → item}) for initial
            snapshot drain, and a _Subscription for subsequent messages.
        """
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        sub = _Subscription(queue=q, topics=topics)
        for topic in topics:
            self._by_topic[topic].add(sub)
        return self._latest, sub

    def unsubscribe(self, sub: _Subscription) -> None:
        """Deregister a client subscription on disconnect."""
        for topic in sub.topics:
            self._by_topic[topic].discard(sub)


# ── Topic list builder ───────────────────────────────────────────────────────


def sse_topics(env_name: str) -> list[str]:
    """The Kafka topics the broadcaster consumes and every SSE client subscribes to. Topics are
    flat (one per event type), so the list does not depend on the client's symbols."""
    return [
        topic_market_bars(env_name),
        topic_market_bars_htf(env_name),
        topic_intelligence(env_name),
        topic_intelligence_journal(env_name),
        topic_signals_aggregated(env_name),
    ]


# ── Topic → SSE event name mapping ──────────────────────────────────────────


def _serialize_sse_item(item: dict) -> str:
    """Serialize an SSE item (topic, key, payload) to JSON."""
    return json.dumps({"topic": item["topic"], "key": item["key"], "payload": item["payload"]})


# Longest prefix first: intelligence.journal before intelligence.
_EVENT_BY_PREFIX: tuple[tuple[str, str], ...] = (
    ("market.bars", "market_data"),
    # intelligence.journal: BarIntelligenceRecord transformed to scorecard shape by broadcaster
    ("intelligence.journal", "signal_scorecard"),
    ("intelligence", "intelligence_data"),
    ("signals.aggregated", "signal_data"),
)


@functools.lru_cache(maxsize=256)
def _event_name_for_topic(topic: str) -> str:
    """Map a Kafka topic name to an SSE event name, with or without an env prefix ('dev.'): the
    bare name is tried first, then the name after its first segment."""
    rest = topic.split(".", 1)[1] if "." in topic else ""
    for candidate in (topic, rest):
        for prefix, event in _EVENT_BY_PREFIX:
            if candidate.startswith(prefix):
                return event
    return "message"


# ── SSE endpoint ──────────────────────────────────────────────────────────────


@router.get("/events")
async def sse_events(
    request: Request,
    symbols: str = Query(..., description="Comma-separated symbols, e.g., ESU5,NQU5,RTYU5"),
    timeframe: str = Query("1m", description="Timeframe, e.g., 1m/5m/15m/1h/4h/1d"),
    last_event_id: str = Query(None, alias="lastEventId"),
):
    """Server-Sent Events: bridge Redpanda Kafka topics → browser.

    Uses KafkaSSEBroadcaster fan-out pattern:
    - Snapshot phase: drain per-topic deque(maxlen=30) for initial data on connect
    - Live phase: await asyncio.Queue items from broadcaster; yield heartbeat on timeout
    - On disconnect: unsubscribe queue from broadcaster
    """

    if dependencies.kafka_broadcaster is None:
        logger.error("Kafka broadcaster not initialized")
        return StreamingResponse(
            iter([b'event:error\ndata:{"error":"kafka broadcaster not ready"}\n\n']),
            media_type="text/event-stream",
        )

    broadcaster: KafkaSSEBroadcaster = dependencies.kafka_broadcaster
    topic_list = sse_topics(_get_settings().env_name or "")
    snapshot, sub = broadcaster.subscribe(frozenset(topic_list))

    async def event_generator() -> AsyncGenerator[bytes]:
        try:
            # Initial keep-alive
            yield b": keep-alive\n\n"

            # ── Snapshot phase: send latest-per-key state for each subscribed topic ──
            if not last_event_id:
                for topic in topic_list:
                    topic_latest = snapshot.get(topic, {})
                    if not topic_latest:
                        continue
                    event_name = _event_name_for_topic(topic)
                    for item in topic_latest.values():
                        try:
                            data_json = _serialize_sse_item(item)
                        except Exception:
                            continue
                        frame = f"event: {event_name}\ndata: {data_json}\n\n".encode()
                        yield frame

            # ── Live: await messages from broadcaster fan-out ──
            while True:
                if await request.is_disconnected():
                    logger.info(
                        "SSE client is_disconnected=True, breaking",
                        symbols=symbols,
                        timeframe=timeframe,
                    )
                    break

                try:
                    item = await asyncio.wait_for(sub.queue.get(), timeout=5.0)
                except TimeoutError:
                    yield b": heartbeat\n\n"
                    continue
                except asyncio.CancelledError:
                    break

                # No topic filter needed — broadcaster delivers only subscribed topics
                event_name = _event_name_for_topic(item["topic"])
                try:
                    data_json = _serialize_sse_item(item)
                except Exception:
                    continue

                frame = f"event: {event_name}\ndata: {data_json}\n\n".encode()
                yield frame

        except asyncio.CancelledError:
            logger.info("SSE client disconnected (cancelled)", symbols=symbols, timeframe=timeframe)
        except Exception as e:
            logger.error("SSE stream error", error=str(e), symbols=symbols, timeframe=timeframe)
            yield b'event: error\ndata: {"error": "stream error"}\n\n'
        finally:
            logger.info("SSE generator closing", symbols=symbols, timeframe=timeframe)
            broadcaster.unsubscribe(sub)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
