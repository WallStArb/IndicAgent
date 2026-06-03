# Architectural Weakness Assessment

**Version:** 1.0
**Status:** under-review
**Priority:** high
**Milestone:** v2.8
**Last Updated:** 2026-05-23
**Tags:** architecture, tech-debt, persistence, shadow-governance, telemetry, dag, hotfix, audit

---

## HOTFIX — Active Bugs Causing Data Loss or Incorrect Behavior RIGHT NOW

These are not design risks — they are production defects writing wrong data or silently discarding data today. Fix before any new feature work.

### HF-1: Shadow signals bypass live trading suppression (CRITICAL — Alpha Leakage)
Shadow plugins marked `is_shadow=TRUE` in `shadow_registry` can be selected as the winner signal and published to `topic_signals_aggregated`. The lifecycle tracker activates them as real trades. Shadow mode provides zero actual trade suppression.
- Root cause A: `is_shadow` is never stamped on signal dicts — `executor.py:697-710` post-processing loop omits the field, so `signal_writer_agent.py:201`'s `sig.get("is_shadow", False)` always returns `False`.
- Root cause B: `winner_selector.py` has no shadow-eligibility filter — shadow plugins compete for winner on equal footing.
- **Files:** `src/intelligence/pipeline/executor.py:697-710`, `src/intelligence/pipeline/signal_processor.py:421-433`, `src/intelligence/pipeline/winner_selector.py`
- **Fix:** In the post-processing loop add `sig["is_shadow"] = self._is_shadow(task.plugin_name, cache_snapshot.shadow_cache)`. Before `select_winner()`, filter: `eligible_ranked = [s for s in ranked if not cache_snapshot.shadow_cache.get(s.get("setup_plugin",""), False)]`.

### HF-2: `CtxWriterAgent` flush crashes silently — `.inc()` AttributeError empties no buffers (CRITICAL — Information Destruction)
OTel counter objects expose `.add()`, not `.inc()`. Two calls in `ctx_writer_agent.py:343,351` use `.inc(len(batch))`. This raises `AttributeError` inside `_flush()`, propagating to `_do_flush()`, which catches it and increments `_flush_errors_total` without clearing buffers. Every subsequent flush attempt re-fails. Buffers grow until `MAX_BUFFER_SIZE` overflows and oldest rows are dropped. CTX events that drive macro context are silently lost.
- Also affects `llm_writer_service.py:822` (i8 buffer never flushes).
- **Files:** `services/ctx_writer_agent.py:343,351`, `services/llm_writer_service.py:822`
- **Fix:** Replace `.inc(n)` with `.add(n)` at all three sites.

### HF-3: `LLMWriterAgent._pool` AttributeError swallows parse-success back-fills (CRITICAL — Information Destruction)
`_process_calls_message()` references `self._pool` (never initialized — only `self.db_manager` exists). Any `_parse_update` message raises `AttributeError`, caught silently by the outer `except Exception`. `parse_success` back-fills on `llm_calls` are permanently dropped. The LLM calibration feedback loop accumulates rows with incorrect NULL `parse_success`.
- **File:** `services/llm_writer_service.py:695`
- **Fix:** Replace `self._pool.acquire()` with `await self.db_manager.execute_command(_UPDATE_PARSE_SQL, call_id, parse_success)`.

### HF-4: `FeatureWriterAgent` ghost-run mode — DB connection failure silently disables all persistence (HIGH — Information Destruction)
`_connect_database()` catches all exceptions and sets `self.db_manager = None`. The service continues consuming Kafka and filling its buffer. After `MAX_BUFFER_SIZE=10,000` rows, oldest rows drop silently. Zero rows are written to `intelligence_features` — the primary feature hypertable. The service appears healthy. At ~160 rows/min this is the highest-volume data loss in the system.
- **File:** `services/feature_writer_agent.py:406-414`
- **Fix:** Raise in `_connect_database()` so systemd restarts the service. Add `feature_writer_db_connected` OTel gauge.

### HF-5: `SwarmLedgerWriterAgent` auto-commit — DB failure causes permanent event loss (CRITICAL — Information Destruction)
`enable_auto_commit=True` on the Kafka consumer advances offsets immediately on poll. If the DB write fails (network, pool exhaustion, PostgreSQL restart), the event is permanently lost — no replay, no DLQ. The service also silently swallows all exceptions with `logger.warning(...)` and has no DLQ, no error counter, and no offset management.
- **File:** `services/swarm_ledger_writer_agent.py:94-100`
- **Fix:** Set `enable_auto_commit=False`. Migrate to `BaseWriterAgent`. Wire DLQ.

### HF-6: `LLMWriterService` stall watchdog permanently disabled — `_last_msg_ts` never set (HIGH — Feedback Loop Gap)
The custom `_stall_watchdog()` reads `self._last_msg_ts` which is never assigned anywhere in the file. The `if self._last_msg_ts is None: continue` guard fires on every iteration — the watchdog is permanently in startup-grace mode and never fires. A stalled `indicagent-llm-writer` is invisible to the watchdog.
- **File:** `services/llm_writer_service.py:937-954`
- **Fix:** Replace `self._last_msg_ts` with `self._last_message_ts` (BaseAgent attribute); call `self._record_message_consumed()` inside `_process_loop()`.

### HF-7: `BarWriterAgent` stall detection blind — `_record_message_consumed()` never called (HIGH — Feedback Loop Gap)
`BarWriterAgent` overrides `_run()` but never calls `_record_message_consumed()`. The stall watchdog in `BaseAgent` reads `self._last_message_ts` which is only set by that method. A stalled bar-writer will not self-terminate and will not be detected by the service auditor.
- **File:** `services/bar_writer_agent.py:241-270`
- **Fix:** Add `self._record_message_consumed()` inside the `async for` loop at line 254.

### HF-8: Shadow governance metrics permanently incorrect — `up_down_counter` with absolute values (HIGH — Feedback Loop Gap)
Five shadow metrics (`SHADOW_WIN_RATE`, `SHADOW_N_RESOLVED`, `SHADOW_EV_R`, `SHADOW_DAYS_TO_GATE`, `SHADOW_EV_CI_LOWER`) are `create_up_down_counter`. Each audit cycle adds the current absolute value — after 10 cycles a plugin with `n=50` reads `500`. The shadow dashboard is permanently incorrect. This is a known OTel delta/cumulative anti-pattern.
- **File:** `src/observability/metrics.py:224-243`, `services/shadow_auditor_agent.py:170-194`
- **Fix:** Change all five to `create_gauge` and call `.set(value, attrs)` instead of `.add(value, attrs)`.

### HF-9: Three latency metrics use `up_down_counter` instead of `histogram` — p50/p95/p99 impossible (CRITICAL — Alpha Leakage)
`intelligence_pipeline_i1_latency_ms`, `intelligence_pipeline_i7_latency_ms`, and `intelligence_pipeline_pipeline_latency_ms` are all `up_down_counter` (via `gauge()`). An `up_down_counter` is a cumulative sum — it cannot produce percentiles. Latency data grows forever and you cannot alert on "p95 I7 latency > 50ms". Additionally, `_i1_latency_ms` and `_pipeline_latency` are declared but never called — the Grafana dashboard for pipeline latency shows flat zero permanently.
- **File:** `services/intelligence_pipeline_agent.py:180-191`
- **Fix:** Replace `gauge()` with `_meter.create_histogram()` for latency metrics and `_meter.create_counter()` for count metrics. Add `.record()` calls at the two dead sites.

### HF-10: `intelligence.i8` and `llm.outcomes` topics have no active publisher — subscriptions consuming void (HIGH — Information Destruction)
**STATUS: PARTIALLY FIXED 2026-06-03 (commit 3dada29f)**
`llm_writer_service` subscribes to `intelligence.i8` (i8 column in `intelligence_features` never populated) and `llm.outcomes` (LLM audit trail outcome back-fill permanently broken). Both topics have zero active publishers after a full codebase search.
- **Files:** `services/llm_writer_service.py:478-479`, `src/core/stream_keys.py:111,136`
- **Fix:** Identify intended publisher (likely `narrative_group_compute_agent` for i8; `signal_tracker_compute_agent` for outcomes) and add publish calls, or document these as deferred and remove dead subscriptions.
- **`llm.outcomes` FIXED:** `signal_tracker._publish_transition()` now publishes to `topic_llm_outcomes` on every `EXIT` transition.
- **`intelligence.i8` DEFERRED:** No qualitative tier built. Subscription stays; publisher deferred to Q-tier work.

### HF-11: `ctx_writer_agent` skips `super()._teardown()` — final buffer flush never runs on shutdown (HIGH — Information Destruction)
`ctx_writer_agent._teardown()` omits `super()._teardown()`. The final flush guard in `BaseWriterAgent._teardown()` is never called. Any buffered CTX records at shutdown time are lost with no warning.
- **File:** `services/ctx_writer_agent.py:376-387`
- **Fix:** Add `await super()._teardown()` at the start of `CtxWriterAgent._teardown()`.

---

## Existing Findings #1–#12 (Updated)

### #1. IntelligencePipelineComputeAgent — 1892-line god class (CRITICAL)

**File:** `services/intelligence_pipeline_agent.py`

**Intentional design (correct):** Unified in-process I1→I7 pipeline eliminates Kafka round-trips between tiers. This is the right trade-off for latency.

**Accidental complexity (fixable):** 9+ responsibilities, 44 mutable state dicts, signal gating/calibration/ranking, state checkpoint/restore, 6 async DB cache refresh loops, shadow governance, metrics, DLQ routing — all in one class.

**2026-05-23 update:** Confirmed by compute-latency audit (CL-1 through CL-12) and simplification audit. Three new findings amplify this: (a) `_health_monitor_loop` is an empty no-op stub (CL-11); (b) `CacheManager.snapshot()` copies four dicts on every bar even when nothing changed (CL-9); (c) `PluginStateManager.get_all_states_for()` is an O(N) scan that doubles cost at 116 symbols (simplification Section 1). The decomposition in the "Target decomposition" section below is the correct fix.

**Fix:** Extract `PluginExecutor`, `PluginStateManager`, `SignalProcessor`, `CacheManager`, `OutputQueue` as in-process classes sharing memory. No Kafka boundaries needed.

**Renaissance lens:** "One process" is the right call for latency. "One class" is accidental complexity.

---

### #2. Settings is a 1131-line god object (HIGH)

**File:** `src/config/settings.py`

Infrastructure config (Kafka URLs, DB connections) entangled with business logic (instrument definitions, LLM providers, Kalman params).

**2026-05-23 update:** Simplification audit identified 8 dead fields that can be deleted immediately with zero risk: `SWARM_QUEUE_TIMEOUT_MS` (deprecated, zero uses), `LLM_RATE_LIMIT_RPM`, `LLM_RATE_LIMIT_TPM` (orphaned, never read by runtime), `SHADOW_CORRELATION_THRESHOLD`, `SHADOW_MIN_SAMPLES` (zero uses), `LANGFUSE_HOST` (never implemented), `MLFLOW_TRACKING_URI` (bypassed by local constant in training agent). Also: `SemanticCache` ignores `LLM_SEMANTIC_CACHE_SIZE` setting — hardcoded to 500. Quick win: delete 8 dead fields now.

**Fix:** Delete 8 dead fields. Extract instrument definitions to DB or YAML. Settings should only be infra.

---

### #3. Signal ledger schema — 64-field accordion (HIGH)

**File:** `src/persistence/repository/signal_ledger_repository.py` (977 lines)

**2026-05-23 update:** Persistence audit confirms this pattern is widespread. Migration 094 adds `cis_score`, `bucket_scores`, `weights_version` correctly. The positional-tuple write pattern remains a maintenance hazard but commit `e58e0e87` resolved the immediate stale-column reference issue. No active data loss from this finding today.

**Fix:** Replace positional tuple with named params or asyncpg named parameter binding. Batch lifecycle updates.

---

### #4. AI layer has three dead/unfinished foundations (MEDIUM-HIGH)

**2026-05-23 update:** Simplification audit adds clarity:
- `ShadowRecorder` (`src/core/ml/shadow.py`) — zero production instantiations confirmed. Safe to delete now.
- `TransformRecorder` (`src/core/ml/transform_recorder.py`) — NOT dead. `intelligence_pipeline_agent.py:250` instantiates it live; 5 pipeline stages call it. `graduation_compute_agent.py` reads `signal_transform_log`. The "ARCHIVED" label is misleading — the migration to `LineageRecorder` is incomplete. There are now TWO parallel graduation mechanisms (see #33).
- `_on_guardrail_violation` and `_audit_payload` hooks — still no-ops; safe to delete. `_on_error` correctly emits metrics.
- `GuardrailsValidator` in `src/core/llm/guardrails.py` — zero schemas registered, dead branch in `chain.py` on every LLM call. Safe to delete (53 lines). v2.8 will replace with Guardrails AI.
- TEMPLATE agent (`src/intelligence/ai/TEMPLATE_agent.py:78`) calls `self._llm.generate()` directly, bypassing the mandatory `_llm_generate()` audit path. Every new agent copied from this template will inherit the violation.

**Fix:** Delete `ShadowRecorder`, `GuardrailsValidator`, `_on_guardrail_violation`, `_audit_payload`. Fix TEMPLATE. Resolve graduation ambiguity (see #33).

---

### #5. Output queue drops messages silently (MEDIUM → CRITICAL — confirmed active)

**2026-05-23 update:** Compute-latency audit (CL-3) confirms `_enqueue()` on the intelligence topic (line 507) is non-blocking with silent drop on `QueueFull`. Signal payloads use `enqueue_blocking` (correct) but `IntelligenceEvent` — the foundation of all feature storage — is fire-and-forget drop. Counter increments but no alert fires. This is an active data loss risk under Kafka lag.

**Fix:** Change line 507 to `await self._out_queue.enqueue_blocking(...)`. Apply same to journal enqueue at line 598.

---

### #6. Error handling: bare `except Exception` blocks (MEDIUM)

**2026-05-23 update:** Persistence audit confirms several active instances beyond the original finding. `SwarmLedgerWriterAgent` (HF-5 above) is the most severe. `LLMWriterService` (P-8) uses `auto_offset_reset="latest"` — a service restart loses all messages published during the outage window. Three services (`swarm_ledger_writer`, `bar_replay_provider`, `signal_replay_auditor`) bypass `BaseWriterAgent` entirely and have no DLQ, no offset management, and no error counting.

---

### #7. Global mutable state without thread protection (MEDIUM)

No change from original finding. Still unresolved.

---

### #8. Bootstrap retry pattern duplicated (MEDIUM)

**2026-05-23 update:** Code reuse audit (CR-1, CR-11) confirms and extends — now 3 independent retry implementations without jitter. `bar_aggregator_agent.py:203-267` (64-line manual loop) diverges in retry schedule from `BaseAgent._setup_with_retry()`, creating thundering-herd risk on restart.

**Fix:** Set `circuit_breaker = True` on `BarAggregatorComputeAgent`. Wire `BaseAgent._setup_with_retry()` with configurable class attributes.

---

### #9. `validate_signal()` exists but is never called (MEDIUM)

No change from original finding. Still unresolved.

---

### #10. Plugin circuit breaker under-utilized (MEDIUM)

**2026-05-23 update:** Compute-latency audit (CL-2) confirms `PluginCircuitBreaker` (584 lines) is wired only for LLM chain and IBKR. `PluginExecutor` uses the simpler `CircuitBreaker` with `circuit_breakers={}` — every breaker starts from zero on restart. A plugin timing out at 4500ms will not be detected by the 5000ms performance threshold that exists specifically for this case. On 12 active (symbol, tf) keys this adds ~54s of accumulated latency per bar cycle.

---

### #11. Intelligence pipeline checkpoint write swallowed (MEDIUM)

**2026-05-23 update:** Simplification audit confirms checkpoint `write_checkpoint()` calls `Path.write_text()` synchronously in the async loop (not in `asyncio.to_thread()`). At 116 symbols, the checkpoint payload doubles. GARCH/Kalman states require array-to-list conversion. The 5-minute checkpoint write can block the asyncio loop on large symbol sets.

**Fix:** Re-raise on checkpoint write failure. Wrap `write_checkpoint()` in `asyncio.to_thread()` to prevent event loop blocking.

---

### #12. Dashboard has no React error boundaries (LOW-MEDIUM)

No change from original finding. Still unresolved.

---

## New Findings #13–#36 (Added 2026-05-23)

### #13. All 37 service files have zero OTel span coverage (CRITICAL — P3 Feedback Loop Gap)

**Severity:** CRITICAL
**Renaissance:** P3
**Files:** All 37 `services/*.py` files; `src/observability/spans.py:23`

No service file contains any `start_as_current_span` or `observed_span` call. Span instrumentation exists only in base classes and three `src/` modules. The `observed_span()` docstring says "For use only in the two pipeline span sites in `intelligence_pipeline_agent.py`" — those two sites do not exist. The entire critical path — bar ingestion, I1-I7 execution, signal processing, DB persistence — has no distributed traces.

**Fix:** Add `observed_span("pipeline.process_bar_inner")` wrapping `_process_bar_inner()` as minimum viable entry point. Add `observed_span("feature_pipeline.run")` in `FeaturePipelineExecutor`.

---

### #14. Per-stage latency (I2-I6) completely absent — 6 pipeline stages dark (HIGH — P1 Alpha Leakage + P3)
**STATUS: FIXED 2026-06-03 (commit 3dada29f)**

**Severity:** HIGH
**Renaissance:** P1, P3
**Files:** `services/intelligence_pipeline_agent.py:180-184`, `src/intelligence/pipeline/feature_pipeline_executor.py`

Only end-to-end and I7 latency are measured. I1 gauge is declared but never called (dead instrument). I2, I3, I4, I5, SMC, I6 — 68 plugins across 6 tiers — have no per-stage aggregate. A new I4 plugin causing a 30ms regression has no directly alertable metric. Per-plugin histogram via `PluginObserver` exists but there is no per-tier roll-up for fast triage.

**Fix:** `_timed_tier` wrapper in `executor.py run_tiers()` records `intelligence_pipeline_tier_latency_ms{tier=X}` for each individual tier. All 6 tiers (i2, i3, i4, i5, smc, i6) now emit per-tier latency histograms.

---

### #15. Three services bypass `DatabaseManager.create_pool()` — missing JSONB codecs and pool gauges (HIGH — P2 Information Destruction)

**Severity:** HIGH
**Renaissance:** P2
**Files:** `services/swarm_ledger_writer_agent.py:89-92`, `services/bar_replay_provider_agent.py:60`, `services/signal_replay_auditor_agent.py:69`

`DatabaseManager.create_pool()` registers JSONB codecs and emits `DB_POOL_SIZE`/`DB_POOL_IDLE` gauges. Three services call `asyncpg.create_pool()` directly. Without JSONB codecs, asyncpg may double-serialize dict values into `jsonb` columns — `json.dumps(already_a_string)` produces escaped strings in the database silently.

**Fix:** Replace all three direct `asyncpg.create_pool()` calls with `from src.core.database_manager import create_pool as create_db_pool`.

---

### #16. `signal_replay_auditor_agent` and `bar_replay_provider_agent` reinvent BaseAgent lifecycle (HIGH — P3 Feedback Loop Gap)

**Severity:** HIGH
**Renaissance:** P3
**Files:** `services/signal_replay_auditor_agent.py:55-80`, `services/bar_replay_provider_agent.py:40-75`

Both define their own `_stop = asyncio.Event()`, `_setup()`, `_teardown()`, `_run()` outside any base class. They get none of: SIGTERM handling, OTel lifecycle, systemd watchdog notifications, stall detection, setup retry, or DLQ routing. A stalled `signal_replay_auditor` silently fails to backfill lifecycle outcomes, degrading signal quality scoring.

**Fix:** Migrate both to `BaseAgent`. `bar_replay_provider_agent` exits on completion via `sys.exit(0)` from `_run()`.

---

### #17. `intelligence-pipeline` systemd `After=` references non-existent unit (CRITICAL — P3 Feedback Loop Gap)

**Severity:** CRITICAL
**Renaissance:** P3
**File:** `production/systemd/indicagent-intelligence-pipeline.service:3`

`After=indicagent-bar-aggregator-compute.service` — this unit does not exist. The real unit is `indicagent-bar-aggregator.service`. systemd silently treats unknown `After=` references as already-satisfied. On cold boot, the intelligence pipeline starts without waiting for bar-aggregator, processing bars against partially-seeded feature windows before HTF bars arrive.

**Fix:** Change `After=` line to reference `indicagent-bar-aggregator.service`. Also add `After=indicagent-cross-asset.service indicagent-macro-compute.service`.

---

### #18. `_DAG_ORDER` missing 11 deployed services — ML batch failures invisible (HIGH — P3 Feedback Loop Gap)

**Severity:** HIGH
**Renaissance:** P3
**File:** `services/service_auditor_agent.py:55-96`

Eleven services with active systemd units are absent from `_DAG_ORDER`: `shadow-auditor`, `weight-updater`, `ml-orchestrator`, `ml-data-quality`, `ml-discovery`, `hmm-training`, `feature-validation`, `api`, `dashboard`, `redpanda-ready`, `redpanda-watchdog`. If `ml-orchestrator` hits `StartLimitHit`, the auditor never sees it and never resets it.

**Fix:** Add all 11 to `_DAG_ORDER` with appropriate priority levels (oneshot batch at L8; api/dashboard at L10; infra units as non-restartable sentinels).

---

### #19. `feature_writer` agent ID mismatch breaks Kafka lag monitoring (HIGH — P3 Feedback Loop Gap)

**Severity:** HIGH
**Renaissance:** P3
**File:** `services/service_auditor_agent.py:131`, `services/feature_writer_agent.py:239-240`

`_AGENT_ID_TO_UNIT` maps `"feature_writer"` to the unit, but `FeatureWriterAgent` registers itself as `"feature_writer_agent"`. The `PERSISTENCE_CONSUMER_LAG` metric is labeled `agent_id="feature_writer_agent"` while the auditor queries for `agent_id="feature_writer"`. Feature-writer — the primary `intelligence_features` hypertable writer — can accumulate unbounded consumer lag with no alert.

**Fix:** Change the key in `_AGENT_ID_TO_UNIT` from `"feature_writer"` to `"feature_writer_agent"`.

---

### #20. Cyclic L5 dependency — cross-asset and intelligence-pipeline at same DAG priority (HIGH — P3 Feedback Loop Gap)

**Severity:** HIGH
**Renaissance:** P3
**Files:** `services/cross_asset_service.py:173`, `services/intelligence_pipeline_agent.py:219`, `services/service_auditor_agent.py:64-66`

`cross_asset` subscribes to `topic_intelligence` (from pipeline) and `intelligence_pipeline` subscribes to `topic_cross_asset` (from cross-asset). Both are at DAG priority 5. On dual-failure recovery, restart order is undefined. Pipeline starting before cross-asset processes first bars with an empty cross-asset cache.

**Fix:** Set `indicagent-cross-asset` and `indicagent-macro-compute` to priority 5, `indicagent-intelligence-pipeline` to priority 6. Add `After=indicagent-cross-asset.service indicagent-macro-compute.service` to pipeline unit.

---

### #21. `alerting-agent` and `dlq-drain` declare dependency on non-existent `redpanda.service` (HIGH — P3 Feedback Loop Gap) - RESOLVED

**Severity:** HIGH
**Renaissance:** P3
**Files:** `production/systemd/indicagent-alerting-agent.service:3`, `production/systemd/indicagent-dlq-drain.service:3`

`After=redpanda.service` — Redpanda runs in Docker, not systemd. The dependency is silently ignored. On cold start, alerting-agent and dlq-drain may start before Redpanda accepts connections, causing their Kafka consumers to fail initial connection and backoff. During that window, DLQ events accumulate unread and alerts are not dispatched.

**Fix:** Replace `redpanda.service` with `indicagent-redpanda-ready.service` and add `Requires=indicagent-redpanda-ready.service`.

**Resolution (quick task 260528-806, 2026-05-28):** Introduced `indicagent-timescaledb-ready.service` and `indicagent-infrastructure.target`. All 40 app services (including alerting-agent and dlq-drain) now `Requires=indicagent-infrastructure.target`, which gates on both `indicagent-timescaledb-ready` and `indicagent-redpanda-ready` exiting cleanly. The broken `redpanda.service` dependency is superseded by the unified target.

---

### #22. Shadow promotion/demotion gates train on all signals including shadow — contaminated statistics (HIGH — P2+P3)

**Severity:** HIGH
**Renaissance:** P2, P3
**Files:** `services/shadow_auditor_agent.py:115-124`, `services/shadow_auditor_agent.py:256-265`

Both `_check_promotion()` and `_check_demotion()` query `signal_ledger` without `AND is_shadow = FALSE`. Because HF-1 means all signals currently have `is_shadow=FALSE`, this is a no-op today. But if HF-1 is fixed without fixing these queries, shadow observations immediately contaminate the live-track statistics. Promotion `n` deflates; EV[R] is diluted by shadow performance.

**Fix:** Add `AND is_shadow = FALSE` to both queries. Also add `AND pnl_r IS NOT NULL` to the demotion query — a plugin with null PnL (rarely filled instruments) can never be demoted.

---

### #23. Swarm agent shadow governance is structurally dead — auditor always sees n=0 (HIGH — P3 Feedback Loop Gap)

**Severity:** HIGH
**Renaissance:** P3
**Files:** `services/shadow_auditor_agent.py:115-124,256-265`, `src/core/ai/base_group_service.py:162-164`

Shadow auditor queries `signal_ledger WHERE setup_plugin = $1` using swarm agent IDs (`"correlation_v1"`, etc.). Swarm agents have no rows in `signal_ledger` under those IDs — they modify multipliers, not setup_plugin rows. Every auditor cycle finds `n=0` for all 5 swarm agents. Promotion always fails; demotion resets to 0. Swarm agents are permanently stuck in enrolled `is_shadow=TRUE` state (though `alpha_swarm_agent._evaluate_agent()` governs them separately via Spearman-rho, that path is independent and the auditor's interference neutralizes it).

**Fix:** Add a component-type branch in `_run_audit()` to skip `signal_ledger` lookups for `component_type='swarm_agent'` rows.

---

### #24. `"agent"` vs `"agent_id"` metric label key inconsistency across 83 emission sites (HIGH — P3 Feedback Loop Gap)

**Severity:** HIGH
**Renaissance:** P3
**Files:** `src/core/agent/base.py:120,136`, `services/bar_writer_agent.py:117-120`, five writer services

`BaseAgent` uses `{"agent": name}` for crash and heartbeat metrics. `BaseWriterAgent` uses `{"agent_id": ...}` for persistence metrics. `bar_writer_agent` uses `{"agent": self.name}` for its own histogram. `service_auditor_agent` queries `agent_id`. Cross-agent fleet-wide dashboards are impossible to build correctly. Any dashboard computing fleet-wide P95 write latency silently computes a partial answer missing bar-writer.

**Fix:** Standardize on `"agent_id"` everywhere. Move `_batch_latency_attrs` initialization into `BaseWriterAgent.__init__` as `{"agent_id": self.name.lower()}` to eliminate per-subclass declaration. Update Grafana queries.

---

### #25. `TransformRecorder` archived but still active on hot path — 4-5 async DB writes per signal per bar (HIGH — P1 Alpha Leakage)
**STATUS: FIXED 2026-06-03 (commit 3dada29f)**

**Severity:** HIGH
**Renaissance:** P1
**Files:** `services/intelligence_pipeline.py` (was `intelligence_pipeline_agent.py`), `src/core/ml/transform_recorder.py:1`

Module header says "ARCHIVED in Phase 78 (D-04). Do NOT import." It emits `DeprecationWarning` at import. Yet `_setup()` instantiated it live and passed it to `SignalProcessor`, which routed it through all 5 pipeline stages.

**Fix applied:** `recorder=None` passed to `SignalProcessor`; teardown flush block removed. The `if recorder is not None` guards in `signal_processor.py` prevent any calls. `graduation_analyzer` still reads historical `signal_transform_log` data — see #33 for migration plan.

---

### #26. `PluginStateManager.get_all_states_for()` is O(N) scan — quadratic scaling cliff at 116 symbols (HIGH — P1 Alpha Leakage)

**Severity:** HIGH
**Renaissance:** P1
**Files:** `src/intelligence/pipeline/state_manager.py:91-102`, `src/intelligence/pipeline/feature_pipeline_executor.py:200`

`get_all_states_for()` scans all `_plugin_states` entries to filter by `(symbol, tf)`. At 58 symbols with 6 TFs and 132 plugins = ~45,936 entries scanned per bar call. At 116 symbols this doubles to ~91,872. With concurrent per-key workers, this scan runs thousands of times per minute. This is the dominant hot-path cost as symbol count doubles.

**Fix:** Index `_plugin_states` with a secondary lookup `dict[(symbol, tf), dict[str, dict]]`. `get_all_states_for()` becomes O(1). Required before scaling to 116 symbols.

---

### #27. `LLMWriterService` uses `auto_offset_reset="latest"` — restart loses all messages during outage window (MEDIUM — P2 Information Destruction)

**Severity:** MEDIUM
**Renaissance:** P2
**File:** `services/llm_writer_service.py:568`

All other writer agents use `"earliest"`. A crash or restart skips all messages published during the downtime. LLM audit records and outcome back-fills are permanently lost. `llm_calls` accumulates gaps. `llm_model_scores` trains on incomplete data.

**Fix:** Change to `auto_offset_reset="earliest"`. Idempotency is already guaranteed by `ON CONFLICT (call_id, called_at) DO NOTHING`.

---

### #28. `roll_compute` misclassified at DAG priority 8 — delays front-month promotion after outage (MEDIUM — P1 Alpha Leakage)

**Severity:** MEDIUM
**Renaissance:** P1
**Files:** `services/service_auditor_agent.py:84`, `services/roll_compute_agent.py:377-382`

`roll_compute_agent` subscribes to `topic_market_bars` (published by `provider_merger` at priority 2) but is placed at DAG priority 8. If a futures roll event occurred during an outage, `roll_compute` will not process it until all priority 1-7 services are healthy — potentially minutes after bars are flowing. During that window the pipeline processes bars for a stale contract.

**Fix:** Move `indicagent-roll-compute` to priority 3 in `_DAG_ORDER`.

---

### #29. `signal_metrics_writer` DLQ topic undiscoverable and not drained (LOW — P2 Information Destruction)

**Severity:** LOW
**Renaissance:** P2
**Files:** `services/signal_metrics_writer_agent.py:244-245`, `services/dlq_drain_agent.py`

`_dlq_topic()` returns `{env}.intelligence.signal_metrics.dlq` — not defined in `stream_keys.py` and not in `dlq_drain_agent`'s subscription list. Failed signal_metrics write events accumulate in an unmonitored, undrained topic. There are no alerts on it.

**Fix:** Add `topic_signal_metrics_writer_dlq()` to `stream_keys.py`. Add to `dlq_drain_agent`'s subscription list.

---

### #30. `bar_replay` has no `Conflicts=ibkr-provider` guard — simultaneous publish corrupts bar stream (MEDIUM — P2 Information Destruction)

**Severity:** MEDIUM
**Renaissance:** P2
**File:** `production/systemd/indicagent-bar-replay.service`

`bar_replay_provider_agent` publishes to `topic_market_bars` and `topic_market_bars_htf` simultaneously with `ibkr-provider`. If both run at the same time, the intelligence pipeline sees bars from two sources in the same Kafka partition sequence as legitimate data.

**Fix:** Add `Conflicts=indicagent-ibkr-provider.service` to the bar-replay unit.

---

### #31. `_health_monitor_loop` variants — 4 divergent implementations across services (MEDIUM — P4 Complexity Drag)

**Severity:** MEDIUM
**Renaissance:** P4
**Files:** `services/feature_writer_agent.py:530`, `services/llm_writer_service.py:996`, `services/intelligence_pipeline_agent.py:604`, `services/bar_aggregator_agent.py:590`

Four completely different conceptions: full with correct `.set()`, full with wrong `.add()` (LLM writer accumulates uptime forever), empty no-op stub (pipeline), sophisticated `HealthMetrics` circuit-breaker model (aggregator — the most correct but siloed). Also: `_health_monitor_loop` in `intelligence_pipeline_agent` has an empty body (`while self.running: await asyncio.sleep(10)`) — all slots for health monitoring are unused.

**Fix:** Absorb `_health_monitor_loop()` into `BaseWriterAgent`. The `HealthMetrics` pattern in `bar_aggregator_agent` is the intended model; factor it up to a `HealthSummary` dataclass in `src/core/agent/`.

---

### #32. 25 raw `.isoformat()` calls produce `+00:00` instead of canonical `Z` suffix (MEDIUM — P2 Information Destruction)
**STATUS: PARTIALLY FIXED 2026-06-03 (commit 3dada29f)**

**Severity:** MEDIUM
**Renaissance:** P2
**Files:** 10 service files including `bar_replay_provider_agent.py`, `signal_auditor_agent.py`, `signal_metrics_compute_agent.py`, `signal_tracker_compute_agent.py`, `service_auditor_agent.py`, others

`format_iso_ts(dt)` exists in `service_utils.py` to produce `Z`-suffix strings for Kafka/JSON. 25 raw `.isoformat()` calls produce `+00:00`. External consumers using naive `datetime.fromisoformat()` on Python < 3.11 will fail. Downstream sort order can diverge in some libraries.

**Kafka-path calls fixed:** `lifecycle_transitions.py` `to_dict()`/`_json_safe()`, `bar_replay_provider._publish_bar()`, `signal_replay_auditor` transition payloads now use `format_iso_ts()`.
**Remaining:** Log-only and checkpoint calls (`bar_aggregator`, `signal_auditor`, `service_auditor`, `bar_replay_provider` checkpoint, `bar_accumulator`) — low risk, left as-is. Add a ruff rule to prevent regressions.

---

### #33. Dual graduation mechanisms — `signal_transform_log` vs `signal_lineage` — architectural ambiguity (MEDIUM — P4 Complexity Drag)

**Severity:** MEDIUM
**Renaissance:** P4
**Files:** `services/graduation_compute_agent.py`, `src/intelligence/swarm/graduation.py`, `src/core/ai/base_group_service.py:282`, `services/alpha_swarm_agent.py`

Two parallel graduation systems: (1) `graduation_compute_agent` reads `signal_transform_log` (written by archived `TransformRecorder`) to evaluate `transform_graduation`; (2) `alpha_swarm_agent._graduation_loop` runs Spearman weight learning directly against `swarm_agent_weights`. If `TransformRecorder` is removed (#25), graduation_compute_agent breaks. If it's kept, an archived module feeds a live service. The canonical graduation path is undocumented.

**Fix:** Document which path is canonical before v2.8 adds more agents. If the swarm loop supersedes graduation_compute, migrate graduation_compute to use `signal_lineage` and remove `TransformRecorder`. If both serve different purposes (plugin-level vs agent-level graduation), document explicitly.

---

### #34. `otel.py` silently suppresses all OTel initialization errors — entire deployment runs dark (MEDIUM — P3 Feedback Loop Gap)
**STATUS: FIXED 2026-06-03 (commit 3dada29f)**

**Severity:** MEDIUM
**Renaissance:** P3
**File:** `src/observability/otel.py:49-50,63-64`

Both `MeterProvider` and `TracerProvider` initialization errors are caught with bare `except Exception: pass`. A misconfigured `OTEL_EXPORTER_OTLP_ENDPOINT` causes all production metrics to be silently discarded with no log warning, no counter, and no startup alert. Agents proceed with no-op providers believing they are observable.

**Fix applied:** Both except blocks now emit `_log.warning("otel.meter_provider_init_failed ...")` / `_log.warning("otel.tracer_provider_init_failed ...")` with endpoint and error string.

---

### #35. LLM provider coupling — adding LiteLLM requires touching every agent constructor (MEDIUM — P4 Complexity Drag)

**Severity:** MEDIUM
**Renaissance:** P4
**Files:** `src/intelligence/ai/alpha/skeptic_agent.py:57`, 4 other agent files, `src/core/ai/base_group_service.py:130`

Every agent constructor hardcodes `llm_chain: LLMProviderChain`. Replacing with LiteLLM for v2.8 means touching 5 agent files plus the group service constructor, chain wiring, and tests. `SemanticCache`, `rate_limiter`, and `token_budget` also duplicate functionality LiteLLM provides natively.

**Fix (before v2.8):** Move `_llm` from agent constructor injection to a late-binding accessor on `BaseAIAgent` — agents call `self._get_llm()` from the group service. Declare `self._llm: LLMProviderChain | None = None` in `BaseAIAgent.__init__` with a guard in `_llm_generate()` to surface un-wired agents at construction time.

---

### #36. `PluginStateManager` checkpoint write is synchronous — blocks asyncio event loop at 116+ symbols (MEDIUM — P1 Alpha Leakage)

**Severity:** MEDIUM
**Renaissance:** P1
**File:** `src/intelligence/pipeline/state_manager.py:141`

`write_checkpoint()` calls `Path.write_text()` synchronously in the async context. At current symbol count (58 symbols × 6 TFs × 132 plugins), the checkpoint write is tolerable every 5 minutes. At 116 symbols with GARCH/Kalman states requiring array-to-list conversion, this write can block the event loop. Checkpoint path is also hardcoded (`cache/pipeline_checkpoint.json`) — incompatible with multi-shard deployments.

**Fix:** Wrap `write_checkpoint()` in `asyncio.to_thread()`. Make path a `Settings` field (`PIPELINE_CHECKPOINT_PATH`).

---

## What's Actually Solid (Do Not Refactor)

These are well-designed and working.

- **Plugin system** — registry + tier validation + frozen outputs. 132 plugins across 7 tiers, validated at startup. Single source of truth in `register_plugins.py`.
- **Typed bus** — `IntelligenceEvent` with Pydantic schemas. Strong type safety across I1-I7. `model_validate` catches schema drift at deserialization boundaries.
- **BaseAIAgent compute wrapper** — timing capture, `asyncio.wait_for` timeout, neutral fallback on error, OTel metrics. Clean template pattern.
- **Signal lifecycle state machine** — `lifecycle_tracker.py` is pure functions. Well-tested, no side effects, no DB access.
- **Aggregator logic** — CIS scoring + regime gating + co-fire detection. `_build_all_ranked()` with perf weights, alpha decay, calibration. Complex but correct.
- **Kafka isolation** — all topics via `stream_keys.py`. Zero hardcoded topic strings. Environment prefix handled centrally.
- **`PluginObserver` per-plugin histograms** — `PLUGIN_DURATION_MS` is correctly a histogram with `{plugin_name, tier}` labels. Per-plugin latency visibility is solid.
- **`BaseWriterAgent` flush/commit/DLQ machinery** — for the services that use it correctly. Offset commit on successful flush, DLQ routing, buffer depth tracking.
- **`_SIGNAL_REPLAY_UNRESOLVED_GAUGE` delta pattern** — correctly computes delta and calls `.add()`. Previous OTel delta bug is fixed here.

---

## Overlap with Existing Ideas

| Finding | Existing Idea | Delta |
|---------|--------------|-------|
| #1 Pipeline god class | "Parallel DAG execution" (#21) | Different scope — #21 is within-tier parallelism; #1 is class decomposition |
| #5 Queue drops | "Backpressure & autoscaling" (#23) | Finding #5 / CL-3 confirms it's an active data loss risk, not theoretical |
| #6 Bare excepts | "Service resilience patterns" (#20) | Finding #6 is the concrete symptom; #20 is the broader pattern |
| #2 Settings god object | No existing idea | New |
| #3 64-field ledger tuple | No existing idea | New |
| #4 Dead AI foundations | No existing idea | New |
| #7 Unprotected global state | No existing idea | New |
| #10 Plugin circuit breaker | "Latency and persistence audit" | CL-2 confirms the 5000ms performance threshold exists and is unused |
| #26 O(N) state scan | No existing idea | New — scaling cliff at 116 symbols |

---

## Renaissance-Ranked Backlog (P1 → P4)

### P1 — Alpha Leakage (latency, throughput, signal quality degradation)

| # | Finding | Severity |
|---|---------|----------|
| HF-1 | Shadow signals trade live — winner suppression missing | CRITICAL |
| HF-9 | Latency metrics are `up_down_counter` — p50/p95 impossible | CRITICAL |
| #5/CL-3 | Intelligence topic drops silently on QueueFull | CRITICAL |
| #26 | `PluginStateManager.get_all_states_for()` O(N) scan — quadratic at 116 symbols | HIGH |
| ~~#25~~ | ~~`TransformRecorder` archived but live on hot path — 4-5 async writes/signal~~ | ~~HIGH~~ FIXED 2026-06-03 |
| ~~#14~~ | ~~Per-stage latency (I2-I6) completely absent~~ | ~~HIGH~~ FIXED 2026-06-03 |
| #10/CL-2 | `PluginCircuitBreaker` unused on plugin path — 4500ms plugins uncaught | MEDIUM |
| #28 | `roll_compute` at priority 8 despite needing priority-2 data — stale contract after outage | MEDIUM |
| #32 | 25 raw `.isoformat()` calls — Kafka paths fixed; log/checkpoint calls remain | MEDIUM (partial) |
| #36 | Checkpoint write synchronous — blocks asyncio event loop at 116+ symbols | MEDIUM |
| #35 | LLM provider coupling — LiteLLM swap touches every agent file | MEDIUM |

### P2 — Information Destruction (silent failures, data loss, swallowed errors, dropped events)

| # | Finding | Severity |
|---|---------|----------|
| HF-2 | `CtxWriterAgent` `.inc()` AttributeError — buffers never flush, CTX records lost | CRITICAL |
| HF-3 | `LLMWriterAgent._pool` AttributeError — parse-success back-fills silently dropped | CRITICAL |
| HF-5 | `SwarmLedgerWriterAgent` auto-commit — DB failure = permanent event loss | CRITICAL |
| HF-4 | `FeatureWriterAgent` ghost-run — DB failure silently disables all feature persistence | HIGH |
| ~~HF-10~~ | ~~`intelligence.i8` and `llm.outcomes` topics have no publisher~~ | `llm.outcomes` FIXED 2026-06-03; `i8` DEFERRED |
| HF-11 | `CtxWriterAgent` skips `super()._teardown()` — final flush on shutdown never runs | HIGH |
| #15 | Three services bypass `create_pool()` — missing JSONB codecs, silent double-serialization | HIGH |
| #22 | Shadow promotion/demotion trains on all signals including shadow | HIGH |
| #27 | `LLMWriterService` `auto_offset_reset="latest"` — restart loses all messages during outage | MEDIUM |
| #30 | `bar_replay` no `Conflicts=ibkr-provider` — simultaneous publish corrupts bar stream | MEDIUM |
| #29 | `signal_metrics_writer` DLQ undiscoverable and not drained | LOW |

### P3 — Feedback Loop Gap (missing observability, undetectable failures, broken monitoring)

| # | Finding | Severity |
|---|---------|----------|
| HF-6 | `LLMWriterService` stall watchdog permanently disabled | HIGH |
| HF-7 | `BarWriterAgent` stall detection blind — `_record_message_consumed()` never called | HIGH |
| HF-8 | Shadow governance metrics permanently incorrect — `up_down_counter` with absolute values | HIGH |
| #13 | All 37 services have zero OTel span coverage | CRITICAL |
| #17 | `intelligence-pipeline` systemd `After=` references non-existent unit | CRITICAL |
| #18 | `_DAG_ORDER` missing 11 deployed services | HIGH |
| #19 | `feature_writer` agent ID mismatch breaks Kafka lag monitoring | HIGH |
| #20 | Cyclic L5 dependency — restart order undefined after dual failure | HIGH |
| #21 | `alerting-agent` and `dlq-drain` declare broken `redpanda.service` dependency | HIGH - RESOLVED (260528-806) |
| #23 | Swarm agent shadow governance structurally dead — auditor always sees n=0 | HIGH |
| #24 | `"agent"` vs `"agent_id"` metric label split — cross-agent dashboards broken | HIGH |
| #16 | `signal_replay_auditor` and `bar_replay_provider` reinvent BaseAgent lifecycle | HIGH |
| ~~#34~~ | ~~`otel.py` silently suppresses all OTel init errors — deployment runs dark~~ | ~~MEDIUM~~ FIXED 2026-06-03 |
| #31 | 4 divergent `_health_monitor_loop` implementations | MEDIUM |
| #9 | `validate_signal()` exists but never called — I7 output boundary unguarded | MEDIUM |

### P4 — Complexity Drag (abstraction overhead, dead code, copy-paste surface)

| # | Finding | Severity |
|---|---------|----------|
| #4 | Dead AI foundations: `ShadowRecorder`, `GuardrailsValidator`, no-op hooks, TEMPLATE bug | MEDIUM |
| #2 | Settings god object with 8 dead fields | HIGH |
| #33 | Dual graduation mechanisms — architectural ambiguity | MEDIUM |
| #31 | Divergent health monitor implementations | MEDIUM |
| #8/CR-11 | Bootstrap retry pattern duplicated 3x without jitter | MEDIUM |
| #1 | Pipeline god class — accidental complexity | CRITICAL |

---

## v2.8 Readiness

v2.8 milestone: AI platform phases 094-099 (LiteLLM, DSPy, Zep memory, evolvable agents), 101-103 (evolvable agents).

### Do Before v2.8 Starts

These are structural blockers that will make v2.8 phases harder or unsafe to execute without them:

1. **Fix all HOTFIX items (HF-1 through HF-11)** — shadow signals trading live and multiple data-loss bugs must be resolved before adding more AI agents that interact with the same pipelines.
2. **Fix `intelligence-pipeline` systemd `After=` (#17)** — wrong unit reference means cold-boot behavior is undefined. Fix before adding v2.8 services.
3. **Add `_DAG_ORDER` entries for 11 missing services (#18)** — ML batch service failures (ml-orchestrator, ml-data-quality, ml-discovery) go undetected. v2.8 adds more ML services.
4. **Index `PluginStateManager._plugin_states` by `(symbol, tf)` (#26)** — O(N) scan doubles cost at 116 symbols. v2.8 adds more agents and symbols; this becomes the dominant CPU cost.
5. **Move `_llm` from agent constructors to late-binding accessor on `BaseAIAgent` (#35)** — LiteLLM integration (v2.8 phase 1) touches every agent file without this refactor. One-time 2-3 hour fix that makes the entire v2.8 AI layer a 1-file change.
6. **Resolve graduation architecture ambiguity (#33)** — if v2.8 adds evolvable agents with their own graduation, having two parallel graduation systems creates a third.
7. **Fix `feature_writer` agent ID mismatch (#19)** — Kafka lag monitoring for the primary feature persistence layer is dark. v2.8 increases feature write volume.

### Do During v2.8

These can be addressed as part of v2.8 milestone phases without blocking start:

1. **LiteLLM integration replaces `providers.py`, `chain.py`, `semantic_cache.py`, `rate_limiter.py`, `token_budget.py`** — net reduction ~400 lines. Keep `_publish_audit()` Kafka wiring.
2. **Evolvable agent registry** — replace hardcoded `self._agents` list in `alpha_swarm_agent.py` with `@register_agent` decorator pattern. Model after `register_plugins.py`.
3. **Move `prompt_version` from class to instance attribute** — prerequisite for DSPy A/B testing multiple prompt versions without service restart.
4. **Add `memory: dict | None` to `AIContext`** — clean seam for Zep memory injection; additive change, no existing logic needs to change.
5. **Delete `GuardrailsValidator` stub** — v2.8 replaces with Guardrails AI. Delete now to avoid name collision.
6. **`PluginCircuitBreaker` for plugins (#10)** — wire into `PluginExecutor._get_plugin_cb()`. v2.8 adds more agents with LLM calls that can time out.

### Safe to Defer

These won't block v2.8 but should eventually be addressed:

1. **Pipeline god class decomposition (#1)** — highest leverage but largest effort. Defer until after v2.8 ships.
2. **React error boundaries (#12)** — low severity; dashboard render crashes are edge cases.
3. **Global mutable state thread protection (#7)** — no known production failures from this yet.
4. **Settings god object full refactoring (#2)** — delete 8 dead fields now (quick win); full extraction of instrument definitions to DB/YAML can wait.
5. **Standardize `_health_monitor_loop` in BaseWriterAgent (#31)** — code quality improvement, no data loss risk.
6. **25 raw `.isoformat()` calls (#32)** — consumer-facing risk is low since `parse_iso_ts()` handles both forms.
7. **Dead topic cleanup (D-12 `signals.aggregated`, D-13 `market.data.quality`, D-14 `intelligence.signal.audit`)** — document intent, no immediate harm.
8. **Settings checkpoint path hardcoding (#36)** — only matters for multi-shard deployments.

---

## Phase 107 Resolutions (2026-05-25)

**Wave 3: Complexity Reduction — HYGIENE-04, HYGIENE-05, HYGIENE-06**

### HYGIENE-04: DAG Completeness
**Status:** COMPLETE (Phase 107-03, 2026-05-25)
**Resolution:** All 41 deployed services now covered in _DAG_ORDER (42 entries total)
- Added `indicagent-ibkr-restart` to _DAG_ORDER priority 0 (infrastructure sentinel, oneshot wrapper)
- Added `indicagent-bar-aggregator.service` to production/systemd/ (was installed but missing from repo)
- Fixed bar-aggregator After= dependency to include `indicant-provider-merger.service` (priority 2)
- **Verification:** 42/41 services covered (102.5%); all systemd unit dependencies align with _DAG_ORDER priorities
- **Impact:** Service auditor now monitors all deployed services; correct restart order prevents race conditions

### HYGIENE-05: Dead Code Deletion
**Status:** COMPLETE (verified 2026-05-25)
**Resolution:** All dead code removed in prior phases; verified via git grep (0 results)
- `ShadowRecorder` class: Not found in codebase (deleted in prior phase)
- `GuardrailsValidator` class: Not found in codebase (deleted in prior phase)
- 8 dead Settings fields: Not found in settings.py (deleted in prior phase)
  - SWARM_QUEUE_TIMEOUT_MS, LLM_RATE_LIMIT_RPM, LLM_RATE_LIMIT_TPM
  - SHADOW_CORRELATION_THRESHOLD, SHADOW_MIN_SAMPLES
  - LANGFUSE_HOST, MLFLOW_TRACKING_URI, RUSTFUSE_PREFIX
- TEMPLATE agent bug: TEMPLATE_agent.py uses `self._llm_generate()` correctly (line 78)
- **Verification:** `git grep "ShadowRecorder|GuardrailsValidator|SWARM_QUEUE_TIMEOUT_MS|..."` returns 0 results
- **Impact:** Cognitive load reduced; no false trails for developers

### HYGIENE-06: Shadow Governance
**Status:** COMPLETE (verified 2026-05-25)
**Resolution:** Shadow promotion/demotion queries already correct (fixed in prior phase)
- Promotion query (line 126): `WHERE ... is_shadow = TRUE` — shadow plugin performance based on shadow signals only
- Demotion query (line 267): `WHERE ... is_shadow = FALSE` — live plugin performance based on live signals only
- Swarm agents skipped (lines 100-102): `if ctype == "swarm_agent": continue` — no query execution for swarm agents
- **Verification:** Shadow signals cannot contaminate live track promotion stats
- **Impact:** Graduation decisions based on clean data; optimizing for correct objective

### Summary
- **HYGIENE-04:** COMPLETE — DAG completeness at 102.5% (42 entries for 41 deployed services)
- **HYGIENE-05:** COMPLETE — Dead code fully removed (0 git grep results for all patterns)
- **HYGIENE-06:** COMPLETE — Shadow governance queries filter correctly (is_shadow + swarm skip)

**Phase 107 Wave 3: COMPLETE**

All 9 HYGIENE criteria (HYGIENE-01 through HYGIENE-09) are now complete across Waves 1-3.
Phase 107 infrastructure hygiene work is complete and ready for verification deployment.

---

*Last Updated: 2026-05-25 — Phase 107 Wave 3 complete*
