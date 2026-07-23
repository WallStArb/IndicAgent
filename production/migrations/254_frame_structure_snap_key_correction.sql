-- Migration 254: correct alpha.frame.structure_snap_proximity_atr's description
--
-- Code review finding WR-01 (166-REVIEW.md): migration 253 seeded this key describing a
-- "snap the ATR-fallback price to a nearby structural level" behavior, but
-- structural_confluence.py's actual 3-tier resolution (confluence -> single-best -> ATR
-- fallback) never implements that step -- the ATR fallback tier always returns the pure
-- scalar seed unconditionally, with no proximity check. Investigation traced the migration's
-- description to a misreading of the archived trade_framer.py's actual semantics: there,
-- structure_snap_proximity_atr never changed a stop price either -- it only classified an
-- ALREADY-COMPUTED structural stop as stop_basis="structure_snap" (a descriptive label) vs
-- "garch_adaptive" when that stop happened to land within this distance of where the ATR
-- fallback would have been. Wiring an actual price-snapping tier into Phase 166's structural
-- candidate would be new, empirically untested trading logic with no data to validate it
-- against yet (Phase 163 not live -- NULL_PENDING_163, 166-01-SUMMARY.md) -- out of scope for
-- a description correction. This key stays reserved for todo 175 (Part 2) to reconsider
-- alongside the SMC/swing/fib/anchored-VWAP source expansion, not implemented here.
--
-- No behavior change: the key was never read by any code path (confirmed via
-- `grep -rn "structure_snap_proximity_atr" src/ services/ tests/`), so correcting its
-- description has zero live effect. Idempotent: guarded by a NOT LIKE check on the corrected
-- prefix so a re-run is a no-op.

BEGIN;

UPDATE config_schema
SET description = '[reserved, unused] Phase 166 structural candidate Part 1: seeded per the '
    'original plan alongside the other 6 structural-confluence thresholds, but no "snap to '
    'structural level" tier was implemented in structural_confluence.py''s 3-tier resolution '
    '(confluence -> single-best -> ATR fallback always returns the pure scalar seed '
    'unconditionally) -- code review finding WR-01 (166-REVIEW.md) traced the original '
    'description to a misreading of the archived trade_framer.py''s actual semantics there '
    '(a post-hoc stop_basis classification label, never a price transformation). Reserved for '
    'todo 175 (Part 2) to reconsider, not currently consumed by any code path. NOT an ML '
    'learning target.'
WHERE config_key = 'alpha.frame.structure_snap_proximity_atr'
  AND description NOT LIKE '[reserved, unused]%';

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT
    NOW(),
    'alpha.frame.structure_snap_proximity_atr',
    (SELECT COALESCE(MAX(version), 0) + 1 FROM config_history WHERE config_key = 'alpha.frame.structure_snap_proximity_atr'),
    config_value,
    'migration-254',
    'description-only correction (WR-01, 166-REVIEW.md): key is seeded but never read by any '
    'code path -- reserved for todo 175, not a behavior change'
FROM config_state
WHERE config_key = 'alpha.frame.structure_snap_proximity_atr'
  AND NOT EXISTS (
      SELECT 1 FROM config_history
      WHERE config_key = 'alpha.frame.structure_snap_proximity_atr'
        AND changed_by = 'migration-254'
  );

COMMIT;
