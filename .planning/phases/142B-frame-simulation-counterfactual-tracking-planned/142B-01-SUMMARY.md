---
phase: 142B-frame-simulation-counterfactual-tracking
plan: 01
subsystem: database
tags: [timescaledb, hypertable, batch-compute, apr, alpha-frames, adaptive-parameter-registry]

# Dependency graph
requires:
  - phase: 142A-ensemble-ic-measurement
    provides: alpha_events population + EIC-04 PASS verdict (54/1425=3.79%), hold_max_bars APR keys
provides:
  - alpha_frames hypertable (composite PK, no FK to alpha_events, D-04 lifecycle CHECK)
  - AlphaFrameWriter(BaseBatch) writing one primary frame per alpha_events row (FRAME-01)
  - compute_frame_geometry / compute_expected_r_snapshot pure functions for Plan 02 reuse
  - 9 new APR keys (alpha.frame.*, alpha.scoring.*, infra.alpha_frame_writer.*, infra.counterfactual_tracker.*)
  - docs/plans/SHADOW-REVIEW.md frozen Phase 147 promotion criteria
affects: [142B-02-counterfactual-tracker, 143, 147]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Composite hypertable PK containing the partition column (frame_id, bar_ts) instead of a sole-uuid PK, when the partition column cannot be the sole PK"
    - "Anti-join checkpoint: target table itself is the resume state for --backfill mode (no separate checkpoint file)"
    - "Per-(symbol, tf) partitioned chunked write to avoid one long-running read transaction over a multi-million-row backlog"
    - "Diagnostic snapshot columns (gross_expected_r/cost_r/net_expected_r) computed at write time from signal-only inputs, explicitly documented as non-gate reporting columns via SQL COMMENT ON COLUMN"

key-files:
  created:
    - production/migrations/214_alpha_frames_schema.sql
    - services/alpha_frame_writer.py
    - docs/plans/SHADOW-REVIEW.md
    - tests/unit/test_alpha_frames_schema.py
    - tests/unit/test_alpha_frame_writer_geometry.py
    - tests/unit/test_alpha_frame_writer.py
  modified:
    - services/service_auditor.py
    - scripts/infrastructure/backfill/infrastructure_truncate_derived_tables.sh

key-decisions:
  - "frame_id is a deterministic content_key TEXT (not a uuid), PK is composite (frame_id, bar_ts) so create_hypertable succeeds (review H1 fix already baked into the plan)"
  - "No FK from alpha_frames to alpha_events; provenance carried by corpus_run_id/weight_epoch columns; truncate script updated as the operational substitute for FK-CASCADE (review M1 fix already baked into the plan)"
  - "ATR is a caller-supplied price-unit value to compute_frame_geometry, never read from feature_vectors (review H2 fix already baked into the plan) — Plan 02 computes it from market_data_ohlcv"
  - "gross_expected_r/net_expected_r are diagnostic magnitudes only, explicitly documented in SQL column comments and SHADOW-REVIEW.md as never a gate input (review M5 fix already baked into the plan)"
  - "SHADOW-REVIEW.md's drawdown and IC-Sharpe-cliff criteria stated with an explicit numeric base (peak cumulative R; last-20d >= 0.5x full-period) per review M6"

patterns-established:
  - "Pattern: compute_frame_geometry / compute_expected_r_snapshot as pure module-level functions in the writer service, imported by the downstream tracker service rather than duplicated"

requirements-completed: [FRAME-01, FRAME-03]

# Metrics
duration: ~35min
completed: 2026-07-10
---

# Phase 142B Plan 01: Migration 214 + AlphaFrameWriter + SHADOW-REVIEW.md Summary

**alpha_frames hypertable (composite PK, no FK) + AlphaFrameWriter(BaseBatch) writing one primary hypothetical frame per alpha_events row via per-(symbol,tf) chunked anti-join, plus the frozen five-criterion SHADOW-REVIEW.md pre-commitment document for Phase 147 promotion.**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-07-10T10:14:00Z
- **Completed:** 2026-07-10T10:29:00Z
- **Tasks:** 3
- **Files modified:** 8 (6 created, 2 modified)

## Accomplishments

- `alpha_frames` created as a TimescaleDB hypertable with a composite `(frame_id, bar_ts)` PK
  (containing the partition column, so `create_hypertable` applies cleanly — applied and
  verified against the live `indicagent` DB), D-04's corrected lifecycle CHECK constraint,
  `corpus_run_id`/`weight_epoch` provenance columns, and no FK to `alpha_events`.
- 9 new APR keys seeded (`alpha.frame.stop_atr_mult`/`target_r_multiple`/`atr_period`,
  `alpha.scoring.min_strategy_n`/`bootstrap_max_n`/`bootstrap_batch`,
  `infra.alpha_frame_writer.chunk_size`, `infra.counterfactual_tracker.itersize`/`workers`) —
  verified live in `config_state`.
- `AlphaFrameWriter(BaseBatch)` writes one `frame_variant='primary'` row per pending
  `alpha_events` row via a per-(symbol, tf) anti-join + chunked flush, idempotent via
  `content_key`-derived `frame_id` and `ON CONFLICT (event_id, bar_ts, frame_variant) DO
  NOTHING`. Geometry columns are left NULL for Plan 02's `CounterfactualTracker` to fill.
- `compute_frame_geometry` (pure fn, ATR-only, direction-correct for long and short) and
  `compute_expected_r_snapshot` (pure fn, D-03 diagnostic triad, direction-agnostic) are both
  defined here and available for Plan 02 to import.
- `docs/plans/SHADOW-REVIEW.md` frozen with five numerically-evaluable criteria (60 trading
  days, 95% CI day-clustered block bootstrap, Sharpe > 0.5, max drawdown < 25% of peak
  cumulative R, no IC-Sharpe cliff), the gross-gate decision (D-01), the `net_expected_r`
  reporting-only column (D-02), and the day-clustered block-bootstrap method's residual
  cross-symbol correlation caveat (review H4).
- `indicagent-alpha-frame-writer` registered as a oneshot in `service_auditor.py`; `alpha_frames`
  added to the corpus-rebuild truncate script.

## Task Commits

1. **Task 1: Migration 214 — alpha_frames hypertable + APR key seeds + service/truncate registration** - `9198be07` (feat)
2. **Task 2: AlphaFrameWriter service — FRAME-01 pure geometry + expected-R snapshot + chunked idempotent write** - `8c326f79` (feat)
3. **Task 3: SHADOW-REVIEW.md frozen pre-commitment document** - `4fcdbca9` (docs)

_No separate plan-metadata commit — this is a worktree-isolated parallel executor run; the
orchestrator handles STATE.md/ROADMAP.md updates centrally after merge (per its instructions,
not a deviation)._

## Files Created/Modified

- `production/migrations/214_alpha_frames_schema.sql` - `alpha_frames` hypertable DDL + 9 APR key seeds (config_schema/config_state/config_history triad)
- `services/alpha_frame_writer.py` - `AlphaFrameWriter(BaseBatch)`, `compute_frame_geometry`, `compute_expected_r_snapshot`, `FrameConfig`
- `docs/plans/SHADOW-REVIEW.md` - frozen Phase 147 promotion criteria
- `tests/unit/test_alpha_frames_schema.py` - migration DDL assertions (13 tests)
- `tests/unit/test_alpha_frame_writer_geometry.py` - pure-fn geometry math, long/short (6 tests)
- `tests/unit/test_alpha_frame_writer.py` - FrameConfig binding, expected-R snapshot, idempotency, source guards (14 tests)
- `services/service_auditor.py` - registered `indicagent-alpha-frame-writer` in `_DAG_ORDER` (priority 8) and `_ONESHOT_UNITS`
- `scripts/infrastructure/backfill/infrastructure_truncate_derived_tables.sh` - added `alpha_frames` to the corpus-rebuild truncate list, pre/post row-count SELECTs, and confirmation prompt wording

## Decisions Made

None beyond what the plan already specified — the plan's action text had already incorporated
the four cross-AI review fixes (H1 PK/hypertable identity, H2 ATR source, M1 FK/truncation
position, M5 expected-R units) and the M6 numeric-criteria requirement for SHADOW-REVIEW.md, so
this execution implemented those as written rather than making new judgment calls.

## Deviations from Plan

None - plan executed exactly as written. (Two self-inflicted overly-strict test assertions were
tightened during implementation — grep-based tests that initially matched the plan's own
explanatory comments rather than actual code/config content; these were fixed in-place before
the Task 1/Task 2 commits, not tracked as deviations since they never affected committed
production code, only test-authoring precision within the same task.)

## Issues Encountered

None. Migration 214 applied cleanly against the live `indicagent` DB on the first attempt;
`alpha_frames` confirmed present in `timescaledb_information.hypertables`. Full
`tests/unit/` suite run showed exactly the one pre-existing failure already tracked in STATE.md
(`test_feature_factory.py::TestRegimePrimitives::test_no_smooth_or_backward_in_factory`, todo-086
false positive) with 5601 passed / 42 skipped — no new failures introduced by this plan's changes.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `alpha_frames` schema, `AlphaFrameWriter`, and the frozen `SHADOW-REVIEW.md` are all in place.
  Plan 02 (`CounterfactualTracker`, FRAME-02/03/04) can now import `compute_frame_geometry` from
  `services/alpha_frame_writer.py` and build the T+1 geometry fill + price-path scan against the
  `alpha_frames` schema this plan created.
- `AlphaFrameWriter` has not yet been run against the live `alpha_events` backlog (12M+ rows) —
  that is an operational step for after Plan 02 lands (running the writer before the tracker
  exists would leave every frame permanently `status='open'` with no path to closure). No
  blocker; simply sequencing the two-plan wave in the order the phase intends.
- No stubs: every code path in `AlphaFrameWriter` is fully wired (no hardcoded empty return
  values, no placeholder text, no unconnected data source).

---
*Phase: 142B-frame-simulation-counterfactual-tracking*
*Completed: 2026-07-10*
