---
phase: 113
reviewers: [gemini, codex]
reviewed_at: 2026-06-03T08:20:00-04:00
plans_reviewed: [113-01-PLAN.md]
---

# Cross-AI Plan Review — Phase 113

## Gemini Review

### Summary
The plan provides a comprehensive and technically sound approach to addressing systemic architectural debt in the IndicAgent platform. By prioritizing integrity invariants (content-addressed IDs, idempotent upserts, and DAG enforcement) alongside operational reliability (backpressure, SSE observability), the plan effectively bridges the gap between historical development and production-grade stability. The scope is well-aligned with the goal of hardening the core intelligence pipeline.

### Strengths
- **Architectural Rigor:** Explicitly mandates DAG integrity via CI enforcement, preventing future regression of DB-ignorant constraints.
- **Integrity Focused:** Content-addressed IDs and idempotent UPSERT operations are the correct primitives for deterministic replay and state consistency in feature stores.
- **In-Process Calibration:** Moving confidence calibration into the synchronous pipeline flow maintains the requirement that I1–I7 are fully contained, avoiding unnecessary latency or coupling with external services.
- **Defensive Engineering:** Implementing a backpressure circuit breaker and dedicated telemetry counters for dropped messages demonstrates a mature approach to production observability.

### Concerns
- **HIGH: Writer Contract Refactoring (Task 7):** Modifying `BaseWriter._parse_payload` is a high-risk change as it affects all subclasses. A breaking change here without a clear migration path could cause widespread silent failures in persistence.
- **MEDIUM: Hot-Reload Concurrency (Task 10):** Atomically replacing an in-memory contract set in multiple daemons needs careful synchronization. If a pipeline process is midway through `_process_bar()` when the update arrives, state inconsistency could occur.
- **MEDIUM: Signal ID Collision (Task 5):** The plan does not define behavior when identical inputs produce the same ID (e.g., duplicate ticks leading to identical feature extraction). Is this a fatal error or a deduplication event?
- **LOW: Migration Ordering (Task 5 & 11):** The plan mentions migrations 115 and 116 but does not specify if they are interdependent.

### Suggestions
- **Writer Contract (Task 7):** Introduce the new signature as `_parse_payload_v2` and provide a default implementation in `BaseWriter` that calls the old `_parse_payload` with a deprecation warning, allowing phased subclass transition.
- **Pipeline Consistency (Task 10):** Use an atomic reference swap to ensure the pipeline reads a consistent snapshot of the contract set for the duration of a single bar process.
- **Collision Handling (Task 5):** Define explicit behavior for content-addressed collisions: log a `CRITICAL` and drop, or UPSERT. Given the idempotency requirement, UPSERT is safer.
- **Verification:** Add an integration test for backpressure by flooding a mock pipeline with bars faster than the processing rate.

### Risk Assessment
**MEDIUM** — Technical direction is excellent, but the wide-reaching BaseWriter refactor and contract hot-reload complexity present significant risks. These require high test coverage and careful, incremental deployment.

---

## Codex Review

### Summary
The plan is directionally strong and maps most roadmap findings to concrete files, commits, and tests. The main risk is that the plan bundles several high-blast-radius changes into one phase — BaseWriter contract rewrite, confidence calibration insertion, hot-reload propagation, and pipeline backpressure behavior — without sharp enough dependency ordering, rollout strategy, and compatibility tests to avoid fixing integrity issues while introducing silent data loss or broken downstream contracts.

### Strengths
- Clear traceability from review findings to implementation targets and commits.
- Good separation of concerns: calibration stays in-process, Kafka remains a sink, CRITICAL-03 explicitly kept out of this phase.
- Content-addressed `signal_id` directly addresses replay/idempotency problems.
- CI DAG invariant tests align with non-negotiable architecture constraints.
- SSE fan-out refactor is appropriately scoped around topic indexing, bounded cache size, and drop telemetry.
- Moving feature writes from DO NOTHING to DO UPDATE is the right direction for deterministic replay.
- The plan includes tests for the SSE broadcaster rather than only refactoring production code.

### Concerns
- **HIGH: BaseWriter contract change** — Updating "all subclasses" can easily miss edge cases where subclasses rely on `None`, empty lists, partial validation, or exception-based rejection. Needs explicit subclass inventory and compatibility tests per subclass.
- **HIGH: Signal ID payload canonicalization** — If `payload_hash` depends on Python dict ordering, float formatting, timestamp serialization, or optional fields, identical signals may produce different IDs across runs. Canonicalization must be precisely defined.
- **HIGH: UNIQUE INDEX CONCURRENTLY cannot run inside a transaction** — PostgreSQL prohibits this. The migration runner's transaction behavior, duplicate pre-check, and failure handling must be explicitly accounted for.
- **HIGH: Calibration fallback behavior undefined** — If curves are missing, stale, partially loaded, or malformed, the behavior must be explicit: pass-through raw confidence, clamp, reject, or mark as uncalibrated. Silent pass-through is probably correct but must be stated.
- **HIGH: Backpressure drops bars — may corrupt indicator continuity** — For market intelligence, dropping bars is not just load shedding; it can change rolling windows, regime state, CIS smoothing, and narratives. Stateful plugins need gap awareness.
- **MEDIUM: Live contract hot-reload underspecified** — "Other daemons" is too vague. Needs a concrete daemon list, message schema, validation, versioning, and atomic swap semantics.
- **MEDIUM: DAG invariant test scope too narrow** — Only checks forbidden imports at module load time in `src/intelligence/`. Misses local imports inside functions, indirect access, and `services/intelligence_pipeline.py`.
- **MEDIUM: Feature DO UPDATE may overwrite better data with stale replay** — Should define whether replay determinism or last-write-wins is intended.
- **LOW: Deleting test_sse_intelligence.py** — If the Redis-specific path is dead, delete or rewrite only the dead assumptions while preserving behavioral expectations where possible.
- **LOW: setup_performance gate enforcement point** — "Gate check code + migration 116 if DB config" is too uncertain for implementation.

### Suggestions
- Define canonical signal hashing explicitly: UTC ISO or epoch nanoseconds for timestamps, normalized timeframe string, stable agent_id, RFC canonical JSON for payload, deterministic float handling. Exclude volatile fields.
- Add pre-migration duplicate check for `signal_ledger.signal_id`; document that migration 115 is non-transactional (`CONCURRENTLY`).
- Add tests proving signal ID stability across: identical replay, reordered payload keys, timezone-equivalent timestamps, minor non-identity metadata changes.
- For calibration, add tests for: missing curve, stale curve, out-of-range raw confidence, concurrent curve reload.
- For BaseWriter, create a subclass inventory table before implementation; require test per writer for all-valid, all-invalid, mixed, parser exception, and DLQ shape.
- Make backpressure configurable: configurable max queue depth, per-symbol/tf drop labels, queue depth gauge, test that warning and metric emit exactly once per drop.
- Expand DAG invariant tests: scan AST for forbidden imports, include `services/intelligence_pipeline.py`, check hardcoded topic strings outside `stream_keys.py`.
- Make hot-reload concrete: add schema/version for contracts.updated, validate before swap, preserve last-known-good on bad update, emit reload success/failure metrics.

### Risk Assessment
**HIGH** — The plan targets the right problems, but combined blast radius is large: signal identity, calibration before I7, writer DLQ behavior, feature-store idempotency, live contract state, and bar ingestion under pressure. Risk becomes manageable if the plan tightens canonicalization, migration safety, explicit fallback behavior, subclass coverage, and backpressure semantics before implementation.

---

## Consensus Summary

### Agreed Strengths
- Content-addressed signal_id is the correct primitive for replay idempotency (both reviewers)
- In-process calibration before I7 maintains pipeline DB-ignorance invariant (both reviewers)
- CI DAG invariant enforcement is the right long-term gate (both reviewers)
- SSE topic-indexed fan-out refactor is well-scoped (both reviewers)

### Agreed Concerns (address before execution)

**1. BaseWriter contract blast radius [HIGH — both reviewers]**
Both reviewers independently flagged this as the highest-risk task. All subclasses must be inventoried before implementation. At minimum: explicit list of all `_parse_payload` implementations, test per subclass covering all-valid, all-invalid, mixed, and exception cases.

**2. Signal ID payload canonicalization [HIGH — Codex; MEDIUM — Gemini]**
The SHA-256 hash must be stable across runs. The plan's use of `json.dumps(sig.get("contributing_plugins", {}), sort_keys=True)` is a good start but must explicitly handle: float normalization, timestamp format (use UTC epoch integer, not ISO string), and exclusion of volatile fields (trace IDs, creation timestamps). Add stability tests.

**3. UNIQUE INDEX CONCURRENTLY transaction constraint [HIGH — Codex]**
Migration 115 must be marked as non-transactional. The migration runner (if using a transaction-wrapping tool) must be directed to run this step outside a transaction block. Add the pre-check `DO $$ ... RAISE EXCEPTION IF duplicates ... $$` before the index creation.

**4. Calibration fallback when curves unavailable [HIGH — Codex]**
Task 6 must specify: if `get_calibrated_confidence()` returns `None` (no cached curve), the pipeline silently passes through `raw_confidence` unchanged. This must be the explicit contract, not assumed.

**5. Backpressure and stateful indicator continuity [HIGH — Codex]**
Dropping the oldest bar under load can corrupt stateful plugin state (rolling windows, Kalman filters, regime detection). Task 12 should note that dropped bars trigger a `STALE_STATE` flag or that plugins must be gap-tolerant. Minimum: log the dropped symbol+tf so operators can detect when state may be stale.

**6. Hot-reload daemon inventory [MEDIUM — both reviewers]**
Task 10 says "other daemons found via grep." This must be resolved to a concrete list before execution and each daemon tested independently. Minimum: atomic swap pattern (replace reference, don't mutate in place) with validation before the swap commits.

### Divergent Views
- **Gemini** suggested a `_parse_payload_v2` deprecated-shim transition for BaseWriter. **Codex** recommended a subclass inventory and parallel test suite instead. Codex's approach is better — a shim adds complexity without fixing the subclasses; inventory + tests is cleaner.
- **Gemini** rated overall risk MEDIUM. **Codex** rated HIGH. Codex's HIGH rating is correct given the calibration fallback, canonicalization, migration transaction, and backpressure concerns that Gemini did not surface. Weight Codex's risk level.
