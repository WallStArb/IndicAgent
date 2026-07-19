-- Migration 217: alpha.ensemble.sign_symmetric APR flag — Phase 143.1 Plan 04 (Component E, todo 094)
--
-- Champion/challenger behavior switch for sign-symmetric ensemble eligibility (todo 094).
-- Default false reproduces the pre-Component-E champion byte-for-byte: eligibility
-- (_ELIGIBILITY_BASE_WHERE), compute_quality_weight, the E2 mean-variance sign path, and
-- ic_engine.py's _run_lifecycle_hook demote predicate are all flag-gated sign-aware
-- behavior switches that reduce to their pre-existing long-only-eligible form when this
-- key is false. weight_version remains a data-scoping tag only -- this flag is the real
-- behavior differentiator between Plan 07's mainline champion (flag OFF) and Plan 08's
-- challenger (flag ON); promotion = flipping this default to true after shadow-mode
-- validation clears (docs/plans/SHADOW-REVIEW.md).

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alpha.ensemble.sign_symmetric',
    'bool',
    'false',
    NULL, NULL,
    '[initial_estimate] Champion/challenger behavior switch (todo 094, Component E). '
    'When false, ensemble eligibility/quality-weight/E2-sign-path/lifecycle-demote-hook '
    'reduce byte-for-byte to the pre-Component-E long-only-eligible champion. When true, '
    'contrarian (ic_sign=-1) features with a significant CI on their own side (ic_ci_upper<0) '
    'become eligible for ensemble weighting and are protected from the lifecycle hook''s '
    'demote predicate. Not an ML learning target -- flipped only via explicit promotion '
    'after mandatory shadow-mode validation (Plan 08).'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('alpha.ensemble.sign_symmetric', 'false', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES (
    NOW(), 'alpha.ensemble.sign_symmetric', 1, 'false', 'migration_224',
    'Initial estimate: sign-symmetric ensemble eligibility defaults OFF (pre-Component-E '
    'champion equivalence) pending shadow-mode validation [initial_estimate]'
)
ON CONFLICT DO NOTHING;

COMMIT;
