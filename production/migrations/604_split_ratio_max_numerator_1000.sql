-- 604: infra.backfill.split_ratio_max_numerator 50 -> 1000 (todo 646, lead ruling 2026-11-20 UTC).
-- The stage 2 split audit (data/massive_split_audit/2026-11-20-646) measured 140 reverse splits
-- (1-for-55 to 1-for-10000, penny stocks that later died) whose vendor tape steps by the factor and
-- that the cap of 50 refused as not_a_split_ratio. The denominator cap stays 4: raising it admits
-- stock dividends and spin-offs the vendor serves as small forward factors (not split rows).
-- Known limit: the rule reads a factor as p/q within the relative tolerance, and rounding to an
-- integer alone stays inside 0.002 from p = 250 on, so above 250 the ratio rule filters nothing;
-- the vendor tape step, the adjacent-day check and review separate a split from a rescale there.
-- One of the 163 integer-like rows (1-for-10000) stays refused: it is above the schema bound.
BEGIN;

WITH moved AS (
    UPDATE config_state
       SET config_value = '1000', version = version + 1
     WHERE config_key = 'infra.backfill.split_ratio_max_numerator'
       AND config_value <> '1000'
    RETURNING config_key, version, config_value
)
INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT now(), config_key, version, config_value, 'migration_604',
       '[measured] numerator cap 50 to 1000: 140 tape-confirmed reverse splits (1-for-55 to 1-for-10000) refused by the cap in the stage 2 split audit of 2026-11-20 (todo 646)'
FROM moved;

UPDATE config_schema
   SET default_value = '1000',
       version = version + 1,
       description = '[measured 2026-11-20, was initial_estimate 50] Largest numerator of a recognised split ratio p/q (the larger term of the ratio read as a number above 1, so 20 for 1-for-20). A vendor-declared or measured factor is a split ratio only when it or its inverse is p/q within infra.backfill.split_ratio_rel_tol with p and q under their caps; otherwise it is no split row (held as an unclassified rescale, services/bar_hold.py; a review row in the Massive split audit). Raised from 50 to 1000 by migration 604 because 140 tape-confirmed reverse splits up to 1-for-10000 were refused. From p = 250 on the tolerance no longer discriminates (rounding alone stays inside it), so above that the vendor tape step and the adjacent-day check carry the decision. infer_split snap bound stays p, q <= 50. Not an ML learning target.'
 WHERE config_key = 'infra.backfill.split_ratio_max_numerator'
   AND default_value <> '1000';

COMMIT;
