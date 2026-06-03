import asyncio
import functools
import json
from collections import defaultdict
from collections.abc import AsyncGenerator

import structlog
from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from ...core.stream_keys import (
    topic_intelligence,
    topic_intelligence_i8,
    topic_intelligence_journal,
    topic_market_bars,
    topic_market_bars_htf,
    topic_narratives,
    topic_narratives_group,
    topic_signals_aggregated,
)
from .. import dependencies
from ..utils import get_settings as _get_settings

logger = structlog.get_logger(__name__)

router = APIRouter()


# ── KafkaSSEBroadcaster ──────────────────────────────────────────────────────


class KafkaSSEBroadcaster:
    """Fan-out broadcaster: single Kafka consumer → N connected SSE clients.

    Pattern:
      - KafkaConsumerClient.messages() loop → fan-out to all subscribed queues
      - Per-topic deque(maxlen=30) snapshot for new client connections
      - Per-client asyncio.Queue(maxsize=500) for live delivery
    """

    def __init__(self) -> None:
        self._queues: list[asyncio.Queue] = []
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
            # Latest-per-key: always keep the most recent message for each key.
            # Uses key or falls back to a monotonic counter for keyless messages.
            slot = key if key is not None else "__keyless"
            self._latest[topic][slot] = item
            # Fan-out: deliver to all connected clients; skip full queues (slow client)
            for q in list(self._queues):
                try:
                    q.put_nowait(item)
                except asyncio.QueueFull:
                    pass  # slow client — drop message, continue

    def subscribe(self) -> tuple[dict, asyncio.Queue]:
        """Register a new SSE client.

        Returns:
            (latest_dict, live_queue): latest dict (topic → {key → item}) for initial
            snapshot drain, and a live asyncio.Queue for subsequent messages.
        """
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._queues.append(q)
        return self._latest, q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        """Deregister a client queue on disconnect."""
        try:
            self._queues.remove(q)
        except ValueError:
            pass  # already removed or never subscribed


# ── Topic list builder ───────────────────────────────────────────────────────


def _build_topic_list(symbols: list[str], timeframe: str) -> list[str]:
    """Return Kafka topics to subscribe for the given symbols and timeframe.

    Topics are flat (one per event type, not per symbol/TF). Deduplication
    handled by returning unique topic names only.
    """
    settings = _get_settings()
    env_name = settings.env_name or ""
    topics: list[str] = []
    # market.ticks removed — IBKRProvider publishes bars not ticks; intelligence_pipeline subscribes internally
    # indicators removed — only archived services published to this topic
    topics.append(topic_market_bars(env_name))
    topics.append(topic_market_bars_htf(env_name))
    topics.append(topic_intelligence(env_name))
    topics.append(topic_intelligence_journal(env_name))
    topics.append(topic_intelligence_i8(env_name))
    topics.append(topic_signals_aggregated(env_name))
    topics.append(topic_narratives(env_name))
    topics.append(topic_narratives_group(env_name))
    # Deduplicate while preserving order
    seen: set[str] = set()
    result: list[str] = []
    for t in topics:
        if t not in seen:
            seen.add(t)
            result.append(t)
    return result


# ── Topic → SSE event name mapping ──────────────────────────────────────────


def _serialize_sse_item(item: dict) -> str:
    """Serialize an SSE item (topic, key, payload) to JSON."""
    return json.dumps({"topic": item["topic"], "key": item["key"], "payload": item["payload"]})


@functools.lru_cache(maxsize=256)
def _event_name_for_topic(topic: str) -> str:
    """Map a Kafka topic name (period-separated) to an SSE event name.

    Strips optional env prefix (e.g. 'dev.') before matching.
    """
    # Strip env prefix: everything before the first period that isn't a known domain segment
    known_prefixes = {
        "market.ticks",
        "market.bars",
        "indicators",
        "intelligence.journal",
        "intelligence.i7",
        "intelligence.i8",
        "intelligence",
        "signals.aggregated",
        "signals",
        "narratives.group",
        "narratives",
        "llm.calls",
        "llm.outcomes",
        "system.events",
    }
    # Find rest after first dot if the first segment looks like an env name
    dot_idx = topic.find(".")
    if dot_idx > 0:
        rest = topic[dot_idx + 1 :]
        # Check if rest matches a known prefix → the first part is env prefix
        matches = any(
            rest == p or rest.startswith(p + ".") or rest.startswith(p) for p in known_prefixes
        )
        if matches:
            candidate = rest
        else:
            candidate = topic
    else:
        candidate = topic

    if candidate == "market.ticks" or candidate.startswith("market.ticks"):
        return "tick_data"
    if candidate == "market.bars" or candidate.startswith("market.bars"):
        return "market_data"
    if candidate == "indicators" or candidate.startswith("indicators"):
        return "indicator_data"
    # intelligence.journal — BarIntelligenceRecord transformed to scorecard shape by broadcaster
    if candidate == "intelligence.journal" or candidate.startswith("intelligence.journal."):
        return "signal_scorecard"
    if candidate == "intelligence.i8" or candidate.startswith("intelligence.i8"):
        return "narrative_data"
    if candidate == "intelligence" or candidate.startswith("intelligence"):
        return "intelligence_data"
    if candidate == "signals.aggregated" or candidate.startswith("signals.aggregated"):
        return "signal_data"
    if candidate == "signals" or candidate.startswith("signals"):
        return "signal_data"
    if candidate == "narratives.group" or candidate.startswith("narratives.group"):
        return "narrative_data"
    if candidate == "narratives" or candidate.startswith("narratives"):
        return "narrative_data"
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
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    topic_list = _build_topic_list(symbol_list, timeframe)
    topic_set = set(topic_list)

    snapshot, live_q = broadcaster.subscribe()

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
                    item = await asyncio.wait_for(live_q.get(), timeout=5.0)
                except TimeoutError:
                    yield b": heartbeat\n\n"
                    continue
                except asyncio.CancelledError:
                    break

                # Filter to only topics this client subscribed to
                if item["topic"] not in topic_set:
                    continue

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
            broadcaster.unsubscribe(live_q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
