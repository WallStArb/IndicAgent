-- Migration 369: alpha.universe.r2k_sample_size APR key (universe expansion, 2026-09-26)
--
-- Sizes the down-cap Russell 2000 draw made by
-- scripts/infrastructure/universe_expansion_holdings_draw.py: a seeded, market-cap-stratified
-- sample from IWM (Russell 2000) holdings, onboarded 1d-only
-- for the research panel's compute_eligible_1d universe.
--
-- A separate key from alpha.universe.target_sample_size (migration 339, stays 0 per Phase 174
-- D-01) and alpha.universe.pilot_sample_size (migration 342, the D-10 pilot). This draw is
-- neither: Phase 174's D-10 gate measured raw pairwise correlation, which shared market beta
-- dominates; the evidence framework (docs/plans/2026-09-24-evidence-framework.md) counts
-- independent bets after removing common factors, which is the breadth small caps add.
--
-- Paired config_schema/config_state INSERT, ON CONFLICT DO NOTHING (migration 339/342 pattern).

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
(
    'alpha.universe.r2k_sample_size',
    'int',
    '100',
    1, 2000,
    '[user_preference] Size of the down-cap Russell 2000 stratified draw '
    '(universe_expansion_holdings_draw.py): cap-decile-stratified sample from IWM (Russell 2000) '
    'holdings, excluding symbols already in instruments. Chosen by the owner 2026-09-26. Changing '
    'it after a draw has been onboarded does not re-draw; a new draw is a new onboarding run. '
    'Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
('alpha.universe.r2k_sample_size', '100', 1)
ON CONFLICT (config_key) DO NOTHING;
