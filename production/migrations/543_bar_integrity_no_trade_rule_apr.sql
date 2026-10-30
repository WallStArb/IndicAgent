-- Migration 543: the no-trade rule of the 1d session_coverage verdict (review of 2bc1e2e9a)
--
-- A session with no bar inside a corroborated vendor window counted as an answered no-trade day with no
-- bound on the run and no check that the name could have gone untraded. On real data multi-week IBKR
-- history holes in liquid names (LVS, AIZ, LGND, PFBC) passed as "no trade". The rule now answers a
-- missing session only when the run of consecutive sessions with no stored bar is short and the median
-- volume of the nearest stored bars either side is thin. The three keys below are read by
-- services/bar_reconciliation_audit.py (_IntegrityParams) and handed to
-- src/intelligence/bars/integrity_checks.py::no_trade_sessions. Values calibrated in
-- .planning/phases/191-unified-raw-bar-table/191-SESSION-COVERAGE-FIX.md. Idempotent.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
    (
        'threshold.bar_integrity.no_trade_run_max_sessions',
        'int', '3', 1, 20,
        '[rca_analysis] Longest run of consecutive sessions with no stored bar that session_coverage_1d may count as answered no-trade days inside a corroborated vendor window. Longer runs stay holes (a vendor history hole, not a quiet spell). 3 is the 90th percentile of the run length of near-no-trade bars (volume at most 100 shares) in the Alpaca SIP era 2016-01-04 onward. Not an ML learning target.'
    ),
    (
        'threshold.bar_integrity.no_trade_neighbor_window_sessions',
        'int', '5', 1, 20,
        '[rca_analysis] How many stored bars either side of a missing run session_coverage_1d takes the median volume over to judge whether the name could have gone untraded. 5 matches the window the calibration used (one trading week). Not an ML learning target.'
    ),
    (
        'threshold.bar_integrity.no_trade_neighbor_median_volume_max_shares',
        'float', '50000', 0, 100000000,
        '[rca_analysis] Largest neighbouring median daily volume, in shares, at which a missing session may count as an answered no-trade day in session_coverage_1d. Above it the name trades every session and a missing bar is a hole. 50000 is the 99th percentile (45,907 shares) of the neighbouring median volume around near-no-trade bars (volume at most 100 shares) in the Alpaca SIP era, rounded up. Not an ML learning target.'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('threshold.bar_integrity.no_trade_run_max_sessions', '3', 1),
    ('threshold.bar_integrity.no_trade_neighbor_window_sessions', '5', 1),
    ('threshold.bar_integrity.no_trade_neighbor_median_volume_max_shares', '50000', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), s.config_key, s.version, s.config_value, 'migration:543',
       'seed (1d session_coverage counted multi-week vendor history holes in liquid names as no-trade days)'
  FROM config_state s
 WHERE s.config_key IN ('threshold.bar_integrity.no_trade_run_max_sessions',
                        'threshold.bar_integrity.no_trade_neighbor_window_sessions',
                        'threshold.bar_integrity.no_trade_neighbor_median_volume_max_shares')
   AND NOT EXISTS (
       SELECT 1 FROM config_history h
        WHERE h.config_key = s.config_key AND h.version = s.version
          AND h.changed_by = 'migration:543'
   );

COMMIT;
