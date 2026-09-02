-- 320: add 'construction' to concept_registry's domain vocabulary.
-- Genesis for the personal-scale edge determination program's verdict registry
-- (docs/plans/2026-09-02-personal-scale-edge-determination-plan.md, Governance):
-- construction falsification verdicts get domain='construction' rows at verdict
-- time. First row: range_pct_fast_xs_ls_h5, DEAD 2026-09-02.
-- Not a compressed hypertable; no VACUUM step applies.

ALTER TABLE concept_registry DROP CONSTRAINT concept_registry_domain_check;
ALTER TABLE concept_registry ADD CONSTRAINT concept_registry_domain_check
    CHECK (domain = ANY (ARRAY['feature'::text, 'ensemble_strategy'::text, 'construction'::text]));

INSERT INTO concept_registry (domain, name, description, status, enabled, metadata)
VALUES (
  'construction',
  'range_pct_fast_xs_ls_h5',
  'Falsified DEAD 2026-09-02 by the pre-registered IS run (scripts/analysis/range_pct_fast_xs_ls_h5_falsification.py, commit 0c9a344dd). 931 rebalances 2007-2025: shuffled-null p=0.0010 (cross-sectional signal real), but OLS of per-rebalance gross LS on the EW-universe mean gives beta +1.14, R2 0.75 (Phase 148 failure mode). Neutralized intercept +4.9bp/rebalance turns net-negative at ALL 9 spread x borrow combos under personal costs (measured one-way turnover 0.45/rebalance; commissions 2.8-3.2bp/side at 100k equity quintile breadth), and net-at-anchor is negative in 2/3 subperiods. Verdict: a market-beta tilt, not a personal-scale market-neutral edge. Per the pre-registration, no successor is auto-promoted.',
  'deprecated',
  false,
  jsonb_build_object(
    'verdict', 'DEAD',
    'run_date', '2026-09-02',
    'script', 'scripts/analysis/range_pct_fast_xs_ls_h5_falsification.py',
    'commit', '0c9a344dd',
    'rebalances', 931,
    'shuffled_null_p', 0.0010,
    'gross_mean_bp_per_rebalance', 22.5,
    'gross_ci_bp', to_jsonb(ARRAY[9.2, 35.1]),
    'beta', 1.1368,
    'r2', 0.747,
    'intercept_bp_per_rebalance', 4.87,
    'turnover_mean_per_rebalance', 0.451,
    'net_cheapest_corner_ci_bp', to_jsonb(ARRAY[-7.9, 5.8]),
    'subperiod_net_bp', to_jsonb(ARRAY[-9.7, -12.1, 8.7]),
    'symbols_passing_per_symbol_bh_fdr', '52/231'
  )
)
ON CONFLICT (domain, name) DO NOTHING;
