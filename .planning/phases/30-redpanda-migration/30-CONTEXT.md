# Phase 30: Redpanda Migration - Context

**Gathered:** 2026-03-13
**Status:** Ready for planning
**Source:** PRD Express Path (memory/project_redpanda_migration.md + docs/ideas/tech-stack.md)

<domain>
## Phase Boundary

Replace DragonflyDB (Redis Streams) with Redpanda as the event bus across all 8 services. Remove DragonflyDB from the stack entirely. What remains: Redpanda (streams) + PostgreSQL/TimescaleDB (cold tier). This is a pure transport-layer migration — no business logic changes, no plugin changes, no schema changes.

**Scope:** All 8 services + stream_utils.py + stream_keys.py + test fixtures + docker-compose.yml.
**Not in scope:** IntelligenceEvent schema, I1–I8 plugins, TimescaleDB, IBKR/TWS integration, Dashboard UI, Prometheus metrics.

</domain>

<decisions>
## Implementation Decisions

### Client Library
- **aiokafka** — async Kafka client for Python. Replaces `redis.asyncio` streams entirely.
- Remove `redis[hiredis]` from requirements.txt (no remaining Redis dependency after migration).
- No `confluent-kafka` — aiokafka is pure Python asyncio, matches the existing async service pattern.

### Infrastructure
- Redpanda runs as a single container in `production/docker-compose.yml` for local dev/prod.
- Redpanda replaces DragonflyDB container. DragonflyDB container removed from compose.
- Redpanda ports: 9092 (Kafka), 9644 (admin/metrics), 8082 (HTTP proxy — optional).
- Use `redpandadata/redpanda:latest` official image.
- Topic creation: dedicated topic init script run at startup (or via compose `depends_on`).

### Topic Design (locked — from docs/ideas/tech-stack.md)
One topic per event type, message key = `SYMBOL:TF` for partition routing.
`dev.` prefix = development env, controlled by `settings.env_name` (same as current `env_prefix`).

| Current Redis Stream | Redpanda Topic | Message Key |
|---|---|---|
| `ticks:SYMBOL:live` | `{env}.market.ticks` | `SYMBOL` |
| `market:SYMBOL:TF` | `{env}.market.bars` | `SYMBOL:TF` |
| `indicators:SYMBOL:TF` | `{env}.indicators` | `SYMBOL:TF` |
| `intelligence:SYMBOL:TF` | `{env}.intelligence` | `SYMBOL:TF` |
| `intelligence_i7:SYMBOL:TF` | `{env}.intelligence.i7` | `SYMBOL:TF` |
| `intelligence_i8:SYMBOL:TF` | `{env}.intelligence.i8` | `SYMBOL:TF` |
| `signals:SYMBOL:TF` | `{env}.signals` | `SYMBOL:TF` |
| `signals:SYMBOL:TF:aggregated` | `{env}.signals.aggregated` | `SYMBOL:TF` |
| `narratives:SYMBOL:TF` | `{env}.narratives` | `SYMBOL:TF` |
| `llm_calls:stream` | `{env}.llm.calls` | plain (no key) |
| `llm_outcomes:stream` | `{env}.llm.outcomes` | plain (no key) |

### stream_keys.py Rewrite
- Replace Redis key builders with Kafka topic + message key helpers.
- `get_stream_maxlen()` → Kafka topic retention config (set at topic creation, not per-publish).
- Topic names are the new "stream keys". `stream_keys.py` becomes `topic_keys.py` or updated in-place.
- `env_prefix` → `env_name` (e.g., `"dev"`) used as topic prefix.

### stream_utils.py Rewrite
- Replace `XGROUP_CREATE`/`XGROUP_SETID` pattern with aiokafka consumer group management.
- Consumer group creation is implicit in Kafka — just subscribe and commit offsets.
- `ensure_consumer_group_with_reset()` disappears entirely — Kafka consumer groups track offsets durably.
- Producer: `AIOKafkaProducer`. Consumer: `AIOKafkaConsumer` with `group_id` and `auto_offset_reset="latest"` for services that only care about live data.
- Services that need replay from restart: `auto_offset_reset="earliest"` or committed offset resume.

### price:SYMBOL:latest Replacement (locked)
- Remove HSET/HGETALL from `tws_daemon`. No Redis hash writes.
- `signal_generator_service` maintains in-process dict `self._live_quotes: dict[str, dict]`.
- TWS daemon publishes tick events to `{env}.market.ticks` topic.
- `signal_generator_service` subscribes to ticks topic, updates `self._live_quotes` in real-time.
- Fallback: if `_live_quotes` has no entry for a symbol at signal time, use `None` (same current behavior on HGETALL miss).

### Cache Migration (locked)
All Redis-backed caches replaced with in-process dicts, DB-backed for persistence:
- **Drift detection cache** (`_drift_states`) — already in-memory in market_analysis_service.
- **LLM model scores** (`llm_model_scores` table) — already DB-backed; score cache re-warms from DB on startup.
- **Setup performance** (`setup_performance` table) — already DB-backed; performance cache re-warms from DB on startup.
- No explicit cache migration needed — these were already DB-primary, Redis was redundant.

### Service-by-Service Migration Order (5-plan breakdown — locked)
- **Plan 1:** Infrastructure + Core Abstractions
  - Redpanda container in docker-compose.yml (alongside DragonflyDB — dual-run during migration)
  - aiokafka added to requirements.txt
  - `stream_utils.py` rewrite: aiokafka producer/consumer helpers
  - `stream_keys.py` rewrite: topic + message key builders
  - Topic init script: create all topics with correct retention/partition settings
  - Unit tests for new stream_utils and stream_keys
- **Plan 2:** Hot Tier + Intelligence Pipeline
  - `tws_daemon` → publish to Redpanda market.bars + market.ticks (remove Redis XADD + HSET)
  - `timeframes_builder_service` → consume from Redpanda market.bars, publish to Redpanda market.bars (higher TFs)
  - `indicator_service` → consume from Redpanda market.bars, publish to Redpanda indicators
  - `market_analysis_service` → consume from Redpanda indicators, publish to Redpanda intelligence
- **Plan 3:** Signal + AI Services
  - `signal_generator_service` → consume from Redpanda intelligence + market.ticks (for live quotes), publish to Redpanda signals + signals.aggregated; remove HGETALL, add `_live_quotes` dict
  - `signal_lifecycle_service` → consume from Redpanda market.bars + signals.aggregated, publish to Redpanda llm.outcomes
  - `ai_narrative_service` → consume from Redpanda intelligence, publish to Redpanda narratives + llm.calls
- **Plan 4:** Writer Services + API/SSE
  - `feature_writer_service` → consume from Redpanda intelligence, write to TimescaleDB (no change to DB logic)
  - `llm_writer_service` → consume from Redpanda llm.calls + llm.outcomes, write to TimescaleDB
  - API SSE (`src/api/sse.py`) → subscribe to Redpanda topics instead of Redis streams
- **Plan 5:** Cache Migration + DragonflyDB Removal + E2E Validation
  - Remove DragonflyDB container from docker-compose.yml
  - Remove `redis[hiredis]` from requirements.txt
  - Remove all remaining Redis imports (verify none remain outside src/providers/ibkr.py)
  - Full E2E test: services start, tws_daemon publishes, intelligence pipeline flows, signals fire, dashboard receives via SSE
  - Prometheus metrics verify: all service metrics healthy post-migration

### What Does NOT Change (locked)
- `IntelligenceEvent` schema (`src/intelligence/schemas.py`) — untouched
- I1–I8 plugin logic — untouched
- TimescaleDB tables and queries — untouched
- IBKR/TWS integration (`src/providers/ibkr.py`) — untouched
- Dashboard UI — untouched (SSE event structure unchanged, only SSE backend migrated)
- Prometheus metrics — untouched
- `src/config/settings.py` — `env_name` already exists; minor update to expose as topic prefix

### Dual-Run Strategy (migration safety)
- Plan 1-4: DragonflyDB stays running alongside Redpanda. Services are migrated one at a time.
- No service publishes to BOTH — once migrated, the service is Redpanda-only.
- Plan 5: After all 8 services migrated and E2E verified, DragonflyDB removed.
- systemd services restarted one at a time; verified with journalctl before moving to next.

### Testing Strategy
- Unit tests: mock aiokafka producer/consumer (same pattern as current Redis mock)
- Integration tests: require running Redpanda (same gate as current Redis integration tests)
- E2E: `historical_backfill.py --replay-only --days 1` after all services migrated; verify intelligence_features and signal_ledger populated
- All 1659 existing tests must continue to pass (unit tests only require mock changes)

### Claude's Discretion
- Exact Redpanda container config (single-node, listeners, etc.)
- Topic partition count (default 1 per topic is fine for single-node dev/prod)
- Retention period per topic (7 days default is reasonable)
- Whether to create a `src/core/kafka_utils.py` or rename `stream_utils.py` in-place
- Exact aiokafka producer/consumer wrapper API (keep similar to current redis stream API where possible for minimal diff)

</decisions>

<specifics>
## Specific References

- **Tech stack design doc:** `docs/ideas/tech-stack.md` — all architectural decisions with full reasoning
- **Memory design:** `memory/project_redpanda_migration.md` — 5-plan breakdown
- **Current stream abstraction:**
  - `src/core/stream_utils.py` — 51 lines, consumer group creation/reset
  - `src/core/stream_keys.py` — 136 lines, all stream key construction
- **Current stream consumers/producers:** All 8 service files in `services/`
- **SSE backend:** `src/api/sse.py` — reads from Redis streams for SSE push
- **Docker compose:** `production/docker-compose.yml` — DragonflyDB container to replace
- **Requirements:** `requirements.txt` — redis[hiredis] to remove, aiokafka to add

</specifics>

<deferred>
## Deferred Ideas

- **Schema registry integration** — Redpanda ships a schema registry; wire it for IntelligenceEvent. Deferred: adds complexity, schemas are already enforced via Pydantic in-process.
- **DragonflyDB re-addition for tick SaaS fan-out** — add ONLY when tick streaming SaaS tier is a real product feature (Trigger 1 from tech-stack.md).
- **Redpanda multi-node cluster** — single-node for current scale; upgrade when throughput warrants.
- **Kafka consumer lag monitoring** — add to Prometheus/Grafana after migration is stable.

</deferred>

---

*Phase: 30-redpanda-migration*
*Context gathered: 2026-03-13 via PRD Express Path (memory + tech-stack.md)*
