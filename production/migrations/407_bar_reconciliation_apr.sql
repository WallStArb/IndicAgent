-- 407: D7 nightly reconciliation audit thresholds (phase 185 plan 23, D-26, todo 462).
--
-- services/bar_reconciliation_audit.py reads every key here; the audit only reports
-- (integrity_monitor, OTel metrics labeled by check, the log) and never fails on a finding,
-- so these thresholds set what counts as a finding, not what the pipeline does. Idempotent.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
    (
        'threshold.bar_reconciliation.close_tolerance_bp',
        'float',
        '15.0',
        0, 1000,
        '[rca_analysis] Close difference in basis points above which two views of one daily close disagree: the daily bar vs the last regular-session 5m close, and Tradier vs IBKR SMART TRADES in D1. Seeded from the measured 2024 auction-print distribution (p99 about 15 bp). Not an ML learning target.'
    ),
    (
        'threshold.bar_reconciliation.venue_close_tolerance_rel',
        'float',
        '0.0005',
        0, 1,
        '[initial_estimate] Relative close difference above which a venue-routed D1 observation disagrees with the SMART observation for the same symbol and date. Not an ML learning target.'
    ),
    (
        'threshold.bar_reconciliation.adjusted_ratio_step_rel',
        'float',
        '0.02',
        0, 1,
        '[initial_estimate] Relative step in the ADJUSTED_LAST / TRADES close ratio between consecutive sessions above which the step needs an explanation (a recorded dividend ex-date or corporate action on that date). Not an ML learning target.'
    ),
    (
        'threshold.bar_reconciliation.unexplained_jump_sigma',
        'float',
        '8.0',
        1, 100,
        '[initial_estimate] Close-to-close log return, in multiples of the symbol''s robust (MAD) return scale, above which a jump with no corporate action and no quarantine flag is an unexplained seam. Not an ML learning target.'
    ),
    (
        'threshold.bar_reconciliation.seam_scale_sessions',
        'int',
        '60',
        10, 1000,
        '[initial_estimate] Daily sessions of closes read per symbol to estimate the robust return scale the seam check divides by. Not an ML learning target.'
    ),
    (
        'threshold.bar_reconciliation.dividend_freshness_sessions',
        'int',
        '3',
        0, 250,
        '[initial_estimate] Sessions the Yahoo dividend coverage end may trail the last completed session before a compute_1d symbol counts as stale (todo 428). Not an ML learning target.'
    ),
    (
        'threshold.bar_reconciliation.lookback_sessions',
        'int',
        '5',
        1, 250,
        '[initial_estimate] Sessions each nightly audit judges for the per-day checks (route disagreement, adjusted vs trades, daily vs intraday, seams, stray sources). Not an ML learning target.'
    ),
    (
        'threshold.bar_reconciliation.volume_tolerance_rel',
        'float',
        '0.005',
        0, 1,
        '[rca_analysis] Relative difference between the IBKR daily volume and the summed regular-session 5m volume above which the two disagree. 185-12 measured over all 1.03M derived sessions: 90.3% exact, p99 relative deficit 0.26% (the official daily volume counts auction prints and odd lots the 5m grid does not carry), so exact equality is not a property of the data. Not an ML learning target.'
    ),
    (
        'threshold.bar_reconciliation.completeness_min_share',
        'float',
        '0.996',
        0, 1,
        '[rca_analysis] Share of expected session slots per (symbol, timeframe, year) that must hold a stored real bar or lie inside an answered request window; below it the cell is a finding (todo 462). Seeded from the 2007-2023 real-15m share of 5m-active slots (99.6%, measured 2026-09-29). Not an ML learning target.'
    ),
    (
        'threshold.bar_reconciliation.completeness_years',
        'int',
        '1',
        1, 30,
        '[initial_estimate] Calendar years (the current one and those before it) the nightly completeness and masked-slot checks cover. One year keeps the nightly read to minutes; a wider one-off is an APR change. Not an ML learning target.'
    ),
    (
        'threshold.bar_reconciliation.nightly_max_age_hours',
        'int',
        '26',
        1, 240,
        '[initial_estimate] Hours since the nightly backfill last finished beyond which the night counts as skipped. Not an ML learning target.'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('threshold.bar_reconciliation.close_tolerance_bp', '15.0', 1),
    ('threshold.bar_reconciliation.venue_close_tolerance_rel', '0.0005', 1),
    ('threshold.bar_reconciliation.adjusted_ratio_step_rel', '0.02', 1),
    ('threshold.bar_reconciliation.unexplained_jump_sigma', '8.0', 1),
    ('threshold.bar_reconciliation.seam_scale_sessions', '60', 1),
    ('threshold.bar_reconciliation.dividend_freshness_sessions', '3', 1),
    ('threshold.bar_reconciliation.lookback_sessions', '5', 1),
    ('threshold.bar_reconciliation.volume_tolerance_rel', '0.005', 1),
    ('threshold.bar_reconciliation.completeness_min_share', '0.996', 1),
    ('threshold.bar_reconciliation.completeness_years', '1', 1),
    ('threshold.bar_reconciliation.nightly_max_age_hours', '26', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'threshold.bar_reconciliation.close_tolerance_bp', 1, '15.0', 'migration_407', 'Initial value [rca_analysis] 2024 p99 about 15 bp'),
    (NOW(), 'threshold.bar_reconciliation.venue_close_tolerance_rel', 1, '0.0005', 'migration_407', 'Initial value [initial_estimate]'),
    (NOW(), 'threshold.bar_reconciliation.adjusted_ratio_step_rel', 1, '0.02', 'migration_407', 'Initial value [initial_estimate]'),
    (NOW(), 'threshold.bar_reconciliation.unexplained_jump_sigma', 1, '8.0', 'migration_407', 'Initial value [initial_estimate]'),
    (NOW(), 'threshold.bar_reconciliation.seam_scale_sessions', 1, '60', 'migration_407', 'Initial value [initial_estimate]'),
    (NOW(), 'threshold.bar_reconciliation.dividend_freshness_sessions', 1, '3', 'migration_407', 'Initial value [initial_estimate]'),
    (NOW(), 'threshold.bar_reconciliation.lookback_sessions', 1, '5', 'migration_407', 'Initial value [initial_estimate]'),
    (NOW(), 'threshold.bar_reconciliation.volume_tolerance_rel', 1, '0.005', 'migration_407', 'Initial value [rca_analysis] 185-12 p99 volume deficit 0.26%'),
    (NOW(), 'threshold.bar_reconciliation.completeness_min_share', 1, '0.996', 'migration_407', 'Initial value [rca_analysis] 2007-2023 real-15m share'),
    (NOW(), 'threshold.bar_reconciliation.completeness_years', 1, '1', 'migration_407', 'Initial value [initial_estimate]'),
    (NOW(), 'threshold.bar_reconciliation.nightly_max_age_hours', 1, '26', 'migration_407', 'Initial value [initial_estimate]')
ON CONFLICT DO NOTHING;

COMMIT;
