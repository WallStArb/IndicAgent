-- Migration 352: Phase 174 code review remediation (174-REVIEW.md WR-01, WR-04, WR-05, WR-07).
--
-- 1. WR-04: instruments.compute_eligible defaulted to true, so any insert path that did not
--    name the column (POST /instruments, DatabaseManager.upsert_instruments) created a
--    compute-eligible row that skipped the compute-readiness predicate entirely. The default
--    becomes false. The 22 inactive rows still carry the old default's true; they are
--    cleared, and a trigger plus a CHECK keep every inactive row at false from then on, for
--    every writer (API PATCH, soft delete, upserts), so a re-activation can never resurrect
--    a stale eligibility claim.
--
-- 2. WR-01: TagCalibrator measured the failed-gate D-09 pilot cohort (is_active=true,
--    compute_eligible=false) into its run-level BH-FDR family: 218 empirical rows across 32
--    symbols, which also shifted every other symbol's adjusted p-values. The reader is fixed
--    in code; here those rows are expired (valid_to set, evidence annotated), not deleted --
--    the measurements stay on record. The remaining symbols' q-values need one TagCalibrator
--    re-run after this migration to come from a clean family.
--
-- 3. WR-05 / WR-07: two infra.* APR keys for ic_engine's disk-backed scratch headroom check,
--    replacing a module constant and adding a reserve floor for the database, which shares
--    the scratch directory's filesystem.
--
-- No compressed hypertable is touched; no VACUUM step required.

BEGIN;

-- 1. WR-04 ------------------------------------------------------------------------------

ALTER TABLE instruments ALTER COLUMN compute_eligible SET DEFAULT false;

UPDATE instruments
SET compute_eligible = false, compute_eligible_1d = false, live_tradeable = false
WHERE is_active = false
  AND (compute_eligible OR compute_eligible_1d OR live_tradeable);

-- Enforce "an inactive row holds no eligibility" in the database, for every writer: a
-- BEFORE trigger clears the flags whenever a row is written with is_active not true (a
-- soft delete, PATCH, or an inactive insert), so a later re-activation can only start
-- from false; the CHECK makes a violating row unrepresentable. Individual insert paths
-- no longer re-implement the rule.
CREATE OR REPLACE FUNCTION instruments_clear_eligibility_when_inactive()
RETURNS trigger
LANGUAGE plpgsql
AS $fn$
BEGIN
  IF NEW.is_active IS NOT TRUE THEN
    NEW.compute_eligible := false;
    NEW.compute_eligible_1d := false;
    NEW.live_tradeable := false;
  END IF;
  RETURN NEW;
END
$fn$;

DROP TRIGGER IF EXISTS trg_instruments_clear_eligibility_when_inactive ON instruments;
CREATE TRIGGER trg_instruments_clear_eligibility_when_inactive
BEFORE INSERT OR UPDATE ON instruments
FOR EACH ROW EXECUTE FUNCTION instruments_clear_eligibility_when_inactive();

ALTER TABLE instruments ADD CONSTRAINT instruments_inactive_holds_no_eligibility
CHECK (is_active IS TRUE OR NOT (compute_eligible OR compute_eligible_1d OR live_tradeable));

COMMENT ON COLUMN instruments.compute_eligible IS
    'Dimension 2 of 3 (Phase 174 D-07): COMPUTE-ELIGIBLE -- feature_factory / ic_engine / '
    'regime models consume this symbol. Defaults false (migration 352): every new row, from '
    'any insert path, starts ineligible and is promoted only by '
    'scripts/infrastructure/universe_expansion_promote_compute_eligible.py once '
    'COMPUTE_READY_PREDICATE_SQL holds -- fetch_complete AND non-zero tradeable rows at every '
    'timeframe in the APR compute stack (feature.factory.target_timeframes), never an '
    'any-one-timeframe test. An inactive row always holds false (trigger + CHECK below), so a
re-activated row starts ineligible.';

-- 2. WR-01 ------------------------------------------------------------------------------

UPDATE instrument_tags t
SET valid_to = NOW(),
    evidence = COALESCE(t.evidence, '{}'::jsonb) || jsonb_build_object(
        'expired_by', 'migration 352',
        'expired_reason',
        'measured while outside the compute universe (is_active=true, '
        'compute_eligible=false: Phase 174 D-09 1d-only pilot cohort, D-10 gate FAILED); '
        'TagCalibrator should never have included this symbol in its BH-FDR family '
        '(174-REVIEW.md WR-01)'
    )
FROM instruments i
WHERE i.symbol = t.symbol
  AND i.is_active = true
  AND i.compute_eligible = false
  AND t.source = 'empirical'
  AND t.valid_to IS NULL;

-- 3. WR-05 / WR-07 ----------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
(
    'infra.ic_engine.scratch_headroom_multiplier',
    'float',
    '2.2',
    2.0, NULL,
    '[conventional] Phase 174 review WR-07 (was module constant '
    '_DISK_BACKED_SCRATCH_HEADROOM_MULTIPLIER): required free scratch space as a multiple '
    'of one disk-backed cell''s float32 footprint. The structural floor is 2.0 (X_raw and '
    'X_nd coexist within one cell); the excess is a safety margin for estimate error. Not '
    'an ML learning target.'
),
(
    'infra.ic_engine.scratch_min_free_after_fraction',
    'float',
    '0.15',
    0.0, 0.9,
    '[initial_estimate] Phase 174 review WR-05: fraction of the scratch filesystem''s total '
    'size that must remain free AFTER a disk-backed cell''s scratch files are fully '
    'written. The scratch dir (/var/tmp) shares its filesystem with the TimescaleDB volume, '
    'which keeps writing WAL and results during the run; memmap files are sparse, so space '
    'is consumed as rows land, not at the check. Without a reserve the check admits a cell '
    'that leaves the database no room -- the shape of the 2026-08-13 disk-full incident. '
    'Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
('infra.ic_engine.scratch_headroom_multiplier', '2.2', 1),
('infra.ic_engine.scratch_min_free_after_fraction', '0.15', 1)
ON CONFLICT (config_key) DO NOTHING;

COMMIT;
