-- Migration 133: Register MeanReversion dual-gate threshold in parameter store.
--
-- Phase 126 dual-gate diagnosis showed that |trend_regime| < 0.4 (Gate A) and
-- |kalman_price_position| >= 1.0 (Gate B) are mutually exclusive in practice:
-- only 114 of 2,222,468 bars pass both gates (0.005%). Root cause: kalman_price_position
-- is near-zero in ranging regimes (p50 = 2.57e-13 when Gate A passes).
--
-- The trend_regime_max threshold is relaxed from 0.4 to 0.2 here as a diagnostic
-- seed. However, the plugin is parked shadow_only=True pending redesign — the
-- fundamental issue is a gate conflict, not a threshold tuning problem.
-- See mean_reversion.py module docstring for full diagnosis.
--
-- Provenance: [rca_analysis] — relaxed from 0.4 to 0.2 based on Phase 126 SQL probe.
-- ML learning target once shadow data accumulates (n >= 100, p < 0.05).

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES (
    'threshold.mean_reversion.trend_regime_max',
    'float', '0.2', 0.0, 1.0,
    '[rca_analysis] Max abs(trend_regime) for MeanReversionPlugin Gate A. '
    'Relaxed from 0.4 to 0.2 in Phase 126 after dual-gate mutual-exclusion diagnosis '
    '(both_gates_ok/total_bars = 0.005% at threshold=0.4). Plugin parked shadow_only=True; '
    'redesign needed to reconcile Gate A (ranging) vs Gate B (kalman displacement). '
    'ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES (
    'threshold.mean_reversion.trend_regime_max',
    '0.2',
    1
)
ON CONFLICT (config_key) DO UPDATE
    SET config_value = EXCLUDED.config_value,
        version = config_state.version + 1,
        updated_at = NOW();
