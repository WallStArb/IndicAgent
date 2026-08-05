-- Migration 290: Named Interaction Primitives -- Phase 151 Plan 05
--
-- Registers and adds columns for the 5 named tier-1 interaction candidates
-- from ROADMAP's consolidated 2026-07-24 roster: todo 066's three
-- cross-timeframe return divergences and todo 104's two event flags. These
-- are the only tier-1 candidates that arrived pre-specified and Fable-
-- reviewed.
--
-- Migration numbering note: the plan's own text names the file
-- "263_named_interaction_primitives.sql" (provisional target as of the
-- plan's 2026-07-24 authoring date). Live inspection at execution time
-- (2026-08-05) shows the sequence has since advanced through 289 (same
-- collision class already documented in migration 255/216/287/288/289's own
-- numbering notes) -- 290 is the verified next-free number, checked against
-- both `ls production/migrations/` and `config_history` (no
-- changed_by='migration_290' row exists) before this file's apply.
--
-- Binding correction (plan objective): ROADMAP's Theory-Motivated Interaction
-- Layer design-rules paragraph says interaction features register with
-- parent_features=[]. That is wrong. Every one of the 8 live tier=1_interaction
-- rows has exactly 2 non-empty parent_features (migration 197), and
-- scripts/ops/alpha/ops_interaction_primitives_pilot.py:132-139 hard-raises
-- ValueError on any other arity. Migration 169's own column comment defines
-- 1_interaction as "deterministic combination of two tier-0 features." Every
-- row below supplies exactly 2 non-empty parent_features.
--
-- No new APR keys in this migration -- todo 066's own note ("No new APR keys
-- -- differences of two atomic per-TF returns, no window") was confirmed
-- correct by its 2026-07-24 Fable review, and the two flags are parameterless.
--
-- Column type: DOUBLE PRECISION for all 5 new columns, matching every other
-- feature_vectors column added since migration 201. ADD COLUMN IF NOT EXISTS
-- with no DEFAULT is metadata-only against the compressed hypertable -- no
-- decompression step required (confirmed via migration 197/206/216/255/266/
-- 267/287/288/289 precedent).
--
-- Nullable design (binding): ret_div_1m_5m/5m_1h/1h_1d are NULL at every
-- timeframe other than the lower timeframe of their pair -- None means "this
-- pair is undefined here," never a fake 0.0 (which would be indistinguishable
-- from "the two timeframes actually agree"). ret_div_1m_5m is additionally
-- NULL wherever 1m OHLCV is absent (~99% of the 5m corpus -- see the column
-- comment below), a deliberate, documented data limitation, not a defect.
-- opex_flag/quad_witching_flag are non-nullable (always computable from
-- bar_ts alone).
--
-- Parent-selection rationale (recorded in SUMMARY): the parents are the
-- same-row columns partial_spearman_ic will control for. ctf_momentum is the
-- only HTF-derived column in the schema, so it is the honest second control
-- for the two well-defined divergence pairs. ret_div_1m_5m's 1m constituent
-- has NO same-row column at any persisted timeframe; its controls are
-- therefore one-sided (ret_lag_1/ret_lag_2, same-tf short-horizon return
-- structure) -- a known measurement caveat, not a complete control. The two
-- flags' parents are exactly the controls
-- docs/research/signal-temporal-atomic-primitives.md lines 202-203 prescribe,
-- restricted to tier-0 columns (migration 169 defines 1_interaction as a
-- combination of two tier-0 features, so quad_witching_flag takes
-- dow_sin/month_sin rather than the tier-1 opex_flag).
--
-- Phase 170 parity (Section 4 below, added retroactively: this plan was
-- written 2026-07-24, before Phase 170 shipped its dual-write cutover
-- 2026-08-04/05): ic_engine.py's _apply_feature_transitions runs a PARITY
-- PRECONDITION on every corpus pass (Phase 170 Plan 06, T-170-17) that
-- hard-stops if any feature_registry row lacks a concept_registry
-- counterpart. Unlike plans 151-01/03/04, this migration's rows are
-- tier='1_interaction' with real parent_features, so a concept_parent edge
-- insert is required too (migration 283's L-8 join table -- a single
-- parent_concept_id FK cannot represent this). Field mapping matches
-- migration 284's feature-domain seed exactly (derived from the
-- feature_registry rows this migration's own Section 3 just inserted, never
-- re-typed literals, so the tables cannot drift).

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. feature_vectors: 5 new columns
-- ---------------------------------------------------------------------------

ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS ret_div_1m_5m DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS ret_div_5m_1h DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS ret_div_1h_1d DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS opex_flag DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS quad_witching_flag DOUBLE PRECISION;

COMMENT ON COLUMN feature_vectors.ret_div_1m_5m IS
    'log(1m close return) - log(own 5m close return): last 1m log return minus own bar log return. NULL at every timeframe other than 5m. Additionally NULL wherever 1m OHLCV is absent -- 1m coverage is 2026-03-23..2026-06-23 versus 5m''s 2006-06-02..2026-07-07, so expect roughly 1 percent non-null coverage. Deliberate, documented data limitation, not a defect. Phase 151.';
COMMENT ON COLUMN feature_vectors.ret_div_5m_1h IS
    'Own 5m bar log return minus the last closed 1h bar''s log return. NULL at every timeframe other than 5m. Phase 151.';
COMMENT ON COLUMN feature_vectors.ret_div_1h_1d IS
    'Own 1h bar log return minus the last closed 1d bar''s log return. NULL at every timeframe other than 1h. Phase 151.';
COMMENT ON COLUMN feature_vectors.opex_flag IS
    '1.0 iff bar_ts falls on the monthly options-expiration Friday (dow==Friday AND week_of_month==3), else 0.0. No market-holiday table (source doc rejects one as nonstationary institutional data). Phase 151.';
COMMENT ON COLUMN feature_vectors.quad_witching_flag IS
    '1.0 iff opex_flag==1.0 AND bar_ts.month % 3 == 0 (quarterly quad-witching), else 0.0. Phase 151.';

-- ---------------------------------------------------------------------------
-- 2. feature_registry: 5 new rows (tier='1_interaction', added_phase='151')
--    Every row supplies exactly 2 non-empty parent_features (binding
--    correction, see header note above).
-- ---------------------------------------------------------------------------

INSERT INTO feature_registry
    (feature_name, group_name, tier, formula_short, normalization, linear_ready,
     requires_htf, status, added_phase, parent_features)
VALUES
('ret_div_1m_5m',      'cross_tf', '1_interaction',
 'last 1m log return - own 5m log return (1m constituent has no same-row column; controls are same-tf short-horizon return proxies)',
 'unbounded_signed', true, true, 'active', '151', ARRAY['ret_lag_1', 'ret_lag_2']),
('ret_div_5m_1h',      'cross_tf', '1_interaction',
 'own 5m log return - last 1h log return',
 'unbounded_signed', true, true, 'active', '151', ARRAY['ret_lag_1', 'ctf_momentum']),
('ret_div_1h_1d',      'cross_tf', '1_interaction',
 'own 1h log return - last 1d log return',
 'unbounded_signed', true, true, 'active', '151', ARRAY['ret_lag_1', 'ctf_momentum']),
('opex_flag',          'calendar', '1_interaction',
 'dow==Friday AND week_of_month==3 (monthly options expiration)',
 'bounded_unsigned', false, false, 'active', '151', ARRAY['dow_sin', 'week_of_month_sin']),
('quad_witching_flag', 'calendar', '1_interaction',
 'opex_flag AND month mod 3 == 0 (quarterly quad-witching)',
 'bounded_unsigned', false, false, 'active', '151', ARRAY['dow_sin', 'month_sin'])
ON CONFLICT (feature_name) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 3. Phase 170 parity: concept_registry/concept_gate/concept_parent mirror
--    for this migration's 5 rows (see header note above).
-- ---------------------------------------------------------------------------

INSERT INTO concept_registry
    (domain, name, description, status, enabled, group_name, is_control, control_expectation,
     added_phase, created_at, metadata)
SELECT
    'feature', fr.feature_name, fr.formula_short, fr.status, (fr.status = 'active'),
    fr.group_name, fr.is_control, fr.control_expectation, fr.added_phase, fr.added_at,
    jsonb_strip_nulls(jsonb_build_object(
        'tier', fr.tier, 'formula_short', fr.formula_short, 'normalization', fr.normalization,
        'linear_ready', fr.linear_ready, 'requires_htf', fr.requires_htf,
        'window_apr_keys', to_jsonb(fr.window_apr_keys), 'source_dims', to_jsonb(fr.source_dims),
        'notes', fr.notes, 'apr_namespace', 'feature.'
    ))
FROM feature_registry fr
WHERE fr.feature_name IN (
    'ret_div_1m_5m', 'ret_div_5m_1h', 'ret_div_1h_1d', 'opex_flag', 'quad_witching_flag'
)
ON CONFLICT (domain, name) DO NOTHING;

INSERT INTO concept_gate
    (concept_id, gate_metric_name, gate_eval_method, min_gate_metric, min_gate_n,
     fdr_required, fdr_alpha)
SELECT cr.concept_id, 'ic_sharpe_hac', 'bootstrap_ci', fr.min_ic_sharpe, fr.min_ic_n,
       fr.fdr_required, fr.fdr_alpha
FROM feature_registry fr
JOIN concept_registry cr ON cr.domain = 'feature' AND cr.name = fr.feature_name
WHERE fr.feature_name IN (
    'ret_div_1m_5m', 'ret_div_5m_1h', 'ret_div_1h_1d', 'opex_flag', 'quad_witching_flag'
)
ON CONFLICT (concept_id) DO NOTHING;

INSERT INTO concept_parent (child_concept_id, parent_concept_id)
SELECT child.concept_id, parent.concept_id
FROM feature_registry fr
CROSS JOIN LATERAL unnest(fr.parent_features) AS pf(parent_name)
JOIN concept_registry child  ON child.domain = 'feature' AND child.name = fr.feature_name
JOIN concept_registry parent ON parent.domain = 'feature' AND parent.name = pf.parent_name
WHERE fr.feature_name IN (
    'ret_div_1m_5m', 'ret_div_5m_1h', 'ret_div_1h_1d', 'opex_flag', 'quad_witching_flag'
)
ON CONFLICT DO NOTHING;

COMMIT;
