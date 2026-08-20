-- Migration 320: alpha.commodity_regime.ts_proxy_threshold (todo 335 follow-up, code review)
--
-- commodity_momentum_ts.build_tiers()'s tiers2 (backwardation/neutral/contango) was
-- reordered ascending by todo 335's fix, but its two bound literals (-0.25 / 0.25)
-- stayed hardcoded -- an architecture violation per CLAUDE.md's migrate-as-you-go
-- mandate, since this same session's diff directly touched these exact lines.
-- tiers1's primary_threshold is already APR-backed (migration 306) and used
-- symmetrically (-primary / +primary); tiers2's 0.25 is the same shape (a single
-- magnitude used as both the negative and positive bound), so one new key covers it.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, description)
VALUES
    ('alpha.commodity_regime.ts_proxy_threshold', 'float', '0.25',
     '[initial_estimate] Unified commodity group ts_proxy (contango/backwardation) '
     'split threshold, used symmetrically as -threshold/+threshold around neutral. '
     'Previously hardcoded in commodity_momentum_ts.build_tiers() (todo 335 code '
     'review, 2026-08-20). Candidate ML target.');

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.commodity_regime.ts_proxy_threshold', '0.25', 1);

COMMIT;
