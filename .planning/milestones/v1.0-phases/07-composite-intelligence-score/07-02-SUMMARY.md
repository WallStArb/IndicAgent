---
phase: 07-composite-intelligence-score
plan: "02"
subsystem: intelligence
tags: [cis, scorer, aggregator, signal-ledger, timescaledb, tdd]

# Dependency graph
requires:
  - phase: 07-01
    provides: "5 CIS evidence-contributor I7 plugins (CHoCHReversal, FVGFill, PatternCompletion, DivergenceStack, RegimeTransition)"
provides:
  - "CISScorer class: 6-bucket weighted directional scorer [-1.0, +1.0], fires when abs(CIS) > 0.35 and buckets_agreeing >= 3"
  - "CIS-augmented aggregate(): CIS overrides winner-pick direction when features provided; fallback preserved"
  - "LedgerEntry with 4 CIS fields (cis_score, bucket_scores, weights_version, signal_quality); to_insert_params() returns 28-tuple"
  - "Migration 011: ADD COLUMN IF NOT EXISTS for 4 CIS columns + partial index for weight_updater"
  - "signal_generator_service.py passes features= to aggregate() and CIS fields to LedgerEntry"
affects:
  - 07-03-weight-updater  # reads signal_ledger.bucket_scores / weights_version
  - signal_generator_service

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "CIS bucket scoring: 6 buckets, weighted sum, threshold + agreement gate before fire"
    - "agreeing count uses sign(cis_score) not magnitude — bucket agrees when bucket_score * sign > 0.1"
    - "CIS overrides priority-pick; fallback path (_aggregate_fallback) preserved intact"
    - "New LedgerEntry fields use None defaults — fully backward compatible with pre-CIS signals"

key-files:
  created:
    - src/intelligence/trading/cis_scorer.py
    - production/migrations/011_signal_ledger_cis_cols.sql
    - tests/unit/intelligence/test_cis_scorer.py
  modified:
    - src/intelligence/trading/aggregator.py
    - src/intelligence/trading/signal_ledger.py
    - services/signal_generator_service.py
    - tests/unit/intelligence/test_aggregator.py
    - tests/unit/intelligence/test_signal_ledger.py

key-decisions:
  - "agreeing logic uses sign(cis_score) not cis_score magnitude — prevents all buckets from failing threshold when CIS is below 0.35 but individual buckets are directional"
  - "CIS override path (_aggregate_via_cis) synthesizes a signal in CIS direction when no plugin fires in that direction — ensures CIS can direct even when plugins are mixed"
  - "CIS fields attached to selected_signal dict AND AggregatedResult — both pathways available to consumers"
  - "plan verification command used sparse features (CIS ~0.25 < threshold) — implementation correct with full features (CIS 0.558); test suite covers both cases"
  - "bucket_scores serialized via json.dumps() at to_insert_params() position 25 (0-based) — matches asyncpg ::jsonb cast at $26"
  - "signal_quality always None at fire time; signal_tracker_service.py populates on exit (unchanged, no scope creep)"

patterns-established:
  - "CIS scorer: test with full bullish_features() set to validate fire threshold; sparse features may not reach 0.35"
  - "LedgerEntry backward compat: all new CIS fields have None defaults; existing signal construction needs no changes"

requirements-completed:
  - CIS-B1
  - CIS-B2
  - CIS-B3

# Metrics
duration: 7min
completed: 2026-02-28
---

# Phase 7 Plan 02: CIS Bucket Scorer + Aggregator Replacement Summary

**CISScorer with 6-bucket weighted directional scoring replaces winner-pick aggregator; LedgerEntry extended to 28-column INSERT; signal_generator_service wired end-to-end**

## Performance

- **Duration:** 7 min
- **Started:** 2026-02-28T01:15:58Z
- **Completed:** 2026-02-28T01:23:00Z
- **Tasks:** 2
- **Files modified:** 7 (3 created, 4 modified)

## Accomplishments
- Implemented CISScorer class with 6 bucket scoring methods (trend/momentum/structure/pattern/institutional/regime), BOOTSTRAP_WEIGHTS summing to 1.0, fires when abs(CIS) > 0.35 AND buckets_agreeing >= 3
- Rewrote aggregator.py to accept `features=` kwarg; CIS overrides direction when fired; original priority/majority/regime_tiebreak fallback preserved as `_aggregate_fallback()`
- Extended LedgerEntry with 4 new fields and to_insert_params() returns 28-tuple matching new _INSERT_SQL with $25-$28 for cis_score/bucket_scores/weights_version/signal_quality
- Created migration 011 with ADD COLUMN IF NOT EXISTS for all 4 CIS columns plus partial index for weight_updater training queries
- Wired `features=features` into signal_generator_service.py aggregate() call; LedgerEntry construction passes CIS fields from AggregatedResult
- Test suite grew from 708 → 749 passing; 16 new CIS scorer tests + 7 aggregator CIS tests + 2 signal_ledger CIS field tests

## Task Commits

Each task was committed atomically:

1. **Task 1: TDD — CISScorer class and updated aggregator** - `8df195d` (feat)
2. **Task 2: Extend LedgerEntry, add DB migration, wire features=** - `f63f174` (feat)

## Files Created/Modified
- `src/intelligence/trading/cis_scorer.py` - New: CISScorer, CISResult, BOOTSTRAP_WEIGHTS, BUCKET_NAMES
- `src/intelligence/trading/aggregator.py` - Rewritten: CIS-augmented aggregate(), AggregatedResult.cis_score/bucket_scores/weights_version fields
- `src/intelligence/trading/signal_ledger.py` - Extended: 4 CIS fields on LedgerEntry, 28-tuple to_insert_params(), updated _INSERT_SQL
- `production/migrations/011_signal_ledger_cis_cols.sql` - New: ADD COLUMN IF NOT EXISTS for all 4 CIS columns + partial index
- `services/signal_generator_service.py` - One-line aggregate() change + 4 CIS kwargs in build_ledger_entries()
- `tests/unit/intelligence/test_cis_scorer.py` - New: 16 tests covering all 6 buckets, fire conditions, invariants, plugin integration
- `tests/unit/intelligence/test_aggregator.py` - Extended: 7 new CIS integration tests
- `tests/unit/intelligence/test_signal_ledger.py` - Extended: len==28 assertion + CIS field serialization test

## Decisions Made
- **agreeing logic uses sign(cis_score), not cis_score magnitude:** The plan's spec multiplied `bucket_score * cis_score` (raw value like 0.249), which made all buckets fail the 0.1 threshold. Changed to `bucket_score * sign(cis_score)` — a bucket score of 0.28 with positive CIS now correctly evaluates as 0.28 > 0.1 = agreeing. Verified: full bullish features produce CIS=0.558, direction=1, 5 buckets agreeing.
- **CIS synthesis when no matching plugin:** When CIS fires but no plugin signal matches CIS direction, the aggregator takes the highest-priority signal and overrides its direction. This ensures CIS always has a signal to return when it fires.
- **plan verification command uses sparse features:** The plan's smoke-test command (`trend_regime=0.8, bos_detected=1.0, ob_type=1, hmm_prob_trending_up=0.7` only) produces CIS=0.249 which doesn't meet 0.35 threshold. This is correct behavior — with only 5 of ~25 features populated, the score is proportionally lower. Full bullish feature set produces CIS=0.558.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed agreeing bucket counting logic**
- **Found during:** Task 1 verification (final plan verification command)
- **Issue:** Plan spec: `bucket_scores[b] * (cis_score if cis_score != 0 else 1)`. With cis_score=0.249 and bucket_score=0.28, product is 0.0697 < 0.1 — all buckets fail. The design intent is clearly "does this bucket push in the CIS direction?" not "does the product of score and magnitude exceed noise?"
- **Fix:** Changed `cis_sign = cis_score` to `cis_sign = 1.0 if cis_score >= 0 else -1.0` — now correctly uses sign(cis_score) for the agreement gate
- **Files modified:** `src/intelligence/trading/cis_scorer.py`
- **Verification:** Full bullish features: agreeing=5; neutral features: agreeing=0 (correct). All 16 CIS tests pass.
- **Committed in:** `f63f174` (included in Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 — bug in agreeing count logic)
**Impact on plan:** Essential for correctness. Without fix, CIS would never fire because agreeing count uses raw cis_score magnitude as a multiplier, making the 0.1 threshold effectively 0.25+ per-bucket rather than 0.1.

## Issues Encountered
None beyond the auto-fixed deviation above.

## User Setup Required
Apply migration when ready:
```sql
-- Connect to indicagent DB and run:
-- psql $DATABASE_URL -f production/migrations/011_signal_ledger_cis_cols.sql
```
This adds 4 nullable columns to signal_ledger — safe to run on live table (no data migration needed).

## Next Phase Readiness
- CIS scoring pipeline complete end-to-end: features → CISScorer → AggregatedResult → LedgerEntry → signal_ledger
- 07-03 (weight_updater) can now query `signal_ledger.bucket_scores` + `signal_quality` via `idx_ledger_resolved_cis` partial index
- 07-04 (trade_framer at_limit/at_pullback) is independent — can proceed in parallel
- All 749 unit tests pass; 0 ruff errors on modified source files

---
*Phase: 07-composite-intelligence-score*
*Completed: 2026-02-28*
