# Architecture Audit Design

**Version:** 1.0
**Last Updated:** 2026-05-23
**Date:** 2026-05-23
**Status:** Approved - ready to execute next session
**Output:** Updated `docs/research/architectural-weakness-assessment.md`
**Framing:** Renaissance/Simons — audit the machine for alpha leakage, information destruction, and feedback loop gaps. Every piece of complexity that can be removed should be removed.

---

## Purpose

A full-spectrum architectural audit of IndicAgent across 7 domains, executed as 7 parallel `gsd-codebase-mapper` agents feeding into a synthesis agent. The audit extends the existing `docs/research/architectural-weakness-assessment.md` with new numbered findings, a ranked improvement backlog, and a simplification readiness assessment for v2.8.

The existing doc covers compute (#1), settings (#2), persistence (#3), dead AI foundations (#4), queue drops (#5), and error handling (#6-#12). This audit adds fresh coverage of telemetry alignment, code reuse, DAG correctness, shadow governance, and cross-cutting simplification opportunities.

---

## Framing Principles (apply to all agents)

Every finding should answer one of three questions:

1. **Alpha leakage** - does this add latency, reduce throughput, or degrade signal quality?
2. **Information destruction** - does this lose, suppress, or corrupt data flowing through the machine?
3. **Feedback loop gap** - does this prevent the system from observing, measuring, or correcting itself?

A finding that doesn't map to one of these three is noise. Prioritize accordingly.

The fourth question for Agent 7 only:
4. **Expansion drag** - does this block or complicate the next milestone (AI platform, evolvable agents, symbol scaling)?

---

## Agent Roster

8 agents total. Agents 1-7 run in parallel. Agent 8 (synthesis) runs after all 7 complete.

---

### Agent 1: Telemetry / OTel Coverage

**Focus files:** `src/observability/`, all `services/*.py`, `src/core/agent/`

**Questions to answer:**
- Which services have zero OTel span coverage on their critical path?
- Are counter/histogram/gauge labels consistent across services? Known inconsistency: `agent` vs `agent_id` on `agent_last_message_timestamp_seconds`.
- Are there duplicate metrics measuring the same thing under different names?
- Is the delta/cumulative pattern applied correctly everywhere? (OTel delta pattern bug was previously fixed - verify it held.)
- Which failure paths emit no telemetry at all (silent failures with no counter increment)?
- Are latency histograms present for every pipeline stage, or only at the aggregate level?
- Is there any remaining `prometheus_client` import (fully removed in Phase 83 - verify clean)?
- What metrics exist in `metrics.py` that are never read by Grafana or any downstream consumer?

**Renaissance lens:** Telemetry is the feedback loop. A service with no spans is a black box. A black box cannot be improved systematically. Find every black box.

**Output format:** Numbered findings with severity (CRITICAL/HIGH/MEDIUM/LOW), file + line references, and a one-line fix recommendation.

---

### Agent 2: Code Reuse / Base Abstractions

**Focus files:** `src/core/agent/`, `services/*.py`, `src/persistence/repository/`, `src/core/`

**Questions to answer:**
- Is `_setup_with_retry()` (or equivalent bootstrap retry logic) duplicated across multiple services? The existing assessment flagged 3x duplication - confirm and find all instances.
- What health-check patterns exist and how many variations are there? Should there be one.
- What DLQ routing patterns exist? Are they centralized in `BaseWriterAgent` or re-implemented per writer?
- What error counter patterns exist? Are they consistent or does every service roll its own label schema?
- Are there service pairs that are structurally near-identical (same base, same flow, same Kafka in/out pattern) that could share a parameterized base class?
- What utility functions exist in multiple files (`format_iso_ts`, UTC timestamp construction, etc.) that should be in `service_utils.py` and aren't?
- What does `BaseWriterAgent` currently provide, and what should it provide that it doesn't?
- Are there any `src/core/` modules that are imported by only one service (not really "core")?

**Renaissance lens:** Copy-paste is technical debt with interest. Every duplicated pattern is a maintenance surface that diverges silently. Find the patterns that belong in base layers.

**Output format:** Numbered findings with severity, affected files (list all instances), and consolidation recommendation.

---

### Agent 3: DAG Correctness and Startup Order

**Focus files:** `services/service_auditor_agent.py` (`_DAG_ORDER`, `_LAG_THRESHOLDS`, `_AGENT_ID_TO_UNIT`), all `services/*.py` Kafka topic subscriptions, `production/systemd/`

**Questions to answer:**
- Is `_DAG_ORDER` in `service_auditor_agent.py` complete and accurate? List any services present in `services/` that are missing from `_DAG_ORDER`.
- Does the L1-L10 ordering correctly model actual data dependencies? Can an L6 service start processing before its L5 dependencies have produced any output?
- Are there health gates between layers, or do services blindly subscribe to topics and silently receive nothing on cold start?
- Do any services subscribe to a topic that no currently-running service publishes to? (dead subscriptions)
- Do any services publish to a topic that no currently-running service consumes? (dead publishers)
- Are `_LAG_THRESHOLDS` calibrated to actual expected throughput, or are they defaults that were never tuned?
- Are ML batch services (`ml-training`, `ml-orchestrator`, etc.) modeled correctly in the DAG as timer-triggered vs always-on?
- Is `_AGENT_ID_TO_UNIT` consistent with actual systemd unit names in `production/systemd/`?

**Renaissance lens:** A machine with incorrect wiring produces incorrect output silently. DAG errors are the hardest class of bug to detect because the data looks plausible. Find every wiring inconsistency.

**Output format:** Numbered findings. For dead subscriptions/publishers, include the topic name, the subscriber/publisher service, and what should be there instead.

---

### Agent 4: Shadow Governance Consistency

**Focus files:** `src/intelligence/register_plugins.py`, `services/intelligence_pipeline_agent.py`, `src/core/`, `src/intelligence/trading/`, `src/persistence/repository/`, all agent files that produce I7 signals

**Questions to answer:**
- Is `shadow_registry_ensure()` called at startup for every agent that produces signals? List any signal-producing code paths where it is missing.
- Is the promotion gate (`n >= 100` AND `bootstrap_ci_lower(pnl_r) > 0.0`) applied uniformly, or are there code paths that bypass it?
- Is the demotion gate (EV[R] < -0.05 for 3 consecutive cycles) actually wired and firing, or is it defined but not called?
- CIS weight loading: is `weight_updater.py` actually seeding from DB on startup, or does the pipeline always start from bootstrap weights? (Known bug in memory - verify current state of fix.)
- Is shadow suppression (`regime_suppressed` status) applied consistently in all I7 aggregation paths, or only in the main pipeline?
- Is the `shadow_registry` DB table schema consistent with what all writers are inserting into it?
- Are there signals that flow through to `signal_ledger` without ever passing through shadow governance?

**Renaissance lens:** Shadow governance is the machine's self-correction mechanism. A governance system with gaps is worse than no governance - it creates false confidence. Find every bypass.

**Output format:** Numbered findings with severity. For missing `shadow_registry_ensure()` calls, include the exact file and function where it should be added.

---

### Agent 5: Compute and Latency

**Focus files:** `services/intelligence_pipeline_agent.py`, `src/intelligence/register_plugins.py`, `src/core/plugin_circuit_breaker.py`, `src/observability/metrics.py`, `src/core/agent/`

**Questions to answer:**
- Where does time actually go in a bar processing cycle? Map the per-stage latency: Kafka consume → I1 → I2 → I3 → I4 → I5 → I6 → I7 → publish. Which stages have per-plugin latency measurement and which don't?
- Is `put_nowait` still the output queue strategy? Is there any backpressure or blocking on full queue?
- Is `PluginCircuitBreaker` (`src/core/plugin_circuit_breaker.py`) actually wired into the intelligence pipeline, or is it defined but unused? (Existing assessment flagged this as a fix candidate.)
- Thread pool: 12 workers for 132 plugins. What's the actual utilization pattern? Are any tiers bottlenecked on thread pool capacity?
- Are there plugins whose output is consumed by no downstream tier? (dead compute)
- Are there any synchronous DB calls on the hot path (bar processing loop)? The design says the real-time pipeline never touches the DB directly - verify this holds.
- Are the 6 DB cache refresh loops (`perf_weights`, `shadow_cache`, `drift_penalties`, `CIS_weights`, `calibration_curves`, `TOD_multipliers`) all running at appropriate intervals, or are any polling too frequently?
- What's the current line count and responsibility surface of `intelligence_pipeline_agent.py`? Has the god class decomposition from the existing assessment progressed?

**Renaissance lens:** Latency is alpha. Every millisecond you spend on dead compute, unnecessary polling, or unbackpressured queues is edge leaked. Map every microsecond on the hot path.

**Output format:** Numbered findings. For latency findings, include the measured or estimated cost. For dead compute, include the plugin name and which tier it belongs to.

---

### Agent 6: Persistence Patterns

**Focus files:** `src/persistence/repository/`, all `services/*_writer_agent.py` and `services/*_writer_service.py`, `production/migrations/`

**Questions to answer:**
- Which of the 13 writer services still use positional tuple parameters in SQL queries? List each with file + line.
- Which writers still do per-row DB calls instead of batch inserts? What's the estimated write volume per writer that makes this a problem?
- Is the `_parse_payload` return contract (`None` for unparseable payload, `[]` for all-invalid signals, non-empty list for valid signals) followed correctly in all writers? Any cases where `None` is returned for a valid-but-empty case (causing double DLQ)?
- Is DLQ routing wired in all 13 writers, or only in some?
- Post-migration 093 and 094: are there any services still referencing dropped columns? (Existing assessment had a fix for this - verify it held.)
- Are there writer services whose Pydantic validation models are missing or incomplete?
- Are error counters consistent across writers? (Same label schema, same metric names?)
- Are there any writers with silent `except` blocks that swallow errors without DLQ or counter?

**Renaissance lens:** Persistence is where information either survives or is lost forever. A writer that silently swallows an error is an information destruction event. Find every one.

**Output format:** Numbered findings. For positional tuple findings, include the exact file, function, and line count of the tuple. For DLQ gaps, include the writer name and the code path where errors are swallowed.

---

### Agent 7: Simplification and v2.8 Readiness

**Focus files:** Full codebase - `services/`, `src/`, `src/core/`, `src/intelligence/`, `src/config/`

**Framing:** Assume the next milestone (v2.8) adds: an AI agent platform (LiteLLM/Instructor/PydanticAI), evolvable agents with a registry, Zep memory integration, DSPy optimization, and a significant increase in tracked symbols. Ask: *what in the current architecture creates drag against that expansion?*

**Questions to answer:**
- What dead code exists that can be deleted with zero functionality loss? Known candidates: `LineageRecorder` (107 lines, zero production instantiations), graduation loop (`asyncio.sleep(900)` doing nothing), `_on_error`/`_on_guardrail_violation`/`_audit_payload` no-op hooks.
- What services are structurally pass-through (receive from Kafka, do minimal transformation, publish to another topic) and could be eliminated or merged?
- What abstractions exist that add indirection without adding clarity or capability? Where is the code harder to understand because of an abstraction rather than easier?
- What configuration is hardcoded that should be data-driven (DB, YAML, env)? The `Settings` god object is known - are there others?
- What would break first if symbol count doubled (58 → 116)? What would break first if bar frequency doubled?
- What in the current codebase assumes a single AI provider or a fixed agent topology? Where would adding a new AI agent require touching more than 2 files?
- What patterns would need to exist in base classes to support evolvable/self-modifying agents? Are there hooks for this, or would it require invasive changes?
- What is the minimum set of changes that would make the codebase materially easier to extend for v2.8?

**Renaissance lens:** A bigger machine built on a tangled foundation breaks in unexpected ways. Simplification before expansion is not cleanup - it is load-bearing work. Find everything that will become a bottleneck when the next layer lands.

**Output format:** Two sections:
1. **Delete/merge candidates** - items that can be removed with zero functionality loss, ordered by lines of code reclaimed
2. **v2.8 friction points** - specific files/patterns that will create drag during v2.8 implementation, with a one-line description of the required change

---

### Agent 8: Synthesis

**Runs after all 7 domain agents complete.**

**Inputs:** All 7 domain findings docs at `docs/architecture/audit-2026-05-23-<domain>.md`

**Task:** Produce an updated `docs/research/architectural-weakness-assessment.md` that:

1. Preserves all existing findings (#1-#12) with their current status
2. Adds new findings as #13 onward from domain agent outputs, deduplicated and consolidated
3. Updates any existing finding where new evidence confirms, contradicts, or adds nuance
4. Produces a **Renaissance-ranked backlog** using this priority order:
   - **P1 - Alpha leakage:** latency, throughput, signal quality degradation
   - **P2 - Information destruction:** silent failures, data loss, swallowed errors
   - **P3 - Feedback loop gaps:** missing observability, undetectable failures
   - **P4 - Complexity drag:** abstraction overhead, dead code, copy-paste surface
5. Produces a **v2.8 readiness section** summarizing Agent 7's findings as: "do this before v2.8 starts", "do this during v2.8", "safe to defer"

**Output files:**
- Updated `docs/research/architectural-weakness-assessment.md` (in-place update)
- `docs/architecture/audit-2026-05-23-synthesis.md` (synthesis working doc, preserved for reference)

---

## Execution Plan (next session)

```
Session start
├── Spawn Agents 1-7 in parallel (gsd-codebase-mapper)
│   Each writes to docs/architecture/audit-2026-05-23-<domain>.md
│
└── When all 7 complete:
    └── Spawn Agent 8 (synthesis)
        ├── Reads all 7 domain docs
        ├── Updates architectural-weakness-assessment.md
        └── Writes synthesis working doc
```

**Invoke with:** `/gsd-map-codebase` for each domain agent, then a general-purpose synthesis agent.

**Expected duration:** One session. Agents 1-7 run in parallel so total wall time is approximately the longest single-domain audit.

---

## Success Criteria

The audit is complete when:

1. All 7 domain docs exist at `docs/architecture/audit-2026-05-23-<domain>.md`
2. `architectural-weakness-assessment.md` has been updated with new findings and a Renaissance-ranked backlog
3. The v2.8 readiness section exists and distinguishes pre-v2.8 work from during/deferred
4. Every finding has: severity, file + line reference, one-line fix recommendation, Renaissance category (alpha leakage / information destruction / feedback gap / complexity drag)
