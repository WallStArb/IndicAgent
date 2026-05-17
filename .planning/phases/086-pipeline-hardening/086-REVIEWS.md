---
phase: 086
reviewers: [gemini, codex, ollama]
reviewed_at: 2026-05-17T00:00:00Z
plans_reviewed:
  - 086-01-PLAN.md
  - 086-02-PLAN.md
  - 086-03-PLAN.md
  - 086-04-PLAN.md
note: claude skipped (self — running in Claude Code)
---

# Cross-AI Plan Review — Phase 086: Pipeline Hardening

---

## Gemini Review

# Phase 086: Pipeline Hardening Review

## Summary
The proposed plans effectively address the hardening requirements by introducing per-plugin circuit breakers, explicit validation gates, and improved stall detection. The architectural approach is generally sound, leveraging existing infrastructure (OTel, systemd, Prometheus) to minimize complexity. The use of a pending DLQ buffer in Plan 086-02 is a necessary pragmatic choice to reconcile synchronous parsing with asynchronous I/O, and the proposed stall detection in Plan 086-03 demonstrates a clear understanding of the need to avoid race conditions with existing in-process watchdogs.

## Strengths
- **Pragmatic Integration**: Plans leverage existing OTel and Prometheus structures rather than introducing new dependencies.
- **Circuit Breaker Strategy**: The lazy factory approach and integration with `src/observability/circuit_breaker.py` are cleaner than the existing `src/core` implementation.
- **DLQ Pattern**: The buffer-and-drain pattern in Plan 086-02 correctly manages the impedance mismatch between sync signal validation and async DLQ ingestion.
- **Stall Safety**: The 60-second grace period for stall detection (360s vs 300s watchdog) correctly prioritizes stability and prevents premature service restarts.

## Concerns
- **Plan 086-01 (Circuit Breaker State Persistence):** The current plan stores the `CircuitBreaker` instance in `__init__` as an in-memory dictionary. If the agent restarts (e.g., due to a crash), all circuit breaker state is lost, potentially leading to immediate re-triggering of failed plugins. (**MEDIUM**)
- **Plan 086-03 (Service Auditor Performance):** `_fetch_stalled_agents` queries Prometheus for *every* agent on every check cycle. If the number of agents grows significantly, this could lead to high load on the metrics server or long-running audit cycles. (**LOW**)
- **Plan 086-04 (Prometheus Query Reliance):** The system health endpoint executes four sequential Prometheus queries via `aiohttp`. If Prometheus is slow or down, this endpoint could hang or timeout. While it has a 3-second timeout, this is effectively a synchronous block in the API thread. (**MEDIUM**)
- **Plan 086-02 (Signal Payload Modification):** If `validate_signal` is updated in the future to be stricter, there is a risk that valid signals are routed to the DLQ. Ensure the DLQ includes sufficient metadata to allow for easy inspection and potential reprocessing. (**LOW**)

## Suggestions
- **Circuit Breaker State:** Consider persisting the "OPEN" status of circuit breakers in a lightweight cache or at least document this as a known limitation.
- **Health Endpoint Optimization:** Consider caching the results of the Prometheus queries in memory for 10-15 seconds to reduce load and improve responsiveness.
- **Auditor Scalability:** If the number of agents increases, replace the per-check Prometheus query with a single aggregate query that returns all status metrics at once.
- **DLQ Enrichment:** Ensure `_send_to_dlq` logs the specific validation failure message alongside the original payload to make debugging easier.

## Risk Assessment
**Risk Level: LOW**

The plans are well-aligned with the goal of "failing loudly" and hardening the boundaries. The most significant risks are operational (e.g., Prometheus query latency affecting health checks) and state persistence (e.g., CB reset on restart), both of which are manageable and do not threaten the overall integrity of the platform.

---

## Codex Review

## Summary

Overall, the phase direction is sound: the plans target the right failure boundaries for pipeline hardening, and they mostly respect existing architecture choices like OTel metrics, asyncpg writers, Redpanda topics, and systemd recovery. The biggest risks are not scope creep but semantic mismatches with current code: the selected circuit breaker API will not recover or reset correctly if used as planned, signal validation may not DLQ invalid-only payloads promptly, OBS-03 appears to query the wrong metric label, and OBS-02 likely mounts at the wrong endpoint path.

## Plan 086-01: Pipeline Agent Hardening

### Strengths

- Uses the existing lightweight `src/observability/circuit_breaker.py`, avoiding the heavier state-manager implementation.
- Preserves bar-level continuity by continuing to use `asyncio.gather(..., return_exceptions=True)`.
- Blocking only the signal-output path is a good prioritization: malformed or dropped signals are higher risk than journal drops.
- Making checkpoint writes raise is directionally aligned with "fail loudly".

### Concerns

- **HIGH:** The proposed manual `record_failure()` use does not reset failures on success. Intermittent failures will eventually open the breaker even if the plugin usually succeeds.
- **HIGH:** Checking `cb.state == OPEN` before dispatch will never transition to `HALF_OPEN`, because the lightweight breaker only performs `OPEN -> HALF_OPEN` inside `call()` in `src/observability/circuit_breaker.py:35`.
- **HIGH:** `_publish_signals_or_dlq()` is currently synchronous in `services/intelligence_pipeline_agent.py:1564`. Converting it to await `_enqueue_blocking()` requires changing its signature and every call site.
- **MEDIUM:** Blocking enqueue can stall `_run_i7_inner()` indefinitely if the drain loop stops making progress. Needs observability and probably a timeout/stall log.
- **MEDIUM:** Circuit breaker metrics only set `OPEN`; no plan records `CLOSED` or `HALF_OPEN`, so Grafana can show stale open states after recovery.
- **LOW:** `_write_local_checkpoint()` is only called during `_teardown()`, so this does not harden per-bar durability.

### Suggestions

- Wrap plugin execution through the breaker's `call()` path, or extend the lightweight breaker with `allow_request()`, `record_success()`, and explicit transition reporting.
- Emit state metrics on every transition: closed `0`, open `1`, half-open `2`.
- Include skipped-open counts/logs so "skipped for subsequent bars" is visible, not only the first open transition.
- Make `_publish_signals_or_dlq()` async and update `_run_i7_inner()` to `await` it.
- Add tests for: three repeated plugin exceptions opens breaker, open breaker skips plugin, timeout permits half-open retry, success closes breaker.

### Risk Assessment

**HIGH.** The current plan likely opens breakers but does not recover them or reset failure counts correctly. That would satisfy part of the first success criterion but could create permanent plugin suppression.

## Plan 086-02: Signal Writer Validation Gate

### Strengths

- Puts validation at the correct final persistence boundary before `signal_ledger`.
- Reuses canonical `validate_signal()` from `src/intelligence/trading/signal_schema.py`.
- DLQ topic choice is consistent with existing `topic_signal_writer_dlq()`.
- Partitioning valid and invalid signals is better than rejecting an entire mixed payload.

### Concerns

- **HIGH:** Invalid-only payloads may not be DLQ'd by the pending-buffer design. `BaseWriterAgent` only flushes when rows are buffered; if `_parse_payload()` returns `None`, the whole payload is DLQ'd by the base loop, while `self._invalid_signals` may remain pending until a future valid flush.
- **HIGH:** The pending invalid list is process memory, not offset-coupled durability. A crash before a later flush can lose per-signal DLQ records.
- **MEDIUM:** `validate_signal()` requires fields like `type`, `timeframe`, `risk_reward_ratio`, and `invalidation_conditions`; verify all I7 ranked signals still carry those fields after ranking/enrichment.
- **MEDIUM:** `_payload_to_ledger_entries()` can coerce malformed values with defaults, so validation must happen before conversion and must validate the exact signal dictionaries being converted.
- **LOW:** `list[dict]` invalid buffer is unbounded under sustained invalid traffic.

### Suggestions

- Prefer overriding the writer `_run()` for this agent so validation and `await _send_to_dlq()` happen in the same message-processing transaction before buffering valids.
- If keeping the sync parse design, return a sentinel/empty valid row path carefully so invalids are drained even when no valid rows exist.
- DLQ the invalid signal with envelope metadata: source topic, payload symbol/tf/bar_ts, signal_id if present, validation reason.
- Add tests for mixed valid/invalid payload, invalid-only payload, and malformed signal that would currently be coerced into a ledger row.

### Risk Assessment

**HIGH.** The intent is correct, but the pending-buffer approach has durability and invalid-only edge-case gaps that directly affect the second success criterion.

## Plan 086-03: Agent Stall Detection

### Strengths

- Uses existing OTel liveness metric instead of adding `prometheus_client`.
- A 360-second external threshold avoids racing the 300-second in-process watchdog.
- Reuses the service auditor's existing systemd restart mechanism.
- Cold-start false-positive protection is explicitly called out.

### Concerns

- **HIGH:** The existing liveness gauge uses label `agent`, not `agent_id`, in `src/core/agent/base.py`. The plan maps by `agent_id` through `_AGENT_ID_TO_UNIT`, so it will likely miss all series.
- **HIGH:** Prometheus-driven stall detection may restart agents during expected quiet periods unless gated by market/session activity or agent-specific traffic expectations.
- **MEDIUM:** Adding `last_processed_at` to `BaseAgent` does not help Prometheus-based detection unless exposed somewhere else.
- **MEDIUM:** `_AGENT_ID_TO_UNIT` currently mixes naming styles. The new query must normalize labels carefully or update mappings.
- **LOW:** Need to ensure repeated stale checks do not restart the same unit every 15 seconds; use existing `ServiceState` escalation/debounce logic.

### Suggestions

- Query `agent_last_message_timestamp_seconds` and read `metric["agent"]`, or change the emitted label consistently across code and dashboards.
- Limit stall detection to agents with `max_idle_seconds > 0` or those expected to consume continuously during active sessions.
- Use `ServiceState` to debounce restart attempts and escalation.
- Log the observed timestamp, age, metric label, and mapped unit for auditability.
- Add unit tests for cold start, stale metric, missing metric, unknown label, and recently restarted unit.

### Risk Assessment

**MEDIUM-HIGH.** The design is useful, but the label mismatch can make it nonfunctional, while insufficient quiet-period gating can cause unnecessary restarts.

## Plan 086-04: System Health Endpoint

### Strengths

- Aggregating Prometheus into one API endpoint is a practical dashboard/backend integration.
- Per-query degradation is appropriate for a health summary endpoint.
- Uses timezone-aware `datetime.now(UTC)`.
- Keeps the route small and isolated to `src/api/routes/health.py`.

### Concerns

- **HIGH:** The route is mounted at `/health`, not `/api/health`, in `src/api/main.py:131`. The endpoint will likely be `/health/system`, not `/api/health/system`.
- **MEDIUM:** Planned query names need verification. Existing lag metric is `persistence_consumer_lag_records`, not `persistence_consumer_lag`.
- **MEDIUM:** `dlq_messages_total` is a counter, not depth. Calling the returned field `dlq_depth` may be misleading unless querying Redpanda/Kafka lag or a DLQ table count.
- **MEDIUM:** Creating a new `aiohttp.ClientSession` per request is acceptable at low volume but not ideal; shared app lifecycle session would be cleaner.
- **LOW:** Blanket `except Exception: pass` hides broken Prometheus queries. Returning partial fields plus a `query_errors` list would improve operability without returning 503.

### Suggestions

- Confirm the public path and either document `/health/system` or update router prefix intentionally.
- Use exact metric names from `src/observability/metrics.py`: `persistence_consumer_lag_records`, `agent_last_message_timestamp_seconds`, `signal_replay_unresolved_gauge`, and `dlq_messages_total`.
- Rename `dlq_depth` to `dlq_messages_total` unless a true depth source exists.
- Include `"status": "healthy" | "degraded"` and a `query_errors` field for partial failures.
- Add one route test that monkeypatches Prometheus responses and verifies timestamp conversion.

### Risk Assessment

**MEDIUM.** The endpoint is low blast-radius, but wrong route path and metric names would make it fail the OBS-02 intent operationally.

## Overall Risk Assessment

**MEDIUM-HIGH.** The plans target the phase goals, but PIPE-01 and PIPE-02 need design corrections before implementation. The circuit breaker must support success reset and half-open recovery, and the signal writer must DLQ invalid signals transactionally before offset commit. OBS-03 and OBS-02 are smaller changes but need metric-label and route-path fixes to avoid silent nonfunctionality.

---

## Ollama Review (gemma4:e4b)

## Cross-AI Plan Review: Pipeline Hardening (Phase 086)

### Overview Summary

Overall, Phase 086 presents a robust set of hardening steps critical for moving the system into production reliability. The plans demonstrate excellent awareness of asynchronous flow control (Plan 086-02) and modern distributed systems patterns (Plan 086-01 and 086-03). The architectural choices -- like using the pending buffer pattern and coupling service auditing with Prometheus metrics -- are technically advanced and appropriate for the complexity of IndicAgent. However, the plans contain significant details concerning error propagation, state management, and timing gaps that require immediate refinement to ensure the system handles failure gracefully and consistently across all components.

### Plan 086-01: Pipeline Agent Hardening (PIPE-01 + PIPE-03 + PIPE-04)

**Summary:** This plan correctly identifies the architectural needs to make the core intelligence pipeline resilient against individual plugin failures, ensuring bar continuity and local data durability.

**Strengths:**
- Effective Failure Isolation (PIPE-01): Using a dedicated CircuitBreaker state per plugin is the correct pattern to prevent cascading failures.
- Data Durability (PIPE-03): Making `_write_local_checkpoint` raise on failure ensures write failures are immediately detectable.
- Flow Control (PIPE-04): Converting signaling paths to use an explicit, blocking enqueue correctly serializes output and provides backpressure.

**Concerns:**
- **Missing Recovery on Write Failure (HIGH):** Removing the `try/except` block in `_write_local_checkpoint` means the entire processing agent fails immediately. The plan does not specify what happens next (retry with backoff?). Simply raising is insufficient for reliable checkpointing.
- **CB State Reset (MEDIUM):** The implementation does not specify how failure thresholds are reset (after timeout? manually?). Without clear reset semantics, the circuit breaker could permanently suppress healthy plugins post-recovery.
- **Inconsistency of Enqueue Paths (MEDIUM):** The decision to leave `_enqueue_intel_journal` and IntelligenceEvent enqueue non-blocking contradicts the hardening goal. These paths could still lead to silent data loss under stress.

**Suggestions:**
- Instead of merely raising on checkpoint failure, consider a bounded retry (3 attempts, increasing delay) before propagating.
- Add logic for automatic CB state reset after a "recovery period" or after enough successful bars, preventing permanent plugin suppression.
- Evaluate rate-limiting the non-blocking paths to prevent silent drops when the system is backlogged.

**Risk Assessment: MEDIUM.** Core improvements are excellent, but lack of graceful recovery logic (retry/backoff) in the checkpointing phase introduces risk of hard service failure during temporary I/O glitches.

### Plan 086-02: Signal Writer Validation Gate (PIPE-02)

**Summary:** This plan effectively implements the critical defensive layer needed before persistence, ensuring that malformed or invalid signals do not pollute TimescaleDB.

**Strengths:**
- Architecturally sound pending buffer pattern correctly handles the sync/async boundary mismatch.
- Clear failure path via DLQ provides maximum visibility into data quality issues.
- Centralized `validate_signal()` ensures schema definition is testable and not hardcoded.

**Concerns:**
- **DLQ Backpressure (HIGH):** If the DLQ topic or Redpanda broker is unavailable or rate-limited, `self._invalid_signals` can grow unboundedly in memory, leading to OOM and crashing the Signal Writer Agent.
- **Validation Scope (MEDIUM):** If `validate_signal` is solely structural, it may miss business validity checks. Needs clarification on completeness of validation.
- **Performance Impact (LOW):** Parsing and validating payloads on every bar will introduce measurable CPU overhead. Performance testing needed.

**Suggestions:**
- Implement a bounded retry mechanism and a failsafe for the DLQ. If Redpanda connectivity fails repeatedly, switch to writing invalid signals to a local persistent file and log the failure, rather than risking OOM.
- Expose size of `self._invalid_signals` as an operational metric; alert when it exceeds a defined threshold.

**Risk Assessment: HIGH.** The single point of failure is DLQ persistence. If the DLQ path fails, the agent traps error state in RAM, leading to inevitable process crash under sustained upstream failure.

### Plans 086-03 and 086-04

These plans are foundational but require robust implementation details around false-positive detection logic and timing. The stall detection design is sound; primary risk is network jitter causing false positives. For the health endpoint, verify exact Prometheus metric names before implementation.

---

## Consensus Summary

### Agreed Strengths

- **Existing infrastructure leverage**: All reviewers praised using `src/observability/circuit_breaker.py` (not the heavier core version), OTel metrics, and the existing `_send_to_dlq` pattern
- **Pending buffer pattern (Plan 02)**: Recognized by Gemini and Codex as the correct design to bridge sync `_parse_payload` with async `_send_to_dlq`
- **360s stall threshold**: All reviewers agree the 60s grace over the 300s in-process watchdog is the right call to prevent race conditions
- **Degraded-not-503 design (Plan 04)**: Per-query try/except failure isolation praised as appropriate for a health summary endpoint

### Agreed Concerns

**Priority 1 (HIGH — must fix before execution):**

1. **Circuit breaker recovery is broken as planned (PIPE-01)** — Codex: `OPEN -> HALF_OPEN` only happens inside `call()`, not via manual `record_failure()` alone. The breaker will open but never recover. Gemini + Ollama also flagged CB state reset as a gap. **Action required**: Read `src/observability/circuit_breaker.py` carefully. Either use `cb.call()` wrapper or confirm the API has a `record_success()` / reset path. Update plan before executing.

2. **Invalid-only payload DLQ gap (PIPE-02)** — Codex: if `_parse_payload()` returns `None` (all signals invalid), `self._invalid_signals` is never drained until a future valid flush. Ollama: unbounded buffer under sustained invalid traffic causes OOM risk. **Action required**: Handle the invalid-only case explicitly in `_flush_batch` or trigger a drain even when no valid rows exist.

3. **OBS-03 label key mismatch** — Codex (HIGH): `BaseAgent._last_msg_ts_attrs` emits label `agent`, not `agent_id`. `_AGENT_ID_TO_UNIT` lookup uses `agent_id`, so all Prometheus series will be silently missed. **Action required**: Read `src/core/agent/base.py` lines around `_last_msg_ts_attrs` before implementing `_fetch_stalled_agents`. Use whichever label key is actually emitted.

4. **OBS-02 router prefix mismatch** — Codex (HIGH): `src/api/main.py` mounts the health router at `/health` not `/api/health`. Endpoint would be `/health/system` not `/api/health/system`. **Action required**: Check actual `app.include_router(health.router, prefix=...)` call in `main.py` before writing the test or docs.

**Priority 2 (MEDIUM — address in implementation):**

5. **`_publish_signals_or_dlq()` may be sync** — Codex: if it's currently sync, `await _enqueue_blocking(...)` requires making it async and updating all call sites. Verify before Task 3.

6. **Circuit breaker OPEN metric goes stale** — Codex + Gemini: metric only set to `1` on open; no clear `0` on recovery. Grafana shows stale alerts. Emit `0` on CLOSED/recovery.

7. **Stall detection false positives during market close** — Codex: agents that legitimately idle during off-hours would be incorrectly restarted. Gate on session activity or agent-specific max_idle expectation.

8. **OBS-02 metric names need verification** — Codex: `persistence_consumer_lag_records` not `persistence_consumer_lag`; `dlq_messages_total` is a counter not a depth gauge; `signal_replay_unresolved_gauge` spelling. Verify exact names against `src/observability/metrics.py`.

### Divergent Views

- **Checkpoint PIPE-03 scope**: Gemini rated this LOW risk (checkpoint only happens at teardown, not per-bar — "aspirational" requirement). Ollama rated it MEDIUM and suggested retry/backoff. Codex noted the same teardown-only scope. **Resolution**: Codex/Gemini are correct that it's teardown-only; simply removing the swallow is the right fix. Ollama's retry suggestion is over-engineering for a shutdown path.

- **Overall risk rating**: Gemini rated LOW, Codex rated MEDIUM-HIGH, Ollama rated MEDIUM. The divergence is driven by Codex's deeper code-specific findings (label key mismatch, route prefix, CB recovery API). **Resolution**: Codex findings are the most specific and actionable; treat overall risk as MEDIUM-HIGH pending fixes to the 4 HIGH items above.
