# Personal-Scale Edge Determination — Program Plan (pre-registered)

**Author:** Claude (Sonnet 5), interactive session, 2026-09-02.
**Status:** CLOSED. The decision gate's kill criterion (rule 3) fired 2026-09-12; this program's
construction-discovery phase is over, and the record moved to the unified design
(`docs/plans/2026-09-26-unified-research-to-production-design.md`, adopted 2026-09-26, E18).
Condensed 2026-10-31 (todo 568) to status, decision and the numbers a disclosure requires; the
full text stands at commit `1280dc0a4`. Verdict details:
`docs/research/construction-verdict-ledger.md` and the `legacy-*` cards in
`docs/research/summary-cards/`; verdict rows in `concept_registry` (`domain='construction'`).

**Origin:** user directive 2026-09-02 ("we have been drifting aimlessly for weeks"). Gate
structure stayed rigid (null-arm, BH-FDR, pre-registration, OOS); the ruler's constants went
personal-scale and one axis (holding period) was added, all pre-registered here before any
workstream number existed.

## The pre-registered hurdle (what `scripts/research/cost_hurdle.py` cites)

Workstream 0b's constants were committed BEFORE any candidate placement against the output;
changing one after a placement invalidates every placement made with it. They stay module
constants in `cost_hurdle.py`, deliberately not APR keys, because an APR key is meant to be
tuned and these must not be: `SIGMA_TARGET=0.16`, `COMMISSION_PER_SHARE=0.0035` at
`ASSUMED_PRICE=50`, `LIVE_SPREAD_ANCHOR=0.00014` (1.4 bp), `CS_VALIDATION_BAND=(0.5, 3.0)`,
`SPREAD_SENSITIVITY_BAND=(0.5, 1.0, 2.0)`, `UNIVERSE_BREADTHS=(4.5, 8.4)` (0a's measured
range), `LIBRARY_RANKS=(3.0, 10.0)` (0b's sensitivity range). Hurdle math: net_IR =
IC*sqrt(breadth) - drag_annual/sigma, with one_way_cost = spread/2 + commission_frac.

Corwin-Schultz FAILED its pre-registered validation and was declared unusable: 20 live
top-of-book quotes gave a median live spread of 1.4 bp against a median CS/live ratio of
15.7x, far outside the [0.5, 3.0] band; the estimator measures volatility, not bounce, on
this tiny-spread universe. Live levels became the anchor.

0a's library dimensionality (run 2026-09-02): IC-profile effective rank MP-K=7 of 244
features (participation ratio 17.3); range/vol vs momentum cross-family correlation -0.003
(independent); informational rank MP-K=48. Breadth 4.5-8.4 x rank 7 gives 32-59
per-period bets; measured per-cell ICs 0.03-0.055 against a worst-case personal IC_min of
about 0.003-0.004 at H=5-10, so costs were never the binding constraint at personal scale.

## The decision rules (pre-registered 2026-09-02)

1. A construction passes falsification AND clears the hurdle -> formal gate re-run.
2. Measured signal mass clears the hurdle but no construction exists -> exactly ONE new
   construction is designed and pre-registered for that band (fired once, on
   `range_pct_fast`).
3. Nothing clears the correctly-calibrated hurdle -> KILL CRITERION: "this corpus, at
   breadth ~8 and this TF stack (5m to 1d), cannot carry the endgame." Universe expansion
   becomes primary. A final answer, not an invitation to recalibrate.

## Verdicts (details in the ledger and summary cards)

- 0c paper screen (2026-09-02): 208 FDR-passing 1d cells all clear the worst-case personal
  hurdle; 87 with broad support. A 10x spread-anchor transcription bug was caught the same
  day; it was conservative, no verdict flipped.
- Phase 148's Gate-1-passing `alpha_score` construction: KILLED ON PAPER 2026-09-02. Gate 2's
  realized OOS frame P&L was negative gross of any costs (mean -0.1215 R), which no cost
  hurdle can rescue.
- Pre-registration 1, `range_pct_fast_xs_ls_h5` (2026-09-02, corrected 2026-09-13): DEAD.
  Real association (shuffled-null p 0.0010) but a market-beta tilt (beta 1.14, R2 0.75);
  neutralized net failed at all 9 personal-cost combinations. The same 10x anchor bug
  reached this script and sat undetected 11 days; the rerun at the corrected anchor left the
  verdict unchanged.
- Pre-registration 2, `alpha_score_residual_single_security_15m` (2026-09-03): FAIL. Family
  signal real and 19-year-stable (0.00277, null p 0.0020) but 0/231 symbols cleared their
  own per-symbol BY-FDR null, and the point estimate sat at the 0b best-case floor: a
  uniformly dilute common effect, not concentrated per-name alpha (the raw arm was ~3.8x
  stronger).
- Workstream 1 coverage fix (2026-09-03): complete; all 231 active instruments routed to
  regime groups, existing labels frozen byte-identically.
- Graveyard reconsideration (2026-09-11): `bars_since_high_fast_xs_ls_h5` DEAD;
  `cointegrated_pairs_residual` CLOSED (0/6 ETF pairs, then 0/471 same-sector single-name
  pairs); `cross_sectional_relative_value` reuse stays queued with no path.
- Pre-registration 3, `range_pct_fast_xs_ls_h5_single_name_only` (2026-09-13): DEAD on the
  3/3 stability criterion (subperiod nets +17.87 / -1.14 / +4.87 bp at anchor cost).
- Decision gate (2026-09-12, preconditioned on the post-coverage recompute): **rule 3 fired**.
  At gate time 14 constructions had run to a definitive verdict, zero PASS, so future
  marginal findings read against alpha/N_tested of about 0.0036, not 0.05. Consequence:
  universe expansion became the primary research direction (later carried by the unified
  design's data foundation and the 931-name daily universe). Not closed by this verdict: N1
  (structurally inconclusive) and the separate H-A/H-B track (both later FAIL, ledger).
