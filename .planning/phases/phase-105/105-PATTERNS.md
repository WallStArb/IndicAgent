# Phase 105: Architecture Hotfix Sprint - Pattern Map

**Mapped:** 2026-05-23
**Files analyzed:** 10 modified files (no new files created)
**Analogs found:** 10 / 10

---

## File Classification

| Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `services/ctx_writer_agent.py` | writer/service | event-driven flush | `services/feature_writer_agent.py` | exact |
| `services/llm_writer_service.py` | writer/service | request-response + batch | `services/feature_writer_agent.py` | role-match |
| `services/feature_writer_agent.py` | writer/service | CRUD batch | `services/ctx_writer_agent.py` | exact |
| `services/bar_writer_agent.py` | writer/service | CRUD batch | `services/feature_writer_agent.py` | exact |
| `services/swarm_ledger_writer_agent.py` | writer/service | event-driven | `services/feature_writer_agent.py` | role-match |
| `src/intelligence/pipeline/executor.py` | pipeline/compute | transform | `src/intelligence/pipeline/signal_processor.py` | role-match |
| `src/intelligence/pipeline/signal_processor.py` | pipeline/compute | transform | `src/intelligence/pipeline/executor.py` | exact |
| `services/shadow_auditor_agent.py` | auditor/service | CRUD + metrics | `services/bar_auditor_agent.py` | role-match |
| `src/observability/metrics.py` | config/registry | N/A | self (inline patterns) | exact |
| `services/intelligence_pipeline_agent.py` | compute/service | event-driven | `services/contract_metadata_writer_agent.py` | partial |

---

## Pattern Assignments

### `services/ctx_writer_agent.py` (HF-2 + HF-11)

**Analog:** `services/feature_writer_agent.py` (lines 467-470), `services/ctx_writer_agent.py` (lines 330-387)

**Bug locations in current source:**
- Line 343: `self._events_written.inc(len(event_batch))` — `.inc()` does not exist on OTel counters
- Line 351: `self._snapshots_written.inc(len(snapshot_batch))` — same
- Lines 376-387: `_teardown()` missing `await super()._teardown()` as first call

**OTel counter `.add()` pattern** (from `services/feature_writer_agent.py` line 470, `services/ctx_writer_agent.py` line 166):
```python
# CORRECT — OTel counter call site
self._events_consumed.add(1)                   # single increment
self._events_written.add(len(event_batch))     # batch increment
```

**`_teardown()` with `super()` pattern** (from `services/bar_writer_agent.py` lines 272-277):
```python
async def _teardown(self) -> None:
    await super()._teardown()     # FIRST — runs BaseWriterAgent final flush
    if self._kafka_consumer is not None:
        await self._kafka_consumer.stop()
    if self._db_pool is not None:
        await self._db_pool.close()
```

**Fix for HF-2:**
```python
# Line 343 — change:
self._events_written.inc(len(event_batch))
# to:
self._events_written.add(len(event_batch))

# Line 351 — change:
self._snapshots_written.inc(len(snapshot_batch))
# to:
self._snapshots_written.add(len(snapshot_batch))
```

**Fix for HF-11:**
```python
# Add as FIRST line of _teardown() at line 376:
async def _teardown(self) -> None:
    await super()._teardown()   # runs BaseWriterAgent final flush first
    if self._event_buffer or self._snapshot_buffer:
        ...  # existing custom flush logic remains
```

**Caution:** Before adding `super()._teardown()`, verify `BaseWriterAgent._teardown()` at `src/core/agent/base_writer.py` does not also call `_flush_batch()` in a way that duplicates the custom `_flush()` call below it. If `BaseWriterAgent._teardown()` calls `_flush_batch()` which is a no-op stub (line 360-365 confirms this), the double-flush risk is zero.

---

### `services/llm_writer_service.py` (HF-3 + HF-6 + HF-10)

**Analog:** `services/feature_writer_agent.py` (db_manager pattern), `src/core/agent/base.py` (`_last_message_ts` and `_record_message_consumed()`)

**Bug locations in current source:**
- Line 695: `async with self._pool.acquire() as conn:` — `self._pool` never initialized; only `self.db_manager` exists
- Line 822: `self.i8_writes_total.inc(len(batch))` — `.inc()` does not exist on OTel counter
- Lines 946, 948: `self._last_msg_ts` — undefined attribute; correct name is `self._last_message_ts`
- `_process_loop()` does not call `self._record_message_consumed()` after consuming each message

**`db_manager.execute_command` pattern** (from `services/feature_writer_agent.py` and `src/core/database_manager.py`):
```python
# CORRECT — use db_manager, not self._pool.acquire()
# HF-3 fix at line 695:
await self.db_manager.execute_command(_UPDATE_PARSE_SQL, call_id, parse_success)
# Replaces the broken:
# async with self._pool.acquire() as conn:
#     await conn.execute(_UPDATE_PARSE_SQL, call_id, parse_success)
```

**OTel counter `.add()` fix for HF-3 line 822:**
```python
# Change:
self.i8_writes_total.inc(len(batch))
# to:
self.i8_writes_total.add(len(batch))
```

**Stall watchdog attribute fix (HF-6)** — BaseAgent defines `self._last_message_ts` (with `_message_`). Source: `src/core/agent/base.py`. Replace both references:
```python
# Lines 946, 948 — change self._last_msg_ts to self._last_message_ts:
if self._last_message_ts is None:
    continue
idle_secs = time.monotonic() - self._last_message_ts
```

**`_record_message_consumed()` wiring pattern** (from `services/feature_writer_agent.py` lines 467-470):
```python
# Inside _process_loop() after consuming each message — add after the topic routing check:
async for kafka_topic, key, payload in self._consumer.messages():
    if not self.running:
        break
    self._record_message_consumed()   # ADD THIS — sets self._last_message_ts
    try:
        ...
```

**HF-10 — dead topic subscriptions:**
`intelligence.i8` and `llm.outcomes` topics: verify which services subscribe, then either remove subscriptions or add a `# TODO: publisher not yet wired` comment. Do not silently leave them active.

---

### `services/feature_writer_agent.py` (HF-4)

**Analog:** `services/ctx_writer_agent.py` lines 367-374 (`_setup()` raises on DB failure via `DatabaseManager.initialize()`)

**Bug location in current source:**
- Lines 406-414: `_connect_database()` catches all exceptions and sets `self.db_manager = None` instead of raising

**Fail-fast pattern** (ghost-run anti-pattern fix):
```python
# _connect_database() BEFORE (lines 412-414):
except Exception as e:
    self.logger.warning("Database unavailable, persistence disabled", error=str(e))
    self.db_manager = None

# AFTER — minimal change only, do not refactor initialization:
except Exception as e:
    self.logger.error("feature_writer.db_connect_failed", error=str(e))
    raise
```

**Why raise:** `BaseAgent._setup()` propagates the exception to the service runner, which exits. systemd `Restart=on-failure` restarts the service. A writer with no DB is useless — fail-fast is the correct pattern. See `services/ctx_writer_agent.py` line 368-369 for the standard pattern where `DatabaseManager.initialize()` raises naturally.

---

### `services/bar_writer_agent.py` (HF-7)

**Analog:** `services/feature_writer_agent.py` lines 467-470, `services/ctx_writer_agent.py` line 180, `services/bar_auditor_agent.py` line 229

**Bug location in current source:**
- Lines 241-270: custom `_run()` override has no call to `self._record_message_consumed()` inside the loop

**`_record_message_consumed()` in custom `_run()` pattern** (from `services/ctx_writer_agent.py` line 180):
```python
async for _topic, _key, payload in self._kafka_consumer.messages():
    if not self.running:
        break
    # Route contract update events first
    if _topic == _contract_updates_topic:
        await self._handle_contract_update(payload)
        continue
    self._record_message_consumed()   # ADD after routing check, around line 254
    try:
        rows = self._parse_payload(payload)
        ...
```

**Exact insertion point:** After the `_contract_updates_topic` routing block (around line 254), before the `try:` block at line 254. This mirrors `bar_auditor_agent.py` line 229: `self._record_message_consumed()  # Track liveness for stall detection`.

---

### `services/swarm_ledger_writer_agent.py` (HF-5)

**Analog:** `services/feature_writer_agent.py` lines 442-451 (`enable_auto_commit=False` with `_consumer` wired for offset commit)

**Bug location in current source:**
- Lines 98-99: `enable_auto_commit=True` in `KafkaConsumerClient` constructor

**`enable_auto_commit=False` pattern** (from `services/feature_writer_agent.py` lines 442-451):
```python
self._kafka_consumer = KafkaConsumerClient(
    *topics,
    bootstrap_servers=self._kafka_bootstrap,
    group_id=CONSUMER_GROUP,
    auto_offset_reset="earliest",
    enable_auto_commit=False,   # offsets committed only after successful DB write
)
await self._kafka_consumer.start()
self._consumer = self._kafka_consumer   # wire to BaseWriterAgent for offset commit
```

**Minimum fix for HF-5:** Change `enable_auto_commit=True` to `enable_auto_commit=False` at line 99. The existing `ON CONFLICT` UPSERT on `signal_ai_enrichment.signal_id` makes re-delivery safe (at-least-once delivery is acceptable). Full manual commit wiring is out of scope per PLAN.md.

---

### `src/intelligence/pipeline/executor.py` (HF-1 — shadow stamp)

**Analog:** `src/intelligence/pipeline/executor.py` lines 211-217 (`_is_shadow()` method already exists)

**Bug location in current source:**
- Lines 697-710: post-processing loop stamps `sig["setup_plugin"]`, `sig["symbol"]`, `sig["tf"]`, `sig["regime_type"]` but never stamps `sig["is_shadow"]`

**`_is_shadow()` method** (lines 211-217 — already in the file):
```python
def _is_shadow(self, plugin_name: str, shadow_cache: dict) -> bool:
    """Look up shadow state from the passed shadow_cache parameter."""
    return shadow_cache.get(plugin_name, False)
```

**Shadow stamp pattern — add to post-processing loop** (after line 707):
```python
for task, output in zip(tasks, outputs, strict=False):
    output.pop("_tier_key", None)
    if output.get("direction", 0) != 0:
        sig = output
        sig["setup_plugin"] = task.plugin_name
        sig["symbol"] = symbol
        sig["tf"] = tf
        plugin_inst = self._plugin_cache.get(task.plugin_name)
        sig["regime_type"] = getattr(plugin_inst, "regime_type", "any")
        sig["is_shadow"] = self._is_shadow(task.plugin_name, cache_snapshot.shadow_cache)  # ADD
        raw_signals.append(sig)
```

**`cache_snapshot` parameter:** `run_i7_complete()` already receives `cache_snapshot: CacheSnapshot` (confirmed by `CacheSnapshot.shadow_cache` field at `signal_processor.py` line 132). The method signature already has access; no parameter changes needed.

---

### `src/intelligence/pipeline/signal_processor.py` (HF-1 — winner filter + status)

**Analog:** `src/intelligence/pipeline/signal_processor.py` lines 405-433 (existing ranking/annotation loop), `src/intelligence/pipeline/executor.py` lines 697-710

**Bug locations in current source:**
- Line 421: `select_winner(ranked, ...)` passes full `ranked` list including shadow plugins
- Line 411: status annotation has `"pending"` and `"regime_suppressed"` branches but no `"shadow"` branch

**Shadow winner filter pattern** (insert before line 420, after the annotation loop):
```python
# Build eligible list — shadow plugins cannot win (they are being evaluated, not live)
eligible_ranked = [
    s for s in ranked
    if not cache_snapshot.shadow_cache.get(s.get("setup_plugin", ""), False)
]

# Line 421 — change ranked to eligible_ranked:
winner, _, resolution_method = select_winner(
    eligible_ranked, cis_result, long_bias=getattr(self._settings, "winner_long_bias", True)
)
```

**Shadow status annotation** (add to line 411 status block):
```python
# Existing status assignment:
sig["status"] = "pending" if sig.get("regime_eligible", True) else "regime_suppressed"

# Add shadow override after the existing line:
if cache_snapshot.shadow_cache.get(sig.get("setup_plugin", ""), False):
    sig["status"] = "shadow"
```

**`cache_snapshot` is already a parameter:** `process()` at line 241 receives `cache_snapshot: CacheSnapshot`. `CacheSnapshot.shadow_cache` is a `dict` field (line 132). No signature changes needed.

**Fix order matters (internal to Task 4):** stamp in executor first (so `is_shadow` field exists) → filter in signal_processor (so shadows cannot win) → status annotation (so shadow signals get correct status string) → auditor query fixes.

---

### `services/shadow_auditor_agent.py` (HF-1 — SQL filters + HF-8 — metric type)

**Analog:** `src/observability/metrics.py` (correct `point_gauge` usage at lines 121-124, 152-155, 261-264)

**Bug locations in current source:**
- Line 115: `_check_promotion()` SQL has no `AND is_shadow = FALSE` filter
- Line 256: `_check_demotion()` SQL has no `AND is_shadow = FALSE` filter
- Line 84: `_run_audit()` does not filter `shadow_registry` by `component_type`, so swarm agents (with no `signal_ledger` rows) always evaluate to n=0
- Lines 170-194: `SHADOW_N_RESOLVED.add()`, `SHADOW_WIN_RATE.add()`, etc. — all accumulate forever (wrong metric type for point-in-time values)

**SQL filter fix for `_check_promotion()` (line 119-123):**
```python
signal_rows = await conn.fetch(
    """
    SELECT outcome, pnl_r, signal_computed_at
    FROM signal_ledger
    WHERE setup_plugin = $1
      AND is_shadow = FALSE          -- ADD: only count live-mode resolved signals
      AND outcome IS NOT NULL
      AND outcome NOT IN ('never_activated', 'ttl_expired_behind')
    """,
    name,
)
```

**SQL filter fix for `_check_demotion()` (same pattern at line ~256):** Add `AND is_shadow = FALSE` to the same `signal_ledger` query.

**`component_type` filter fix for `_run_audit()`:** Add `WHERE component_type = 'plugin'` (or equivalent) to the `shadow_registry` query at line 84 so swarm agents are excluded from signal-ledger-based evaluation.

**`point_gauge` + `.set()` pattern** (from `src/observability/metrics.py` lines 121-124 and 152-155):
```python
# CORRECT existing usage (circuit breaker state — point-in-time):
CIRCUIT_BREAKER_STATE = _meter.create_gauge(
    "plugin_circuit_breaker_state",
    description="Circuit breaker state (0=closed, 1=open, 2=half-open)",
)
# Call site: CIRCUIT_BREAKER_STATE.set(value, {"label": val})

# CORRECT existing usage (consumer lag — point-in-time):
PERSISTENCE_CONSUMER_LAG = _meter.create_gauge(
    "persistence_consumer_lag_records",
    description="Current consumer lag in records",
)
```

**HF-8 fix in `src/observability/metrics.py` lines 224-244:**
```python
# Change all five shadow metrics from create_up_down_counter to point_gauge():
# BEFORE:
SHADOW_N_RESOLVED = _meter.create_up_down_counter("shadow_n_resolved", ...)
SHADOW_WIN_RATE = _meter.create_up_down_counter("shadow_win_rate", ...)
SHADOW_EV_R = _meter.create_up_down_counter("shadow_ev_r", ...)
SHADOW_EV_CI_LOWER = _meter.create_up_down_counter("shadow_ev_ci_lower", ...)
SHADOW_DAYS_TO_GATE = _meter.create_up_down_counter("shadow_days_to_gate", ...)

# AFTER:
SHADOW_N_RESOLVED = point_gauge("shadow_n_resolved", "Resolved shadow signals")
SHADOW_WIN_RATE = point_gauge("shadow_win_rate", "Shadow plugin win rate")
SHADOW_EV_R = point_gauge("shadow_ev_r", "Shadow plugin E[PnL_R]")
SHADOW_EV_CI_LOWER = point_gauge("shadow_ev_ci_lower", "Shadow 95% CI lower bound on E[PnL_R]")
SHADOW_DAYS_TO_GATE = point_gauge("shadow_days_to_gate", "Estimated days to N=100 resolved")
```

**HF-8 fix in `services/shadow_auditor_agent.py` lines 170-194:**
```python
# Change all .add() to .set() for the five shadow metrics:
SHADOW_N_RESOLVED.set(n, {"plugin": name})
SHADOW_WIN_RATE.set(round(win_rate, 4), {"plugin": name})
SHADOW_EV_R.set(round(ev_r, 4), {"plugin": name})
SHADOW_EV_CI_LOWER.set(ci_display, {"plugin": name})
SHADOW_DAYS_TO_GATE.set(round(days_to_gate, 1) if days_to_gate != float("inf") else 0.0, {"plugin": name})
```

**Note:** `SHADOW_PROMOTION_READY` at line 244 is also `create_up_down_counter` — evaluate whether it should also be `point_gauge`. It is a boolean flag (0/1) representing current state, so yes it should also be `point_gauge` + `.set()`.

---

### `src/observability/metrics.py` (HF-8 — `point_gauge` already exists)

**No analog needed — `point_gauge()` factory is already defined at lines 32-34:**
```python
def point_gauge(name: str, documentation: str):
    """Create a named OTel gauge for point-in-time absolute values. Use .set(value)."""
    return _meter.create_gauge(name, description=documentation)
```

**Existing correct usages of `_meter.create_gauge()` (lines 121, 152, 261, 278):**
- `CIRCUIT_BREAKER_STATE` (line 121) — `create_gauge`, call `.set()`
- `PERSISTENCE_CONSUMER_LAG` (line 152) — `create_gauge`, call `.set()`
- `AGENT_LAST_MESSAGE_TIMESTAMP_SECONDS` (line 261) — `create_gauge`, call `.set()`
- `AGENT_CIRCUIT_BREAKER_STATE` (line 278) — `create_gauge`, call `.set()`

**Existing correct usage of `_meter.create_histogram()` (lines 51, 85, 111, 137, 147, 214, 457):**
```python
# Reference for HF-9 histogram creation:
PLUGIN_DURATION_MS = _meter.create_histogram(
    "intelligence_pipeline_plugin_duration_ms",
    description="Per-plugin execution latency",
    unit="ms",
)
# Call site: PLUGIN_DURATION_MS.record(duration_ms, {"plugin_name": name, "tier": tier})

AI_AGENT_DURATION_MS = _meter.create_histogram(
    "ai_agent_duration_ms",
    description="AI agent execution latency in ms",
    unit="ms",
)
```

---

### `services/intelligence_pipeline_agent.py` (HF-9)

**Analog:** `src/observability/metrics.py` lines 51-55 (`create_histogram` with `unit="ms"`), `services/contract_metadata_writer_agent.py` lines 64-67 (service-local histogram via `_meter.create_histogram`)

**Bug locations in current source (lines 176-193):**
- `self._bars_processed` created with `gauge()` — should be `counter()` (monotonic count)
- `self._i1_latency_ms` created with `gauge()` — should be `_meter.create_histogram()`
- `self._i7_latency_ms` created with `gauge()` — should be `_meter.create_histogram()`
- `self._pipeline_errors` created with `gauge()` — should be `counter()`
- `self._pipeline_latency` created with `gauge()` — should be `_meter.create_histogram()`
- `self._i1_latency_ms` and `self._pipeline_latency` are created but never called (dead instruments)

**Histogram creation pattern** (from `services/contract_metadata_writer_agent.py` lines 64-67, and `src/observability/metrics.py` lines 51-55):
```python
from opentelemetry import metrics as _otel_metrics
_meter = _otel_metrics.get_meter("indicagent")

_PROCESSING_LATENCY = _cmw_meter.create_histogram(
    "contract_writer_processing_latency_seconds",
    description="Roll event processing latency",
)
```

**HF-9 fix in `services/intelligence_pipeline_agent.py` lines 176-193:**
```python
# Import _meter or use the module-level one; access via self._meter from BaseAgent
# Replace gauge() calls with correct types:

self._bars_processed = counter(
    "intelligence_pipeline_bars_processed_total",
    "Bars processed through I1-I7 pipeline",
)
self._i1_latency_ms = self._meter.create_histogram(
    "intelligence_pipeline_i1_latency_ms",
    description="I1 tier execution time in milliseconds",
    unit="ms",
)
self._i7_latency_ms = self._meter.create_histogram(
    "intelligence_pipeline_i7_latency_ms",
    description="I7 tier execution time in milliseconds",
    unit="ms",
)
self._pipeline_errors = counter(
    "intelligence_pipeline_pipeline_errors_total",
    "Pipeline processing errors",
)
self._pipeline_latency = self._meter.create_histogram(
    "intelligence_pipeline_pipeline_latency_ms",
    description="Per-bar pipeline latency in milliseconds",
    unit="ms",
)
```

**Wire `.record()` calls:** After converting to histogram, add `.record()` in `_process_bar_inner()` and at the I1 tier execution boundary. Use `PLUGIN_DURATION_MS.record(duration_ms, {"plugin_name": name, "tier": "i1"})` as the reference call pattern (from `metrics.py` line 51).

---

## Shared Patterns

### OTel Metric Call API (cross-cutting — applies to all HF-2, HF-3, HF-8, HF-9)
**Source:** `src/observability/metrics.py` lines 1-13 (module docstring)
```python
# Counter:         METRIC.add(n, {"label": value})       — monotonic, only deltas
# UpDownCounter:   METRIC.add(delta, {"label": value})   — accumulated running total
# Point Gauge:     METRIC.set(value, {"label": value})   — point-in-time absolute
# Histogram:       METRIC.record(value_ms, {"label": value})
# NO .inc() METHOD EXISTS ON ANY OTel INSTRUMENT
```

### `_record_message_consumed()` wiring (cross-cutting — HF-6, HF-7)
**Source:** `services/feature_writer_agent.py` line 470, `services/ctx_writer_agent.py` line 180
**Apply to:** Any `_run()` or `_process_loop()` override that consumes from Kafka
```python
# Inside the Kafka message loop, call after consuming each message:
self._record_message_consumed()
# Sets self._last_message_ts (monotonic clock). Used by:
# - BaseAgent._stall_watchdog() to detect stalls
# - service_auditor_agent._fetch_stalled_agents() to detect dead agents
# - AGENT_LAST_MESSAGE_TIMESTAMP_SECONDS gauge (auto-set internally)
```

### `enable_auto_commit=False` (cross-cutting — HF-5)
**Source:** `services/feature_writer_agent.py` lines 447-451
**Apply to:** Any writer service that performs DB writes before committing offsets
```python
KafkaConsumerClient(
    *topics,
    bootstrap_servers=...,
    group_id=...,
    auto_offset_reset="earliest",
    enable_auto_commit=False,   # commit after successful DB write, not on receive
)
```

### `await super()._teardown()` as first call (cross-cutting — HF-11)
**Source:** `services/bar_writer_agent.py` lines 272-277
**Apply to:** All `BaseWriterAgent` subclasses that override `_teardown()`
```python
async def _teardown(self) -> None:
    await super()._teardown()   # FIRST — guaranteed flush of in-flight buffers
    # then stop consumers, close DB pools
```

### Fail-fast DB init (cross-cutting — HF-4)
**Source:** `services/ctx_writer_agent.py` lines 367-369 (standard pattern):
```python
async def _setup(self) -> None:
    self._db = DatabaseManager(self.settings.database_url)
    await self._db.initialize()   # raises on failure — let systemd restart
```
**Do not catch DB init exceptions in writer services.** A writer with no DB is permanently broken. Swallowing the exception creates ghost-run services that log no data and fill buffers silently.

---

## No Analog Found

All 10 files have strong analogs in the codebase. No files require reaching for external patterns.

---

## Fix Sequencing (for planner)

Per RESEARCH.md task sequencing:

1. **Task 1** — HF-2 (`ctx_writer_agent.py` `.inc()` fix) + HF-11 (`ctx_writer_agent.py` `super()._teardown()`) + HF-3 (`llm_writer_service.py` pool ref + `.inc()` fix). No dependencies.
2. **Task 2** — HF-6 + HF-7 (stall watchdog fixes in `llm_writer_service.py` and `bar_writer_agent.py`). Read current state of `llm_writer_service.py` after Task 1 edits before modifying.
3. **Task 3** — HF-4 (`feature_writer_agent.py` raise) + HF-5 (`swarm_ledger_writer_agent.py` auto-commit). No inter-task dependencies.
4. **Task 4** — HF-1 shadow governance. Internal order: executor.py stamp → signal_processor.py filter → signal_processor.py status → shadow_auditor_agent.py SQL fixes.
5. **Task 5** — HF-8 + HF-9 (OTel metric type fixes in `metrics.py`, `shadow_auditor_agent.py`, `intelligence_pipeline_agent.py`).
6. **Task 6** — HF-10 (dead topic subscriptions). Lowest urgency.

---

## Metadata

**Analog search scope:** `services/`, `src/intelligence/pipeline/`, `src/observability/`, `src/core/agent/`
**Files scanned:** 12 source files read directly
**Pattern extraction date:** 2026-05-23
