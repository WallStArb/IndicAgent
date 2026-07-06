-- Migration 200: Seed feature.hmm.min_state_occupation and feature.hmm.churn_window APR keys.
--
-- Seeds the Adaptive Parameter Registry entries for LIFECYCLE-00's remaining HMM
-- regime-label validation scope: P2b degenerate-model occupation-fraction gate and
-- P2c hmm_churn rolling-instability feature. Both keys are idempotent:
-- ON CONFLICT (config_key) DO NOTHING.
--
-- Key design notes:
--
--   feature.hmm.min_state_occupation — minimum alpha-pass occupation fraction any
--     HMM state must hold across the smoothed label sequence. Below this floor the
--     model has effectively collapsed onto fewer than n_components effective states
--     (degenerate fit) and its labels must not enter feature_vectors — a degenerate
--     regime label is silently worse than no label at all, since LIFECYCLE-04's
--     downstream regime-shift guard trusts feature_vectors.regime as ground truth.
--     Default 0.05 per docs/plans/2026-06-28-hmm-regime-audit-optimization.md P2b.
--     Not an ML learning target.
--
--   feature.hmm.churn_window — rolling window (bars) over which hmm_churn is
--     computed as the fraction of prior-window bars whose regime label changed
--     from the immediately preceding bar. High churn signals a symbol oscillating
--     across a regime boundary rather than occupying a stable regime, which is a
--     confound the regime-shift guard must be able to see. Default 10 per
--     docs/plans/2026-06-28-hmm-regime-audit-optimization.md P2c. Not an ML
--     learning target.
--
-- Column set matches migration 161 (config_schema has config_key, value_type,
-- default_value, min_value, max_value, description; config_state has config_key,
-- config_value, version).

-- -------------------------------------------------------------------------
-- Section 1: config_schema entries
-- -------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
(
    'feature.hmm.min_state_occupation',
    'float',
    '0.05',
    0.005, 0.30,
    '[initial_estimate] Minimum alpha-pass occupation fraction any HMM state must hold across the smoothed label sequence; below this the model is degenerate and its labels are skipped (P2b). Not an ML learning target.'
),
(
    'feature.hmm.churn_window',
    'int',
    '10',
    3, 100,
    '[initial_estimate] Rolling window (bars) over which hmm_churn is computed as the fraction of prior-window bars where the regime label changed (P2c). Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

-- -------------------------------------------------------------------------
-- Section 2: config_state entries (seed values = defaults above)
-- -------------------------------------------------------------------------

INSERT INTO config_state (config_key, config_value, version) VALUES
('feature.hmm.min_state_occupation', '0.05', 1),
('feature.hmm.churn_window',         '10',   1)
ON CONFLICT (config_key) DO NOTHING;
