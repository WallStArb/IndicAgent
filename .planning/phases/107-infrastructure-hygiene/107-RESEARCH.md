# Phase 107: Infrastructure Hygiene - Research

**Researched:** 2026-05-25
**Domain:** PostgreSQL, OpenTelemetry, systemd service orchestration, async Python patterns
**Confidence:** HIGH

## Summary

Phase 107 is a foundational infrastructure hygiene phase that addresses 9 measurable criteria across 3 waves: Service Consistency (30%), Silent Failure Elimination (35%), and Complexity Reduction (35%). The phase targets critical technical debt that would cause invisible regressions during v2.8 AI platform work, including data loss bugs, corrupted metrics, service inconsistencies, and dead code accumulation.

The phase is characterized by its Renaissance engineering principles: zero tolerance for silent failures, instrumentation before optimization, measurement-driven verification (binary SQL success query), and serial wave execution with stabilization gates. This is not speculative work—every criterion addresses a confirmed, active issue documented in the architectural weakness assessment (HF-1 through HF-11, findings #1 through #36).

**Primary recommendation:** Execute strictly in serial wave order (Wave 1 → deploy → verify → stabilize → Wave 2 → deploy → verify → stabilize → Wave 3 → deploy → verify). Do not parallelize waves—debugging concurrent failures across BaseAgent lifecycle, DatabaseManager pools, and writer flush spans would be a rollback nightmare. Each wave builds on the previous: HYGIENE-07/08 must stabilize before HYGIENE-01 can be safely added to the same services.

## User Constraints (from CONTEXT.md)

### Locked Decisions

From `.planning/phases/107-infrastructure-hygiene/107-CONTEXT.md`:

**Wave Execution Strategy:**
- Serial wave execution with verification gates — Wave 1 → deploy → verify → stabilize → Wave 2 → deploy → verify → stabilize → Wave 3 → deploy → verify
- Rationale: Wave 1 changes (BaseAgent lifecycle, DatabaseManager pools) are high-risk. Parallel waves make rollback hell if Wave 2 reveals a Wave 1 bug. Serial waves with checkpoints prioritize debuggability over speed.
- Verification gate per wave: Run the success SQL query from CONTEXT.md; only proceed if it returns TRUE.

**Dependencies:**
- Hard dependencies serialized — HYGIENE-07 (BaseAgent) before HYGIENE-01 (flush spans) on the same services; HYGIENE-08 (DatabaseManager) before HYGIENE-03 (AttributeError fixes) on the same services
- Rationale: Can't add flush spans to services lacking proper teardown. Can't fix data loss bugs in services with broken DB connection handling.
- Within-wave parallelization allowed — HYGIENE-09 (agent ID labels) can run in parallel with HYGIENE-07/08 in Wave 1; Wave 2 criteria (HYGIENE-01/02/03) can run in parallel since they target disjoint services

**Scope:**
- Keep all 9 criteria — do not defer HYGIENE-05 (dead code deletion) to post-v2.8
- Rationale: Dead code deletion is low-risk (git revert is trivial) and high-value (cognitive clarity during complex AI platform changes). Having ShadowRecorder, GuardrailsValidator, and 8 dead Settings fields around means developers constantly second-guess "Is this used?" and follow false trails.
- HYGIENE-09 (agent ID labels) is P1, not P3 — fleet-wide dashboards are broken today due to 50/50 label split; cannot observe system-wide behavior during v2.8 AI platform rollout if Grafana queries can't aggregate across all services

**Automation & Verification:**
- CI gates for static checks — Ruff checks for metric type violations (HYGIENE-02) and label consistency (HYGIENE-09); pre-commit hooks for dead code references (HYGIENE-05)
- Runtime queries with Grafana visibility — systemd timer runs verification queries every 15min; results written to `hygiene_status` table or logged to structlog; Grafana panel displays current state (green/red per criterion)
- Manual spot-checks for automation validation — bootstrap CI verification (HYGIENE-03), hand-calculation of `pnl_r` CI lower bound to validate query logic

### Claude's Discretion

- Wave-to-wave stabilization time — let the system run for 1-2 hours after each wave deployment, monitor Grafana panels for anomalies before proceeding to next wave
- If any wave fails verification, rollback to previous wave's checkpoint before debugging — don't compound failures by pushing forward with broken foundation
- Verification queries can be refined during planning phase, but the binary success/failure nature must be preserved

### Deferred Ideas (OUT OF SCOPE)

- 013-earnings-provider-lane.md — Qualitative lane for earnings data integration. Belongs in future qualitative provider phase, not infrastructure hygiene.
- 014-macro-event-provider-lane.md — Qualitative lane for macro events (FOMC, CPI, NFP). Belongs in future qualitative provider phase.
- 015-qualitative-shadow-evaluation.md — Shadow evaluation gate for qualitative lanes. Belongs with qualitative provider work.
- 017-unified-intelligence-layer-modularization.md — Quant pipeline modularization. Architecture evolution, not infrastructure hygiene.
- 005-bi-analytics-layer-apache-superset.md — BI analytics layer. Tooling addition, not infrastructure debt.
- Kafka topic lifecycle management — Process fix, not Phase 107 infrastructure debt
- Test infrastructure health — Design debt, not Phase 107 scope
- Documentation audit — Automate instead of manual audit
- Health monitor standardization — Too low priority for Phase 107

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| **asyncpg** | 0.29.0+ | PostgreSQL async driver with connection pooling | Project-standard DB layer — all new DB code uses asyncpg, not psycopg2 |
| **OpenTelemetry** | 1.20++ | Distributed tracing and metrics instrumentation | Phase 83 fully migrated from prometheus_client to OTel SDK — single source of truth for metrics |
| **structlog** | 23.0+ | Structured logging with JSON output | Project-standard logger — all services use `structlog.get_logger()` |
| **aiokafka** | 0.9.0+ | Kafka async client (via `KafkaProducerClient` wrapper) | Project-standard Kafka layer — producer/consumer wrappers abstract raw aiokafka |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| **BaseAgent** | (in `src/core/agent/base.py`) | Service lifecycle: SIGTERM handling, stall detection, OTel, metrics | All services except 2 current exceptions (`signal_replay_auditor`, `bar_replay_provider`) |
| **DatabaseManager** | (in `src/core/database_manager.py`) | Connection pooling with JSONB codecs and pool gauges | All DB-writing services except 3 current bypasses (`swarm_ledger_writer`, `bar_replay_provider`, `signal_replay_auditor`) |
| **observed_span** | (in `src/observability/spans.py`) | OTel span wrapper with auto-error recording | Critical path instrumentation — Phase 106 added hot-path spans |
| **BaseWriterAgent** | (in `src/core/agent/base_writer.py`) | Flush/commit/DLQ machinery for persistence services | All `*_writer_agent.py` services |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| BaseAgent lifecycle | Custom SIGTERM/stall detection per service | BaseAgent is debugged and standardized — custom lifecycle diverges from 38/42 services |
| DatabaseManager.create_pool() | Direct asyncpg.create_pool() | DatabaseManager registers JSONB codecs and emits pool gauges — direct bypass loses both |
| OTel SDK histograms | prometheus_client Histogram | OTel is project standard (Phase 83 migration) — prometheus_client fully removed |

**Installation:**
```bash
# All dependencies already in requirements.txt from prior phases
# No new package installations needed for Phase 107
```

## Architecture Patterns

### Recommended Project Structure

```
src/
├── core/
│   ├── agent/
│   │   ├── base.py              # BaseAgent lifecycle (HYGIENE-07 migration target)
│   │   └── base_writer.py       # BaseWriterAgent flush/commit machinery
│   ├── database_manager.py      # create_pool() with JSONB codecs (HYGIENE-08 target)
│   └── service_utils.py         # format_iso_ts() for timestamp serialization
├── observability/
│   ├── metrics.py               # OTel metric definitions (HYGIENE-02 target)
│   ├── otel.py                  # MeterProvider/TracerProvider initialization
│   └── spans.py                 # observed_span wrapper (HYGIENE-01 target)
services/
├── signal_replay_auditor_agent.py   # HYGIENE-07, HYGIENE-08 migration
├── bar_replay_provider_agent.py     # HYGIENE-07, HYGIENE-08 migration
├── swarm_ledger_writer_agent.py     # HYGIENE-03, HYGIENE-08 migration
├── ctx_writer_agent.py              # HYGIENE-01, HYGIENE-03 fixes
├── llm_writer_service.py            # HYGIENE-01, HYGIENE-03 fixes
├── feature_writer_agent.py          # HYGIENE-01, HYGIENE-03 fixes
└── service_auditor_agent.py         # HYGIENE-04 DAG updates
```

### Pattern 1: BaseAgent Lifecycle Migration (HYGIENE-07)

**What:** Migrate 2 services (`signal_replay_auditor_agent`, `bar_replay_provider_agent`) from custom lifecycle to BaseAgent.

**When to use:** Services that define their own `_stop = asyncio.Event()`, `_setup()`, `_teardown()`, `_run()` outside any base class and lack SIGTERM handling, OTel lifecycle, systemd watchdog notifications, stall detection, setup retry, or DLQ routing.

**Example:**

```python
# BEFORE (bar_replay_provider_agent.py):
class BarReplayProviderAgent:
    agent_id = "bar_replay_provider"

    def __init__(self) -> None:
        self._log = structlog.get_logger(self.agent_id)
        self._settings = Settings()
        self._producer: KafkaProducerClient | None = None
        self._pool: asyncpg.Pool | None = None
        self._stop = asyncio.Event()  # Custom stop event
        self._last_replayed_ts: datetime | None = None

    async def _setup(self) -> None:
        self._pool = await create_db_pool(...)  # Direct asyncpg bypass
        self._producer = KafkaProducerClient(...)
        await self._producer.start()

    async def _teardown(self) -> None:
        if self._producer:
            await self._producer.stop()
        if self._pool:
            await self._pool.close()

# AFTER (HYGIENE-07 migration):
from src.core.agent.base import BaseAgent

class BarReplayProviderAgent(BaseAgent):
    """Inherits SIGTERM handling, stall detection, OTel, metrics."""

    def __init__(self) -> None:
        super().__init__(name="bar_replay_provider", max_idle_seconds=300)
        # Now available: self.tracer, self._meter, self.logger, self.settings
        self._producer: KafkaProducerClient | None = None
        self._pool: asyncpg.Pool | None = None
        self._last_replayed_ts: datetime | None = None

    async def _setup(self) -> None:
        # Use DatabaseManager.create_pool() (HYGIENE-08):
        from src.core.database_manager import create_pool as create_db_pool
        self._pool = await create_db_pool(
            self.settings.database_url,
            pool_name="bar_replay_provider",
        )
        self._producer = KafkaProducerClient(
            bootstrap_servers=self.settings.kafka_bootstrap_servers
        )
        await self._producer.start()

    async def _teardown(self) -> None:
        if self._producer:
            await self._producer.stop()
        if self._pool:
            await self._pool.close()

    async def _run(self) -> None:
        while self.running:
            # Main loop here
            if completion_condition:
                self.logger.info("bar_replay_provider.complete")
                sys.exit(0)  # Self-termination on completion

    # Inherited from BaseAgent:
    # - SIGTERM/SIGINT handlers (auto-registered in start())
    # - Stall detection (self.max_idle_seconds > 0 enables watchdog)
    # - OTel MeterProvider/TracerProvider (initialized in start())
    # - Metrics port exposed at :8000/metrics
    # - _send_to_dlq() stub (override _dlq_topic() to enable routing)
```

**Verification:**
```python
# Test that migrated service has BaseAgent capabilities:
assert hasattr(agent, 'tracer')
assert hasattr(agent, '_meter')
assert hasattr(agent, '_stop_event')
assert hasattr(agent, '_record_message_consumed')
```

### Pattern 2: DatabaseManager Pool Standardization (HYGIENE-08)

**What:** Replace 3 services' direct `asyncpg.create_pool()` calls with `DatabaseManager.create_pool()` to ensure JSONB codecs and pool gauges.

**When to use:** Services that bypass `create_pool()` from `database_manager.py` and call `asyncpg.create_pool()` directly.

**Example:**

```python
# BEFORE (signal_replay_auditor_agent.py):
import asyncpg

class SignalReplayAuditorAgent:
    async def _setup(self) -> None:
        self._pool = await asyncpg.create_pool(
            self._settings.database_url,
            pool_name="signal_replay_auditor",
            min_size=1,
            max_size=3,
        )

# AFTER (HYGIENE-08 fix):
from src.core.database_manager import create_pool as create_db_pool

class SignalReplayAuditorAgent(BaseAgent):  # Also inherits from BaseAgent (HYGIENE-07)
    async def _setup(self) -> None:
        self._pool = await create_db_pool(
            self.settings.database_url,  # Use self.settings from BaseAgent
            pool_name="signal_replay_auditor",
            min_size=1,
            max_size=3,
        )
        # Now has JSONB codecs registered and emits DB_POOL_SIZE/DB_POOL_IDLE gauges
```

**Key insight:** Direct `asyncpg.create_pool()` bypasses the `_setup_codecs()` function that registers JSONB encoders/decoders. Without codecs, dict values passed to jsonb columns get double-serialized (`json.dumps(already_a_string)`), producing escaped strings in the database.

### Pattern 3: Writer Flush Span Instrumentation (HYGIENE-01)

**What:** Wrap all `*_writer_agent.py:_flush()` methods in `observed_span("writer.flush")` to make flush failures visible.

**When to use:** All persistence services that batch-write to DB (`ctx_writer`, `llm_writer`, `feature_writer`).

**Example:**

```python
# BEFORE (ctx_writer_agent.py):
class CtxWriterAgent(BaseWriterAgent):
    async def _flush(self) -> None:
        async with self.db_manager.get_connection() as conn:
            async with conn.transaction():
                await conn.executemany(_INSERT_CTX_EVENT_SQL, self._ctx_event_buffer)
                self._ctx_event_buffer.clear()
                # Flush failures invisible to OTel

# AFTER (HYGIENE-01 instrumentation):
from src.observability.spans import observed_span

class CtxWriterAgent(BaseWriterAgent):
    async def _flush(self) -> None:
        async with observed_span("writer.flush", tracer=self.tracer) as span:
            async with self.db_manager.get_connection() as conn:
                async with conn.transaction():
                    await conn.executemany(_INSERT_CTX_EVENT_SQL, self._ctx_event_buffer)
                    self._ctx_event_buffer.clear()
            # Flush failures now recorded in span with ERROR status
            # Span includes attributes: agent_id, batch_size, flush_ms
```

**Verification:**
```python
# Check span exists in traces:
# curl -s http://localhost:9090/api/v1/query?query=rate(span_duration_seconds{span_name="writer.flush"}[5m])
```

### Anti-Patterns to Avoid

- **Custom lifecycle instead of BaseAgent:** Reinventing SIGTERM handling, stall detection, and OTel initialization per service. BaseAgent already provides this — use it.
- **Direct asyncpg.create_pool():** Bypasses JSONB codecs and pool gauges. Always use `create_pool()` from `database_manager.py`.
- **Uninstrumented flush methods:** Writer `_flush()` methods without span coverage. Flush failures are silent without spans.
- **Wrong metric instrument types:** Using `up_down_counter` for absolute values (shadow metrics) or latency (needs histogram). Use `create_gauge()` for absolute values, `create_histogram()` for latency.
- **Metric label inconsistency:** Mixing `"agent"` and `"agent_id"` label keys. Standardize on `"agent_id"` everywhere.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Service lifecycle (SIGTERM, stall detection, OTel) | Custom `_stop` event, signal handlers, manual tracer init | `BaseAgent` from `src/core/agent/base.py` | BaseAgent is debugged across 38/42 services — custom lifecycle diverges from project standard |
| Connection pooling with JSONB codecs | Direct `asyncpg.create_pool()` with manual codec setup | `create_pool()` from `src/core/database_manager.py` | DatabaseManager registers JSONB codecs and emits pool gauges — direct bypass loses both |
| OTel span error recording | Manual `try/except` with `span.record_exception()` | `observed_span()` from `src/observability/spans.py` | Wrapper auto-records ERROR status and exception on raise — eliminates boilerplate |
| Metric label management | Per-service label dict declarations | `_batch_latency_attrs = {"agent_id": self.name.lower()}` pattern from BaseWriterAgent | Centralizes label key — prevents `"agent"` vs `"agent_id"` split |
| DB connection retry | Custom retry loop with backoff | `BaseAgent._setup_with_retry()` | Already implements exponential backoff with jitter and circuit breaker |

**Key insight:** Phase 107 is about adopting existing patterns, not building new ones. The project has solid infrastructure (BaseAgent, DatabaseManager, observed_span) — the problem is inconsistent adoption across services.

## Common Pitfalls

### Pitfall 1: Forgetting `super()._teardown()` When Overriding

**What goes wrong:** `CtxWriterAgent._teardown()` omits `super()._teardown()`. The final flush guard in `BaseWriterAgent._teardown()` is never called. Any buffered records at shutdown time are lost with no warning.

**Why it happens:** Python doesn't automatically call parent class `_teardown()` when overriding. Developers focus on service-specific teardown (closing DB, producer) and forget the base class logic.

**How to avoid:** Always call `await super()._teardown()` as the first line in any overridden `_teardown()` method. Document this in code comments.

**Warning signs:** Writer services losing data on graceful shutdown. `BaseWriterAgent._teardown()` has a final flush guard that's easy to miss.

### Pitfall 2: OTel Counter `.inc()` Method Doesn't Exist

**What goes wrong:** `CtxWriterAgent` calls `self._some_counter.inc(len(batch))`. OTel counter objects expose `.add()`, not `.inc()`. This raises `AttributeError` inside `_flush()`, propagating to `_do_flush()`, which catches it and increments `_flush_errors_total` without clearing buffers. Buffers grow until overflow.

**Why it happens:** Muscle memory from prometheus_client (which used `.inc()`). Phase 83 migrated to OTel SDK but call sites weren't all updated.

**How to avoid:** Always use `.add(delta, attrs)` for OTel counters and up-down counters. Never use `.inc()`.

**Warning signs:** Buffer overflow warnings in logs. `_flush_errors_total` incrementing but no actual DB error logged.

### Pitfall 3: Wrong Metric Instrument Type

**What goes wrong:** Shadow metrics (`SHADOW_WIN_RATE`, `SHADOW_N_RESOLVED `) are `create_up_down_counter`, but each audit cycle adds the current absolute value. After 10 cycles, a plugin with `n=50` reads `500`. Shadow dashboard is permanently incorrect.

**Why it happens:** OTel has 4 instrument types (Counter, UpDownCounter, Gauge, Histogram). Using the wrong type produces garbage data.

**How to avoid:**
- **Counter:** Monotonically increasing count (never decreases). Use `.add(1, attrs)`.
- **UpDownCounter:** Gauge that goes up and down. Use `.add(delta, attrs)`.
- **Gauge:** Point-in-time absolute value. Use `.set(value, attrs)`.
- **Histogram:** Distribution of values (latency, batch size). Use `.record(value, attrs)`.

**Rule of thumb:** If it's a current value (not a delta), use `create_gauge()`. If it's a rate/delta, use `create_counter()` or `create_up_down_counter()`. If you need percentiles (p50, p95, p99), use `create_histogram()`.

**Warning signs:** Metrics that grow forever when they shouldn't. Dashboard values that look wrong (shadow win rate > 1.0, latency in millions).

### Pitfall 4: Metric Label Key Inconsistency

**What goes wrong:** `BaseAgent` uses `{"agent": name}` for crash metrics. `BaseWriterAgent` uses `{"agent_id": ...}` for persistence metrics. `service_auditor_agent` queries `agent_id`. Cross-agent fleet-wide dashboards are impossible to build.

**Why it happens:** No centralized convention. Each developer picks a label key name.

**How to avoid:** Standardize on `"agent_id"` everywhere. Move label dict initialization into base class constructors so subclasses don't declare their own.

**Warning signs:** Grafana queries that manually union multiple label keys. Dashboard panels showing partial data.

### Pitfall 5: DatabaseManager Ghost-Run Mode

**What goes wrong:** `FeatureWriterAgent._connect_database()` catches all exceptions and sets `self.db_manager = None`. The service continues consuming Kafka and filling its buffer. After `MAX_BUFFER_SIZE=10,000` rows, oldest rows drop silently. Zero rows are written to `intelligence_features`.

**Why it happens:** Defensive programming — "if DB connection fails, keep running". But for a writer service, running without a DB connection is worse than crashing.

**How to avoid:** Writer services should raise in `_connect_database()` so systemd restarts the service. Add a `*_db_connected` OTel gauge to track connection state.

**Warning signs:** Service logs show no errors. Metrics show consumer lag at 0. But DB queries return no recent rows.

### Pitfall 6: Shadow Signals Bypassing Live Suppression

**What goes wrong:** Shadow plugins marked `is_shadow=TRUE` in `shadow_registry` can be selected as the winner signal and published to `topic_signals_aggregated`. Lifecycle tracker activates them as real trades. Shadow mode provides zero actual trade suppression.

**Why it happens:** Two bugs: (1) `is_shadow` is never stamped on signal dicts — post-processing loop omits the field. (2) `winner_selector.py` has no shadow-eligibility filter.

**How to avoid:** In the post-processing loop add `sig["is_shadow"] = self._is_shadow(task.plugin_name, cache_snapshot.shadow_cache)`. Before `select_winner()`, filter: `eligible_ranked = [s for s in ranked if not cache_snapshot.shadow_cache.get(s.get("setup_plugin",""), False)]`.

**Warning signs:** Shadow signals appearing in `signal_ledger` with `is_shadow=FALSE`. Shadow plugin IDs in aggregated signals.

## Code Examples

### Example 1: BaseAgent Migration (HYGIENE-07)

```python
# Source: src/core/agent/base.py (lines 1-517)

# BaseAgent provides:
# - SIGTERM/SIGINT handling via _register_signal_handlers()
# - Stall detection via _stall_watchdog() (when max_idle_seconds > 0)
# - OTel MeterProvider + TracerProvider via init_otel_providers()
# - Metrics port at :8000/metrics
# - _send_to_dlq() stub (override _dlq_topic() to enable routing)
# - _setup_with_retry() with exponential backoff

# Migration pattern for signal_replay_auditor_agent.py:

# BEFORE:
class SignalReplayAuditorAgent:
    agent_id = "signal_replay_auditor"

    def __init__(self) -> None:
        self._log = structlog.get_logger(self.agent_id)
        self._settings = Settings()
        self._producer: KafkaProducerClient | None = None
        self._pool: asyncpg.Pool | None = None
        self._stop = asyncio.Event()  # Custom stop event

    async def _setup(self) -> None:
        self._pool = await asyncpg.create_pool(...)  # Direct bypass
        self._producer = KafkaProducerClient(...)
        await self._producer.start()

# AFTER:
from src.core.agent.base import BaseAgent
from src.core.database_manager import create_pool as create_db_pool

class SignalReplayAuditorAgent(BaseAgent):
    """Inherits full BaseAgent lifecycle."""

    def __init__(self) -> None:
        super().__init__(
            name="signal_replay_auditor",
            max_idle_seconds=600,  # Enable stall detection
        )
        # Now available: self.tracer, self._meter, self.logger, self.settings
        self._producer: KafkaProducerClient | None = None
        self._pool: asyncpg.Pool | None = None

    async def _setup(self) -> None:
        # Use DatabaseManager.create_pool() (HYGIENE-08):
        self._pool = await create_db_pool(
            self.settings.database_url,
            pool_name="signal_replay_auditor",
            min_size=1,
            max_size=3,
        )
        self._producer = KafkaProducerClient(
            bootstrap_servers=self.settings.kafka_bootstrap_servers
        )
        await self._producer.start()
        self._log.info("signal_replay_auditor.started")

    async def _run(self) -> None:
        while self.running:
            await self._run_audit_cycle()
            await asyncio.sleep(REPLAY_INTERVAL_SECONDS)

    async def _teardown(self) -> None:
        if self._producer:
            await self._producer.stop()
        if self._pool:
            await self._pool.close()

# Now inherits:
# - SIGTERM handling (auto-registered in start())
# - Stall detection (max_idle_seconds > 0 enables watchdog)
# - OTel instrumentation (self.tracer, self._meter)
# - Metrics exposure (:8000/metrics)
# - DLQ routing (_send_to_dlq() stub)
```

### Example 2: Writer Flush Span Instrumentation (HYGIENE-01)

```python
# Source: src/observability/spans.py (lines 1-33)

from src.observability.spans import observed_span, ATTR_BATCH_SIZE, ATTR_FLUSH_MS

# Instrument ctx_writer_agent.py _flush() method:

class CtxWriterAgent(BaseWriterAgent):
    async def _flush(self) -> None:
        # Wrap entire flush in observed_span for visibility
        async with observed_span("writer.flush", tracer=self.tracer) as span:
            flush_start = time.monotonic()

            # Flush CTX events buffer
            if self._ctx_event_buffer:
                async with self.db_manager.get_connection() as conn:
                    async with conn.transaction():
                        await conn.executemany(
                            _INSERT_CTX_EVENT_SQL,
                            self._ctx_event_buffer,
                        )
                        span.set_attribute(ATTR_BATCH_SIZE, len(self._ctx_event_buffer))
                        self._ctx_event_buffer.clear()

            # Flush CTX snapshots buffer
            if self._ctx_snapshot_buffer:
                async with self.db_manager.get_connection() as conn:
                    async with conn.transaction():
                        await conn.executemany(
                            _UPSERT_CTX_SNAPSHOT_SQL,
                            self._ctx_snapshot_buffer,
                        )
                        span.set_attribute("snapshot_batch_size", len(self._ctx_snapshot_buffer))
                        self._ctx_snapshot_buffer.clear()

            flush_ms = (time.monotonic() - flush_start) * 1000
            span.set_attribute(ATTR_FLUSH_MS, flush_ms)

        # If flush raises, observed_span auto-sets ERROR status and records exception
        # Span appears in traces with agent_id, batch_size, flush_ms attributes
```

### Example 3: Metric Type Fixes (HYGIENE-02)

```python
# Source: src/observability/metrics.py (lines 244-260)

# BEFORE (wrong instrument type):
SHADOW_WIN_RATE = _meter.create_up_down_counter(
    "shadow_win_rate",
    description="Shadow plugin win rate",
)
# Usage: SHADOW_WIN_RATE.add(0.65, {"plugin": "rsi"})  # WRONG — accumulates forever

# AFTER (correct instrument type):
SHADOW_WIN_RATE = _meter.create_gauge(
    "shadow_win_rate",
    description="Shadow plugin win rate",
)
# Usage: SHADOW_WIN_RATE.set(0.65, {"plugin": "rsi"})  # CORRECT — absolute value

# Apply to all 5 shadow metrics:
SHADOW_N_RESOLVED = _meter.create_gauge("shadow_n_resolved", "Resolved shadow signals")
SHADOW_EV_R = _meter.create_gauge("shadow_ev_r", "Shadow plugin E[PnL_R]")
SHADOW_EV_CI_LOWER = _meter.create_gauge("shadow_ev_ci_lower", "Shadow 95% CI lower bound")
SHADOW_DAYS_TO_GATE = _meter.create_gauge("shadow_days_to_gate", "Estimated days to N=100")

# Usage in shadow_auditor_agent.py:
SHADOW_WIN_RATE.set(win_rate, {"plugin": plugin_id})
SHADOW_N_RESOLVED.set(n_resolved, {"plugin": plugin_id})
SHADOW_EV_R.set(ev_r, {"plugin": plugin_id})
SHADOW_EV_CI_LOWER.set(ci_lower, {"plugin": plugin_id})
SHADOW_DAYS_TO_GATE.set(days_to_gate, {"plugin": plugin_id})
```

### Example 4: DatabaseManager Pool Standardization (HYGIENE-08)

```python
# Source: src/core/database_manager.py (lines 19-30)

async def _setup_codecs(conn):
    """Setup JSONB codecs for new connections (init= callback for pool)."""
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")
    await conn.set_type_codec("json", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")

async def create_pool(database_url: str, pool_name: str = "default", **kwargs) -> asyncpg.Pool:
    """Create an asyncpg pool with JSONB codecs and pool size gauges."""
    pool = await asyncpg.create_pool(database_url, init=_setup_codecs, **kwargs)
    DB_POOL_SIZE.add(pool.get_size(), {"pool": pool_name})
    DB_POOL_IDLE.add(pool.get_idle_size(), {"pool": pool_name})
    return pool

# Apply to swarm_ledger_writer_agent.py:

# BEFORE:
import asyncpg

class SwarmLedgerWriterAgent:
    async def _setup(self) -> None:
        self._pool = await asyncpg.create_pool(
            self._settings.database_url,
            min_size=2,
            max_size=10,
        )

# AFTER:
from src.core.database_manager import create_pool as create_db_pool

class SwarmLedgerWriterAgent(BaseAgent):  # Also migrate to BaseAgent (HYGIENE-07)
    async def _setup(self) -> None:
        self._pool = await create_db_pool(
            self.settings.database_url,
            pool_name="swarm_ledger_writer",
            min_size=2,
            max_size=10,
        )
        # Now has JSONB codecs registered and emits DB_POOL_SIZE/DB_POOL_IDLE gauges
```

### Example 5: Fixing AttributeError Bugs (HYGIENE-03)

```python
# Source: docs/ideas/architectural-weakness-assessment.md (HF-2, HF-3, HF-11)

# Fix 1: CtxWriterAgent .inc() AttributeError (HF-2)
# File: services/ctx_writer_agent.py:343,351

# BEFORE:
async def _flush(self) -> None:
    CTX_EVENTS_WRITTEN_TOTAL.inc(len(self._ctx_event_buffer))  # WRONG — AttributeError
    CTX_SNAPSHOTS_WRITTEN_TOTAL.inc(len(self._ctx_snapshot_buffer))  # WRONG — AttributeError

# AFTER:
async def _flush(self) -> None:
    CTX_EVENTS_WRITTEN_TOTAL.add(len(self._ctx_event_buffer), self._batch_latency_attrs)
    CTX_SNAPSHOTS_WRITTEN_TOTAL.add(len(self._ctx_snapshot_buffer), self._batch_latency_attrs)

# Fix 2: LLMWriterService _pool AttributeError (HF-3)
# File: services/llm_writer_service.py:695

# BEFORE:
async def _process_calls_message(self, msg: dict) -> None:
    async with self._pool.acquire() as conn:  # WRONG — self._pool never initialized
        await conn.execute(_UPDATE_PARSE_SQL, call_id, parse_success)

# AFTER:
async def _process_calls_message(self, msg: dict) -> None:
    await self.db_manager.execute_command(_UPDATE_PARSE_SQL, call_id, parse_success)

# Fix 3: CtxWriterAgent missing super()._teardown() (HF-11)
# File: services/ctx_writer_agent.py:376-387

# BEFORE:
async def _teardown(self) -> None:
    if self._producer:
        await self._producer.stop()
    # Missing super()._teardown() — final flush never runs

# AFTER:
async def _teardown(self) -> None:
    await super()._teardown()  # MUST be first — calls BaseWriterAgent._teardown()
    if self._producer:
        await self._producer.stop()
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| prometheus_client for metrics | OpenTelemetry SDK | Phase 83 (2026-05) | All metrics now OTel-native — direct SDK calls, no prometheus_client wrapper |
| Manual signal handlers | BaseAgent lifecycle | Phase 84 (2026-05) | SIGTERM handling, stall detection, OTel initialization centralized |
| Custom DB pool setup | DatabaseManager.create_pool() | Phase 104 (2026-05) | JSONB codecs and pool gauges standardized across most services |
| Service-specifc retry loops | BaseAgent._setup_with_retry() | Phase 106 (2026-05-25) | Exponential backoff with jitter and circuit breaker centralized |

**Deprecated/outdated:**
- **prometheus_client:** Fully removed in Phase 83. Do not use `from prometheus_client import Counter/Gauge/Histogram`. Use OTel SDK.
- **ShadowRecorder:** Zero production instantiations. Dead code scheduled for deletion in HYGIENE-05.
- **GuardrailsValidator:** Zero schemas registered. Dead branch in chain.py. v2.8 will replace with Guardrails AI. Delete in HYGIENE-05.
- **8 dead Settings fields:** `SWARM_QUEUE_TIMEOUT_MS`, `LLM_RATE_LIMIT_RPM`, `LLM_RATE_LIMIT_TPM`, `SHADOW_CORRELATION_THRESHOLD`, `SHADOW_MIN_SAMPLES`, `LANGFUSE_HOST`, `MLFLOW_TRACKING_URI`, plus one orphan field. Delete in HYGIENE-05.

## Open Questions

1. **Wave stabilization time**
   - What we know: Serial wave execution with verification gates is required. Each wave must deploy → verify → stabilize before next wave.
   - What's unclear: How long to stabilize after each wave deployment? 1 hour? 2 hours? Monitor Grafana for anomalies?
   - Recommendation: Let the system run for 1-2 hours after each wave deployment, monitoring Grafana panels for metric spikes, consumer lag, error rates. If all green, proceed to next wave. If any anomaly appears, rollback to previous wave checkpoint and investigate.

2. **Verification query refinement**
   - What we know: Binary SQL success query must return TRUE for all 9 criteria to pass Phase 107.
   - What's unclear: Can the verification queries be refined during planning, or must they stay fixed from CONTEXT.md?
   - Recommendation: Queries can be refined during planning phase to add edge case handling, but the binary success/failure nature must be preserved. No "partial credit" — each criterion is either passing or failing.

3. **CI gate implementation for static checks**
   - What we know: HYGIENE-02 (metric type violations) and HYGIENE-09 (label consistency) need CI gates. HYGIENE-05 (dead code) needs pre-commit hooks.
   - What's unclear: What specific Ruff rules or custom linters to write? How to integrate with CI pipeline?
   - Recommendation: Write custom Ruff rules for metric type violations (detect `.inc()` calls, detect wrong instrument type usage). Write pre-commit hook for dead code (check imports of deleted modules). Add to `.github/workflows/ci.yml` to block PR merge if violations detected.

4. **Runtime verification automation**
   - What we know: systemd timer should run verification queries every 15min. Results should be written to `hygiene_status` table or logged to structlog. Grafana panel should display current state.
   - What's unclear: Should this be a new dedicated service, or add to existing `service_auditor_agent`? Table schema for `hygiene_status`?
   - Recommendation: Add to existing `service_auditor_agent` (already monitors service health). Create `hygiene_status` table with columns `criterion_id`, `status`, `last_checked`, `details`. Grafana panel queries this table and shows green/red per criterion.

## Sources

### Primary (HIGH confidence)

- **architectural-weakness-assessment.md** — Complete inventory of 36 findings with file locations and line numbers. Source of truth for all 9 HYGIENE criteria. (2026-05-23)
- **BaseAgent source code** (`src/core/agent/base.py`) — Lifecycle contract, SIGTERM handling, stall detection, OTel initialization.
- **DatabaseManager source code** (`src/core/database_manager.py`) — `create_pool()` with JSONB codecs and pool gauges.
- **Metrics module** (`src/observability/metrics.py`) — OTel metric definitions, instrument types, label conventions.
- **observed_span wrapper** (`src/observability/spans.py`) — OTel span context manager with auto-error recording.
- **service_auditor_agent.py** — DAG order registry, `_DAG_ORDER`, `_LAG_THRESHOLDS`, `_AGENT_ID_TO_UNIT` mappings.
- **Phase 106 deliverables** — Foundation Hardening completed 2026-05-25. Provides patterns to follow for BaseAgent adoption, DatabaseManager pools, hot-path spans.

### Secondary (MEDIUM confidence)

- **CONTEXT.md** (`.planning/phases/107-infrastructure-hygiene/107-CONTEXT.md`) — User decisions on wave execution strategy, dependencies, scope, automation.
- **REQUIREMENTS.md** (`.planning/REQUIREMENTS.md`) — HYGIENE-01 through HYGIENE-04 requirement text.
- **STATE.md** (`.planning/STATE.md`) — Project state, v2.8 roadmap, evidence gates.
- **CLAUDE.md** — Project conventions, naming rules, gotchas, infrastructure reference.

### Tertiary (LOW confidence)

- None. All findings are verified against source code or architectural assessment. No web-search-only claims.

## Metadata

**Confidence breakdown:**
- Standard stack: **HIGH** — All libraries and patterns verified against active codebase. No speculative additions.
- Architecture: **HIGH** — BaseAgent, DatabaseManager, observed_span patterns verified against source code. Migration examples tested against existing service patterns.
- Pitfalls: **HIGH** — All 6 pitfalls documented with specific file locations and line numbers from architectural weakness assessment. Fixes are straightforward.
- Wave execution strategy: **HIGH** — Serial waves with verification gates is explicit user decision in CONTEXT.md.
- Verification queries: **MEDIUM** — SQL queries can be refined during planning, but binary success/failure approach is locked.

**Research date:** 2026-05-25
**Valid until:** 30 days (stable infrastructure domain — no fast-moving dependencies)
