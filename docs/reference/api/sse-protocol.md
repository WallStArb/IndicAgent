<!-- generated-by: gsd-doc-writer -->
# Server-Sent Events Protocol

**Version:** 3.0
**Status:** current
**Last Updated:** 2026-09-04

Real-time streaming API served by the FastAPI backend on `:8000`. Single endpoint: `GET /api/sse/events`, implemented in `src/api/routes/sse.py`. Verified 2026-09-04 against that file and `src/core/stream_keys.py`.

---

## Connection

```
GET /api/sse/events?symbols=ESU5,NQU5,RTYU5&timeframe=1m
```

| Query param | Required | Notes |
|-------------|----------|-------|
| `symbols` | Yes | Comma-separated. Symbols are used only to open the connection — topic subscription itself is flat (one subscription per event type, not per symbol/TF); filtering by symbol happens client-side on the payload |
| `timeframe` | No, default `1m` | Accepted but likewise not used to filter topic subscription today — same flat-topic caveat as `symbols` |
| `lastEventId` | No | If set, the snapshot phase (below) is skipped |

Response: `text/event-stream`, headers `Cache-Control: no-cache`, `X-Accel-Buffering: no`.

## Architecture

`KafkaSSEBroadcaster` (in `sse.py`) is a single-consumer, N-client fan-out: one `KafkaConsumerClient` (consumer group `sse_broadcaster`, `auto_offset_reset="latest"`, seeks to end on startup — SSE never replays history) reads all subscribed Kafka topics and fans each message out to every connected client's own bounded `asyncio.Queue(maxsize=500)`. A message is dropped (and `SSE_MESSAGES_DROPPED_TOTAL` incremented, labeled by topic) if a client's queue is full, rather than blocking the broadcaster for a slow client.

Per (topic, message-key) pair, the broadcaster also keeps a size-bounded "latest" snapshot (`_MAX_LATEST_KEYS = 200` per topic, oldest evicted on overflow) so a newly-connecting client gets current state for every symbol/timeframe immediately, not just future events.

Bars with `source == "ibkr_seed"` (historical gap-fill data) are filtered out before fan-out — they must never reach dashboard clients as if live.

## Message lifecycle per connection

1. **Initial keep-alive**: `: keep-alive\n\n` comment frame sent immediately.
2. **Snapshot phase** (skipped if `lastEventId` was supplied): for each subscribed topic, drain the broadcaster's latest-per-key snapshot and emit one SSE frame per key.
3. **Live phase**: block on the client's queue with a 5s timeout; on timeout emit `: heartbeat\n\n`; on disconnect (`request.is_disconnected()`), break and unsubscribe.

## Subscribed topics

Every connection subscribes to the same fixed topic set regardless of query params (built by `_build_topic_list()` in `sse.py`, via `src/core/stream_keys.py`):

| `stream_keys.py` function | Topic (env-prefixed, dots) | SSE `event:` name |
|---|---|---|
| `topic_market_bars` | `{env}.market.bars` | `market_data` |
| `topic_market_bars_htf` | `{env}.market.bars.htf` | `market_data` |
| `topic_intelligence` | `{env}.intelligence` | `intelligence_data` |
| `topic_intelligence_journal` | `{env}.intelligence.journal` | `signal_scorecard` — payload transformed from the raw `BarIntelligenceRecord` into a `{ts, symbol, tf, data}` scorecard shape by `_extract_signal_scorecard_payload()` before fan-out |
| `topic_intelligence_i8` | `{env}.intelligence.i8` | `narrative_data` |
| `topic_signals_aggregated` | `{env}.signals.aggregated` | `signal_data` |
| `topic_narratives` | `{env}.narratives` | `narrative_data` |
| `topic_narratives_group` | `{env}.narratives.group` | `narrative_data` |

The event-name mapper (`_event_name_for_topic()`) also recognizes `market.ticks` → `tick_data` and `indicators` → `indicator_data`, but neither topic is in the subscribed set above — `IBKRProvider` publishes bars, not ticks, and `indicators` had only archived v2.x publishers. Any unmatched topic falls back to a generic `message` event name.

## Message format

Every SSE frame (snapshot or live) is:
```
event: <event_name>
data: {"topic": "<full topic string>", "key": <string|null>, "payload": <topic-specific JSON>}

```
`payload` shape depends on the source topic/schema — see [Stream Schemas](../schemas/stream-schemas.md) for the live v3.0 payload contracts (`FeatureVectorRecord`, `alpha_events`) and the archived v2.x `IntelligenceEvent`/`SignalEvent` contracts still flowing on `intelligence.journal`/`intelligence.i8` while those producers remain dormant.

## Failure mode

If the Kafka broadcaster failed to initialize at API startup, the endpoint still returns `200` with a `text/event-stream` body containing a single `event:error` frame (`{"error":"kafka broadcaster not ready"}`) rather than an HTTP error status — clients must handle an `error` event on the stream, not just a non-2xx response.

---

**Guide:** [Dashboard Development](../../guides/dashboard-development.md)
