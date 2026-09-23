---
phase: 175-itr-materiality-filtered-empirical-tags-for-breadth-peer-gro
plan: 01
subsystem: database
tags: [postgresql, timescaledb, migration, apr, instrument-tag-registry, config-registry]

# Dependency graph
requires: []
provides:
  - "instrument_tags: 11 new Pass 4 evidence columns (partial_loading, partial_loading_ci_low, incremental_r2, sign_stable_windows, sign_stable_windows_total, null_arm_p_value, null_arm_bh_p, materiality_sample_n, passes_materiality, discovery_state, first_measured_at)"
  - "instrument_tags_active view (todo 126) - the required unexpired-row read path"
  - "instrument_tags_discovery_state_check CHECK constraint (NULL/pending_oos/confirmed)"
  - "11 alpha.tag_calibrator.materiality.* APR keys seeded across config_schema/config_state/config_history"
affects: [175-02, 175-03, 175-04, 175-05]

# Tech tracking
tech-stack:
  added: []
  patterns: ["config_history idempotent-provenance seed pattern: INSERT ... SELECT * FROM (VALUES ...) v WHERE NOT EXISTS (correlated on config_key + changed_by), needed because config_history's PK includes timestamp so a literal VALUES(NOW(),...) ON CONFLICT DO NOTHING never actually conflicts across invocations"]

key-files:
  created: [production/migrations/346_itr_materiality_evidence_columns.sql]
  modified: []

key-decisions:
  - "R-03: control_factor_series is four legs only (SPY/TLT/HYG-IEF/UUP), no DBC commodity leg, stored as an APR JSON list rather than a Python constant"
  - "R-04: passes_materiality encodes the statistical gate ONLY; discovery_state='confirmed' (temporal) and valid_to IS NULL (expiry) are separate columns the reader ANDs, not collapsed into one boolean"
  - "R-05: Codex's partial_loading_ci_low lower-CI gate is retained as a real column and a real gate"
  - "R-08: null_arm_seed is APR-backed (CLAUDE.md category 1: seeds affecting algorithm output), tagged [conventional] not [initial_estimate] since 42 is the project's standing default seed, not an uncalibrated statistical estimate"
  - "D-05: ten threshold keys seeded at Codex's conservative proposed defaults, not an averaged Codex/Fable/AGY synthesis"

patterns-established:
  - "config_history seeding under a PK that includes timestamp must use WHERE NOT EXISTS keyed on (config_key, changed_by), not ON CONFLICT DO NOTHING, to actually be idempotent across repeated `psql -f` invocations"

requirements-completed: [P175-02, P175-04, P175-06, P175-07, P175-08]

# Metrics
duration: ~35min
completed: 2026-09-23
---

# Phase 175 Plan 01: ITR Materiality Evidence Schema Summary

**Migration 346 ships the instrument_tags Pass 4 evidence schema, the instrument_tags_active view, and 11 alpha.tag_calibrator.materiality.* APR keys — applied live, verified idempotent, and committed.**

## Performance

- **Duration:** ~35 min
- **Completed:** 2026-09-23
- **Tasks:** 3 (Task 0 checkpoint confirmed by orchestrator evidence, Task 1 + Task 2 executed)
- **Files modified:** 1 (production/migrations/346_itr_materiality_evidence_columns.sql)

## Task 0: D-07 Cross-AI Review Gate

Confirmed via evidence supplied by the orchestrating session rather than a live human response: the Fable + Codex/AGY cross-AI review of the full 175-0N-PLAN.md set completed and cleared 2026-09-18 (reviewers: codex, antigravity, fable; gate_status: cleared). A first premature "ready" claim was caught in a same-day cleanup audit (the initial Fable dispatch had reviewed a different document), a fresh Fable dispatch against the actual plan set found one real finding (the sign-stability gate's "sliding bar" framing was imprecise), and that finding was fixed same session (commit `be50af233`). STATE.md was corrected accordingly (commit `80998a8fc`). `.planning/STATE.md`'s live Phase Summary confirms: "D-07 gate cleared by all three required reviewers (Codex, AGY, Fable — full review record: `175-REVIEWS.md`), ready for `/gsd-execute-phase 175`." Proceeded directly into Task 1 per the orchestrator's dispatch instructions.

## Accomplishments
- Migration 346 written, applied live, and re-run twice with zero errors and zero duplicate side effects on the second pass
- All 11 `instrument_tags` evidence columns, the `instrument_tags_active` view, the table-scoped `discovery_state` CHECK constraint, and all 11 `alpha.tag_calibrator.materiality.*` APR keys (config_schema + config_state + config_history) verified live against the database, not just claimed from the file
- Found and fixed a real idempotency bug in the `config_history` seed block before it could land: `config_history`'s primary key is `(timestamp, config_key, version)`, so a literal `VALUES (NOW(), ...) ON CONFLICT DO NOTHING` can never actually conflict across two separate `psql -f` invocations — it silently duplicated all 11 provenance rows on the second run (22 rows instead of 11, caught live during Task 2's idempotency verification, not left for a later discovery)

## Task Commits

1. **Task 1 + Task 2 (combined per plan instructions): Author + apply migration 346** - `14292958f` (feat) — the plan's Task 2 explicitly directs committing the migration file in the same task as applying it live ("A migration applied live via `psql -f` has no forcing function to get committed — commit it in the same breath as applying it, not 'later.'"), so both tasks land in one commit as designed.

## Files Created/Modified
- `production/migrations/346_itr_materiality_evidence_columns.sql` - 11 `instrument_tags` evidence columns, `instrument_tags_active` view, `discovery_state` CHECK constraint, 11 `alpha.tag_calibrator.materiality.*` APR keys across all three config tables

## Decisions Made
- Kept the plan's exact APR key set, bounds, provenance tokens, and control_factor_series JSON list as specified — no deviation from the numeric/textual content of Task 1's `<action>` block
- Diverged from migration 230's literal `INSERT ... VALUES (NOW(), ...) ON CONFLICT DO NOTHING` shape for `config_history` (Block 5), replacing it with `INSERT ... SELECT * FROM (VALUES ...) v WHERE NOT EXISTS (SELECT 1 FROM config_history ch WHERE ch.config_key = v.config_key AND ch.changed_by = v.changed_by)` — the literal-VALUES form is provably not idempotent when the target table's PK includes `timestamp`, and this plan's own Task 2 acceptance criteria requires the migration to be re-runnable with zero additional effect. All plan-mandated grep-based acceptance criteria (11 `ADD COLUMN`, 33 `materiality.` occurrences, 20 `[initial_estimate]`, 2 `[conventional]`, 11 `migration_346` literal occurrences, exactly 1 `INSERT INTO config_history` statement) still hold against the fixed file.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed non-idempotent config_history seed causing silent row duplication on re-run**
- **Found during:** Task 2 (idempotency verification — running the migration a second time)
- **Issue:** The plan's specified `INSERT INTO config_history (...) VALUES (NOW(), ...), ... ON CONFLICT DO NOTHING;` shape relies on `ON CONFLICT` finding a matching unique/PK constraint to trigger on. `config_history`'s PK is `(timestamp, config_key, version)` — since `timestamp` is `NOW()` at each invocation, the second `psql -f` run's rows never collide with the first run's rows on the PK, so `ON CONFLICT DO NOTHING` silently does nothing and all 11 rows get inserted a second time (verified live: count went from 11 to 22 after a second apply). This directly violates Task 2's own acceptance criterion (`count(*) ... = 11` after a second invocation) and the plan's stated idempotency requirement.
- **Fix:** Deleted the 22 duplicated test rows, then rewrote the `INSERT INTO config_history` statement to select from a `VALUES` list guarded by a correlated `WHERE NOT EXISTS (SELECT 1 FROM config_history ch WHERE ch.config_key = v.config_key AND ch.changed_by = v.changed_by)` clause instead of relying on `ON CONFLICT`. Re-applied the migration twice from a clean `config_history` state: first run inserted 11 rows, second run inserted 0.
- **Files modified:** production/migrations/346_itr_materiality_evidence_columns.sql
- **Verification:** `psql -f` run twice in sequence — first invocation `INSERT 0 11`, second invocation `INSERT 0 0`; live `SELECT count(*) FROM config_history WHERE config_key LIKE 'alpha.tag_calibrator.materiality.%' AND changed_by = 'migration_346';` returns exactly `11` after the second run. All plan-specified grep acceptance criteria (including the literal `migration_346` occurrence count of 11) re-verified against the fixed file.
- **Committed in:** `14292958f` (Task 2 commit — the fix landed before the file was ever committed, so there is no separate "broken" commit in history)

---

**Total deviations:** 1 auto-fixed (Rule 1 - bug)
**Impact on plan:** Necessary for correctness — the plan's own acceptance criteria required idempotency, and the plan's literal SQL shape (copied from migration 230's pattern) does not achieve it for this particular table. No scope creep; the fix is scoped entirely to Block 5's `config_history` INSERT statement.

## Issues Encountered
None beyond the deviation documented above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All Pass 4 evidence columns, the `instrument_tags_active` view, and all 11 `alpha.tag_calibrator.materiality.*` APR keys are live in the database and ready for 175-02/175-03/175-04/175-05 to read/write
- Every new column is NULL/absent of data by design — TagCalibrator's next run (plan 03) populates them; no pre-existing `instrument_tags` row or column was mutated
- No blockers for downstream plans in this phase

---
*Phase: 175-itr-materiality-filtered-empirical-tags-for-breadth-peer-gro*
*Completed: 2026-09-23*

## Self-Check: PASSED

- FOUND: production/migrations/346_itr_materiality_evidence_columns.sql
- FOUND: .planning/phases/175-itr-materiality-filtered-empirical-tags-for-breadth-peer-gro/175-01-SUMMARY.md
- FOUND: commit 14292958f (migration author + apply)
- FOUND: commit 99f8840a3 (SUMMARY.md)
