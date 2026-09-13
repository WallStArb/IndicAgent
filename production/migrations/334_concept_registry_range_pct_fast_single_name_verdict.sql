-- 334: verdict row for range_pct_fast_xs_ls_h5_single_name_only, Pre-registration 3 of
-- docs/plans/2026-09-02-personal-scale-edge-determination-plan.md (todo 375). DEAD.
--
-- Locked design (single-name-only universe, 128 of 231 symbols, everything else inherited
-- unchanged from Pre-registration 1) was AGY-reviewed before running per this program's
-- standing practice. AGY raised multiple structural objections (post-hoc subgroup
-- selection / meta-FDR, unrealistic single-stock cost assumptions, sector-clustering
-- invalidating the shuffled null's exchangeability assumption, survivorship bias,
-- under-diversified early legs, an unlocked/unversioned symbol query) plus a specific
-- claim that the pre-registered stability criterion (net > 0 in 3/3 subperiods) fails.
--
-- AGY's specific subperiod numbers (+10.98/-8.26/-2.10bp) were independently verified
-- against the exact locked formula and found WRONG -- true numbers are
-- +17.87/-1.14/+4.87bp/rebalance (subperiod 2, 2013-10-02..2019-11-06). But the
-- qualitative conclusion was directionally correct: subperiod 2 is negative, and the
-- pre-registered PASS rule requires strict positivity in ALL 3 subperiods. Per the
-- pre-registration's own invalidation clause ("no post-hoc loosening of Criterion (c)
-- after the script prints its output"), this is a hard, honest DEAD on criterion (c)
-- alone -- the full bootstrap CI / shuffled-null machinery (criteria a/b) was not run,
-- since all three criteria must pass and (c) already fails under the locked design.
--
-- AGY's other structural objections (meta-FDR alpha adjustment, single-stock cost
-- realism, sector-stratified null, symbol-list versioning) remain valid critiques of
-- this construction TYPE generally and are recorded for any future attempt, but did not
-- need to be resolved to reach this verdict -- criterion (c) fails regardless of them.
-- Not a compressed hypertable; no VACUUM step applies.

INSERT INTO concept_registry (domain, name, description, status, enabled, metadata)
VALUES (
  'construction',
  'range_pct_fast_xs_ls_h5_single_name_only',
  'DEAD 2026-09-13 (Pre-registration 3, todo 375, docs/plans/2026-09-02-personal-scale-edge-determination-plan.md). Successor to the pooled range_pct_fast_xs_ls_h5 DEAD verdict (2026-09-02), restricted to the 128-symbol single-name-equity subset after a diagnostic found the pooled verdicts beta contamination was disproportionately an ETF-subset property. AGY-reviewed before running per program practice; AGY raised valid structural objections (post-hoc subgroup selection without a meta-FDR alpha adjustment, unrealistic sub-1bp spread/borrow assumptions for single stocks, a shuffled null that breaks sector clustering by permuting across sectors with structurally different range regimes, 100% survivorship among the 128 symbols, under-diversified k=6 legs in 2007-2008, an unlocked/unversioned symbol query) and specifically claimed the pre-registered stability criterion (net > 0 in 3/3 subperiods) fails. AGYs specific subperiod numbers were independently verified and found wrong; the qualitative conclusion held under the correct numbers computed directly from the locked _build_phase/_drag formula at anchor cost (1.4bp spread, 0.5bp borrow): subperiod 1 (2007-08-14..2013-09-25) +17.87bp, subperiod 2 (2013-10-02..2019-11-06) -1.14bp, subperiod 3 (2019-11-13..2025-12-23) +4.87bp. Criterion (c) requires strict positivity in all three; subperiod 2 is negative. DEAD on criterion (c) alone, per the pre-registrations own no-post-hoc-loosening clause -- the full bootstrap CI / shuffled-null machinery (criteria a/b) was not run since all three criteria are required and (c) already fails. The earlier diagnostic headline number (10.17bp neutralized intercept, primary phase only) was a preliminary non-load-bearing signal, not survivable rigor -- the excess return is concentrated in the 2007-2013 crisis-era subperiod and does not hold uniformly across the sample.',
  'deprecated',
  false,
  jsonb_build_object(
    'verdict', 'DEAD',
    'run_date', '2026-09-13',
    'script', 'scripts/analysis/range_pct_fast_beta_by_universe_composition.py (diagnostic) + direct verification of pre-registered subperiod formula, no separate falsification script committed since criterion (c) alone was decisive',
    'preregistration', 'Pre-registration 3, docs/plans/2026-09-02-personal-scale-edge-determination-plan.md',
    'universe', 'single_name_equity tag, 128 of 231 symbols',
    'failing_criterion', 'c (stability: net > 0 in 3/3 subperiods)',
    'subperiod_net_bp_at_anchor_cost', to_jsonb(ARRAY[17.87, -1.14, 4.87]),
    'subperiod_windows', to_jsonb(ARRAY['2007-08-14..2013-09-25', '2013-10-02..2019-11-06', '2019-11-13..2025-12-23']),
    'criteria_a_b_computed', false,
    'reason_a_b_not_computed', 'all three PASS criteria required; criterion c already fails under the locked design, so a/b are moot',
    'preliminary_diagnostic_primary_phase_intercept_bp', 10.17,
    'preliminary_diagnostic_note', 'primary-phase-only intercept masked the subperiod instability; not representative once split',
    'agy_review_doc', 'not separately archived -- findings folded into this row and into docs/research/construction-verdict-ledger.md',
    'agy_specific_subperiod_claim_bp', to_jsonb(ARRAY[10.98, -8.26, -2.10]),
    'agy_claim_verification', 'wrong numbers, right qualitative conclusion (criterion c fails)',
    'agy_valid_structural_objections_not_yet_resolved', to_jsonb(ARRAY[
      'meta_fdr_alpha_adjustment_for_post_hoc_subgroup_selection',
      'single_stock_cost_realism_spread_and_borrow',
      'shuffled_null_breaks_sector_clustering_exchangeability',
      'survivorship_bias_128_of_128_active',
      'under_diversified_k6_legs_2007_2008',
      'unlocked_unversioned_symbol_query'
    ]),
    'source_todo', '375',
    'ledger_row', 'docs/research/construction-verdict-ledger.md'
  )
)
ON CONFLICT (domain, name) DO NOTHING;
