-- Migration 297: feature_edge_by_regime / feature_edge_by_symbol views (todo 251)
--
-- No consolidated place existed to answer "which features currently show edge" or "how has a
-- feature's edge trended over corpus runs" -- feature_ic_scores already has both answers built
-- in, it just wasn't queried that way. No new table, no new write path: both views read
-- feature_ic_scores directly and accrue automatically as ic_engine.py reruns.
--
-- Two grains, deliberately not collapsed into one (segment-by-regime principle -- collapsing
-- would hide regime-conditional edge):
--
-- 1. feature_edge_by_regime -- cross-sectional, pooled ACROSS SYMBOLS, per (feature, tf,
--    regime, lookahead_bars). This is the exact population services/ic_engine.py's own
--    promotion/demotion lifecycle hook (_apply_feature_transitions) reads to decide
--    feature_registry status -- filter verified against that function's live query
--    (services/ic_engine.py:4467-4485), not inferred from feature_ic_scores' schema alone:
--    `WHERE symbol = 'POOLED' AND is_pooled = true AND regime != '_pooled'`. symbol='POOLED'
--    is a sentinel (_CROSS_SECTIONAL_SYMBOL) written only by the cross-sectional aggregation
--    path (services/ic_engine.py ~line 3209), which sets regime_scope='cross_sectional'
--    explicitly and regime=<the actual regime label>, never the pooled sentinel -- confirmed
--    by reading that write site directly, not the module's _resolve_regime_scope() helper
--    (which governs a DIFFERENT, per-symbol pooled-across-regime write path and would have
--    given a wrong answer here: is_pooled=True always resolves to regime_scope='pooled' via
--    that helper, never 'cross_sectional' -- the two mechanisms use different code paths).
--
-- 2. feature_edge_by_symbol -- pooled ACROSS REGIME, per (feature, symbol, tf,
--    lookahead_bars) -- the other existing pooling axis. Filter:
--    `WHERE symbol <> 'POOLED' AND is_pooled = true AND regime_scope = 'pooled'`, matching
--    the table's own existing feature_ic_scores_pooled_uq partial unique index
--    (`is_pooled = true AND symbol <> 'POOLED'`) -- verified against both the general
--    per-symbol pooled pass (_compute_one_regime_cell via _resolve_regime_scope(True, ...))
--    and the narrower context-features pooled pass (services/ic_engine.py ~line 2838),
--    both of which write regime_scope='pooled' for a real (non-'POOLED') symbol.
--
-- "Current" vs "history" is ONE concern, not two views: training_window_end is the
-- walk-forward data boundary (not a run timestamp), so both views expose it as a plain
-- column rather than filtering to the latest. Current edge:
--   SELECT * FROM feature_edge_by_regime
--   WHERE training_window_end = (SELECT max(training_window_end) FROM feature_ic_scores);
-- History/trend: omit that filter, ORDER BY feature_name, tf, regime, training_window_end.
--
-- Column selection: every ic_value/ic_sharpe/gate/walk-forward/e-value column that already
-- exists on feature_ic_scores, so the view is a full reporting surface, not a narrowed
-- projection a future question has to work around. partial_ic/partial_ic_p_value/
-- partial_ic_n/passes_partial_fdr are included even though they are only populated for
-- tier=1_interaction features (screened by a separate mechanism,
-- scripts/ops/alpha/ops_interaction_primitives_pilot.py) -- harmless NULLs for every other
-- feature, and gives the interaction-layer screen a home in the same summary surface instead
-- of a third view.
--
-- Supersedes scripts/analysis/ops_primitive_discovery_report.py's unimplemented skeleton
-- (Phase 142.5 Plan 00). Retirement deliberately deferred -- see todo 251 for why.

BEGIN;

CREATE OR REPLACE VIEW feature_edge_by_regime AS
SELECT
    feature_name,
    vector_domain,
    tf,
    regime,
    lookahead_bars,
    training_window_end,
    ic_value,
    ic_sign,
    ic_sharpe,
    ic_sharpe_hac,
    ic_sharpe_n_windows,
    ic_sortino,
    ic_win_rate,
    sign_hit_rate,
    magnitude_conditional_ic,
    ic_ci_lower,
    ic_ci_upper,
    p_value,
    bh_adjusted_p,
    passes_ci_gate,
    passes_fdr,
    wf_fold_count,
    wf_pass_count,
    wf_ic_sharpe,
    passes_walkforward,
    n_independent,
    reliable,
    cluster_id,
    feature_status_at_eval,
    cumulative_e_value,
    ic_shrunk,
    shrinkage_weight,
    partial_ic,
    partial_ic_p_value,
    partial_ic_n,
    passes_partial_fdr,
    regime_label_source,
    computed_at
FROM feature_ic_scores
WHERE symbol = 'POOLED'
  AND is_pooled = true
  AND regime_scope = 'cross_sectional'
  AND regime <> '_pooled';

COMMENT ON VIEW feature_edge_by_regime IS
    'Cross-sectional edge, pooled across symbols, per (feature, tf, regime, lookahead_bars). '
    'Exact population services/ic_engine.py''s promotion/demotion lifecycle hook reads. '
    'Current edge: filter training_window_end = max(training_window_end). '
    'History/trend: omit that filter. Todo 251, migration 297.';

CREATE OR REPLACE VIEW feature_edge_by_symbol AS
SELECT
    feature_name,
    vector_domain,
    symbol,
    tf,
    lookahead_bars,
    training_window_end,
    ic_value,
    ic_sign,
    ic_sharpe,
    ic_sharpe_hac,
    ic_sharpe_n_windows,
    ic_sortino,
    ic_win_rate,
    sign_hit_rate,
    magnitude_conditional_ic,
    ic_ci_lower,
    ic_ci_upper,
    p_value,
    bh_adjusted_p,
    passes_ci_gate,
    passes_fdr,
    wf_fold_count,
    wf_pass_count,
    wf_ic_sharpe,
    passes_walkforward,
    n_independent,
    reliable,
    cluster_id,
    feature_status_at_eval,
    cumulative_e_value,
    ic_shrunk,
    shrinkage_weight,
    partial_ic,
    partial_ic_p_value,
    partial_ic_n,
    passes_partial_fdr,
    regime_label_source,
    computed_at
FROM feature_ic_scores
WHERE symbol <> 'POOLED'
  AND is_pooled = true
  AND regime_scope = 'pooled';

COMMENT ON VIEW feature_edge_by_symbol IS
    'Edge pooled across regime, per (feature, symbol, tf, lookahead_bars) -- the other '
    'existing pooling axis on feature_ic_scores. Current edge: filter training_window_end '
    '= max(training_window_end). History/trend: omit that filter. Todo 251, migration 297.';

COMMIT;
