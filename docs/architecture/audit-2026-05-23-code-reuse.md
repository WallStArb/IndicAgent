# Code Reuse and Base Abstraction Audit

**Date:** 2026-05-23
**Scope:** `src/core/agent/`, `src/core/`, `services/*.py`, `src/persistence/repository/`
**Framing:** Copy-paste is technical debt with interest. Every duplicated pattern is a
maintenance surface that diverges silently. Each finding answers: does this cause alpha
leakage, information destruction, or a feedback loop gap?

---

## Finding CR-1: Manual Retry Loop in `bar_aggregator_agent._setup()` Duplicates `BaseAgent._setup_with_retry()`

**Severity:** HIGH
**Category:** Complexity Drag / Feedback Loop Gap

**Files:**
- `services/bar_aggregator_agent.py:203-267` — 64-line manual retry loop
- `src/core/agent/base.py:488-511` — `_setup_with_retry()` (the authoritative implementation)

**Description:**
`BaseAgent` already provides `_setup_with_retry()` activated via `circuit_breaker = True`. `BarAggregatorComputeAgent._setup()` reimplements exponential backoff from scratch with its own constants (`_MAX_ATTEMPTS = 4`, `_BASE_DELAY = 2.0`), its own cleanup logic, and its own log events. The two implementations diverge: the base class uses jitter-free power-of-`SETUP_RETRY_BACKOFF_S`, the service uses `_BASE_DELAY * 2^(attempt-1)`. Neither uses `retry_utils.exponential_backoff_with_jitter`.

This matters for feedback loop stability: a diverging retry schedule means the aggregator
re-establishes Kafka connections at different intervals than every other service, creating
a thundering-herd window that isn't mitigated by jitter.

**Fix:**
Set `circuit_breaker = True` on `BarAggregatorComputeAgent` and remove the manual loop.
The partial-cleanup logic (stopping half-started producers on `KafkaConnectionError`) can
be moved to a `_teardown()` guard; `_setup_with_retry()` already re-raises on final failure.

---

## Finding CR-2: `_health_monitor_loop()` Cloned Across Three Services

**Severity:** HIGH
**Category:** Information Destruction / Complexity Drag

**Files:**
- `services/feature_writer_agent.py:530-550` — `_health_monitor_loop()`
- `services/llm_writer_service.py:996-1017` — identical structure, different counters
- `services/intelligence_pipeline_agent.py:604-607` — stub version (loop with no body)

**Description:**
`feature_writer_agent` and `llm_writer_service` share an almost line-for-line health monitor:
compute `uptime = int((datetime.now(tz=UTC) - self.start_time).total_seconds())`, emit the
uptime gauge, log "Health check" with counters, sleep for a configurable interval, catch
`CancelledError` to exit cleanly. The only differences are which counters appear in the log.

The uptime gauge is also emitted with inconsistent semantics: `feature_writer` calls
`self.service_uptime_seconds.set(uptime)` (point_gauge) while `llm_writer` calls
`self.service_uptime_seconds.add(uptime)` (up_down_counter). This produces divergent
Prometheus behavior: the LLM writer accumulates uptime forever rather than tracking
current age.

`start_time`, `_error_count`, `_total_batches` are also duplicate attributes managed
identically in both services. They shadow the batch counters already in `BaseWriterAgent`
(e.g., `_flush_errors_total`, `_parse_failures_total`) without adding signal.

**Fix:**
Absorb `_health_monitor_loop()` into `BaseWriterAgent` as a default 30-second loop that
logs `buffer_depth`, `flush_errors`, and `uptime` (derived from `self._start_time`).
Subclasses override `_health_log_extra()` returning a dict of additional counters to merge
into the log call. Remove per-service `start_time`, `_error_count`, `_total_batches`
fields; expose `_start_time: float = time.monotonic()` from `BaseWriterAgent.__init__`.

---

## Finding CR-3: Four `_teardown()` Methods with Identical `consumer.stop() + db.close()` Pattern

**Severity:** MEDIUM
**Category:** Complexity Drag

**Files:**
- `services/signal_writer_agent.py:152-157`
- `services/lifecycle_writer_agent.py:221-226`
- `services/graduation_writer_agent.py:120-125`
- `services/signal_metrics_writer_agent.py:289-295`
- `services/lineage_writer_agent.py:43-48`
- `services/ctx_writer_agent.py:376-387` (variation: skips `super()._teardown()`)

**Description:**
Five of six `BaseWriterAgent` subclasses implement `_teardown()` as:
```python
await super()._teardown()
if self._consumer:
    await self._consumer.stop()
if self._db:          # or self._pool
    await self._db.close()
```
This is mechanical boilerplate repeated per file. `ctx_writer_agent` omits `super()._teardown()`,
meaning its final buffer flush (which guards against data loss on shutdown) is skipped silently.
This is an information destruction risk: any records buffered at shutdown are lost without
any warning because the buffer is not empty but the flush is never attempted.

**Fix:**
`BaseWriterAgent._teardown()` already handles final flush. Add two optional lifecycle hooks:
`_close_consumer()` and `_close_db()` that `BaseWriterAgent._teardown()` calls by default
when `self._consumer` and `self._db` (or `self._pool`) are present via `hasattr` check.
Subclasses that use those attribute names get shutdown for free. `ctx_writer`'s omitted
`super()._teardown()` should be treated as a bug and fixed immediately.

---

## Finding CR-4: `enable_auto_commit=True` on `SwarmLedgerWriterAgent` Breaks Write-Safety Guarantee

**Severity:** CRITICAL
**Category:** Information Destruction

**Files:**
- `services/swarm_ledger_writer_agent.py:94-100`

**Description:**
`SwarmLedgerWriterAgent` uses `enable_auto_commit=True` on its `KafkaConsumerClient`.
The entire `BaseWriterAgent` reliability model depends on manual offset commit only after
`_flush_batch` succeeds. Auto-commit advances the offset immediately on poll, meaning if
the DB write fails (network blip, pool exhaustion, PostgreSQL restart), the event is
permanently lost — no replay, no DLQ, no retry.

`SwarmLedgerWriterAgent` also extends `BaseAgent` directly instead of `BaseWriterAgent`,
so it does not get the buffer/flush/commit/DLQ machinery at all. The service manually
catches exceptions and logs warnings without any DLQ routing or offset management.

**Fix:**
Migrate `SwarmLedgerWriterAgent` to `BaseWriterAgent`. Set `enable_auto_commit=False`.
Implement `_flush_batch` to execute the `_UPSERT_ENRICHMENT_SQL` block. The retry backoff
for missing `signal_ledger` rows (`_RETRY_BACKOFF_S`) belongs in `_flush_batch`, not in
`_run()`, consistent with how other writers handle application-level retry.

---

## Finding CR-5: Three Services Bypass `create_pool()` Wrapper (Missing JSONB Codec + Pool Gauges)

**Severity:** HIGH
**Category:** Information Destruction

**Files:**
- `services/swarm_ledger_writer_agent.py:89-92` — `asyncpg.create_pool(...)` direct call
- `services/bar_replay_provider_agent.py:60` — `asyncpg.create_pool(...)` direct call
- `services/signal_replay_auditor_agent.py:69` — `asyncpg.create_pool(...)` direct call

**Description:**
`src/core/database_manager.py:25-30` provides a `create_pool()` wrapper that registers
JSONB codecs (`_setup_codecs`) and emits `DB_POOL_SIZE` / `DB_POOL_IDLE` gauges on every
new pool. Three services call `asyncpg.create_pool()` directly, bypassing both.

Without JSONB codecs, asyncpg returns `dict` objects from `json.dumps`-encoded columns
instead of native Python dicts. In services that insert dicts into `jsonb` columns (e.g.
`signal_ai_enrichment.metadata`), this can cause double-serialization bugs silently —
`json.dumps(already_a_string)` produces `'"{\\"key\\": \\"value\\"}"'` in the database.

**Fix:**
Replace all three direct `asyncpg.create_pool(...)` calls with
`from src.core.database_manager import create_pool as create_db_pool`. One-line change per
file.

---

## Finding CR-6: `_batch_latency_attrs` Label Key Inconsistency Splits Grafana Aggregations

**Severity:** HIGH
**Category:** Information Destruction / Alpha Leakage

**Files:**
- `services/signal_writer_agent.py:78` — `{"agent_id": "signal_writer_agent"}`
- `services/lifecycle_writer_agent.py:97` — `{"agent_id": "lifecycle_writer_agent"}`
- `services/graduation_writer_agent.py:75` — `{"agent_id": "graduation_writer_agent"}`
- `services/llm_writer_service.py:457` — `{"agent_id": "llm_writer"}`
- `services/feature_writer_agent.py:276` — `{"agent_id": "feature_writer"}`
- `services/bar_writer_agent.py:118` — `{"agent": self.name}` (different key!)

**Description:**
`PERSISTENCE_BATCH_LATENCY` is the single histogram used for DB write latency across all
writer agents. Five writers label it with `agent_id`; `bar_writer_agent` labels it with
`agent`. This splits any cross-agent latency aggregation in Grafana: `{agent_id=~".*"}` will
miss bar writer's rows and vice versa. Any dashboard that attempts fleet-wide P95 write
latency is silently computing a partial answer.

This is alpha leakage: if pipeline write latency is degrading for bar_writer specifically,
a dashboard query using the wrong label key will not show it.

**Fix:**
`BaseWriterAgent.__init__` should initialize `self._batch_latency_attrs` automatically as
`{"agent_id": self.name.lower().replace(" ", "_")}`, removing per-subclass declaration.
Fix `bar_writer_agent` to use `agent_id` to align. This is one line in base class, four
deleted lines across subclasses.

---

## Finding CR-7: `setup_service_logging()` Called in `_setup()` After `super().__init__()` in Several Services

**Severity:** MEDIUM
**Category:** Complexity Drag

**Files:**
- `services/graduation_writer_agent.py:108` — called inside `_setup()`
- `services/swarm_ledger_writer_agent.py:83` — called inside `__init__` before `super()`
- `services/ml_orchestrator_agent.py:60` — called inside `_setup()`
- `services/ml_data_quality_agent.py:50` — called inside `__init__` before `super()`
- `services/ml_discovery_agent.py:67` — called inside `__init__` before `super()`
- `services/signal_replay_auditor_agent.py:479` (main entrypoint only — not a BaseAgent subclass)

**Description:**
`BaseAgent.__init__` (lines 105-111) auto-derives the log path from the agent name using
PascalCase-to-snake_case conversion and calls `setup_service_logging()` itself before
creating the logger. Services that call `setup_service_logging()` manually are either
redundant (the idempotency guard makes the second call a no-op) or — if called in `_setup()`
which runs after `__init__` — they are calling it after the logger is already created with
the auto-path, making the call permanently inert.

For `graduation_writer_agent`, the call in `_setup()` (not `__init__`) is permanently
inert because `BaseAgent.__init__` ran first. The log file IS correct (auto-derived
matches the manual string), but the code implies it has an effect it does not.

**Fix:**
Remove all manual `setup_service_logging()` calls from services that extend `BaseAgent`
or `BaseWriterAgent`. The auto-derivation in `BaseAgent` is authoritative. For non-BaseAgent
services (`signal_replay_auditor_agent`, `bar_replay_provider_agent`), calls in the
`main()` entrypoint are correct and should remain.

---

## Finding CR-8: `signal_replay_auditor_agent` and `bar_replay_provider_agent` Reinvent `BaseAgent` Lifecycle

**Severity:** HIGH
**Category:** Feedback Loop Gap / Complexity Drag

**Files:**
- `services/signal_replay_auditor_agent.py:55-80` — ad-hoc `_setup`, `_teardown`, `asyncio.Event`
- `services/bar_replay_provider_agent.py:40-75` — same pattern, no class hierarchy

**Description:**
Both classes define their own `_stop = asyncio.Event()`, `_setup()`, `_teardown()`, and
`_run()` outside any base class. They get none of: SIGTERM handling, OTel lifecycle,
systemd watchdog notifications, stall detection, setup retry, or DLQ routing.

For `signal_replay_auditor_agent` this matters for the feedback loop: if the auditor
stalls (e.g., pool exhaustion during a large backfill), there is no `max_idle_seconds`
watchdog to trigger systemd restart. A stalled replay auditor silently fails to backfill
lifecycle outcomes, degrading signal quality scoring without any alerting.

`bar_replay_provider_agent` uses `self._settings` instead of `self.settings` (the BaseAgent
convention), requiring a separate Settings construction.

**Fix:**
Both services should extend `BaseAgent`. `bar_replay_provider_agent` is a one-shot agent
(exits on completion) — implement as `BaseAgent` with `_run()` that calls `sys.exit(0)` on
completion. `signal_replay_auditor_agent` runs a periodic loop — maps cleanly to the
standard `_run()` loop pattern.

---

## Finding CR-9: `_health_monitor_loop` Has Four Distinct Implementations Across Services

**Severity:** MEDIUM
**Category:** Complexity Drag / Information Destruction

**Files and patterns:**
1. `services/feature_writer_agent.py:530` — full: uptime + counters + sleep + CancelledError
2. `services/llm_writer_service.py:996` — full: same but `add(uptime)` vs `.set(uptime)` (bug)
3. `services/intelligence_pipeline_agent.py:604` — stub: `while self.running: await asyncio.sleep(10)` with no body
4. `services/bar_aggregator_agent.py:590` — complex: `HealthMetrics.is_healthy()` circuit-breaker model with `_handle_unhealthy_state()`

**Description:**
There are four completely different conceptions of what a health monitor loop is. Variation 3
exists only to create a named task in `asyncio.create_task(self._health_monitor_loop())` for
structured cancellation — it does nothing. Variation 4 is the most sophisticated (and likely
the intended model) but has not been factored up.

The `HealthMetrics` dataclass in `bar_aggregator_agent.py:90-151` (tracking consecutive
errors, bars per minute, last bar timestamp) is exactly the kind of service-level health
model that belongs in a `BaseComputeAgent` mixin, not embedded in one service file.

**Fix:**
Define a `HealthSummary` dataclass in `src/core/agent/` with: `consecutive_errors`,
`messages_last_minute`, `last_message_ts`, `is_healthy() -> tuple[bool, str]`. Give
`BaseAgent` an optional `_health_summary: HealthSummary | None` field and a
`_health_monitor_loop()` default that reports it every 60s. Services that track per-bar
health replace their custom `HealthMetrics` with `_health_summary`.

---

## Finding CR-10: `isoformat()` Called Directly in 25 Places Instead of `format_iso_ts()`

**Severity:** HIGH
**Category:** Information Destruction / Alpha Leakage

**Files:** (representative sample - 25 total instances)
- `services/bar_replay_provider_agent.py:68,90,113`
- `services/signal_auditor_agent.py:239,240,248,249,250`
- `services/signal_metrics_compute_agent.py:223,325,345`
- `services/signal_tracker_compute_agent.py:965`
- `services/service_auditor_agent.py:756`
- `services/graduation_compute_agent.py:301`
- `services/signal_replay_auditor_agent.py:367,369,414`
- `services/bar_auditor_agent.py:583,584`
- `services/bar_aggregator_agent.py:478,493,605`

**Description:**
`format_iso_ts(dt)` in `service_utils.py:227-229` exists precisely to produce `Z`-suffixed
ISO-8601 strings for Kafka/JSON. The 25 raw `.isoformat()` calls produce `+00:00` suffix
instead of `Z`. These strings are consumed by `parse_iso_ts()` which handles both forms,
but downstream consumers that use naive `datetime.fromisoformat()` without the normalizer
will fail on Python < 3.11 where `fromisoformat` does not accept `Z`.

More critically, if any of these timestamps reach an external consumer (REST API, webhook,
Grafana annotation) that expects canonical ISO-8601, the inconsistency between `Z` and
`+00:00` produces divergent sort orders in some libraries.

**Fix:**
Global search-replace: `dt.isoformat()` → `format_iso_ts(dt)` where `dt` is a `datetime`
object. Add a ruff rule (`DTZ001` / custom) to flag raw `.isoformat()` on datetime objects
in the `services/` directory.

---

## Finding CR-11: `retry_utils.py` Module Unused by Services — Bar Aggregator and Signal Tracker Reinvent It

**Severity:** MEDIUM
**Category:** Complexity Drag

**Files:**
- `src/core/retry_utils.py` — `retry_with_backoff()` with jitter (used only by `src/core/llm/providers.py`)
- `services/bar_aggregator_agent.py:211-267` — manual loop, no jitter
- `services/signal_tracker_compute_agent.py:889-941` — manual loop with hand-coded backoff schedule

**Description:**
`retry_with_backoff()` exists in core and handles the general case cleanly. Zero services
import it directly. Two services manually implement equivalent logic without jitter. The
`signal_tracker` bootstrap uses a hardcoded tuple `_BOOTSTRAP_BACKOFF_SECONDS = (0.5, 1.0, 2.0, 5.0, 10.0)`,
which is a local constant rather than the standardized exponential schedule.

The absence of jitter matters: if multiple services restart simultaneously (e.g., after a
server reboot), they all hit the DB at `T+2s, T+4s, T+8s` in lockstep rather than
spreading load.

**Fix:**
Replace both manual loops with `retry_with_backoff(self._setup, ...)` or the base class
`_setup_with_retry()`. For `signal_tracker`'s bootstrap (which has domain-specific
all-empty check logic), wrap just the DB fetch call with `retry_with_backoff`.

---

## Finding CR-12: Structurally Near-Identical Writer Agent Pairs

**Severity:** MEDIUM
**Category:** Complexity Drag

**Files:**
- `services/signal_writer_agent.py` vs `services/lifecycle_writer_agent.py`
- `services/lineage_writer_agent.py` vs `services/graduation_writer_agent.py`

**Description:**
`signal_writer_agent` and `lifecycle_writer_agent` share an identical structure:
- `BaseWriterAgent` subclass
- `BATCH_SIZE = 100`, `FLUSH_INTERVAL_SECS = 5.0`, `MAX_BUFFER_SIZE = 10_000`
- `max_idle_seconds=300` in constructor
- `self._db: DatabaseManager | None`
- `self._consumer: KafkaConsumerClient | None`
- `self._repo: SignalLedgerRepository | None`
- `_setup()`: `DatabaseManager` init + `SignalLedgerRepository(self._db)` + `_create_consumer()`
- `_teardown()`: `super()._teardown()` + `consumer.stop()` + `db.close()`
- Three identical `counter()` metrics: events_consumed, written, write_errors

Both write to `signal_ledger` via `SignalLedgerRepository`. They differ only in topic,
consumer group, and `_flush_batch()` implementation (INSERT vs UPDATE).

`lineage_writer` and `graduation_writer` are similarly structural twins (both: `BaseWriterAgent`,
`DatabaseManager`, `_create_consumer()`, identical teardown).

**Fix:**
This pair does not need a new base class — the existing `BaseWriterAgent` + `SignalLedgerRepository`
already centralizes enough. The value here is standardizing the three boilerplate counters
(`events_consumed`, `rows_written`, `write_errors`) into `BaseWriterAgent` as
`_events_consumed_total`, `_rows_written_total`, `_write_errors_total`, auto-named from
`self.name`. Subclasses increment via inherited counters; specific metric names are
auto-derived. This eliminates ~12 lines of constructor boilerplate per writer.

---

## Finding CR-13: `src/core/retry_utils.py` Is Effectively Dead Code for Services

**Severity:** LOW
**Category:** Complexity Drag

**Files:**
- `src/core/retry_utils.py` — imported by one file: `src/core/llm/providers.py`
- Not imported by any of the 40 service files

**Description:**
`retry_utils` is named as a shared core utility but is only consumed internally by the LLM
provider chain. Given that two services have hand-rolled retry loops (see CR-1, CR-11), the
module exists in core without being discoverable to service authors.

**Fix:**
Either (a) document in `service_utils.py` that `retry_utils.retry_with_backoff` is the
standard for any ad-hoc retry needs, or (b) re-export it from `service_utils` as
`from src.core.retry_utils import retry_with_backoff as retry_with_backoff`. The `__all__`
export in `retry_utils` is already defined — it just needs a discovery path.

---

## Finding CR-14: Per-Service OTel Meter Instances (`_*_meter = _otel_metrics.get_meter("indicagent")`)

**Severity:** LOW
**Category:** Complexity Drag

**Files:**
- `services/bar_writer_agent.py:60` — `_bw_meter = _otel_metrics.get_meter("indicagent")`
- `services/bar_aggregator_agent.py:33` — `_baa_meter = _otel_metrics.get_meter("indicagent")`
- `services/contract_metadata_writer_agent.py:51` — `_cmw_meter`
- `services/bar_auditor_agent.py:79` — `_ba_meter`
- `services/roll_compute_agent.py:57` — `_rca_meter`
- `services/signal_metrics_compute_agent.py:47` — `_smc_meter`
- `services/signal_auditor_agent.py:40` — `_sa_meter`

**Description:**
Seven services import `from opentelemetry import metrics as _otel_metrics` and call
`get_meter("indicagent")` — the exact same thing `src/observability/metrics.py`'s `_meter`
does. These services bypass the central `counter()` / `gauge()` / `point_gauge()` factory
functions in `metrics.py` and call `create_counter()` directly on their local meter.

OTel's MeterProvider returns the same underlying meter for the same name in the same
process, so functionally there is no difference. But the pattern is inconsistent: some
services use `counter("name", "doc")` from `metrics.py` while others use
`_meter.create_counter("name", description="doc")` directly. This means `metrics.py`'s
deduplication cache in `base_writer.py`'s `_get_or_create_counter` is bypassed for
module-level instruments in these services — if they ever get instantiated twice in a test,
duplicate instrument registration errors will surface.

**Fix:**
Remove the per-service `_*_meter` imports. Use `from src.observability.metrics import counter, gauge`
for all new instruments. For existing module-level instruments in the seven affected services,
leave in place but add a comment noting they should migrate. Do not break existing Grafana
dashboard metric names.

---

## Summary Table

| Pattern | Instances | Impact | Recommended Home | Effort |
|---|---|---|---|---|
| Manual setup retry loop | `bar_aggregator_agent:203-267` | Thundering herd on restart | `BaseAgent.circuit_breaker = True` | XS |
| `_health_monitor_loop()` clone | `feature_writer`, `llm_writer`, `intelligence_pipeline` | Uptime gauge bug in llm_writer | `BaseWriterAgent._health_monitor_loop()` | S |
| Identical `_teardown()` boilerplate | 6 `BaseWriterAgent` subclasses | `ctx_writer` skips final flush silently | `BaseWriterAgent._teardown()` with hooks | S |
| `enable_auto_commit=True` writer | `swarm_ledger_writer_agent` | Permanent event loss on DB failure | Migrate to `BaseWriterAgent` | M |
| Direct `asyncpg.create_pool()` bypass | 3 services | Missing JSONB codecs, missing pool gauges | Use `database_manager.create_pool()` | XS |
| `_batch_latency_attrs` key mismatch | `bar_writer_agent` vs 5 others | Grafana aggregation silently incomplete | `BaseWriterAgent.__init__` default | XS |
| Redundant `setup_service_logging()` | 6 `BaseAgent` subclasses | Misleading dead code | Remove from subclasses | XS |
| Non-BaseAgent ad-hoc lifecycle | `signal_replay_auditor`, `bar_replay_provider` | No stall detection, no watchdog | Migrate to `BaseAgent` | M |
| 4 divergent health monitor designs | `bar_aggregator`, `feature_writer`, `llm_writer`, `intelligence_pipeline` | Health model inconsistency | `src/core/agent/health.py` mixin | L |
| Raw `.isoformat()` (25 instances) | 10 services | `+00:00` vs `Z` inconsistency | `format_iso_ts()` everywhere | S |
| `retry_utils` not used by services | `bar_aggregator`, `signal_tracker` | No jitter on startup retry | Document + re-export from `service_utils` | XS |
| Near-identical writer pairs | `signal_writer`/`lifecycle_writer`, `lineage`/`graduation` | Counter boilerplate drift | Standard counters in `BaseWriterAgent` | S |
| Per-service OTel meter instances | 7 services | Instrument cache bypass | `metrics.py` factory functions | XS |
| `retry_utils` dead code discovery | 0 of 40 services import it | Utility exists, nobody finds it | Re-export from `service_utils` | XS |

**Effort key:** XS = < 30 min, S = 30–90 min, M = 2–4 hr, L = half-day

**Priority order:**
1. CR-4 (CRITICAL: data loss on DB failure — `swarm_ledger_writer`)
2. CR-3 (`ctx_writer` skips final flush — silent data loss)
3. CR-5 (JSONB codec bypass — silent double-serialization)
4. CR-6 (metric label split — broken observability)
5. CR-10 (ISO timestamp inconsistency — 25 instances)
6. CR-1, CR-8, CR-11 (retry / lifecycle correctness)
7. CR-2, CR-9, CR-12, CR-14 (structural cleanup)
8. CR-7, CR-13 (cosmetic / discoverability)
