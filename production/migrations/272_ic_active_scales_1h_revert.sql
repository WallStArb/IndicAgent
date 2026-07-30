-- Migration 272: alpha.ic.active_scales.1h -- revert 1h to all four scales
--
-- Migration 271 excluded 1h's slow/extended scales because they measured 0.000
-- completeness under forward_return_writer.py's same-ET-session completeness gate
-- (7 bars/session ceiling meant 1h's slow(20)/extended(60) lookaheads could never
-- land inside one session). Todo 208 (2026-07-30) found that gate itself was wrong:
-- overnight/weekend gaps are a known, accepted market property (1d never gated on
-- them), and the trade-construction layer that actually holds positions
-- (services/counterfactual_tracker.py, hold_max_bars) is already session-agnostic
-- and bar-indexed. forward_return_writer.py's complete_{scale} now means the same
-- thing at every tf -- the forward bar exists -- with no session-boundary check
-- anywhere. 1h's slow/extended completeness collapse was entirely an artifact of
-- the now-removed gate, not a property of 1h itself: return_slow/return_extended
-- were already ~99.9% non-NULL even under the old gate (only the completeness FLAG
-- was zeroed), so once forward_returns is rebuilt under the corrected definition,
-- 1h's slow/extended will have real, measurable completeness again.
--
-- This migration is the config-only revert path migration 271's own description
-- explicitly named as the mechanism for exactly this scenario ("reversible via a
-- single config change to this key alone (no code, no migration) if that
-- investigation changes what's measurable for 1h") -- but a migration is used here
-- rather than an ad-hoc UPDATE so the change is versioned, recorded in
-- config_history with full provenance, and reproducible across environments.
--
-- Requires forward_returns to be truncated and rebuilt under the corrected
-- (session-gate-removed) forward_return_writer.py before this value is meaningful
-- -- see the corpus pipeline rerun this migration ships alongside. Does NOT touch
-- alpha.ic.lookahead.{tf}.{scale} (migration 269, the bar-count VALUES) -- whether
-- 20/60 remain the right slow/extended bar counts for 1h under the corrected
-- completeness definition is a separate, open tier-count/spacing question (todo
-- 208's Step 3), deliberately not settled by this migration.

BEGIN;

UPDATE config_schema
SET description = '[rca_analysis] JSON array of scale names ic_engine.py attempts '
    'computation for on 1h -- subset of ["fast","mid","slow","extended"]. All four '
    'active (reverted 2026-07-30, migration 272): the earlier slow/extended '
    'exclusion (migration 271) was caused by forward_return_writer.py''s '
    'same-ET-session completeness gate, which has since been removed (todo 208) '
    '-- not a property of 1h itself. Order in the array is not meaningful -- '
    'canonicalized to fast, mid, slow, extended order at load time regardless of '
    'how written here.'
WHERE config_key = 'alpha.ic.active_scales.1h';

UPDATE config_state
SET config_value = '["fast","mid","slow","extended"]',
    version       = version + 1
WHERE config_key = 'alpha.ic.active_scales.1h';

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), 'alpha.ic.active_scales.1h', version, '["fast","mid","slow","extended"]',
    'migration_272',
    'Todo 208: reverted migration 271''s 1h slow/extended exclusion now that its '
    'cause (the same-ET-session completeness gate in forward_return_writer.py) has '
    'been removed. Requires a forward_returns rebuild to take effect.'
FROM config_state WHERE config_key = 'alpha.ic.active_scales.1h'
ON CONFLICT DO NOTHING;

COMMIT;
