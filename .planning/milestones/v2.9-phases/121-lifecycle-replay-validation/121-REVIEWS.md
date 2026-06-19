---
phase: 121
reviewers: [gemini]
reviewed_at: 2026-06-10T22:18:21Z
plans_reviewed:
  - 121-01-PLAN.md
  - 121-02-PLAN.md
notes: "codex skipped (usage limit reached); ollama skipped (Docker container, no REST port exposed to localhost)"
---

# Cross-AI Plan Review — Phase 121

## Gemini Review

# Review: Phase 121 Lifecycle Replay & Validation

## Summary
The plan provides a sound, high-integrity approach to remediating the 5.17M noise signal crisis by combining surgical data cleanup with a full lifecycle replay. It correctly identifies the critical technical bottlenecks (schema drift, hardcoded filters) and introduces necessary safety guards (snapshotting, scoped deletion). The workflow is logically sequenced, ensuring that before-replay states are preserved for the subsequent performance validation report.

## Strengths
- **Data Safety:** Implementing an explicit `phase_121_before_snapshot` with an `exists-guard` ensures that the pre-remediation state is preserved before any destructive operations, providing a "panic button" rollback if the replay goes awry.
- **Surgical Cleanup:** Moving away from a broad `historical_backfill.py --clean` to a scoped `--setups` approach is a major improvement, preventing unintended collateral damage to healthy, non-shadow control setups.
- **Integrity Enforcement:** The integration of an "integrity gate" between the replay and the report is crucial, preventing the validation phase from running on corrupted or incomplete data.
- **Metric Accuracy:** Calculating metrics using actual production data within `phase_121_report.py` ensures the validation report is empirical and untainted by legacy estimates.

## Concerns
- **HIGH: Transactional Atomicity Risks.** The plan mentions using advisory locks (standard practice in this codebase), but does not explicitly detail the recovery protocol if `lifecycle_replay.py` crashes *after* the cleanup but *before* the replay completes. Millions of rows could be left in an orphan state.
- **MEDIUM: `intelligence_features` Integrity.** While you correctly identified that `intelligence_features` lacks a `setup_plugin` column and should not be deleted, the plan is silent on whether stale features from the noise signals could skew future model training or if they should be nullified/archived elsewhere.
- **MEDIUM: Schema Drift Complexity.** Updating `lifecycle_replay.py` to support 14 new columns is high-risk. If the schema mapping is off, the replay will either fail or silently write corrupted lifecycle state.
- **LOW: Dependency on `asyncpg`.** Ensure that the `asyncpg` connection pool settings for the replay job are tuned for the `MARKET_CHUNK=2000` size, as millions of row insertions can trigger aggressive memory usage or lock contention on TimescaleDB.

## Suggestions
- **Add an "Orphan Cleanup" Step:** Include a formal validation query in `_verify_replay()` that identifies any entries in `signal_ledger` that lack matching rows in `signal_outcomes` and vice-versa, specifically for the shadow setups, before finalizing the job as `COMPLETED`.
- **Dry-Run Validation:** Before the full replay, perform a dry-run execution on a single, isolated setup (e.g., `trad_OFIContinuation`) to verify the 14-column mapping and ensure `asyncpg` ingestion performance matches expectations.
- **Explicit Rollback Strategy:** Document a simple SQL script in `MEMORY.md` that can restore `signal_ledger` and `signal_outcomes` for the 22 affected setups if the snapshot is required, so the operator isn't scrambling to figure it out during an outage.

## Risk Assessment
**Risk Level: MEDIUM**
While the plan is technically robust, the scale (millions of rows) combined with legacy schema complexity makes this a non-trivial operation. The primary risk is not the plan logic, but the potential for silent data corruption if the 14-column mapping isn't perfectly aligned with the target schema. Strict adherence to the dry-run recommendation will lower this risk to LOW.

---

## Consensus Summary

Only one reviewer completed (Gemini). Codex hit usage limits; Ollama unavailable via REST API from host.

### Agreed Strengths
- Before-snapshot with exists-guard is the correct data-safety pattern for irreversible deletes at this scale
- Plugin-scoped `--setups` filter for `--clean` prevents collateral damage to GOOD control setups
- Integrity gate hard-fail before the report prevents misleading validation output
- Using live DB metrics (not stale doc estimates) for the comparison report

### Agreed Concerns
- **HIGH: Crash-recovery gap between --clean and lifecycle_replay.** If the backfill regeneration succeeds but lifecycle_replay.py crashes mid-run, signal_ledger has regenerated signals with no signal_outcomes rows (orphan state). No re-run mechanism is specified for partial replay completion. The advisory lock prevents concurrent runs but does not help resume a failed run.
- **MEDIUM: 14-column schema mapping risk.** Silent corruption is possible if any new column has a type mismatch (e.g., JSONB returned as dict by asyncpg vs. string). The plan relies on ruff + ast.parse as acceptance criteria, which do not catch runtime type errors.
- **MEDIUM: intelligence_features staleness.** Feature rows from the noise-signal era are not deleted; their impact on future ML training is unaddressed. (Note: this is a design decision — the research found features are per-bar, not per-signal, so they are reusable. The gap is that the plan does not document this rationale explicitly.)

### Divergent Views
- N/A (single reviewer)
