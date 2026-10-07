-- 454: the d2-v2 cutover's source admission and review keys (phase 185 plan 185-38 Task 0).
--
-- Tradier is a name's primary 1d source only on evidence. scripts/ops/bars/ops_source_policy.py
-- --admission-sweep measures, per name, the latest current-scale TRADIER and SMART TRADES close on
-- every common session and admits Tradier when at least min_overlap_sessions common sessions exist
-- and at least min_agree_share of them agree within threshold.bar_integrity.fallback_basis_tolerance_bp.
-- A failing name gets an IBKR-primary exception row in bar_source_policy carrying the evidence.
--
-- scripts/ops/bars/ops_cutover_review.py gates the first d2-v2 apply on the per-name dry-run TSV:
-- a name whose removed share, refused-interior share or refused-head share exceeds its key and that
-- has no exception row fails the review. It is a one-off gate (185-42 deletes it); its two
-- cutover keys then get retire: 185-43 entries.
--
-- Numbers 447 to 452 are reserved by other plans; 453 is 185-34's. Idempotent.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
('threshold.bar_integrity.tradier_admission_min_overlap_sessions', 'int', '60', 1, 100000,
 '[initial_estimate] Fewest common sessions (both vendors answered at current scale) on which ops_source_policy.py --admission-sweep admits Tradier as a name''s primary 1d source; fewer (including none) is no evidence and fails. Also the length of the recent window a Tradier-incumbent name is re-tested on. Not an ML learning target.'),
('threshold.bar_integrity.tradier_admission_min_agree_share', 'float', '0.9', 0, 1,
 '[initial_estimate] Smallest share of common sessions whose IBKR/Tradier close ratio is within threshold.bar_integrity.fallback_basis_tolerance_bp for Tradier to be admitted as a name''s primary 1d source (185-36 dry run: 179 of 236 IBKR-only names at or above 0.9). Not an ML learning target.'),
('threshold.bar_integrity.cutover_max_removed_share', 'float', '0.005', 0, 1,
 '[initial_estimate] Largest share of a name''s stored 1d bars the first d2-v2 apply may remove without an exception row (ops_cutover_review.py). Not an ML learning target.'),
('threshold.bar_integrity.cutover_max_refused_share', 'float', '0.005', 0, 1,
 '[initial_estimate] Largest refused-interior share of stored 1d bars, and largest refused share of fallback head dates, a name may carry into the first d2-v2 apply without an exception row (ops_cutover_review.py). Not an ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('threshold.bar_integrity.tradier_admission_min_overlap_sessions', '60', 1),
    ('threshold.bar_integrity.tradier_admission_min_agree_share', '0.9', 1),
    ('threshold.bar_integrity.cutover_max_removed_share', '0.005', 1),
    ('threshold.bar_integrity.cutover_max_refused_share', '0.005', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), config_key, 1, config_value, 'migration_454',
       'Initial value for the d2-v2 cutover admission and review [initial_estimate]'
  FROM config_state
 WHERE config_key IN ('threshold.bar_integrity.tradier_admission_min_overlap_sessions',
                      'threshold.bar_integrity.tradier_admission_min_agree_share',
                      'threshold.bar_integrity.cutover_max_removed_share',
                      'threshold.bar_integrity.cutover_max_refused_share')
   AND NOT EXISTS (SELECT 1 FROM config_history h
                   WHERE h.config_key = config_state.config_key
                     AND h.changed_by = 'migration_454');

COMMIT;
