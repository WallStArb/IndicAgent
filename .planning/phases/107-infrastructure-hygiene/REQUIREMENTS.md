# Phase 107: Infrastructure Hygiene — Requirements (Renaissance-Style)

**Milestone:** v2.8 Infrastructure Hardening + AI Platform
**Depends on:** Phase 106
**Last Updated:** 2026-05-25

## Renaissance Principles Applied

**Jim Simons' demands:**
1. **"Zero tolerance for silent failures"** — data loss = alpha leakage
2. **"If you can't measure it, you don't understand it"** — instrumentation before optimization
3. **"Every component must earn its keep"** — justify existence with measurements
4. **"Simplicity over complexity"** — smallest fix that solves the problem
5. **"Technical debt is quantifiable"** — measure it, don't guess at it

## Wave 1: Instrumentation First (Blocker for Everything Else)

### HYGIENE-01: Writer Flush Path Observability

**Hypothesis:** Writer flush failures are invisible → we don't know when persistence is broken → data loss accumulates silently.

**Renaissance Principle:** *Instrumentation is physics — you cannot optimize what you don't measure.*

**✅ Phase 106 Delivered** (already complete):
- ✅ Hot path span coverage: `_process_bar_inner()` wrapped in `observed_span("pipeline.process_bar_inner")`
- ✅ Per-tier latency histogram: `INTELLIGENCE_PIPELINE_TIER_LATENCY_MS` with tier labels (i1, i2_i6)
- ✅ enqueue_blocking for intel+journal topics (timeout-protected backpressure)
- ✅ O(1) state lookup via `_states_by_key` secondary index

**❌ Still Missing** (Phase 107 scope):
- ❌ Writer flush path spans (feature_writer, signal_writer, llm_writer, ctx_writer, swarm_ledger_writer)
- ❌ Flush error visibility (AttributeError in ctx_writer, ghost-run in feature_writer)
- ❌ DB connection failure visibility

**Measurement — Before:**
```bash
# Quantify the missing spans
grep -c "observed_span.*flush\|start_as_current_span.*flush" services/*_writer_agent.py
# Expected: 0 (no writer flush spans)

# Count flush error handling gaps
grep -c "except.*Exception.*pass" services/*_writer_agent.py
# Expected: 3-5 services swallow exceptions
```

**Measurement — After:**
```sql
-- Verify writer flush spans
SELECT
  'writer_flush_span_coverage' as metric,
  COUNT(*) * 100.0 / (SELECT COUNT(*) FROM writer_agents) as coverage_pct
FROM span_coverage
WHERE function_name = '_flush'
  AND span_name IS NOT NULL;

-- Target: 100% coverage
```

**Success Criteria** (what must be TRUE):
1. **Writer flush paths instrumented:**
   - All `*_writer_agent.py:_flush()` methods wrapped in `observed_span("writer.flush")`
   - DB operations (batch insert, connection acquire) emit child spans
   - Flush duration recorded as histogram: `{service}_flush_duration_ms`

2. **Flush error visibility:**
   - Every `except Exception` block in `_flush()` emits `span.add_event("exception", {...})`
   - OTel span status set to `ERROR` with exception message
   - Structlog `error()` calls include `trace_id` and `span_id` for correlation
   - No bare `except: pass` blocks in flush paths

3. **DB connection visibility:**
   - `_connect_database()` failures raise (not silent) → systemd restarts service
   - `{service}_db_connected` OTel gauge: green=connected, red=disabled
   - Connection pool exhaustion emits `{service}_db_pool_exhausted_total` counter

4. **Verification query green:**
   ```bash
   grep -c "observed_span.*flush" services/*_writer_agent.py  # Target: ≥5 (all writers)
   grep -c "except.*Exception.*pass" services/*_writer_agent.py  # Target: 0
   ```

**Root Cause Fix** (prevent recurrence):
- Add `src/observability/spans.py` lint rule: `@require_span()` decorator for critical methods
- CI gate: `pytest tests/observability/test_span_coverage.py` fails if coverage < 100%
- Template update: `services/TEMPLATE_agent.py` includes `observed_span()` examples

**Why Jim Cares:**
*"When feature_writer's DB connection silently fails and the service ghost-runs with `db_manager = None`, we drop 10,000 rows at 160/min. That's 6.25% data loss. We won't know until PnL drops three weeks later. Flush path visibility means we'll see DB failures in Grafana within 5 minutes. Data loss is alpha leakage."*

**Renaissance Measurement:**
- Before: `0` writer flush spans, `3-5` silent exception handlers
- After: `100%` writer coverage, `0` silent exception handlers
- Metric: `writer_flush_span_coverage_pct` (target: 100%)

---

### HYGIENE-02: Metric Type Correctness Enforcement

**Hypothesis:** Wrong metric types → alerts fire incorrectly → we wake up at 3am for non-issues → alert fatigue → real problems ignored.

**Renaissance Principle:** *Measurement integrity is as important as measurement itself.*

**Measurement — Before:**
```bash
# Quantify the wrongness
echo "Latency as counter/gauge: $(grep -r 'create_counter.*latency\|create_gauge.*latency' src/ services/ | wc -l)"
echo "Level as up_down_counter: $(grep -r 'create_up_down_counter.*depth\|create_up_down_counter.*size' src/ services/ | wc -l)"
echo "Shadow metrics wrong type: $(grep -A5 'SHADOW_WIN_RATE\|SHADOW_N_RESOLVED\|SHADOW_EV_R\|SHADOW_DAYS_TO_GATE\|SHADOW_EV_CI_LOWER' src/observability/metrics.py | grep 'create_up_down_counter' | wc -l)"

# Expected: 3 latency as gauge, 5 shadow metrics wrong type
```

**Measurement — After:**
```sql
-- Verify correctness
SELECT
  metric_type_violations_count,
  metric_type_violations_count * 100.0 / total_metrics as violation_pct
FROM metric_audit
WHERE audit_date = CURRENT_DATE;

-- Target: 0 violations, 0% violation rate
```

**Success Criteria** (what must be TRUE):
1. **Latency = histogram:**
   - `intelligence_pipeline_i1_latency_ms` converted to histogram (currently dead gauge)
   - `intelligence_pipeline_i7_latency_ms` converted to histogram (currently dead gauge)
   - `intelligence_pipeline_pipeline_latency_ms` converted to histogram (currently dead gauge)
   - All three have `.record()` calls added (currently declared but never called)

2. **Shadow governance metrics = gauge:**
   - `SHADOW_WIN_RATE`, `SHADOW_N_RESOLVED`, `SHADOW_EV_R`, `SHADOW_DAYS_TO_GATE`, `SHADOW_EV_CI_LOWER`
   - All changed from `create_up_down_counter` to `create_gauge`
   - Emission pattern changed from `.add(value, attrs)` to `.set(value, attrs)`

3. **Label consistency:**
   - Standardize on `agent_id` everywhere (eliminate `agent` vs `agent_id` split)
   - Update `_batch_latency_attrs` in `BaseWriterAgent.__init__` to `{"agent_id": self.name.lower()}`
   - Update Grafana queries to use `agent_id` label

4. **Automated enforcement:**
   ```python
   # Add to src/observability/metrics.py
   def assert_metric_type_correctness():
       """Enforce metric type constraints at module import time."""
       from src.observability.metrics import ALL_METRICS

       for name, metric in ALL_METRICS.items():
           if 'latency' in name and not isinstance(metric, Histogram):
               raise ValueError(f"Latency metric {name} must be histogram, got {type(metric)}")
           if 'shadow' in name and isinstance(metric, UpDownCounter):
               raise ValueError(f"Shadow metric {name} must be gauge, not up_down_counter")
   ```

5. **Verification query green:**
   ```bash
   ruff check src/observability/metrics.py services/ --select RUF  # Custom rule for metric type violations
   # Target: 0 violations
   ```

**Root Cause Fix** (prevent recurrence):
- Add ruff custom rule `RUF101`: Flag raw metric creation without type annotation
- CI gate: `pytest tests/observability/test_metric_types.py` validates all metrics follow naming conventions
- Documentation: Add `src/observability/METRIC_TYPE_GUIDE.md` with decision tree

**Why Jim Cares:**
*"Our shadow governance dashboard shows SHADOW_WIN_RATE = 500% because we're using up_down_counter. We can't trust our own dashboards. If we can't trust our measurements, we can't trust our science. That's unacceptable."*

**Renaissance Measurement:**
- Before: `8` metric type violations (3 latency + 5 shadow)
- After: `0` violations
- Metric: `metric_type_violation_count` (target: 0)

---

## Wave 2: Silent Failure Elimination (Blocker for AI Platform)

### HYGIENE-03: Silent Data Loss Elimination

**Hypothesis:** Services drop data silently → we trade on incomplete information → alpha leakage → bad decisions.

**Renaissance Principle:** *Silent failures are the most expensive — you pay the cost without knowing it.*

**Measurement — Before:**
```sql
-- Quantify the loss
SELECT
  service_name,
  'buffer_overflows_per_hour' as metric,
  SUM(buffer_overflow_count) / EXTRACT(EPOCH FROM (MAX(observed_ts) - MIN(observed_ts))) * 3600 as value
FROM service_health_metrics
WHERE buffer_overflow_count > 0
GROUP BY service_name;

-- Expected: feature_writer has QueueFull drops at 160/min
```

**Measurement — After:**
```sql
-- Verify no silent drops
SELECT
  service_name,
  'silent_drop_rate' as metric,
  CASE
    WHEN uses_enqueue_blocking THEN 0
    ELSE buffer_overflow_count / total_messages
  END as value
FROM service_health_metrics
WHERE critical_writer = TRUE;

-- Target: 0.00% for all critical writers
```

**Success Criteria** (what must be TRUE):
1. **No silent queue drops:**
   - `intelligence_pipeline_agent.py:507` (intelligence topic enqueue) converted to `enqueue_blocking`
   - `intelligence_pipeline_agent.py:598` (journal topic enqueue) converted to `enqueue_blocking`
   - All `enqueue_blocking` sites have timeout configured (no infinite blocks)

2. **Flush failures raise, not swallow:**
   - `ctx_writer_agent.py:343,351` `.inc()` → `.add()` (fixes AttributeError)
   - `feature_writer_agent.py:406-414` `_connect_database()` raises instead of setting `db_manager = None`
   - All writer agents have `feature_writer_db_connected` OTel gauge (green = connected, red = disabled)

3. **Offset correctness:**
   - `swarm_ledger_writer_agent.py` migrated to `BaseWriterAgent` (gets DLQ, offset management for free)
   - `llm_writer_service.py` changed from `auto_offset_reset="latest"` to `"earliest"`
   - All writers use `enable_auto_commit=False` with manual commit after successful flush

4. **Verification query green:**
   ```sql
   SELECT 1 FROM service_health_metrics
   WHERE silent_drop_rate = 0.00
   AND all_critical_writers_connected = TRUE;
   ```

**Root Cause Fix** (prevent recurrence):
- Add `BaseWriterAgent` enforcement: Subclass must call `super()._teardown()` (detects missing via override check)
- CI gate: `pytest tests/persistence/test_writer_integrity.py` simulates DB failure, verifies service crashes
- Template update: `services/TEMPLATE_writer_agent.py` shows correct flush/offset pattern

**Why Jim Cares:**
*"FeatureWriter dropping 10,000 rows at 160/min is 6.25% data loss. We're trading on 93.75% of our signal. If this happened at Renaissance, we'd shut down trading until fixed. Data loss is alpha leakage. Period."*

**Renaissance Measurement:**
- Before: `6.25%` data loss rate (feature_writer QueueFull drops)
- After: `0.00%` data loss
- Metric: `silent_data_loss_rate` (target: 0.00%)

---

### HYGIENE-04: DAG Topology Correctness

**Hypothesis:** Wrong systemd dependencies → services start in wrong order → race conditions → silent data corruption → undetectable until PnL drops.

**Renaissance Principle:** *System topology is physics. Get it wrong and the universe punishes you.*

**Measurement — Before:**
```bash
# Quantify the DAG violations
echo "Services missing from _DAG_ORDER: $(comm -13 <(grep -oP 'indicagent-[^:]+' services/service_auditor_agent.py | sort) <(systemctl list-units --all | grep indicagent | awk '{print $1}' | sort) | wc -l)"
echo "Invalid After= references: $(grep -rh 'After=' production/systemd/ | grep -v 'indicagent-' | wc -l)"
echo "Cyclic dependencies: $(grep -A10 'cross_asset\|intelligence_pipeline' services/service_auditor_agent.py | grep 'priority.*5' | wc -l)"

# Expected: 11 services missing, 2 invalid refs, 1 cycle
```

**Measurement — After:**
```sql
-- Verify DAG completeness
SELECT
  dag_completeness_pct,
  invalid_dependency_count,
  cyclic_dependency_count
FROM dag_audit
WHERE audit_date = CURRENT_DATE;

-- Target: 100% completeness, 0 invalid refs, 0 cycles
```

**Success Criteria** (what must be TRUE):
1. **All deployed services in `_DAG_ORDER`:**
   - Add 11 missing services: `shadow-auditor`, `weight-updater`, `ml-orchestrator`, `ml-data-quality`, `ml-discovery`, `hmm-training`, `feature-validation`, `api`, `dashboard`, `redpanda-ready`, `redpanda-watchdog`
   - ML batch services at L8 (oneshot, non-restartable)
   - API/dashboard at L10 (user-facing, optional)
   - Infra units marked `restartable=False` (redpanda-ready, redpanda-watchdog)

2. **After= references only valid units:**
   - `indicagent-intelligence-pipeline.service`: Change `After=indicagent-bar-aggregator-compute.service` → `indicagent-bar-aggregator.service`
   - Add `After=indicagent-cross-asset.service indicagent-macro-compute.service`
   - `indicagent-alerting-agent.service` + `indicagent-dlq-drain.service`: Change `After=redpanda.service` → `indicagent-redpanda-ready.service`
   - Add `Requires=indicagent-redpanda-ready.service` to both

3. **Priority levels match data flow:**
   - `indicagent-cross-asset` + `indicagent-macro-compute`: priority 5
   - `indicagent-intelligence-pipeline`: priority 6 (subscribes to cross-asset output)
   - `indicagent-roll-compute`: priority 3 (needs priority-2 bar data)

4. **Agent ID mapping consistency:**
   - Change `_AGENT_ID_TO_UNIT["feature_writer"]` → `_AGENT_ID_TO_UNIT["feature_writer_agent"]`
   - Verify `PERSISTENCE_CONSUMER_LAG` metric uses `agent_id="feature_writer_agent"`

5. **Verification script green:**
   ```python
   # scripts/verify_dag_correctness.py
   def verify_dag_correctness():
       """Assert DAG matches deployed reality."""
       deployed_units = get_systemd_units()
       dag_services = get_dag_order_services()

       missing = deployed_units - dag_services
       if missing:
           raise ValueError(f"DAG missing {len(missing)} services: {missing}")

       invalid_refs = find_invalid_systemd_dependencies()
       if invalid_refs:
           raise ValueError(f"Invalid After= refs: {invalid_refs}")

       cycles = detect_cycles_in_dag()
       if cycles:
           raise ValueError(f"Cyclic dependencies detected: {cycles}")

       print("✓ DAG topology correct")
   ```

**Root Cause Fix** (prevent recurrence):
- Add CI gate: `pytest tests/operations/test_dag_correctness.py` runs on every commit to `services/service_auditor_agent.py`
- Pre-commit hook: `.git/hooks/pre-commit` runs `scripts/verify_dag_correctness.py`
- Template update: `production/systemd/indicagent-TEMPLATE.service` shows correct `After=`, `Requires=`, priority

**Why Jim Cares:**
*"If ml-orchestrator fails at 3am and the auditor never sees it, we train models on stale data for 6 hours. That's garbage in, garbage out. But worse — we won't know we're training on garbage until the model starts losing money. By then, we've made bad trading decisions on corrupted data. That's unacceptable."*

**Renaissance Measurement:**
- Before: `11` services missing from DAG, `2` invalid dependencies, `1` cycle
- After: `0` missing, `0` invalid, `0` cycles
- Metric: `dag_completeness_pct` (target: 100%)

---

## Wave 3: Complexity Reduction (Efficiency)

### HYGIENE-05: Dead Code Elimination

**Hypothesis:** Dead code inflates maintenance burden → new engineers learn wrong patterns → bad patterns propagate → codebase rots.

**Renaissance Principle:** *Code surface area = cognitive load. Minimize both.*

**Measurement — Before:**
```bash
# Quantify the dead code
echo "Dead imports: $(git grep -l 'ShadowRecorder\|GuardrailsValidator' | wc -l)"
echo "Dead Settings fields: $(grep -E 'SWARM_QUEUE_TIMEOUT_MS|LLM_RATE_LIMIT|RUSTFUSE_PREFIX|LANGFUSE_HOST|MLFLOW_TRACKING_URI' src/config/settings.py | wc -l)"
echo "TEMPLATE violations: $(grep 'self._llm.generate()' src/intelligence/ai/TEMPLATE_agent.py | wc -l)"

# Expected: 4 files with dead imports, 8 dead fields, 1 TEMPLATE bug
```

**Measurement — After:**
```sql
-- Verify cleanup
SELECT
  dead_import_count,
  dead_settings_field_count,
  template_violation_count,
  total_loc_deleted
FROM code_cleanup_audit
WHERE audit_date = CURRENT_DATE;

-- Target: 0 dead imports, 0 dead fields, 0 template violations, -400 LOC
```

**Success Criteria** (what must be TRUE):
1. **Dead AI foundation imports removed:**
   - `ShadowRecorder` from `src/core/ml/shadow.py` (0 instantiations confirmed)
   - `GuardrailsValidator` from `src/core/llm/guardrails.py` (0 schemas registered, dead branch in chain.py)
   - `_on_guardrail_violation` and `_audit_payload` hooks (no-op stubs)
   - `TransformRecorder` instantiation from `intelligence_pipeline_agent.py:250` (archived but live on hot path)

2. **Settings dead fields purged:**
   - `SWARM_QUEUE_TIMEOUT_MS` (deprecated, zero uses)
   - `LLM_RATE_LIMIT_RPM`, `LLM_RATE_LIMIT_TPM` (orphaned, never read)
   - `SHADOW_CORRELATION_THRESHOLD`, `SHADOW_MIN_SAMPLES` (zero uses)
   - `LANGFUSE_HOST` (never implemented)
   - `MLFLOW_TRACKING_URI` (bypassed by local constant)

3. **TEMPLATE agent fixed:**
   - `src/intelligence/ai/TEMPLATE_agent.py:78` changed from `self._llm.generate()` → `self._llm_generate()`
   - Add comment: `# NEVER call self._llm.generate() directly — use self._llm_generate() for audit trail`

4. **Pre-commit hook enforcement:**
   ```bash
   # .git/hooks/pre-commit
   #!/bin/bash
   if git grep -q "ShadowRecorder\|GuardrailsValidator" HEAD; then
     echo "❌ Forbidden patterns found. Phase 107 cleanup incomplete."
     exit 1
   fi

   if git diff --cached src/config/settings.py | grep -q 'SWARM_QUEUE_TIMEOUT_MS\|LLM_RATE_LIMIT'; then
     echo "❌ Dead Settings fields re-added. Abort."
     exit 1
   fi
   ```

5. **Verification query green:**
   ```bash
   git grep "ShadowRecorder\|GuardrailsValidator" | wc -l  # Target: 0
   grep -E 'SWARM_QUEUE_TIMEOUT_MS|LLM_RATE_LIMIT' src/config/settings.py | wc -l  # Target: 0
   grep 'self._llm.generate()' src/intelligence/ai/TEMPLATE_agent.py | wc -l  # Target: 0
   ```

**Root Cause Fix** (prevent recurrence):
- Add `tests/observability/test_dead_code.py` that fails if forbidden patterns found
- CI gate: `pytest tests/observability/test_dead_code.py` runs on every PR
- Documentation: Add `docs/gotchas.md` entry listing known dead code to avoid re-adding

**Why Jim Cares:**
*"Every line of dead code is a line new engineers must learn. Every wrong pattern in TEMPLATE is copied 10 times. We had 4 services bypassing DatabaseManager because the pattern existed in code. Simplicity is force multiplication. Complexity is technical debt with interest."*

**Renaissance Measurement:**
- Before: `4` dead imports, `8` dead Settings fields, `1` TEMPLATE bug
- After: `0` dead imports, `0` dead fields, `0` template bugs
- Metric: `dead_code_violation_count` (target: 0)

---

### HYGIENE-06: Shadow Registry Integrity

**Hypothesis:** Shadow governance queries are wrong → shadow signals contaminate live track → we promote bad plugins → live trading degradation.

**Renaissance Principle:** *Experimental integrity is sacred. Control groups must remain independent.*

**Measurement — Before:**
```sql
-- Quantify the contamination
SELECT
  'plugins_with_shadow_contamination' as metric,
  COUNT(DISTINCT setup_plugin) as value
FROM (
  SELECT setup_plugin,
    SUM(CASE WHEN is_shadow THEN 1 ELSE 0 END) as shadow_count,
    COUNT(*) as total_count
  FROM signal_ledger
  WHERE setup_plugin IN (SELECT id FROM shadow_registry)
  GROUP BY setup_plugin
  HAVING SUM(CASE WHEN is_shadow THEN 1 ELSE 0 END) > 0
) contaminated;

-- Expected: 0 today (because HF-1 means all signals have is_shadow=FALSE), but query is wrong
```

**Measurement — After:**
```sql
-- Verify queries filter shadows
SELECT
  'promotion_queries_filter_shadows' as metric,
  CASE
    WHEN promotion_query LIKE '%is_shadow = FALSE%' THEN 1
    ELSE 0
  END as value
FROM shadow_audit_queries
WHERE query_name = '_check_promotion';

-- Target: 1 (filter present)
```

**Success Criteria** (what must be TRUE):
1. **Promotion queries filter shadows:**
   - `shadow_auditor_agent.py:115-124` (_check_promotion) adds `AND is_shadow = FALSE`
   - `shadow_auditor_agent.py:256-265` (_check_demotion) adds `AND is_shadow = FALSE`
   - Demotion query also adds `AND pnl_r IS NOT NULL` (plugins with null PnL can't be demoted)

2. **Swarm agents skip ledger queries:**
   - Add component-type branch in `shadow_auditor_agent.py:_run_audit()`
   - For `component_type='swarm_agent'`, skip `signal_ledger` lookups
   - Document: swarm agents governed by `alpha_swarm_agent._graduation_loop` via Spearman-rho

3. **Bootstrap CI validation:**
   - Manual spot-check: `shadow_registry.bootstrap_ci_lower_bound` calculation
   - Extract `signal_ledger.pnl_r` values for a plugin
   - Compute CI lower bound manually: `mean(ev_r) - 1.96 * stddev(ev_r) / sqrt(n)`
   - Compare with `bootstrap_ci_lower_bound` in `shadow_registry`
   - Assert values match within `tolerance=0.01`

4. **Graduation architecture resolution:**
   - Document canonical graduation path in `docs/architecture/graduation.md`
   - If swarm loop supersedes `graduation_compute_agent`, migrate to use `signal_lineage`
   - If both serve different purposes (plugin-level vs agent-level), document explicitly
   - Remove `TransformRecorder` if `graduation_compute_agent` migrated

5. **Verification query green:**
   ```sql
   SELECT 1 FROM shadow_audit
   WHERE promotion_queries_filter_shadows = TRUE
   AND demotion_queries_filter_shadows = TRUE
   AND swarm_agents_skip_ledger_queries = TRUE;
   ```

**Root Cause Fix** (prevent recurrence):
- Add `tests/intelligence/test_shadow_governance.py` that validates shadow isolation
- CI gate: `pytest tests/intelligence/test_shadow_governance.py` runs on every commit to `shadow_auditor_agent.py`
- Documentation: Update `docs/operations/shadow-governance.md` with correct query patterns

**Why Jim Cares:**
*"If shadow signals contaminate promotion statistics, we're optimizing for the wrong objective function. That's not just a bug — that's bad science. At Renaissance, if your control group leaks into your treatment group, you throw out the experiment. You don't promote the contaminated model to production."*

**Renaissance Measurement:**
- Before: `2` queries missing `is_shadow = FALSE` filter, swarm agents query ledger incorrectly
- After: `0` query contamination, swarm agents skip ledger
- Metric: `shadow_governance_integrity_violations` (target: 0)

---

## Wave 1: Service Consistency (Blocker for Everything Else)

### HYGIENE-07: Service Lifecycle Consistency

**Hypothesis:** Services bypassing `BaseAgent` lifecycle → missing SIGTERM handling, stall detection, DLQ routing → invisible failures → undetected data corruption.

**Renaissance Principle:** *Silent failures are the most expensive — you pay the cost without knowing it.*

**Measurement — Before:**
```bash
# Quantify the inconsistency
echo "Services not using BaseAgent: $(comm -13 <(grep -l "BaseAgent" services/*.py | wc -l) <(systemctl list-units --all | grep indicagent | grep -v "timer\|target" | wc -l))"
# Expected: 2 services (signal_replay_auditor, bar_replay_provider)

# Check for custom lifecycle implementations
grep -r "_stop.*asyncio.Event()" services/ | wc -l
# Expected: 2 services with custom stop logic
```

**Measurement — After:**
```sql
-- Verify all services use BaseAgent
SELECT
  'base_agent_adoption_pct' as metric,
  COUNT(CASE WHEN inherits_from_base_agent THEN 1 END) * 100.0 / COUNT(*) as value
FROM service_agents
WHERE is_deployed = TRUE;

-- Target: 100%
```

**Success Criteria** (what must be TRUE):
1. **Migrate `signal_replay_auditor_agent` to `BaseAgent` lifecycle:**
   - Remove custom `_stop = asyncio.Event()`, `_setup()`, `_teardown()`, `_run()`
   - Inherit from `BaseAgent` — gets SIGTERM handling, stall detection, OTel lifecycle
   - Implement `_run()` as async generator (exits on completion)
   - Gets DLQ routing via `_send_to_dlq()` (BaseAgent infrastructure)

2. **Migrate `bar_replay_provider_agent` to `BaseAgent` lifecycle:**
   - Remove custom lifecycle methods
   - Inherit from `BaseAgent`
   - Preserve existing behavior: `sys.exit(0)` on completion (one-shot batch service)
   - Gets stall detection, OTel spans, health monitoring

3. **Lifecycle verification:**
   - Both services call `self._record_message_consumed()` in message loop
   - Both services emit `agent_last_message_timestamp_seconds` metric
   - Both services handle SIGTERM via `BaseAgent._signal_handlers`
   - Stall detection fires after `max_idle_seconds` (configurable per service)

4. **Verification query green:**
   ```bash
   # All agents inherit from BaseAgent
   grep -c "class.*Agent.*BaseAgent" services/*.py  # Target: all agents
   
   # No custom _stop = asyncio.Event() patterns
   grep -r "_stop.*asyncio.Event()" services/*.py | wc -l  # Target: 0
   ```

**Root Cause Fix** (prevent recurrence):
- Add CI gate: `pytest tests/operations/test_base_agent_lifecycle.py` fails if service doesn't inherit from BaseAgent
- Template update: `services/TEMPLATE_batch_agent.py` shows one-shot batch pattern with BaseAgent
- Documentation: Update `docs/architecture/service-lifecycle.md` with BaseAgent best practices

**Why Jim Cares:**
*"If signal_replay_auditor silently fails to backfill lifecycle outcomes, we're scoring signal quality on incomplete data. We'll promote bad plugins to production and demote good ones. That's optimizing for the wrong objective function. When the backfill fails but we don't know it failed, we're making trading decisions on corrupted data. That's unacceptable."*

**Renaissance Measurement:**
- Before: `2` services bypassing BaseAgent (custom lifecycle, no stall detection)
- After: `0` services bypassing (100% BaseAgent adoption)
- Metric: `base_agent_adoption_pct` (target: 100%)

---

### HYGIENE-08: DatabaseManager Pool Standardization

**Hypothesis:** Services bypassing `DatabaseManager.create_pool()` → missing JSONB codecs → silent double-serialization → corrupted data in database.

**Renaissance Principle:** *Data integrity is non-negotiable. Corrupted data = corrupted decisions.*

**Measurement — Before:**
```bash
# Quantify the bypass
echo "Services bypassing DatabaseManager: $(grep -r "asyncpg.create_pool" services/ | grep -v "database_manager.py" | wc -l)"
# Expected: 3 services

# Check for JSONB double-serialization
psql -U postgres -d indicagent -c "SELECT pg_typeof(jsonb_col), LEFT(jsonb_col::text, 20) FROM signal_ledger LIMIT 1;"
# If double-serialized: type shows "jsonb" but value starts with '"' (escaped string)
```

**Measurement — After:**
```sql
-- Verify all services use DatabaseManager
SELECT
  'database_manager_adoption_pct' as metric,
  COUNT(CASE WHEN uses_database_manager_pool THEN 1 END) * 100.0 / COUNT(*) as value
FROM database_access_patterns
WHERE service_category = 'writer';

-- Target: 100%

-- Verify no double-serialization
SELECT
  'jsonb_double_serialization_count' as metric,
  COUNT(*) as value
FROM jsonb_columns
WHERE pg_typeof = 'jsonb'
  AND LEFT(value::text, 1) = '"';

-- Target: 0
```

**Success Criteria** (what must be TRUE):
1. **Migrate 3 services to `DatabaseManager.create_pool()`:**
   - `swarm_ledger_writer_agent.py:89-92`: Replace `asyncpg.create_pool()` with `create_pool()`
   - `bar_replay_provider_agent.py:60`: Replace `asyncpg.create_pool()` with `create_pool()`
   - `signal_replay_auditor_agent.py:69`: Replace `asyncpg.create_pool()` with `create_pool()`

2. **JSONB codec verification:**
   ```python
   # DatabaseManager.create_pool() registers these codecs automatically:
   - JsonCodec(dict → jsonb)  # Pass dict directly, no json.dumps()
   - JsonCodec(list → jsonb)   # Pass list directly
   - DateTimeUTCCodec          # timestamptz with UTC timezone
   
   # Verify no double-serialization in DB:
   assert pg_column_type == "jsonb"
   assert not db_value.startswith('"')  # Not escaped string
   assert db_value.startswith('{') or db_value.startswith('[')
   ```

3. **Pool gauge visibility:**
   - All services emit `DB_POOL_SIZE` gauge (current connections)
   - All services emit `DB_POOL_IDLE` gauge (idle connections)
   - All services emit `{service}_db_pool_exhausted_total` counter on timeout
   - Grafana dashboard: `Database Pool Health` shows all services

4. **Connection string standardization:**
   - All services use `DatabaseManager.get_connection()` context manager
   - No bare `asyncpg.connect()` calls outside database_manager.py
   - Connection timeout configured via `Settings.DB_TIMEOUT`

5. **Verification query green:**
   ```bash
   # No direct asyncpg.create_pool() calls in services/
   grep -r "asyncpg.create_pool" services/ | grep -v "database_manager.py" | wc -l  # Target: 0
   
   # All services import DatabaseManager
   grep -l "from src.core.database_manager import" services/*.py | wc -l  # Target: all DB services
   ```

**Root Cause Fix** (prevent recurrence):
- Add pre-commit hook: `.git/hooks/pre-commit` blocks `asyncpg.create_pool` in services/
- CI gate: `pytest tests/persistence/test_database_manager_usage.py` verifies pool creation
- Template update: `services/TEMPLATE_writer_agent.py` shows DatabaseManager pattern
- Documentation: Add `docs/operations/database-connection-guide.md` with JSONB best practices

**Why Jim Cares:**
*"JSONB double-serialization means we write escaped strings to the database instead of structured data. When we query it back, we get garbage. LLM agents reading corrupted signal_ledger data will train on noise. DSPy prompt optimization will be optimizing for the wrong objective function. That's not just a bug — that's bad science. Corrupted data corrupts everything downstream."*

**Renaissance Measurement:**
- Before: `3` services bypassing DatabaseManager, potential JSONB corruption
- After: `0` services bypassing, `0` JSONB double-serialization
- Metric: `database_manager_adoption_pct` (target: 100%), `jsonb_double_serialization_count` (target: 0)

---

### HYGIENE-09: Agent ID Label Standardization

**Hypothesis:** `"agent"` vs `"agent_id"` label split → fleet-wide dashboards impossible → cross-agent queries broken → we can't see system-level health.

**Renaissance Principle:** *Measurement integrity is as important as measurement itself. You can't optimize what you can't aggregate.*

**Measurement — Before:**
```bash
# Quantify the inconsistency
echo "Metrics using 'agent' label: $(grep -r '"agent":' services/ | wc -l)"
echo "Metrics using 'agent_id' label: $(grep -r '"agent_id":' services/ | wc -l)"
# Expected: split across services

# Check Grafana queries
grep -r 'agent=' production/grafana/dashboards/ | wc -l
grep -r 'agent_id=' production/grafana/dashboards/ | wc -l
# Expected: inconsistent query patterns
```

**Measurement — After:**
```sql
-- Verify label consistency
SELECT
  'agent_id_label_consistency_pct' as metric,
  COUNT(CASE WHEN label_key = 'agent_id' THEN 1 END) * 100.0 / COUNT(*) as value
FROM otel_metric_labels
WHERE metric_name LIKE '%agent%'
  AND label_key IN ('agent', 'agent_id');

-- Target: 100% use 'agent_id'
```

**Success Criteria** (what must be TRUE):
1. **Standardize all metrics on `agent_id`:**
   - `BaseAgent.__init__`: Change `_crash_attrs = {"agent": self._agent_label}` → `{"agent_id": self._agent_label}`
   - `BaseAgent.__init__`: Change `_setup_success_attrs` → `{"agent_id": self._agent_label}`
   - `BaseAgent.__init__`: Change `_setup_latency_attrs` → `{"agent_id": self._agent_label}`
   - `BaseWriterAgent.__init__`: Move `_batch_latency_attrs` initialization from subclasses to base class as `{"agent_id": self.name.lower()}`

2. **Update service-specific label declarations:**
   - `bar_writer_agent.py`: Change histogram attrs from `{"agent": self.name}` → `{"agent_id": self.name.lower()}`
   - All `_dlq_attrs`, `_cb_attrs` already use `agent_id` (correct, keep)

3. **Grafana dashboard query updates:**
   - Find/replace: `$agent` → `$agent_id` in all dashboard JSON
   - Fleet-wide dashboards now work correctly:
     - P95 write latency across all writers
     - Total DLQ volume across all services
     - Agent crash rate across fleet
     - Agent setup latency distribution

4. **Verification query green:**
   ```bash
   # No 'agent' label keys in services/
   grep -r '"agent":' services/ | grep -v '"agent_id":' | wc -l  # Target: 0
   
   # All metrics use 'agent_id'
   grep -r '"agent_id":' services/ | wc -l  # Target: all metric label declarations
   ```

**Root Cause Fix** (prevent recurrence):
- Add ruff custom rule `RUF102`: Flag `{"agent": ...}` in metric declarations
- CI gate: `pytest tests/observability/test_metric_label_consistency.py` verifies all metrics use `agent_id`
- Template update: `services/TEMPLATE_agent.py` shows correct label pattern
- Documentation: Add `src/observability/METRIC_LABEL_CONVENTIONS.md` with `agent_id` as standard

**Why Jim Cares:**
*"We can't build a fleet-wide P95 latency dashboard if half the services use `agent` and half use `agent_id`. Any dashboard computing aggregate metrics silently computes a partial answer missing the bar-writer data. When we wake up at 3am for a page about high latency, we don't know if it's one service or the whole fleet. That's not measurement — that's guessing. Measurement requires consistent dimensions."*

**Renaissance Measurement:**
- Before: `~50%` label consistency (split between `agent` and `agent_id`)
- After: `100%` label consistency (all use `agent_id`)
- Metric: `agent_id_label_consistency_pct` (target: 100%)

---

## Renaissance-Style Success Metrics

**Jim Simons' final question:** *"After Phase 107, how will we know we succeeded? Not 'did we complete the checklist' — 'what's the measurable improvement?'*

### Quantified Before/After Metrics:

| Metric | Before | After | Target | Measurable Via | Phase 106 Credit |
|--------|--------|-------|--------|----------------|------------------|
| **Hot path span coverage** | 0% | ✅ 100% | 100% | `critical_path_span_coverage_pct` | Phase 106-04 ✅ |
| **Tier latency histograms** | 0 | ✅ 1 (i1, i2_i6) | 1+ | `tier_latency_histograms_count` | Phase 106-04 ✅ |
| **BaseAgent adoption** | ~90% (38/42) | 100% (42/42) | 100% | `base_agent_adoption_pct` | **Phase 107** |
| **DatabaseManager adoption** | ~75% (3 bypass) | 100% (0 bypass) | 100% | `database_manager_adoption_pct` | **Phase 107** |
| **Agent ID label consistency** | ~50% (split) | 100% (all agent_id) | 100% | `agent_id_label_consistency_pct` | **Phase 107** |
| **Writer flush span coverage** | 0% (0/5 writers) | 100% (5/5) | 100% | `writer_flush_span_coverage_pct` | **Phase 107** |
| **Metric type violations** | 5 (shadow metrics) | 0 | 0 | `metric_type_violation_count` | **Phase 107** |
| **Silent data loss rate** | 6.25% (feature_writer) | 0.00% | 0.00% | `silent_data_loss_rate` | **Phase 107** |
| **DAG completeness** | 74% (32/43 services) | 100% (43/43) | 100% | `dag_completeness_pct` | **Phase 107** |
| **Dead code violations** | 13 (4 imports + 8 fields + 1) | 0 | 0 | `dead_code_violation_count` | **Phase 107** |
| **Shadow governance integrity** | 2 query violations | 0 | 0 | `shadow_governance_integrity_violations` | **Phase 107** |

**Phase 106 Already Delivered:**
- ✅ Hot path span: `_process_bar_inner()` wrapped in `observed_span()`
- ✅ Tier latency: `INTELLIGENCE_PIPELINE_TIER_LATENCY_MS` histogram
- ✅ Backpressure: `enqueue_blocking()` with timeout for intel+journal
- ✅ State lookup: O(1) via `_states_by_key` secondary index

**Phase 107 Scope (9 criteria):**

**Wave 1 — Service Consistency (Blocker for everything else):**
- BaseAgent lifecycle adoption (migrate 2 services: signal_replay_auditor, bar_replay_provider)
- DatabaseManager pool standardization (fix 3 bypass services, prevent JSONB corruption)
- Agent ID label standardization (unify fleet-wide metrics)

**Wave 2 — Silent Failure Elimination (Blocker for AI platform):**
- Writer flush path spans (feature_writer, signal_writer, llm_writer, ctx_writer, swarm_ledger_writer)
- Metric type correctness (shadow governance metrics: up_down_counter → gauge)
- Silent data loss elimination (AttributeError fixes, ghost-run prevention, offset correctness)

**Wave 3 — Complexity Reduction (Efficiency):**
- DAG topology correctness (11 missing services, dependency fixes, cyclic dependency resolution)
- Dead code elimination (ShadowRecorder, GuardrailsValidator, Settings cleanup, TEMPLATE fixes)
- Shadow registry integrity (query filters, swarm agent fixes, graduation resolution)

### Overall Phase 107 Success Score:

```
Phase_107_Success_Score =
  # Wave 1: Service Consistency (30%)
  (base_agent_adoption_pct * 0.10) +
  (database_manager_adoption_pct * 0.10) +
  (agent_id_label_consistency_pct * 0.10) +
  
  # Wave 2: Silent Failure Elimination (35%)
  (writer_flush_span_coverage_pct * 0.10) +
  ((1 - metric_type_violation_count/5) * 0.10) +
  ((1 - silent_data_loss_rate) * 0.15) +
  
  # Wave 3: Complexity Reduction (35%)
  (dag_completeness_pct * 0.12) +
  ((1 - dead_code_violation_count/13) * 0.12) +
  ((1 - shadow_governance_integrity_violations/2) * 0.11)

Target: 100% (all metrics at target)
Minimum Acceptable: 95% (allows partial credit)

Phase 106 Contribution:
  +0.15 (hot path spans: already 100%)
  +0.10 (tier latency histograms: already deployed)
  = 0.25 (25% of total observability score already delivered)
```

**Success Interpretation:**
- **100%**: All 9 criteria at target — infrastructure hygiene complete, v2.8 ready
- **95-99%**: Minor gaps (e.g., 1 service still bypassing BaseAgent, 1 label key inconsistent) — proceed with caution
- **< 95%**: Critical gaps remain — Phase 107 incomplete, block v2.8 AI platform work

### Verification Queries (run after Phase 107 completes):

```sql
-- Phase 107 Success Verification
WITH metrics AS (
  SELECT
    -- Wave 1: Service Consistency
    (SELECT COUNT(CASE WHEN inherits_from_base_agent THEN 1 END) * 100.0 / COUNT(*)
     FROM service_agents WHERE is_deployed = TRUE) as base_agent_adoption,

    (SELECT COUNT(CASE WHEN uses_database_manager_pool THEN 1 END) * 100.0 / COUNT(*)
     FROM database_access_patterns WHERE service_category = 'writer') as db_manager_adoption,

    (SELECT COUNT(CASE WHEN label_key = 'agent_id' THEN 1 END) * 100.0 / COUNT(*)
     FROM otel_metric_labels
     WHERE metric_name LIKE '%agent%' AND label_key IN ('agent', 'agent_id')) as agent_id_consistency,

    -- Wave 2: Silent Failure Elimination
    (SELECT COUNT(*) * 100.0 / (SELECT COUNT(*) FROM writer_agents)
     FROM span_coverage WHERE function_name = '_flush' AND span_name IS NOT NULL) as writer_flush_coverage,

    (SELECT COUNT(*) FROM metric_type_violations) as metric_violations,

    (SELECT CASE WHEN uses_enqueue_blocking THEN 0 ELSE buffer_overflow_count / total_messages END
     FROM service_health_metrics WHERE service_name = 'feature_writer') as data_loss_rate,

    -- Wave 3: Complexity Reduction
    (SELECT COUNT(DISTINCT unit) * 100.0 / (SELECT COUNT(*) FROM systemd_units)
     FROM dag_order) as dag_completeness,

    (SELECT COUNT(*) FROM dead_code_violations) as dead_violations,

    (SELECT COUNT(*) FROM shadow_governance_violations) as shadow_violations
)
SELECT
  base_agent_adoption >= 100 as hyg07_pass,
  db_manager_adoption >= 100 as hyg08_pass,
  agent_id_consistency >= 100 as hyg09_pass,
  writer_flush_coverage >= 100 as hyg01_pass,
  metric_violations = 0 as hyg02_pass,
  data_loss_rate = 0.00 as hyg03_pass,
  dag_completeness >= 100 as hyg04_pass,
  dead_violations = 0 as hyg05_pass,
  shadow_violations = 0 as hyg06_pass,
  (
    -- Wave 1: Service Consistency (30%)
    (base_agent_adoption * 0.10) +
    (db_manager_adoption * 0.10) +
    (agent_id_consistency * 0.10) +
    -- Wave 2: Silent Failure Elimination (35%)
    (writer_flush_coverage * 0.10) +
    (CASE WHEN metric_violations = 0 THEN 1 ELSE 0 END * 0.10) +
    (CASE WHEN data_loss_rate = 0 THEN 1 ELSE 0 END * 0.15) +
    -- Wave 3: Complexity Reduction (35%)
    (dag_completeness * 0.12) +
    (CASE WHEN dead_violations = 0 THEN 1 ELSE 0 END * 0.12) +
    (CASE WHEN shadow_violations = 0 THEN 1 ELSE 0 END * 0.11)
  ) >= 0.95 as phase_107_success
FROM metrics;
```

**Expected result:** All `hygXX_pass = TRUE`, `phase_107_success = TRUE`

---

## Why This Matters for v2.8 AI Platform

**Without Phase 107:**
- ❌ DSPy prompt optimization regressions invisible (no spans, no tier latency)
- ❌ LLM call audit trail corrupted (silent data loss in writers)
- ❌ New AI agents not monitored by service auditor (DAG incomplete)
- ❌ Bad patterns copied into new agents (dead code in TEMPLATE)
- ❌ Shadow signals contaminate AI agent evaluation (governance queries wrong)

**With Phase 107:**
- ✅ Every LLM call traced end-to-end (span coverage)
- ✅ Every tier instrumented (I1-I7 latency histograms)
- ✅ Data loss impossible (enqueue_blocking, flush failures raise)
- ✅ New AI agents auto-enrolled in DAG (service auditor sees them)
- ✅ TEMPLATE agent safe to copy (dead code removed, patterns correct)
- ✅ Shadow governance accurate (control groups isolated)

**Jim Simons' final stamp:**

*"This is how Renaissance does infrastructure. Measure everything. Fix root causes. Never tolerate silent failures. Every line of code earns its keep. When you add 10 AI agents in v2.8, you'll do it on a foundation that's engineered like physics — not held together by duct tape and hope."*

---

**Next Steps:**
1. Review and refine requirements
2. Run baseline measurements (capture "before" state)
3. Execute Phase 107 plans (wave-by-wave)
4. Run verification queries (confirm "after" state)
5. Compute Phase 107 Success Score (must be ≥ 95%)
6. Gate v2.8 AI platform work on Phase 107 completion
