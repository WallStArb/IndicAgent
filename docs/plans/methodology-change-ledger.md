# Methodology Change Ledger

**Status:** STANDING — append-only; maintained forever
**Created:** 2026-07-01
**Purpose:** Track every methodology change made *after seeing results*, so the family-wise
error of pipeline iterations is visible the same way BH-FDR makes feature-level multiplicity
visible.

---

## Why This Exists

BH-FDR controls multiplicity across features tested *within* a pipeline run. Nothing controls
multiplicity across *versions of the pipeline itself*. Each corpus rebuild has followed
methodology fixes made in response to the previous run's results. Each fix was individually
defensible; the sequence is a garden of forking paths at the pipeline level. A single-operator
system has no adversarial reviewer to catch this — this ledger is the structural substitute.

**The rule:** any change to gates, thresholds, fold construction, stratification, embargo,
clustering, or return definitions that is made after observing results from the machinery it
modifies gets an entry here, in the same commit. Entries answer three questions:
1. What result was observed before the change?
2. What changed?
3. What would the change have looked like if decided *before* seeing any data (pre-registered
   justification) — and honestly, was it?

**The consumer:** the OOS boundary is the ultimate control (`alpha.validation.oos_start` —
never touched by any iteration), but the OOS window can only be spent once per major claim.
This ledger tells us how much selection pressure the in-sample machinery has accumulated,
i.e., how skeptical to be when we finally spend it.

**The operational fix that makes this ledger shrink (2026-07-01, Simons-lens review): freeze
the method, automate the cadence.** Most result-driven methodology tweaks happen because a
rebuild/refresh is a manually-triggered event — every run is an occasion to fiddle. Once the
methodology stabilizes (post-Phase-B), ic_engine/ensemble refresh becomes a boring scheduled
job with the method frozen; changes then require a deliberate act that lands here, instead of
a temptation that accompanies every manual run. Staleness is also an error: a model running on
last month's weights is a silent methodology choice too.

---

## Retrospective Entries (reconstructed 2026-07-01)

### E1 — 2026-06-26: IC stratification switched from per-symbol HMM to cross-sectional pooling
- **Observed first:** per-symbol per-regime cells too thin (~1.5K bars at 5m); `ic_sharpe_hac`
  structurally NULL per-symbol per-regime.
- **Changed:** `ic_engine` regime source swapped to `market_regimes` join + POOLED pass
  (commit `74447369`, Phase 140.5 P4). ~58x observation density.
- **Pre-registered?** Partially — sample-size floors were a stated principle before the
  observation, and the fix follows from arithmetic, not from disappointing IC values. Low
  selection-pressure risk. But note: the change was made without first recording what the
  per-symbol-stratified results *were*, which is why todo 026's validation gate is now
  circular (labels feed IC; IC would validate labels; the per-symbol IC rows don't exist).

### E2 — 2026-06-29 → 2026-06-30: IC gate redesign after 5m/15m returned 0 qualifying features
- **Observed first:** Phase 141 gate FAIL — 5m = 0, 15m = 0 qualifying features on the
  2026-06-29 corpus.
- **Changed:** Phase A — WF fold construction, corpus-level BH-FDR, scale-specific embargo,
  direct-linkage clustering; gate replaced (`ic_ci_lower > 0 AND passes_fdr` instead of binary
  `passes_walkforward`). Result on next corpus: 5m = 37, 15m = 28 qualifying features.
- **Pre-registered?** No — this is the highest-selection-pressure entry in the ledger. The
  root-cause analysis (A1) concluded the original gate was a design bug (721 cells had
  `ic_ci_lower > 0` and were being rejected by fold-construction artifacts), which is a
  legitimate defense. But the sequence "gate fails → gate redesigned → gate passes" is exactly
  the pattern this ledger exists to flag. **Implication: the 37/28 qualifying-feature counts
  are gate-conditional in-sample results and carry accumulated selection pressure from this
  iteration. They must not be cited as evidence of edge until confirmed on the untouched OOS
  window (Phase 142A).**

### E3 — 2026-06-29 → 2026-07-01: three corpus rebuilds
- **Observed first / changed:** build 1 (2026-06-29) superseded by feature-factory changes
  (VP/SR removal, 7-feature demote/restore); build 2 (2026-06-30) superseded by Phase A
  methodology fixes; build 3 (2026-07-01) is current.
- **Pre-registered?** Mixed. Feature-set changes (build 1→2) were structural, not
  result-driven. Build 2→3 inherits E2's pressure.

### E4 — 2026-06-26: BIC K-selection (K=3 → K=5)
- **Observed first:** BIC study across SPY/TLT/GLD/EWT.
- **Changed:** `feature.hmm.n_components` 3 → 5; all regime labels re-derived.
- **Pre-registered?** Yes — model-selection criterion chosen before results, unanimous across
  symbols, provenance recorded in APR. This is the clean pattern; entries should look like
  this.

---

## Live Entries (append below; same commit as the change)

<!-- Template:
### E<n> — <date>: <one-line summary>
- **Observed first:** <the result that prompted the change>
- **Changed:** <what, where, commit>
- **Pre-registered?** <yes / partially / no — and the honest justification>
-->

### E5 — 2026-07-09: BH-FDR multiplicity correction added to the ensemble weight_version A/B judgment, before the judgment has ever run
- **Observed first:** nothing — the E1/E2 A/B judgment (`ops_ensemble_weight_compare.py`,
  built 2026-07-04 in Phase 142B.1) has never been executed. `ensemble_weights` still
  holds only `weight_version='v1'` rows. This entry is written before any result exists.
- **Changed:** `ops_ensemble_weight_compare.py`'s D-10 win rule (challenger CI strictly
  above champion CI, walk-forward stable) is applied independently across every (tf,
  regime) stratum in a comparison round (~36 strata: 4 tfs × 9 cross-sectional regime
  labels). Added a per-stratum Fisher-z difference test (`fisher_z_difference_p`,
  `src/intelligence/statistics/ic_math.py`) plus one `multipletests` BH-FDR pass across
  all strata compared in the run (`alpha.ensemble.compare_fdr_alpha`, migration 213,
  seeded 0.05). A stratum must now pass D-10 AND survive BH-FDR to report `WIN`; passing
  D-10 alone reports `WIN-FDR-VETO`, a distinct, visible verdict rather than a silent
  fold into `LOSS`. Resolves measurement-ic-engine.md Open Question 7 (does winner's-curse
  correction apply at ensemble grain) — full reasoning and rejected alternatives (LOO
  shrinkage across variants, cross-strata priors, hierarchical two-level, conditional
  post-selection inference) in
  `docs/research/fable-2026-07-09-ensemble-winners-curse-peer-group.md`. Todo 069.
- **Pre-registered?** Yes — this is the clean pattern (same shape as E4). The correction
  is decided and implemented before the judgment has ever run, specifically so the first
  E1-vs-v1 / E2-vs-v1 verdicts are corrected from the start rather than reported raw and
  retroactively caveated. No result influenced this design; the decision doc's own
  candidate analysis (§4) explicitly rejected the more elaborate alternatives (variant
  shrinkage, hierarchical pooling) as unsupported by current evidence (only 2-3 variants
  exist) rather than reaching for complexity to look more rigorous.

### E6 — 2026-07-11: Fisher-z CI replaced with circular block bootstrap CI (Component A, todo 091, Phase 143.1-01)
- **Observed first:** the 2026-07-09 empirical-null diagnostic (`ops_ic_null_calibration.py`,
  todo 071/L4-2) found `_fisher_z_ci`'s analytic asymptotic CI empirically miscalibrated on
  this corpus: 38% SUSPECT rate (11/29 evaluated cells, `se_ratio > 1.2`), spanning 4/8
  `(tf, is_pooled)` strata — not confined to `1d`/thin-N corners. `_fisher_z_ci` gates
  BH-FDR pass/fail, walk-forward validation, and the EIC-04 hard gate (currently PASS at
  54/1425 = 3.79%, itself calibrated assuming this CI machinery is trustworthy).
- **PRE-COMMITTED PASS THRESHOLD (recorded BEFORE the bootstrap re-run below):** the staged
  gate PASSES iff `<= 2` SUSPECT cells out of the 66-72 evaluated AND no single
  `(tf, is_pooled)` stratum has more than 1 SUSPECT cell (SUSPECT = the diagnostic's existing
  `se_ratio > 1.2` flag, unchanged). This is the numeric bound Plan 07's corpus-wide re-run
  is gated on — it must not be relaxed after seeing the bootstrap's actual SUSPECT count.
- **Changed:** restored `_circular_block_bootstrap_ic` (`src/intelligence/statistics/ic_math.py`,
  removed in commit `c6f5056b`, 2026-06-26) with its pre-ranking bug fixed — inputs are now
  RAW unranked paired observations, re-ranked inside the bootstrap loop every iteration via
  `rankdata`, instead of resampling already-globally-ranked values (the exact defect the
  2026-07-09 diagnostic proved exists). Rewired all 3 `_fisher_z_ci` call sites in
  `services/ic_engine.py` (`_compute_symbol_tf`'s regime block, the daily context-features
  loop, `_compute_cross_sectional_tf` — the one that gates ensemble eligibility) to the
  bootstrap, with a genuine signature change (raw arrays, not point-estimate + N) at each
  site. Migration 222 reactivated the 6 `alpha.ic.bootstrap_*` APR keys (migrations
  161/165/177), dead since the 2026-06-26 removal.
- **Scope boundary (explicit, not an oversight):** `services/ensemble_ic_engine.py`'s EIC-04
  gate CI computation (~line 778) and `scripts/ops/corpus/ops_oos_holdout_eval.py` (~line 213)
  intentionally STAY ON `_fisher_z_ci` this phase — deferred per 143.1-CONTEXT.md resolved
  item 3 / RESEARCH.md Open Question 1. `_fisher_z_ci` itself is not deleted; it remains the
  production CI for those two call sites.
- **Staged-validation result (measured AFTER the threshold above was committed):**
  `ops_ic_null_calibration.py --ci-method bootstrap` on the SAME 66-cell stratified
  sample (29 evaluated, 37 skipped -- identical to the Fisher-z baseline run, confirming
  no sampling drift between the two comparisons): **6/29 (20.7%) SUSPECT at
  `--n-permutations 200`** (matching the original diagnostic's default), down from
  11/29 (37.9%) under Fisher-z -- a real, substantial improvement. Stratum breakdown:
  `tf=5m,is_pooled=false`: 3 SUSPECT; `tf=15m,is_pooled=false`: 1; `tf=1d,is_pooled=false`:
  1; `tf=1d,is_pooled=true`: 1.
  **VERDICT: GATE NOT CLEARED.** 6 > 2 (total bound), and `tf=5m,is_pooled=false` has 3 > 1
  (per-stratum bound). Re-running at `--n-permutations 1000` (5x more null-permutation
  precision) did not clear it either (8/29 SUSPECT, `tf=5m` worsening to 4) -- ruling out
  small-sample noise in the null benchmark as the cause. A follow-up robustness check
  varying `bootstrap_block_size` for the 5m stratum from 78 (APR default, ~1 trading day)
  up to 780 (~10 trading days) produced an IDENTICAL 4/7 SUSPECT count for 5m at every
  block size tested, with `se_ratio` for the flagged cells flat-to-worsening as block size
  grew -- ruling out "block too short to capture autocorrelation" as the cause too. The
  residual is concentrated in autocorrelation/momentum-family features
  (`ret_autocorr_1`/VNQ, `ctf_momentum`/XHB+IBB, `month_sin`/EFA) at `tf=5m` specifically.
  Full investigation captured as `.planning/todos/pending/099-bootstrap-ci-staged-validation-gate-not-cleared-5m-residual.md`.
  **Per this entry's own pre-committed rule: Plan 07's corpus-wide re-run remains BLOCKED**
  pending either (a) resolution of the 5m residual, or (b) an explicit, separately-recorded
  project-owner decision to accept the residual risk and proceed anyway. The corrected
  bootstrap CODE (Tasks 1-2 of Phase 143.1-01) ships regardless -- it is unconditionally
  correct relative to what it replaced (fixes a proven pre-ranking bug, cuts the SUSPECT
  rate nearly in half) even though it does not fully clear this phase's own strict bar.
- **Downstream exposure, explicitly not re-litigated here:** whether EIC-04's prior PASS
  verdict (54/1425 = 3.79%, Phase 142A/143) should be reconsidered now that its upstream CI
  machinery is proven miscalibrated under Fisher-z is deferred to the project owner — this
  entry records the fact, not a re-adjudication of that gate decision (per 143.1-CONTEXT.md's
  explicit deferral and RESEARCH.md's Pitfall 7 framing).
- **Pre-registered?** Yes for the pass threshold (recorded before the bootstrap diagnostic
  was ever run against this corpus — see timestamp ordering in this same commit). The
  decision to replace Fisher-z with a bootstrap at all was made from a diagnostic result
  (the 38% SUSPECT finding), not blind — but the fix itself (re-rank per iteration) is the
  mechanically correct implementation of the method the codebase already committed to
  building (todo 091 was filed, scoped, and locked in CONTEXT.md before this plan's own
  execution began), not a result-chasing redesign of the gate's pass/fail logic.
- **Runtime budget (Task 4, SHOULD-FIX 4, measured 2026-07-11 at the live/unchanged APR
  values — `bootstrap_resamples=2000`, `bootstrap_seed=42`,
  `bootstrap_block_size.{5m,15m,1h,1d}=78/26/10/10`; Task 3's block-size robustness sweep
  was diagnostic-only and never wrote to `config_state`, confirmed by direct query before
  benchmarking, so Task 3's calibration result above applies unchanged at these params —
  no re-run of Task 3 needed):** `_circular_block_bootstrap_ic` cost is driven almost
  entirely by `n` (post-stride valid-observation count), not by `block_size` — cost is
  effectively per-`(symbol-or-POOLED, regime, tf, lookahead)` group, since one call
  vectorizes the CI across all ~150 features in that group simultaneously (`X_raw` shape
  `[n_obs, n_features]`), confirmed by cross-checking `feature_ic_scores` row counts
  against `count(DISTINCT (symbol, regime, lookahead_bars))` (row count = group count ×
  150 features, exactly, at every `(tf, is_pooled)` stratum). Timed
  `_circular_block_bootstrap_ic` directly on synthetic arrays sized to the corpus's actual
  `n_independent` distribution (isolates the bootstrap's own cost from
  `ops_ic_null_calibration.py`'s unrelated multi-table asyncpg fetch, which is NOT
  representative of production — `ic_engine.py` already holds the data in memory when it
  calls the bootstrap): per-call time scales slightly superlinearly in `n` (empirical
  exponent ≈1.1-1.15, consistent with `rankdata`'s O(n log n) cost inside the per-iteration
  loop) — e.g. tf=5m POOLED avg `n≈56,559` → 17.6s/call; tf=5m POOLED max observed
  `n≈1,489,473` (single outlier cell) → 687s/call; tf=5m per-symbol avg `n≈4,170` →
  1.1s/call. Summing per-call time × group count across all 8 `(tf, is_pooled)` strata
  at their AVERAGE group size (6,219 total groups corpus-wide) gives **≈11,875s (≈3.3hr)
  single-worker serial time**; `ic_engine.py` already parallelizes via
  `ProcessPoolExecutor` at `infra.ic_engine.workers=12`, giving **≈990s (≈16.5min)
  parallel wall-clock** under even load. **PRE-COMMITTED ACCEPTABLE RUNTIME BUDGET: 60
  minutes wall-clock** at 12 workers for the bootstrap-CI portion of a corpus-wide
  re-run — roughly 3.6x the ≈16.5min central estimate, sized to absorb load-imbalance risk
  from the heavy right tail of large POOLED cells (the single largest observed 5m POOLED
  cell alone costs 687s = over 11 minutes) landing disproportionately on one worker. This
  budget is additive to `ic_engine.py`'s pre-existing non-CI per-cell cost (fetch/join/
  feature-completeness work), which is unchanged by this component and not
  re-benchmarked here. If a future corpus-wide re-run measures wall-clock materially
  above this budget, that is itself a signal worth investigating (worker starvation,
  DB contention, or an undercounted tail) before accepting the result.
