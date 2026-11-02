-- Migration 557: APR seeds for the pilot gate (todo 584 design D3, item 9).
--
-- The gate (scripts/ops/ops_feature_column_screen.py) catches a defect shape the 564 and 583
-- findings share: a column whose first finite row comes far later than its declared memory
-- (hma_slope_z at 7,560 rows, the HMM on AAPL at 5,470), or that is mostly an exact 0.0 fill. It
-- runs on a pilot chunk at the new pin before the full rerun.
--
--   threshold.pilot_gate.warmup_gap_bars   G2: first finite row index minus the declared memory
--                                          may not exceed this many bars.
--   threshold.pilot_gate.zero_share_max    G3: the exact-0.0 share of finite post-warmup rows
--                                          may not exceed this, for a column outside zero_is_state.
--   infra.pilot_gate.names                 the pilot names (JSON list), chosen to break things.
--
-- Pilot set (30 names, resolved from live data 2026-11-02): SPY and the degenerate-prone ETFs LQD,
-- FXI, UUP, RSP (documented occupation-gate failures, regime_writer todo 168); AAPL, ASML and
-- FAST (no 1d HMM output at K=5, todo 583), MSFT, HON and SCCO (HON and SCCO carry the volume-basis
-- seam: fallback until 2026, sip_rth after), KO, JPM, XOM; five recent listings CRWV, FIG, CHYM,
-- BKV, JBS (fewer bars than any intraday warmup); five names with a current bar hold (bar_hold_current,
-- 45 names; the STATE.md figure of 229 D7-hold names does not reproduce from a table I could find):
-- APLD, ATRO, CPK, CRGY and CTVA (also the Vylor spin-off); the five thinnest names by median 1d
-- dollar volume over the last year among the stage-2 names: GNE, GLIBA, INGN, BOC, CENT; and CSX,
-- which holds a 510-bar pre-2016 IBKR 5m segment. Both tolerances are [initial_estimate]: the
-- first pilot run reports the observed gap and share distributions and the lead recalibrates.
-- Idempotent.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
    (
        'threshold.pilot_gate.warmup_gap_bars',
        'int', '5', 0, 5000,
        '[initial_estimate] Pilot gate G2 (todo 584 D3): the most bars by which a stored column''s first finite row may follow its declared feature_memory_bars before the gate fails. 5 allows an upstream NaN row or two; hma_slope_z (7,560 rows late) and the HMM outputs (5,470) are far beyond it. Not an ML learning target.'
    ),
    (
        'threshold.pilot_gate.zero_share_max',
        'float', '0.25', 0, 1,
        '[initial_estimate] Pilot gate G3 (todo 584 D3): the largest exact-0.0 share of a column''s finite post-warmup rows before the gate fails it for review, for a column outside the kernels'' zero_is_state set. A 0.0 that is a fill (the 474 neutral fills) shows as a large share; a counted event rate does not. Not an ML learning target.'
    ),
    (
        'infra.pilot_gate.names',
        'json', '[]',
        NULL, NULL,
        '[user_preference] The pilot names for the feature-column gate (todo 584 D3): ETFs prone to a degenerate regime fit, large caps, names across the volume-basis seam, recent listings, names with a bar hold, thin names, a spin-off and a name with a pre-2016 IBKR 5m segment. Read by scripts/ops/ops_feature_column_screen.py --pilot. Not an ML learning target.'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('threshold.pilot_gate.warmup_gap_bars', '5', 1),
    ('threshold.pilot_gate.zero_share_max', '0.25', 1),
    (
        'infra.pilot_gate.names',
        '["AAPL","APLD","ASML","ATRO","BKV","BOC","CENT","CHYM","CPK","CRGY","CRWV","CSX","CTVA","FAST","FIG","FXI","GLIBA","GNE","HON","INGN","JBS","JPM","KO","LQD","MSFT","RSP","SCCO","SPY","UUP","XOM"]',
        1
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT now(), s.config_key, 1, s.config_value, 'migration_557',
       'seed: pilot gate tolerances and pilot names (todo 584 D3)'
  FROM config_state s
 WHERE s.config_key IN (
       'threshold.pilot_gate.warmup_gap_bars', 'threshold.pilot_gate.zero_share_max',
       'infra.pilot_gate.names')
   AND NOT EXISTS (
       SELECT 1 FROM config_history h
        WHERE h.config_key = s.config_key AND h.changed_by = 'migration_557'
 );

COMMIT;
