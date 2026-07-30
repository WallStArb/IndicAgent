-- Migration 271: alpha.ic.active_scales.{tf} -- per-tf active-scale set
--
-- ic_engine.py's _SCALES was a hardcoded global 4-tuple ("fast","mid","slow",
-- "extended") applied uniformly to every timeframe, even though 1h has zero real
-- observations for slow/extended (0.000 completeness, live-measured 2026-07-30
-- against forward_returns under the current same-ET-session completeness gate --
-- see docs/superpowers/specs/2026-07-30-per-tf-active-scale-set-design.md and
-- todo 208). This key controls WHICH scales ic_engine attempts computation for,
-- per tf -- distinct from alpha.ic.lookahead.{tf}.{scale} (migration 269), which
-- stores the bar-count VALUES and is untouched by this migration.
--
-- 1h excludes slow/extended based on TODAY'S measured completeness, not a
-- prediction about todo 208's still-open investigation into whether the
-- session-boundary gate should exist at all. Reversible via a single config
-- change to this key alone (no code, no migration) if that investigation changes
-- what's measurable for 1h.

BEGIN;

INSERT INTO config_schema (config_key, value_type, description)
VALUES
    ('alpha.ic.active_scales.5m', 'json',
     '[rca_analysis] JSON array of scale names ic_engine.py attempts computation '
     'for on 5m -- subset of ["fast","mid","slow","extended"]. All four active; 5m '
     'has no measured completeness collapse at any tier (see todo 146''s full-corpus '
     'diagnostic). Order in the array is not meaningful -- canonicalized to fast, '
     'mid, slow, extended order at load time regardless of how written here.'),
    ('alpha.ic.active_scales.15m', 'json',
     '[rca_analysis] JSON array of scale names ic_engine.py attempts computation '
     'for on 15m. Same rationale as 5m -- all four active.'),
    ('alpha.ic.active_scales.1h', 'json',
     '[rca_analysis] JSON array of scale names ic_engine.py attempts computation '
     'for on 1h. Excludes slow/extended: live-measured 0.000 completeness under '
     'the current same-ET-session completeness gate (7 bars/session ceiling) -- '
     'see docs/superpowers/specs/2026-07-30-per-tf-active-scale-set-design.md. '
     'NOT a permanent commitment -- reversible via this key alone if todo 208''s '
     'session-gate investigation changes what''s measurable for 1h.'),
    ('alpha.ic.active_scales.1d', 'json',
     '[rca_analysis] JSON array of scale names ic_engine.py attempts computation '
     'for on 1d. Same rationale as 5m -- all four active (1d has no session-'
     'boundary gate at all, per forward_return_writer.py).')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.ic.active_scales.5m', '["fast","mid","slow","extended"]', 1),
    ('alpha.ic.active_scales.15m', '["fast","mid","slow","extended"]', 1),
    ('alpha.ic.active_scales.1h', '["fast","mid"]', 1),
    ('alpha.ic.active_scales.1d', '["fast","mid","slow","extended"]', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'alpha.ic.active_scales.5m', 1, '["fast","mid","slow","extended"]',
     'migration_271', 'Seed per-tf active-scale set (2026-07-30 design) -- 5m unaffected.'),
    (NOW(), 'alpha.ic.active_scales.15m', 1, '["fast","mid","slow","extended"]',
     'migration_271', 'Seed per-tf active-scale set (2026-07-30 design) -- 15m unaffected.'),
    (NOW(), 'alpha.ic.active_scales.1h', 1, '["fast","mid"]',
     'migration_271', 'Seed per-tf active-scale set (2026-07-30 design) -- 1h excludes '
     'slow/extended, 0.000 measured completeness. Reversible via this key alone.'),
    (NOW(), 'alpha.ic.active_scales.1d', 1, '["fast","mid","slow","extended"]',
     'migration_271', 'Seed per-tf active-scale set (2026-07-30 design) -- 1d unaffected.')
ON CONFLICT DO NOTHING;

COMMIT;
