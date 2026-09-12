-- 333: verdict row for bars_since_high_fast_xs_ls_h5, the personal-scale edge program's
-- decision-gate closing candidate (graveyard-reconsideration item #2, 2026-09-11).
-- Backfills a governance gap: the construction-verdict-ledger and STATE.md already record
-- this DEAD, but no concept_registry row was ever written, unlike the other three
-- construction-domain verdicts (migrations 328-330) -- the program's own governance rule
-- ("construction verdicts get concept_registry rows at verdict time") was not followed here.
--
-- Confidence caveat, recorded honestly rather than silently upgraded: unlike the other three
-- rows, this verdict's core "unconditional full-history spread check" (mean -0.0004/rebalance)
-- and its structurally-motivated successor's sign-consistency check have NO committed,
-- pre-registered falsification script backing them (git history confirms no such script was
-- ever added; a stray /tmp/spy_15m_bars_since.csv is the only trace) -- unlike
-- range_pct_fast_xs_ls_h5_falsification.py, phase148_personal_hurdle_placement.py, and
-- alpha_score_residual_single_security_15m.py, which are all locked-design, committed,
-- reproducible artifacts. The regime-decomposition half of this verdict (the 52-day
-- down_primary_backwardation attribution) IS reproducible -- it is pure SQL analysis over
-- already-persisted feature_ic_scores/market_regimes rows, consistent with 0c's own
-- "no new measurement" convention. Only the spread-check half is ad hoc. Filed as todo 374
-- for remediation (build the missing script, or formally downgrade this row if it fails a
-- proper falsification). Not a compressed hypertable; no VACUUM step applies.

INSERT INTO concept_registry (domain, name, description, status, enabled, metadata)
VALUES (
  'construction',
  'bars_since_high_fast_xs_ls_h5',
  'DEAD 2026-09-11 (graveyard-reconsideration item #2, docs/research/2026-09-11-strategic-plans-features-ensemble-construction.md; personal-scale edge program decision-gate closing candidate). Unconditional full-history cross-sectional spread check: negative gross return (mean -0.0004/rebalance) despite positive pooled regime-averaged IC (0.1118); low beta (0.19, R^2=0.085) rules out beta-contamination as the explanation, unlike range_pct_fast. Regime-gated refinement also fails on decomposition: the cited "0.11 avg IC, 46-symbol support" premise (scripts/analysis/personal_edge_paper_screen.py, H=5) averages 5 FDR-passing feature_ic_scores cells drawn from FOUR structurally different market_regimes.regime_group taxonomies (equity trend/vol, commodity contango/backwardation, rates curve-shape, fx dollar risk) as if one coherent axis. The standout cell (commodity down_primary_backwardation, IC=0.299, p=2e-5, FDR-pass) occurred on only 52 total days across 16 years (2008 crash / 2014-15 oil collapse / 2020 COVID / 2022 bear) -- a handful of macro-shock episodes, not 52 independent bets. Stripping it out, the only broad/robust cells are two equity ones (mid_neutral IC=0.043, high_bear IC=0.040) -- barely above the already-failed unconditional pooled IC. No regime-gate construction survives this decomposition. Structurally-motivated successor (S/R-pivot volume divergence via feature_factory._compute_sr_dist_atr, Fable-reviewed, no look-ahead) also tested, also flat (51-58% sign consistency, below any reasonable significance bar). CONFIDENCE CAVEAT: the spread-check and successor numbers above have no committed falsification script backing them (unlike this program''s other three construction verdicts) -- see metadata.reproducibility and todo 374.',
  'deprecated',
  false,
  jsonb_build_object(
    'verdict', 'DEAD',
    'run_date', '2026-09-11',
    'unconditional_spread_mean_per_rebalance', -0.0004,
    'unconditional_pooled_regime_avg_ic', 0.1118,
    'unconditional_beta', 0.19,
    'unconditional_r2', 0.085,
    'regime_gate_premise_source', 'scripts/analysis/personal_edge_paper_screen.py',
    'regime_gate_premise_avg_ic', 0.11,
    'regime_gate_premise_symbols', '46/187',
    'regime_taxonomies_averaged', to_jsonb(ARRAY['equity_trend_vol','commodity_contango_backwardation','rates_curve_shape','fx_dollar_risk']),
    'standout_cell', jsonb_build_object('regime_group', 'commodity_down_primary_backwardation', 'ic', 0.299, 'p', 2e-5, 'passes_fdr', true, 'n_days', 52, 'n_years_span', 16),
    'robust_cells_excl_standout', jsonb_build_object('equity_mid_neutral_ic', 0.043, 'equity_high_bear_ic', 0.040),
    'successor_construction', 'sr_pivot_volume_divergence',
    'successor_helper', 'feature_factory._compute_sr_dist_atr',
    'successor_sign_consistency_pct', to_jsonb(ARRAY[51, 58]),
    'reproducibility', jsonb_build_object(
      'committed_falsification_script', false,
      'note', 'unconditional spread-check and successor sign-consistency numbers computed ad hoc, no pre-registered/committed script found in git history; regime-decomposition attribution IS reproducible (pure SQL over persisted feature_ic_scores/market_regimes)',
      'remediation_todo', '374'
    ),
    'source_doc', 'docs/research/2026-09-11-strategic-plans-features-ensemble-construction.md',
    'ledger_row', 'docs/research/construction-verdict-ledger.md'
  )
)
ON CONFLICT (domain, name) DO NOTHING;
