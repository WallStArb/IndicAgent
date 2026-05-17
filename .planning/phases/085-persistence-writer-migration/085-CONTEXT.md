# Phase 085: Persistence Writer Migration - Context

**Gathered:** 2026-05-17
**Status:** Ready for planning

<domain>
## Phase Boundary

Migrate five persistence writers to adopt the Phase 084 base contracts so that silent data loss,
swallowed errors, and per-record writes are mechanically eliminated across the fleet. Every message
either lands in the DB or in the DLQ — observable, retryable, never silently dropped. Phase 084
delivered the base class contracts; Phase 085 is the mechanical application across writers.

Out of scope: pipeline circuit breaker wiring (Phase 086), signal transform phases 2-4 (Phase 087),
compute performance optimization (Phase 089).

</domain>

<decisions>
## Implementation Decisions

### PERSIST-04: SignalMetricsWriterAgent Batching (signal_metrics_writer_agent.py)

- **D-01:** Migrate `SignalMetricsWriterAgent` from `BaseAgent` to `BaseWriterAgent`. Single buffer
  holds all event dicts regardless of event type. `_flush_batch()` dispatches by `event_type` using
  the existing module-level handler functions (`_handle_metrics_computed`, `_handle_ic_computed`,
  `_handle_dq_failure`) — they stay as pure SQL helpers. Inherits DLQ, buffer-depth gauge, flush
  error counter, flush contract for free.

- **D-02:** Define `SignalMetricsEvent` as a Pydantic discriminated union in
  `src/intelligence/schemas.py` (alongside `BarIntelligenceRecord` and other bus schemas).
  `SignalMetricsWriterAgent` declares `payload_model = SignalMetricsEvent`. Malformed events DLQ
  automatically at the base validation layer — correctness by construction. `SignalMetricsComputeAgent`
  imports from the same location to ensure it publishes the right shape.

- **D-03:** The setup_performance backward-compat shim stays inside `_handle_metrics_computed()` —
  it is a DB write contingent on event data and belongs with the other DB writes for that event type.
  No extraction into a separate method for temporary code.

### PERSIST-01: LineageWriterAgent Payload Model (lineage_writer_agent.py)

- **D-04:** Define `LineageEvent` Pydantic model in `src/core/ai/lineage.py` alongside
  `LineageRecorder` (the sole producer). `lineage_writer_agent.py` imports it as `payload_model`.
  BaseWriterAgent validates on receive → DLQ on `ValidationError`. The schema contract lives with
  the thing that produces events.

- **D-05:** Delete the manual `signal_id` / `event_type` check from `_parse_payload()`. With
  `payload_model` enforcing required fields, the manual check is unreachable dead code. `_parse_payload()`
  receives an already-validated `LineageEvent` and returns `[payload]`.

### PERSIST-02: FeatureSnapshotWriterAgent Retry (feature_snapshot_writer_agent.py)

- **D-06:** Delete the `_do_flush()` override entirely. Inherit base re-raise behavior: flush failure
  re-raises, buffer stays intact, systemd restarts the agent. Kafka offset is not committed until
  successful flush → restart reprocesses from last committed position. Bounded retry by construction,
  zero new code.

- **D-07:** No `_dlq_topic()` for the shadow table. Kafka offset replay + `_flush_errors_total`
  counter + structured log `"shadow_write_failed"` is sufficient visibility. Shadow data is sourced
  from `intelligence.journal` which is already replayable. DLQ without a replay consumer is
  operational noise. "Observable and recoverable" meets PERSIST-02.

### PERSIST-03: LLM Writer Service Outcome Errors (llm_writer_service.py)

- **D-08:** Outcome errors in `_process_outcome_message()` currently log + DLQ + return False
  (no raise). "Re-raise" means the exception propagates to `_run()` which then decides whether
  to crash or continue. Planner should audit the actual swallowed-error paths and make failures
  visible in structured logs and the `_WRITE_ERRORS` counter. The DLQ routing stays; the specific
  ask is that DB errors during outcome writes are not swallowed silently inside the try/except.

### PERSIST-05: Named Parameter Style (fleet-wide)

- **D-09:** All writers using positional tuples in `executemany` / `execute_batch` migrate to
  named-field row construction. Pattern: build rows from named Pydantic model attributes (where a
  `payload_model` exists) or from a named `_to_row()` helper function that maps field names to
  positions explicitly. SQL remains `$1/$2` positional (asyncpg constraint). The goal: reviewers
  can read row construction without counting argument positions.

- **D-10:** Scope of migration — planner audits all writers for positional tuples:
  `lineage_writer_agent`, `lifecycle_writer_agent`, `ctx_writer_agent`, `bar_writer_agent`, and
  `swarm_ledger_writer_agent`. All offenders migrate in this phase. Fleet-wide consistency —
  one pattern, zero exceptions.

### Renaissance / Architectural Principles

- **D-11:** Every design decision in this phase is filtered through: (1) correctness by construction
  over defensive runtime checks, (2) reuse of base contracts over reinvention, (3) observable failures
  over silent ones, (4) automation (systemd + Kafka offsets) over manual recovery, (5) simplicity
  over complexity — don't build permanent scaffolding around temporary code.

### Claude's Discretion

- Exact field list for `LineageEvent` Pydantic model (copy from `LineageRecorder.record()` call sites)
- Exact field list for `SignalMetricsEvent` discriminated union variants (copy from existing handler functions)
- Batch size and flush interval defaults for the migrated `SignalMetricsWriterAgent`
- Exact `_to_row()` helper signatures for non-Pydantic writers

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 084 Base Contracts (READ FIRST — this phase applies these contracts)
- `src/core/agent/base_writer.py` — BaseWriterAgent buffer/flush/commit/DLQ pattern, `payload_model` ClassVar gate, `_do_flush()` re-raise contract
- `src/core/agent/base.py` — BaseAgent lifecycle, `_send_to_dlq()`, circuit breaker class attrs
- `.planning/phases/084-base-agent-hardening/084-CONTEXT.md` — D-01 through D-09 (locked Phase 084 decisions)

### Target Writers
- `services/lineage_writer_agent.py` — PERSIST-01 target; has `_dlq_topic()`, missing `payload_model`
- `services/feature_snapshot_writer_agent.py` — PERSIST-02 target; overrides `_do_flush()` to clear-on-error
- `services/llm_writer_service.py` — PERSIST-03 target; 1033 lines, outcome error paths
- `services/signal_metrics_writer_agent.py` — PERSIST-04 target; extends BaseAgent, per-record writes
- `services/lifecycle_writer_agent.py` — PERSIST-05 audit target (positional tuples)
- `services/ctx_writer_agent.py` — PERSIST-05 audit target (executemany with positional tuples)
- `services/bar_writer_agent.py` — PERSIST-05 audit target
- `services/swarm_ledger_writer_agent.py` — PERSIST-05 audit target

### Reference Template (Named Params Pattern)
- `services/contract_metadata_writer_agent.py` — reference template for migration style

### Schema Locations
- `src/intelligence/schemas.py` — where `SignalMetricsEvent` discriminated union will be added
- `src/core/ai/lineage.py` — where `LineageEvent` Pydantic model will be added (co-locate with `LineageRecorder`)

### Requirements
- `.planning/REQUIREMENTS.md` — PERSIST-01 through PERSIST-05 (full acceptance criteria)
- `.planning/ROADMAP.md` — Phase 085 success criteria (5 numbered items)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `BaseWriterAgent._send_to_dlq()` — already implemented, called on `ValidationError` by base when `payload_model` is declared
- `BaseWriterAgent._do_flush()` — Phase 084 re-raise contract: buffer stays intact, systemd restart recovers
- `_handle_metrics_computed()`, `_handle_ic_computed()`, `_handle_dq_failure()` — existing pure SQL helpers in `signal_metrics_writer_agent.py`; keep as-is, called from `_flush_batch()`
- `LineageRecorder.record()` — in `src/core/ai/lineage.py`; its call signature defines the `LineageEvent` field list
- `feature_writer_agent._record_to_insert_params()` — named-field helper pattern already in use; reference for `_to_row()` style

### Established Patterns
- `payload_model: ClassVar[type[BaseModel]]` on `BaseWriterAgent` subclasses — Phase 084 pattern; base validates raw Kafka dict, routes to DLQ on `ValidationError`
- `executemany` with positional tuples — the anti-pattern being eliminated
- Discriminated union with `Literal` event_type field — standard Pydantic pattern for heterogeneous event streams

### Integration Points
- `SignalMetricsComputeAgent` is the sole producer of `intelligence.signal_metrics` — imports `SignalMetricsEvent` from `schemas.py` after this phase
- `LineageRecorder` (in `BaseGroupService`) is the sole producer of `topic_signal_lineage` — `LineageEvent` co-located in `lineage.py`
- systemd + Kafka offset commits are the retry mechanism for `feature_snapshot_writer_agent` — no new code needed

</code_context>

<specifics>
## Specific Ideas

- **Jim Simons / Renaissance framing throughout:** Every error at every layer is quantified and
  observable. Silent failures are structurally impossible. Automation (systemd, Kafka offsets) over
  manual recovery. Don't build permanent scaffolding around temporary code (shims). One pattern
  fleet-wide, zero exceptions.
- `SignalMetricsEvent` should be a Pydantic discriminated union keyed on `event_type: Literal["metrics_computed" | "ic_computed" | "metrics_dq_failure"]`. Each variant is a named model. The base validates on receive, dispatcher checks the `event_type` field.
- `LineageEvent` field list derived from `LineageRecorder.record()` call sites — don't invent; read the producer.

</specifics>

<deferred>
## Deferred Ideas

- **DLQ consumer for shadow table replay** — shadow data has no replay consumer today; a DLQ nobody reads is operational noise. If parity auditor requirements evolve, revisit in a future phase.
- **Per-writer Grafana DLQ depth panels** — Phase 084 wired `agent_dlq_total` counter; dashboarding it per-writer is Phase 086/089 scope when the data accumulates.

</deferred>

---

*Phase: 085-persistence-writer-migration*
*Context gathered: 2026-05-17*
