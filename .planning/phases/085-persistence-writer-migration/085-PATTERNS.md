# Phase 085: Persistence Writer Migration - Pattern Map

**Mapped:** 2026-05-17
**Files analyzed:** 11 (8 writer services + 2 schema files + 1 base contract)
**Analogs found:** 11 / 11

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `services/lineage_writer_agent.py` | writer | Kafka-to-DB, CRUD | `services/lifecycle_writer_agent.py` | exact |
| `services/feature_snapshot_writer_agent.py` | writer | Kafka-to-DB, CRUD | `services/lineage_writer_agent.py` | exact |
| `services/llm_writer_service.py` | writer | Kafka-to-DB, multi-topic | `services/bar_writer_agent.py` | role-match |
| `services/signal_metrics_writer_agent.py` | writer | Kafka-to-DB, CRUD | `services/lifecycle_writer_agent.py` | exact |
| `services/lifecycle_writer_agent.py` | writer | Kafka-to-DB, batch | self (audit target only) | exact |
| `services/ctx_writer_agent.py` | writer | Kafka-to-DB, batch | self (audit target only) | exact |
| `services/bar_writer_agent.py` | writer | Kafka-to-DB, CRUD | self (audit target only) | exact |
| `services/swarm_ledger_writer_agent.py` | writer | Kafka-to-DB, upsert | self (audit target only) | exact |
| `src/core/ai/lineage.py` | schema/model | event producer | `src/intelligence/schemas.py` | role-match |
| `src/intelligence/schemas.py` | schema/model | discriminated union | self | exact |
| `services/contract_metadata_writer_agent.py` | writer (reference) | request-response | — | reference template |

---

## Pattern Assignments

### `services/lineage_writer_agent.py` (PERSIST-01)

**Analog:** `services/lifecycle_writer_agent.py`

**Current state:** Already a `BaseWriterAgent` subclass. Has `_dlq_topic()`. Missing `payload_model` ClassVar. Manual `signal_id`/`event_type` check in `_parse_payload()` is dead code once `payload_model` is wired.

**Pattern to add — `payload_model` ClassVar** (copy from `lifecycle_writer_agent.py` pattern, applied to lineage):

```python
from src.core.ai.lineage import LineageEvent  # defined in PERSIST-01 companion task

class LineageWriterAgent(BaseWriterAgent):
    payload_model = LineageEvent  # base validates; DLQ on ValidationError
```

**Pattern to replace — `_parse_payload`** (lines 56-60, current):

```python
# CURRENT (dead check after payload_model validation):
def _parse_payload(self, payload: dict) -> list | None:
    if not payload.get("signal_id") or not payload.get("event_type"):
        return None
    return [payload]
```

Replace with (receives already-validated `LineageEvent`):

```python
def _parse_payload(self, payload: LineageEvent) -> list | None:
    return [payload]  # D-05: manual check deleted; payload_model enforces fields
```

**Pattern to replace — `_flush_batch` positional tuple** (lines 67-80, current):

```python
# CURRENT (positional tuple construction — anti-pattern):
rows.append((
    event["ts"],         # $1
    event["signal_id"],  # $2
    event["event_type"], # $3
    event["source"],     # $4
    event.get("dag_order"),    # $5
    event.get("multiplier"),   # $6
    event.get("metadata", {}), # $7
    event.get("is_shadow", True), # $8
    event.get("symbol", ""),   # $9
    event.get("tf", ""),       # $10
))
```

Replace using named-field `_to_row()` helper (reference: `feature_writer_agent._record_to_insert_params`, lines 158-203):

```python
def _to_row(self, event: LineageEvent) -> tuple:
    """Map LineageEvent fields to positional INSERT params — explicit, reviewable."""
    return (
        event.ts,         # $1 ts::timestamptz
        str(event.signal_id),  # $2 signal_id::uuid
        event.event_type, # $3 event_type
        event.source,     # $4 source
        event.dag_order,  # $5 dag_order
        event.multiplier, # $6 multiplier
        event.metadata,   # $7 metadata::jsonb
        event.is_shadow,  # $8 is_shadow
        event.symbol,     # $9 symbol
        event.tf,         # $10 tf
    )

async def _flush_batch(self, batch: list[LineageEvent]) -> None:
    rows = [self._to_row(e) for e in batch]
    async with self._pool.acquire() as conn:
        await conn.executemany(
            """INSERT INTO signal_lineage
               (ts, signal_id, event_type, source, dag_order, multiplier,
                metadata, is_shadow, symbol, tf)
               VALUES ($1::timestamptz, $2::uuid, $3, $4, $5, $6, $7::jsonb, $8, $9, $10)
               ON CONFLICT DO NOTHING""",
            rows,
        )
```

---

### `src/core/ai/lineage.py` — `LineageEvent` Pydantic model (PERSIST-01 companion)

**Analog:** `LineageRecorder.record()` call signature (lines 44-56 in `src/core/ai/lineage.py`)

**Pattern — derive field list from producer, not from imagination:**

The `LineageRecorder.record()` method signature defines the canonical field list:

```python
# LineageRecorder.record() signature (lineage.py lines 44-56) — copy these as model fields:
def record(
    self,
    *,
    signal_id: UUID,       # required
    event_type: str,       # required — 'transform' | 'agent_prediction' | 'lifecycle'
    source: str,           # required — transform_id or agent_id
    dag_order: int | None = None,
    multiplier: float | None = None,
    metadata: dict[str, Any] | None = None,
    is_shadow: bool = True,
    symbol: str = "",
    tf: str = "",
) -> None:
```

The `record()` method also builds the row dict with a `"ts"` field set to `datetime.now(UTC).isoformat()` (line 59). `LineageEvent` must include `ts`.

**Pattern to add in `lineage.py`** (co-locate with `LineageRecorder`):

```python
from pydantic import BaseModel, ConfigDict

class LineageEvent(BaseModel):
    """Kafka payload schema for topic_signal_lineage events.

    Field list derived from LineageRecorder.record() signature — no guesswork.
    Co-located with LineageRecorder (sole producer) per D-04.
    """
    model_config = ConfigDict(extra="forbid")

    ts: str            # ISO-8601 UTC timestamp set by LineageRecorder
    signal_id: str     # UUID as str (JSON transport)
    event_type: str    # 'transform' | 'agent_prediction' | 'lifecycle'
    source: str        # transform_id or agent_id
    dag_order: int | None = None
    multiplier: float | None = None
    metadata: dict = {}     # event-specific JSONB
    is_shadow: bool = True  # D-48 default
    symbol: str = ""
    tf: str = ""
```

---

### `services/feature_snapshot_writer_agent.py` (PERSIST-02)

**Analog:** `services/lineage_writer_agent.py`

**Current state:** Already a `BaseWriterAgent` subclass. Overrides `_do_flush()` at lines 96-110 to clear buffer on error instead of re-raising. This is the anti-pattern to delete.

**Pattern to delete — `_do_flush` override** (lines 96-110):

```python
# DELETE THIS ENTIRE OVERRIDE per D-06:
async def _do_flush(self) -> None:
    """Override: shadow table clears buffer on error instead of retrying."""
    if not self._buffer:
        return
    batch = self._buffer[:]
    try:
        await self._flush_batch(batch)
        self._buffer.clear()
        ...
    except Exception:
        self._flush_errors_total.add(1)
        self.logger.exception("shadow_write_failed", rows=len(batch))
        self._buffer.clear()  # <-- silent data loss, the bug
```

**Pattern to inherit — base re-raise** (`base_writer.py` lines 250-288):

After deleting `_do_flush`, the base class contract applies: flush failure re-raises, buffer stays intact, systemd restart reprocesses from last committed Kafka offset. Zero new code needed (D-06).

**Per D-07:** No `_dlq_topic()` needed for shadow table. The `_flush_errors_total` counter (already wired via `BaseWriterAgent.__init__`) plus the `"shadow_write_failed"` structured log is sufficient observability.

---

### `services/signal_metrics_writer_agent.py` (PERSIST-04)

**Analog:** `services/lifecycle_writer_agent.py` (same base migration pattern)

**Current state:** Extends `BaseAgent` (lines 178-245). Per-record writes inside a message loop with swallowed errors. No buffer, no batch, no DLQ.

**Pattern to adopt — `BaseWriterAgent` migration** (model from `lifecycle_writer_agent.py`):

```python
# FROM (current — BaseAgent):
class SignalMetricsWriterAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(name=_AGENT_NAME)
        self._db: DatabaseManager | None = None
        self._kafka_consumer: KafkaConsumerClient | None = None

# TO (migrated — BaseWriterAgent):
class SignalMetricsWriterAgent(BaseWriterAgent):
    BATCH_SIZE = 50       # Claude's discretion per context
    FLUSH_INTERVAL_SECS = 5.0

    payload_model = SignalMetricsEvent  # discriminated union; DLQ on ValidationError

    def __init__(self) -> None:
        super().__init__(name=_AGENT_NAME)
        self._db: DatabaseManager | None = None
        # Remove self._kafka_consumer — use self._create_consumer() in _setup()
```

**Pattern — `_setup()` using `_create_consumer()`** (from `lifecycle_writer_agent.py` lines 201-209):

```python
async def _setup(self) -> None:
    self._db = DatabaseManager(self.settings.database_url)
    await self._db.initialize()

    self._create_consumer()    # assigns self._consumer; offset commits work automatically
    await self._consumer.start()
    self._last_flush = time.monotonic()
    self.logger.info("signal_metrics_writer.setup_complete", topic=self._topic_name())
```

**Pattern — `_topic_name()` and `_consumer_group`**:

```python
def _topic_name(self) -> str:
    return topic_signal_metrics(self.env_name)

@property
def _consumer_group(self) -> str:
    return _CONSUMER_GROUP
```

**Pattern — `_dlq_topic()`** (to add; reference `lineage_writer_agent.py` line 53):

```python
def _dlq_topic(self) -> str | None:
    return topic_signal_metrics_dlq(self.env_name)  # add stream key if not exists
```

**Pattern — `_parse_payload()`** (receives already-validated `SignalMetricsEvent`):

```python
def _parse_payload(self, payload: SignalMetricsEvent) -> list | None:
    return [payload]   # dispatch in _flush_batch by event_type
```

**Pattern — `_flush_batch()` with event_type dispatch** (keeps existing pure SQL helpers, D-01/D-03):

```python
async def _flush_batch(self, batch: list[SignalMetricsEvent]) -> None:
    """Dispatch by event_type to existing pure SQL helper functions."""
    assert self._db is not None
    async with self._db.get_connection() as conn:
        for event in batch:
            if event.event_type == "metrics_computed":
                await _handle_metrics_computed(conn, event.model_dump())
            elif event.event_type == "ic_computed":
                await _handle_ic_computed(conn, event.model_dump())
            elif event.event_type == "metrics_dq_failure":
                await _handle_dq_failure(conn, event.model_dump())
            # Unknown event_type already blocked by discriminated union
```

**Pattern — `_teardown()`** (from `lifecycle_writer_agent.py` lines 214-219):

```python
async def _teardown(self) -> None:
    await super()._teardown()
    if self._consumer:
        await self._consumer.stop()
    if self._db:
        await self._db.close()
```

---

### `src/intelligence/schemas.py` — `SignalMetricsEvent` discriminated union (PERSIST-04 companion)

**Analog:** Existing `IntelligenceEvent` / sub-model pattern in `schemas.py`, plus Pydantic discriminated union standard.

**Pattern — derive field lists from existing handler function signatures** (lines 50-175 in `signal_metrics_writer_agent.py`):

From `_handle_metrics_computed()` (lines 50-124) — fields passed as positional args to `conn.execute()`:

```python
class MetricsComputedEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_type: Literal["metrics_computed"]
    track: str
    setup_plugin: str
    tf: str
    regime_type: str
    window_days: int
    symbol: str = "*"
    n: int
    n_outliers: int
    never_activated_pct: float | None = None
    win_rate: float | None = None
    avg_r: float | None = None
    std_r: float | None = None
    sharpe: float | None = None
    p_value: float | None = None
    avg_mae: float | None = None
    avg_mfe: float | None = None
    computed_at: str        # ISO-8601; handler converts with datetime.fromisoformat()
```

From `_handle_ic_computed()` (lines 127-154):

```python
class ICComputedEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_type: Literal["ic_computed"]
    setup_plugin: str
    tf: str
    regime_type: str
    window_days: int
    symbol: str = "*"
    n: int
    ic: float | None = None
    p_value: float | None = None
    is_significant: bool = False
    computed_at: str
```

From `_handle_dq_failure()` (lines 157-175):

```python
class MetricsDQFailureEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_type: Literal["metrics_dq_failure"]
    signal_id: str          # UUID as str
    reason_code: str
    entry_price: float | None = None
    stop_loss: float | None = None
    pnl_r: float | None = None
    direction: str | None = None
    hmm_regime: str | None = None
    setup_plugin: str | None = None
```

**Pattern — discriminated union assembly** (Pydantic standard with `Annotated` + `Field(discriminator=...)`):

```python
from typing import Annotated, Union
from pydantic import Field

SignalMetricsEvent = Annotated[
    Union[MetricsComputedEvent, ICComputedEvent, MetricsDQFailureEvent],
    Field(discriminator="event_type"),
]
```

Place all three variant models and the `SignalMetricsEvent` union in `src/intelligence/schemas.py` alongside `BarIntelligenceRecord` and other bus schemas per D-02.

---

### `services/llm_writer_service.py` (PERSIST-03)

**Analog:** `services/bar_writer_agent.py` (multi-topic custom `_run()` pattern)

**Current state:** Already a `BaseWriterAgent` subclass. Custom `_run()` handles triple-topic dispatch. The bug is in `_process_outcome_message()` lines 763-768: DB exceptions are logged and DLQ'd but `return False` prevents the exception from propagating to the caller — the `_WRITE_ERRORS` counter is NOT incremented on DB errors, only on outer exception catch.

**Pattern — current swallowed error path** (lines 738-768):

```python
# CURRENT — DB errors inside inner try/except swallowed:
if self.db_manager:
    try:
        ...
        await self.db_manager.execute_batch(_UPDATE_OUTCOME_SQL, [params])
    # <-- no except here for DB errors; falls through to outer except
    ...
except Exception as e:
    self.logger.error("Error processing outcome message", error=str(e))  # generic
    self.error_count_total.add(1)
    self._error_count += 1
    await self._send_to_dlq(payload, e)
    return False   # <-- exception swallowed; _WRITE_ERRORS not incremented
```

**Pattern to apply — make DB errors observable** (D-08):

```python
# AFTER: DB errors increment _WRITE_ERRORS and log structured event, then re-raise
# so the outer loop in _run() receives the exception.
if self.db_manager:
    outcome_at = ...
    params = (...)
    try:
        await self.db_manager.execute_batch(_UPDATE_OUTCOME_SQL, [params])
    except Exception as db_exc:
        _WRITE_ERRORS.add(1, {"agent": _AGENT_NAME, "event_type": "outcome"})
        self.logger.error(
            "outcome_write_failed",
            signal_id=parsed["signal_id"],
            error=str(db_exc),
        )
        raise   # propagate; _run() caller decides crash vs continue
```

Note: `_WRITE_ERRORS` is the existing module-level counter from `signal_metrics_writer_agent.py` pattern — `llm_writer_service.py` uses `self.error_count_total` (named differently). Use whichever counter is declared in that file for the outcome error path.

---

### PERSIST-05: Named Parameter Audit (`lifecycle_writer_agent.py`, `ctx_writer_agent.py`, `bar_writer_agent.py`, `swarm_ledger_writer_agent.py`)

**Reference template:** `services/contract_metadata_writer_agent.py` (named `conn.execute()` with `event.field` attribute access, lines 200-213) and `services/feature_writer_agent.py` `_record_to_insert_params()` (lines 158-203).

#### `services/lifecycle_writer_agent.py` — audit result

`_flush_exit_items()` (lines 148-170): Uses positional `entry.get("field")` args directly in `_db.execute_command()`. **Offender.**

```python
# CURRENT (positional gets, hard to audit — 12 args):
result = await self._db.execute_command(
    self._EXIT_IDEMPOTENT_SQL,
    entry.get("signal_id"),   # $1
    entry.get("status"),      # $2
    entry.get("exit_at"),     # $3
    ...
)
```

**Pattern to apply** — named `_exit_to_params()` helper:

```python
def _exit_to_params(self, entry: dict) -> tuple:
    """Build positional params for EXIT UPDATE — named extraction, explicit positions."""
    return (
        entry.get("signal_id"),    # $1 signal_id::uuid
        entry.get("status"),       # $2 status
        entry.get("exit_at"),      # $3 exit_at
        entry.get("exit_price"),   # $4 exit_price
        entry.get("exit_reason"),  # $5 exit_reason
        entry.get("pnl_r"),        # $6 pnl_r
        entry.get("pnl_dollars"),  # $7 pnl_dollars
        entry.get("signal_quality"), # $8 signal_quality
        entry.get("mae"),          # $9 mae
        entry.get("mfe"),          # $10 mfe
        entry.get("bars_in_trade"), # $11 bars_in_trade
        entry.get("outcome"),      # $12 outcome
    )

async def _flush_exit_items(self, items: list[dict]) -> None:
    for entry in items:
        result = await self._db.execute_command(
            self._EXIT_IDEMPOTENT_SQL,
            *self._exit_to_params(entry),
        )
        ...
```

#### `services/ctx_writer_agent.py` — audit result

`_process_message()` (lines 215, 240): Uses positional tuple literals appended directly to `_event_buffer` and `_snapshot_buffer`. **Offender.**

```python
# CURRENT (positional tuple literals — field order must be memorized):
self._event_buffer.append((event_ts, symbol, event_type, source, inner_payload))
self._snapshot_buffer.append((symbol, event_type, valid_from, ctx_data))
```

**Pattern to apply** — named `_to_event_row()` / `_to_snapshot_row()` helpers:

```python
def _to_event_row(
    self,
    event_ts,
    symbol: str | None,
    event_type: str,
    source: str,
    inner_payload: dict,
) -> tuple:
    """Build positional params for _INSERT_CTX_EVENT_SQL."""
    return (
        event_ts,      # $1 event_ts
        symbol,        # $2 symbol (nullable)
        event_type,    # $3 event_type
        source,        # $4 source
        inner_payload, # $5 payload::jsonb
    )

def _to_snapshot_row(
    self,
    symbol: str | None,
    event_type: str,
    valid_from,
    ctx_data: dict,
) -> tuple:
    """Build positional params for _UPSERT_CTX_SNAPSHOT_SQL."""
    return (
        symbol,     # $1 symbol
        event_type, # $2 event_type
        valid_from, # $3 valid_from
        ctx_data,   # $4 ctx::jsonb
    )
```

#### `services/bar_writer_agent.py` — audit result

`_parse_payload()` (lines 149-173): Returns a 10-element tuple with positional OHLCV fields. **Offender** (positional tuple construction inline).

```python
# CURRENT (10-positional inline tuple):
row = (
    bar.ts,
    bar.symbol,
    base,
    bar.tf,
    bar.open,
    bar.high,
    bar.low,
    bar.close,
    bar.volume,
    source,
)
```

**Pattern to apply** — named `_bar_to_row()` helper:

```python
def _bar_to_row(self, bar: BarMessage, base: str, source: str) -> tuple:
    """Build positional params for _INSERT_OHLCV_SQL."""
    return (
        bar.ts,      # $1 timestamp
        bar.symbol,  # $2 symbol
        base,        # $3 base
        bar.tf,      # $4 timeframe
        bar.open,    # $5 open
        bar.high,    # $6 high
        bar.low,     # $7 low
        bar.close,   # $8 close
        bar.volume,  # $9 volume
        source,      # $10 source
    )
```

#### `services/swarm_ledger_writer_agent.py` — audit result

`_apply_projection()` (lines 209-227): Uses named `conn.execute()` with scalar field args — already named-field style via function parameters. **No positional tuple anti-pattern found.** SQL parameter comments are inline (`# ($1 signal_id::uuid, $2 swarm_multiplier, ...)`). This writer does NOT need `_to_row()` migration; existing pattern is acceptable.

`SwarmLedgerWriterAgent` still extends `BaseAgent` (line 69), not `BaseWriterAgent`. Per CONTEXT.md D-10, the PERSIST-05 audit covers positional tuples only — not a full BaseWriterAgent migration. Planner should confirm whether swarm_ledger needs migration or is out of scope for 085.

---

## Shared Patterns

### `payload_model` ClassVar Gate
**Source:** `src/core/agent/base_writer.py` lines 84, 316-325
**Apply to:** `lineage_writer_agent.py` (PERSIST-01), `signal_metrics_writer_agent.py` (PERSIST-04)

```python
# base_writer.py _run() — how payload_model gates validation:
model_cls = type(self).payload_model
if model_cls is not None:
    try:
        validated = model_cls.model_validate(payload)
        rows = self._parse_payload(validated)
    except ValidationError as exc:
        self._parse_failures_total.add(1)
        await self._maybe_route_to_dlq(payload, exc)
        continue
else:
    rows = self._parse_payload(payload)
```

### DLQ Routing
**Source:** `src/core/agent/base.py` lines 355-381 + `src/core/agent/base_writer.py` line 185
**Apply to:** All writers that declare `_dlq_topic()`

```python
# base.py _send_to_dlq() — called by base on ValidationError or parse failure:
async def _send_to_dlq(self, payload: dict, error: Exception) -> None:
    AGENT_DLQ_TOTAL.add(1, self._dlq_attrs)
    dlq_topic = self._dlq_topic()
    if dlq_topic is None:
        self.logger.error("agent.dlq_discard", ...)
        return
    # Routes DLQPayload to configured topic via producer
```

### Named-Field `_to_row()` Helper Pattern
**Source:** `services/feature_writer_agent.py` lines 158-203
**Apply to:** All PERSIST-05 positional-tuple offenders

```python
# Canonical pattern — _record_to_insert_params in feature_writer_agent.py:
def _record_to_insert_params(record: BarIntelligenceRecord, ...) -> tuple:
    """Build a 31-element tuple — one comment per position."""
    return (
        event.ts,      # $1 ts
        event.symbol,  # $2 symbol
        ...
    )
```

### `_create_consumer()` Setup Pattern
**Source:** `src/core/agent/base_writer.py` lines 160-177
**Apply to:** `signal_metrics_writer_agent.py` — replace manual `KafkaConsumerClient` construction

```python
# base_writer.py _create_consumer() — assigns self._consumer for offset commits:
def _create_consumer(self, topics: list[str] | None = None) -> Any:
    topic_list = topics or [self._topic_name()]
    consumer = KafkaConsumerClient(
        *topic_list,
        bootstrap_servers=self.settings.kafka_bootstrap_servers,
        group_id=self._consumer_group,
        auto_offset_reset="earliest",
        enable_auto_commit=False,
    )
    self._consumer = consumer
    return consumer
```

### `_flush_batch` Re-raise Contract
**Source:** `src/core/agent/base_writer.py` lines 250-288
**Apply to:** `feature_snapshot_writer_agent.py` (PERSIST-02) — delete `_do_flush` override

```python
# base_writer.py _do_flush() — buffer left intact on exception:
except Exception as exc:
    span.set_status(StatusCode.ERROR, str(exc))
    self._flush_errors_total.add(1)
    self.logger.exception("flush_failed", batch_size=len(batch))
    raise  # buffer NOT cleared; systemd restart reprocesses from committed offset
```

---

## No Analog Found

All files in scope have strong analogs in the existing codebase. No files require falling back to RESEARCH.md patterns.

---

## Positional Tuple Audit Summary

| Writer | Offending Location | Anti-pattern Type | Migration |
|---|---|---|---|
| `lineage_writer_agent.py` | `_flush_batch` lines 67-80 | 10-element tuple from `event[]` dict keys | `_to_row(LineageEvent)` helper |
| `lifecycle_writer_agent.py` | `_flush_exit_items` lines 148-162 | 12 positional `entry.get()` args to `execute_command` | `_exit_to_params(entry)` helper |
| `ctx_writer_agent.py` | `_process_message` lines 215, 240 | 4- and 5-element positional tuple literals | `_to_event_row()` + `_to_snapshot_row()` helpers |
| `bar_writer_agent.py` | `_parse_payload` lines 162-172 | 10-element positional tuple inline | `_bar_to_row(bar, base, source)` helper |
| `swarm_ledger_writer_agent.py` | `_apply_projection` lines 209-227 | Named params via function args — no violation | No migration needed |
| `feature_snapshot_writer_agent.py` | None (delegates to `_record_to_insert_params`) | No violation | No migration needed |

---

## Metadata

**Analog search scope:** `services/`, `src/core/agent/`, `src/intelligence/`, `src/core/ai/`
**Files scanned:** 11 source files read in full
**Pattern extraction date:** 2026-05-17
