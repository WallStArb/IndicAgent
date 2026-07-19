-- Migration 235: regroup above_wk_vwap out of the calendar feature_registry group (todo 116)
--
-- above_wk_vwap is price-dependent and stateful (reads FeatureCache, see
-- feature_factory.py:21), unlike every other calendar-group member, which is pure
-- timestamp arithmetic (deterministic, stateless, O(1) function of the bar timestamp
-- alone). Regrouped to 'structure', matching its actual computation class: a boolean
-- flag for price position relative to a reference level, the same shape as
-- range_position/bar_close_pos/gap_z/high_52w_dist (all already 'structure').
--
-- Metadata-only: no compute change, no column added/removed.

BEGIN;

UPDATE feature_registry
SET group_name = 'structure'
WHERE feature_name = 'above_wk_vwap';

COMMIT;
