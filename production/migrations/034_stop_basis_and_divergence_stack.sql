-- Migration 034: Stop basis + divergence stack schema — Phase 32
--
-- Sections:
--   1. signal_ledger stop classification columns
--   2. signal_ledger fire-time snapshot columns
--   3. signal_ledger chandelier + trailing stop columns
--   4. signal_ledger staleness + shadow tracking columns
--   5. Index on stop_basis for ML segmentation
--
-- All statements are idempotent (ADD COLUMN IF NOT EXISTS).
-- Do NOT use CONCURRENTLY — not supported on hypertables (CLAUDE.md).

-- ============================================================
-- Section 1: Stop classification columns
-- ============================================================

-- stop_basis: which classification tier the stop falls in.
-- "structure_snap" = structural stop within 1.5xATR of ATR fallback
-- "garch_adaptive" = GARCH-scaled ATR or structural stop outside proximity
-- "atr_static"     = plain ATR fallback with no GARCH regime available
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS stop_basis TEXT;

-- stop_structure_type: the structural level used as the stop anchor.
-- "ob_bottom"|"demand_zone"|"sweep_level"|"swing_low"|"swing_high"|
-- "sr_support"|"sr_resistance"|"fvg_low"|"fvg_high"|"atr_fallback"
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS stop_structure_type TEXT;

-- stop_structure_age_bars: bars since the structural level was formed.
-- NULL for level types with no age field (zones, OBs, FVGs).
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS stop_structure_age_bars INTEGER;

-- structural_stop_distance_atr: distance from structural stop to ATR fallback
-- expressed in units of effective_atr. Used for ML stop quality scoring.
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS structural_stop_distance_atr DOUBLE PRECISION;

-- ============================================================
-- Section 2: Fire-time snapshot columns
-- ============================================================

-- hmm_regime_at_fire: HMM regime integer (0=ranging, 1=trending, 2=strong trend)
-- captured at the exact bar the signal fires.
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS hmm_regime_at_fire INTEGER;

-- garch_sigma_at_fire: instantaneous GARCH conditional volatility at fire time.
-- Point-in-time snapshot — different from the rolling regime integer.
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS garch_sigma_at_fire DOUBLE PRECISION;

-- ============================================================
-- Section 3: Chandelier + trailing stop columns
-- ============================================================

-- chandelier_vol_source: which volatility input was used to compute the
-- chandelier exit. "garch_sigma" = GARCH σ used; "atr_14" = ATR×14 used.
-- NULL = chandelier not computed for this signal.
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS chandelier_vol_source TEXT;

-- trailing_stop_price: JSONB array of {ts, price} objects recording the
-- trailing stop path from signal fire to exit.
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS trailing_stop_price JSONB;

-- trailing_stop_tightening_rate: rate at which trailing stop tightens per bar
-- (expressed as fraction of ATR per bar).
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS trailing_stop_tightening_rate DOUBLE PRECISION;

-- ============================================================
-- Section 4: Staleness + shadow tracking columns
-- ============================================================

-- staleness_score: composite staleness metric [0, 1] at time of exit.
-- Higher = more stale. Used for ML staleness predictor training.
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS staleness_score DOUBLE PRECISION;

-- staleness_trigger_reason: which staleness trigger fired first.
-- "bar_count"|"regime_flip"|"structure_break"|"none"
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS staleness_trigger_reason TEXT;

-- shadow_tracking_start_ts: when shadow tracking began for this signal.
-- NULL for live signals (is_shadow=FALSE).
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS shadow_tracking_start_ts TIMESTAMPTZ;

-- shadow_mae: maximum adverse excursion in the shadow (paper) track.
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS shadow_mae DOUBLE PRECISION;

-- shadow_mfe: maximum favorable excursion in the shadow (paper) track.
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS shadow_mfe DOUBLE PRECISION;

-- shadow_outcome: 8-class outcome for the shadow track.
-- Same taxonomy as the live signal outcome column.
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS shadow_outcome TEXT;

-- ============================================================
-- Section 5: Indexes
-- ============================================================

-- Partial index on stop_basis for ML segmentation queries.
-- Only indexes rows where stop_basis is populated (post-migration signals).
CREATE INDEX IF NOT EXISTS idx_signal_ledger_stop_basis
    ON signal_ledger (stop_basis) WHERE stop_basis IS NOT NULL;
