# Phase 2: Feature Store - Research

**Researched:** 2026-02-23
**Domain:** TimescaleDB hypertable design, async Redis consumer groups, asyncpg batch writes, signal_ledger schema migration
**Confidence:** HIGH

## Summary

Phase 2 builds the durable persistence layer beneath the intelligence bus. Every `IntelligenceEvent` published to the `intelligence:SYMBOL:TF` Redis stream by `market_analysis_service.py` must be consumed by a standalone `feature_writer_service.py` and batch-written to a new `intelligence_features` TimescaleDB hypertable. Simultaneously, `signal_ledger` gains two FK-like columns (`feature_ts`, `feature_tf`) so signals can be JOINed back to the full feature context they were generated from — the key enabler for ML training in Phase 5.

All patterns for this phase already exist in the codebase. `market_analysis_service.py` and `signal_generator_service.py` are the reference implementations for the consumer group + asyncpg batch-write pattern. The `DatabaseManager.execute_batch()` method uses `asyncpg` `executemany` inside a transaction — use it directly. The migration numbering convention is `009_` (current max is `008`). The `signal_ledger` schema is confirmed live with no `feature_ts`/`feature_tf` columns yet.

**Primary recommendation:** Clone the `market_analysis_service.py` consumer-group loop skeleton for `feature_writer_service.py`; replace the plugin pipeline body with a single batch INSERT to `intelligence_features`; add `feature_ts`/`feature_tf` to `signal_ledger` via a separate migration; update `signal_generator_service.py`'s `build_ledger_entries()` to populate those columns from the `IntelligenceEvent.ts` and `IntelligenceEvent.tf` fields already available in the parse result.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| FST-01 | `intelligence_features` TimescaleDB hypertable created with tiered JSONB columns, GIN indexes, no retention policy | Migration 009 creates hypertable; tiered JSONB mirrors `IntelligenceEvent` sub-model structure; GIN indexes on each tier column for `@>` queries; no `add_retention_policy` call — indefinite storage by design |
| FST-02 | Feature Writer Service (`services/feature_writer_service.py`) consumes `intelligence:` stream via consumer group and batch-writes to `intelligence_features` | Consumer group pattern confirmed in `market_analysis_service.py` and `signal_generator_service.py`; `DatabaseManager.execute_batch()` is the batch writer; consumer group name convention `feature_writer:persist` from design doc |
| FST-03 | `signal_ledger` gains `feature_ts` + `feature_tf` columns enabling JOIN to full feature context | `ALTER TABLE` migration adds nullable `TIMESTAMPTZ` and `TEXT` columns; `LedgerEntry` dataclass and `_INSERT_SQL` in `signal_ledger.py` updated; `build_ledger_entries()` in `signal_generator_service.py` populates from `event.ts` / `event.tf` |
| FST-04 | DB compressed after 7 days, indefinite retention for seasonal ML analysis | `add_compression_policy('intelligence_features', INTERVAL '7 days')` in migration; NO `add_retention_policy` call — explicit design decision from design doc |
</phase_requirements>

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| asyncpg | >=0.31.0 | Async PostgreSQL driver, batch inserts | Already in requirements.txt; used by `DatabaseManager.execute_batch()` |
| redis[hiredis] | >=7.1.0 | Async Redis consumer group reads | Already in requirements.txt; `redis.asyncio` used by all services |
| pydantic | >=2.12.0 | `IntelligenceEvent.model_validate_json()` deserialization | Already in requirements.txt; Phase 1 established the schema |
| structlog | >=25.5.0 | Structured JSON logging | Already in requirements.txt; all services use it |
| prometheus-client | >=0.24.0 | Metrics counters/gauges | Already in requirements.txt; `src/observability/metrics.py` helper exists |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| asyncio | stdlib | Async task loop, graceful shutdown | Service main loop and signal handling |
| TimescaleDB | running | Hypertable, compression, chunking | Via `asyncpg`; no separate Python driver needed |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `asyncpg` batch via `execute_batch` | psycopg2 `execute_batch` | psycopg2 is sync; asyncpg is already the project standard for async services |
| Per-message INSERT | Buffered batch (collect N events then flush) | Buffered batch is strictly better for hypertable write throughput; 10-50 event buffer per symbol/tf is safe |
| Separate TimescaleDB table per tier | Single table with tiered JSONB columns | Single table matches design decision; tiered JSONB = queryable per-tier without schema migration |

**Installation:** No new packages required — all dependencies already installed.

---

## Architecture Patterns

### Recommended Project Structure

```
services/
└── feature_writer_service.py    # new — consumer group reader + batch writer

src/intelligence/
└── schemas.py                   # existing — IntelligenceEvent used for deserialization

src/intelligence/trading/
└── signal_ledger.py             # existing — add feature_ts/feature_tf to LedgerEntry + _INSERT_SQL

production/migrations/
├── 009_intelligence_features.sql      # new — hypertable + compression + GIN indexes
└── 010_signal_ledger_feature_cols.sql # new — ALTER TABLE signal_ledger ADD COLUMN feature_ts/tf

tests/unit/service_tests/
└── test_feature_writer_service.py     # new — unit tests for consumer loop, batch writer, parse
```

### Pattern 1: Consumer Group Loop (established pattern)

**What:** `xgroup_create` once at startup, then `xreadgroup` with `">"` to claim undelivered messages, `xack` after successful processing.

**When to use:** Any service that must not miss events (at-least-once delivery).

**Example (from `signal_generator_service.py`):**
```python
# Source: services/signal_generator_service.py lines 306-316, 459-478

async def _setup_consumer_groups(self) -> None:
    from src.core.stream_keys import intelligence as sk_intel
    for tf in self.config["service"]["timeframes"]:
        for sym in self.config["service"]["symbols"]:
            stream_name = sk_intel(self.env_prefix, sym, tf)
            try:
                await self.redis_client.xgroup_create(
                    stream_name, self.consumer_group, "0", mkstream=True
                )
            except Exception:
                pass  # group already exists — normal on restart

async def _process_loop(self) -> None:
    while self.running and not self.shutdown_requested:
        for tf in self.config["service"]["timeframes"]:
            for sym in self.config["service"]["symbols"]:
                stream_name = sk_intel(self.env_prefix, sym, tf)
                messages = await self.redis_client.xreadgroup(
                    self.consumer_group,
                    self.consumer_name,
                    {stream_name: ">"},
                    count=10,
                    block=100,
                )
                for _stream, msgs in messages:
                    for message_id, fields in msgs:
                        await self._process_single_message(
                            sym, tf, fields, stream_name, message_id
                        )
        await asyncio.sleep(self.config["service"]["processing_interval"])
```

### Pattern 2: IntelligenceEvent Deserialization (established pattern)

**What:** Parse the `b"event"` JSON field from the stream message into a typed `IntelligenceEvent`. Return `None` and ack-and-skip on failure.

**When to use:** Any consumer of the `intelligence:` stream.

**Example (from `signal_generator_service.py`):**
```python
# Source: services/signal_generator_service.py lines 73-85

def _parse_intelligence_event(fields: dict[bytes, bytes]) -> IntelligenceEvent | None:
    raw = fields.get(b"event", b"")
    if not raw:
        return None
    try:
        return IntelligenceEvent.model_validate_json(raw)
    except (ValidationError, ValueError) as e:
        logger.warning("Failed to parse IntelligenceEvent", error=str(e))
        return None
```

### Pattern 3: Asyncpg Batch Write (established pattern)

**What:** `DatabaseManager.execute_batch(sql, params)` — executes `executemany` inside a single transaction. Rolls back on failure.

**When to use:** Inserting multiple rows atomically.

**Example (from `src/core/database_manager.py`):**
```python
# Source: src/core/database_manager.py lines 61-78

async def execute_batch(self, statement: str, params: list[list[Any]] | list[tuple]) -> None:
    if not params:
        return
    async with self.get_connection() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            await conn.executemany(statement, params)
            await tr.commit()
        except Exception:
            await tr.rollback()
            raise
```

### Pattern 4: TimescaleDB Hypertable + Compression (established pattern)

**What:** `CREATE TABLE` → `create_hypertable` → `ALTER TABLE SET (timescaledb.compress...)` → `add_compression_policy`. No `add_retention_policy` for `intelligence_features`.

**When to use:** Every time-series table. Compress-orderby must be `ASC` (lesson from migration 007).

**Example (from `production/migrations/007_fix_compress_orderby_and_retention.sql`):**
```sql
-- Source: production/migrations/007_fix_compress_orderby_and_retention.sql

ALTER TABLE IF EXISTS signal_ledger SET (
    timescaledb.compress = true,
    timescaledb.compress_segmentby = 'symbol,setup_plugin',
    timescaledb.compress_orderby = 'timestamp ASC'  -- ASC, not DESC
);

DO $$ BEGIN
  PERFORM add_compression_policy('signal_ledger', INTERVAL '30 days', if_not_exists => true);
EXCEPTION WHEN others THEN NULL; END $$;
```

### Pattern 5: ADD COLUMN Migration (ALTER TABLE pattern)

**What:** Add nullable columns to existing hypertable via `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`. TimescaleDB supports this without decompressing.

**Example (inferred from project migration style):**
```sql
-- Production migration pattern used in this project
ALTER TABLE signal_ledger
    ADD COLUMN IF NOT EXISTS feature_ts  TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS feature_tf  TEXT;

CREATE INDEX IF NOT EXISTS idx_ledger_feature_ts
    ON signal_ledger (feature_ts)
    WHERE feature_ts IS NOT NULL;
```

### Anti-Patterns to Avoid

- **Consumer group name with timestamp suffix** (like `signal_generator_{int(time.time())}`): The existing services do this, creating a new group on every restart and accumulating stale groups. For `feature_writer_service.py`, use a fixed group name `feature_writer:persist` so restarts resume from the last acknowledged position. This is the convention from the design doc.
- **compress_orderby = 'timestamp DESC'**: Migration 007 exists specifically to fix this mistake. Always use ASC.
- **Per-message INSERT vs batch**: Writing one row per event kills hypertable throughput. Buffer events and flush as a batch (either N events or time-based flush interval).
- **Dropping the `intelligence` table write**: `market_analysis_service.py` currently writes to the old `intelligence` table via `_persist_intelligence`. Do NOT remove this yet — it may have undocumented consumers. The feature writer service is additive.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Consumer group at-least-once delivery | Custom retry loop | Redis XREADGROUP + XACK | Already built into Dragonfly/Redis protocol |
| Async DB connection pooling | Manual connection management | `DatabaseManager` (asyncpg pool) | Already exists in `src/core/database_manager.py` |
| Event deserialization + validation | Custom JSON parser | `IntelligenceEvent.model_validate_json()` | Phase 1 defined the schema; use it |
| Hypertable chunk management | Manual partitioning | TimescaleDB `create_hypertable` | Automatic chunk creation and management |
| Batch write transactions | Manual BEGIN/COMMIT | `DatabaseManager.execute_batch()` | Already wraps `executemany` in transaction with rollback |
| Prometheus metrics registry | Custom counter dict | `src/observability/metrics.py` `counter()` / `gauge()` | Guards against duplicate registration errors |

**Key insight:** The entire service is glue code — deserialization already done (Phase 1 schemas), DB write already done (DatabaseManager), consumer group pattern already done (signal_generator). The novel piece is the `intelligence_features` schema and the `_INSERT_SQL` for it.

---

## Common Pitfalls

### Pitfall 1: Fixed vs Dynamic Consumer Group Name

**What goes wrong:** Using `f"feature_writer_{int(time.time())}"` (like existing services do) means every restart creates a NEW consumer group starting from `"0"`. All pending/unacknowledged messages from the previous group are abandoned. Events missed during downtime are never written to `intelligence_features`.

**Why it happens:** The existing services (signal_generator, market_analysis) have stateless processing — missing a bar on restart is acceptable. The feature writer must be stateful — it must resume from the last written position.

**How to avoid:** Use fixed group name `feature_writer:persist`. On `xgroup_create`, catch `ResponseError` (group exists) and continue — this is the correct pattern.

**Warning signs:** Consumer group count in Redis growing unboundedly (`XINFO GROUPS intelligence:ESH6:5m` shows many groups).

### Pitfall 2: asyncpg JSONB Serialization

**What goes wrong:** Passing a Python dict directly to asyncpg for a `JSONB` column raises `asyncpg.exceptions.UnsupportedClientError`. asyncpg does not auto-serialize dicts to JSON.

**Why it happens:** asyncpg maps Python types directly to Postgres types. Dict → JSONB is not automatic.

**How to avoid:** Call `json.dumps(the_dict)` and cast in SQL with `$N::jsonb`. Already established in `signal_ledger.py`'s `to_insert_params()` — same pattern applies to `intelligence_features`.

**Warning signs:** `asyncpg.exceptions.InvalidTextRepresentation` or `UnsupportedClientError` on INSERT.

### Pitfall 3: GIN Index on NULL JSONB

**What goes wrong:** GIN indexes on JSONB columns that contain `NULL` values slow down index builds and can cause `NULL` pointer issues in old versions of GIN operators.

**Why it happens:** During warm-up, some tier outputs may be empty `{}`. A GIN index on an empty JSONB object is fine, but `NULL` (not `{}`) at the column level breaks GIN.

**How to avoid:** Use `NOT NULL DEFAULT '{}'::jsonb` on all tiered JSONB columns. The `IntelligenceEvent` sub-models always produce a dict (possibly empty), never `None`.

**Warning signs:** GIN index build fails during migration, or queries with `@>` operator return unexpected results.

### Pitfall 4: compress_orderby DESC vs ASC

**What goes wrong:** TimescaleDB compresses chunks by sorting on `compress_orderby`. DESC means forward time scans (which cover most queries) decompress in reverse order — worse locality.

**Why it happens:** Copying old migration patterns without reading migration 007's comment about why it was written.

**How to avoid:** Always use `compress_orderby = 'timestamp ASC'`. Migration 007 documented this lesson explicitly.

**Warning signs:** Slow analytical queries despite compression enabled.

### Pitfall 5: Signal Ledger Column Addition Without Null Default

**What goes wrong:** `ALTER TABLE signal_ledger ADD COLUMN feature_ts TIMESTAMPTZ NOT NULL` fails because existing rows have no value.

**Why it happens:** `signal_ledger` already has rows (after backfill runs in Phase 3). Adding `NOT NULL` without a default fails.

**How to avoid:** Add columns as nullable (`feature_ts TIMESTAMPTZ`, no NOT NULL). Historical signals before Phase 2 will have `NULL` feature_ts — that is expected and correct. Phase 3 backfill will need to decide whether to populate these or leave them NULL.

**Warning signs:** `ERROR: column "feature_ts" of relation "signal_ledger" contains null values`.

### Pitfall 6: Metrics Port Conflict

**What goes wrong:** `feature_writer_service.py` calls `start_metrics_server(port=9115)` but that port is already taken by another service.

**Why it happens:** Each service must use a unique Prometheus port. Current allocations: indicator_service=9111, signal_generator=9112, ai_narrative=9113, market_analysis=9114.

**How to avoid:** Assign `feature_writer_service` port `9115`. Document in the service config.

---

## Code Examples

Verified patterns from codebase:

### intelligence_features INSERT SQL (new — pattern from signal_ledger.py)
```python
# Pattern: modeled on signal_ledger.py _INSERT_SQL
# Each tier column is a serialized JSONB dict

_INSERT_FEATURE_SQL = """
INSERT INTO intelligence_features (
    ts, symbol, tf, platform, source, schema_version,
    bar, i1, i3, i4, i5, smc, i6
) VALUES (
    $1, $2, $3, $4, $5, $6,
    $7::jsonb, $8::jsonb, $9::jsonb, $10::jsonb, $11::jsonb, $12::jsonb, $13::jsonb
)
ON CONFLICT (ts, symbol, tf) DO NOTHING
"""

def _event_to_insert_params(event: IntelligenceEvent) -> tuple:
    return (
        event.ts,
        event.symbol,
        event.tf,
        event.platform,
        event.source,
        event.schema_version,
        json.dumps(event.bar.model_dump()),
        json.dumps({k: v for k, v in event.i1.model_dump().items() if v is not None}),
        json.dumps(event.i3.model_dump(exclude_none=True)),
        json.dumps(event.i4.model_dump(exclude_none=True)),
        json.dumps(event.i5.model_dump(exclude_none=True)),
        json.dumps(event.smc.model_dump(exclude_none=True)),
        json.dumps(event.i6.model_dump(exclude_none=True)),
    )
```

### intelligence_features hypertable DDL (migration 009)
```sql
CREATE TABLE IF NOT EXISTS intelligence_features (
    ts              TIMESTAMPTZ     NOT NULL,
    symbol          TEXT            NOT NULL,
    tf              TEXT            NOT NULL,
    platform        TEXT            NOT NULL DEFAULT 'futures',
    source          TEXT            NOT NULL DEFAULT 'live',   -- 'live' | 'backfill'
    schema_version  TEXT            NOT NULL DEFAULT '1.0',
    -- Tiered JSONB columns — one per IntelligenceEvent sub-model
    bar             JSONB           NOT NULL DEFAULT '{}',
    i1              JSONB           NOT NULL DEFAULT '{}',
    i3              JSONB           NOT NULL DEFAULT '{}',
    i4              JSONB           NOT NULL DEFAULT '{}',
    i5              JSONB           NOT NULL DEFAULT '{}',
    smc             JSONB           NOT NULL DEFAULT '{}',
    i6              JSONB           NOT NULL DEFAULT '{}',
    PRIMARY KEY (ts, symbol, tf)
);

SELECT create_hypertable(
    'intelligence_features', 'ts',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

-- Composite index for common query pattern: symbol + timeframe + time range
CREATE INDEX IF NOT EXISTS idx_intel_features_sym_tf_ts
    ON intelligence_features (symbol, tf, ts DESC);

-- GIN indexes for per-tier JSONB field queries (e.g. WHERE i4 @> '{"garch_vol_regime": 1}')
CREATE INDEX IF NOT EXISTS idx_intel_features_i1_gin  ON intelligence_features USING GIN (i1);
CREATE INDEX IF NOT EXISTS idx_intel_features_i3_gin  ON intelligence_features USING GIN (i3);
CREATE INDEX IF NOT EXISTS idx_intel_features_i4_gin  ON intelligence_features USING GIN (i4);
CREATE INDEX IF NOT EXISTS idx_intel_features_i5_gin  ON intelligence_features USING GIN (i5);
CREATE INDEX IF NOT EXISTS idx_intel_features_smc_gin ON intelligence_features USING GIN (smc);
CREATE INDEX IF NOT EXISTS idx_intel_features_i6_gin  ON intelligence_features USING GIN (i6);

-- Compression: 7-day policy, no retention (indefinite storage by design)
ALTER TABLE intelligence_features SET (
    timescaledb.compress = true,
    timescaledb.compress_segmentby = 'symbol,tf',
    timescaledb.compress_orderby   = 'ts ASC'
);

DO $$ BEGIN
  PERFORM add_compression_policy('intelligence_features', INTERVAL '7 days', if_not_exists => true);
EXCEPTION WHEN others THEN NULL; END $$;

-- NO add_retention_policy — indefinite retention is the design decision
```

### signal_ledger column migration (migration 010)
```sql
-- Add feature linkage columns to signal_ledger
ALTER TABLE signal_ledger
    ADD COLUMN IF NOT EXISTS feature_ts  TIMESTAMPTZ,   -- NULL for signals before Phase 2
    ADD COLUMN IF NOT EXISTS feature_tf  TEXT;           -- NULL for signals before Phase 2

-- Partial index (only rows that have feature linkage)
CREATE INDEX IF NOT EXISTS idx_ledger_feature_ts
    ON signal_ledger (feature_ts)
    WHERE feature_ts IS NOT NULL;
```

### LedgerEntry update for feature_ts/feature_tf
```python
# Source: src/intelligence/trading/signal_ledger.py
# Add to LedgerEntry dataclass:
feature_ts: datetime | None = None
feature_tf: str | None = None

# Update to_insert_params() — now returns 24-element tuple:
# ...existing 22 fields..., feature_ts, feature_tf

# Update _INSERT_SQL to include feature_ts ($23), feature_tf ($24)
# Update build_ledger_entries() in signal_generator_service.py:
entries.append(LedgerEntry(
    ...
    feature_ts=timestamp,   # event.ts — same timestamp as the intelligence event
    feature_tf=timeframe,   # event.tf — same timeframe
))
```

### Buffered batch flush pattern for feature_writer_service
```python
# Buffer events by (symbol, tf) and flush when buffer reaches BATCH_SIZE or FLUSH_INTERVAL elapses
BATCH_SIZE = 50
FLUSH_INTERVAL_SECS = 5.0

async def _maybe_flush(self, force: bool = False) -> None:
    now = time.time()
    if force or (now - self._last_flush) >= FLUSH_INTERVAL_SECS:
        all_params = []
        for buf in self._buffer.values():
            all_params.extend(buf)
        if all_params and self.db_manager:
            await self.db_manager.execute_batch(_INSERT_FEATURE_SQL, all_params)
            self._buffer.clear()
            self._last_flush = now
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `intelligence` table: flat scalar-only JSONB | `intelligence_features`: tiered JSONB per sub-model | Phase 2 | Arrays, nested objects, all 150+ fields preserved |
| `compress_orderby = 'timestamp DESC'` | `compress_orderby = 'timestamp ASC'` | Migration 007 (2026-02-19) | Forward scan performance |
| Flat string k/v in intelligence stream | Single `{"event": "<json>"}` IntelligenceEvent | Phase 1 (2026-02-23) | Typed, validated, versionable |
| `intelligence_processor_service.py` (parallel pipeline) | `market_analysis_service.py` (sole pipeline) | Phase 1 (2026-02-23) | Single source of truth |

**Still present (not deprecated yet):**
- `_persist_intelligence()` in `market_analysis_service.py`: Writes to old `intelligence` table. Leave in place for Phase 2 — the feature writer is additive. Can be removed in a future cleanup phase once `intelligence_features` is confirmed operational.
- `features` table: Exists in DB (migration 001), never written to. Remains unused. Not to be confused with `intelligence_features` (the new table).

---

## Open Questions

1. **Batch size / flush strategy**
   - What we know: `DatabaseManager.execute_batch()` wraps `executemany` in a single transaction. Larger batches = fewer round trips = better throughput, but higher memory and longer transaction hold time.
   - What's unclear: Optimal batch size for the expected event rate (3 symbols × 4 timeframes = 12 events/bar, bars every 1-60 seconds depending on timeframe).
   - Recommendation: Start with `BATCH_SIZE=50` and a 5-second time-based flush. Adjust based on observed write latency in Prometheus metrics.

2. **Consumer group name for signal_generator_service**
   - What we know: `signal_generator_service.py` uses `f"signal_generator_{int(time.time())}"` — a new group on every restart, which means it processes events from the beginning of the stream each time (position `"0"`).
   - What's unclear: Whether this was intentional (idempotent processing) or accidental.
   - Recommendation: Do NOT change signal_generator's group name in Phase 2 — out of scope. Feature writer uses its own fixed group `feature_writer:persist`.

3. **`intelligence` table write removal**
   - What we know: `market_analysis_service._persist_intelligence()` writes to the old `intelligence` table with scalar-only data. The new `intelligence_features` table makes this redundant.
   - What's unclear: Whether any external code, dashboards, or queries read from the `intelligence` table.
   - Recommendation: Leave `_persist_intelligence()` in place for Phase 2. Removal is a separate cleanup task after verifying `intelligence_features` is operational.

4. **Backfill compatibility (Phase 3 concern)**
   - What we know: `historical_backfill.py` Stage 2 inserts to `signal_ledger` using psycopg2 `execute_batch`. Adding `feature_ts`/`feature_tf` columns to `signal_ledger` means the backfill INSERT will fail with too few params unless updated simultaneously.
   - What's unclear: Whether Phase 3 plan will update `historical_backfill.py` to populate these columns.
   - Recommendation: Plan 02-03 must update `historical_backfill.py`'s `LedgerEntry` construction to pass `feature_ts`/`feature_tf` (or explicitly pass `NULL`) to avoid breaking Stage 2. Flag this dependency in the plan.

---

## Sources

### Primary (HIGH confidence)
- `/home/bg/dev/indicagent/services/market_analysis_service.py` — consumer group pattern, `_process_market_data`, `_setup_consumer_groups`, `_publish_intelligence`, `_persist_intelligence`
- `/home/bg/dev/indicagent/services/signal_generator_service.py` — `_parse_intelligence_event`, `build_ledger_entries`, `_process_single_message`, `_process_loop`
- `/home/bg/dev/indicagent/src/core/database_manager.py` — `execute_batch`, asyncpg pool pattern
- `/home/bg/dev/indicagent/src/intelligence/trading/signal_ledger.py` — `LedgerEntry`, `_INSERT_SQL`, `to_insert_params()`
- `/home/bg/dev/indicagent/src/intelligence/schemas.py` — `IntelligenceEvent`, all sub-models, field inventory
- `/home/bg/dev/indicagent/production/migrations/007_fix_compress_orderby_and_retention.sql` — hypertable compression pattern, ASC orderby lesson
- `/home/bg/dev/indicagent/production/scripts/db_setup.sh` — migration execution order (base schema first, then 0NN_ numbered files)
- `/home/bg/dev/indicagent/src/core/stream_keys.py` — stream name helpers
- `/home/bg/dev/indicagent/src/observability/metrics.py` — Prometheus counter/gauge helpers, port assignments
- Live DB schema confirmed: `signal_ledger` has no `feature_ts`/`feature_tf` columns; next migration is `009`; `intelligence_features` table does not exist yet

### Secondary (MEDIUM confidence)
- `/home/bg/dev/indicagent/docs/plans/2026-02-22-unified-intelligence-data-bus-design.md` — design decisions: fixed consumer group name `feature_writer:persist`, indefinite retention, 7-day compression, tiered JSONB schema choice
- `/home/bg/dev/indicagent/.planning/STATE.md` — accumulated decisions from Phase 1 execution

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already in requirements.txt and in active use
- Architecture: HIGH — consumer group pattern and batch write pattern are directly cloned from existing services
- DB schema: HIGH — confirmed against live DB; `\d signal_ledger` shows exact current columns
- Pitfalls: HIGH — most come from existing migration history (007) and signal_ledger.py's JSONB serialization pattern
- Batch sizing: MEDIUM — no production load data yet; recommendation is reasonable starting point

**Research date:** 2026-02-23
**Valid until:** 2026-04-23 (stable domain — TimescaleDB and asyncpg APIs are stable)
