-- Migration 342: alpha.universe.pilot_sample_size APR key (Phase 174, plan 174-15, D-10)
--
-- Registers a SEPARATE APR key from alpha.universe.target_sample_size (migration 339) for
-- sizing D-10's pre-registered pilot gate draw. D-10's decision text specifies roughly 30-50
-- symbols for the pilot cohort -- a small, throwaway-scale draw used only to test whether the
-- down-cap population decorrelates from the existing single-name book before paying the full
-- backfill cost of the real Plan 12 draw.
--
-- Why a SEPARATE key rather than reusing alpha.universe.target_sample_size: D-01 requires
-- target_sample_size to stay 0 (= UNSET) until Plan 11 sets it from a measured ic_engine
-- scale-up result. Overloading one key for both the pilot draw and the full draw would make
-- D-01's crash-loud guard in universe_expansion_stratified_sourcing.py's _async_main()
-- unreachable during the pilot -- the guard checks `target_size <= 0` and fails loud, so if
-- the pilot borrowed that key to size itself, the guard would either block the pilot too (a
-- false blocker) or the pilot would leave a nonzero value behind that silently defeats the
-- guard for whatever runs next. A dedicated key keeps the two draws structurally independent:
-- the pilot script (universe_expansion_pilot_draw.py) reads pilot_sample_size and separately
-- asserts target_sample_size == 0 at start-up, aborting if that invariant does not hold
-- (T-174-60).
--
-- Follows migration 339's paired config_schema/config_state INSERT pattern (both use
-- ON CONFLICT (config_key) DO NOTHING, safe to re-run).

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
(
    'alpha.universe.pilot_sample_size',
    'int',
    '40',
    30, 50,
    '[initial_estimate] Phase 174 D-10: size of the down-cap pre-registered pilot gate draw '
    '(distinct from alpha.universe.target_sample_size, which stays 0/unset per D-01 until '
    'Plan 11 measures the ic_engine scale-up result -- overloading one key for both purposes '
    'would make the D-01 crash-loud guard unreachable during the pilot). D-10''s decision text '
    'specifies roughly 30-50 symbols for this pilot cohort. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
('alpha.universe.pilot_sample_size', '40', 1)
ON CONFLICT (config_key) DO NOTHING;

-- Idempotency: both blocks use ON CONFLICT (config_key) DO NOTHING (migration 339's pattern).
-- Safe to re-run -- zero errors, zero row changes.
