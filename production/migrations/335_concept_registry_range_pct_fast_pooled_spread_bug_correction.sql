-- 335: corrects migration 329's recorded numbers for range_pct_fast_xs_ls_h5 (the
-- pooled DEAD verdict, 2026-09-02) after discovering scripts/analysis/
-- range_pct_fast_xs_ls_h5_falsification.py's _LIVE_SPREAD_ANCHOR carried a 10x
-- transcription bug (0.0014 = 14bp instead of 0.00014 = 1.4bp) -- the exact same bug
-- personal_edge_paper_screen.py caught and fixed IN ITSELF on 2026-09-02, which never
-- propagated to this sibling script. Found 2026-09-13 only because the user directly
-- challenged the cost assumptions used across this session's work, prompting a
-- decomposition of the cost model that surfaced the mismatched constant.
--
-- 11 days undetected: past an AGY adversarial design review of the pre-registration,
-- the 2026-09-11 graveyard reconsideration pass (which cited this verdict as
-- "confirmed settled"), and two same-day reuses of this file's _build_phase earlier in
-- this same session (range_pct_fast_beta_by_universe_composition.py,
-- range_pct_fast_xs_ls_h5_single_name_falsification's Pre-registration 3 review) --
-- neither of which imported the buggy constant, so neither is affected.
--
-- Source fixed in the same commit as this migration. The ENTIRE original pre-registered
-- falsification was re-run end to end at the corrected anchor (not just the spread
-- terms in isolation) -- full methodology unchanged, same script, same locked design.
--
-- VERDICT DOES NOT CHANGE: still DEAD. Criterion (a) still fails at all 9 cost combos
-- (CI still crosses zero everywhere -- driven by genuine sampling-noise width, not by
-- the cost-driven point estimate). Criterion (c) still fails on the same qualitative
-- shape (subperiods 1 and 2 negative, only 3 positive) -- correcting a 10x cost
-- overstatement made every point estimate more favorable but did not flip the
-- underlying multi-year negative stretch, which is a property of the gross return
-- series itself, not an artifact of the cost model. Gross mean, beta, R2, shuffled-null
-- p, and turnover are UNCHANGED (none of these four depend on the spread constant --
-- this is itself a useful cross-check that only the intended quantities moved).
--
-- Not a compressed hypertable; no VACUUM step applies.

UPDATE concept_registry
SET
  description = description || ' CORRECTED 2026-09-13: the original run used a spread constant with a 10x transcription bug (0.0014=14bp instead of 0.00014=1.4bp, the same bug personal_edge_paper_screen.py had already caught and fixed in itself). Re-ran the full falsification at the corrected anchor -- verdict UNCHANGED (still DEAD): all 9 cost combos still fail criterion (a), stability still fails on the same 2-of-3-negative-subperiods shape. Point estimates shifted meaningfully favorable (cheapest-corner mean moved from roughly -1bp to +1.85bp) but CI width (driven by sampling noise, not cost) kept the lower bound negative either way. Corrected figures in metadata.',
  metadata = metadata || jsonb_build_object(
    'spread_bug_corrected_2026_09_13', true,
    'spread_bug_description', 'original _LIVE_SPREAD_ANCHOR = 0.0014 (14bp), should have been 0.00014 (1.4bp) -- 10x transcription error, same class as the bug personal_edge_paper_screen.py fixed in itself 2026-09-02',
    'spread_bug_found_by', 'user directly challenged cost assumptions 2026-09-13, prompting a cost-model decomposition',
    'original_net_cheapest_corner_ci_bp', to_jsonb(ARRAY[-7.9, 5.8]),
    'corrected_net_cheapest_corner_ci_bp', to_jsonb(ARRAY[-5.02, 8.59]),
    'corrected_net_cheapest_corner_mean_bp', 1.85,
    'original_subperiod_net_bp', to_jsonb(ARRAY[-9.7, -12.1, 8.7]),
    'corrected_subperiod_net_bp', to_jsonb(ARRAY[-3.87, -6.42, 14.16]),
    'unaffected_by_correction', to_jsonb(ARRAY['gross_mean_bp_per_rebalance', 'beta', 'r2', 'shuffled_null_p', 'turnover_mean_per_rebalance']),
    'verdict_change', false,
    'source_fix_commit', 'same commit as this migration'
  )
WHERE domain = 'construction' AND name = 'range_pct_fast_xs_ls_h5';
