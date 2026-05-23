# Architectural Audit Synthesis — 2026-05-23

**Produced by:** Synthesis agent (Claude Sonnet 4.6)
**Source:** 7 domain audits (telemetry, code-reuse, DAG, shadow-governance, compute-latency, persistence, simplification)
**Coverage:** 92 individual findings across 7 domains merged into 47 master findings (11 HOTFIX + 24 new + 12 updated)

---

## Cross-Domain Patterns

These are root causes that manifested as independent findings across multiple domain audits. Each represents a systemic gap, not an isolated bug.

### Pattern A: The OTel Metric Type Anti-Pattern (4 domains, 9 findings)

The same mistake — using `up_down_counter` where `histogram` or `gauge` is needed — appears in:
- **Telemetry:** T-2 (three latency metrics as `up_down_counter`), T-5 (five shadow metrics accumulate forever)
- **Compute-latency:** CL-1 (`_i1_latency_ms` dead instrument)
- **Persistence:** P-9 (`BarWriterAgent` private histogram excluded from shared dashboard)
- **Code-reuse:** CR-2 (`llm_writer` calls `.add(uptime)` on `up_down_counter` instead of `.set()`)

Root cause: The `gauge()` factory in `src/observability/metrics.py` wraps `create_up_down_counter()`. When developers want a point-in-time value, they call `gauge()` (semantically correct name) and get an accumulating counter (semantically wrong implementation). The factory name is misleading. Every developer who calls `gauge()` for a ratio or rate metric gets permanently incorrect data.

**Single fix unlocks all:** Add a `point_gauge()` factory that calls `create_gauge()` (OTel 0.47+ API) or equivalent. Audit and migrate all 9 affected metrics in one pass.

---

### Pattern B: BaseAgent Lifecycle Bypass (3 domains, 6 findings)

Three independent audits found services that reinvent lifecycle plumbing already in `BaseAgent`/`BaseWriterAgent`:
- **Code-reuse:** CR-4 (`SwarmLedgerWriterAgent` extends `BaseAgent` not `BaseWriterAgent`, reinvents consumer + DB), CR-8 (`signal_replay_auditor`, `bar_replay_provider` build their own `_setup/_teardown/_run`)
- **Persistence:** P-4 (`SwarmLedgerWriterAgent` no DLQ, swallows all errors), P-2 (`CtxWriterAgent` no DLQ topic configured), P-5 (`FeatureWriterAgent` ghost-run on DB failure), P-3 (`CtxWriterAgent` `.inc()` crash from OTel mismatch)
- **Telemetry:** T-6 (`BarWriterAgent` custom `_run()` never calls `_record_message_consumed()`), T-7 (`LLMWriterService` stall watchdog reads unset attribute)

Root cause: `BaseAgent`/`BaseWriterAgent` provide correct behaviors (stall detection, DLQ routing, offset commit, flush guarantee). Services that bypass or partially override these lose the behaviors silently. The class hierarchy is not enforced and has no startup validation.

**Single fix unlocks most:** Add a startup assertion in `BaseAgent.__init_subclass__()` that warns (not raises) when a subclass overrides `_run()` without calling `self._record_message_consumed()`. Also: make `BaseWriterAgent._teardown()` call `super()._teardown()` enforcement visible — add an assertion that `_teardown()` was called before process exit.

---

### Pattern C: DAG Wiring Gaps — Silent Subscribers to Empty Topics (2 domains, 4 findings)

Both the DAG audit and telemetry audit independently found Kafka topics with consumers but no publishers:
- **DAG:** D-5 (`intelligence.i8` — no publisher), D-6 (`llm.outcomes` — no publisher), D-12 (`signals.aggregated` — no service consumer), D-13 (`market.data.quality` — no consumer), D-14 (`intelligence.signal.audit` — no consumer)
- **Telemetry:** T-3 (`_i1_latency_ms` metric wired but never called — same pattern in OTel space)

Root cause: No automated test verifies the producer-consumer pairing for every Kafka topic. Topics are declared in `kafka_init_topics.py` but publisher/subscriber pairings are not enforced. A service can subscribe to a topic that was never wired to a publisher and the system runs indefinitely consuming nothing.

**Single fix:** Add a CI test that reads all `stream_keys.py` topic functions, cross-references them against `services/*.py` for at least one publisher AND one subscriber, and fails on orphaned topics. This would have caught D-5, D-6, and D-12-14 at merge time.

---

### Pattern D: systemd Unit File Configuration Drift (1 domain, 5 findings)

The DAG audit found a cluster of systemd unit files with broken or missing dependency declarations:
- D-3: `intelligence-pipeline` `After=` references non-existent `indicagent-bar-aggregator-compute.service`
- D-4: `alerting-agent` and `dlq-drain` depend on non-existent `redpanda.service`
- D-11: 7 L6 services have only `After=network-online.target` with no upstream ordering
- D-2: `bar-aggregator.service` has no versioned reference in `production/systemd/`

Root cause: systemd silently ignores unknown `After=` and `Wants=` targets — there is no startup-time validation of unit dependencies. Combined with the absence of a CI check that verifies unit file contents, configuration drift accumulates undetected. A deployment script that regenerates units from `production/systemd/` will miss `bar-aggregator` entirely.

**Single fix:** Add a CI script (`production/scripts/validate_systemd_units.py`) that: (1) verifies all `After=` and `Wants=` targets exist in `production/systemd/` or are known systemd builtins, (2) verifies all services in `_DAG_ORDER` have a corresponding unit file in `production/systemd/`. This catches D-2, D-3, D-4 at commit time.

---

### Pattern E: Shadow Governance — Three-Layer Failure (1 domain, 4 findings that compound)

The shadow governance audit found that the feature exists structurally but fails at every execution layer:
- SG-1: `is_shadow` never stamped on signal dicts (executor omits the field)
- SG-7: Winner selection has no shadow eligibility filter (shadow plugin can trade live)
- SG-4: Swarm agent auditor gates always see n=0 (queries wrong table)
- SG-2/3: Promotion/demotion queries include shadow observations (latent bug waiting for SG-1 fix)

Root cause: Shadow governance was implemented as a DB feature (enrollment, registry) but the enforcement point — the signal processor that converts registry state into runtime behavior — was never completed. The DB layer is correct; the runtime enforcement layer has three gaps. These compound: fixing SG-1 without SG-7 makes shadow signals correctly tagged but still tradeable. Fixing SG-7 without SG-2/3 suppresses live trades but trains the promotion gate on contaminated data.

**Required fix order:** SG-7 → SG-1 → SG-6 → SG-2/3 → SG-4. Each step is blocked on the previous.

---

## Top 5 Highest-Leverage Fixes

These fixes each resolve the most findings simultaneously.

### Fix 1: Shadow signal suppression (resolves SG-1, SG-7, SG-6, SG-2, SG-3 — 5 findings, HF-1)
**Effort:** 1-2 hours
**Files:** `src/intelligence/pipeline/executor.py`, `src/intelligence/pipeline/signal_processor.py`, `src/intelligence/pipeline/winner_selector.py`, `services/shadow_auditor_agent.py`
**Why:** One atomic change (stamp + filter) stops shadow signals from entering live trading. Without it, shadow mode is purely observational decoration. All other shadow governance improvements depend on this being correct first. Also fixes the feedback loop contamination in CIS weight training.

### Fix 2: Correct OTel metric types — latency histograms and shadow gauges (resolves T-2, T-5, T-3, CR-2, P-9 — 5 findings, HF-8, HF-9)
**Effort:** 2-3 hours
**Files:** `services/intelligence_pipeline_agent.py:176-193`, `src/observability/metrics.py:224-243`, `services/shadow_auditor_agent.py:170-194`, `services/feature_writer_agent.py:276`, `services/bar_writer_agent.py:118`
**Why:** The p50/p95/p99 latency percentiles and shadow governance dashboards are permanently wrong. This is pure instrument type changes — no logic changes. Also standardizes the `"agent"` vs `"agent_id"` label split, fixing all cross-agent Grafana aggregations.

### Fix 3: `.inc()` → `.add()` and `self._pool` fix (resolves P-3, P-1, HF-2, HF-3 — 4 findings)
**Effort:** 30 minutes
**Files:** `services/ctx_writer_agent.py:343,351`, `services/llm_writer_service.py:695,822`
**Why:** Four lines of code changes. `CtxWriterAgent` buffers are currently silently growing forever and will drop CTX rows at `MAX_BUFFER_SIZE`. `LLMWriterAgent` parse-success back-fills are silently dropped on every `_parse_update` message. Both are active data loss bugs requiring minimal effort to fix.

### Fix 4: `intelligence-pipeline` systemd + DAG order fixes (resolves D-3, D-4, D-7, D-8, #17, #18, #19, #20, #21 — 9 findings)
**Effort:** 2-3 hours
**Files:** `production/systemd/indicagent-intelligence-pipeline.service`, `production/systemd/indicagent-alerting-agent.service`, `production/systemd/indicagent-dlq-drain.service`, `services/service_auditor_agent.py`
**Why:** On cold boot, the intelligence pipeline currently starts without waiting for bar-aggregator (broken `After=` reference). Alerting and DLQ drain start before Redpanda is ready. Feature-writer lag is invisible. This cluster of fixes makes the cold-boot behavior deterministic and monitored.

### Fix 5: `PluginStateManager` O(N) scan index (resolves #26, Simplification Section 1 — scaling cliff)
**Effort:** 1-2 hours
**Files:** `src/intelligence/pipeline/state_manager.py`
**Why:** At 58 symbols this is tolerable. At 116 symbols (v2.8 target) it doubles the dominant hot-path CPU cost. The fix is a mechanical dict refactor that does not change any behavior — only adds a secondary index. Deferring past v2.8 makes it a crisis fix under production load instead of a planned improvement.

---

## "Fix This First" — Ordered List for Next 2 Weeks

### Week 1: Active Data Loss and Shadow Governance

**Day 1-2: Three-line hotfixes with immediate impact**
1. `.inc()` → `.add()` in `ctx_writer_agent.py:343,351` and `llm_writer_service.py:822` (HF-2)
2. Replace `self._pool.acquire()` with `self.db_manager.execute_command()` in `llm_writer_service.py:695` (HF-3)
3. Add `await super()._teardown()` to `ctx_writer_agent._teardown()` (HF-11)
4. `LLMWriterService` stall watchdog: replace `_last_msg_ts` with `_last_message_ts`, call `_record_message_consumed()` (HF-6)
5. `BarWriterAgent`: add `self._record_message_consumed()` in `_run()` loop (HF-7)

**Day 3-4: Shadow signal suppression (HF-1 — highest business impact)**
6. Stamp `sig["is_shadow"]` in `executor.py` post-processing loop
7. Filter shadow plugins from `select_winner()` candidates in `signal_processor.py`
8. Set `sig["status"] = "regime_suppressed"` for shadow signals
9. Add `AND is_shadow = FALSE` to promotion/demotion queries in `shadow_auditor_agent.py`
10. Skip `signal_ledger` lookups in `_run_audit()` for `component_type='swarm_agent'`

**Day 5: `FeatureWriterAgent` ghost-run fix (HF-4)**
11. Raise in `_connect_database()` instead of setting `db_manager = None`
12. Add `feature_writer_db_connected` OTel gauge

### Week 2: Observability and DAG Correctness

**Day 6-7: OTel metric type corrections (HF-8, HF-9)**
13. Replace `gauge()` with `create_histogram()` for latency metrics in `intelligence_pipeline_agent.py:176-193`
14. Add `.record()` calls for dead `_i1_latency_ms` and `_pipeline_latency` instruments
15. Fix shadow metrics: change to `create_gauge` + `.set()` in `shadow_auditor_agent.py`
16. Standardize metric label key to `"agent_id"` everywhere (base.py, bar_writer)

**Day 8: DAG wiring fixes**
17. Fix `intelligence-pipeline` `After=` — change `bar-aggregator-compute` → `bar-aggregator` (D-3)
18. Fix `alerting-agent` and `dlq-drain` `After=` — change `redpanda.service` → `indicagent-redpanda-ready.service` (D-4)
19. Fix `_AGENT_ID_TO_UNIT` key `"feature_writer"` → `"feature_writer_agent"` (D-7)
20. Add 11 missing services to `_DAG_ORDER` at appropriate priority levels (D-1)

**Day 9: `SwarmLedgerWriterAgent` write-safety (HF-5)**
21. Set `enable_auto_commit=False`
22. Migrate to `BaseWriterAgent` or add error counter + DLQ

**Day 10: Quick-win dead code and scaling prep**
23. Delete `ShadowRecorder` (`src/core/ml/shadow.py`) — confirmed zero instantiations
24. Delete `GuardrailsValidator` (`src/core/llm/guardrails.py`) — 53 lines, zero schemas
25. Delete 8 dead Settings fields (`SWARM_QUEUE_TIMEOUT_MS`, `LLM_RATE_LIMIT_RPM/TPM`, `SHADOW_CORRELATION_THRESHOLD`, `SHADOW_MIN_SAMPLES`, `LANGFUSE_HOST`, `MLFLOW_TRACKING_URI`)
26. Fix TEMPLATE agent to use `_llm_generate()` (one-line change)
27. Fix `PluginStateManager.get_all_states_for()` O(N) → O(1) secondary index (before v2.8)

---

*Synthesis produced 2026-05-23. Cross-reference with individual domain audits in `docs/architecture/audit-2026-05-23-*.md` for full per-finding context and line references.*
