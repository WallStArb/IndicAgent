# Phase 108: Self-Healing Hardening - Research

**Researched:** 2026-05-28
**Domain:** systemd watchdog, OTel observability, DLQ quarantine, consumer stall detection, FastAPI instrumentation
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Design Principle (applies everywhere)**
- D-01: OTel is the single health measurement layer. Every service emits OTel -> OTel Collector -> Prometheus -> Grafana. No parallel health event publishing to Kafka for monitoring purposes. Kafka `system.health.events` exists for audit trails, not for monitoring decisions.
- D-02: One pane of glass = Grafana. Alerts fire from Grafana on Prometheus metrics. ServiceAuditor reads Prometheus. No ambiguity about which tool is authoritative.
- D-03: Renaissance RED method for every service — Rate (messages/sec), Errors (error rate), Duration (latency histogram).

**OTel Health Contract**
- D-04: Mandatory signals for every daemon inheriting BaseAgent:
  - `agent_last_message_timestamp_seconds` (gauge) — already exists
  - `agent_crash_total` (counter) — already exists
  - `agent_dlq_total` (counter) — already exists
  - `watchdog_notify_total` (counter) — NEW
  - `watchdog_notify_suppressed_total` (counter) — NEW
- D-05: Implemented once in BaseAgent. Every subclass inherits automatically.
- D-06: Oneshot services emit one counter at script end: `job_completed_total{job="<name>", status="success|failure"}`.

**WatchdogSec Rollout**
- D-07: Add `WatchdogSec=60` to 25 daemon unit files missing it (indicagent-api included).
- D-08: Skip `indicagent-dashboard` (Next.js has no sd_notify; WatchdogSec without notify would kill it every 60s).
- D-09: Skip all oneshot unit files (Type=oneshot).
- D-10: `BaseAgent._watchdog_notify()` already correct. Only add two OTel counters (D-04).

**Non-BaseAgent Service Migration**
- D-11: Migrate 3-5 Python services not yet on BaseAgent. HYGIENE-07 targets: `signal_replay_auditor`, `bar_replay_provider`.
- D-12: Audit method: `grep -rL "BaseAgent" services/*.py`.

**FastAPI OTel**
- D-13: Add `opentelemetry-instrumentation-fastapi` to requirements. One `FastAPIInstrumentor().instrument_app(app)` call in `src/api/main.py`.
- D-14: Add one custom health gauge: `api_health` = 1 when DB is reachable, 0 when not.

**End-to-End Latency**
- D-15: Add `bar_e2e_latency_ms` histogram to `intelligence_pipeline_agent`. Labels: `symbol`, `tf`.
- D-16: Existing per-stage histograms already in place. Phase 108 adds end-to-end wrapper only.
- D-17: BPS derived from existing `bars_processed_total` via Grafana rate() — verify counter exists and is labeled.

**Circuit Breaker Alerting**
- D-18: CB state OTel gauge (`AGENT_CIRCUIT_BREAKER_STATE`) already exists from Phase 106. Verify `plugin_id` label.
- D-19: CB state transition detection in `IntelligencePipelineAgent` bar loop: track `_cb_open_reported` set; emit structured log when CB transitions to OPEN. No Kafka publish.

**DLQ Quarantine**
- D-20: No re-delivery loop. Quarantine is DB-level: `DLQDrainAgent` tracks occurrence count per `(agent, source_topic, error_type)` in `dlq_events`. After >= `DLQ_MAX_RETRIES=3` identical errors in 24h, mark `quarantined=true`.
- D-21: Add `dlq_quarantine_total` OTel counter in `DLQDrainAgent`.
- D-22: No new Kafka topic.

**Stuck Consumer Detection**
- D-23: Lower `_STALL_THRESHOLD_SECONDS` from 360 to 120.
- D-24: Add `consumer_stall_detected_total` OTel counter in ServiceAuditor. Labels: `unit`.
- D-25: Existing restart behavior unchanged.

**SOP Documentation**
- D-26: Update CLAUDE.md with OTel health contract.
- D-27: Document Grafana alert SLOs.

### Claude's Discretion
- How to structure the quarantine count query in DLQDrainAgent (in-memory dict vs DB query per message)
- Exact placement of `bar_e2e_latency_ms` measurement start/end in pipeline code
- Whether to use a set or dict for `_cb_open_reported` tracking
- How to add `watchdog_notify_total` and `watchdog_notify_suppressed_total` counters to the existing `_watchdog_notify()` without changing its behavior

### Deferred Ideas (OUT OF SCOPE)
- DB backups (nightly pg_dump)
- DLQ dead.final Kafka topic
- Next.js dashboard OTel
- Distributed tracing across services (Tempo per-span)
</user_constraints>

---

## Summary

Phase 108 is a targeted hardening sprint with well-defined implementation points across five work streams: WatchdogSec rollout (unit file edits only), two new OTel counters in BaseAgent, FastAPI OTel instrumentation, CB open state logging in the pipeline, DLQ quarantine via `dlq_events` table extension, stall threshold reduction in ServiceAuditor, plus a HYGIENE-07 cleanup identifying any remaining non-BaseAgent daemon services.

The codebase audit reveals the scope is well-constrained. All five work streams touch existing files — no new services, no new Kafka topics, no new tables except for the `quarantined` boolean column on `dlq_events`. The most complex piece is the DLQ quarantine logic: it requires an in-memory occurrence counter keyed by `(agent, source_topic, error_type)` with a 24h sliding window, plus a migration adding `quarantined BOOLEAN DEFAULT FALSE` to `dlq_events`.

**Primary recommendation:** Implement in dependency order — BaseAgent OTel counters first (inherited everywhere), then unit files (no code dependency), then DLQ quarantine (isolated to DLQDrainAgent), then ServiceAuditor stall threshold + counter, then CB logging in pipeline, then FastAPI instrumentation, then HYGIENE-07 audit/migration, then CLAUDE.md SOP update.

---

## Standard Stack

### Core (already in requirements.txt)
| Library | Version | Purpose | Status |
|---------|---------|---------|--------|
| `opentelemetry-sdk` | >=1.20.0 | OTel instruments (counter, gauge, histogram) | Already installed |
| `opentelemetry-instrumentation` | >=0.45b0 | Base instrumentation package | Already installed |
| `sdnotify` | any | sd_notify wrapper for `_watchdog_notify()` | Already used |
| `asyncpg` | any | DB queries for DLQ quarantine logic | Already used |

### New Dependencies
| Library | Version | Purpose | Why |
|---------|---------|---------|-----|
| `opentelemetry-instrumentation-fastapi` | >=0.45b0 | Auto-instrument every HTTP endpoint | D-13; one-line wiring, standard OTel |

**Installation:**
```bash
# Add to requirements.txt:
opentelemetry-instrumentation-fastapi>=0.45b0
```

---

## Architecture Patterns

### Confirmed: Existing Infrastructure State (HIGH confidence from code audit)

**WatchdogSec fleet status (verified from production/systemd/):**
- 4 units already have `WatchdogSec=60/120`: `bar-aggregator`, `bar-auditor`, `bar-writer`, `service-auditor`
- 25 daemon (Type=simple) units missing WatchdogSec and NOT dashboard:
  - `alerting-agent`, `alpha-swarm`, `api`, `bar-replay`, `cross-asset`, `ctx-writer`, `dlq-drain`, `feature-writer`, `graduation-compute`, `graduation-writer`, `ibkr-provider`, `intelligence-pipeline`, `lifecycle-writer`, `lineage-writer`, `llm-writer`, `macro-compute`, `narrative-compute`, `provider-merger`, `signal-auditor`, `signal-metrics-compute`, `signal-metrics-writer`, `signal-replay`, `signal-tracker-compute`, `signal-writer`, `swarm-ledger-writer`
- 13 oneshot units (Type=oneshot): skip per D-09
- 1 skip: `dashboard` (Next.js, no sd_notify per D-08)

**HYGIENE-07 status (verified from code):**
- `signal_replay_auditor_agent.py` — `class SignalReplayAuditorAgent(BaseAgent)` — ALREADY ON BaseAgent
- `bar_replay_provider_agent.py` — `class BarReplayProviderAgent(BaseAgent)` — ALREADY ON BaseAgent
- The grep-rL "BaseAgent" false positives were services using `BaseWriterAgent`, `BaseGroupService`, or `BaseProviderAgent` which all inherit from `BaseAgent`
- **True HYGIENE-07 gap is closed.** The audit step in D-12 will confirm no remaining daemons need migration.

**OTel instruments already in `src/observability/metrics.py`:**
- `AGENT_LAST_MESSAGE_TIMESTAMP_SECONDS` — gauge, agent_id label
- `AGENT_DLQ_TOTAL` — counter, agent_id label
- `AGENT_CIRCUIT_BREAKER_STATE` — gauge, agent_id label (this is the setup CB, not plugin CB)
- `DLQ_MESSAGES_TOTAL` — counter, agent/topic/error_type labels
- In `src/observability/circuit_breaker.py`: `intelligence_pipeline_plugin_cb_state` gauge with `plugin` label

**Circuit breaker state gauge labels (verified from circuit_breaker.py):**
- `intelligence_pipeline_plugin_cb_state` gauge in `circuit_breaker.py` uses label `{"plugin": label}`
- D-18 says verify `plugin_id` label — the actual label key is `plugin`, not `plugin_id`
- D-19 CB transition detection: `PluginExecutor._plugin_circuit_breakers` dict is in `executor.py`, not directly accessible from `IntelligencePipelineComputeAgent` — must access via `self._executor._plugin_circuit_breakers`

**`bars_processed_total` exists (verified):**
- `intelligence_pipeline_bars_processed_total` counter defined in `IntelligencePipelineComputeAgent.__init__` at line 178-181
- Labeled with no per-bar symbol/tf labels — Grafana `rate()` gives global BPS

**`dlq_events` table schema (verified from live DB):**
- Columns: `id`, `routed_at`, `agent`, `source_topic`, `dlq_topic`, `error_type`, `error_message`, `payload`, `retry_count`
- No `quarantined` column yet — requires migration
- Has UNIQUE index on `(agent, source_topic, routed_at)` — note: this prevents burst-dedup but the migration comment says "no dedup" (the index was added in production, not from migration 088)

**FastAPI OTel (verified):**
- `opentelemetry-instrumentation-fastapi` is NOT in requirements.txt
- No `FastAPIInstrumentor` call in `src/api/main.py`
- Health router at `/health` prefix (not `/api/health`)
- `api_health` gauge not yet defined in `metrics.py`

### Pattern 1: Adding OTel Counters to `_watchdog_notify()`

**What:** Add `watchdog_notify_total` and `watchdog_notify_suppressed_total` counters inside the existing notify loop without altering behavior.

**Where:** `src/core/agent/base.py` — `_watchdog_notify()` method (currently lines 349-372)

**When to use:** The two branches in the existing `if should_notify:` / else block map perfectly to the two new counters.

```python
# Source: src/core/agent/base.py _watchdog_notify() (verified)
# Add at module level in base.py alongside AGENT_CRASH_TOTAL:
WATCHDOG_NOTIFY_TOTAL = _base_meter.create_counter(
    "watchdog_notify_total",
    description="Successful sd_notify WATCHDOG=1 pings per agent",
)
WATCHDOG_NOTIFY_SUPPRESSED_TOTAL = _base_meter.create_counter(
    "watchdog_notify_suppressed_total",
    description="Suppressed watchdog pings (agent alive but idle/stalled) per agent",
)

# In _watchdog_notify(), after the existing `if should_notify:` block:
if should_notify:
    notifier.notify("WATCHDOG=1")
    WATCHDOG_NOTIFY_TOTAL.add(1, self._last_msg_ts_attrs)   # NEW
else:
    WATCHDOG_NOTIFY_SUPPRESSED_TOTAL.add(1, self._last_msg_ts_attrs)  # NEW
```

**Label key:** Use `self._last_msg_ts_attrs` which is `{"agent_id": name}` — consistent with existing `AGENT_LAST_MESSAGE_TIMESTAMP_SECONDS` label per CLAUDE.md.

### Pattern 2: WatchdogSec Unit File Addition

**What:** Add two lines to each daemon unit's `[Service]` section.

**Where:** `production/systemd/<unit>.service` — 25 files

**Pattern (from existing bar-aggregator.service):**
```ini
[Service]
# ... existing lines ...
WatchdogSec=60
NotifyAccess=main
```

Both lines required: `NotifyAccess=main` permits the main process to write to NOTIFY_SOCKET (uvicorn and Python services use the main pid). Already present in the 4 existing watchdog units — confirms this is the correct pattern.

### Pattern 3: FastAPI OTel Instrumentation

**What:** Auto-instrument every HTTP endpoint with rate/error/latency.

**Where:** `src/api/main.py` — add after `app = FastAPI(...)` definition.

```python
# Add to requirements.txt:
# opentelemetry-instrumentation-fastapi>=0.45b0

# Add import in src/api/main.py:
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

# After app = FastAPI(...):
FastAPIInstrumentor().instrument_app(app)
```

**Custom health gauge (`api_health`):**
```python
# In src/observability/metrics.py:
API_HEALTH = _meter.create_gauge(
    "api_health",
    description="API DB connectivity: 1=reachable, 0=unreachable",
)

# In src/api/routers/health.py, inside the /health/database endpoint:
from src.observability.metrics import API_HEALTH
# On success:
API_HEALTH.set(1, {"service": "indicagent-api"})
# On failure:
API_HEALTH.set(0, {"service": "indicagent-api"})
```

### Pattern 4: DLQ Quarantine in DLQDrainAgent

**What:** Track `(agent, source_topic, error_type)` occurrence counts in a rolling 24h window. After >= `DLQ_MAX_RETRIES=3` occurrences, mark new arrivals as quarantined in DB.

**Migration required:**
```sql
-- New migration file: production/migrations/099_dlq_quarantine.sql
ALTER TABLE dlq_events ADD COLUMN IF NOT EXISTS quarantined BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS dlq_events_quarantine_lookup_idx 
    ON dlq_events (agent, source_topic, error_type, routed_at DESC);
```

**In-memory counter approach (Claude's discretion — recommended):**

Use a `collections.defaultdict` keyed by `(agent, source_topic, error_type)` storing `(count, window_start)`. On each message, evict entries older than 24h and increment. This avoids a DB query per message.

```python
# In DLQDrainAgent.__init__:
from collections import defaultdict
from datetime import timedelta
self._quarantine_counts: dict[tuple, tuple[int, datetime]] = defaultdict(lambda: (0, datetime.now(UTC)))
self._DLQ_MAX_RETRIES = 3  # or from settings

# In _drain_message():
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

**INSERT SQL update (add quarantined column to existing `_INSERT_SQL`):**
```sql
INSERT INTO dlq_events
    (routed_at, agent, source_topic, dlq_topic, error_type, error_message, payload, retry_count, quarantined)
VALUES
    ($1, $2, $3, $4, $5, $6, $7, $8, $9)
```

**New OTel counter in `src/observability/metrics.py`:**
```python
DLQ_QUARANTINE_TOTAL = _meter.create_counter(
    "dlq_quarantine_total",
    description="DLQ messages quarantined after DLQ_MAX_RETRIES identical errors in 24h",
)
```

### Pattern 5: ServiceAuditor Stall Threshold + Counter

**What:** Lower `_STALL_THRESHOLD_SECONDS` from 360 to 120 and add `consumer_stall_detected_total` counter.

**Where:** `services/service_auditor_agent.py`

```python
# Change at line 47:
_STALL_THRESHOLD_SECONDS = 120  # was 360

# In _prometheus_check_loop(), before calling _restart_service_by_unit():
from src.observability.metrics import CONSUMER_STALL_DETECTED_TOTAL
CONSUMER_STALL_DETECTED_TOTAL.add(1, {"unit": unit})
await self._restart_service_by_unit(unit)
```

**New counter in `src/observability/metrics.py`:**
```python
CONSUMER_STALL_DETECTED_TOTAL = _meter.create_counter(
    "consumer_stall_detected_total",
    description="Consumer stall events detected by ServiceAuditor before restart",
)
```

### Pattern 6: CB Open State Logging in Intelligence Pipeline

**What:** Detect plugin circuit breaker transitions to OPEN in the bar processing loop. Emit structured log with plugin_id and failure_count. No Kafka publish.

**Challenge:** `PluginExecutor._plugin_circuit_breakers` dict is not exposed via `IntelligencePipelineComputeAgent`. Options:
1. Add a `@property circuit_breakers` on `PluginExecutor` (clean)
2. Track CB open state via the existing `intelligence_pipeline_plugin_cb_state` gauge transitions (indirect)
3. Add a callback/hook to `CircuitBreaker._on_open_transition()` (invasive)

**Recommended approach (Claude's discretion):** Add a `@property` on `PluginExecutor` that exposes `_plugin_circuit_breakers`. Then in `IntelligencePipelineComputeAgent._process_bar()` or a periodic scan, compare current CB states against a `_cb_open_reported` set.

```python
# In IntelligencePipelineComputeAgent._setup():
self._cb_open_reported: set[str] = set()

# In bar processing (post-bar, checking executor CB state):
for plugin_name, cb in self._executor.circuit_breakers.items():
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

### Pattern 7: `bar_e2e_latency_ms` Histogram

**What:** Measure time from bar arrival to signal written to Kafka output queue.

**Where:** `services/intelligence_pipeline_agent.py` — in the `_process_bar()` method or the equivalent top-level bar handler.

```python
# In __init__:
self._bar_e2e_latency = self._meter.create_histogram(
    "bar_e2e_latency_ms",
    description="End-to-end bar latency from arrival to signal enqueue",
    unit="ms",
)

# In bar processing method:
t0 = time.monotonic()
# ... full I1-I7 processing ...
self._bar_e2e_latency.record(
    (time.monotonic() - t0) * 1000,
    {"symbol": symbol, "tf": tf},
)
```

### Pattern 8: Oneshot Job Completion Counters

**What:** Three lines of Python at the end of oneshot scripts (ml-training, roll-batch, shadow-auditor).

```python
# At script exit in each oneshot service:
from src.observability.metrics import JOB_COMPLETED_TOTAL  # new counter

# On success:
JOB_COMPLETED_TOTAL.add(1, {"job": "ml-training", "status": "success"})
# In except block:
JOB_COMPLETED_TOTAL.add(1, {"job": "ml-training", "status": "failure"})
```

**New counter in `src/observability/metrics.py`:**
```python
JOB_COMPLETED_TOTAL = _meter.create_counter(
    "job_completed_total",
    description="Oneshot job completions by name and status",
)
```

### Anti-Patterns to Avoid

- **Don't add WatchdogSec to oneshot units:** WatchdogSec requires periodic WATCHDOG=1 pings which oneshots never send; they would always be killed before completion.
- **Don't add WatchdogSec to dashboard:** Next.js process does not call sd_notify; the service would be killed every 60s. `Restart=always` is sufficient.
- **Don't query DB per message for quarantine counting:** In-memory defaultdict is O(1) per message and survives the 24h window without DB round-trips.
- **Don't track CB state by querying Prometheus:** The CB objects are in-process; reading them directly is always accurate.
- **Don't use `event=` kwarg in structlog calls:** Use `signal=`, `payload=`, or `data=` per CLAUDE.md.
- **Don't break `_watchdog_notify()` backward compatibility:** When `max_idle_seconds == 0`, `should_notify` is always `True` and `WATCHDOG_NOTIFY_SUPPRESSED_TOTAL` never increments — that is correct.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| FastAPI HTTP instrumentation | Custom middleware for rate/error/latency | `FastAPIInstrumentor().instrument_app(app)` | One call auto-instruments all routes; custom middleware duplicates existing logic |
| sd_notify | Direct Unix socket writes | `sdnotify.SystemdNotifier()` | Already used in `_watchdog_notify()`; handles NOTIFY_SOCKET correctly |
| OTel counter/gauge creation | Any custom wrapper | `_meter.create_counter/gauge/histogram()` from `metrics.py` | All instruments are module-level singletons; duplicate creation crashes the OTel SDK |
| Quarantine persistence | New Kafka topic for quarantined messages | `quarantined BOOLEAN` column on `dlq_events` | Re-delivery loop doesn't exist; DB column is queryable, Kafka topic is write-only |

---

## Common Pitfalls

### Pitfall 1: OTel Duplicate Instrument Registration
**What goes wrong:** Creating the same instrument name twice in the same process causes OTel SDK to raise or silently return a no-op instrument.
**Why it happens:** `base.py` creates instruments at module level; if a subclass also creates an instrument with the same name, registration conflicts.
**How to avoid:** All new instruments go in `src/observability/metrics.py` as module-level constants. `base.py` creates its own private instruments (AGENT_CRASH_TOTAL, etc.) using a private `_base_meter` — these are distinct from `metrics.py` instruments. The two new watchdog counters go in `base.py` alongside `AGENT_CRASH_TOTAL`, not in `metrics.py`, to follow the existing pattern.
**Warning signs:** OTel SDK warns at startup about duplicate instrument names.

### Pitfall 2: WatchdogSec Without NotifyAccess
**What goes wrong:** `WatchdogSec=60` set but process is killed every 60s because sd_notify pings are not reaching systemd.
**Why it happens:** systemd requires `NotifyAccess=main` (or `all`) to accept WATCHDOG=1 from the process.
**How to avoid:** Always add both `WatchdogSec=60` AND `NotifyAccess=main` together. The 4 existing units confirm this pattern.
**Warning signs:** `systemctl status` shows service cycling restarts immediately after startup; `journalctl` shows "Watchdog timeout" errors.

### Pitfall 3: Stall Threshold Racing with In-Process Watchdog
**What goes wrong:** Lowering `_STALL_THRESHOLD_SECONDS` to 120 may cause ServiceAuditor to restart a service that the in-process `_stall_watchdog` (max_idle_seconds) would have restarted moments later via sys.exit(1), resulting in a double-restart.
**Why it happens:** `_stall_watchdog` uses `max_idle_seconds` (varies per agent). The existing 360s threshold was chosen as "300s in-process watchdog + 60s grace."
**How to avoid:** 120s threshold is safe if the agent's `max_idle_seconds > 120s`. Agents with `max_idle_seconds=600` (DLQDrainAgent) or `max_idle_seconds=0` (no in-process watchdog) are safe. Verify no daemon has `max_idle_seconds < 120`.
**Warning signs:** ServiceAuditor logs show a restart of a service that is already restarting.

### Pitfall 4: DLQ Quarantine Window Memory Growth
**What goes wrong:** `_quarantine_counts` dict grows unboundedly if many distinct `(agent, source_topic, error_type)` combinations appear.
**Why it happens:** In-memory dict with no eviction of old keys (only window-start reset on 24h boundary).
**How to avoid:** Add a periodic cleanup that deletes keys whose `window_start` is older than 48h. The fleet has ~15 DLQ topics × ~5 error types = ~75 keys max in practice — not a real concern but document it.
**Warning signs:** Memory growth in DLQDrainAgent process over days.

### Pitfall 5: HYGIENE-07 Over-Migration
**What goes wrong:** Migrating scripts that are NOT daemons (oneshots, utility scripts) to BaseAgent lifecycle — they would not exit cleanly after completing work.
**Why it happens:** grep-rL "BaseAgent" finds files like `shadow_auditor_agent.py`, `ml_training_agent.py` which look like daemon targets but are oneshots.
**How to avoid:** Only migrate files where systemd unit is `Type=simple` (confirmed daemon). Oneshots: `hmm_training`, `shadow_auditor`, `ml_training`, `feature_validation`, `ml_orchestrator`, `ml_data_quality`, `ml_discovery` — all already correctly Type=oneshot, do not migrate.
**Warning signs:** An oneshot service starts, calls `await agent.start()`, completes work, but `_run()` does not exit because the base class loop is waiting for stop_event. systemd timer never fires "exit 0."

### Pitfall 6: `api_health` Gauge Staleness
**What goes wrong:** `api_health` gauge is only updated when `/health/database` is called. If no traffic hits that endpoint, Prometheus sees a stale value.
**Why it happens:** OTel gauges in pull-mode (Prometheus scrape) need to be set before the scrape arrives.
**How to avoid:** Add a background task in the FastAPI lifespan that calls the DB health check every 30s and updates the gauge unconditionally, independent of HTTP traffic.

---

## Code Examples

### Existing `_watchdog_notify()` (verified, base.py lines 349-372)
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
            # ADD: WATCHDOG_NOTIFY_TOTAL.add(1, self._last_msg_ts_attrs)
        # ADD: else: WATCHDOG_NOTIFY_SUPPRESSED_TOTAL.add(1, self._last_msg_ts_attrs)
        await asyncio.sleep(interval_s)
```

### Existing `_fetch_stalled_agents()` (verified, service_auditor_agent.py lines 658-697)
```python
# Uses _STALL_THRESHOLD_SECONDS = 360 (change to 120 per D-23)
# Metric label key confirmed: r["metric"].get("agent_id", "")  -- matches CLAUDE.md
```

### Existing DLQDrainAgent `_drain_message()` (verified, dlq_drain_agent.py lines 134-191)
```python
# No quarantine counting today — plain INSERT into dlq_events
# Add: occurrence counting + quarantined param before conn.execute()
```

### Existing CB state gauge label (verified, circuit_breaker.py lines 42-50)
```python
# Label key is "plugin" (not "plugin_id"):
_cb_state_gauge.set(_STATE_VALUE.get(state.value, 0), {"plugin": label})
```

### Existing `intelligence_pipeline_bars_processed_total` (verified, intelligence_pipeline_agent.py line 179)
```python
self._bars_processed = counter(
    "intelligence_pipeline_bars_processed_total",
    "Bars processed through I1-I7 pipeline",
)
# Labels: none (no symbol/tf per-bar label)
# Grafana: rate(intelligence_pipeline_bars_processed_total[5m]) = global BPS
```

---

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| 4 services with WatchdogSec | 29 services with WatchdogSec (after Phase 108) | systemd auto-restarts any hung Python process |
| No watchdog OTel visibility | `watchdog_notify_suppressed_total` counter | Grafana can alert when a live agent stops processing messages before systemd timeout |
| DLQ is an audit log only | DLQ quarantine on repeated errors | Prevents silent infinite error loops |
| 360s stall detection | 120s stall detection | Faster detection of stuck consumers |
| Manual CB state inspection | Structured logs on CB open transitions | Grafana Loki/OTel alerts on plugin failures |

---

## Open Questions

1. **HYGIENE-07 actual targets**
   - What we know: `signal_replay_auditor_agent.py` and `bar_replay_provider_agent.py` are ALREADY on BaseAgent. The HYGIENE-07 requirement lists them as migration targets.
   - What's unclear: Were these migrated during Phase 107 and the REQUIREMENTS.md not updated? Or is there another list of services?
   - Recommendation: The D-12 audit (`grep -rL "BaseAgent" services/*.py`) at plan execution time will confirm actual state. Treat HYGIENE-07 as a verification step, not a migration step.

2. **`api_health` gauge background update frequency**
   - What we know: D-14 says add the gauge to the `/health/database` endpoint. Without a background task, the gauge only updates on HTTP traffic.
   - What's unclear: Whether a background refresh loop should be added to the API lifespan.
   - Recommendation: Add a 30s background DB health check coroutine in the FastAPI `lifespan` context manager. This ensures Prometheus always scrapes a fresh value.

3. **CB open detection scan frequency**
   - What we know: D-19 says detect when a CB transitions to OPEN in the bar loop.
   - What's unclear: Should the scan happen on every bar or only periodically? The pipeline processes 1m bars (12/hour per symbol) — scanning per bar is cheap.
   - Recommendation: Scan after every bar in `_process_bar_inner()`. Cost is negligible (dict iteration over ~132 plugin entries).

---

## Sources

### Primary (HIGH confidence)
- `src/core/agent/base.py` — complete `_watchdog_notify()` implementation, existing OTel instruments confirmed
- `src/observability/metrics.py` — all existing instrument names and labels confirmed
- `src/core/agent/base_writer.py` — DLQ routing path confirmed
- `services/dlq_drain_agent.py` — DLQDrainAgent implementation, `_INSERT_SQL` structure confirmed
- `services/service_auditor_agent.py` — `_STALL_THRESHOLD_SECONDS=360`, `_fetch_stalled_agents()` implementation confirmed
- `services/intelligence_pipeline_agent.py` — `_build_plugin_circuit_breakers()`, `bars_processed_total` counter confirmed
- `src/observability/circuit_breaker.py` — CB OTel gauge with `{"plugin": label}` confirmed
- Live DB query — `dlq_events` schema confirmed (no `quarantined` column yet)
- `production/systemd/` file audit — 25 daemon services missing WatchdogSec confirmed
- `production/migrations/088_dlq_events.sql` — original dlq_events migration structure confirmed

### Secondary (MEDIUM confidence)
- `opentelemetry-instrumentation-fastapi` — standard OTel package, confirmed absent from requirements.txt; D-13 decision is the authority

---

## Metadata

**Confidence breakdown:**
- WatchdogSec rollout: HIGH — all 43 unit files audited; exact count (25) confirmed
- OTel counter additions: HIGH — existing `_watchdog_notify()` code read and annotated
- DLQ quarantine: HIGH — dlq_events schema confirmed live; migration pattern from 088 is reusable
- Stall threshold change: HIGH — line 47 of service_auditor_agent.py confirmed
- CB open logging: MEDIUM — access path via `self._executor._plugin_circuit_breakers` not yet confirmed (PluginExecutor may not expose it as a property)
- FastAPI OTel: HIGH — confirmed absent, one-call pattern standard
- HYGIENE-07 status: HIGH — both named targets are already on BaseAgent; this is a verification step

**Research date:** 2026-05-28
**Valid until:** 2026-06-28 (stable domain; 30-day validity)
