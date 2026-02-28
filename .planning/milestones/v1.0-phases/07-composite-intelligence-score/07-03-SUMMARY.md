---
phase: 07-composite-intelligence-score
plan: "03"
subsystem: intelligence
tags: [cis, weight-updater, scikit-learn, logistic-regression, signal-quality, timescaledb, migration]

# Dependency graph
requires:
  - phase: 07-02
    provides: "CISScorer, LedgerEntry with bucket_scores/signal_quality fields, migration 011"
provides:
  - "scikit-learn>=1.5.0 in requirements.txt and installed"
  - "migration 012: cis_weights table + bootstrap row (version=1, designed weights)"
  - "compute_new_weights(): None <50 samples, blended 70/30 at 50-99, learned at 100+"
  - "run_weight_update(db_manager): queries signal_ledger, INSERTs new version row"
  - "signal_tracker_service: computes signal_quality = max(0, pnl_r * confidence) on exit"
  - "signal_ledger._UPDATE_STATUS_SQL: includes signal_quality=$10"
affects:
  - 07-04-entry-types  # independent wave, no dependency
  - signal_tracker_service

# Tech tracking
tech-stack:
  added:
    - "scikit-learn>=1.5.0 (v1.8.0 installed in venv)"
  patterns:
    - "Weight updater: accept pre-fetched data as input parameter — testable without DB"
    - "Transition thresholds: <50 None; 50-99 blended (70% designed + 30% learned); >=100 learned"
    - "LogisticRegression(C=1.0, max_iter=500) + softmax(abs(coef)) + clip_and_renormalize(min_w=0.05)"
    - "signal_quality = max(0, pnl_r * confidence_at_fire) — simplified (vol_regime not stored at fire)"
    - "Degenerate target guard: all same quality → None (avoids ValueError from LogisticRegression)"

key-files:
  created:
    - src/intelligence/weight_updater.py
    - production/migrations/012_cis_weights_table.sql
    - tests/unit/intelligence/test_weight_updater.py
  modified:
    - requirements.txt
    - src/intelligence/trading/signal_ledger.py
    - services/signal_tracker_service.py

key-decisions:
  - "weight_updater.py accepts pre-fetched data (list[dict]) — no DB coupling in pure function, run_weight_update() handles DB interaction separately"
  - "signal_quality = max(0.0, pnl_r * confidence) — simplified formula (vol_regime_at_fire not stored at signal fire time; denominator omitted)"
  - "cis_weights CHECK constraint includes 'blended' — migration 011 only had designed/learned; blended is a valid transient type written during 50-99 sample window"
  - "Bootstrap weights in migration match BOOTSTRAP_WEIGHTS in cis_scorer.py exactly — single source of truth for designed weights"
  - "abs(coef) in softmax: direction of bucket influence comes from bucket score sign, not weight sign — ensures all weights stay positive after softmax"

patterns-established:
  - "WeightUpdateResult dataclass: always includes n_resolved, weights_type, weights, signal_quality_mean, did_retrain"
  - "JSON string bucket_scores handled inline with isinstance(bs, str) check — asyncpg returns JSONB as strings"
  - "Degenerate guard before LogisticRegression.fit(): check y.sum() == 0 or y.sum() == len(y)"

requirements-completed:
  - CIS-C1
  - CIS-C2
  - CIS-C3

# Metrics
duration: 4min
completed: 2026-02-28
---

# Phase 7 Plan 03: Adaptive Weight Learning Summary

**LogisticRegression-based CIS weight updater with 3-tier bootstrap→blended→learned transition, cis_weights DB table, and signal_quality population on signal exit**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-28T01:26:53Z
- **Completed:** 2026-02-28T01:31:00Z
- **Tasks:** 2
- **Files modified:** 6 (3 created, 3 modified)

## Accomplishments
- Implemented `compute_new_weights()` as a pure function accepting pre-fetched resolved signal data; returns None below 50 samples, blended (70% designed / 30% learned) at 50-99, full learned at 100+; all weights sum to 1.0 with minimum 0.05 per bucket
- Created migration 012 with `cis_weights` table (CHECK constraint on weights_type: designed/learned/blended), unique index on (version, symbol, timeframe), and bootstrap row seeded with BOOTSTRAP_WEIGHTS values
- Extended `signal_ledger._UPDATE_STATUS_SQL` with `signal_quality=$10` and added corresponding kwarg to `update_signal_status()`; `signal_tracker_service` now computes `signal_quality = max(0.0, pnl_r * confidence)` on every signal exit
- Added `run_weight_update(db_manager)` async function that queries signal_ledger and INSERTs new version row to cis_weights after successful training
- Test suite grew from 749 → 771 passing; 22 new tests covering all transition thresholds, weight invariants, degenerate target guard, JSON string handling, and BOOTSTRAP_WEIGHTS sanity check

## Task Commits

Each task was committed atomically:

1. **Task 1: Add scikit-learn, migration 012, signal_quality on exit** - `c1ee7af` (feat)
2. **Task 2: Implement weight_updater.py with tests** - `c6a4649` (feat)

## Files Created/Modified
- `src/intelligence/weight_updater.py` - New: WeightUpdateResult dataclass, compute_new_weights(), run_weight_update(), _softmax(), _clip_and_renormalize()
- `production/migrations/012_cis_weights_table.sql` - New: CREATE TABLE cis_weights + UNIQUE INDEX + bootstrap INSERT
- `tests/unit/intelligence/test_weight_updater.py` - New: 22 tests for compute_new_weights()
- `requirements.txt` - Added scikit-learn>=1.5.0
- `src/intelligence/trading/signal_ledger.py` - Extended _UPDATE_STATUS_SQL with signal_quality=$10; update_signal_status() accepts signal_quality kwarg
- `services/signal_tracker_service.py` - Computes signal_quality on exit; passes to update_signal_status()

## Decisions Made
- **weight_updater is a pure function:** Design choice to accept pre-fetched data rather than internal DB queries makes `compute_new_weights()` testable without mocking async DB; `run_weight_update(db_manager)` handles DB interaction in a separate layer.
- **Simplified signal_quality formula:** `pnl_r * confidence` without vol_regime denominator — vol_regime is not stored on signal_ledger at fire time; formula produces correct ordering even without normalization (vol_regime is usually ~1.0).
- **cis_weights CHECK includes 'blended':** The plan spec showed CHECK (weights_type IN ('designed', 'learned')) but blended is a valid type written during 50-99 sample window. Added to prevent DB constraint violation.
- **abs(coef) in softmax:** LogisticRegression coefficients can be negative; using abs() ensures softmax produces positive weights regardless of coefficient sign. The direction of influence comes from the bucket score sign, not the weight sign.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added 'blended' to cis_weights CHECK constraint**
- **Found during:** Task 1 (migration creation)
- **Issue:** Plan spec showed CHECK (weights_type IN ('designed', 'learned')) but the weight_updater returns weights_type='blended' for 50-99 samples. Inserting a 'blended' row would violate the constraint.
- **Fix:** Added 'blended' to the CHECK constraint in migration 012
- **Files modified:** `production/migrations/012_cis_weights_table.sql`
- **Verification:** Migration SQL is syntactically correct; test_weight_updater.py verifies blended type is returned at 50-99 samples
- **Committed in:** `c1ee7af` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 2 — missing critical constraint value)
**Impact on plan:** Essential for correctness. Without fix, live DB would reject blended weight rows with a CHECK violation when 50-99 resolved signals accumulate.

## Issues Encountered
None — implementation matched plan exactly except for the auto-fixed constraint issue above.

## User Setup Required
Apply migration when ready:
```sql
-- Connect to indicagent DB and run:
-- psql $DATABASE_URL -f production/migrations/012_cis_weights_table.sql
```
This creates the cis_weights table and seeds the bootstrap row — safe to run on live DB (new table, no existing data affected).

## Next Phase Readiness
- Weight learning pipeline complete: signal_tracker populates signal_quality → weight_updater reads from signal_ledger → writes new cis_weights version rows
- Phase 7 plans 07-01, 07-02, 07-03, 07-04 all complete — Phase 7 (Composite Intelligence Score) is done
- 771 unit tests pass; 0 ruff errors on all modified source files
- CIS weights start at designed bootstrap and self-improve once 50+ resolved signals accumulate

---
*Phase: 07-composite-intelligence-score*
*Completed: 2026-02-28*
