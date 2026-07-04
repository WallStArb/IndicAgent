---
phase: lifecycle-replay-repair
reviewers: [gemini, codex]
reviewed_at: "2026-06-04T00:00:00Z"
plans_reviewed: [docs/plans/2026-06-03-lifecycle-replay-repair.md]
status: archived
resolution: Plan implemented 2026-06-06 — see `production/scripts/lifecycle_replay.py` v1.2
---

# Cross-AI Plan Review — Lifecycle Replay Repair

**Status:** Archived — Historical reference only. The reviewed plan was implemented and is now production code.

## Gemini Review

### Summary

The plan is directionally sound: it targets the Phase-104 split correctly by treating `signal_ledger` as immutable and writing lifecycle state only to `signal_outcomes`. The explicit SQL join, wall-clock `expires_at` handling, reset/replay/verify flow, and unit tests are all appropriate. The main risks are operational and data-integrity related: the reset scope is underspecified, concurrent live services could race the replay, the script's transaction handling needs explicit final commits/rollbacks, and the replay query as written may exclude broken rows if `signal_outcomes` rows are missing or not in the expected status.

### Strengths

- Correct ownership model: immutable signal definition stays in `signal_ledger`; mutable lifecycle fields go to `signal_outcomes`.
- Uses parameterized SQL for symbol/timeframe filters.
- Explicit `JOIN` avoids relying on stale view column assumptions.
- Reusing current `evaluate_signal()` and `evaluate_market_entry()` is the right source of truth.
- `--reset`, `--dry-run`, and `--verify` are the right operational controls for a destructive replay.
- Wall-clock `expires_at` handling addresses the important Phase 107.5 semantic change.
- Unit tests target the pure helpers, which keeps replay logic testable without a database.

### Concerns

- **HIGH: Reset scope is too vague.** "Pre-fix signals" must be bounded by exact timestamps, likely `sl.timestamp >= '2026-05-21'` and `< fixed_code_cutover_ts` or `< '2026-06-02'`. Without this, `--reset` could wipe valid post-fix outcomes or older healthy data.

- **HIGH: Live service concurrency is not addressed.** During reset/replay, signal writer, lifecycle writer, tracker, metrics, swarm, and setup-performance jobs can race the script. The Phase-104 migration notes explicitly require stopping L6+ services for similar operations. This plan should require a maintenance window or advisory lock.

- **HIGH: Existing transaction flow needs review.** The current script starts manual transactions and releases connections without an obvious final `COMMIT` after the final flush. If that remains, the last batch or whole pair can be rolled back by pool cleanup. The plan says write SQL likely needs no changes, but transaction handling must be verified too.

- **HIGH: Proposed `JOIN` may hide orphaned ledger rows.** `JOIN signal_outcomes so` skips `signal_ledger` rows missing seeded outcomes. For repair tooling, either verify zero missing `signal_outcomes` rows before replay or use `LEFT JOIN` plus `INSERT INTO signal_outcomes ... ON CONFLICT DO NOTHING`.

- **MEDIUM: Work queue/status filtering may skip corrupt resolved rows unless reset runs first.** This is fine operationally, but the script should refuse replay for the target window unless `--reset` has run or unless unresolved/resolved counts confirm expected state.

- **MEDIUM: Derived-table truncation is global.** `TRUNCATE swarm_agent_weights` and `setup_performance` may be correct, but the plan should state how and when they are rebuilt. Otherwise consumers may run with empty/neutral weights after replay.

- **MEDIUM: `expires_at` handling can leave stale rows pending.** Returning `{zone_outcome: None, exit_at: None}` for not-yet-expired signals is correct only if `_process_symbol_tf` does not count them as processed or write `status='expired'`. This needs explicit implementation detail and tests.

- **MEDIUM: Performance risk from loading all bars/signals into memory.** 2.83M signals across 23 instruments and multiple timeframes is large. Per-pair ownership helps, but fetching all bars from `min_ts` can still be heavy. Batch/windowed replay or memory estimates should be included.

- **MEDIUM: Timestamp/chunk pruning mismatch.** `signal_outcomes` is keyed by `signal_id`; timestamp is not in that table. Comments or SQL implying `(signal_id, timestamp)` pruning no longer apply after the split. Updates should not pretend `timestamp` helps `signal_outcomes`.

- **LOW: Test path mismatch.** The repo already has `tests/unit/scripts/test_lifecycle_replay.py`; the plan proposes `tests/unit/production/test_lifecycle_replay.py`. Pick the existing convention unless there is a deliberate test layout change.

- **LOW: Verification is underspecified.** "counts signals with/without outcomes" should also check impossible combinations, missing market outcomes where `market_entry_price` exists, stale pending where `expires_at < max(bar_ts)`, and null `pnl_r` for resolved terminal outcomes where PnL is expected.

### Suggestions

- Add exact reset predicates with `--start-ts` and `--end-ts` required for `--reset`.
- Add a preflight phase: confirm required columns exist, count target-window rows, count missing `signal_outcomes`, abort unless counts match expectations.
- Use a DB advisory lock for the replay: `SELECT pg_try_advisory_lock(...)`.
- Require operational quiescence: stop lifecycle writer, signal tracker, metrics updater, setup performance updater, swarm/graduation writers.
- Repair or assert `signal_outcomes` 1:1 coverage with `LEFT JOIN` + `INSERT ... ON CONFLICT DO NOTHING`.
- Explicitly commit after final flush and rollback on exceptions.
- Add `expires_at` tests that assert not-yet-expired signals produce no write.
- After replay, run rebuild jobs for `setup_performance` and `swarm_agent_weights`, or document that they remain empty until scheduled jobs repopulate them.

### Risk Assessment

**Overall risk: HIGH.**

The code changes are moderate, but the operation is destructive and touches 2.83M lifecycle records plus downstream derived tables. The plan can achieve the phase goal, but only if reset scoping, service quiescence, transaction commits, orphan outcome handling, and verification gates are tightened before execution.

---

## Codex Review

### Summary

The plan to repair `lifecycle_replay.py` is well-structured and addresses the critical data integrity issue caused by the Phase-104 schema split. By focusing on explicit table joins and rigorous idempotent replay logic, the approach minimizes the risk of further corrupting the downstream feature store. The inclusion of an integrated reset phase and post-replay verification makes this a robust operational procedure rather than just a hotfix.

### Strengths

- **Architectural Correctness:** Moving from the `signal_ledger_full` view to explicit `JOIN` operations on `signal_ledger` and `signal_outcomes` correctly acknowledges the database normalization introduced in Phase 104.
- **Idempotency & Safety:** The `--reset` flag and the inclusion of truncation for derived tables (`swarm_agent_weights`, `setup_performance`) are essential for ensuring a clean state and preventing stale data from bleeding into the recomputed results.
- **Temporal Logic Alignment:** Updating `resolve_at_end_of_bars` to respect `expires_at` (wall-clock) while providing a fallback to `ttl_bars` ensures compatibility with the post-Phase-107.5 intelligence pipeline.
- **Comprehensive Testing:** The planned unit tests cover the most critical, high-risk logic branches (TTL/expires logic), which are prone to subtle off-by-one or temporal errors.

### Concerns

- **MEDIUM: Performance.** Replaying 2.83M signals in a single script run could place significant load on the TimescaleDB instance. Ensure that `conn.fetch` in the replay phase uses keyset pagination or server-side cursors to avoid OOM issues on the Python runner if the memory footprint of 2.83M records exceeds expected limits.
- **MEDIUM: Locking/Concurrency.** The plan mentions 8 workers but does not explicitly detail transaction management. If multiple workers are updating the same `signal_outcomes` records (or derived tables) simultaneously, ensure the `UPDATE` statements are atomic and do not cause excessive row-level locking contention.
- **LOW: Temporal Drift.** Replaying signals requires historical bar data. Ensure that the `bar_replay_provider` used by the script is strictly aligned with the exact data available at the time the signal was originally fired to avoid "re-simulation" bias where the outcome differs simply due to data provider differences.

### Suggestions

- **Batching/Pagination:** Implement chunking (e.g., process 10,000 signals at a time) in the replay phase rather than pulling the entire set into memory, even if the database supports it.
- **Dry-Run Default:** Force the script to require an explicit `--confirm` flag in addition to `--reset`, preventing accidental wipes if the command is run without arguments.
- **Pre-Flight Integrity Check:** Before the `reset` phase, add a step that checks if the `signal_outcomes` table has foreign key constraints or triggers that might be impacted by the bulk deletion/update to avoid runtime database exceptions.

### Risk Assessment

**Overall risk: MEDIUM.**

While the plan is logically sound, the risk stems from the scale of the operation (2.83M records) and the potential for "re-simulation drift." The actual logic updates are straightforward, but the operational impact of running a bulk write-intensive script against production data stores requires careful staging and monitoring.

---

## Consensus Summary

### Agreed Strengths

- Both reviewers agree the explicit JOIN approach is architecturally correct for the Phase-104 split.
- Both approve the reset/verify operational model as well-designed.
- Both agree unit tests for the pure TTL/expires_at helpers are the right testing strategy.

### Agreed Concerns

1. **Live service concurrency (Gemini: HIGH, Codex: MEDIUM)** — Both flag that running replay while live services are writing to signal_outcomes will cause data races. Requires either a maintenance window, advisory lock, or service quiescence.
2. **Memory/performance at scale (Gemini: MEDIUM, Codex: MEDIUM)** — Both note 2.83M signals + all historical bars is a large memory footprint. Per-pair ownership helps but may not be enough.
3. **Derived table rebuild strategy (Gemini: MEDIUM)** — Truncating swarm_agent_weights and setup_performance without a rebuild plan leaves downstream consumers in an undefined state.

### Divergent Views

- **Orphan signal_outcomes rows (Gemini only, HIGH)** — Gemini flags that the INNER JOIN will skip signal_ledger rows with no matching signal_outcomes row. Codex does not mention this. This is a real risk if Phase-104 seeding was incomplete.
- **Temporal drift / re-simulation bias (Codex only, LOW)** — Codex worries about bar data alignment. Gemini does not raise this. In practice, the replay uses the same `market_data_ohlcv` table the live pipeline uses, so this is unlikely to be an issue.
- **Risk level** — Gemini rates HIGH, Codex rates MEDIUM. The gap comes from Gemini's stronger concerns about operational safety (concurrency, orphan rows, transaction handling).
