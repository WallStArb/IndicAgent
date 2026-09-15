-- Migration 341: additive compute_eligible_1d column, a 1d-only compute-readiness
-- dimension (Phase 174, plan 174-13, D-07a continued / D-09; closes the D-09 down-cap
-- cohort's schema need).
--
-- D-09 restricts the down-cap stratified sample to 1d bars only -- those symbols will
-- have no 5m/15m/1h history at all. Plan 02's compute_eligible column (migration 337)
-- and its COMPUTE_READY_PREDICATE_SQL require all four timeframes; a 1d-only symbol can
-- never satisfy that predicate and must never be promoted to compute_eligible=true. This
-- migration adds a second, independent eligibility column scoped to 1d alone, so a
-- 1d-only symbol is structurally unable to reach dimension='compute' (it does not carry
-- compute_eligible=true) while still being addressable at dimension='compute_1d'.
--
-- Default is DELIBERATELY the opposite of migration 337's compute_eligible DEFAULT true.
-- 337 was retrofitting a column onto a universe that was already uniformly
-- compute-ready (measured: all 231 active symbols cleared all four timeframes), so
-- `true` was the measured truth for the existing rows. compute_eligible_1d is a
-- forward-looking gate for a cohort (D-09's down-cap sample) that does not exist in the
-- instruments table yet -- the honest default for any row inserted later, before its 1d
-- backfill is measured complete, is "not yet proven." DEFAULT false reflects that.
--
-- Default mapping for the 253 existing rows, justified by a MEASURED query (this
-- migration's own header), not an assumption:
--   compute_eligible_1d = true for the 231 rows where is_active = true AND a
--     fetch_complete backfill_status row exists for tf='1d' AND
--     market_data_ohlcv_tradeable has at least one row at timeframe='1d'. Measured via
--     SELECT count(*) against the live database immediately before writing this file:
--     231 rows match. This equals `SELECT count(*) FROM instruments WHERE is_active =
--     true AND compute_eligible = true` at the same point in time (231) -- every
--     currently-active symbol is 1d-complete, consistent with Plan 02's four-timeframe
--     audit finding (1d is one of the four timeframes that audit already verified).
--   compute_eligible_1d stays false (the column default) for every is_active = false row
--     and for any future D-09 down-cap symbol until its own 1d backfill is measured
--     complete and this same predicate is re-run to promote it explicitly.
--
-- compute_eligible_1d is deliberately INDEPENDENT of compute_eligible, not implied by
-- it and not a narrowing of it. A symbol carrying compute_eligible_1d = true and
-- compute_eligible = false is the intended steady state for the Phase 174 D-09 down-cap
-- cohort -- not an inconsistency to be repaired. Conversely every existing
-- four-timeframe symbol has compute_eligible_1d = true as well (it is 1d-complete by
-- construction of the four-timeframe predicate), so a 1d cross-sectional cell can see
-- the full 1d-capable universe, not a subset.
--
-- This migration deliberately does NOT touch instruments.compute_eligible,
-- COMPUTE_READY_PREDICATE_SQL, or any of the three existing get_active_contracts()
-- dimension clause strings ('backfill'/'compute'/'live') -- purely additive alongside
-- them. Plan 174-13's own acceptance criteria require git diff on those to be empty.
--
-- Idempotent: DDL uses ADD COLUMN IF NOT EXISTS (migration 158's / 337's pattern); the
-- UPDATE is naturally idempotent (re-running it re-asserts the same values for the same
-- WHERE clause, and rows already compute_eligible_1d = true from a prior run simply get
-- re-set to the same value). Safe to re-run.

BEGIN;

-- ── Block 1: additive DDL, forward-looking safe default ──────────────────────────

ALTER TABLE instruments
    ADD COLUMN IF NOT EXISTS compute_eligible_1d boolean NOT NULL DEFAULT false;

-- ── Block 2: explicit backfill statement ─────────────────────────────────────────
-- The semantic mapping decision is a visible, reviewable SQL statement, not only an
-- implicit column default (CLAUDE.md: "silent wrong answers are worse than loud
-- crashes"; migration 337's own convention). Uses the same i.symbol outer-alias
-- convention as COMPUTE_READY_PREDICATE_SQL / COMPUTE_READY_1D_PREDICATE_SQL in
-- scripts/analysis/instrument_compute_eligibility_audit.py, scoped to '1d' only.

UPDATE instruments i
SET compute_eligible_1d = true
WHERE i.is_active = true
  AND (SELECT count(*) FROM backfill_status b
       WHERE b.symbol = i.symbol AND b.tf = '1d' AND b.fetch_complete) = 1
  AND (SELECT count(*) FROM market_data_ohlcv_tradeable m
       WHERE m.symbol = i.symbol AND m.timeframe = '1d') > 0;

-- ── Block 3: schema-level documentation ──────────────────────────────────────────
-- The semantics live in the schema itself, not only in a planning doc.

COMMENT ON COLUMN instruments.compute_eligible_1d IS
    'Fourth eligibility dimension (Phase 174 D-09), independent of compute_eligible: '
    'this symbol''s 1d series is complete enough to participate in 1d-timeframe '
    'cross-sectional compute (dimension=''compute_1d'' in get_active_contracts()). '
    'Deliberately NOT implied by or narrowed from compute_eligible -- a symbol carrying '
    'compute_eligible_1d = true AND compute_eligible = false is the intended steady '
    'state for the Phase 174 D-09 down-cap cohort (1d bars only, no 5m/15m/1h history), '
    'not an inconsistency to be repaired. Defaults false for any newly inserted row '
    'until its own 1d backfill is measured complete via the same two-clause predicate '
    '(COMPUTE_READY_1D_PREDICATE_SQL in scripts/analysis/'
    'instrument_compute_eligibility_audit.py) used in this migration''s backfill UPDATE.';

COMMIT;
