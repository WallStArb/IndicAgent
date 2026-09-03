-- 328: verdict row for the personal-scale edge program's paper placement of Phase
-- 148's Gate-1-passing construction (todo 367, workstream 0c of
-- docs/plans/2026-09-02-personal-scale-edge-determination-plan.md).
-- KILLED ON PAPER against the 0b personal hurdle. Not a compressed hypertable;
-- no VACUUM step applies.

INSERT INTO concept_registry (domain, name, description, status, enabled, metadata)
VALUES (
  'construction',
  'phase148_alpha_score_directional',
  'Killed on paper 2026-09-02 (todo 367, workstream 0c; scripts/analysis/phase148_personal_hurdle_placement.py). Phase 148 Gate 1 passed (140/640 OOS cells qualify, 21.875%) but the construction fails the personal hurdle on EVERY (tf, scale) cell under the pre-registered worst-case band rule, and -- decisive, band-independent -- Gate 2 realized OOS frame P&L is NEGATIVE gross of personal costs (mean -0.1215 R, Sharpe 0.385, max-dd 9.60 over 33,892 frames / 69 days): a lower cost hurdle cannot rescue a negative gross edge, so 0b''s "wrong trader" insight does not apply to this construction. Placement inputs, all measured: unbiased all-cell mean rank-IC 0.000-0.050 per cell (qualifying-cell means 0.03-0.18 are selection-inflated); sign co-firing 100.0% at 15m/1h/1d (todo 277) -> ONE systematic directional bet per rebalance, bets band 1-2; horizons intraday (rebalance 504-19,656x/yr). Worst-case IC_min 0.024-1.64 per cell. Caveat recorded, not a reopening: the 15m mid/slow/extended and 5m extended cells clear the MOST favorable band by 4.7-11.7x; the swing variable is alpha_score''s unmeasured turnover, and that signal mass belongs to the demeaned-residual thread (workstream 2''s 15m diagnostic, todo 278''s design), which this verdict does not touch.',
  'deprecated',
  false,
  jsonb_build_object(
    'verdict', 'KILLED_ON_PAPER',
    'run_date', '2026-09-02',
    'script', 'scripts/analysis/phase148_personal_hurdle_placement.py',
    'gate1_cells', 640,
    'gate1_qualifying', 140,
    'gate1_qualifying_fraction', 0.21875,
    'ic_all_mean_by_cell', to_jsonb(ARRAY[0.0008, -0.0011, -0.0077, 0.0078, -0.0000, 0.0498, 0.0186, 0.0213]),
    'ic_qual_mean_by_cell', to_jsonb(ARRAY[0.0311, 0.0446, 0.0480, 0.0662, 'nan'::float, 0.1140, 0.1255, 0.1802]),
    'ic_min_best_by_cell', to_jsonb(ARRAY[0.0104, 0.0042, 0.0030, 0.0017, 0.0060, 0.0042, 0.0027, 0.0019]),
    'ic_min_worst_by_cell', to_jsonb(ARRAY[0.2342, 0.0956, 0.0676, 0.0375, 0.1352, 0.0956, 0.0605, 0.0428]),
    'cell_order', to_jsonb(ARRAY['5m_fast','5m_mid','5m_slow','5m_ext','15m_fast','15m_mid','15m_slow','15m_ext']),
    'gate2_mean_pnl_r', -0.1214896346368989,
    'gate2_sharpe', 0.38512018365944,
    'gate2_max_dd_ratio', 9.596266492204732,
    'gate2_n_frames', 33892,
    'gate2_oos_days', 69,
    'cofiring_same_direction', to_jsonb(ARRAY['5m: 99.6%','15m: 100.0%','1h: 100.0%','1d: 100.0%']),
    'todo277_pooled_ic_15m_raw', -0.00129,
    'todo277_pooled_ic_15m_residual', 0.00453,
    'bets_per_rebalance_band', to_jsonb(ARRAY[1.0, 2.0]),
    'turnover_band', to_jsonb(ARRAY[0.08, 0.45]),
    'spread_band_bp', to_jsonb(ARRAY[0.7, 1.4, 2.8]),
    'note', 'Numbers use the corrected 0b live-spread anchor 0.00014 (1.4bp); the 0c screen had a 10x transcription (0.0014) fixed the same day - margins were understated, no verdict flipped.'
  )
)
ON CONFLICT (domain, name) DO NOTHING;
