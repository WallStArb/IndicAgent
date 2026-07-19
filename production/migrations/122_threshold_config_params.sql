-- Migration 122: Register I7 plugin detection thresholds in parameter store.
--
-- Initial seed values match current hard-coded constants exactly (zero behaviour change
-- at rollout). All are marked [initial_estimate] or [conventional] — none are
-- empirically validated per instrument or regime. ML discovery will replace them
-- once sufficient outcome-labelled signals accumulate (target: n >= 100, p < 0.05).
--
-- Provenance convention: see docs/foundation/parameter-store.md#description-field.

-- ── schema entries ──────────────────────────────────────────────────────────

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
    (
        'threshold.trend_following.regime_min',
        'float', '0.5', 0.0, 1.0,
        '[initial_estimate] Min abs(trend_regime) for TrendFollowingPlugin gate. '
        'Not instrument/regime validated. ML learning target.'
    ),
    (
        'threshold.trend_following.confidence_min',
        'float', '0.4', 0.0, 1.0,
        '[initial_estimate] Min trend_confidence for TrendFollowingPlugin gate. '
        'Not outcome-validated. ML learning target.'
    ),
    (
        'threshold.ofi_continuation.min_bars',
        'int', '10', 1, 100,
        '[rca_analysis] Min consecutive directional OFI bars for OFIContinuationPlugin. '
        'Phase 118 starting guess — DB had no rows at calibration time. ML learning target.'
    ),
    (
        'threshold.ofi_continuation.magnitude_floors',
        'json',
        '{"ES": 500, "NQ": 200, "CL": 1000, "GC": 500, "_default": 500}',
        NULL, NULL,
        '[initial_estimate] Per-instrument OFI magnitude floor (p75 estimate) for '
        'OFIContinuationPlugin. upper_ref = 4 * floor (ratio fixed at 4x across all instruments). '
        'ML learning target per instrument.'
    ),
    (
        'threshold.pattern_completion.confidence_min',
        'float', '0.70', 0.0, 1.0,
        '[rca_analysis] Min I5 pattern confidence for PatternCompletionPlugin. '
        'Raised from 0.50 in Phase 118 — not outcome-validated. ML learning target.'
    ),
    (
        'threshold.vwap_reversion.sigma_min',
        'float', '1.5', 0.5, 4.0,
        '[conventional] Min abs(session_vwap_deviation_sigma) for AnchoredVWAPReversionPlugin. '
        'Textbook 1.5-sigma convention — not instrument-validated. ML learning target.'
    ),
    (
        'threshold.vwap_reversion.hurst_max',
        'float', '0.55', 0.3, 0.7,
        '[conventional] Max hurst_exponent for AnchoredVWAPReversionPlugin mean-reversion gate. '
        'Textbook 0.55 threshold — not outcome-validated. ML learning target.'
    )
ON CONFLICT (config_key) DO NOTHING;

-- ── live state entries ───────────────────────────────────────────────────────

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('threshold.trend_following.regime_min',       '0.5',   1),
    ('threshold.trend_following.confidence_min',   '0.4',   1),
    ('threshold.ofi_continuation.min_bars',        '10',    1),
    ('threshold.ofi_continuation.magnitude_floors',
        '{"ES": 500, "NQ": 200, "CL": 1000, "GC": 500, "_default": 500}', 1),
    ('threshold.pattern_completion.confidence_min','0.70',  1),
    ('threshold.vwap_reversion.sigma_min',         '1.5',   1),
    ('threshold.vwap_reversion.hurst_max',         '0.55',  1)
ON CONFLICT (config_key) DO NOTHING;

-- ── seed config_history ──────────────────────────────────────────────────────

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'threshold.trend_following.regime_min',       1, '0.5',   'initial_estimate', 'Migration 128 seed'),
    (NOW(), 'threshold.trend_following.confidence_min',   1, '0.4',   'initial_estimate', 'Migration 128 seed'),
    (NOW(), 'threshold.ofi_continuation.min_bars',        1, '10',    'rca_analysis',     'Phase 118 starting guess; DB had no rows'),
    (NOW(), 'threshold.ofi_continuation.magnitude_floors',1,
        '{"ES": 500, "NQ": 200, "CL": 1000, "GC": 500, "_default": 500}',
        'initial_estimate', 'Migration 128 seed'),
    (NOW(), 'threshold.pattern_completion.confidence_min',1, '0.70',  'rca_analysis',     'Raised from 0.50 in Phase 118'),
    (NOW(), 'threshold.vwap_reversion.sigma_min',         1, '1.5',   'conventional',     'Textbook 1.5-sigma; not instrument-validated'),
    (NOW(), 'threshold.vwap_reversion.hurst_max',         1, '0.55',  'conventional',     'Textbook 0.55; not outcome-validated');
