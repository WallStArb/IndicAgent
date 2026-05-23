---
phase: 092
reviewers: [gemini]
reviewed_at: 2026-05-20T08:30:00Z
plans_reviewed:
  - 092-01-PLAN.md
  - 092-02-PLAN.md
  - 092-03-PLAN.md
---

# Cross-AI Plan Review — Phase 092

## Gemini Review

### Review Summary
The plans are exceptionally robust, logically sequenced, and demonstrate a deep understanding of the system's strict architectural constraints. By utilizing a wave-based deployment to manage schema changes and consumer dependencies, you have effectively mitigated the primary risks of event-bus rejection and data corruption. The design correctly isolates pure statistical logic from stateful persistence and integrates safety gates for tail risk, aligning perfectly with the phase goal of closing the measurement-to-action loop.

### Strengths
- **Sequential Risk Mitigation:** The Wave 1 consumer guarding (`AND entry_type='*'`) is a crucial, well-identified step that prevents breaking downstream services before the new data schema is fully propagated.
- **Pure Logic Separation:** Offloading statistics (skewness/kurtosis) to pure helper functions (`_distribution_shape`) ensures testability and prevents leakage of business logic into the data pipeline.
- **Idempotency & Safety:** The use of `information_schema` for DDL checks and guarded PK rebuilds demonstrates a professional approach to zero-downtime database evolution.
- **OTel Integration:** Explicitly incrementing counters on promotion blocks (`SHADOW_TAIL_RISK_BLOCKED`) ensures observability into the governance logic, which is vital for debugging "silent" promotion failures.

### Concerns
- **Performance (MEDIUM):** In Plan 03, fetching from `signal_metrics` inside the governance loop is safe if cached, but if called per-tick per-symbol, it could induce latency. Ensure this is cached or limited to the governance cadence (the existing 30-minute audit cycle).
- **SQL Complexity (LOW):** Rebuilding a Primary Key in production (Plan 01/Task 4) is inherently risky even with idempotent guards. Ensure the `ALTER TABLE ... ADD PRIMARY KEY` is executed within a transaction block that is strictly monitored for timeouts.
- **Edge Case Guarding (LOW):** In Plan 02/Task 1, ensure the `None` handling for the `recovery_factor` denominator is robust (e.g., `if abs(p5_r) > 1e-9`).

### Suggestions
- **DDL Guard:** For the PK rebuild, verify if the DB user has `ACCESS EXCLUSIVE` lock permissions in the deployment environment. If not, consider a "new table -> move data -> swap" approach if the table size is massive.
- **Statistical Robustness:** In the `recovery_factor` calculation, define explicit handling for `p5_r == 0` (or `None`). Given the "None-safe" requirement, return `None` rather than `0` or raising an exception.
- **Governance Testing:** Add a "Negative" test case in Plan 03 to verify that if the DB call fails (e.g., DB down), the system defaults to "fail-open" or "fail-closed" based on the established safety protocol.
- **Test Data:** Include a test case that deliberately injects an `entry_type` that is NOT in the allowed list to ensure the system gracefully handles unknown types by defaulting to the global `*` aggregate.

### Risk Assessment
**Risk Level: LOW**

The plan accounts for all identified "critical pitfalls." The sequential dependency between waves (Schema -> Compute -> Governance) is logical and minimizes the blast radius of any individual failure. The reliance on pure, unit-testable helpers for the new statistical metrics significantly reduces the likelihood of logic bugs in the production pipeline. As long as the database migration (PK rebuild) is performed with standard high-availability practices, the implementation path is well-secured.

---

## Codex Review

Codex review failed (exit code 1, empty output). CLI invocation returned no response.

---

## Consensus Summary

Only one reviewer (Gemini) produced output. No consensus synthesis possible across multiple reviewers.

### Agreed Strengths (Gemini)
- Wave-based dependency ordering eliminates deploy-order race conditions
- Pure function separation (`_distribution_shape`, `_tail_risk_blocks_promotion`) enables isolated unit testing
- Idempotent DDL via IF NOT EXISTS + information_schema guard is zero-downtime safe
- OTel counter on tail gate blocks provides observability without manual inspection

### Agreed Concerns (Gemini)
- **MEDIUM:** Tail gate DB fetch — confirm it runs only on the 30-minute audit cadence, not per-tick (already designed correctly per CONTEXT.md D-16, but worth verifying in code review)
- **LOW:** PK rebuild under production load — signal_metrics is ~1.6k rows so this is instant, but add explicit timeout guard in migration
- **LOW:** `recovery_factor` denominator guard — CONTEXT.md specifies `p5_r < -1e-9` check, confirm this is the implementation (matches Gemini concern exactly)

### Divergent Views
N/A — single reviewer.

### Actionable Items for Executor
1. In `_distribution_shape()`: verify `recovery_factor` guard uses `p5_r < -1e-9` (CONTEXT.md D-01), NOT `abs(p5_r) > epsilon` — semantics differ (Gemini flags this correctly; CONTEXT.md is authoritative)
2. In Plan 03 `_check_promotion()`: add exception handler around the `fetchrow` so DB failure fails-open (skips tail gate) rather than crashing the audit cycle
3. Confirm tail gate query runs inside existing `pool.acquire()` context in `_check_promotion()`, not a new connection
