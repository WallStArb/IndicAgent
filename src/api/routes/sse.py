import asyncio
import json
from collections.abc import AsyncGenerator

import structlog
from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from ...config.settings import Settings
from ...core.stream_keys import indicators as sk_indicators
from ...core.stream_keys import intelligence as sk_intelligence
from ...core.stream_keys import live_tick as sk_live_tick
from ...core.stream_keys import market as sk_market
from ...core.stream_keys import narratives as sk_narratives
from ...core.stream_keys import signals_aggregated as sk_signals_aggregated
from .. import dependencies

logger = structlog.get_logger(__name__)

router = APIRouter()


def _resolve_contract(symbol: str) -> str:
    """Map base symbol (ES) to active contract code (ESH6).

    Accepts both base symbols and contract codes. If the symbol is already
    a contract code (contains a digit), return it as-is.
    """
    if any(ch.isdigit() for ch in symbol):
        return symbol  # Already a contract code
    settings = Settings()
    for c in settings.contracts:
        if c.base == symbol:
            return c.symbol
    return symbol  # Fallback: use as-is


def _build_stream_list(symbols: list[str], timeframe: str) -> list[str]:
    settings = Settings()
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
            streams.append(sk_signals_aggregated(env_prefix, contract, tf))
            streams.append(sk_narratives(env_prefix, contract, tf))
    return streams


def _event_name_for_stream(stream_name: str) -> str:
    # Remove optional env prefix when testing startswith
    parts = stream_name.split(":", 1)
    head = parts[0]
    rest = parts[1] if len(parts) > 1 else ""
    # If head is an env name (e.g., "dev"), re-evaluate from rest
    known_domains = {"ticks", "market", "indicators", "intelligence", "signals", "narratives"}
    candidate = rest if rest and head not in known_domains else stream_name
    if candidate.startswith("ticks:"):
        return "tick_data"
    if candidate.startswith("market:"):
        return "market_data"
    if candidate.startswith("indicators:"):
        return "indicator_data"
    if candidate.startswith("intelligence:"):
        # Intelligence stream payload: {"event": "<IntelligenceEvent JSON>"}
        # Parse the event field client-side: JSON.parse(payload.event)
        # See src/intelligence/schemas.py for IntelligenceEvent schema
        return "intelligence_data"
    if candidate.startswith("signals:"):
        return "signal_data"
    if candidate.startswith("narratives:"):
        return "narrative_data"
    return "message"


@router.get("/events")
async def sse_events(
    request: Request,
    symbols: str = Query(..., description="Comma-separated symbols, e.g., ESU5,NQU5,RTYU5"),
    timeframe: str = Query("1m", description="Timeframe, e.g., 1m/5m/15m/1h/4h/1d"),
    last_event_id: str = Query(None, alias="lastEventId"),
):
    """Server-Sent Events: bridge Redis Streams → browser.

    - Agents/services publish to Redis Streams.
    - This endpoint XREADs those streams and emits named SSE events.
    - View-only; HITL inputs should use normal HTTP endpoints.
    """

    if dependencies.redis_manager is None:
        # Lazy import fallback or raise
        logger.error("Redis manager not initialized")
        return StreamingResponse(
            iter([b'event:error\ndata:{"error":"redis not ready"}\n\n']),
            media_type="text/event-stream",
        )

    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    streams = _build_stream_list(symbol_list, timeframe)

    # Track last IDs per stream for XREAD
    last_ids: dict[str, str] = {s: last_event_id or "$" for s in streams}

    async def event_generator() -> AsyncGenerator[bytes]:
        redis = dependencies.redis_manager.redis_client  # type: ignore[attr-defined]

        # Initial hello
        yield b": keep-alive\n\n"

        try:
            # ── Snapshot: replay latest entries so dashboard has data on connect ──
            if not last_event_id:
                for stream_name in streams:
                    # indicators: grab last 30 (one per indicator type)
                    # others: grab last 1
                    count = 30 if "indicators:" in stream_name else 2
                    try:
                        entries = await redis.xrevrange(stream_name, count=count)
                    except Exception:
                        continue
                    if not entries:
                        continue
                    # xrevrange returns newest-first; reverse for chronological order
                    event_name = _event_name_for_stream(stream_name)
                    for msg_id, fields in reversed(entries):
                        last_ids[stream_name] = msg_id
                        try:
                            data_json = json.dumps(
                                {"stream": stream_name, "id": msg_id, "payload": fields}
                            )
                        except Exception:
                            data_json = json.dumps(
                                {"stream": stream_name, "id": msg_id, "payload": {}}
                            )
                        frame = f"event: {event_name}\nid: {msg_id}\ndata: {data_json}\n\n".encode()
                        yield frame

            # ── Live: XREAD for new messages ──
            while True:
                if await request.is_disconnected():
                    break

                try:
                    # XREAD across all streams; block for a short time
                    result = await redis.xread(
                        last_ids,
                        block=5000,  # 5s
                        count=200,
                    )
                except Exception as e:
                    logger.warning("xread failed", error=str(e))
                    await asyncio.sleep(0.5)
                    continue

                if not result:
                    # Heartbeat comment to keep connection alive
                    yield b": heartbeat\n\n"
                    continue

                # result: List[Tuple[stream_name, List[Tuple[id, fields]]]]
                for stream_name, messages in result:
                    # redis-py returns str (decode_responses=True)
                    event_name = _event_name_for_stream(stream_name)
                    for msg_id, fields in messages:
                        # Update last id for this stream
                        last_ids[stream_name] = msg_id

                        # Fields already dict of strings; provide raw payload
                        try:
                            data_json = json.dumps(
                                {
                                    "stream": stream_name,
                                    "id": msg_id,
                                    "payload": fields,
                                }
                            )
                        except Exception:
                            data_json = json.dumps(
                                {"stream": stream_name, "id": msg_id, "payload": {}}
                            )

                        # SSE frame
                        frame = f"event: {event_name}\nid: {msg_id}\ndata: {data_json}\n\n".encode()
                        yield frame

        except asyncio.CancelledError:
            logger.info("SSE client disconnected (cancelled)")
        except Exception as e:
            logger.error("SSE stream error", error=str(e))
            yield f'event: error\ndata: {{"error": "{str(e)}"}}\n\n'.encode()

    return StreamingResponse(event_generator(), media_type="text/event-stream")
