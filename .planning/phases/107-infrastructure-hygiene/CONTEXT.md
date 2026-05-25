# Phase 107: Infrastructure Hygiene — Context for GSD Workflows

**Created:** 2026-05-25
**Purpose:** Critical context for `/gsd:discuss-phase 107` and `/gsd:plan-phase 107` after context clearing
**Renaissance-designed:** 9 criteria, measurement-driven, root-cause-focused

---

## 🎯 Phase Goal (from ROADMAP.md)

**Goal:** Audit and close accumulated DB and observability debt before AI platform work begins.

**Why this matters:** v2.8 AI platform (LiteLLM, DSPy, Zep memory, evolvable agents) requires a solid foundation. Silent data loss, corrupted metrics, and service inconsistencies will cause invisible regressions during LLM optimization.

**Dependencies:** Phase 106 (Foundation Hardening) — **COMPLETE**

---

## 📋 What Phase 106 Already Delivered (DON'T RE-PLAN THIS)

✅ **Hot path span coverage:** `_process_bar_inner()` wrapped in `observed_span("pipeline.process_bar_inner")`
✅ **Per-tier latency histogram:** `INTELLIGENCE_PIPELINE_TIER_LATENCY_MS` with tier labels (i1, i2_i6)
✅ **Backpressure:** `enqueue_blocking()` with timeout for intel+journal topics
✅ **O(1) state lookup:** `_states_by_key` secondary index in PluginStateManager

**Source:** `.planning/phases/phase-106/106-04-SUMMARY.md`

**Implication:** Phase 107 builds on this foundation — don't re-plan hot path spans or tier latency.

---

## 🔴 Critical Context: Why Phase 107 Exists

### **Source of Truth:** `docs/ideas/architectural-weakness-assessment.md`

**Key Findings Driving Phase 107:**

#### **CRITICAL — Data Loss (Alpha Leakage)**
- **HF-2:** `ctx_writer_agent.py:343,351` — `.inc()` AttributeError → buffers never flush → CTX events lost
- **HF-3:** `llm_writer_service.py:695` — `self._pool` AttributeError → parse-success back-fills dropped
- **HF-4:** `feature_writer_agent.py:406-414` — DB connection failure → `db_manager = None` → ghost-run → 6.25% data loss
- **HF-11:** `ctx_writer_agent.py` skips `super()._teardown()` → final flush never runs on shutdown
- **#5/CL-3:** Intelligence topic drops silently on QueueFull → backpressure missing

#### **CRITICAL — Observability Gaps (Can't Detect Regressions)**
- **#13:** All 37 services have zero OTel span coverage → distributed tracing dark
- **#14:** Per-stage latency (I2-I6) completely absent → can't alert on I4 regression
- **#24:** `"agent"` vs `"agent_id"` label split → fleet-wide dashboards broken
- **HF-8:** 5 shadow metrics use `up_down_counter` with absolute values → dashboard permanently wrong

#### **HIGH — Service Inconsistency (Invisible Failures)**
- **#15:** 3 services bypass `DatabaseManager.create_pool()` → missing JSONB codecs → double-serialization
- **#16:** `signal_replay_auditor` and `bar_replay_provider` don't use `BaseAgent` → missing SIGTERM handling, stall detection, DLQ
- **#18:** `_DAG_ORDER` missing 11 deployed services → ML batch failures invisible
- **#20:** Cyclic L5 dependency → undefined restart order after dual failure

#### **HIGH — Technical Debt (Complexity Drag)**
- **#4:** Dead AI foundations: `ShadowRecorder`, `GuardrailsValidator`, TEMPLATE bug
- **#2:** 8 dead Settings fields (`SWARM_QUEUE_TIMEOUT_MS`, `LLM_RATE_LIMIT_*`, etc.)
- **#22:** Shadow promotion queries train on shadow signals → contaminated statistics
- **#23:** Swarm agents query `signal_ledger` but have no rows → governance structurally dead

---

## 📊 Phase 107 Scope: 9 Criteria in 3 Waves

### **Wave 1: Service Consistency (30%)** — Blocker for everything else

**HYGIENE-07: BaseAgent Lifecycle Adoption**
- **Target:** Migrate 2 services to `BaseAgent`: `signal_replay_auditor_agent`, `bar_replay_provider_agent`
- **Why:** Custom lifecycle = missing SIGTERM handling, stall detection, DLQ routing
- **Success:** `base_agent_adoption_pct = 100%` (currently ~90%, 38/42 services)

**HYGIENE-08: DatabaseManager Pool Standardization**
- **Target:** Fix 3 services bypassing `DatabaseManager.create_pool()`: `swarm_ledger_writer_agent`, `bar_replay_provider_agent`, `signal_replay_auditor_agent`
- **Why:** Missing JSONB codecs → silent double-serialization → corrupted data
- **Success:** `database_manager_adoption_pct = 100%` (currently ~75%, 3 bypass services)

**HYGIENE-09: Agent ID Label Standardization**
- **Target:** Standardize all metrics on `agent_id` label (not `agent`)
- **Why:** Fleet-wide dashboards impossible with split labels
- **Success:** `agent_id_label_consistency_pct = 100%` (currently ~50/50 split)

### **Wave 2: Silent Failure Elimination (35%)** — Blocker for AI platform

**HYGIENE-01: Writer Flush Path Observability**
- **Target:** Wrap all `*_writer_agent.py:_flush()` in `observed_span("writer.flush")`
- **Why:** Flush failures invisible → don't know when persistence is broken
- **Success:** `writer_flush_span_coverage_pct = 100%` (currently 0/5 writers)

**HYGIENE-02: Metric Type Correctness**
- **Target:** Fix 5 shadow metrics (up_down_counter → gauge), fix latency metrics (counter → histogram)
- **Why:** Wrong metric types → alerts fire incorrectly → we wake up at 3am for non-issues
- **Success:** `metric_type_violation_count = 0` (currently 5 violations)

**HYGIENE-03: Silent Data Loss Elimination**
- **Target:** Fix AttributeError bugs (HF-2, HF-3), prevent ghost-run (HF-4), add super()._teardown() (HF-11)
- **Why:** Silent data loss = alpha leakage = trading on incomplete information
- **Success:** `silent_data_loss_rate = 0.00%` (currently 6.25% in feature_writer)

### **Wave 3: Complexity Reduction (35%)** — Efficiency

**HYGIENE-04: DAG Topology Correctness**
- **Target:** Add 11 missing services to `_DAG_ORDER`, fix systemd dependencies, resolve cyclic dependency
- **Why:** Wrong restart order → race conditions → silent data corruption
- **Success:** `dag_completeness_pct = 100%` (currently 74%, 32/43 services)

**HYGIENE-05: Dead Code Elimination**
- **Target:** Delete `ShadowRecorder`, `GuardrailsValidator`, 8 dead Settings fields, fix TEMPLATE agent
- **Why:** Dead code inflates maintenance burden → new engineers learn wrong patterns
- **Success:** `dead_code_violation_count = 0` (currently 13 violations)

**HYGIENE-06: Shadow Registry Integrity**
- **Target:** Fix promotion/demotion queries (add `AND is_shadow = FALSE`), skip swarm agent ledger queries
- **Why:** Shadow signals contaminate live track → we optimize for wrong objective function
- **Success:** `shadow_governance_integrity_violations = 0` (currently 2 query violations)

---

## 🎓 Renaissance Engineering Principles (How to Approach)

**Jim Simons' demands:**
1. **"Zero tolerance for silent failures"** — data loss = alpha leakage
2. **"If you can't measure it, you don't understand it"** — instrumentation before optimization
3. **"Every component must earn its keep"** — justify existence with measurements
4. **"Simplicity over complexity"** — smallest fix that solves the problem
5. **"Technical debt is quantifiable"** — measure it, don't guess at it

**Design principles:**
- **Modularity:** Each concern has a single owner
- **Reuse:** If it exists twice, extract it
- **Separation of concerns:** Analytics in plugins, transport in services
- **DAG discipline:** No cycles, clear dependencies, restart order is declarative
- **Efficiency vs simplicity:** Right-sized for the problem at hand
- **Compute costs:** Every byte written, every query executed metered
- **Maintenance burden:** Surface area matters

**Planning approach:**
- **Measure first** — quantify the problem before fixing
- **Root cause focus** — fix the process, not just the symptom
- **Automated enforcement** — CI gates, pre-commit hooks, not manual checklists
- **Verification queries** — success is binary (SQL query returns TRUE/FALSE)

---

## 📁 Key Files to Reference During Planning

### **Must Read** (Source of truth for findings)
- `docs/ideas/architectural-weakness-assessment.md` — All findings with file locations and line numbers

### **Will Reference** (Specific implementations)
- `src/core/agent/base.py` — BaseAgent lifecycle (what to migrate to)
- `src/core/database_manager.py` — DatabaseManager pool (what to use)
- `src/observability/metrics.py` — Current metric definitions (what to fix)
- `src/observability/spans.py` — Span infrastructure (patterns to follow)
- `services/service_auditor_agent.py` — DAG order (what to add)

### **Target Files** (What gets modified)
- `services/signal_replay_auditor_agent.py` — HYGIENE-07, HYGIENE-08
- `services/bar_replay_provider_agent.py` — HYGIENE-07, HYGIENE-08
- `services/swarm_ledger_writer_agent.py` — HYGIENE-03, HYGIENE-08
- `services/ctx_writer_agent.py` — HYGIENE-01, HYGIENE-03
- `services/llm_writer_service.py` — HYGIENE-01, HYGIENE-03
- `services/feature_writer_agent.py` — HYGIENE-01, HYGIENE-03
- `services/shadow_auditor_agent.py` — HYGIENE-02, HYGIENE-06
- `src/config/settings.py` — HYGIENE-05 (dead fields)
- `src/core/ml/shadow.py` — HYGIENE-05 (ShadowRecorder)
- `src/core/llm/guardrails.py` — HYGIENE-05 (GuardrailsValidator)
- `src/intelligence/ai/TEMPLATE_agent.py` — HYGIENE-05 (TEMPLATE bug)

---

## 🚫 What NOT to Do (Common Mistakes)

**❌ Don't re-plan Phase 106 work:**
- Hot path spans (already done in 106-04)
- Tier latency histograms (already done in 106-04)
- Backpressure enqueue_blocking (already done in 106-04)
- O(1) state lookup (already done in 106-04)

**❌ Don't expand scope beyond 9 criteria:**
- No Kafka topic lifecycle (process fix, not Phase 107)
- No test infrastructure health (design debt, not infrastructure)
- No documentation audit (automate instead)
- No health monitor standardization (too low priority)

**❌ Don't add new features:**
- No new metrics beyond what's specified
- No new dashboards (fix existing data)
- No new services (consistency only)

---

## ✅ Success Criteria (Binary Verification)

**Single SQL query determines success:**
```sql
SELECT
  base_agent_adoption >= 100 AND
  db_manager_adoption >= 100 AND
  agent_id_consistency >= 100 AND
  writer_flush_coverage >= 100 AND
  metric_violations = 0 AND
  data_loss_rate = 0.00 AND
  dag_completeness >= 100 AND
  dead_violations = 0 AND
  shadow_violations = 0
  as phase_107_success;
```

**If query returns TRUE → Phase 107 complete → unblock v2.8 AI platform**
**If query returns FALSE → Phase 107 incomplete → fix gaps**

---

## 🎯 Current State Snapshot (Baseline Before Phase 107)

```bash
# Quick assessment commands
grep -c "class.*Agent.*BaseAgent" services/*.py  # Expected: ~38/42 (90%)
grep -r "asyncpg.create_pool" services/ | grep -v "database_manager.py" | wc -l  # Expected: 3
grep -r '"agent":' services/ | wc -l  # Expected: split with agent_id
grep -c "observed_span.*flush" services/*_writer_agent.py  # Expected: 0
grep "up_down_counter" src/observability/metrics.py | grep -E "SHADOW_WIN_RATE|SHADOW_N_RESOLVED|SHADOW_EV_R" | wc -l  # Expected: 5
```

**Expected baseline:**
- BaseAgent adoption: ~90% (38/42 services)
- DatabaseManager bypass: 3 services
- Agent ID label split: ~50/50
- Writer flush spans: 0/5 writers
- Shadow metric violations: 5
- DAG completeness: 74% (32/43 services)
- Dead code violations: 13
- Shadow governance violations: 2

---

## 🚀 Next Steps

1. **Read this CONTEXT.md first** (after `/clear`, this is what survives)
2. **Read `docs/ideas/architectural-weakness-assessment.md`** (source of truth)
3. **Read `.planning/phases/phase-106/106-04-SUMMARY.md`** (what was just delivered)
4. **Run `/gsd:discuss-phase 107`** — gather context, clarify approach
5. **Run `/gsd:plan-phase 107`** — create detailed plans with verification loops

**Key questions for discuss-phase:**
- Are all 9 criteria the right set? (Renaissance priority: P1 > P2 > P3 > P4)
- Should Wave 1 (service consistency) be executed separately or together with Wave 2?
- Any dependencies between criteria that affect wave sequencing?
- Are there any HYGIENE criteria that should be deleted/deferred?

---

**Last updated:** 2026-05-25 (Renaissance redesign: 9 criteria, 3 waves, measurement-driven)
