# Phase 108: Self-Healing Hardening - Pattern Map

**Mapped:** 2026-05-28
**Files analyzed:** 9 files to modify + 1 migration file to create
**Analogs found:** 9 / 10

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `src/core/agent/base.py` | base-class | event-driven | self (add counters to existing `_watchdog_notify()`) | exact |
| `src/observability/metrics.py` | config/registry | — | self (add new instruments at module level) | exact |
| `services/dlq_drain_agent.py` | service/consumer | CRUD + event-driven | self (extend `_drain_message()` + `__init__`) | exact |
| `services/service_auditor_agent.py` | service/monitor | request-response | self (change constant + add OTel counter) | exact |
| `services/intelligence_pipeline_agent.py` | service/compute | event-driven | self (add histogram + CB open logging) | exact |
| `src/api/main.py` | API | request-response | self (add FastAPIInstrumentor + lifespan background task) | exact |
| `src/api/routes/health.py` | route | request-response | self (add `api_health` gauge writes) | exact |
| `production/systemd/*.service` (25 files) | config | — | `indicagent-bar-aggregator.service` | exact |
| `production/migrations/099_dlq_quarantine.sql` | migration | — | `production/migrations/088_dlq_events.sql` | exact |
| `CLAUDE.md` | documentation | — | self (append OTel health contract SOP) | exact |

---

## Pattern Assignments

### `src/core/agent/base.py` — add watchdog OTel counters

**Analog:** self — extend existing `_watchdog_notify()` at lines 349–372

**Existing OTel counter pattern at module level** (lines 52–55):
```python
_base_meter = _otel_metrics.get_meter("indicagent")

AGENT_CRASH_TOTAL = _base_meter.create_counter(
    "agent_crash_total",
    description="Agent crashes (uncaught exceptions) from BaseAgent._run()",
)
```

**New counters to add** — place immediately after `AGENT_CRASH_TOTAL` block, using same `_base_meter`:
```python
WATCHDOG_NOTIFY_TOTAL = _base_meter.create_counter(
    "watchdog_notify_total",
    description="Successful sd_notify WATCHDOG=1 pings per agent",
)
WATCHDOG_NOTIFY_SUPPRESSED_TOTAL = _base_meter.create_counter(
    "watchdog_notify_suppressed_total",
    description="Suppressed watchdog pings (agent alive but idle/stalled) per agent",
)
```

**Critical:** Use `_base_meter` (not `_meter` from `metrics.py`) to avoid duplicate instrument registration. The existing AGENT_CRASH_TOTAL is the authority on this split.

**Existing `_watchdog_notify()` body** (lines 349–372) — add two lines inside the loop:
```python
async def _watchdog_notify(self) -> None:
    socket_path = os.getenv("NOTIFY_SOCKET", "")
    usec = int(os.getenv("WATCHDOG_USEC", "0"))
    if not socket_path or usec <= 0:
        return
    import sdnotify
    notifier = sdnotify.SystemdNotifier()
    interval_s = usec / 2_000_000
    while self.running:
        should_notify = True
        if self.max_idle_seconds > 0 and self._last_message_ts is not None:
            should_notify = (time.monotonic() - self._last_message_ts) < interval_s * 2
        if should_notify:
            notifier.notify("WATCHDOG=1")
            WATCHDOG_NOTIFY_TOTAL.add(1, self._last_msg_ts_attrs)   # NEW
        else:
            WATCHDOG_NOTIFY_SUPPRESSED_TOTAL.add(1, self._last_msg_ts_attrs)  # NEW
        await asyncio.sleep(interval_s)
```

**Label attribute:** `self._last_msg_ts_attrs` = `{"agent_id": name}` — defined at line 120. Matches existing `AGENT_LAST_MESSAGE_TIMESTAMP_SECONDS` label pattern and CLAUDE.md rule.

---

### `src/observability/metrics.py` — add new OTel instruments

**Analog:** self — existing module-level instrument blocks (lines 59–708)

**Instrument creation pattern** (copied from lines 302–309):
```python
SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL = _meter.create_counter(
    "service_auditor_service_restarts_total",
    description="Total service restarts triggered by ServiceAuditorAgent",
)
```

**New instruments to add** — one per new signal, grouped by functional area. Add after the existing `# DLQ metrics` block (line 324):

```python
# ---------------------------------------------------------------------------
# DLQ quarantine metrics (Phase 108)
# ---------------------------------------------------------------------------

DLQ_QUARANTINE_TOTAL = _meter.create_counter(
    "dlq_quarantine_total",
    description="DLQ messages quarantined after DLQ_MAX_RETRIES identical errors in 24h",
)

# ---------------------------------------------------------------------------
# Consumer stall detection (Phase 108)
# ---------------------------------------------------------------------------

CONSUMER_STALL_DETECTED_TOTAL = _meter.create_counter(
    "consumer_stall_detected_total",
    description="Consumer stall events detected by ServiceAuditor before restart",
)

# ---------------------------------------------------------------------------
# Oneshot job completion counters (Phase 108)
# ---------------------------------------------------------------------------

JOB_COMPLETED_TOTAL = _meter.create_counter(
    "job_completed_total",
    description="Oneshot job completions by name and status",
)

# ---------------------------------------------------------------------------
# API health gauge (Phase 108)
# ---------------------------------------------------------------------------

API_HEALTH = _meter.create_gauge(
    "api_health",
    description="API DB connectivity: 1=reachable, 0=unreachable",
)
```

**Note:** `_meter` here (not `_base_meter`) — `_meter = otel_metrics.get_meter("indicagent")` at line 24.

**`create_gauge` analog** — `SHADOW_N_RESOLVED` at line 240:
```python
SHADOW_N_RESOLVED = point_gauge("shadow_n_resolved", "Resolved shadow signals")
```
However, `point_gauge()` wraps `_meter.create_gauge()` — both are correct. Use `_meter.create_gauge()` directly to be consistent with the `API_HEALTH` docstring in RESEARCH.md.

---

### `services/dlq_drain_agent.py` — add quarantine counting

**Analog:** self — extend `__init__()` and `_drain_message()`

**Existing `__init__` pattern** (lines 82–87):
```python
def __init__(self) -> None:
    super().__init__(name="dlq_drain_agent", max_idle_seconds=600)
    self._pool: asyncpg.Pool | None = None
    self._consumer: KafkaConsumerClient | None = None
```

**Add to `__init__`** — after existing assignments:
```python
from collections import defaultdict
from datetime import timedelta
# In-memory rolling 24h occurrence counter keyed by (agent, source_topic, error_type)
# Value: (count, window_start). Evicted when window_start > 48h old on next access.
self._quarantine_counts: dict[tuple, tuple[int, datetime]] = defaultdict(
    lambda: (0, datetime.now(UTC))
)
self._DLQ_MAX_RETRIES: int = 3  # promote to settings.DLQ_MAX_RETRIES if configurable
```

**Existing `_drain_message()` INSERT** (lines 161–173):
```python
async with self._pool.acquire() as conn:
    await conn.execute(
        _INSERT_SQL,
        routed_at,
        msg.agent,
        msg.source_topic,
        dlq_topic,
        msg.error_type,
        msg.error_message,
        msg.payload,
        msg.retry_count,
    )
```

**New `_INSERT_SQL`** — add `quarantined` column (9th param):
```python
_INSERT_SQL: str = """
INSERT INTO dlq_events
    (routed_at, agent, source_topic, dlq_topic, error_type, error_message, payload, retry_count, quarantined)
VALUES
    ($1, $2, $3, $4, $5, $6, $7, $8, $9)
"""
```

**Quarantine logic to add inside `_drain_message()`** — after `DLQPayload.model_validate()`, before the DB write:
```python
from src.observability.metrics import DLQ_QUARANTINE_TOTAL
key = (msg.agent, msg.source_topic, msg.error_type)
count, window_start = self._quarantine_counts[key]
now = datetime.now(UTC)
if now - window_start > timedelta(hours=24):
    count, window_start = 0, now
count += 1
self._quarantine_counts[key] = (count, window_start)
quarantined = count > self._DLQ_MAX_RETRIES
if quarantined:
    DLQ_QUARANTINE_TOTAL.add(1, {"agent": msg.agent, "error_type": msg.error_type})
```

**Then pass `quarantined` as 9th param to `conn.execute()`.**

**Import additions needed** at top of file:
```python
from collections import defaultdict
from datetime import timedelta
```
(`datetime` and `UTC` are already imported at line 23.)

---

### `services/service_auditor_agent.py` — stall threshold + counter

**Analog:** self — change constant at line 47 + add counter call at lines 394–403

**Existing constant** (line 47):
```python
_STALL_THRESHOLD_SECONDS = 360  # 300s in-process watchdog + 60s grace
```
**Change to:**
```python
_STALL_THRESHOLD_SECONDS = 120  # lowered from 360 per Phase 108 D-23
```

**Existing stall restart call** (lines 394–403):
```python
stalled_units = await self._fetch_stalled_agents()
for unit in stalled_units:
    if unit in _ONESHOT_UNITS:
        continue
    self.logger.warning(
        "service_auditor.stall_detected",
        unit=unit,
        threshold_seconds=_STALL_THRESHOLD_SECONDS,
    )
    await self._restart_service_by_unit(unit)
```

**Add counter before the restart call:**
```python
from src.observability.metrics import CONSUMER_STALL_DETECTED_TOTAL
# ...
    self.logger.warning(
        "service_auditor.stall_detected",
        unit=unit,
        threshold_seconds=_STALL_THRESHOLD_SECONDS,
    )
    CONSUMER_STALL_DETECTED_TOTAL.add(1, {"unit": unit})  # NEW
    await self._restart_service_by_unit(unit)
```

**Import:** Add `CONSUMER_STALL_DETECTED_TOTAL` to the existing import at line 40:
```python
from src.observability.metrics import (
    CONSUMER_STALL_DETECTED_TOTAL,
    SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL,
    SERVICE_UP_GAUGE,
)
```

---

### `services/intelligence_pipeline_agent.py` — e2e latency + CB open logging

**Analog:** self — existing histogram pattern at lines 182–200; `_process_bar_compute()` at lines 523–586

**Existing histogram creation pattern** (lines 182–200):
```python
self._i1_latency_ms = self._meter.create_histogram(
    "intelligence_pipeline_i1_latency_ms",
    description="I1 tier execution time in milliseconds",
    unit="ms",
)
self._pipeline_latency = self._meter.create_histogram(
    "intelligence_pipeline_pipeline_latency_ms",
    description="Per-bar pipeline latency in milliseconds",
    unit="ms",
)
```

**New histogram to add in `__init__`** — after existing histogram block:
```python
self._bar_e2e_latency = self._meter.create_histogram(
    "bar_e2e_latency_ms",
    description="End-to-end bar latency from arrival to signal enqueue",
    unit="ms",
)
```

**Existing per-stage latency record pattern** (lines 533–534, 559–560, 583–584):
```python
self._i1_latency_ms.record(i1_duration_ms, {"symbol": bar.symbol, "tf": bar.tf})
self._i7_latency_ms.record(i7_duration_ms, {"symbol": bar.symbol, "tf": bar.tf})
self._pipeline_latency.record(pipeline_latency_ms, {"symbol": bar.symbol, "tf": bar.tf})
```

**`bar_e2e_latency_ms` record call** — add at end of `_process_bar_compute()`, after existing `_pipeline_latency.record()`:
```python
# bar_e2e_latency uses the same t0 from _process_bar_inner; pipeline_latency_ms is already computed
self._bar_e2e_latency.record(pipeline_latency_ms, {"symbol": bar.symbol, "tf": bar.tf})
```
Note: `pipeline_latency_ms = (time.perf_counter() - t0) * 1000` is already computed at line 583 — reuse it. No new `t0` needed.

**CB open state tracking** — in `_setup()`:
```python
self._cb_open_reported: set[str] = set()
```

**CB open detection** — add at end of `_process_bar_compute()`, after `self._bars_processed.add(1)`:
```python
# CB open state detection per D-19: scan post-bar, emit structured log on transition
for plugin_name, cb in self._executor._plugin_circuit_breakers.items():
    if cb.state.value == "open" and plugin_name not in self._cb_open_reported:
        self._cb_open_reported.add(plugin_name)
        self.logger.warning(
            "intelligence_pipeline.cb_open",
            plugin_id=plugin_name,
            failure_count=cb.failures,
        )
    elif cb.state.value != "open" and plugin_name in self._cb_open_reported:
        self._cb_open_reported.discard(plugin_name)
        self.logger.info("intelligence_pipeline.cb_closed", plugin_id=plugin_name)
```

**`_plugin_circuit_breakers` access:** `PluginExecutor` stores this as `self._plugin_circuit_breakers` (line 174 of `src/intelligence/pipeline/executor.py`). Access via `self._executor._plugin_circuit_breakers` directly — no property exists yet. This is a private dict but acceptable for intra-package use. Do NOT add a `@property` on PluginExecutor unless required by a test.

**CB label key is `"plugin"` (not `"plugin_id"`)** — from `src/observability/circuit_breaker.py` line 42-50. The structured log uses `plugin_id=` as a kwarg (not event key) — this is correct structlog usage.

---

### `src/api/main.py` — FastAPI OTel instrumentation

**Analog:** self — extend `lifespan()` and add after `app = FastAPI(...)` definition

**Existing app definition location** — `app = FastAPI(...)` is defined after the `lifespan` function; find by searching for `FastAPI(`.

**Import to add** (follow existing import block pattern):
```python
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
```

**After `app = FastAPI(...)` definition:**
```python
FastAPIInstrumentor().instrument_app(app)
```

**Existing lifespan pattern** (lines 35–50) — shows background task creation using `asyncio.create_task()`. Add a background `api_health` refresh task using the same pattern:
```python
# Inside lifespan(), after dependencies.db_manager.initialize():
from src.observability.metrics import API_HEALTH

async def _refresh_api_health():
    """Update api_health gauge every 30s for Prometheus scrape freshness."""
    while True:
        try:
            conn = await dependencies.db_manager.connection_manager.get_connection()
            await conn.fetchval("SELECT 1")
            await conn.close()
            API_HEALTH.set(1, {"service": "indicagent-api"})
        except Exception:
            API_HEALTH.set(0, {"service": "indicagent-api"})
        await asyncio.sleep(30)

_health_task = asyncio.create_task(_refresh_api_health())
```

Cancel `_health_task` in the `finally` block alongside `_broadcaster_task`.

---

### `src/api/routes/health.py` — `api_health` gauge writes

**Analog:** self — extend `/health/database` endpoint (lines 31–47)

**Existing endpoint pattern** (lines 31–47):
```python
@router.get("/database")
async def database_health(db_manager=Depends(get_db_manager)):
    try:
        conn = await db_manager.connection_manager.get_connection()
        _ = await conn.fetchval("SELECT 1")
        await conn.close()
        return {"status": "healthy", "database": "connected", ...}
    except Exception as e:
        logger.error("Database health check failed", error=str(e))
        raise HTTPException(status_code=503, ...) from e
```

**Add gauge writes to both branches:**
```python
from src.observability.metrics import API_HEALTH

@router.get("/database")
async def database_health(db_manager=Depends(get_db_manager)):
    try:
        conn = await db_manager.connection_manager.get_connection()
        _ = await conn.fetchval("SELECT 1")
        await conn.close()
        API_HEALTH.set(1, {"service": "indicagent-api"})  # NEW
        return {"status": "healthy", ...}
    except Exception as e:
        API_HEALTH.set(0, {"service": "indicagent-api"})  # NEW
        logger.error("Database health check failed", error=str(e))
        raise HTTPException(status_code=503, ...) from e
```

The background task in `main.py` is the primary gauge updater; these writes are supplementary for request-time accuracy.

---

### `production/systemd/*.service` (25 daemon files) — WatchdogSec rollout

**Analog:** `production/systemd/indicagent-bar-aggregator.service` — exact pattern confirmed

**Existing pattern in `indicagent-bar-aggregator.service`** (lines 19–21):
```ini
[Service]
...
WatchdogSec=60
NotifyAccess=main
RestartSec=10
```

**Both lines required together.** Add immediately before `RestartSec=10` in each of the 25 daemon files:
```ini
WatchdogSec=60
NotifyAccess=main
```

**The 25 target files** (from RESEARCH.md verification):
- `indicagent-alerting-agent.service`
- `indicagent-alpha-swarm.service`
- `indicagent-api.service`
- `indicagent-bar-replay.service`
- `indicagent-cross-asset.service`
- `indicagent-ctx-writer.service`
- `indicagent-dlq-drain.service`
- `indicagent-feature-writer.service`
- `indicagent-graduation-compute.service`
- `indicagent-graduation-writer.service`
- `indicagent-ibkr-provider.service`
- `indicagent-intelligence-pipeline.service`
- `indicagent-lifecycle-writer.service`
- `indicagent-lineage-writer.service`
- `indicagent-llm-writer.service`
- `indicagent-macro-compute.service`
- `indicagent-narrative-compute.service`
- `indicagent-provider-merger.service`
- `indicagent-signal-auditor.service`
- `indicagent-signal-metrics-compute.service`
- `indicagent-signal-metrics-writer.service`
- `indicagent-signal-replay.service`
- `indicagent-signal-tracker-compute.service`
- `indicagent-signal-writer.service`
- `indicagent-swarm-ledger-writer.service`

**Skip:** `indicagent-dashboard.service` (Next.js, no sd_notify). Skip all `Type=oneshot` units.

---

### `production/migrations/099_dlq_quarantine.sql` — new migration file

**Analog:** `production/migrations/088_dlq_events.sql`

**Migration 088 pattern** (full file):
```sql
-- Migration 088: dlq_events hypertable
CREATE TABLE IF NOT EXISTS dlq_events (
    ...
    retry_count   INT NOT NULL DEFAULT 0,
    PRIMARY KEY (id, routed_at)
);
SELECT create_hypertable('dlq_events', 'routed_at', if_not_exists => TRUE);
SELECT add_retention_policy('dlq_events', INTERVAL '30 days', if_not_exists => TRUE);
```

**New migration to create:**
```sql
-- Migration 099: dlq_events quarantine column
-- Adds quarantined flag for messages that have exceeded DLQ_MAX_RETRIES identical
-- errors in 24h. Set by DLQDrainAgent in-memory counter logic.

ALTER TABLE dlq_events
    ADD COLUMN IF NOT EXISTS quarantined BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS dlq_events_quarantine_lookup_idx
    ON dlq_events (agent, source_topic, error_type, routed_at DESC);
```

---

### Oneshot scripts — `job_completed_total` counter

**Analog:** `production/scripts/roll_batch.py` — existing OTel counter at module level

**Existing roll_batch OTel pattern** (lines 51–58):
```python
_meter = otel_metrics.get_meter("roll_batch")
_RUNS = _meter.create_counter("roll_batch_runs_total", description="Nightly batch runs")
_ERRORS = _meter.create_counter("roll_batch_errors_total", description="Processing errors")
```

**For oneshot scripts (ml-training, roll-batch, shadow-auditor)** — import shared counter, add two calls at script exit:
```python
from src.observability.metrics import JOB_COMPLETED_TOTAL

# On success (before pool.close()):
JOB_COMPLETED_TOTAL.add(1, {"job": "roll-batch", "status": "success"})

# In except block:
JOB_COMPLETED_TOTAL.add(1, {"job": "roll-batch", "status": "failure"})
```

The `job` label value must match the systemd unit's `%n` suffix (e.g., `roll-batch`, `ml-training`, `shadow-auditor`).

---

## Shared Patterns

### OTel Counter/Gauge Call Convention
**Source:** `src/observability/metrics.py` lines 1–16 (docstring) and any `.add()` / `.set()` call site
**Apply to:** All new OTel instrument call sites
```python
# Counter:        .add(1, {"label_key": value})
# UpDownCounter:  .add(delta, {"label_key": value})
# PointGauge:     .set(value, {"label_key": value})
# Histogram:      .record(value, {"label_key": value})
```

### structlog Event Kwarg Rule
**Source:** CLAUDE.md — "structlog `event` kwarg collision"
**Apply to:** All new `self.logger.warning/info/error()` calls
```python
# WRONG: self.logger.warning("...", event="something")
# RIGHT: self.logger.warning("...", signal="something")
# The positional string IS the event; don't pass event= as kwarg
```

### asyncpg Connection Pattern
**Source:** `services/dlq_drain_agent.py` lines 162–173
**Apply to:** Any new DB writes
```python
async with self._pool.acquire() as conn:
    await conn.execute(_INSERT_SQL, param1, param2, ...)
# Never json.dumps() for JSONB columns — asyncpg accepts dicts directly
```

### UTC Timestamp Rule
**Source:** CLAUDE.md + `services/dlq_drain_agent.py` line 159
**Apply to:** All new `datetime.now()` calls
```python
from datetime import UTC, datetime
now = datetime.now(UTC)  # never datetime.now() or datetime.utcnow()
```

---

## No Analog Found

All files have close analogs in the codebase. No new service files are being created.

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `production/migrations/099_dlq_quarantine.sql` | migration | — | New file, but pattern is identical to `088_dlq_events.sql` — no gap |

---

## HYGIENE-07 Verification Note

RESEARCH.md confirms both named HYGIENE-07 targets (`signal_replay_auditor_agent.py`, `bar_replay_provider_agent.py`) are already on BaseAgent. The planner should include a verification step (`grep -rL "BaseAgent" services/*.py`) at execution time but should NOT plan a migration — the gap is likely already closed.

---

## Metadata

**Analog search scope:** `src/core/agent/`, `src/observability/`, `services/`, `src/api/`, `production/systemd/`, `production/migrations/`
**Files scanned:** 12 source files read directly
**Pattern extraction date:** 2026-05-28
