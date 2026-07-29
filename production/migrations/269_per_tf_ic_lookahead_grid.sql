-- Migration 269: per-timeframe alpha.ic.lookahead.{tf}.{scale} APR keys
--
-- Replaces the single global alpha.ic.lookahead.{fast,mid,slow,extended} grid
-- (1/5/20/60, identical across all four timeframes) with per-tf values, confirmed
-- by todo 146's full-corpus, stride-corrected IC-vs-horizon diagnostic
-- (docs/research/fable-2026-07-19-lookahead-and-target-calibration-review.md Q1,
-- scripts/ops/alpha/ops_lookahead_horizon_response.py --max-symbols 80):
--
--   5m:  fast=1  mid=6  slow=12 extended=39
--   15m: fast=1  mid=2  slow=5  extended=10
--   1h:  fast=1  mid=2  slow=20 extended=60  (slow/extended UNCHANGED -- todo 146
--        found 1h has no viable slow/extended tier at all, session-bounded
--        completeness collapses to 0% by horizon=6; restructuring the code to
--        actually drop those tiers is deferred to a separate follow-up todo, not
--        done here -- these two values are seeded unchanged so existing code that
--        still reads them keeps working exactly as today, i.e. producing the same
--        near-zero-valid-row cells it already produces)
--   1d:  fast=1  mid=2  slow=5  extended=10  (1d's old extended=60 "near-optimal"
--        finding was a pre-fix flat-CI artifact, withdrawn by todo 146; every 1d
--        horizon >=20 has a stride-corrected CI half-width exceeding the point
--        estimate itself -- indistinguishable from noise)
--
-- Old global alpha.ic.lookahead.{fast,mid,slow,extended} keys are NOT deleted (still
-- read by any not-yet-updated code path / historical config_history provenance) but
-- their descriptions are updated to note supersession.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
    ('alpha.ic.lookahead.5m.fast', 'int', '1', 1, 500, '[rca_analysis] 5m fast-scale lookahead in bars. Confirmed by todo 146''s full-corpus stride-corrected horizon-response diagnostic (2026-07-20). ML learning target: yes.'),
    ('alpha.ic.lookahead.5m.mid', 'int', '6', 1, 500, '[rca_analysis] 5m mid-scale lookahead in bars. Same source as 5m.fast.'),
    ('alpha.ic.lookahead.5m.slow', 'int', '12', 1, 500, '[rca_analysis] 5m slow-scale lookahead in bars. Same source as 5m.fast.'),
    ('alpha.ic.lookahead.5m.extended', 'int', '39', 1, 500, '[rca_analysis] 5m extended-scale lookahead in bars. Same source as 5m.fast.'),
    ('alpha.ic.lookahead.15m.fast', 'int', '1', 1, 500, '[rca_analysis] 15m fast-scale lookahead in bars. Confirmed by todo 146''s full-corpus stride-corrected horizon-response diagnostic (2026-07-20).'),
    ('alpha.ic.lookahead.15m.mid', 'int', '2', 1, 500, '[rca_analysis] 15m mid-scale lookahead in bars. Same source as 15m.fast.'),
    ('alpha.ic.lookahead.15m.slow', 'int', '5', 1, 500, '[rca_analysis] 15m slow-scale lookahead in bars. Same source as 15m.fast.'),
    ('alpha.ic.lookahead.15m.extended', 'int', '10', 1, 500, '[rca_analysis] 15m extended-scale lookahead in bars. Same source as 15m.fast.'),
    ('alpha.ic.lookahead.1h.fast', 'int', '1', 1, 500, '[rca_analysis] 1h fast-scale lookahead in bars. Confirmed by todo 146''s full-corpus stride-corrected horizon-response diagnostic (2026-07-20).'),
    ('alpha.ic.lookahead.1h.mid', 'int', '2', 1, 500, '[rca_analysis] 1h mid-scale lookahead in bars. Same source as 1h.fast.'),
    ('alpha.ic.lookahead.1h.slow', 'int', '20', 1, 500, '[initial_estimate, known-degenerate] UNCHANGED from the old global default. Todo 146 found 1h has no viable slow tier at all -- same-session completeness collapses to 0% well before this horizon. Structurally removing this tier requires touching ic_engine.py''s fixed _SCALES-indexed compute loops; deferred to a separate follow-up todo. This value intentionally left as-is so existing code keeps producing the same near-zero-valid-row cells it already produces today -- not a calibrated number.'),
    ('alpha.ic.lookahead.1h.extended', 'int', '60', 1, 500, '[initial_estimate, known-degenerate] UNCHANGED from the old global default. Same rationale as alpha.ic.lookahead.1h.slow.'),
    ('alpha.ic.lookahead.1d.fast', 'int', '1', 1, 500, '[rca_analysis] 1d fast-scale lookahead in bars. Confirmed by todo 146''s full-corpus stride-corrected horizon-response diagnostic (2026-07-20); supersedes the withdrawn pre-fix flat-CI "extended=60 near-optimal" finding.'),
    ('alpha.ic.lookahead.1d.mid', 'int', '2', 1, 500, '[rca_analysis] 1d mid-scale lookahead in bars. Same source as 1d.fast.'),
    ('alpha.ic.lookahead.1d.slow', 'int', '5', 1, 500, '[rca_analysis] 1d slow-scale lookahead in bars. Same source as 1d.fast.'),
    ('alpha.ic.lookahead.1d.extended', 'int', '10', 1, 500, '[rca_analysis] 1d extended-scale lookahead in bars. Same source as 1d.fast. Every 1d horizon >=20 under the stride-corrected estimator has a CI half-width exceeding its own point estimate -- 60 was never a real optimum, it was a flat-CI artifact.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.ic.lookahead.5m.fast', '1', 1),
    ('alpha.ic.lookahead.5m.mid', '6', 1),
    ('alpha.ic.lookahead.5m.slow', '12', 1),
    ('alpha.ic.lookahead.5m.extended', '39', 1),
    ('alpha.ic.lookahead.15m.fast', '1', 1),
    ('alpha.ic.lookahead.15m.mid', '2', 1),
    ('alpha.ic.lookahead.15m.slow', '5', 1),
    ('alpha.ic.lookahead.15m.extended', '10', 1),
    ('alpha.ic.lookahead.1h.fast', '1', 1),
    ('alpha.ic.lookahead.1h.mid', '2', 1),
    ('alpha.ic.lookahead.1h.slow', '20', 1),
    ('alpha.ic.lookahead.1h.extended', '60', 1),
    ('alpha.ic.lookahead.1d.fast', '1', 1),
    ('alpha.ic.lookahead.1d.mid', '2', 1),
    ('alpha.ic.lookahead.1d.slow', '5', 1),
    ('alpha.ic.lookahead.1d.extended', '10', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'alpha.ic.lookahead.5m.fast', 1, '1', 'migration_269', 'Seed per-tf lookahead grid (todo 146, confirmed 2026-07-20 full-corpus diagnostic).'),
    (NOW(), 'alpha.ic.lookahead.5m.mid', 1, '6', 'migration_269', 'Seed per-tf lookahead grid (todo 146).'),
    (NOW(), 'alpha.ic.lookahead.5m.slow', 1, '12', 'migration_269', 'Seed per-tf lookahead grid (todo 146).'),
    (NOW(), 'alpha.ic.lookahead.5m.extended', 1, '39', 'migration_269', 'Seed per-tf lookahead grid (todo 146).'),
    (NOW(), 'alpha.ic.lookahead.15m.fast', 1, '1', 'migration_269', 'Seed per-tf lookahead grid (todo 146).'),
    (NOW(), 'alpha.ic.lookahead.15m.mid', 1, '2', 'migration_269', 'Seed per-tf lookahead grid (todo 146).'),
    (NOW(), 'alpha.ic.lookahead.15m.slow', 1, '5', 'migration_269', 'Seed per-tf lookahead grid (todo 146).'),
    (NOW(), 'alpha.ic.lookahead.15m.extended', 1, '10', 'migration_269', 'Seed per-tf lookahead grid (todo 146).'),
    (NOW(), 'alpha.ic.lookahead.1h.fast', 1, '1', 'migration_269', 'Seed per-tf lookahead grid (todo 146).'),
    (NOW(), 'alpha.ic.lookahead.1h.mid', 1, '2', 'migration_269', 'Seed per-tf lookahead grid (todo 146).'),
    (NOW(), 'alpha.ic.lookahead.1h.slow', 1, '20', 'migration_269', 'Unchanged placeholder -- 1h slow tier is known-degenerate, structural fix deferred (todo 146).'),
    (NOW(), 'alpha.ic.lookahead.1h.extended', 1, '60', 'migration_269', 'Unchanged placeholder -- 1h extended tier is known-degenerate, structural fix deferred (todo 146).'),
    (NOW(), 'alpha.ic.lookahead.1d.fast', 1, '1', 'migration_269', 'Seed per-tf lookahead grid (todo 146).'),
    (NOW(), 'alpha.ic.lookahead.1d.mid', 1, '2', 'migration_269', 'Seed per-tf lookahead grid (todo 146).'),
    (NOW(), 'alpha.ic.lookahead.1d.slow', 1, '5', 'migration_269', 'Seed per-tf lookahead grid (todo 146).'),
    (NOW(), 'alpha.ic.lookahead.1d.extended', 1, '10', 'migration_269', 'Seed per-tf lookahead grid (todo 146), supersedes withdrawn extended=60 finding.')
ON CONFLICT DO NOTHING;

UPDATE config_schema
SET description = description || ' [SUPERSEDED 2026-07-29 by migration 269''s per-tf alpha.ic.lookahead.{tf}.{scale} keys -- kept for historical config_history provenance, no longer read by ic_engine.py/ensemble_ic_engine.py/forward_return_writer.py after this migration''s code changes land.]'
WHERE config_key IN (
    'alpha.ic.lookahead.fast', 'alpha.ic.lookahead.mid',
    'alpha.ic.lookahead.slow', 'alpha.ic.lookahead.extended'
);

COMMIT;
