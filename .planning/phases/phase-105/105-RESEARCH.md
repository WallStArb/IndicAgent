# Phase 105: Architecture Hotfix Sprint - Research

**Researched:** 2026-05-23
**Domain:** Python async services, OTel metrics, shadow governance, persistence writers
**Confidence:** HIGH

---

## Summary

Phase 105 is a mechanical bug-fix sprint against 11 confirmed production bugs (HF-1 through HF-11) identified in the 2026-05-23 full-spectrum architectural audit. All bugs are verified by direct source inspection — this is not speculative. The bugs fall into four categories: (1) active data loss via AttributeError crashes in persistence flush paths, (2) shadow signal governance bypass enabling live trade leakage, (3) stall watchdog blindness in two writer services, and (4) OTel metric type mismatches causing permanently incorrect Grafana dashboards.

Critically, PLAN.md already exists in `.planning/phases/phase-105/` with six tasks defined. The research below validates that plan, adds precision on exact code locations, and surfaces three important findings: several files have already been partially modified (migration 094 work), `ctx_writer_agent.py` already has `.inc()` calls at lines 343 and 351 that need fixing, and `signal_processor.py` receives `cache_snapshot` as a parameter but never reads `shadow_cache` from it in the winner-selection path.

**Primary recommendation:** Execute the PLAN.md tasks in order. Tasks 1-2 (data loss) are highest urgency; Task 3 (shadow governance) is highest business impact. All fixes are mechanical line changes with no architectural decisions required.

---

## Bug Inventory — Verified Locations

### HF-1: Shadow signal suppression — shadow plugins can win and reach live trading
**Severity:** CRITICAL (alpha leakage)
**Files:**
- `src/intelligence/pipeline/executor.py` — post-processing loop at lines 697-710. `sig["is_shadow"]` is never stamped. `_is_shadow()` method exists at line 211 but is never called in this loop. Fix: add `sig["is_shadow"] = self._is_shadow(task.plugin_name, cache_snapshot.shadow_cache)` inside the loop after `sig["setup_plugin"]` is set.
- `src/intelligence/pipeline/signal_processor.py` — `process()` method (line 241) receives `cache_snapshot: CacheSnapshot` which has `shadow_cache: dict` (line 132). The `select_winner()` call at line 421 receives the full `ranked` list with no shadow filter. Fix: build `eligible_ranked = [s for s in ranked if not cache_snapshot.shadow_cache.get(s.get("setup_plugin", ""), False)]` and pass `eligible_ranked` to `select_winner()`.
- Status annotation: `signal_processor.py` line 411 sets `status="pending"` or `status="regime_suppressed"` but has no shadow branch. Fix: add shadow status assignment after the existing status stamp.
- `services/shadow_auditor_agent.py` — `_check_promotion()` at line 115 has no `AND is_shadow = FALSE`. `_check_demotion()` at line 256 has no `AND is_shadow = FALSE`. `_run_audit()` at line 84 does not filter by `component_type`, so swarm agents (with no `signal_ledger` rows) always evaluate to n=0.

**Fix dependency chain:** SG-7 (winner filter) → SG-1 (stamp) → SG-6 (status) → SG-2/3 (query filters) → SG-4 (component_type filter). Must fix in this order.

**Key note on existing partial fix:** `services/signal_writer_agent.py` line 201 already reads `is_shadow=bool(sig.get("is_shadow", False))` — it is prepared to receive the field. `signal_ledger_repository.py` already has `is_shadow: bool = False` in `LedgerEntry` at line 94 and `$5 is_shadow` in `_to_row()`. The DB schema and writer are ready; only the stamping (executor.py) and filtering (signal_processor.py) are missing.

---

### HF-2: CtxWriterAgent `.inc()` AttributeErrors crash flush loop
**Severity:** HIGH (data loss)
**File:** `services/ctx_writer_agent.py`
- Line 343: `self._events_written.inc(len(event_batch))` — OTel counter has no `.inc()` method
- Line 351: `self._snapshots_written.inc(len(snapshot_batch))` — same issue
- Effect: `_flush()` raises `AttributeError`, propagates to `_do_flush()`, increments `_flush_errors_total`, but leaves buffers unflushed. `MAX_BUFFER_SIZE` is 50 rows. Every flush attempt re-fails forever.
- Fix: change both `.inc(n)` to `.add(n)`.
- **Verified:** These lines still have `.inc()` calls in the current source (read 2026-05-23).

---

### HF-3: LLMWriterAgent `self._pool` AttributeError on `_parse_update` messages
**Severity:** CRITICAL (data loss + feedback loop corruption)
**File:** `services/llm_writer_service.py`
- Line 695: `async with self._pool.acquire() as conn:` — `self._pool` is never initialized. Only `self.db_manager` exists.
- Any `_parse_update` message raises `AttributeError`, caught by outer `except Exception`, silently dropped. `parse_success` back-fills on `llm_calls` never succeed.
- Fix: replace with `await self.db_manager.execute_command(_UPDATE_PARSE_SQL, call_id, parse_success)`.
- Line 822: `self.i8_writes_total.inc(len(batch))` — same `.inc()` vs `.add()` bug.
- Fix: change to `.add(len(batch))`.
- **Verified:** Both issues confirmed in current source.

---

### HF-4: FeatureWriterAgent ghost-run on DB failure
**Severity:** HIGH (highest data loss rate: ~160 rows/min)
**File:** `services/feature_writer_agent.py`
- Lines 406-414: `_connect_database()` catches all DB exceptions and sets `self.db_manager = None`. When `None`, `_flush_batch()` raises `RuntimeError("No database connection")`. BaseWriterAgent catches this and increments `_flush_errors_total` but does not crash the service. Buffer fills to 10,000 rows then silently drops the oldest.
- Fix: replace `except` block with `raise` — let systemd restart the service.
- **Pattern:** This is the ghost-run anti-pattern. Fail-fast is correct here because a writer service with no DB is useless.

---

### HF-5: SwarmLedgerWriterAgent auto-commit before DB write
**Severity:** HIGH (data loss on DB failure)
**File:** `services/swarm_ledger_writer_agent.py`
- Line 98-99: `enable_auto_commit=True` in `KafkaConsumerClient` constructor. Kafka offsets are committed as messages are received, before the DB write succeeds. A DB failure causes the message to be lost permanently (offset already advanced).
- Fix: change to `enable_auto_commit=False`. Then either commit offsets manually after successful DB write, or accept at-least-once with the existing UPSERT idempotency (the `ON CONFLICT` on `signal_ai_enrichment.signal_id` makes re-delivery safe).
- **Note:** `SwarmLedgerWriterAgent` extends `BaseAgent`, not `BaseWriterAgent`. It has no DLQ. The minimum fix is `enable_auto_commit=False` — the PLAN.md correctly identifies this as the scope boundary.

---

### HF-6: LLMWriterService stall watchdog reads undefined attribute
**Severity:** HIGH (watchdog permanently dead)
**File:** `services/llm_writer_service.py`
- Line 946: `if self._last_msg_ts is None: continue` — `self._last_msg_ts` is never assigned anywhere in the file.
- Line 948: `idle_secs = time.monotonic() - self._last_msg_ts` — also uses undefined attribute.
- BaseAgent defines `self._last_message_ts` (with `_message_` in the name), set only by `_record_message_consumed()`.
- Fix: replace all `self._last_msg_ts` references with `self._last_message_ts`, and add `self._record_message_consumed()` inside `_process_loop()` after each message is consumed.
- **Verified:** Only two references to `_last_msg_ts` exist (lines 946, 948).

---

### HF-7: BarWriterAgent custom `_run()` never calls `_record_message_consumed()`
**Severity:** HIGH (stall watchdog and service_auditor blind to bar_writer)
**File:** `services/bar_writer_agent.py`
- Lines 241-270: custom `_run()` override with `async for _topic, _key, payload in self._kafka_consumer.messages():` loop. No call to `self._record_message_consumed()` inside the loop.
- Effect: `AGENT_LAST_MESSAGE_TIMESTAMP_SECONDS` is never set for `bar_writer_agent`. `service_auditor_agent._fetch_stalled_agents()` will never detect a stall. The BaseAgent stall watchdog (`_stall_watchdog` in `base.py:325`) reads `self._last_message_ts` which is always None.
- Fix: add `self._record_message_consumed()` inside the loop, after the `_contract_updates_topic` routing check (around line 254).
- **Verified:** No call to `_record_message_consumed` exists in `bar_writer_agent.py`.

---

### HF-8: Shadow governance metrics use `up_down_counter` with absolute values
**Severity:** HIGH (dashboard permanently wrong — N× actual value after N audit cycles)
**File:** `src/observability/metrics.py` lines 224-243, `services/shadow_auditor_agent.py` lines 170-194
- `SHADOW_WIN_RATE`, `SHADOW_N_RESOLVED`, `SHADOW_EV_R`, `SHADOW_DAYS_TO_GATE`, `SHADOW_EV_CI_LOWER` — all created via `up_down_counter`. `shadow_auditor_agent.py` calls `.add(absolute_value)` each audit cycle. After 10 cycles, metric shows 10× actual.
- Fix: change all five to `create_gauge()` (the `point_gauge()` factory already exists at `metrics.py:32`) and call `.set(value, attrs)` instead of `.add(value, attrs)` in shadow_auditor_agent.py.
- **Key fact:** `point_gauge()` already exists in `src/observability/metrics.py:32` (added recently). It calls `_meter.create_gauge()`. This is a drop-in replacement.

---

### HF-9: Pipeline latency instruments are `up_down_counter` instead of `histogram`
**Severity:** CRITICAL (no percentile visibility on hottest path)
**File:** `services/intelligence_pipeline_agent.py` lines 176-193
- `self._bars_processed`, `self._i1_latency_ms`, `self._i7_latency_ms`, `self._pipeline_errors`, `self._pipeline_latency` — all created via `gauge()` which wraps `create_up_down_counter()`.
- Additionally, `self._i1_latency_ms` and `self._pipeline_latency` are defined but never called (dead instruments). Grafana dashboard for these metrics shows a flat zero line.
- Fix: replace latency instruments with `_meter.create_histogram()` and count instruments with `_meter.create_counter()`. Then wire actual `.record()` calls.
- **Note:** The audit recommends adding actual `.record()` calls at the I1 tier and `_process_bar_inner()`. This is in scope for HF-9.

---

### HF-10: Dead topic subscriptions — `intelligence.i8` and `llm.outcomes` have no publishers
**Severity:** MEDIUM (no active data loss — services just consume empty topics)
**Files:** `services/` directory — services consuming `intelligence.i8` and `llm.outcomes`
- `intelligence.i8` topic: consumed but no publisher exists anywhere in the codebase.
- `llm.outcomes` topic: consumed by `llm_writer_service.py` but no publisher found.
- Fix options: (a) remove the subscription if the topic will never be wired, or (b) document as "planned publisher" with a TODO.
- **Research note:** The audit says these are dead. Need to verify which services subscribe to them before deciding on removal vs. documentation.

---

### HF-11: CtxWriterAgent `_teardown()` missing `super()._teardown()` call
**Severity:** HIGH (in-flight buffers lost on shutdown)
**File:** `services/ctx_writer_agent.py` lines 376-387
- `_teardown()` has its own flush logic but does NOT call `await super()._teardown()`. `BaseWriterAgent._teardown()` runs the final guaranteed flush of in-flight buffers.
- The current `_teardown()` does have a flush attempt at lines 377-383, but it uses `self._flush(self._event_buffer[:], self._snapshot_buffer[:])` directly. If this raises, the buffers are lost.
- Fix: add `await super()._teardown()` as the FIRST statement in `_teardown()`.
- **Caution:** Adding `super()._teardown()` first may cause a double-flush attempt if the parent class also calls `_flush_batch`. Verify the BaseWriterAgent._teardown() implementation before adding to ensure no duplicate flushes. The PLAN.md plan accounts for this.

---

## Already Partially Fixed (git status)

The following files have staged/unstaged changes from v2.7 migration 094 work:

| File | What Changed | Phase 105 Relevance |
|------|-------------|---------------------|
| `services/signal_writer_agent.py` | Added `cis_score`, `bucket_scores`, `weights_version` field mapping in `_payload_to_ledger_entries()`. Removed `num_signals` local var. | Not a Phase 105 bug. Complement to migration 094. No conflict. |
| `src/intelligence/weight_updater.py` | Removed `confidence` from SELECT query (column no longer exists post-094). | Not a Phase 105 bug. Pre-existing fix. |
| `src/persistence/repository/signal_ledger_repository.py` | Added `cis_score`, `bucket_scores`, `weights_version` fields to `LedgerEntry` and `_INSERT_SQL`. | Not a Phase 105 bug. Required for migration 094. Must be applied before deploying new writer. |
| `tests/unit/persistence/test_signal_ledger_repository.py` | Updated tests for new LedgerEntry fields. | Tests pass — no Phase 105 conflict. |
| `tests/unit/services/test_signal_writer_agent.py` | Updated test fixtures for new signal fields. | Tests pass — no Phase 105 conflict. |

**Conclusion:** These changes do not conflict with any Phase 105 fix. They should be committed as a separate "migration 094 support" commit before Phase 105 work begins, or included in the Phase 105 branch as pre-existing changes.

**Migration 094 dependency:** `production/migrations/094_signal_ledger_cis_columns.sql` must be applied to the database before deploying the modified `signal_writer_agent.py`. Verify with: `psql -U postgres -d indicagent -c "SELECT cis_score FROM signal_ledger LIMIT 1"`.

---

## Standard Stack

### Core Libraries in Use

| Library | Purpose | Where Used |
|---------|---------|-----------|
| `opentelemetry-sdk` | Metrics, spans, traces | `src/observability/metrics.py`, `src/observability/spans.py` |
| `asyncpg` | PostgreSQL async driver | `SwarmLedgerWriterAgent._pool`, `BarWriterAgent._db_pool` |
| `DatabaseManager` | Asyncpg wrapper with pooling | `src/core/database_manager.py` — standard for all writer agents |
| `BaseWriterAgent` | Base class for persistence writers | `src/core/agent/base_writer.py` |
| `BaseAgent` | Base class for all agents | `src/core/agent/base.py` |
| `KafkaConsumerClient` | Kafka consumer abstraction | All writer services |

### OTel Metric Factory Functions

| Factory | Creates | Use Case |
|---------|---------|---------|
| `counter(name, doc)` | `create_counter` | Monotonic cumulative (events consumed, errors total) |
| `gauge(name, doc)` | `create_up_down_counter` | **MISLEADING NAME** — accumulating counter, NOT point-in-time |
| `point_gauge(name, doc)` | `create_gauge` | Point-in-time absolute values (shadow metrics, pool size) |
| `_meter.create_histogram(name, unit)` | Histogram | Latency percentiles (p50/p95/p99) |

**CRITICAL:** `gauge()` is the source of HF-8 and HF-9. It wraps `create_up_down_counter()` which accumulates forever. For any point-in-time value, use `point_gauge()`. For any latency metric, use `_meter.create_histogram()` directly.

**OTel call patterns:**
- Counter: `.add(n, {"label": value})`
- Point gauge: `.set(value, {"label": value})`
- Histogram: `.record(value_ms, {"label": value})`
- Up-down counter (accumulated): `.add(delta, {"label": value})`
- **No `.inc()` method exists on any OTel instrument** (HF-2, HF-3)

---

## Architecture Patterns

### Writer Agent Patterns

**Standard pattern (from `contract_metadata_writer_agent.py` — reference implementation):**
```python
class MyWriterAgent(BaseWriterAgent):
    async def _setup(self) -> None:
        self._db = DatabaseManager(self.settings.database_url)
        await self._db.initialize()  # raises on failure — systemd restarts
        self._create_consumer()
        await self._consumer.start()

    async def _run(self) -> None:
        # Standard: use BaseWriterAgent._run() — do NOT override unless necessary
        # If overriding, MUST call self._record_message_consumed() per message

    async def _teardown(self) -> None:
        await super()._teardown()  # FIRST — runs final flush
        # then clean up resources
```

**`_parse_payload()` return contract (from CLAUDE.md):**
- `None` = truly empty/unparseable → base class routes to DLQ
- `[]` = valid but no rows → base class skips, no DLQ
- `[rows...]` = valid rows → buffered for flush

**Shadow signal stamp pattern:**
```python
# In executor.py post-processing loop:
sig["is_shadow"] = self._is_shadow(task.plugin_name, cache_snapshot.shadow_cache)

# In signal_processor.py before select_winner():
eligible_ranked = [
    s for s in ranked
    if not cache_snapshot.shadow_cache.get(s.get("setup_plugin", ""), False)
]
winner, _, resolution_method = select_winner(eligible_ranked, cis_result, ...)
```

**Stall watchdog pattern:**
```python
# Inside _run() message loop — required for BaseAgent stall detection:
self._record_message_consumed()
# Sets self._last_message_ts (monotonic). Used by _stall_watchdog() and service_auditor.
```

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead |
|---------|-------------|-------------|
| DB connection | asyncpg directly | `DatabaseManager` from `src/core/database_manager.py` — has pooling, error handling |
| Latency histograms | Manual bucketing | `_meter.create_histogram(name, unit="ms")` + `.record()` |
| Point-in-time gauge | `up_down_counter` with absolute values | `point_gauge()` from `src/observability/metrics.py:32` |
| DB execute one-off | `self._pool.acquire()` | `self.db_manager.execute_command(sql, *params)` |
| Shadow cache lookup | Dict query inline | `self._is_shadow(plugin_name, cache_snapshot.shadow_cache)` in executor.py |

---

## Common Pitfalls

### Pitfall 1: OTel `.inc()` does not exist
**What goes wrong:** AttributeError inside flush, caught silently by `_do_flush()`, buffers never drain.
**Why it happens:** Prometheus client had `.inc()`. OTel SDK does not. The migration from prometheus to OTel left some call sites unconverted.
**How to avoid:** Only use `.add(n)` for counters, `.record(v)` for histograms, `.set(v)` for point gauges.

### Pitfall 2: `gauge()` accumulates; `point_gauge()` is point-in-time
**What goes wrong:** Shadow metrics show N× actual value after N audit cycles.
**Why it happens:** `gauge()` wraps `create_up_down_counter()` — misleading name. Every `.add(absolute_value)` call adds to a running sum, not sets a point value.
**How to avoid:** For any value that is already a total (not a delta), use `point_gauge()` + `.set()`.

### Pitfall 3: `_teardown()` override without `super()._teardown()` loses in-flight data
**What goes wrong:** Events buffered after the last flush but before shutdown are dropped.
**How to avoid:** Always call `await super()._teardown()` as the FIRST line of any `_teardown()` override in a `BaseWriterAgent` subclass.

### Pitfall 4: `enable_auto_commit=True` on a writer that may fail DB writes
**What goes wrong:** Kafka offsets committed before DB write succeeds. On failure, messages are permanently lost.
**How to avoid:** Use `enable_auto_commit=False` for any writer that performs DB writes. Only commit after successful write.

### Pitfall 5: Shadow signals need `is_shadow` stamped in executor before signal_processor sees them
**What goes wrong:** `signal_processor.py` receives signals from `executor.py`. If `is_shadow` is not stamped in executor, `shadow_cache.get(setup_plugin)` in signal_processor works correctly but the field will be missing from the signal dict, so `signal_writer_agent` will always write `is_shadow=False`.
**Fix order:** Stamp in executor first (SG-1/HF-1), then filter in signal_processor (SG-7), then fix status annotation (SG-6), then fix auditor queries (SG-2/3/4).

### Pitfall 6: FeatureWriterAgent has its own DB initialization pattern
**What goes wrong:** `feature_writer_agent.py` uses `_connect_database()` with a config dict, not the standard `DatabaseManager(self.settings.database_url)` pattern. Do not refactor the full initialization — only change the exception handling.
**How to avoid:** Minimal change: replace `self.db_manager = None` with `raise` in the `except` block.

---

## Code Examples

### Fix HF-2: `.inc()` → `.add()`
```python
# services/ctx_writer_agent.py line 343 — BEFORE:
self._events_written.inc(len(event_batch))
# AFTER:
self._events_written.add(len(event_batch))

# line 351 — BEFORE:
self._snapshots_written.inc(len(snapshot_batch))
# AFTER:
self._snapshots_written.add(len(snapshot_batch))
```

### Fix HF-3: `self._pool` → `self.db_manager`
```python
# services/llm_writer_service.py line 695 — BEFORE:
async with self._pool.acquire() as conn:
    await conn.execute(_UPDATE_PARSE_SQL, call_id, parse_success)
# AFTER:
await self.db_manager.execute_command(_UPDATE_PARSE_SQL, call_id, parse_success)
```

### Fix HF-11: `super()._teardown()` in CtxWriterAgent
```python
# services/ctx_writer_agent.py — BEFORE:
async def _teardown(self) -> None:
    if self._event_buffer or self._snapshot_buffer:
        ...
# AFTER:
async def _teardown(self) -> None:
    await super()._teardown()  # runs BaseWriterAgent final flush first
    if self._event_buffer or self._snapshot_buffer:
        ...
```

### Fix HF-8: Shadow metrics — `up_down_counter` → `point_gauge`
```python
# src/observability/metrics.py — change from:
SHADOW_WIN_RATE = _meter.create_up_down_counter("shadow_win_rate", ...)
# to:
SHADOW_WIN_RATE = point_gauge("shadow_win_rate", ...)  # already imported

# services/shadow_auditor_agent.py — change from:
SHADOW_WIN_RATE.add(win_rate, {"plugin": name})
# to:
SHADOW_WIN_RATE.set(win_rate, {"plugin": name})
```

### Fix HF-9: Latency metrics — `gauge` → `histogram`
```python
# services/intelligence_pipeline_agent.py — change from:
self._i7_latency_ms = gauge("intelligence_pipeline_i7_latency_ms", "...")
# to:
self._i7_latency_ms = self._meter.create_histogram(
    "intelligence_pipeline_i7_latency_ms",
    description="I7 tier execution time",
    unit="ms",
)
# Then wire: self._i7_latency_ms.record(i7_duration_ms, {"symbol": symbol, "tf": tf})
```

### Fix HF-1: Shadow stamp in executor
```python
# src/intelligence/pipeline/executor.py lines 697-710 — inside post-processing loop:
for task, output in zip(tasks, outputs, strict=False):
    output.pop("_tier_key", None)
    if output.get("direction", 0) != 0:
        sig = output
        sig["setup_plugin"] = task.plugin_name
        sig["symbol"] = symbol
        sig["tf"] = tf
        sig["regime_type"] = getattr(plugin_inst, "regime_type", "any")
        sig["is_shadow"] = self._is_shadow(task.plugin_name, cache_snapshot.shadow_cache)  # ADD
        raw_signals.append(sig)
```

### Fix HF-1: Shadow winner filter in signal_processor
```python
# src/intelligence/pipeline/signal_processor.py — before select_winner() at line 421:
eligible_ranked = [
    s for s in ranked
    if not cache_snapshot.shadow_cache.get(s.get("setup_plugin", ""), False)
]
winner, _, resolution_method = select_winner(
    eligible_ranked, cis_result, long_bias=getattr(self._settings, "winner_long_bias", True)
)
```

### Fix HF-4: FeatureWriterAgent hard crash on DB failure
```python
# services/feature_writer_agent.py — _connect_database() BEFORE:
except Exception as e:
    self.logger.warning("Database unavailable, persistence disabled", error=str(e))
    self.db_manager = None
# AFTER:
except Exception as e:
    self.logger.error("feature_writer.db_connect_failed", error=str(e))
    raise
```

---

## Task Sequencing and Dependencies

```
Task 1: HF-2, HF-3, HF-11 (ctx_writer + llm_writer fixes)
  |-- No dependencies. Start immediately.
  |-- Unblocks: nothing (self-contained)

Task 2: HF-6, HF-7 (stall watchdog fixes)
  |-- Also touches llm_writer_service.py — READ current state from Task 1 first
  |-- No logical dependency on Task 1

Task 3: HF-4, HF-5 (feature_writer ghost-run + swarm_ledger auto-commit)
  |-- No dependencies on other tasks

Task 4: HF-1 (shadow signal suppression)
  |-- Independent of Tasks 1-3
  |-- Internal dependency: executor.py stamp MUST be done before signal_processor.py filter
  |-- Internal dependency: status fix (SG-6) after filter (SG-7) and stamp (SG-1)
  |-- Internal dependency: auditor query fixes (SG-2/3/4) last

Task 5: HF-8, HF-9 (OTel metric type fixes)
  |-- Also touches intelligence_pipeline_agent.py (same file as shadow_auditor_agent.py imports)
  |-- No blocking dependency on Tasks 1-4

Task 6: HF-10 (dead topic subscriptions)
  |-- Lowest urgency — no data loss
  |-- Can be done last or deferred
```

All tasks can be worked in parallel across files. The only ordering constraint is internal to Task 4 (shadow governance fix sequence: stamp → filter → status → query filters).

---

## Test Coverage Analysis

### Existing tests that cover Phase 105 areas

| Test File | What It Tests | Phase 105 Relevance |
|-----------|---------------|---------------------|
| `tests/unit/services/test_ctx_writer_agent.py` | CtxWriterAgent parse and flush | HF-2, HF-11 — add test for `.add()` call and `super()._teardown()` |
| `tests/unit/services/test_llm_writer_service.py` | LLMWriterService processing | HF-3, HF-6 — add `_parse_update` path test and watchdog test |
| `tests/unit/services/test_bar_writer_agent.py` | BarWriterAgent message loop | HF-7 — add test asserting `_record_message_consumed` called |
| `tests/unit/services/test_swarm_ledger_writer_agent.py` | SwarmLedgerWriterAgent | HF-5 — add test for `enable_auto_commit=False` |
| `tests/unit/services/test_signal_writer_agent.py` | SignalWriterAgent | Already modified for migration 094 fields |
| `tests/unit/services/test_shadow_auditor_agent.py` | Shadow auditor | HF-1 (auditor queries) — add test for `is_shadow = FALSE` filter |
| `tests/unit/pipeline/test_executor.py` | PluginExecutor | HF-1 (stamp) — add test for `is_shadow` field in output |
| `tests/unit/pipeline/test_signal_processor.py` | SignalProcessor | HF-1 (filter) — add test for shadow winner suppression |

### Tests that need to be added

For each fix, a unit test should verify the negative case:
- HF-2: Mock `_flush()` and assert `.add()` is called, not `.inc()`
- HF-3: Mock `db_manager.execute_command` and assert it's called on `_parse_update` payload
- HF-4: Assert `_setup()` raises when `_connect_database()` fails
- HF-5: Assert `enable_auto_commit=False` is set in `KafkaConsumerClient` constructor
- HF-7: Assert `_record_message_consumed()` is called in `_run()` loop
- HF-1: Assert winner is not a shadow plugin when shadow_cache marks it `is_shadow=True`

---

## Open Questions

1. **HF-10: Which services subscribe to `intelligence.i8` and `llm.outcomes`?**
   - What we know: audit says no publishers exist
   - What's unclear: whether to remove subscriptions or mark as planned
   - Recommendation: grep for subscribers, then document in CLAUDE.md as "deferred publisher wiring"

2. **CtxWriterAgent `_teardown()` double-flush risk**
   - What we know: the current `_teardown()` has its own flush at lines 377-383
   - What's unclear: whether `super()._teardown()` in `BaseWriterAgent` calls `_flush_batch()` which triggers a second flush
   - Recommendation: read `BaseWriterAgent._teardown()` source before applying the fix to ensure no duplicate transaction

3. **Migration 094 application status**
   - What we know: `094_signal_ledger_cis_columns.sql` is untracked in git
   - What's unclear: whether it has been applied to the production database
   - Recommendation: verify with `psql -U postgres -d indicagent -c "\d signal_ledger" | grep cis_score` before deploying modified signal_writer

---

## Sources

### Primary (HIGH confidence — direct source inspection)
- `docs/architecture/audit-2026-05-23-synthesis.md` — master synthesis with line references
- `docs/architecture/audit-2026-05-23-persistence.md` — P-1 through P-13 with exact file+line
- `docs/architecture/audit-2026-05-23-shadow-governance.md` — SG-1 through SG-9 with exact file+line
- `docs/architecture/audit-2026-05-23-telemetry.md` — T-1 through T-17 with exact file+line
- Direct source reads: `services/ctx_writer_agent.py`, `services/llm_writer_service.py`, `services/bar_writer_agent.py`, `services/swarm_ledger_writer_agent.py`, `services/feature_writer_agent.py`, `services/signal_writer_agent.py`, `services/shadow_auditor_agent.py`
- Direct source reads: `src/intelligence/pipeline/executor.py`, `src/intelligence/pipeline/signal_processor.py`, `src/observability/metrics.py`, `src/persistence/repository/signal_ledger_repository.py`
- `git diff HEAD` — verified exact lines changed in already-modified files
- `.planning/phases/phase-105/PLAN.md` — existing plan with 6 tasks

---

## Metadata

**Confidence breakdown:**
- Bug locations: HIGH — directly read from source files
- Fix patterns: HIGH — mechanical changes verified against existing working code
- Test coverage: MEDIUM — test files confirmed to exist; test content partially read
- Migration 094 status: MEDIUM — files are untracked, DB application status unknown

**Research date:** 2026-05-23
**Valid until:** 2026-06-23 (stable codebase, no fast-moving dependencies)
