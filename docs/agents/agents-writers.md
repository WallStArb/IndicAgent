# Agents Writers — BaseWriter & the Persistence Pattern

**Version:** 2.8.0 | **Status:** current | **Last Updated:** 2026-05-29

---

## Purpose

`BaseWriter` is the second layer of the agent hierarchy, sitting above `BaseAgent`. It adds everything needed to move data from Kafka into TimescaleDB safely: bounded buffering, size-and-time flush triggers, offset commit gating, overflow protection, and DLQ routing.

**Audience:** Engineers adding a new persistence service, debugging a stalled writer, or investigating DLQ events.

The separation between `BaseAgent` and `BaseWriter` exists because compute agents and writer agents have opposite failure modes. A compute agent that crashes loses nothing — messages stay in Kafka. A writer agent that crashes mid-batch risks writing partial rows. `BaseWriter` makes the atomic batch guarantee concrete: flush succeeds and offset commits, or flush fails and the batch stays buffered for retry.

Writers are the **only agents with DB write access**. They must never appear on the compute hot path.

---

## Design Principles

### Why Batch Flushing, Not Per-Message Writes

Per-message DB writes serialize the pipeline to the DB's per-insert latency (~1-5ms). At 10 bars/second across 4 symbols and 6 timeframes, that is 240 inserts/second minimum — the pool exhausts under normal load. Batch flushing amortizes the TCP round-trip, uses `executemany`, and achieves 50-100x throughput on bulk inserts.

Defaults: `BATCH_SIZE = 100` (flush on count) and `FLUSH_INTERVAL_SECS = 5.0` (flush on time). Both thresholds are class attributes — subclasses override them without subclassing `_do_flush()`.

### Why DLQ Quarantine-Then-Drain, Not Retry-In-Place

Retry-in-place blocks the consumer: the same bad message re-processes on every restart until an operator intervenes. DLQ quarantine lets the pipeline keep moving — the bad payload goes to a dead-letter topic where it can be inspected and replayed after the root cause is fixed.

### The Atomic Batch Contract

`_do_flush()` guarantees:

1. `_flush_batch(batch)` is called with a snapshot copy of the buffer.
2. On success: buffer is cleared, Kafka offset is committed.
3. On failure: buffer is **not** cleared, offset is **not** committed. The next flush retries the same batch.

The pipeline never commits an offset ahead of a successful DB write. Losing the process between `_flush_batch` succeeding and `consumer.commit()` completing is safe — the batch will be re-processed on restart, and `_flush_batch` must be idempotent (upsert, not insert).

### Why Idempotency Is Required

Replay is always possible. On restart, the consumer replays from the last committed offset. Any record already in the DB will be re-processed by `_flush_batch`. Writers must use `INSERT ... ON CONFLICT DO UPDATE` (upsert) or an equivalent idempotent path — a bare `INSERT` will raise on replay.

---

## Architecture

### Buffer Accumulation Loop

```
_setup()
  └─→ _create_consumer()          wire KafkaConsumerClient to self._consumer
  └─→ DB pool init                 asyncpg.create_pool(...)

_run() [default implementation]
  └─→ async for message in self._consumer.messages():
        _record_message_consumed()            liveness tick
        parsed = _parse_payload(payload)
        if parsed is None:
          _maybe_route_to_dlq(payload, exc)  DLQ + counter
          continue
        if parsed == []:
          continue                            skip silently — no DLQ, no buffer entry
        _buffer_rows(parsed)                  appends to self._buffer
        if buffer > alert threshold:
          sleep(0.5)                          backpressure
        await maybe_flush()                   flush if size or time threshold met

_teardown()
  └─→ _do_flush()                  final flush of remaining buffer
  └─→ consumer.stop()              close Kafka consumer
  └─→ pool.close() / db.close()   close DB connections
```

### `_create_consumer()` Helper

Call this in `_setup()` instead of wiring `KafkaConsumerClient` manually:

```python
async def _setup(self) -> None:
    self._create_consumer()   # assigns self._consumer
    self._pool = await asyncpg.create_pool(dsn=...)
```

It reads `bootstrap_servers` from `self.settings`, sets `enable_auto_commit=False`, and assigns the result to `self._consumer`. Manual offset commit is mandatory — `BaseWriter._do_flush()` calls `self._consumer.commit()` only after `_flush_batch` succeeds.

### Overflow Protection

`MAX_BUFFER_SIZE = 10_000` (default). When the buffer exceeds this size, the oldest entries are dropped and `buffer_overflow_total` increments. A `buffer_high_watermark` warning fires at 80% capacity (one-shot — not repeated on every message). If you see overflow in production, the flush is too slow relative to the ingestion rate — tune `BATCH_SIZE` or `FLUSH_INTERVAL_SECS`, or investigate DB write latency.

---

## Data Contracts

### `_parse_payload` Return Contract

This is the most important contract in `BaseWriter`. The return value controls the fate of the message:

| Return value | Meaning | What happens |
|-------------|---------|--------------|
| `list` (non-empty) | Valid rows to persist | Rows are buffered, flushed to DB on next flush cycle |
| `[]` (empty list) | All rows invalid, skip silently | No DLQ, no buffer entry — message acknowledged |
| `None` | Payload is unparseable | `_maybe_route_to_dlq()` fires, `parse_failures_total` increments |

**Critical distinction:** Return `[]` (empty list) when individual rows fail validation but the payload envelope is understood. Return `None` only when the payload itself is malformed and cannot be interpreted at all. Returning `None` on a per-row validation failure causes the base writer to DLQ the entire payload — double-penalizing a partially-valid batch.

### `PERSISTENCE_BATCH_LATENCY`

The label key is `agent_id`, not `agent`. This is enforced by the canonical metric in `src/observability/metrics.py`. Using the wrong label key causes Grafana panels to show no data.

```python
from src.observability.metrics import PERSISTENCE_BATCH_LATENCY
PERSISTENCE_BATCH_LATENCY.record((time.monotonic() - t0) * 1000, {"agent_id": self.name})
```

### `PERSISTENCE_CONSUMER_LAG`

`BaseWriter` overrides `_report_consumer_lag()` to report `len(self._buffer)` as the lag gauge. This runs every 15 seconds as a background task. The service auditor reads this metric (via `_AGENT_ID_TO_UNIT` in `service_auditor.py`) to detect stalled writers and trigger restarts.

### Per-Writer Metrics (automatic)

`BaseWriter` creates these per-agent metrics in `__init__` (no subclass code needed):

| Metric | Type | Purpose |
|--------|------|---------|
| `{agent}_buffer_depth` | UpDownCounter | Current buffer depth |
| `{agent}_buffer_overflow_total` | Counter | Rows dropped on overflow |
| `{agent}_flush_latency_seconds` | Histogram | DB batch write latency |
| `{agent}_commit_latency_seconds` | Histogram | Kafka offset commit latency |
| `{agent}_parse_failures_total` | Counter | Payloads routed to DLQ |
| `{agent}_flush_errors_total` | Counter | Batch flush failures |

---

## How To Extend

### New Writer Agent Recipe

```python
from src.core.agent.base_writer import BaseWriter
import asyncpg

class MyWriter(BaseWriter):

    # Tune flush behavior
    BATCH_SIZE = 200
    FLUSH_INTERVAL_SECS = 3.0

    def _topic_name(self) -> str:
        from src.core.stream_keys import topic_my_events
        return topic_my_events(self.env_name)

    @property
    def _consumer_group(self) -> str:
        return f"{self.env_name}.my_writer_group"

    async def _setup(self) -> None:
        self._create_consumer()   # wires self._consumer
        self._pool = await asyncpg.create_pool(
            dsn=self.settings.timescaledb_dsn,
            min_size=2,
            max_size=10,
        )

    def _parse_payload(self, payload: dict) -> list | None:
        """Return list of row dicts, [] for all-invalid, None for unparseable."""
        if "symbol" not in payload or "ts" not in payload:
            return None   # payload envelope is malformed
        rows = []
        for item in payload.get("items", []):
            if not isinstance(item.get("value"), (int, float)):
                continue   # skip invalid rows — don't DLQ the whole batch
            rows.append({"symbol": payload["symbol"], "ts": payload["ts"], "value": item["value"]})
        return rows  # [] is fine here — empty batch is silently skipped

    async def _flush_batch(self, batch: list) -> None:
        """Write batch to DB. Must be idempotent (upsert, not insert)."""
        async with self._pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO my_table (symbol, ts, value)
                VALUES ($1, $2, $3)
                ON CONFLICT (symbol, ts) DO UPDATE SET value = EXCLUDED.value
                """,
                [(r["symbol"], r["ts"], r["value"]) for r in batch],
            )
```

### What `_flush_batch` Must NOT Do

- Clear `self._buffer` — `_do_flush()` does that after `_flush_batch` returns.
- Raise on partial failure without rolling back — either all rows succeed or raise and retry.
- Call `self._consumer.commit()` — `_do_flush()` handles offset commits.

---

## Failure Modes & Operations

### DLQ Drain Procedure

When `agent_dlq_total` increments, payloads are being routed to the DLQ topic (if configured) or logged and discarded. To investigate:

1. Check `logs/<agent_name>_agent.log` for `agent.dlq_discard` events.
2. If a DLQ topic is configured, inspect it: `docker exec redpanda rpk topic consume <dlq_topic> --num 5`.
3. Identify the pattern (schema mismatch, missing fields, upstream producer change).
4. Fix the upstream producer or update `_parse_payload` to handle the new schema.
5. Replay the DLQ topic once the fix is deployed (consumer group reset to beginning of DLQ topic).

### `parse_failures_total` Incrementing

This counter increments when `_parse_payload` returns `None`. Common causes:

- Upstream producer changed the payload schema without updating the writer.
- A new field is required by `_parse_payload` but missing from older messages being replayed.
- A Pydantic validation error when `payload_model` is set on the class.

### Checking Batch Latency

```bash
# Query Prometheus directly
curl -s 'http://localhost:9090/api/v1/query?query=histogram_quantile(0.99,rate(feature_writer_agent_flush_latency_seconds_bucket[5m]))' | jq .
```

P99 flush latency above 500ms usually indicates DB connection pool exhaustion or a slow index rebuild.

### `_consumer` Must Be Assigned in `_setup()`

`BaseWriter._do_flush()` calls `self._consumer.commit()`. If `self._consumer` is `None` (because `_setup()` was not called or `_create_consumer()` was not called), offset commits silently skip. Consumer lag will never decrease on restart. Always verify that `_setup()` assigns `self._consumer` before `_run()` starts.

---

## See Also

- `docs/agents/agents-foundation.md` — BaseAgent contract and liveness signals
- `docs/agents/agents-operations.md` — service mesh, DAG topology, how writers fit in the restart order
- `src/core/agent/base_writer.py` — source of truth
- `src/observability/metrics.py` — canonical metric definitions
