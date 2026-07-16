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
- **Addendum (2026-07-12): the budget was materially wrong, investigated per the note
  above.** The 143.1-07 corpus-wide re-run (`--workers 4`, not the 12 this estimate
  assumed) measured **~10 symbols/5h**, projecting **~40h total** — roughly 40x this
  entry's 60-minute budget, not the ~3x a worker-count-only explanation (4 vs. 12) would
  predict. `py-spy dump` (5/5 samples) confirmed time is genuinely spent inside
  `_circular_block_bootstrap_ic`'s `rankdata`/`argsort` — i.e. the code is doing exactly
  what this entry designed it to do, not a regression. Root cause of the estimate's own
  error: it summed per-call cost at each stratum's *average* group size, but per-call
  cost scales superlinearly in `n` (empirical exponent ≈1.1-1.15, noted above) and real
  corpus cost is dominated by the heavy right tail of large POOLED cells (this entry's
  own example: the largest observed 5m POOLED cell alone costs 687s) landing
  disproportionately given only 4 (not 12) concurrent workers to spread that tail across.
  **Do not cite the ≈16.5min central estimate or the 60-minute budget as reliable going
  forward** — full detail and the resulting checkpointing/resumability fix in
  `.planning/todos/pending/102-ic-engine-idle-session-timeout-writes-zero-rows.md`.

### E7 — 2026-07-11: Canary integrity gate quantitative rule pre-committed before first exercise (Component D, todo 068, Phase 143.1-02)
- **Observed first:** nothing — `ops_canary_integrity_assert.py` has never been run
  against a real corpus. Migration 223 seeded the 5 canary/control `feature_registry`
  rows the same session this entry is written; no `feature_ic_scores` rows exist for
  them yet (Plan 07's corpus-wide re-run is separately blocked, see todo 099 / E6).
  This entry is written before any result exists, per this project's pre-commitment
  convention for gate-affecting decisions.
- **Changed:** `scripts/ops/alpha/ops_canary_integrity_assert.py` added and wired into
  `scripts/ops/corpus/ops_corpus_pipeline_run.sh` immediately after Step 5 (ic_engine).
  The rule is **expectation-aware and false-halt-aware**, not a literal "any stratum
  clears -> halt" (which would fire on expected BH-FDR noise a meaningful fraction of
  runs — Fable review SHOULD-FIX 6, BH-FDR at alpha=0.05 admits ~5% false discoveries
  by design):
  - **HARD-halt, unconditionally:** any negative-control canary
    (`canary_noise_gaussian`/`canary_noise_uniform`/`canary_constant`/
    `canary_near_constant`) clearing `ic_ci_lower>0 AND passes_fdr` in the **POOLED**
    family (`symbol='POOLED' AND is_pooled=true`) — the only family
    `_ELIGIBILITY_BASE_WHERE` (`services/ensemble_trainer.py`) ever reads, so a POOLED
    clear means a broken pipeline is one config flip from weighting a control feature
    into the live ensemble.
  - **HARD-halt, unconditionally:** the acausal-placebo positive control
    (`canary_acausal_placebo`) NOT clearing that same gate in POOLED — proves the
    pipeline fails to detect a deliberate look-ahead leak, which means it cannot be
    trusted to detect a real one either.
  - **NOT a hard-halt:** a single per-symbol (non-POOLED) negative-control clear.
    Instead, per-symbol negative-control clears are counted and compared against a
    **pre-committed Binomial tail bound**: the smallest `k` such that
    `P(Binomial(n_cells, p=0.05) > k) <= 0.01`, where `n_cells` is the number of
    (canary, symbol) negative-control cells evaluated that run, `p=0.05` matches the
    project's standard BH-FDR alpha (the false-clear rate BH-FDR itself admits by
    design), and `tail_alpha=0.01` bounds the probability this gate hard-fails on
    expected statistical noise alone. Only exceeding `k` hard-fails.
  - **No canary rows for the vintage at all** is also a hard-halt (a silent pass here
    would be worse than a loud failure — it would mean the corpus run had zero canary
    coverage and this gate validated nothing).
- **Both `fdr_alpha` (0.05) and `tail_alpha` (0.01) are CLI-overridable** but these are
  the pre-committed defaults this entry locks in — a future change to either requires
  its own ledger entry, not a silent flag change on a live run.
- **Pre-registered?** Yes — the clean pattern (same shape as E4/E5). No canary
  `feature_ic_scores` result exists yet to have influenced this rule; the
  expectation-aware/false-halt-aware design was decided from first principles (BH-FDR's
  known false-discovery budget) and locked in 143.1-CONTEXT.md/RESEARCH.md before this
  plan's own execution began.

### E8 — 2026-07-11: Vol-normalized POOLED-strata IC target A/B design pre-committed before the full-corpus verdict (Component F, todo 097, Phase 143.1-03)
- **Observed first:** nothing definitive at full-corpus scale — this entry records the A/B
  DESIGN and a bounded diagnostic-sample preview, not the corpus-wide verdict. The
  ensemble trains exclusively on `symbol='POOLED'` strata (`ensemble_trainer.py` lines
  317, 430-431, 469, 540); raw-return IC ranks on POOLED are dominated by whichever
  symbols are running hot on a given bar — a real, previously unmeasured bias against the
  population the ensemble actually trains on.
- **Changed:** added `vol_normalized_return()` (`src/intelligence/statistics/ic_math.py`)
  — `return_x / true_range_pct`, epsilon-guarded matching `_ret_vol_ratio()`'s `eps=1e-10`
  convention — and `_cross_sectional_vol_normalized_target()`
  (`services/ic_engine.py`, co-located with `_compute_cross_sectional_tf`), reachable
  from the exact `X_sub`/`valid_mask`/`returns_scale` arrays that function already
  assembles. `true_range_pct` (already loaded in the existing `chunk_sql` query, raw
  non-z-scored) is the sigma proxy — NOT `atr_z` (already z-scored, unusable as a
  denominator) and NOT a new rolling-window computation (no existing column; RESEARCH.md
  Assumption A1). **Neither function is called from the production hot path** — the
  production return target (`return_fast/mid/slow/extended`) is unchanged in this plan.
  Added `scripts/ops/alpha/ops_vol_normalized_target_ab.py`: a read-only, exit-code-always-0
  diagnostic that recomputes POOLED IC with the vol-normalized target for a bounded sample
  of `(tf, regime)` strata (`--max-regimes-per-tf`, default 2) and reports rank correlation
  + qualifying-feature set-difference against the raw-return baseline already stored in
  `feature_ic_scores`, per `(tf, regime, lookahead_bars)` cell.
- **Locked validation contract (per 143.1-CONTEXT.md, restated here for the record):**
  this is an EXPLICIT A/B, never a silent production-target swap. If vol-normalized
  rankings are materially identical to raw, retire the transform rather than keep it on
  theory alone. **Result-recording location:** the DEFINITIVE full-corpus verdict is
  recorded in Plan 07, after Component E's corpus-wide re-run rebuilds `feature_ic_scores`
  under the corrected pipeline — Plan 07 re-invokes this same script with `--all-regimes`
  and appends the full-corpus numbers as an addendum to THIS entry (not a new entry,
  per this ledger's "same commit as the change" convention extended to a staged
  multi-plan change already locked at design time).
- **Bounded diagnostic-sample preview (run live against the current corpus this session,
  `--tf 1d --max-regimes-per-tf 1`, `tf=1d/high_bear`, NOT the full-corpus verdict — a
  functional smoke-test of the script, not evidence for the retire/keep decision):**
  4 lookahead strata evaluated, median rank correlation 0.4477 (range 0.36-0.65),
  raw-only-qualifying=47, vol-only-qualifying=70, both=29 across the 4 strata. This
  preview is NOT cited as the Component F verdict — one `(tf, regime)` cell out of
  4 tfs x 9 cross-sectional regimes is not a representative sample, and the vol-normalized
  side's "qualifying" flag uses this script's own per-stratum BH-FDR family (deliberately
  simplified vs. production's corpus-level family and bootstrap CI, documented in the
  script's own module docstring) — it is recorded here only to confirm the script runs
  correctly end-to-end against live data before Plan 07 depends on it.
- **Pre-registered?** Yes — the clean pattern (same shape as E4/E5/E7). The A/B design
  (what "qualifying" means on each side, the retire-if-identical decision rule, the
  result-recording location) was locked in 143.1-CONTEXT.md before this plan's execution
  began, before any vol-normalized IC value existed anywhere. The one preview number
  above was run after the design was locked and is explicitly labeled non-authoritative
  in this same entry, not presented as if it were the verdict.

### E9 — 2026-07-11: Sign-symmetric ensemble eligibility redesign, code-level (Component E, todo 094, Phase 143.1-04)
- **Observed first:** a live-DB audit (143.1-CONTEXT.md, resolved before this plan's
  execution) found `alpha_events` 99.99% long-only (11.81M long vs. 1,479 short rows) —
  the eligible `feature_ic_scores` population is 1,527 rows, ZERO at `ic_sign=-1`. Root
  cause: three independent sign-asymmetric gates each unconditionally exclude every
  negative-IC (contrarian) feature by construction, not by measurement: (1) the
  walk-forward fold-pass criterion `(fold_ic_arr > 0)` — a persistently-negative feature's
  folds can never satisfy `>0` regardless of stability; (2) `ensemble_trainer.py`'s
  `_ELIGIBILITY_BASE_WHERE` requiring `ic_ci_lower > 0` — a negative point estimate's CI
  lower bound is always below the estimate itself, so this can never pass for a
  contrarian; (3) `services/ic_engine.py`'s post-run `_run_lifecycle_hook` (landed by
  Phase 143, discovered mid-plan — not in the original CONTEXT.md/RESEARCH.md read range)
  — its `failed = ic_ci_lower <= 0` predicate would silently re-demote every contrarian
  one lifecycle cycle after gates (1)/(2) were fixed, self-reverting the whole change with
  no error anywhere. The E2 mean-variance weighting path also had a locked-but-wrong
  formula (`mean_variance_weights(cov, ic_signs * ic_shrunk, ...)` — signs the INPUT to
  Sigma^-1, not the output; mathematically incorrect once a contrarian is correlated with
  another selected feature — Fable review BLOCKER 3).
- **Changed (143.1-04-PLAN.md, all four gates in one plan):** (1) `services/ic_engine.py`
  — sign-consistent walk-forward criterion (`_sign_consistent_wf_pass_count`, new shared
  helper) in all three fold-pass blocks, UNCONDITIONAL (equivalence-preserving for
  ic_sign=1, no APR flag — measurement stays one canonical corpus for both champion and
  challenger). (2) New APR key `alpha.ensemble.sign_symmetric` (boolean, default false,
  migration 224) — the real champion/challenger behavior switch (`weight_version` alone
  was proven vacuous for this purpose, Fable BLOCKER 2: it does not appear in any
  eligibility/weight-derivation predicate, so two weight_version tags with the flag
  unset would train byte-identical weights). `ensemble_trainer.py`'s
  `_ELIGIBILITY_BASE_WHERE`/`_ELIGIBILITY_WHERE` module constants replaced with an
  `_eligibility_where(sign_symmetric)` builder: flag off is byte-identical to the old
  predicate string (tested); flag on adds `(ic_sign=-1 AND ic_ci_upper<0)`. (3)
  `feature_selector.py`'s `compute_quality_weight` made sign-aware:
  `(ic_sign * nearest_ci_bound) * max(sharpe_floor, ic_sign * ic_sharpe)` — reduces
  byte-for-byte to the old formula for ic_sign=1, preserves positive-magnitude weight on
  the negative side via sign framing (not naive `abs()`, which would misapply the
  sharpe_floor comparison and up-weight decay-signature rows). (4) E2 sign-path fixed
  per BLOCKER 3: `resolve_stratum_weights` now signs the OUTPUT of
  `mean_variance_weights(cov, ic_shrunk, ...)` (`ic_signs * mv_raw`), never the input —
  `mean_variance_weights()` itself is called with `ic_shrunk` unchanged. (5)
  `_run_lifecycle_hook`'s `failed`/`material`/`worst_cell` predicates made sign-aware
  under the SAME `alpha.ensemble.sign_symmetric` flag (closing gate 3 above) — a
  contrarian only "fails" if its CI on its own side includes zero, or it fails FDR.
  Every flag-gated predicate is byte-identical to its pre-Component-E form when the flag
  is off (equivalence property, unit-tested at every gate). Commits: sign-consistent
  walk-forward (`9c028ac3`), APR flag + eligibility + quality weight (`a74740e0`), E2
  sign-path + docstring cleanup (`e90471f8`), lifecycle hook (`78fedc3b`).
- **NOT yet executed:** this entry records the CODE-LEVEL redesign only. The corpus
  re-run (regenerating `feature_ic_scores` under the sign-consistent walk-forward
  criterion), the flag-ON challenger training run, and the flag-OFF-vs-flag-ON
  shadow-mode validation required before promotion (any change to `alpha.ensemble.
  sign_symmetric`'s default) are Plan 07/08's responsibility per 143.1-04-PLAN.md's own
  scope boundary — this plan's `<threat_model>` and objective are explicit that shadow
  validation is mandatory before promotion since this changes champion scoring behavior
  for what becomes the owner's live trading capital.
- **Pre-registered?** Yes — the clean pattern (same shape as E4/E5/E7/E8). The flag
  design (a real behavior switch, not the vacuous `weight_version`-only approach; the
  equivalence-preserving unconditional walk-forward fix; the three-gate scope including
  the mid-plan-discovered lifecycle hook) was locked via Fable review (BLOCKER 1/2/3,
  MINOR findings) before this plan's own execution began, before any sign-symmetric
  `feature_ic_scores` or `ensemble_weights` row existed under the new criterion.

### E10 — 2026-07-11: Project-owner risk-acceptance decision on the E6 staged-validation gate, disaggregated by capital-relevance (Phase 143.1-07)

- **Observed first:** E6 recorded the bootstrap CI staged-validation gate as NOT CLEARED
  (6/29 SUSPECT vs. a pre-committed `<=2` total / `<=1` per-stratum bound), blocking Plan
  07's corpus-wide re-run per E6's own pre-committed consequence. Before accepting or
  rejecting that block, this entry traces each of the 6 SUSPECT cells to whether it can
  actually reach a capital-allocation decision, rather than treating the gate's aggregate
  total-bound breach as an undifferentiated risk.
- **Verified by code (not assumed):** the two consumers of `feature_ic_scores` that drive
  live capital allocation — `ensemble_trainer.py`'s eligibility query
  (`services/ensemble_trainer.py:119,363,435`) and Phase 143's `ic_engine.py` post-run
  lifecycle hook (`_run_lifecycle_hook`, `services/ic_engine.py:2264-2285`) — both filter
  to the byte-identical predicate: `symbol='POOLED' AND is_pooled=true AND regime !=
  '_pooled'`. No other code path reads `feature_ic_scores` for a promotion, demotion, or
  weight-assignment decision.
- **Disaggregated re-run result** (`ops_ic_null_calibration.py --ci-method bootstrap`,
  same seed=42, reproduced identically to E6's numbers — 29 evaluated, 6 SUSPECT):

  | feature | symbol | tf | regime | se_ratio | matches eligibility predicate? |
  |---|---|---|---|---|---|
  | ret_autocorr_1 | VNQ | 5m | low_bull | 1.889 | No — `is_pooled=false` |
  | month_sin | EFA | 5m | low_bull | 1.210 | No — `is_pooled=false` |
  | ctf_momentum | XHB | 5m | low_bull | 1.235 | No — `is_pooled=false` |
  | range_pct_slow | EWY | 15m | mid_bull | 1.342 | No — `is_pooled=false` |
  | hurst | BIL | 1d | low_bull | 1.704 | No — `is_pooled=false` |
  | **price_vol_corr_slow** | **POOLED** | **1d** | **mid_bull** | **1.461** | **Yes** |

  5 of 6 SUSPECT cells are `is_pooled=false` (per-symbol) rows — mechanically excluded
  from both capital-allocation consumers by the `symbol='POOLED' AND is_pooled=true`
  clause. They inflate the gate's total-bound count but cannot reach a weight or
  lifecycle-status decision. **Exactly one cell, `price_vol_corr_slow`/POOLED/1d/mid_bull,
  matches the eligibility predicate** and is the sole reason this gate's breach has any
  capital-relevant consequence. Standing alone, it satisfies the gate's own per-stratum
  bound (`<=1` for `tf=1d,is_pooled=true`) at the boundary — the total-bound breach (6>2)
  is driven entirely by the 5 diagnostic-only cells.
- **Root cause remains structural, not noise** (per E6's own two negative controls: 5x
  permutation count and 10x block size both failed to clear the gate, ruling out sampling
  noise and under-blocking). `price_vol_corr_slow` fits the same mechanism as the named
  5m cluster: a rolling-window correlation statistic is itself serially autocorrelated by
  construction (adjacent windows overlap), the same property that defeats circular block
  bootstrap variance estimation for `ret_autocorr_1`/`ctf_momentum`.
- **Live-state check on the one relevant cell:** `feature_registry.status` for
  `price_vol_corr_slow` is `active` (global, not tf/regime-scoped — this table has no
  per-tf column). `ensemble_weights` currently has **zero rows** for
  `(price_vol_corr_slow, tf=1d, regime=mid_bull)` under any `weight_version` — this
  feature is not currently contributing weight at this cell, so the concrete risk is a
  **new** admission under a possibly-overconfident CI, not a pre-existing one being
  perpetuated.
- **DECISION (project-owner directed, this session): PROCEED with Plan 07's full
  corpus-wide re-run.** The gate's total-bound was specified without disaggregating
  capital-relevant (`symbol='POOLED', is_pooled=true`) from diagnostic-only
  (`is_pooled=false`) strata; 5/6 of the measured breach is diagnostic-only, and the one
  cell that is capital-relevant is a single, named, bounded exposure that independently
  satisfies its own stratum's tolerance. This is not a blanket "accept unknown risk" —
  it is accepting a specifically identified, mechanically isolated residual after tracing
  it to the exact decision path it could affect.
- **Mitigation (cheap, targeted, does not require new statistical machinery):** after
  Plan 07's re-run, explicitly check whether `price_vol_corr_slow` newly clears
  `ic_ci_lower > 0` at `tf=1d, regime=mid_bull` (i.e., newly appears in
  `ensemble_weights` or newly avoids lifecycle demotion at that cell) where it did not
  before. If so, treat that admission as flagged pending manual scrutiny (e.g.
  cross-check against the still-live `_fisher_z_ci` value at that one cell) before
  trusting it in a live weight, rather than accepting it silently on the strength of a
  CI method already known to be too narrow for this specific cell.
- **Not resolved by this decision:** todo 099's underlying statistical question (a
  proper long-memory/serial-dependence-aware CI method for autocorrelation/momentum/
  rolling-correlation-family features) remains open, now explicitly non-blocking —
  scope narrowed and re-filed. A separate process-improvement todo is filed against the
  gate design itself: a total-bound that pools `is_pooled=true` and `is_pooled=false`
  cells conflates two different risk classes and should be split in any future
  staged-validation gate of this shape.
- **Pre-registered?** No — this is a post-hoc risk-acceptance decision on an
  already-measured gate result, by definition (E6's own text: "accepting a failed
  gate's result is itself a methodology change requiring its own entry"). What IS
  pre-committed here, for any future incident of this shape: the disaggregation method
  (trace each flagged cell to the literal predicate used by every downstream
  capital-allocation consumer, don't reason about the aggregate) and the mitigation
  pattern (name the exact cell, check its concrete outcome post-run, don't leave it
  silent).

## 2026-07-16 — `market_data_ohlcv` tradeable-bars filtering added to three zero-filter regime/counterfactual/OOS-eval reads

**What result was observed before the change?** `services/cross_sectional_regime_model.py`
(the live Phase 144 cross-sectional regime writer, feeding `market_regimes`, which `ic_engine`
stratifies IC on), `services/counterfactual_tracker.py` (feeding `alpha_frames`'
true-range/MFE/MAE/exit-determination, Phase 142B), and `scripts/ops/corpus/ops_oos_holdout_eval.py`
(a live diagnostic reading `m.open` for OOS feature-IC scoring, found via a CI-guard regex
widening mid-implementation — its JOIN-based read was invisible to the guard's first draft,
which only matched `FROM`) all read `market_data_ohlcv` with zero filtering of placeholder bars.
~82% of intraday / ~32% of daily rows in the live corpus are `volume=0` (synthetic-fill or IBKR
flat-carry-forward). Every regime label, every counterfactual PnL/MFE/MAE, and every OOS
feature-IC score computed by these three files, for the entire corpus history to date, was
computed over this contaminated input.

**What changed?** All three files now read from a new `market_data_ohlcv_tradeable` view
(`WHERE volume > 0`, migration 236) instead of the raw table. No other files' filtering changed
— `regime_writer.py`/`forward_return_writer.py`/`backfill_feature_factory.py` already used
`volume > 0` inline and were confirmed correct by the same audit (see
`docs/plans/2026-07-16-market-data-ohlcv-active-bars-boundary-design.md`), not touched.
`services/bar_auditor.py` and `scripts/debug/analysis/debug_batch_agent_memory.py` also read the
raw table via JOIN, found by the same regex-widening pass, but are correctly left unfiltered
(gap-detection auditor that needs the full calendar grid; dead v2.x code respectively) — allow-listed,
not changed.

**What would the change have looked like if decided *before* seeing any data (pre-registered
justification), and honestly, was it?** This is a straightforward bug fix (missing filter, not
a re-derived threshold or a re-fit gate) — the pre-registered justification is simply "readers
must not see calendar-filler bars," a data-quality invariant this project already committed to
elsewhere (`regime_writer.py`, `forward_return_writer.py`) before this fix existed. It was not
decided in response to observing any specific IC/regime result; the first two files were found by
an unrelated scoping pass (todo 035) and confirmed via direct inspection of their SQL, the third
(`ops_oos_holdout_eval.py`) by widening the CI guard's regex mid-implementation — neither found by
noticing an anomalous downstream number. Honestly pre-registered in that sense, though the
underlying gap had existed, undetected, since each file's creation.

**Consumer note:** the in-flight 143.1-07 corpus rebuild already executed
`cross_sectional_regime_model.py` for its current cycle before this fix landed — its regime
labels are pre-fix. This fix applies cleanly starting with the next corpus rebuild; no
retroactive correction of the in-flight run's regime labels was attempted or is possible without
re-running that step. `ops_oos_holdout_eval.py` is a manually-invoked diagnostic (not part of the
automated corpus pipeline), so any future run of it will use the corrected view immediately.
