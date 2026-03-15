import asyncio
import functools
import json
import time
from collections import defaultdict
from collections.abc import AsyncGenerator

import structlog
from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from ...core.stream_keys import indicators as sk_indicators
from ...core.stream_keys import intelligence as sk_intelligence
from ...core.stream_keys import intelligence_i7 as sk_intelligence_i7
from ...core.stream_keys import live_tick as sk_live_tick
from ...core.stream_keys import market as sk_market
from ...core.stream_keys import narratives as sk_narratives
from ...core.stream_keys import narratives_group as sk_narratives_group
from ...core.stream_keys import signals_aggregated as sk_signals_aggregated
from ...core.stream_keys import system_events as sk_system_events
from ...core.stream_keys import (
    topic_indicators,
    topic_intelligence,
    topic_intelligence_i7,
    topic_intelligence_i8,
    topic_market_bars,
    topic_market_ticks,
    topic_narratives,
    topic_narratives_group,
    topic_signals_aggregated,
)
from .. import dependencies
from ..utils import get_settings as _get_settings
from ..utils import resolve_contract as _resolve_contract

logger = structlog.get_logger(__name__)

router = APIRouter()

_NARRATIVE_GROUPS = ("equity", "energy", "metals", "rates", "fx_crypto", "ag")

_TF_MINUTES: dict[str, int] = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}


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

    async def run(self, consumer: object) -> None:
        """Consume from KafkaConsumerClient and fan-out to all subscribed clients.

        Runs as a background task from lifespan. Stops when consumer stops.
        """
        async for topic, key, payload in consumer.messages():  # type: ignore[union-attr]
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
    # Market ticks + bars + indicators + intelligence (all symbols/TFs share one topic each)
    topics.append(topic_market_ticks(env_name))
    topics.append(topic_market_bars(env_name))
    topics.append(topic_indicators(env_name))
    topics.append(topic_intelligence(env_name))
    topics.append(topic_intelligence_i7(env_name))
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
    if candidate == "intelligence.i7" or candidate.startswith("intelligence.i7"):
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


# ── Legacy Redis stream helpers (kept for backward compat — tests) ─────────────


@functools.lru_cache(maxsize=256)
def _signal_max_age_s(stream_name: str) -> float | None:
    """Return staleness threshold (seconds) for a signal stream, or None for non-signal streams."""
    if "signals:" not in stream_name:
        return None
    parts = stream_name.split(":")
    try:
        agg_idx = parts.index("aggregated")
        tf = parts[agg_idx - 1]
    except (ValueError, IndexError):
        return None
    tf_minutes = _TF_MINUTES.get(tf)
    return None if tf_minutes is None else 2 * tf_minutes * 60


def _signal_entry_stale(stream_name: str, entry_id: str | bytes) -> bool:
    """Return True if this signal stream entry is older than 2×TF."""
    max_age_s = _signal_max_age_s(stream_name)
    if max_age_s is None:
        return False
    try:
        id_str = entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)
        entry_unix_ms = int(id_str.split("-")[0])
    except (ValueError, IndexError):
        return False
    return (time.time() * 1000 - entry_unix_ms) / 1000 > max_age_s


def _build_stream_list(symbols: list[str], timeframe: str) -> list[str]:
    """Legacy Redis stream list builder — kept for backward compatibility with tests.

    Returns Redis-style stream names. Use _build_topic_list() for Kafka-based SSE.
    """
    settings = _get_settings()
    env_prefix = f"{settings.env_name}:" if settings.env_name else ""
    # Accept comma-separated timeframes (e.g. "1m,5m,15m,1h,4h,1d")
    timeframes = [tf.strip() for tf in timeframe.split(",") if tf.strip()]
    streams: list[str] = []
    for sym in symbols:
        contract = _resolve_contract(sym)
        # ticks (no timeframe)
        streams.append(sk_live_tick(env_prefix, contract))
        # market bars and indicators per timeframe
        for tf in timeframes:
            streams.append(sk_market(env_prefix, contract, tf))
            streams.append(sk_indicators(env_prefix, contract, tf))
            streams.append(sk_intelligence(env_prefix, contract, tf))
            streams.append(sk_intelligence_i7(env_prefix, contract, tf))
            streams.append(sk_signals_aggregated(env_prefix, contract, tf))
            streams.append(sk_narratives(env_prefix, contract, tf))
    # Group narrative streams — global, not per-symbol
    for group in _NARRATIVE_GROUPS:
        streams.append(sk_narratives_group(env_prefix, group))
    # System events stream — global, not per-symbol
    streams.append(sk_system_events(env_prefix))
    return streams


@functools.lru_cache(maxsize=512)
def _event_name_for_stream(stream_name: str) -> str:
    """Legacy Redis stream → SSE event name mapping (kept for backward compat with tests)."""
    # Remove optional env prefix when testing startswith
    parts = stream_name.split(":", 1)
    head = parts[0]
    rest = parts[1] if len(parts) > 1 else ""
    # If head is an env name (e.g., "dev"), re-evaluate from rest
    known_domains = {
        "ticks",
        "market",
        "indicators",
        "intelligence",
        "intelligence_i7",
        "signals",
        "narratives",
        "system",
    }
    candidate = rest if rest and head not in known_domains else stream_name
    if candidate.startswith("ticks:"):
        return "tick_data"
    if candidate.startswith("market:"):
        return "market_data"
    if candidate.startswith("indicators:"):
        return "indicator_data"
    if candidate.startswith("intelligence_i7:"):
        return "signal_scorecard"
    if candidate.startswith("intelligence:"):
        return "intelligence_data"
    if candidate.startswith("signals:"):
        return "signal_data"
    if candidate.startswith("narratives:"):
        return "narrative_data"
    if candidate.startswith("system:"):
        return "system_event"
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
                    break

                try:
                    item = await asyncio.wait_for(live_q.get(), timeout=5.0)
                except TimeoutError:
                    yield b": heartbeat\n\n"
                    continue
                except asyncio.CancelledError:
                    break

                # Filter to only topics this client subscribed to
                if item["topic"] not in topic_list:
                    continue

                event_name = _event_name_for_topic(item["topic"])
                try:
                    data_json = _serialize_sse_item(item)
                except Exception:
                    continue

                frame = f"event: {event_name}\ndata: {data_json}\n\n".encode()
                yield frame

        except asyncio.CancelledError:
            logger.info("SSE client disconnected (cancelled)")
        except Exception as e:
            logger.error("SSE stream error", error=str(e))
            yield b'event: error\ndata: {"error": "stream error"}\n\n'
        finally:
            broadcaster.unsubscribe(live_q)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
