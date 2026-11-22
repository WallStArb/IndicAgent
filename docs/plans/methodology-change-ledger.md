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
  Full investigation captured as `.planning/todos/completed/099-bootstrap-ci-staged-validation-gate-not-cleared-5m-residual.md`.
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

- **Addendum, 2026-08-02 (todo 230) — POOLED zero-tolerance rule replaced with a
  Binomial tail bound, after the first real corpus run exercised it.** The
  2026-08-02 `ic_engine` pass (`run_complete` 19:19:25 UTC, 2.92M `feature_ic_scores`
  rows) FATAL-halted on 8 POOLED negative-control clears (3 canaries, ~1.1% of 717
  cell-tests — well under BH-FDR's own 5% naive budget). Investigation (not a
  guess-fix, per this project's own convention) traced the root cause before touching
  the gate:
  - Restricting to the 244 non-canary features in the same cells, `15m/high_neutral`
    and `1h/high_bull` show 12-20% of features clearing `ic_ci_lower>0` (mean IC up to
    0.028 at `1h/high_bull`/60-bar lookahead), versus a clean 2-7% baseline in
    `low_bear`/`mid_bull`/`mid_neutral`. This is genuine, regime-conditional signal
    (momentum/trend features working better in high-vol trending regimes), not an
    artifact — `breadth_vol.py`'s regime-label construction was re-verified fully
    causal (expanding-rank, no centered windows), consistent with Phase 141/todo 092's
    prior look-ahead fix holding.
  - FDR correction is corpus-wide, not per-cell (by design, per the ~232x per-cell
    inflation this project already measured and fixed). A correctly-functioning
    BH-FDR procedure's budgeted false discoveries mathematically cluster near
    whatever cells carry the most genuine small p-values — exactly the cells above.
    The 3 canaries riding along there at a measured 1.1% rate (under the 5% budget)
    is expected FDR behavior, not evidence of a broken pipeline.
  - The original rule's "one config flip away from weighting a control feature into
    the live ensemble" justification is also weaker than stated: `ensemble_trainer.py`
    (line ~820) independently requires `feature_status_at_eval = 'active'`, and
    canaries are permanently `status='candidate'` in `feature_registry` — a POOLED
    clear alone does not reach the live ensemble under the current query.
  - **Rule change:** POOLED negative-control clears are now counted and compared
    against their own pre-committed Binomial tail bound — same construction as the
    per-symbol bound, but with a stricter `pooled_tail_alpha=0.001` (vs. per-symbol's
    `0.01`), reflecting that POOLED remains the eligibility-relevant family even
    though it is not the sole gate on ensemble inclusion. Zero-tolerance is
    mathematically incompatible with a corpus-wide BH-FDR procedure operating as
    designed — holding a global-FDR-corrected canary family to a literal zero-false-
    discovery standard means the gate is expected to intermittently FATAL-halt a
    healthy, correctly-functioning corpus. The 10x-stricter factor itself is a
    judgment call, not derived from a selection procedure — same epistemic status as
    the original per-symbol `tail_alpha=0.01` default this entry already carries.
    `--pooled-tail-alpha` is CLI-overridable; `0.001` is the pre-committed default
    this addendum locks in.
  - Implementation: `scripts/ops/alpha/ops_canary_integrity_assert.py`, tests in
    `tests/unit/test_canary_predictors.py` (`TestCanaryIntegrityAssertion`).

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

- **Addendum, 2026-07-19 — definitive full-corpus verdict (`--all-regimes`), against the
  post-143.1-07 corpus (`training_window_end=2025-12-24 05:15:00+00`).** Two script fixes
  landed first, both from an independent Fable 5 review
  (`docs/research/fable-2026-07-19-lookahead-and-target-calibration-review.md` Q3a):
  (1) the vol-normalized side's BH-FDR now pools p-values into ONE family across the
  whole run, matching production's corpus-wide convention (was one family per stratum,
  which inflated `vol_only` relative to `raw_only` as a correction-strength artifact, not
  a signal difference); (2) the aggregate verdict is conditioned on a reliability floor
  (`n_independent >= alpha.ic.min_reliable_n`, reused rather than a new invented
  threshold) — strata below it stay visible in the per-stratum report but are excluded
  from the median/count rollup.

  **Result: 106 (tf, regime, lookahead) strata evaluated, ALL clearing the reliability
  floor. Median rank correlation 0.7173.** Per the locked decision rule, this is
  unambiguously NOT "materially identical to raw" (would need >0.95 with zero
  raw_only/vol_only) — **retain the transform as a live candidate, do not retire it.**
  Qualifying-feature counts (pooled family): raw_only=260, vol_only=4268, both=925 — read
  qualitatively (vol-normalized surfaces many candidates raw doesn't and vice versa), not
  as a precise "16x more real signal" claim; the two sides still differ in what CI method
  backs `passes_fdr` (raw = production's bootstrap CI; vol-normalized = this diagnostic's
  cheaper Fisher-z/BH-FDR only, no CI recompute, per the script's own documented scoping
  simplification) — this is a feature-set discovery scan, not a rate comparable to a
  promotion decision.

  **New finding, not visible in any smaller sample this project has run: divergence is
  regime-conditional, concentrated in `low_bull`, and NOT explained by low N.**
  `low_bull` strata median rank correlation 0.351 (n=12 strata) vs. 0.731 for every other
  regime (n=94 strata) — a 2x gap. Critically, several of the worst `low_bull` cells are
  among the BEST-powered strata in the entire run, ruling out the "noise from small N"
  explanation that accounts for the earlier-observed 1d/extended outliers:

  | tf | regime | lookahead | n_independent | rank_corr |
  |---|---|---|---|---|
  | 1h | mid_bull | 1 | 50,079 | 0.0485 |
  | 15m | low_bull | 5 | 367,448 | 0.1101 |
  | 1h | low_bull | 1 | 81,018 | 0.1726 |
  | 15m | low_bull | 1 | 436,346 | 0.2349 |
  | 5m | low_bull | 20 | 253,384 | 0.2415 |

  Broader regime-family pattern (bear/neutral/bull median rank_corr 0.75/0.80/0.56)
  shows `bull` regimes generally lag, but `low_bull` specifically is the extreme driver.
  Mechanism not investigated here — candidates include `true_range_pct` behaving
  differently as a normalizer in genuinely low-volatility bull conditions (the
  denominator itself may be compressed/noisy exactly when the regime label says
  volatility is low), or a real economic difference in what predicts returns in that
  regime under the two target definitions. **Flagging as a finding requiring its own
  follow-up, not resolving the mechanism in this entry.**

  Full per-stratum table: this session's run output, not persisted to a table (matches
  this script's existing no-persistence design) — reproducible via `python
  scripts/ops/alpha/ops_vol_normalized_target_ab.py --all-regimes` against the same
  vintage.
- **Not yet decided:** whether to (a) proceed with promoting vol-normalized as a shadow
  `weight_version` variant globally, (b) promote it only outside `low_bull`-family
  regimes pending the mechanism investigation, or (c) investigate the `low_bull`
  divergence first before any promotion decision. Project owner's call — this addendum
  records the evidence, not the decision.

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
`docs/plans/archive/2026-07-16-market-data-ohlcv-active-bars-boundary-design.md`), not touched.
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

---

## 2026-07-19 — Bootstrap-CI residual SUSPECT rate (todo 091) closed via standing dependence-length flag, not per-feature block-size tuning (todo 145)

**What result was observed before the change?** Todo 091's 2026-07-19 confirmation run (fresh
143.1-07 corpus, `--ci-method bootstrap`) found the circular block bootstrap fix (143.1-01) cut
the empirical-null SUSPECT rate from 38% (11/29 evaluated cells) to 21% (4/19) — real
improvement, not full resolution. 3 of the 4 residual SUSPECT cells were the same feature,
`ctf_momentum` (XLY/5m, EWJ/5m, QQQ/15m); the fourth was `flight_quality` (VWO/1h). Fable 5's
2026-07-19 review measured the mechanism directly: integrated autocorrelation time vs. each
feature's tf bootstrap block size (`alpha.ic.bootstrap_block_size.{5m,15m,1h,1d}` = 78/26/10/10
bars). `ctf_momentum` runs ~4x its block size consistently across tfs (structural — it's
HTF-derived, not incidental). `flight_quality` (a TLT/SPY macro-divergence feature that
decorrelates on a months scale) runs ~750x its block size at 1h — no feasible block size fixes
this; ~4 independent blocks of ~7,454 bars exist in ~30k observations, nowhere near enough for a
stable CI.

**What changed?** Per this project's principles (proof before promotion, resist overfitting,
instrument everything), block size was deliberately NOT tuned per feature — that would overfit
one dial to one symptom, and does nothing for `flight_quality` regardless. Instead, standing
instrumentation was added: `scripts/ops/alpha/ops_dependence_length_diagnostic.py` computes a
1/e-decorrelation-lag proxy for integrated autocorrelation time per (feature, tf) directly from
`feature_vectors` (O(n) per series, "sufficient for a flag, not a publication-grade estimate" —
not a rigorous IAT estimator), aggregates across sampled symbols via the median, and writes one
`integrity_monitor` row per (feature, tf) per run (`monitor_type='ic_bootstrap'`,
`subject='feature=<name>|tf=<tf>'`, `metric_name='dependence_length_ratio'`, `passed = ratio <=
alpha.ic.dependence_length_flag_ratio`). New APR key `alpha.ic.dependence_length_flag_ratio`
(migration 239, seed 2.0, `[conventional]`) — a factor-of-2 overshoot as first trigger, well
clear of the measured ~4x/~750x cases so the threshold isn't tuned to squeak either known case
through. Standalone script, not a change inside `services/ic_engine.py` (3,600+ lines, Phase 162
already restructuring its compute functions — avoids a fifth concern in the same file
mid-refactor). `--feature-filter` was also added to `ops_ic_null_calibration.py` so a future
confirmation run can stratify sampling toward `ctf_momentum`/`flight_quality` specifically
instead of the existing boundary-nearest sampling; not executed this session (operational
follow-up). Todo 091 is now closed carrying forward a 21% residual SUSPECT rate, WITH this flag
in place — not silently.

**What would the change have looked like if decided *before* seeing any data (pre-registered
justification), and honestly, was it?** No — this is a textbook post-hoc methodology decision:
the flag's existence, its ratio formula, and its 2.0 threshold were all chosen after observing
the specific `ctf_momentum`/`flight_quality` SUSPECT pattern. There is no pre-registered
dependence-length gate this project committed to before todo 091 surfaced the miscalibration.
What partially mitigates the selection pressure: the flag is a measurement/instrumentation
addition (a new observability signal, gating nothing on its own yet — "wiring an actual
[downstream] consumer is a separate, later decision," per todo 145), not a threshold change to
any existing gate (BH-FDR, EIC-04, walk-forward) — those gates' pass/fail behavior is unchanged
by this entry. The one number chosen with a stated rationale independent of the exact observed
cases (2.0, "a factor-of-2 overshoot is a reasonable first trigger," deliberately not fit to
land just above 4x or 750x) is the closest this entry comes to a pre-registered-style
justification, and it is honestly disclosed as `[conventional]`, not `[rca_analysis]`, for
exactly that reason.

---

### E11 — 2026-07-20: Pre-committed FRAME-04/SHADOW-REVIEW decision rule for Component E
champion/challenger shadow validation (Phase 143.1-08) — RULE ONLY, no result yet

**What result was observed before the change?** None — this entry is written before the
champion (`ensemble_trainer.py --weight-version 143.1-08-champion --no-sign-symmetric`) and
challenger (`--weight-version 143.1-08-challenger --sign-symmetric`) training runs have been
invoked. `feature_vectors` (36,719,598 rows, max `bar_ts` 2026-07-07), `feature_ic_scores`
(854,299 rows, most recent `computed_at` 2026-07-19T01:20:49Z, the corrected Plan 07 corpus)
confirmed live and unchanged by this entry. `alpha_events`, `alpha_frames` confirmed empty
(0 rows each) prior to this entry — no shadow data exists yet to have influenced the rule
below.

**What changed?** The full pre-committed promote/hold decision rule for Component E's
sign-symmetric eligibility flag is recorded in
`.planning/milestones/v3.1-phases/143.1-measurement-and-eligibility-integrity-fisher-z-ci-bootstrap-/143.1-08-SHADOW-VALIDATION.md`
Section 3 (SHADOW-REVIEW.md's frozen 5 criteria, applied per `weight_epoch`, plus two
Component-E-specific additions: non-regression vs. the champion, and a short-side-sanity
check on the newly-eligible population) — reproduced there in full rather than duplicated
here. Summary: **PROMOTE iff criteria 1-6 all pass AND criterion 7 is not a confident
loss; otherwise HOLD.** Section 4 pre-registers the E1-vs-E2 A/B re-run plan (E2 rejected
20/20 previously on a structurally-unexercisable all-long input; does not carry forward).
Section 5 pre-registers the emission-volume re-measurement against the 11.81M-long/1,479-short
pre-fix baseline.

**What would the change have looked like if decided *before* seeing any data (pre-registered
justification), and honestly, was it?** Yes — this is the entry's entire purpose. The rule
is committed to git in this same commit, before the training/scoring/frame-backfill commands
that would produce a result are invoked; the commit timestamp is the pre-registration proof.
The follow-up entry (E12, appended after the runs complete) records the actual measured
result and verdict, and per this ledger's own convention, will not alter the rule stated
here.

**Correction (same day, still before any training/scoring command executed):**
`SHADOW-VALIDATION.md` Section 3a records that criterion 5 (trailing-20-trading-day vs.
full-shadow-period IC Sharpe cliff) is not measurable against a one-shot historical
backtest — it requires a recurring `EnsembleICEngine` cadence over calendar time, which
does not exist (`counterfactual_tracker.py`'s own docstring: "out of scope for this phase,
D-09, follow-on todo 089"). The promote rule is corrected to depend on criteria 1-4 and 6
plus the criterion-7 short-side-sanity check; criterion 5 stays a frozen, unmodified
requirement of Phase 147's actual live promotion gate, deferred (not dropped) to when a
real trailing-vs-full-period split exists. This is a measurability-gap correction, not a
threshold renegotiation after seeing a result — no training or scoring command had run
when this was found.

### E12 — 2026-09-13: 10x spread-constant transcription bug corrected in `range_pct_fast_xs_ls_h5_falsification.py`, foundational to the personal-scale program's kill criterion

- **Observed first:** the pooled `range_pct_fast_xs_ls_h5` DEAD verdict (2026-09-02,
  `concept_registry` migration 329) — one of the two formal pre-registered results the
  program's decision gate (fired 2026-09-12) rests on. User directly challenged this
  session's cost assumptions ("execution costs are near free... assume minimal costs"),
  prompting a decomposition of the cost model rather than a defense or a cave.
- **Changed:** found `_LIVE_SPREAD_ANCHOR = 0.0014` (14bp) in the falsification script —
  should have been `0.00014` (1.4bp), matching 0b's actual measured live-quote median.
  The exact same 10x transcription error `personal_edge_paper_screen.py` had already
  caught and fixed in itself on 2026-09-02 (documented in that script's own comment),
  but the fix never propagated to this sibling script. Sat undetected 11 days — through
  an AGY adversarial review of the pre-registration's design, the 2026-09-11 graveyard
  reconsideration pass (which cited this verdict as "confirmed settled" without
  re-deriving it), and two same-day reuses of this exact file's `_build_phase` earlier
  in the same session the bug was finally caught (neither reuse imported the buggy
  constant, so neither was itself affected). Fixed in source (same commit); the entire
  original falsification was re-run end to end at the corrected value, same locked
  methodology, nothing else touched.
- **Pre-registered?** Yes, unambiguously — this is not a methodology change in the
  sense this ledger normally tracks. The correct value (0.00014, matching 0b's
  independently measured live-quote anchor) WAS the pre-registered intent from the
  start; the bug was a transcription error in implementing an already-locked decision,
  not a new choice made after seeing a disappointing or favorable result. Recorded here
  anyway because a fixed quantity central to a fired kill criterion moved after results
  existed, and this ledger's whole purpose is making exactly that visible, regardless of
  the reason it moved.
- **Result:** verdict UNCHANGED — still DEAD. All 9 cost combos still fail CI>0
  (corrected cheapest-corner CI [−5.0, +8.6]bp vs. originally-recorded [−7.9, +5.8]bp);
  stability still fails on the same qualitative shape (corrected subperiods −3.9/−6.4/
  +14.2bp vs. originally-recorded −9.7/−12.1/+8.7bp). Every point estimate moved
  meaningfully more favorable under the correction; none crossed into PASS territory —
  CI width from genuine sampling noise, not the cost-driven point estimate, is what
  keeps criterion (a) failing. `concept_registry` migration 335;
  `docs/research/construction-verdict-ledger.md`'s `range_pct_fast_xs_ls_h5` row.
- **Process lesson, not just a number fix:** a sibling script caught and fixed this
  exact bug class in itself the same day the buggy script was first run, and that fix
  never got checked against nearby scripts sharing the same constant name/convention.
  Worth a repo-wide grep for other `_LIVE_SPREAD_ANCHOR`-shaped hardcoded constants
  that could carry the same drift the next time a source-of-truth value changes.

### E13 — 2026-09-16: "Single-name equity is the primary breadth lever" corrected after D-10 FAIL; the D-10 thresholds themselves were unachievable by any raw-correlation equity population

- **Observed first:** D-10's pilot gate (Phase 174, Plan 15) FAILED decisively on an
  unbiased, market-cap-stratified draw of 40 down-cap single-name equities: unconditional
  raw correlation 0.3025 vs. ≤0.10 required (3.0x miss), `high_bear` 0.4303 vs. ≤0.30
  (1.4x miss). User pushed back across several turns questioning whether the gate design
  itself, not the population, was the problem — prompting the investigation below rather
  than accepting the FAIL verdict's framing at face value.
- **Changed:** two corrections, both made after seeing the FAIL result:
  1. Checked whether ≤0.10 unconditional was ever achievable for *any* raw-correlation
     equity population: pulled the full 9-regime correlation table for both the pilot and
     the existing 117-name baseline (18 cells total) — not one clears even 0.14, let alone
     0.10. Baseline's own `high_bear` cell (0.4789) misses the `high_bear` ≤0.30 leg worse
     than the pilot did. Both D-10 thresholds were reverse-engineered from a desired n_eff
     outcome ("floors the n_eff ceiling at ~10... a ~3x improvement," per `174-CONTEXT.md`
     D-10), not from any check of what raw equity correlation actually achieves in any
     regime. A residualized (SPY-beta-stripped) check on the same pilot data got to 0.10 —
     meaning the threshold is reachable, just not by raw correlation on unhedged equities.
  2. Corrected the strategic framing itself: STATE.md's Strategic Plan (2026-09-13) named
     single-name equity expansion "the primary breadth-scaling lever" on a raw-count
     argument (hundreds of possible new names vs. ~20 possible new ETFs), never tested
     against a decorrelation-quality argument. An exploratory 11-instrument cross-asset
     basket (GLD/DBC/URA/TLT/UUP/VIXY/EMLC/HYG/XOM/FCX/NEM, all already active and
     compute-eligible, zero onboarding cost) passed the identical D-10 gate cleanly
     (unconditional 0.0947, `high_bear` 0.1180) with n_eff 5.05-7.20 across every regime —
     beating the entire existing single-name book's best-case n_eff (~3.25) with 11
     instruments. Full write-up and a properly pre-registered (not hand-picked) follow-on
     candidate list: `docs/research/phase174-cross-asset-diversification-prereg-2026-09-16.md`.
- **Pre-registered?** No, and this entry exists because of that. Both corrections were made
  strictly after observing the FAIL result — this is exactly the class of change this ledger
  tracks. The 11-symbol exploratory basket in particular was hand-assembled in conversation
  (some ETFs already known to be in the corpus, some equities picked because their business
  obviously tracks a commodity) — real selection-bias risk, explicitly not treated as a valid
  test on its own. The follow-on document fixes a mechanical, reproducible selection rule
  (tertile cutoffs on `TagCalibrator`'s empirical `equity_beta`/macro-driver loadings) before
  running Gate A against it, specifically to remove that risk going forward.
- **Result:** D-10's FAIL verdict for the *specific* population tested (unbiased random
  down-cap draw, raw correlation) stands — the `unconditional` leg missed by 3.0x, a gap the
  `high_bear`-threshold critique doesn't touch. But the broader conclusion the verdict was
  being read for ("single-name equity expansion is a dead end for this program") does not
  follow from it, and STATE.md's Strategic Plan section needs updating to reflect that the
  real constraint is raw correlation among *any* unhedged long-only equity population, not
  something specific to down-cap names — genuine breadth requires either crossing asset
  classes or selecting the narrow slice of equities whose returns are dominated by a
  non-market factor, both now scoped in the follow-on pre-registration.
- **Process lesson:** the tool needed to identify low-market-beta/high-alt-factor equities
  without hand-picking (`TagCalibrator` against `equity_beta`) was correctly wired in schema
  (`factor_series='SPY'` was already set) but had never been run against the single-name
  book — it's a manual, no-timer oneshot tool (`docs/foundation/instrument-tag-registry.md`).
  Before this session, "XOM behaves like an oil stock, not a market stock" was an assertion;
  after running the tool, it's a falsifiable, reproducible fact. A correctly-designed
  measurement that nobody has run yet is indistinguishable from a missing one until someone
  actually runs it — worth checking for other wired-but-dormant measurement tools before
  concluding a hypothesis "can't be tested."

### E14 — 2026-09-25: Phase 179 calibration coverage counted over finite-alpha days, after the frozen run ended FIDELITY BROKEN

- **Observed first:** the frozen Phase 179 run (code a64af3d1a, pre-registration section 12.3)
  ended `FIDELITY = BROKEN` with no token: S3 raised on a zero-variance shifted series. Located
  from coverage counts alone, with no observed or null Sharpe read: section 6 sets alpha = NaN on
  days whose equity stratum has no weights, and section 7's calibration gave a symbol IC 0 unless
  95% of its trailing 504 sessions paired a finite alpha with a finite return. Only the 2023 and
  2024 calibration segments passed; the book held a position on 447 of 3,265 trading days.
- **Changed:** `scripts/analysis/sleeve_walk_forward/portfolio.py::_calibrate` (and the test
  reference): the IC is computed when at least `coverage_fraction` (95%) of the window's
  finite-alpha days also have a finite forward return (and at least 2 are paired). The
  coverage bar's purpose in the source diagnostic, whose alpha was defined every day, was
  missing return data; sample size is already handled by `shrink_instrument_ic`, which scales by
  the paired count. Under the new rule every one of the 13 segments calibrates and the book holds
  a position on 2,592 of 3,265 days (the rest are the no-weight-stratum days section 6 means to
  be flat). Owner decision 2026-09-25 (todo 425, option A).
- **Pre-registered?** No; a change to a frozen design after its run failed. Justification: the
  run produced no token and no performance number was read before or during the diagnosis, so
  the fix cannot be tuned toward an outcome; the new rule is pinned here before any rerun. Same
  hypothesis, same arms, null, thresholds and N_tested (18). Everything downstream of the code
  change is rerun once at the fix commit: V2, V3, V3b, V4, S1, V5, then S2-S4.

### E15 — 2026-09-25: Evidence framework adopted: book-version screen at M = 30 (count restarted), error control on the forward span

- **Observed first:** 18 pre-registered standalone verdicts on vintage 1 (data before
  `alpha.validation.oos_start`, 2025-12-24), zero PASS. The last two with real power machinery
  (TSMOM, Phase 179 E14 rerun) both landed at excess Sharpe +0.19 to +0.22, p 0.22 to 0.36, on a
  13-name daily sleeve where a Sharpe-0.5 edge takes about 16 years to reach t = 2.
- **Changed:** `docs/plans/2026-09-24-evidence-framework.md` version 4 and
  `docs/plans/2026-09-25-alpha-research-architecture.md` (adopted). The unit of test is a book
  version, not an idea; families enter the book by pre-registration and clean guards, never by
  an outcome screen; per-signal and per-family results are evidence records, not tokens. Tests
  on the searched vintage are a screen at alpha / M, one-sided, with M = 30 declared on vintage 1
  and the count restarted at 0 (owner decision); bar p < 0.00167. A test whose null has fewer
  than 600 admissible shifts, or whose synthetic power is below 50%, is refused before any
  real-data number. Error control moves to the forward span (holdout plus accruing data): one
  confirmation test of a frozen book, alpha 0.05 one-sided, on a date fixed at freeze by power.
  Capital only after confirmation, sized net of costs from the low end of the evidence.
  Replaces the program-wide `alpha / N_tested` rule in `construction-verdict-ledger.md`, the
  2-of-3 sub-period rule, and the Track 1 gates for new work.
- **Pre-registered?** No; a change of decision rules after seeing 18 results. Justification:
  no frozen verdict is re-scored, and no pending candidate's numbers exist yet. The count
  restart does not forgive the 18 looks, because none of them touched the forward span, which is
  where false discovery is now controlled; the restart changes only how strict the in-sample
  screen is. Several legacy tests also ran on data or code later corrected (E12's spread
  constant, E14's coverage bug, stale feature snapshots). Legacy rows keep their tokens.

### E16 — 2026-09-25 (ADOPTED 2026-09-25 by the owner): book test and confirmation move from the shift null to a HAC test on book P&L minus its static tilt

- **Observed first:** in H0 simulations with the exact `panel_null.admissible_shifts` rules
  (n = 4,700 sessions, min_shift 63, memory 252), the whole-session shift null is
  anti-conservative at the screen bar for persistent predictors. Rejection rate at nominal
  p 0.00167 by signal autocorrelation time tau (20,000 simulations per row, 16,000 for tau 199):
  tau 1: 0.0013; 7: 0.0018; 19: 0.0020; 39: 0.0021; 79: 0.0038; 132: 0.0054; 199: 0.0065 to
  0.0071; 666: 0.0107. The mechanism is that `min_shift` removes the observed alignment's own
  correlated neighbours from the null while every null draw keeps its neighbours, so the tail
  quantile is estimated from about admissible sessions / tau effective draws. A per-book sign-flip
  surrogate calibration of the bar only halves the excess at tau 199 (0.0065 to 0.00325). On the
  forward span (about 190 sessions today) the shift null is unusable for confirmation: a few
  effective draws, and no admissible shift at all for a book with 52-week members until the span
  exceeds about 380 sessions. Step 0 autocorrelation times (signal only, 1d): family 9 members
  19 to 604 sessions; family 1's same_slot_mean40 about 40.
- **Proposed change:** the S8 screen statistic and the section 7 confirmation statistic both
  become a one-sided HAC (Newey-West) t-test on the walk-forward book's daily P&L minus the P&L
  of its causal static tilt (each symbol's expanding mean weight through the prior session),
  with t critical values. The static-tilt leg does the job the shift null did for persistent
  per-symbol exposure (a book that always holds the same names is not timing them). Simulated
  size, H0, 5,000 simulations per tau at n = 4,000 with Student t4 returns, volatility clustering
  and per-symbol fixed effects in both predictor and returns: at or below nominal at 0.05, 0.01
  and 0.00167 for tau 1, 79 and 666. Confirmation-length size (mean-P&L HAC t, 20,000 simulations
  per cell): 0.045 to 0.055 at alpha 0.05 for n = 190, 500 and 1,000 and tau 1 to 666. The
  per-shift combiner refit is dropped: out-of-sample walk-forward P&L already has zero mean under
  H0, so no fitting capacity remains to remove, and lookahead is guarded by S3's canaries. The
  shift-null excess stays a reported diagnostic. The 600-shift refusal is replaced by the
  synthetic power refusal alone (power at least 50% at the bar).
- **Pinned implementation** (so the build guesses nothing; the simulations used exactly these):
  (a) HAC: Bartlett kernel (Newey-West), lag `L = floor(4 * (n / 100) ** (2 / 9))` with n the
  number of scored sessions, one-sided, critical value from Student t with n - 1 degrees of
  freedom. Not a function of predictor memory: the lag covers the P&L series' own dependence,
  which is short even when predictors are slow. (b) Static tilt: for each symbol, the expanding
  mean of the book's own final weights (after construction and scaling) over all scored sessions
  before t, a session where the symbol has no weight counting as 0; not renormalized; updated
  every session, no refit cadence. The tested series is `sum_j (w_t,j - wbar_t-1,j) * r_t+1,j`;
  scoring starts after `warmup_sessions` (252) so the mean is defined. (c) Unit: one value per
  session; intraday books use session-aggregated P&L (phase 183's R2). (d) Power: planted
  replicates (the family's V3 plant) run through this same statistic at the same bar, R = 100,
  refusal below 50% power; fixed-R exact curtailment is allowed. (e) Evidence records for
  families and members switch to the same HAC t; the shift-null p is kept as a diagnostic in
  every record. M, the bar (p < 0.00167) and confirmation alpha (0.05) are unchanged.
- **Caveats, stated before adoption:** HAC validity needs weakly dependent P&L; simulated with one
  common factor and volatility clustering, not with regime breaks or richer cross-sectional
  dependence. Daily books' P&L must be total-return (todo 428) for the static-tilt leg to mean
  what it says. Scripts: `scripts/analysis/e16_null_size/`.
- **Adoption refinements (phase 183, before any real-data number), each from a new H0
  simulation (`scripts/analysis/e16_null_size/slot_tilt_size.py`: 4 slots, slot-level fixed
  effects in returns, one factor, t4 noise, volatility clustering, persistent predictor whose
  static part aligns with the fixed effects; 4,000 simulations per cell):** (1) on intraday
  panels the static tilt is per (bar-of-session, symbol): a per-symbol tilt rejected in every
  simulation with slot fixed effects, because the shift null this replaces kept each bar's time
  of day. (2) The return is demeaned by its own causal expanding mean per (bar-of-session,
  symbol): the pinned `(w - wbar) * r` carries `(w - wbar) * mean return`, as persistent as the
  predictor and invisible to the Newey-West lag, and was oversized at the 0.00167 bar (0.0040 at
  tau 200 with realistic static means of 0.03 noise sd; 0.042 and 0.152 at tau 40 and 200 with
  0.3). The adopted series `sum (w - wbar)(r - rbar)` has the same expectation and held size in
  every cell: 0.047 to 0.054 at 0.05, 0.0085 to 0.011 at 0.01, 0.00075 to 0.0025 at 0.00167.
  Implemented in `src/intelligence/research/timing.py` and `src/intelligence/statistics/hac.py`
  (the unfloored Newey-West t the simulations used).
- **What it changes if adopted:** evidence framework sections 3, 6 and 7; the architecture's S8;
  phase 183 plans 06 and 09 (book test), which the phase 183 session is holding; D6 of
  `docs/plans/2026-09-25-multi-timeframe-horizon-design.md`.
- **Pre-registered?** No real-data number exists for any book; family 1's evidence runs have not
  started. The change is decided on simulations only.

### E17: 2026-09-26 (ADOPTED 2026-09-26 by the owner, with conditions): the timing statistic scores weights against a memory-lagged cell mean

- **Observed first** (todo 432, phase 183 session, book_v1 refusal diagnosis): E16's series
  `sum (w - wbar)(r - fbar)` is biased under H0 for members built from their own cell's recent
  target returns, because the causal expanding mean `fbar` contains the returns that built `w`
  (a Nickell-type bias). Real power harness: mean40 member H0 mean t -2.5 to -2.7; book_v1's 0/51
  power refusal was produced by the statistic, not by the data's resolution.
- **Independently checked** (this entry's author, `scripts/analysis/e16_null_size/
  own_history_bias_check.py`, 40 simulations per row, t4 noise, trailing-40 own-history member,
  3,000 sessions, 100 names): E16 as built, H0 mean t -0.37 with full histories and -1.37 when 40%
  of names list late (-1.10 with static per-name means); the adopted form -0.20, -0.19 and -0.01.
  The bias scales with how short a cell's history is when it is scored, which is why the real
  panel (late listings, missing bars, 13 slots) shows about -2.6.
- **Adopted statistic:** `T_s = sum over (bar, name) of w * (r - fbar_L)`, no weight demean, where
  `fbar_L` is the cell's mean target over sessions older than the signal's declared memory L, and
  a cell contributes only once `fbar_L` has at least 60 sessions of history. Under H0, `w` (built
  from the last L sessions) and `fbar_L` share no inputs, and `fbar_L` still removes a static cell
  mean. L for a member is its `slot_history_sessions`; for a book, the largest over its members.
- **Conditions of adoption:** (1) one implementation, `timing_series(..., memory_sessions=L)`,
  used by evidence records, book tests and power replicates alike, with L read from the spec and
  recorded in every evidence record; (2) before any real run uses it, an H0 battery of at least
  1,000 simulations per cell with late listings, static per-cell means, t4 noise, per-slot effects
  and a late-listing name, plus at least one cell with S1 in the loop (synthetic prices through
  `residual_returns`, whose 252-session loadings couple residuals across sessions, weakly and
  unmeasured); size must hold at 0.05, 0.01 and 0.00167 as in E16; (3) what it credits is stated:
  a signal that tracks slowly varying expected returns counts as predictability (both the E16 and
  E17 forms score it; the independent check's drifting-mean cells), a static exposure does not;
  (4) family 1's evidence records (spec b828c285, computed under E16 as built) are annotated as
  biased toward zero; the detection stands.
- **Also decided (owner, 2026-09-26):** the next book versions (family 1 book_v2, family 2's first
  book) default to a fixed, pre-registration-signed equal-weight combination of standardized
  members, pinned only after about 100 further synthetic replicates confirm the phase 183
  finding that the 252-session walk-forward ridge costs about half the t at IC 0.002; the ridge
  becomes a later, separately counted book version.
- **Built by:** the phase 183 session (owner of `timing.py`). Todo 432. Statistic 33ca32107;
  equal-weight combiner 5f3de6ca1; family 1 records annotated by migration 377 (condition 4).
- **H0 battery (condition 2), 2026-09-26. Gating criterion DECIDED by the owner 2026-09-26:
  option C, the measured-size gate plus a per-family guard (below).**
  `src/intelligence/research/null_battery.py`, driver `scripts/research/e17_null_battery.py`,
  1,000 simulations per cell, size judged against the 99% binomial bound at each level.
  - First run, every stress at 0.3 of the slot sd: bias fixed (mean t within 0.1 of 0 in every
    cell and arm), but the combined cell's tail was oversized (book 94, 37 and 11 rejections at
    0.05, 0.01, 0.00167). Isolated to static per-cell means with volatility clustering (sd of
    t 1.27; each alone about 0.97): a long-memory member's weight is then largely static, and a
    static weight times the slowly decaying error in fbar_L is long-memory P&L the HAC misses.
    Neither a 4x or 16x HAC lag nor a 252-session floor repairs it.
  - Measured on family 1's panel: static per-(slot, name) means have a true sd of about 0.019
    of the idiosyncratic slot sd (split-half correlation 0.21), the per-slot market mean an rms
    of 0.0096, both far below 0.3. Family 2 (measured by its session): static per-(leg, name)
    0.044, 0.045, 0.017; time-of-day means 0.059, -0.026, 0.013.
  - Second run, gating cells at twice the measured sizes (0.3 cells kept as non-gating
    diagnostics): size holds in the combined cell (sd of t 1.00) and in the S1-in-the-loop cell
    (sd of t 0.97 to 1.03). Three of 135 cell-level checks exceed the bound; fresh-seed reruns
    (2,000 each) show no slot-effect mechanism (0.1 is clean), and the residual excess at
    0.00167 (about 1.4 times nominal on 1,250-session panels, present in the pure Gaussian cell)
    falls to about 1.1 times at the real length of 4,000 sessions. Family 2's second run: size
    holds at 0.01 and 0.00167; its combined cell runs about 7 to 8 percent at 0.05.
  - Documented limits (diagnostic cells): large static cell means with volatility clustering
    (above); and, scored on S1 residual targets, credit for S1's per-slot beta error times the
    time-of-day market mean, of order a^2 var(beta_hat) (book mean t 3.16 at a = 0.3; negligible
    at the measured sizes).
  - The criterion was moved to measured sizes after the 0.3 failure was seen: a forking-paths
    risk in the methodology itself, so it is the owner's decision, not the builder's.
  - Alternatives tested and rejected before the decision (todo 432): a longer HAC lag (4x,
    16x) or a 252-session floor does not repair the 0.3 tail; a forward-shift null (returns at s
    against weights from s + k, k >= L + 1, no wraparound; criterion pre-registered in 432026a0f
    before the result) is more anti-conservative than the Student-t reference in every cell
    (0.3 hostile 10.0% and 3.7% at 0.05 and 0.01 against 9.5% and 3.0%; measured sizes 7.2% and
    2.2% against 6.0% and 1.5%; 400 panels each), and its effective draw count, about
    (sessions - L) / tau, cannot resolve 0.00167 for persistent members.
  - **Owner decision (2026-09-26): C.** The gating cells stay at twice the measured sizes, and the
    gate becomes a checked precondition instead of an assumption: before a family's first real
    run, its own static per-(slot or leg, name) mean sd and time-of-day mean sizes are measured
    on its panel, by the same method as above, and the run is refused (like the power refusal) if
    any exceeds the gated size. A family above the gate needs a battery at its own measured sizes
    first. The measurement is recorded in the family's evidence. Rejected: A (the gate unguarded,
    silently oversized for a family with larger static effects) and B (keep 0.3: no known repair,
    every book test blocked). Build: todo 447 (phase 183 lane).
  - **Guard built 2026-09-27 (todo 447):** `src/intelligence/research/static_sizes.py`, called
    by `run_family` and `run_book` after S0 and before S1. It measures on the analysis panel
    (after the members' universe, total return and any transform; split segments are separate
    names) with raw cross-sectionally demeaned cell returns from `trading_start`, the method
    that reproduces family 1's recorded 0.019, 0.21 and 0.0096. A refusal is recorded
    `refused` (uncharged) with the sizes; a pass puts them in every evidence record (schema
    v4). The gate is the elementwise max over each battery's gating cells, read from the
    battery module; a family module with no battery is refused before the ledger. One
    deviation from "the same method": the time-of-day size is gated net of sampling noise,
    sqrt(mean^2 - se^2), the correction the static sd already had. The raw value is recorded
    beside it. It is mostly noise (family 1: raw rms 0.0096 with per-slot se 0.005 to 0.011,
    net 0.0036), and it refused null test panels with no time-of-day effect. The gates stay as
    derived from the raw values, so this only loosens a measure that noise had inflated.
  - **Measured and passing (2026-09-27):** family 1 (snapshot 81fa9178) pooled static 0.0191
    against 0.038, time of day 0.0036 net against 0.0192; family 2 on its total-return legs
    panel (snapshot 67a17ee8, 189 names) static 0.054, 0.049, 0.016 against 0.088, 0.090, 0.034,
    time of day 0.052, 0.020, 0 against 0.118, 0.053, 0.025. Family 2's overnight static is
    above its session's price-only 0.044 but at 62 percent of the gate. Family 1's gate is
    pooled because its battery draws one sd for every slot; per slot, the open and close slots
    measure 0.043 and 0.034, the rest 0 to 0.024.
- **Pre-registered?** No book has a real-data test under E16; book_v1 was refused and uncharged.
  Family 1's member evidence exists and stays as recorded, annotated per condition (4).

- **Amendment 2026-10-27 (L on a multi-session target; implementer, indicagent-5b).** L kept
  `fbar_L` clear of the signal's inputs only because every target so far ended inside its entry
  session. A daily target at row r runs open[r+1] .. open[r+1+h], so `fbar_L` with L equal to the
  memory reads forward returns that share price moves with the weight's inputs. L is now the
  memory plus h on a 1d panel (fwd_span(h) - 1: h sessions, the last being the overnight move
  into the exit session) and unchanged intraday (`timing.e17_memory`), so no recorded family 1
  or 2 run, frozen verdict or battery moves. Found building the daily residual family's battery
  (prereg `docs/plans/2026-10-27-daily-residual-momentum-reversal-prereg.md`): a 5-session
  reversal member at h = 5 had H0 mean t +0.55 and rejected 15% at 0.05 with L = 5; with L = 10,
  on a battery panel with overnight gaps, mean t about 0 (60 simulations each). A first version
  with L = memory + h - 1 missed the overnight move into the exit session; the code review
  caught it, and the battery could not, because its panel had no overnight gaps then. Open alongside it: the Newey-West lag's Bartlett weights
  under-cover a 5-session overlap (H0 t sd 1.07 to 1.14 in the same runs); the family's battery
  at 1,000 simulations decides whether h = 5 runs before a horizon-tied HAC lag is adopted.

- **Amendment 2026-10-27 (L for fitted and smoothed books, design 4.5; plan 187-08).** A book's
  L is now member memory (with a daily target's reach) plus the combiner's training reach plus
  the horizon rule's reach, summed in rows and rounded up to sessions once (`book.book_memory`),
  used by the book test, its power replicates and the shift diagnostic alike. For an
  equal-weight book with kappa 1 nothing changes. For a ridge book L grows by its training reach
  in sessions; no recorded verdict moves (book_v1 was refused before any statistic). A ridge or
  smoothed (kappa < 1) book runs for real only under a certificate from the E17 battery at 4,000
  sessions (`research/certificates/e17_fitted_books.json`): ridge and kappa 0.2 hold, kappa 0.5
  on static means does not (72 of 67), and ridge with kappa has no gating cell
  (`.planning/phases/187-*/187-08-BATTERY.md`).

- **Amendment 2026-10-27 (in-fold equal-weight signs are trailing, an amendment to design 4.2;
  plan 187-09 Task 3, owner decision 2026-10-27).** Design 4.2 gives a family with no stated
  prior (`corpus_family`, `generated_family`) the sign of its expanding training-fold IC. Under
  design 4.5 every fitted part's training reach enters L, and an expanding fold's reach is the
  whole history, so L would cover the panel and leave E17 nothing to score. The fold is
  trailing instead: a pinned `sign_window_sessions`, refit every `sign_refit_sessions` (on the
  calendar grid when `refit_anchor` is set), with the ridge's embargo (fwd_span(horizon))
  between the last training row and the refit row. The fold IC is the mean over training rows
  of the per-row cross-sectional Pearson correlation of the member's z-score with the S1
  target; a zero or undefined IC makes the member absent for that block. The window plus the
  embargo is the combiner's training reach in `book_memory()`. A book using it runs for real
  only under a battery cell `equal_weight_in_fold_signs`. No recorded spec uses the field, so
  nothing moves.

- **Amendment 2026-11-18 (the battery size gate is family-wise; todo 636; decided AFTER the daily residual
  battery failed under the old gate, ruled by the lead on an independent Opus analysis).** The H0 battery
  judged every (cell, arm, alpha) test against the upper 0.99 binomial quantile. A battery has 126 such tests
  (daily residual: 6 gating cells x 7 arms x 3 levels), so a correct statistic fails it somewhere about 60
  percent of the time. The pooled daily residual run (2,000 simulations per cell) failed in `daily_static_means`
  at 0.05 for `reversal_5` (127, bound 123) and `reversal_5_skip1` (129). Fresh-seed simulation of that arm at the
  same code path (17,000 runs with the battery's) gives 4.99 percent at 0.05, a ratio of true spread to estimated
  standard error of 0.999 and no growth with the static-mean size, so the statistic is calibrated and the
  exceedance is sampling noise caught by a gate with a high false-alarm rate. The two arms share four of five
  inputs and fail at different levels in the two blocks.
  The gate becomes Bonferroni: a test fails when its rejections exceed the quantile 1 - 0.01 / n_tests of
  Binomial(sims, alpha), n_tests the gating cells x arms x alphas of the battery (the same pattern as the
  StepM battery). Recomputed by `battery_pass.problems` from the report; the driver's own failure list is
  advisory. The statistic, the cells and the arms do not change, so no frozen verdict moves. The H-C and
  seasonality passes held under the old per-test 0.99 gate, which is stricter per test, and still hold. Because the amendment follows a failure, the
  daily residual pass is not taken from the old blocks: the whole battery reruns once on fresh seed base
  2,000,000 with 2,000 simulations per cell, declared here and pinned in `DECLARED_REPLICATIONS` before it
  launches; blocks 1 and 2 stay in the todo as history. A looser per-test gate can hide a small real excess;
  the diagnostic above bounds any excess in the failing cell under about 0.4 points at 0.05.

- **Correction 2026-11-18 (retracts the calibration claim of the amendment above; todo 636; lead ruling, the
  ratification is withdrawn).** The amendment said the statistic is calibrated for `reversal_5` (4.99 percent over
  17,000 simulations). That diagnostic reimplemented the arm instead of running the battery's own path, so it did not
  test the battery's statistic. The check with the pass rule fixed before it ran (`scripts/research/e17_arm_calibration.py`,
  commit e93ea8252: the one-sided 95 percent upper bound of the rate at 0.05 below 5.5 percent; the battery's own
  `simulate`, cell `daily_static_means`, 12,000 simulations, seed base 77,000,000; record
  `research/calibrations/e17_reversal_static_means_2026-11-18.json`) FAILS for both arms: `reversal_5` 674 rejections at
  0.05 (5.62 percent, upper bound 5.97), 157 at 0.01 (1.31) and 39 at 0.00167 (0.32); `reversal_5_skip1` 676 (5.63), 149 (1.24)
  and 31 (0.26). The controls hold (`reversal_21` 4.78, M3 4.14, book 4.47, M1 3.18). The excess is real. The family-wise
  gate is therefore not in force: the gate code is reverted to the per-test 0.99 bound (the code key of the H-C record is
  unchanged by the revert, checked), no pass record is bound under it, and the daily residual family waits (a failure
  postpones, never a verdict). The statistic, cells and verdicts did not change. The amendment's own text stays as written
  (append-only). Lesson: a calibration diagnostic runs the battery's own path, and the pass rule is written down before it
  runs. The weak power of a 2,000-simulation bound (a true 6.45 percent size at 0.05 is caught about 17 percent of the
  time) is why single arms are settled by this check, not by the bound.

- **Second correction 2026-11-18 (the cause of the disagreement; todo 636).** The correction above attributes the
  4.85 percent diagnostic to a reimplementation of the arm. A line-by-line and seed-by-seed reconciliation shows that is
  wrong: on identical seeds the reimplementation and the battery's `simulate` give bit-identical t and p (largest
  difference 0.0 over 200 seeds, and the same 674, 157 and 39 rejections over all 12,000), so the battery is the correct
  E17 daily statistic. The 4.85 percent came from a different seed draw. Across seed sets the rejection rate of the two
  five-session reversal arms at 0.05 runs from about 4.6 to 5.6 percent, with a persistent mean t of about +0.035 (about 4
  standard errors pooled), which alone gives about 5.4 percent: a small real size excess, not caused by static means (a
  paired run with static sd 0.06 and 0 gives the same mean t) and not isolated further. The conclusion stands (the excess is
  real, the family-wise gate is not in force, no bind); the stated reason for the earlier diagnostic's different number is
  corrected here.

### E18: 2026-09-26 (ADOPTED 2026-09-26 by the owner): uncapped counted attempts with step-down selection, net-expectation promotion, per-book forward span

- **Source:** `docs/plans/2026-09-26-unified-research-to-production-design.md` (todo 436),
  sections 7 and 9, after a section-by-section brainstorm with the owner and an independent
  adversarial review (Fable 5.1, section 20 of that doc).
- **Replaces E15's screen budget.** E15's hard M = 30 book-version budget per vintage and its
  per-screen Bonferroni bar (p < 0.05 / 30) are replaced by:
  1. uncapped iteration; every real-vintage series a person can see is recorded with its full
     return series and joins the selection universe: book attempts in any runner mode (a new
     `exploration` mode included), member evidence runs, and diagnostic subset refits
     (leave-one-family-out, Shapley). A run that computed a statistic and then failed still counts;
  2. no bar per attempt; at selection, Romano-Wolf StepM over the whole selection universe at
     family-wise 0.05, on each attempt's E17 D_s per session, one common session calendar with
     per-series studentization, one joint stationary-bootstrap index draw, mean block length above
     the longest holding horizon. Known gap, disclosed: step-down tests assume a fixed model set
     while `informed_by` chains are adaptive; the forward confirmation covers it;
  3. vintage extension re-evaluates prior attempts; the count does not reset.
- **Promotion requires positive net expectation.** Within the selection set, the book that spends
  a forward span is chosen by pre-declared net expectation from the cost model at a conservative
  quantile; a book at or below zero is not promoted. Test statistics stay gross: the standing
  costs-not-gating directive holds for discovery and for every statistic. The promoted
  construction (costed partial-adjustment rate, cost-aware construction where used) must itself be
  an attempt in the selection set. Motivation: family 1's members carry gross Sharpe 3.8 to 5.3 at
  about 26x gross turnover per session, where 1 bp per side costs about 65% a year against about
  4.7% gross.
- **Forward span per book.** `.planning/gate_look_log.jsonl` records 7 scored looks at data after
  `alpha.validation.oos_start` (2025-12-24), the last on 2026-08-07 (Phase 148's `alpha_score`,
  the gate166 candidates, the `ctf_momentum` decile long-short), and until 2026-07-02 every IC and
  ensemble computation included that span. Books with `feature_vectors` members or
  `ctf_momentum`-like members confirm only on data after the book's freeze date and never before
  2026-08-08. Price-only families 1 and 2 keep the 2025-12-24 start, disclosed as adjacent to the
  `ctf_momentum` looks. A power-dated test date more than 3 years out refuses promotion.
- **Sealed shadow.** Every book in the selection set runs forward in shadow; its positions are
  readable only for loss-limit monitoring until its power-dated test date.
- **Unchanged:** each forward span's single use; E16/E17's statistic (E17 gains ridge and
  partial-adjustment cells in its H0 battery, and L for fitted books adds combiner and horizon-rule
  reach, design section 4.5). Frozen verdicts are not re-scored; nothing has been charged on
  vintage 1 (book_v1 was refused).
- **Built by:** roadmap phase 187 (research core). Until it lands, the phase 183 runner's
  M = 30 accounting stays in force for any book test run.
- **Pre-registered?** No real-data book test exists on vintage 1.
- **Implementation (phase 187 plans 04-06, 2026-10-27).** `src/intelligence/statistics/stepm.py`
  runs StepM on the joint index draw with each draw's series studentized by its own HAC
  standard error (`studentize="draw"`). Studentizing every draw by the sample standard error
  over-selected in the plan 05 battery (74 family-wise rejections per 1,000 against a bound of
  67 in `slot_effects`; 52 with per-draw studentization). The ledger records `exploration`
  runs, lets them repeat a spec, and no longer refuses a book test past M; `budget_m` stays on
  book_test rows. Selection is a read: `scripts/research/select_books.py` over
  `research_run_series`, with the four `alpha.selection.stepm.*` APR keys (migration 516).
  Adjusted p-values count the observed statistic as one more draw, (k + 1) / (reps + 1).
  `select_books` reports a set as a result only when every charged attempt has a series, no
  charged attempt sits on another vintage (re-evaluation onto an extended vintage is not built),
  and a complete passing battery record on the same StepM code attests it (Codex review,
  2026-10-27). A bootstrap draw with no evidence about an attempt (fewer than two of its
  sessions) counts as an exceedance, never as a loss. The runner keeps a run's series when it
  fails after its statistic exists, refuses a synthetic run on a real snapshot (an uncounted
  look) except a replay of a recorded run, and refuses a real run of a spec already run in
  exploration (AGY review, 2026-10-27). Open: until the full 13-cell per-draw battery holds, no selection set is a
  result.
- **Owner decision 2026-10-27: the StepM battery is judged at the real panel length.** On the
  battery's 1,500-session default panels two gating cells exceeded the bound (slot_effects 71,
  real_grid_hostile 70, bound 67 of 1,000), the short-panel excess E17's own battery documented;
  at 4,000 sessions, fresh seeds, both held (42 and 57). The attestation `select_books` accepts
  is a complete 13-cell run at 4,000 sessions (`stepm_null_battery.REAL_SESSIONS`). Decided
  after the 1,500-session failure was seen, as E17's measured-size gate was, so it is the
  owner's call and recorded as such. The book test's power bar still divides by M (`screen_alpha / M`); what replaces it
  under E18 is settled in plan 07.

### E19: 2026-11-01: the 1d session_coverage verdict anchors at each name's proven start

**Observed before the change.** The verdict judged each name from max(its first stored bar, the
calendar's first session) to the last completed session, so one hole after the first bar capped
the name's ratio for good. At the 2005 era 156 held names failed (191-SESSION-COVERAGE-FIX.md);
moving the calendar start to 2000 (todo 584 item 10) put 41 more below 0.999 (STRL 602 missing
sessions, WEYS 359, EFSC 239, CRGY 166; most 5 to 80). Measured on live canonical 1d bars at the
2000 era: 205 of the 1,509 names with a bar fail, and the failing holes are name-specific (0 of 986
distinct missing 2000-2004 dates for the 41 are vendor-wide). Excluding such a name drops its clean
later years and tilts the universe toward names with complete early history. Todo 532 raised it.

**What changed.** `proven_start` (`src/intelligence/bars/integrity_checks.py`) returns the
earliest answered session s whose session coverage over [s, last session] reaches the threshold
(APR `threshold.bar_integrity.session_coverage_min_1d`, 0.999, unchanged). `session_coverage` is
judged over [proven start, last session] and fails only when no such s exists, that is when the
latest session itself is unanswered. The audit writes the start as an informational fact
`proven_start_1d` (metric_value `date.toordinal()`, `integrity_monitor`, subject `SYM|1d`). The
rebuild (`services/backfill_feature_factory.py`) reads it and computes every timeframe of the name
from that session: bars before it are not fetched, the unit statistics and input digest are clipped
to it (a changed start renames the unit), and the name's own 1d and higher-timeframe inputs start
there. The start depends on bar presence only, never on returns, so it is not a return-informed
selection. An answered session is still a stored bar or an `ohlcv_empty_history` span; a missing
bar is never read as a no-trade day. Unchanged: the threshold, the other eight 1d checks, the
rebuild-only freshness check, the gate.

**Result on live data (2026-11-01).** 189 of the 205 failing names pass; the 16 still failing
(ACA, ACVA, BZH, CCO, CTVA, EIS, H, IOT, KNSL, MSGS, PNFP, PSKY, REMX, RPRX, SHEN, WBD) have an
unanswered latest session. All 41 of the item 10 names pass. Names whose start is later than their
first bar: 189 (trim in days, quartiles 346, 1,149, 2,738; 140 trim more than a year, 75 more than
five, 19 more than ten). A recent single hole costs the history before it: a hole fewer than 1,000
sessions before the end leaves no longer suffix that tolerates it, so the start moves to the next
session. That follows the rule as designed (D4); a later change that keeps more of such a name
would be a further entry.

**Limits, stated.** The threshold is a budget over the whole suffix, not a locality bound: with
3,000 judged sessions a 2-session hole 1,500 sessions before the end is tolerated, so a start can
precede a hole the suffix still absorbs (at most 0.1 percent of the suffix, the same tolerance the
verdict always had). The sector and regime composition of the research universe before and after
the trims has not been compared; that check is open and belongs before the rerun's first
hypothesis test.

**Pre-registered?** No. The rule was decided after seeing the 2000-era failures, by the lead
(design D4, todo 584), on bar presence alone; it does not read any return, signal or feature value,
so it adds no selection pressure to a hypothesis test. Frozen verdicts are not re-scored.

**Built by:** todo 584 item 11; closes todo 532.

### E20: 2026-11-04: the trend HMM state count moves from K=5 to K=3, one global value (583 refusal-rule study)

**Observed before the change.** `feature.hmm.n_components` was 5, from a 2026-06-26 BIC study on
four ETFs at 5m (migration 172) applied to every timeframe. The walk-forward fit refuses a segment
when a state is barely occupied (`degenerate_occupation`); at K=5 that stranded 4,036 of 5,260 1d
segments across 337 names (design D6), and todo 478 had found the same stranding for the
volatility family at K=3.

**The rule, fixed before the run.** For K in {3, 4, 5}, the K with the lowest share of refused
segments; ties within two percentage points go to the smaller K. The choice depends on fit
validity only, never on returns. Run per timeframe on a fixed-seed name sample (1d: the 337
refusal names plus 100 fully written names; 1h and 5m: 40 names), complete shards only.

**Result (refused share of segments, trend).**

| tf | K=3 | K=4 | K=5 | chosen |
|----|-----|-----|-----|--------|
| 5m | 6.2% | 7.9% | 17.0% | 3 |
| 15m | 1.3% | 3.5% | 12.0% | 3 |
| 1h | 1.5% | 5.5% | 9.6% | 3 |
| 1d | rule on complete data | | | 3 |

Volatility family: K=2 at every timeframe (1h: 0.0% refused against 56.6% at K=3), equal to the
existing `alpha.hmm_volatility.n_components`, so unchanged.

**What changed.** `feature.hmm.n_components` 5 to 3 (migration 566, with its `config_history` row
quoting the rule and the table). A per-timeframe mechanism (`feature.hmm.n_components.<tf>`) was
built and then not shipped: the answer is uniform, so four keys would hold one value (Musk step 2).
At K=3 `_build_label_map` assigns trending_down, ranging and trending_up; `transition_up` and
`transition_down` no longer occur. No code branches on them (the label tuple keeps them so label
codes stay stable). Every stored trend regime label changes, which the 186-26 rebuild at the new
pin covers. Companion change, same item: `hmm_vol_prob_elevated` is retired (D6): with K=2 the
label map never assigns the middle label, so the column was 0.0 by construction. The volatility
family's numeric block drops from seven columns to six; no stored value changes.

**BIC disclosure.** BIC prefers the grid edge K=6 on every timeframe, including 1d (380 of 437
names), so it does not bound K under these emissions and is uninformative here; the refusal rule
governs per D6. At 5m the BIC reference K was 6 (trend) and 5 (volatility), so |dK| against the
chosen value is 3 and 3. Nothing in this choice was judged on returns.

**Pre-registered?** The rule was written before the run (design D6, 2026-11-02). The K it selected
was not predicted. Frozen verdicts are not re-scored.

**Built by:** todo 584 item 3; 583 study.

### E21: 2026-11-09 (ADOPTED 2026-11-13): feature-level selection — every measured sweep cell is a counted attempt in the E18 universe

- **Source:** discovery lane (`docs/ideas/base-feature-scouting-and-the-research-ladder.md`,
  `docs/plans/2026-11-09-regime-conditional-and-incremental-ic.md`), gap identified by the review
  of 2026-11-09; todos 601 and 603. Drafted by the lead; the owner adopts or amends.
- **The gap.** E18's selection universe is per-session attempt series in `research_run` /
  `research_run_series`; the sweep (`ic_measure`) writes `feature_ic_scores`, a summary table with
  no series and no per-run provenance. A family built from sweep winners inherits the sweep's
  selection pressure, and nothing corrects it: the cells are invisible to StepM. The interim rule
  (2026-11-09) treats sweep cells as evidence records with `informed_by` chains and `n_looks` as
  bookkeeping. This entry replaces that interim rule with a real one.
- **The rule.**
  1. **Unit: the measured cell.** Level 1: (feature, timeframe, horizon). Level 2: (feature,
     regime group, state, timeframe, horizon). Level 3: (candidate, family, timeframe, horizon),
     in the runner. A proposal never measured costs nothing (blindness is auditable from the
     registry timestamp); a cell measured and then dropped after a result still counts.
  2. **Attempt series: per-session pooled cross-sectional IC.** Each cell's series is its pooled
     per-session IC over the vintage (dates, finite values only), the same per-session granularity
     as E17's D_s, on the common date calendar. StepM runs over these exactly as over book
     attempts: one joint stationary-bootstrap draw, per-series studentization. BH-FDR within the
     sweep block stays a display statistic.
  3. **Storage and sole writer.** Every measured cell is recorded as one `research_run` attempt
     (kind `evidence`, mode `real`, `concept_id` the feature's concept row, `run_group` the batch,
     the spec pinning the cell definition including its coordinates) with its series in
     `research_run_series`, written only through S6. `feature_ic_scores` stays the summary and
     monitoring layer; it is never the selection universe. `select_books.py` already includes
     `evidence` runs, so the universe gains the cells with no new table, no new writer and no
     change to the correction. Mode `real` also imports E18's no-silent-repeat discipline: the
     unique (spec_hash, concept_id) constraint refuses re-measuring the same cell silently.
  4. **Forward span.** A cell's target windows end strictly before `alpha.validation.oos_start`
     and its recorded series stops at that bound; the sweep never reads the forward span
     (section 11's purge rule, generalized to every IC row).
  5. **`informed_by`.** A family or member registration prompted by sweep evidence names the
     prompting cell's run; `run_group` recovers the whole batch. The cells stay in the universe
     forever: the family's book attempts are additional attempts, not replacements. The correction
     covers the feature-level cherry-pick; the book test still covers construction and promotion.
  6. **`n_looks`.** Declared in the ledger before each measurement batch and equal to the cells
     the batch measures across all levels. Universe bookkeeping, never a cap (E18's
     counting-is-a-price doctrine); correlated cells cost little under the joint draw.
- **Admission unchanged.** Admission gates stay outcome-free and their statistics are computed on
  the discovery span only (scouting doc, corrections 1 and 2). E21 changes counting, not
  admission.
- **Disclosed gaps, inherited from E18.** Step-down assumes a fixed model set while `informed_by`
  chains are adaptive; the forward confirmation covers it. Re-evaluation of existing cells on an
  extended vintage is not built (the same open item E18 records).
- **Volume gate.** The first sweep batch is a measured pilot: row count and series bytes of a full
  sweep (order 10<sup>4</sup> runs) are measured on one block before any full-corpus sweep runs.
- **Pre-registered?** Yes, by construction: no real-data sweep has run (the owner's clean-data
  rule, 2026-10-30), so this entry is written before any result it could be reacting to.
- **Built by:** todos 601 (levels 2 and 3) and 603 (register and gates). Until adopted and built,
  the interim rule above holds and no real-data sweep runs.
- **Adoption (2026-11-13).** The owner delegated the call to the lead's judgement against the project
  principles; the lead adopts the rule as written, with the section 11 amendment of the unified design.
  Reasons: it counts every look (the cell is the unit, a dropped cell still counts); it reuses
  `research_run`, `research_run_series`, S6 and `select_books.py`, so it adds no table, writer or
  correction (delete and simplify before build); and it was written before any real-data sweep, so
  nothing in it reacts to a result. The volume gate stands: no full-corpus sweep before the measured
  pilot. The clean-data rule (owner 2026-10-30) still gates the first sweep; adoption removes only the
  counting-rule blocker.

### E22: 2026-11-15 (OWNER EXCEPTION to the raw capture law 528): IBKR raw at or after 2003-09-10 is deleted with no export

**Observed before the change.** IBKR raw held 365.4M `ohlcv_raw` rows on 2026-11-13 (5m 224.7M, 15m 94.0M,
1h 25.4M, 1m 9.78M, 1d 11.48M) and 4.59M `ohlcv_revision` rows. Massive's flat files cover every date
from 2003-09-10 and are the canonical source from that date (step 7); Alpaca covers the span after the
archive end. IBKR raw is read once as evidence before the delete: the D1 card, B4's expected delta, the A11
identity witness and the D3 seam canary.

**What changed.** Law 528 (every vendor answer is stored and nothing is dropped) has one exception, ruled by the
owner on 2026-11-13 ("IBKR is removed entirely"; no export, no restore check, no dump) and given its predicate
by the lead on 2026-11-14: `vendor = 'ibkr' AND timestamp >= '2003-09-10'` in `ohlcv_raw` and `ohlcv_revision`,
run by `logs/massive_step7/run_partf.sh` after Part D passes. The 672,245 IBKR 1d rows before 2003-09-10 stay: they
are the only history before Massive's first file. Asks in `ohlcv_request` that retained rows cite stay with them.

**What it costs.** The IBKR series cannot be re-read for any date at or after 2003-09-10. Canonical does not
change (the gate compares the card recomputed after the delete with `card_after`), and no later statistic reads
IBKR raw. A pre-2003 tape question has only the retained rows.

**Pre-registered?** Yes. It is a retention decision made before the delete runs and not a response to a result of the
machinery it modifies; it adds no look and changes no gate, threshold or return definition.


### E23: 2026-11-18 (ADOPTED 2026-11-18, owner decision taken through the lead): registration of three published-prior families on the stage 2 universe (12 series)

- **Source:** `docs/plans/2026-11-15-published-prior-top3-prereg-drafts.md`.
- **Entry:** Registration of three published-prior families on the stage 2 universe. Counted design choices: the `universe_membership` and core panels as the family universe (two series per member), the seen-name holdout, h = 5 only, the S1-residual transfers of H-A and H-C, the pinned directions, StepM detection at 0.05 as the only pass. Looks declared: 12 series (section 4). Pre-registered by construction: no real-data number exists. Moves no recorded spec hash; `repro_frozen` bit-identical. Further counted design choices recorded 2026-11-18 (build items I1, B-U, B-H): S1 is fitted on the names seen as members on or before each date (first membership onward), membership gates alpha and target only, and non-member same-day returns of already-seen names enter S1's market and group means (point in time); an entrant's residual history starts at its first membership, and the share of member-days not yet warm because of entry is measured per year and disclosed at the membership build; `universe_membership_core` is defined over the span's month-ends, so a name's core status at t depends on months after t: core is a fixed robustness panel and never a selection basis for a counted family, and a family registered on core alone needs a separate counted amendment; M3's continuity rank is taken over every name with a finite ID on row d, including a name whose residual is NaN on d or that is not a member that day (masked afterwards); the H-C pinned values are max_missing_fraction 0.25, lags 5, min_lags 3, window_months 60, with declared memory read from `seasonality.slot_history_sessions(60)` (1,403 sessions) plus S1's 273, so the "about 1,260 plus 273" estimate above is superseded by the measured reach (1,324 and 1,297 sessions); the effective tested span is about 11 years, not 17, because E17's memory L = 1,408 sessions delays the first tested session to 2014-12-29, and the H-C sub-periods are 2015-01-02 to 2018-12-31, 2019 to 2022 and 2023-01-01 to 2025-12-23.
- **Adoption note:** recorded before any real-data number exists. It moves no recorded spec hash. A run still needs the E17 battery pass for its inputs and the E21 clean-data lift.

### E24: 2026-11-18 (ADOPTED 2026-11-18, owner decision taken through the lead): registration of family 10, the daily volume-shock members (4 series)

- **Source:** `docs/plans/2026-11-15-family10-volume-shock-prereg-draft.md`.
- **Entry:** Registration of family 10's two daily-clock volume-shock members on the stage 2 universe. Counted design choices: the 50-session and 5-session windows, the cross-sectional orthogonalization to the same-session return and its absolute value (a transfer of the paper's condition), the 40-of-50 positive-volume rule, the membership and core panels (two series per member), the seen-name holdout, h = 5 only, StepM detection at 0.05 as the only pass. Looks declared: 4 series (section 5). Pre-registered by construction: no real-data number exists. Moves no recorded spec hash.
- **Adoption note:** recorded before any real-data number exists. It moves no recorded spec hash. A run still needs the E17 battery pass for its inputs and the E21 clean-data lift.

### E26: 2026-11-18 (ADOPTED 2026-11-18, owner decision taken through the lead): registration of family 9, 52-week-high anchoring (1 member, 2 series)

- **Source:** `docs/plans/2026-11-15-family9-52week-high-prereg-draft.md`.
- **Entry:** Registration of family 9's one 52-week-high member on the stage 2 universe. Counted design choices: the single member F1 (the ledger's seven pending members reduced to one by Musk step 1), the 252-session window and the 240-of-252 finite rule, the total-return close, the pinned positive sign against the seen opposite-sign corpus look, the membership and core panels (two series), the seen-name holdout, h = 5 only, StepM detection at 0.05 as the only pass. Looks declared: 2 series (section 5). Pre-registered by construction: no real-data number exists. Moves no recorded spec hash.
- **Adoption note:** recorded before any real-data number exists. It moves no recorded spec hash. A run still needs the E17 battery pass for its inputs and the E21 clean-data lift.

### Amendments A1 and A2 to the daily residual family: 2026-11-18 (ADOPTED 2026-11-18, adoption delegated to the lead)

- **Source:** `docs/plans/2026-10-27-daily-residual-momentum-reversal-prereg.md` section 10 and `docs/plans/2026-11-15-published-prior-top3-prereg-drafts.md` (H-A).
- **A1:** the family universe moves from `daily_unseen` (1,269 names) to the stage 2 membership panels, primary `universe_membership` and core `universe_membership_core`, each member a counted series on each panel; the seen-name list stays a pinned exclusion. **A2:** a sixth member M3 `residual_momentum_12_1_continuity` (sign +1, slot history 252, declared memory 525). Attempts: six members times two panels, 12 looks.
- **Machine form:** `research/specs/daily_residual_h5.yaml` and `daily_residual_h5_core.yaml`, spec hashes `de9bc2ac6d71` and `f97c5b4baa5e` (sha1 prefixes of the files at adoption).
- **Status:** recorded before any real-data number exists. The family cannot run until its E17 battery pass is bound (todo 636, block3) and the E21 clean-data lift is given; A1 also depends on the membership build (todo 609). The size-gate history is the E17 amendment of 2026-11-18, not text in the prereg.

### Amendment A3 to the daily residual family: 2026-11-18 (the two 5-session reversal members are dropped; lead ruling, owner veto reserved)

- **Source:** the E17 amendment and its two corrections of 2026-11-18, todo 636, `research/calibrations/e17_reversal_static_means_2026-11-18.json`.
- **A3:** `reversal_5` and `reversal_5_skip1` leave the family. The family is `residual_momentum_12_1` (M1), `residual_momentum_12_1_z` (M2), `residual_momentum_12_1_continuity` (M3) and `reversal_21`, plus the equal-weight book as the combiner. A1 and A2 stand by reference, except that A2's count of six members and its 12 attempts become four members times two panels, 8 attempts (the book is not a counted look, as before). E23's 12 series are the three published-prior families' own count and do not change; no other counted choice moves.
- **Why, and why it is result-independent:** the battery's own statistic over-rejects for the two five-session reversal arms by a small amount that persists across seed sets (a mean t of about +0.035, about 5.4 percent at 0.05; 5.62 and 5.63 percent over 12,000 fresh simulations against a pre-declared pass rule of 5.5 percent; block 3 also exceeded the per-test bound for `reversal_5_skip1` in `daily_gaussian`). The cause is not isolated (todo 638). The decision uses the null battery only: no real-data number exists and none was seen. The statistic, the other members and every frozen verdict are unchanged.
- **Machine form:** `research/specs/daily_residual_h5.yaml` and `daily_residual_h5_core.yaml`, sha1 prefixes of the files `77347dafbb5c` and `77ab4cf495bb`; `null_battery_daily_residual.MEMBERS` follows the spec.
- **Pre-declared rerun:** the whole battery of the four-member family reruns once, one driver call, seed base 3,000,000, 2,000 simulations per cell, under the per-test 0.99 bound of E17 (the family-wise gate is not in force), pinned in `DECLARED_REPLICATIONS` in the same commit. A failure postpones and is never a verdict. Editing the battery module moves the stored H-C seasonality pass (that battery imports the daily panels), so the seasonality battery is rerun at the landing commit on the same seeds (base 0; same code path, so the counts reproduce) and its record rebound; the old record is replaced.
- **Status:** recorded before any real-data number exists and before the rerun launches. The family still needs its E17 pass and the E21 clean-data lift.

### E17 amendment 2026-11-18 (b): L is the weights' memory, the longer of the signal window and the vol window (lead ruling, owner veto reserved)

- **Source:** an independent analysis of the 5-session reversal arms' mean t (todo 638), confirmed by a paired experiment on the battery's own path; `timing.e17_memory`.
- **Finding:** the weights read the trailing vol window (`construction.vol_window_sessions`, 60 sessions in the daily residual family) as well as the signal window, but E17's L counted only the signal window. For a member whose window is shorter than the vol window (reversal 5 and 21, L = 10 and 26) the cell mean fbar_L and |w| share inputs, so the null mean t shifts by about +0.02 to +0.025. Paired over 4,000 simulations at seed base 9,000,000 (`daily_gaussian`, same panels, L as built against L covering the vol window, L = 65): reversal_5 shift +0.0211 (se 0.0014), reversal_21 shift +0.0254 (se 0.0014); mean t -0.0065 to -0.0259 for reversal_5 and +0.0286 to +0.0051 for reversal_21 once L covers the window. This is the cause todo 638 asked for. Momentum members and the book (L of 257 or more) already covered the window and do not move.
- **Change:** `e17_memory(slot_history_sessions, horizon, bars_per_session, weight_history_sessions)` returns `max(slot_history_sessions, weight_history_sessions) + reach`; `book_memory` takes the same argument. Threaded through the runner (family and book paths) and the five batteries (daily residual, seasonality, null_battery including its member arms, overnight_intraday and persistent). One definition of L for the runner and the batteries; the exploration scripts `scripts/research/family1_*.py` (uncounted, outside the runner) still pass the raw slot history and are exempt.
- **What it touches:** L changes only where a member's slot history is below the spec's vol window: the daily residual family's `reversal_21` (21 to 60 sessions, L 26 to 65) and the two dropped 5-session arms; family 1's members with slot history 1 and 5 (15m panel, no daily reach: L 20 in place of 1 and 5), family 2's `gap_fade` (slot history 1, L 20; its other members are 20 or more), and the persistent battery's `rk_vwap_dev_w20_1h` cell (1h source to a 1d book, horizon 1: L 4 to 21; its recorded result in `.planning/phases/184-multi-timeframe-research-inputs/184-05-BATTERY.md` is stale and the cell is withheld for volume basis anyway). Seasonality (1,403), every book (member memory 257 or the family maximum is at least the vol window) and every other member are unchanged. Recorded E17 evidence: family 1 and family 2 have no battery result file for these members (their E17 passes are ledger prose, legacy waivers, todo 637), so no recorded pass changes numerically; their recorded real-run verdicts are re-checked by `repro_frozen` (result in the landing commit message).
- **Fitted-book certificate voided on purpose:** `research/certificates/e17_fitted_books.json` fingerprints `timing.e17_memory` and `book.book_memory`; editing them voids it, so a fitted book (ridge or kappa below 1) is refused for a real run until a fresh battery recertifies it (todo 639). No first counted family uses a fitted book. Book memory is unchanged for every existing spec, so the recertified counts should equal the voided ones.
- **Reruns:** every stored battery pass whose code closure includes the statistic is stale by design: the seasonality battery is rerun at the landing commit on the same seeds (base 0; L is unchanged there, so the counts reproduce) and its record rebound; the daily residual and H-C batteries rerun after landing on seeds the lead declares. The restoration of `reversal_5` and `reversal_5_skip1` (A3) is a separate counted amendment; this entry does not restore them.
- **Status:** recorded before any real-data number exists. The decision uses the null battery only.


## Daily residual battery rerun after the E17 memory fix, declared 2026-11-19 (lead ruling, before launch)

The seed base 3,000,000 run of the four-member family failed on `reversal_21` while the statistic still counted L = 26 against a 60-session vol window (amendment 2026-11-18 b). The statistic changed, so the family is not bound from that run. Pre-declared: the whole battery of the four-member family (M1, M2, M3, `reversal_21`, two panels) reruns once, one driver call, seed base 4,000,000, 2,000 simulations per cell, under the per-test 0.99 bound of E17, at the commit that pins `DECLARED_REPLICATIONS["daily_residual"] = (4_000_000,)`. A failure postpones and is never a verdict. The bound is not changed and no arm is picked after the result. `reversal_5` and `reversal_5_skip1` stay dropped (amendment A3); restoring them is a separate counted amendment.

### E27: 2026-11-19 (lead ruling, owner may veto): the Massive 1d loader excludes a row its own file stamps at another session

**Observed before the change.** The all-ticker 1d load (todo 609 s4) stopped with exit 1 at the 2019-08 month: `build_raw_batch` refused 19 keys offered twice with different values. The 2019-08-12 day file (`data/massive/files/day_aggs_v1/2019/08/2019-08-12.csv.gz`) holds 29 of its 8,477 rows stamped `window_start` 2019-08-13 04:00Z (the next session); 26 have volume 0. Each contradicts the 2019-08-13 file's row for the same ticker (AMUB and BNKU carry different values in both files). A scan of all 50,285,088 day-file rows, 2003 to 2026, against midnight New York of each file's date finds exactly these 29 and no other row; the 5m reader already refuses any minute stamp outside its file's New York day, and every 5m year has loaded under that check.

**What changed.** Law 528 (every vendor answer is stored and nothing is dropped) has one more narrow exception: the 1d loader (`scripts/ops/bars/ops_massive_load.py`, rule `split_misstamped_day_rows` in `src/intelligence/bars/massive_flat.py`) does not load a day-file row whose stamp is not midnight New York of its file's date. The rule is generic (no symbol list), the rows are written as served (every column, the served volume) to `<--out stem>_misstamped_rows.csv`, counted in the year line (`mis-stamped rows excluded`) and logged per file. The archive file keeps every row, so a reload restores them. The generic `VendorIngress` 1d reader (`ops_bar_load --vendor massive --timeframe 1d`) refuses a file holding such a row, since it has no evidence channel. The writer's refusal of a key offered twice with different values is unchanged.

The 29 rows (file 2019-08-12.csv.gz): AMUB, BNKU, BSCE, BUY, DAUD, EEH, EMSG, FAUS, FLEU, GLBY, HONR, IMFC, INAU, IXSE, JJE, OLEM, PQLC, PQSV, PYPE, RBIN, RIDV, SCAP, SCOM, ULTR, USDY, USI, VEGA, VGFO, XMX.

**What it costs.** Those 29 stale or carried rows never reach raw as 2019-08-13 bars; the real 2019-08-13 row of each ticker (where the 2019-08-13 file has one) loads as served. No clean year changes: the rule excludes nothing in any other file.

**Pre-registered?** Yes. A data-integrity rule decided before the affected month is loaded; no statistic has read these rows, no gate, threshold or return definition changes, and it adds no look.


## Daily residual pooled replication, declared 2026-11-20 (lead ruling, before any run)

Pre-declared before the run: nothing below has been run, and no result of it is known.

Where the family stands. The four-member run at seed base 3,000,000 failed `reversal_21` at two cells (127 > 123 in `daily_gaussian` at 0.05, 9 > 8 in `daily_static_means` at 0.00167). It ran before the E17 statistic memory fix (todo 638), so it is not bindable. The rerun declared on 2026-11-19 (seed base 4,000,000, `logs/e17_daily_residual_fix_rerun/`, commit 588502223) held `reversal_21` at every cell and failed one test: `daily_s1_hostile` / `residual_momentum_12_1_continuity` at 0.05, 127 > 123. Both failures postpone and are never a verdict. No gate, bound or arm is changed by this entry, and no seed block is rerun for a pass: 3,000,000 and 4,000,000 stay spent and are not part of the pool (a bound record needs every block at one driver commit, and the pin commit changes the code key).

Declaration. The whole battery (all eight cells, six gating and two diagnostic; no cell or arm picked) runs in two independent blocks, one driver call each, 2,000 simulations per cell, at one commit, the pin commit of todo 584; `DECLARED_REPLICATIONS["daily_residual"] = (5_000_000, 6_000_000)` (block 1 first) is pinned in the commit that records this entry, which precedes the run. The driver draws seed = base + 10,000 x cell + simulation, so block 1 consumes seeds 5,000,000 to 5,071,999 and block 2 6,000,000 to 6,071,999. Every base used before is 0, 1,000,000, 2,000,000, 3,000,000, 4,000,000, 9,000,000 and 77,000,000 (each spans under 100,000 seeds); the two ranges are disjoint from all of them and from each other. Run once, at that commit, never rerun for a pass.

Pass rule. Per cell, arm and alpha, the rejections of the two blocks are summed (n = 4,000) and compared with the unchanged per-test 0.99 binomial bound at the pooled n: 233, 55 and 13 at alpha 0.05, 0.01 and 0.00167 (the per-block bounds at n = 2,000 are 123, 31 and 8). The six gating cells report five arms (the equal-weight book and four members), 90 tests. The pass is the pooled result, judged by `battery_pass.make_record`; the blocks are reported separately and neither is judged alone. `bind_battery_pass.py` accepts exactly the bases (5,000,000, 6,000,000) in that order, requires each block's driver JSON to record its seed base, and refuses a single block, a third block, a different base or a different order. A failure anywhere in the pool postpones the family again and is not a verdict on the hypothesis.

Why the pooled rule is not looser than the per-block rule it replaces. The per-test false-fail probability under a correct statistic is the same quantile (0.99) at a larger n. Computed with `scipy.stats.binom`: at n = 2,000 the per-test exceedance probabilities are 0.0095, 0.0078 and 0.0074; at n = 4,000 they are 0.0086, 0.0094 and 0.0088. Treating the 90 tests as independent (they are positively correlated, which lowers both figures), the expected number of exceedances is 0.74 at n = 2,000 and 0.80 pooled, and the probability of at least one is 0.53 and 0.55. The false-fail rate of the full battery is therefore about the same as a single block's, not lower and not meaningfully higher. Power rises: the bound sits 0.0083 above alpha = 0.05 at n = 4,000 against 0.0115 at n = 2,000, and a true size of 0.055 at alpha 0.05 is flagged with probability 0.17 against 0.09 (at a true 0.06 the figures are 0.665 against 0.366). This replication follows seen failures of two earlier blocks, so it is a retry; it is declared before it runs, every block is spent whatever it shows, and the rule is not relaxed by it. No rule of the form "either block passes" or "the best block" is used. The expected false-fail probability near 0.55 is a property of the E17 per-test gate across 90 tests, recorded in todo 636; a calibration proposal would be a separate counted amendment.

Status: recorded before the run. The declaration is in `DECLARED_REPLICATIONS` and tested (`tests/unit/research/test_battery_pass.py`).

## 2026-11-20: strict sweep gate scope (lead ruling, owner veto reserved)

The A3 strict sweep over all 12,561 universe members cannot pass on a Yahoo-only witness by construction: Yahoo has no history for most dead names (19,342 of 25,189 breaks read; 3,551 of the 4,086 unresolved, 1,516 names). The gate covers the breaks that have a witness. A break the witness cannot read is disclosed as unwitnessed, is not a gate and is never counted as confirmed. The disclosure carries the total and the class counts (witness_no_data 3,551, not_bracketable 262, route_not_rescalable 219, single_bar_reversal 38, recorded rows 15, unrecorded_split 1). A second witness counts only as tape plus a vendor agreeing. Five date corrections that Yahoo cannot judge (ACGN, ETS, ICA, REV, VIP) stay refused and open; the witness rule is not loosened. Record: todos 629 and 646.

## 2026-11-20: strict sweep gate scope by timeframe (lead ruling, owner veto reserved)

Amends the entry above, recorded before any real-data test. The strict sweep gate covers the witnessed breaks inside the name-years each timeframe's compute reads, taken from the fixed `universe_membership` rule and never from sweep results. The 1d scope is every member name-year (318 witnessed undecided breaks); the 5m scope is the tier_5m name-years (81 of those 318). 211 of the 529 undecided witnessed breaks fall in no member name-year and are disclosed with their class counts. Breaks Yahoo cannot bracket (`not_bracketable`) stay disclosed: no witness, no gate, no fix. The scope is not changed after a sweep result is read. List: `logs/sweep_strict_members_20261120b/in_scope_C.csv`.

## 2026-11-21: stage 2 universe, security type once per security and placement of unplaced names (owner standing criterion, lead rulings)

Two dated amendments to `docs/plans/2026-11-13-stage2-universe-preregistration.md`, adopted before any return-based look at the universe and before any counted test.

What changed. (1) The security type is resolved once per security into the append-only `security_type` table (todo 648) instead of being read from the list row of each month-end; member counts at 2008-06-30, 2012-06-29 and 2016-09-30 are 3,007, 3,129 and 3,824 (label rule: 2,138, 2,023, 2,188), and the step at 2016-10 is gone. (2) Placement rule P1 attaches spans to about 110 current equities the pit map left unplaced (Agilent, Accenture, Aon and others); the candidate pin moves with each.

What it costs. A disclosed early-era survivorship direction (a name typed only by a later list is a member back to 2003; the share of early-era member-days resting on a later list is not measured), 823 class conflicts counted not resolved, years 2003 to 2006 and 2009 under the 2,950 sizing and disclosed, and a point of no return after the Massive load for the new spans. No statistic, return definition, floor, window or gate threshold changes.

Pre-registered? Yes. The owner ruled on 2026-11-21 in the lead's session: adopt if it is what Simons would do and its impact is material; the lead found both and records the adoption. Owner veto reserved.

## 2026-11-21: data gate scope, judged on the name-years the compute reads (lead ruling, owner veto reserved)

Implements the owner's materiality ruling of 2026-11-20 (a data gate judges only what can move a counted test) for the 584 corpus rerun data gate (`services/corpus_rerun_data_gate.py`, commit `eaed3ef35`). Recorded before any counted test; no threshold changes.

What changed. The gate counted every session from a name's proven start to the horizon, so a name that died was charged for every later year (AMZ: bars 2003-09-10 to 2004-12-13, member 2003-12 to 2004-11, 252 missing sessions in each of 2005 to 2026). The 2026-11-21 plan-only run on the rebuilt universe failed 90,386 name-years, 43,079 of the 47,088 on the 1d term outside the name's membership years. New rule: the 1d term judges a name-year only if the name has a `universe_membership` row in that year (scope C); the 5m term judges only `tier_5m` years (scope B) and only at scope `all`; sessions count only inside the name's membership span (first day of its first membership month to its last `as_of`); a name that exits and re-enters is judged per year with a row. The thresholds (`max_missing_session_fraction` 0.01, `max_missing_1d_session_fraction` 0.01, `min_session_bar_fraction` 0.9) are unchanged. The scope (`1d` or `all`, CLI `--data-gate-scope`) is recorded in the run and in `corpus_run.data_gate`; a `1d` verdict does not unlock the pilot or any intraday step.

Result on the rebuilt universe (12,857 names, 5,192 in the 5m tier, horizon 2026-11-01, scope `1d`): FAIL on 31 name-years over 30 names, 0 names without a proven start; 22,309 name-years fail the 5m term and do not gate at scope `1d` (the tier 5m load does not exist yet).

What it costs, disclosed. (1) 587 names (25 in the tier, all inactive, 9,492 of 1,042,561 member-months) have a proven start after their last membership month, so the compute starts them after the months they were members; they are listed in the gate result as members before their proven start, not refused. (2) The 31 failing name-years: POWI 2006 and 2007 (70 and 153 missing sessions; the Massive raw rows are themselves sparse, so the hole is vendor-side), and 29 name-years with 1 to 5 missing sessions (1.2 to 4.8 percent), most of them runs of 3 to 5 consecutive sessions with no row. The classified list is `logs/gate_66_20261121/residual_classified.csv`.

Pre-registered? Yes in kind: the scope is the compute's own scope (scope C and B of the 2026-11-20 materiality ruling), taken from the membership rule and never from gate results, and the thresholds were fixed before the run they judge. The residual and the 1d-only pilot gap are open and are decided separately.

## 2026-11-21b: data gate residual tolerance and named exceptions (lead ruling, owner veto reserved)

Amends the entry above. Set after seeing the result, and said plainly: the 1d scope run on the rebuilt universe failed 31 name-years over 30 names. A 1d name-year now gates only when more than 5 percent of its judged sessions are missing (a pre-registered gate constant of this amendment, not an APR key). The 5 percent was chosen after seeing the failures: it sits just above the two largest non-POWI shares (KO 2003 at 4.5 percent on 22 sessions as counted by the gate, FXB 2006 at 4.8 percent), so it was fitted to this result.

Why it is still right. The compute applies no_fill: a missing session is NaN, so a gap removes observations and cannot bias a return. The failing name-years are 0.016 percent of the roughly 190,000 judged. Holding the 30 names would cost far more good history than the gaps cost. The threshold in force before this entry (1 percent per name-year over the whole universe) fails on vendor-side holes in any real universe of this size, so the stricter rule gates nothing it can fix.

Named exceptions, held with their evidence: POWI 2006 (70 of 251 judged sessions missing) and POWI 2007 (153 of 251). The Massive raw rows for POWI are themselves sparse (300 rows for 2006-01 to 2008-01, about 525 expected; none for Jan to Jul 2007 or Sep 2006) and canonical equals raw, so the hole is vendor-side. The cause is unverified (consistent with a period off the SIP feed). The exceptions live in a pinned APR JSON list with the evidence, not in code.

Disclosed class, counts not findings (not witnessed, by ruling): 22 name-years with 1 to 5 missing sessions (AORT 2022, ASB 2014, ERIC 2006, MDRX 2008, EFOR 2026, KIE 2006, AGRX 2019, AXAS 2008, CS 2006, OPK 2018, POLY 2021, TREX 2009, RYZ 2026, BRCD 2007, FLG 2024, GOVI 2023, GSK 2022, MAG~00DHNG15 2016, NTUS 2019, OPLN 2025, SCHW 2005, FXB 2006; mostly runs of 3 to 5 consecutive sessions with no row), and 7 name-years the gate counts at 1 to 3 missing that a direct read of canonical does not reproduce (EWM and GDX and GDXJ 2020, GSAT 2017, KO 2003, NGS 2005, NUE 2020). Of the 31: 27 are at or under 2.0 percent, two are 4.5 and 4.8 percent, and the two POWI years are 27.9 and 61.0 percent.

Proven start, disclosed, no rule change: 587 members (25 in the tier, all inactive; 9,492 of 1,042,561 member-months, 0.9 percent) have a proven start after their last membership month, because the 0.999 coverage rule needs density through the name's last bar and a sparse tail after a halt or delisting pushes the start past the whole dense history (RSX halted 2022-02 with proven start 2022-12-13; BFX, SCOR, HHS the same). The compute starts them at the proven start, so it does not read their member months. The pilot report carries the count; the rule is redefined only if the pilot shows it matters.

Pre-registered? The tolerance and the exceptions are decided before the corpus rerun and before any counted test, but after seeing the gate's 31 failures; that is stated above, and the lead rules it right on the grounds given.

## 2026-11-21c: amendment A4 to the daily residual family, M3 dropped for battery size excess (lead ruling, owner veto reserved)

Recorded before any run of the reduced family and before any real-data number for any member of it.

What changes. `residual_momentum_12_1_continuity` (M3, amendment A2) leaves the family. The family is `residual_momentum_12_1` (M1), `residual_momentum_12_1_z` (M2) and `reversal_21`, plus the equal-weight book of those three. Attempts become three members times two panels, 6 looks (A3 had 8). M3 may return only as its own later family with its own battery, preregistered before it runs.

Why. The cell `daily_s1_hostile` / M3 at alpha 0.05 exceeded its per-2,000 bound of 123 in three independent blocks: 127 (seed base 4,000,000), 126 (5,000,000) and 114 (6,000,000). The pooled replication declared on 2026-11-20 (seed bases 5,000,000 and 6,000,000, commit bc3656687, `logs/e17_daily_residual_pooled_5m6m/`) failed on that one test, 240 against the pooled bound of 233 (6.0 percent at the 5 percent level); `bind_battery_pass.py` refused and nothing was bound (todo 636, outcome note a23e0dd97). Every other test held pooled, M1, M2, `reversal_21` and the book of four included. Three exceedances of the same cell are a mild oversize of the member, not an unlucky draw. The statistic is not changed (a fix would need a methodology change and `repro_frozen`, for a member added late) and the gate is not recalibrated (that would be tuning the gate after seeing its result, which the prereg forbids).

No look is spent. No real-data number was ever produced for M3 or for any other member, and no run attempted the family. The look count stays zero.

The book changes. The equal-weight book of three is a different statistic from the book of four that the 5,000,000 and 6,000,000 blocks tested, so those blocks do not certify it and nothing is carried over from them: the reduced family needs its own pooled replication. The earlier blocks inform the choice to drop M3 and are not part of any pool. The reduced family's pass is decided only by the pool below.

Declaration, before the run. The whole battery of the reduced family (all eight cells, six gating and two diagnostic, `daily_hostile_stress` and `daily_static_vol_stress`; no cell or arm picked) runs in two independent blocks, one driver call each, 2,000 simulations per cell, 12 workers, at one commit, the commit that lands the reduced family. `DECLARED_REPLICATIONS["daily_residual"] = (7_000_000, 8_000_000)` (block 1 first) is pinned in that commit. Seeds follow the driver's rule, base + 10,000 x cell + simulation: block 1 consumes 7,000,000 to 7,071,999 and block 2 8,000,000 to 8,071,999, disjoint from every base used before (0, 1,000,000, 2,000,000, 3,000,000, 4,000,000, 5,000,000, 6,000,000, 9,000,000 and 77,000,000) and from each other. Run once, never rerun for a pass.

Pass rule, unchanged. Per cell, arm and alpha, the rejections of the two blocks are summed (n = 4,000) and compared with the per-test 0.99 binomial bound at the pooled n: 233, 55 and 13 at alpha 0.05, 0.01 and 0.00167. The six gating cells report four arms (M1, M2, `reversal_21` and the book), so the gating tests are 6 x 4 x 3 = 72 (A3's family had 90). Computed with `scipy.stats.binom`, the per-test exceedance probabilities at n = 4,000 under a correct statistic are 0.0086, 0.0094 and 0.0088 at the three levels. Treating the 72 tests as independent (they are positively correlated, which lowers both figures), the expected number of exceedances is 0.64 and the probability of at least one is 0.48. This is a property of the per-test gate, recorded in todo 636, not a reason to loosen it. The pass is the pooled result, judged by `battery_pass.make_record`; the blocks are reported separately and neither is judged alone; no rule of the form "either block passes" or "the best block" is used; every block is spent whatever it shows. `bind_battery_pass.py` accepts exactly the bases (7,000,000, 8,000,000) in that order.

Failure rule. No automatic retry. A failure anywhere in the pool postpones the family and is not a verdict on the hypothesis; the two bases are spent; a further attempt, a change to the family, or any calibration question goes to the lead for a ruling and a new dated declaration before it runs.

Pre-registered? Yes. It is declared before the reduced family's battery runs, after seeing the pooled failure above; both are stated here.

## 2026-11-21d: Massive as a dividend coverage source for total-return panels (lead ruling, owner veto reserved)

Recorded before any counted run on a total-return panel that reads Massive coverage.

What changes. A total-return panel prices a symbol on a session only where its dividends are
known. Until now only Yahoo's coverage decided that, and Yahoo covers the 1,529 names that were
live when it was asked, so every dead member of the stage 2 universe was NaN and a total-return
test ran on survivors. From this entry the research reader takes a session's dividend facts from
one source, first match wins: Yahoo where its span covers the session (the reconciled Yahoo and
IBKR facts, unchanged), else Massive where its claim (`massive-dividend-coverage-v1`, migration
608, `docs/plans/2026-11-21-massive-dividend-coverage-rule.md`) covers it and no gap of the claim
holds it. A Massive yield is the raw cash amount over the stored raw prior close; every Massive
event is unconfirmed (one source), so `suspect_yield` splits the name at one above it, as at any
one-source event; an event declared after its ex-date leaves its session unknown; a covered
session after a hole inside coverage starts a new segment, so no return window spans unknown
dividends.

The coverage claim. A Massive claim runs from a name's first stored ex-date to its last plus
0.75 payment intervals (capped at 400 days, the capture date 2026-11-10 and the end of the
name's last ticker span), minus cadence holes (gaps over 1.5 intervals), the days between ticker
spans and the ex-dates the writer could not store. Phase A measured it against Yahoo on live
names (0.099% silent misses, spin-offs the material class) and against the price drop on dead
names (no excess of unlisted dividend-sized drops); the dry run claimed 14,295 names and 52,296
member-years, 36,339 of them dead. Measured on the real first counted panel (`daily_residual_h5`, snapshot rebuilt at `06d016a78`, 12,245 names): total-return coverage rises from 23.1 to 59.7 percent of member cells (18,930,885 cells); names with any coverage from 1,267 to 6,700 (member names 6,162 of 11,684); of 85,265 member-years, 51,423 have any covered member day and 43,651 are covered on every member day. The old per-year count was not kept, so the member-year gain is not stated; the cell share is the comparison. The Yahoo event count is unchanged at 53,277 (Massive adds 230,932 events over 6,529 symbols, with 10,534 gap rows in the manifest); array identity with the pre-load snapshot was not checked, because that snapshot was deleted, and is covered by the bit-for-bit test on Yahoo-only names.

Disclosed residuals.
- Survivorship. A dead member Massive lists no dividend for gets no claim and drops out of a
  total-return panel: 4,738 dead members with no coverage at all on the loaded coverage (and 554 active names, which a total-return panel also drops). Dead non-payers are under-represented in total-return panels; a price-only panel
  of the same spec keeps them.
- Non-cash distributions. Massive carries cash only. A spin-off or return of capital in a
  Massive span stays in the prices as a loss. No price-based guard: on the Yahoo-covered names,
  98% of overnight drops above 10% (6,119 of 6,241 in 6,406,077 sessions) fall on no ex-date,
  so a guard would split dead names at their earnings and news gaps and remove their crash
  returns from the targets. The event-explained rate on live names, about 1.9 per 100,000
  sessions, is an upper estimate of the missed class.
- Look-ahead. Coverage never passes the capture date and no stored event lies after it; an
  event declared after its ex-date is not applied at that ex-date.

Unchanged. A name with only Yahoo coverage keeps its per-session dividend arrays bit for bit
(tested); the snapshot manifest now records the coverage sources and the Massive lineage, so
snapshot hashes move. `repro_frozen`: bit-identical at the landing commit. E17 battery code keys
unchanged: daily residual `3632233bc6102594ed8f275b091de107c240bf1d3dc19d1f50807e99a187b320`,
seasonality `ae9ff30d86e27d1b3c64e71a18e3c5258fd731dc4d0e1068e892254011f67d40` (the reader
modules are outside both import closures). The feature factory and the reconciliation audit read
only the Yahoo and IBKR sources, with output unchanged; a CI test refuses any new unfiltered
`dividend_events` read.

Pre-registered? Yes: the precedence, the yield, the unconfirmed rule, the declared_on rule, the
hole split and the no-guard decision are fixed in code and in the design note before any counted
run reads Massive coverage.

Correction to 2026-11-21d, same day (the entry is append-only, so the correction is appended). The residual disclosed there as "4,738 dead members and 554 active names with no coverage" was mislabelled by an analysis script that took column labels from the manifest universe (12,626 symbols) instead of the panel's own 12,245. With the right labels, 5,292 member names have no covered day, all of them dead; no active member is uncovered. Of the 5,292, 5,192 have no dividend event, coverage row or gap row (non-payers or names neither source saw), 96 have events and coverage rows but no covered member day (under review, no reader bug found yet) and 4 have a coverage row and gap rows only. The coverage shares and member-year counts in the entry are index-based and unchanged.

## 2026-11-21e: 1d member verdicts for inactive members, judged to the span the compute can read (lead ruling, owner veto reserved)

Recorded before the 1d corpus rerun and before any counted test, after seeing the dry-run counts below.

Gate rule. The `d2_landed` pin gate requires a fresh passing 1d verdict for every universe member, and 4,513 inactive members (11,348 inactive members in all) had no capture after the Massive archive end, so judging them to the last completed session failed `freshness_1d` and `session_coverage` on a tail nobody serves (a 1-in-40 sample of 322 members failed 108 and 94 before the rule). A one-shot (`scripts/ops/bars/ops_member_verdicts_1d.py`) now writes the nine 1d verdicts for every `universe_membership` symbol with the nightly audit's own judgement and writer. An inactive member is judged to the earliest of three ends: the month-end of its last effective month (a row at as_of is effective for the following month, migration 597), the day before the archive end pin, and its last stored 1d bar. An active member is judged to the last completed session, unchanged. `judge_name_1d` also clips `session_coverage` to a listing end, as `freshness_1d` already did.

What the clip does and does not prove, stated plainly. The last-stored-bar end makes `freshness_1d` vacuous for a dead member by design: its data stops, and a stale tail of a name with nothing served after its last bar is not a defect. `unexplained_seam` is vacuous for these members too: the seam read covers only the recent lookback, and a dead member's bars are all older. The proof that carries for them is `session_coverage` inside the span, `canonical_recompute` and `digest_fresh`, which still read every stored bar and every raw observation (canonical equals the d2 recompute of raw, month digests current), plus `policy_conformance`, `lineage_missing` and `split_continuity`. Historical seam defects in dead members rest on the A3 strict sweep alone (a recently dead member can still get a real seam verdict). Two more gaps, disclosed with counts: `session_coverage` anchors at the proven start, so a dead member with a large early hole passes when the span from its proven start to its last bar is dense, and the compute reads the membership years inside that hole as NaN under no_fill (the proven start is an info row, not a required check, and 2026-11-21b records its effect). The last-bar end also hides a tail truncated before the true end: of 11,348 inactive members, 2,767 have their last bar more than 10 days before the judged end and 211 more than 31 days (none beyond 92), consistent with a delisting inside the last effective month; raw holds nothing there, so `canonical_recompute` cannot see it, and the 211 are not chased. An inactive member can fail `canonical_recompute` on a bar after its judged end; that is conservative, not masking.

Result of the full dry run over 12,857 members (167,141 rows, 56 minutes): digest_fresh 18, session_coverage 11, split_continuity 7, unexplained_seam 6, freshness_1d 2; nothing else failed. Disposition by materiality. digest_fresh (HAS, IEF, MBB, MCHI, IGF, MPB, ONB, PFF, SHY, TUR, CMPR, IEI, WDAY, FCFS, OLED, RSPR, SCZ, TLT, all active; 28 stale months on the ETFs): fixed, a daily-stage `--rewrite-digests --apply` over those 18 names wrote 281 digest rows, no bar changed. unexplained_seam (ACIW, AGL, RCAT, SNEX, TROX, WSM, seams 2026-11-17 to 2026-11-19 on Alpaca bars; WSM and TROX read directly: real earnings or distress moves on heavy volume, one bar each): disclosed, not a defect; the check reads a recent window and clears as it ages out. freshness_1d (BKH, NWE, active, 5 sessions behind): disclosed, no fix. session_coverage (ACQR, CEP, DKA, ENGN, GGOV, KWT, PACQ~1726293, PRE, RRF, STNL, WTRE, all inactive; shares from 0.43 to 0.997): vendor-side holes inside the history, the class of the POWI named exceptions in 2026-11-21b; listed, not repaired. split_continuity (HON 2026-06-26, MHH 2013, DRIP 2020, VIP 2004, ACGN 2018, CETV 2003, ETS 2005, all `double_adjusted`): real split-shaped findings, not repaired by this entry; HON (active, the Aerospace separation with a 1-for-2 reverse split, todo 633) is the one inside the recent panel and needs its own corporate-action ruling. These names keep their failing verdicts; the gate is not weakened for them.

Pre-registered? The rule is decided before the corpus rerun and any counted test, after the dry-run counts above; the lead rules it right on the grounds given, and the owner keeps the veto.

## 2026-11-21f: d2_landed holds and the 26 failing names (lead ruling, owner veto reserved)

Amends 2026-11-21e. Recorded before the 1d corpus rerun and any counted test, after the full member verdict run left 26 names failing (digest_fresh was repaired first, 18 names, 281 digest rows, no bar changed).

Gate rule. `d2_landed` now excuses a 1d verdict that is judged and failing when the pinned APR list `infra.corpus_rerun.d2_landed.held_verdicts` (migration 609, a JSON list of {symbol, check, evidence}) names it, and the pin gate result lists every held verdict with its evidence. A missing or stale verdict is never excused, an entry needs written evidence and a known check name, and the list joins every run's apr_hash. No verdict was weakened: each held name keeps its failing verdict row.

Fixed, not held. HON 2026-06-26 (1-for-2 reverse split after the Aerospace separation, todo 633): the row records the day's real move (calendar_adjusted_step -0.7123, the separation) and canonical's step across the date is that same move, so the verdict read it as a double adjustment because the move (-0.71) is about the split's own ratio (ln 2 = 0.69). Verified by level: canonical closes 462.48, 464.42, 227.80, 223.90 are the Alpaca split-adjusted series, continuous apart from the real move. `split_discontinuities` and `split_record` now net the recorded real move for every split row, not only calendar_audit rows with rescale routes; this changes no bar and no recorded split. NWE: merged into Black Hills (renamed Bright Horizon Energy, HZN) on 2026-11-16, no bar after 2026-11-13; a `listing_end` row (reason merged, last session 2026-11-13) is seeded in migration 609, so its freshness is judged to the last session. The Form 25-NSE accession is not recorded; the evidence is the company release and the vendor tape.

Held, with the evidence in the APR list (24 entries). split_continuity 6: MHH 2013 and DRIP 2020 (Yahoo-matched splits, canonical level-continuous, the step coincides with the split product because the real move was +16 and +19 percent); VIP 2004, ACGN 2018, CETV 2003, ETS 2005 (the Massive reference row is dated one or two sessions off the vendor's own tape, Yahoo lists nothing, so one or two canonical bars per name sit on the wrong scale; all inactive; the correction path needs a tape-only witness mode that does not exist, and one or two returns in four dead names are below the materiality line). unexplained_seam 6: ACIW, AGL, RCAT, SNEX, TROX, WSM (real earnings or distress moves on 3 to 8 times normal volume, steps -0.108 to -0.382, no recognised split ratio; they leave the seam lookback within days). session_coverage 11 (ACQR, CEP, DKA, ENGN, GGOV, KWT, PACQ~1726293, PRE, RRF, STNL, WTRE; all inactive; canonical holds every day of the raw series, so the missing sessions are days the vendor serves no bar). freshness_1d 1: BKH, a symbol change to HZN on 2026-11-16 (a symbol change is not a listing end); held until HZN is onboarded.

Pre-registered? Decided before the corpus rerun and any counted test, after the failing set was known; the lead rules it right on the materiality grounds above, and the owner keeps the veto.

## 2026-11-21g: data gate holds for the 1d-first run after the d2 apply (lead ruling, owner veto reserved)

Amends 2026-11-21b. After the d2 member verdicts applied (2026-11-21e, 2026-11-21f) the plan-only data gate at scope 1d on 7e34a8e55 failed where the stored verdicts of runs e8f95b33 and 252928d9 had passed: 21 failing name-years over 12 names, 11 names without a proven start, 36 members before their proven start (587 before). Nothing in the gate rule, the 5 percent residual constant or any tolerance changes. Two named lists change, both pinned in the APR hash, set after seeing the result (said plainly).

What changes. (1) `infra.corpus_rerun.data_gate.held_name_years` gains the 21 name-years, 23 entries with the two POWI years (migration 610, version 1 to 2): ADTX 2021, 2023, 2024; CNSP 2021; EZGO 2021, 2023; GASL 2012, 2014; GNLN 2021; INTM 2025; KXIN 2022; LGHL 2021, 2022; NSPR 2013, 2014; TANH 2017, 2018, 2020; TOPS 2018, 2019; VCIG 2024. (2) New key `infra.corpus_rerun.data_gate.held_names`, a JSON list of {symbol, evidence}: a name with no proven start that is listed is neither judged nor refused and the result reports it (`held_names_by_list`). It excuses nothing else (a start with no sessions, or zero 1d sessions, still refuses). Seeded with ACQR, CEP, DKA, ENGN, GGOV, KWT, PACQ~1726293, PRE, RRF, STNL, WTRE.

Evidence, held name-years. In each, the 1d table holds a bar for every session (for example ADTX 2021: 252 bars, 136 with volume above zero, 116 with zero volume) and the missing count equals the zero-volume days: illiquid micro-caps with no-trade days, not archive holes (Massive raw equals canonical). 1,745 of 3,786 judged sessions in these 21 name-years are zero-volume; compute applies no_fill, so they are NaN and cannot bias a return. 23 held name-years of roughly 190,000 judged (0.012 percent). Per name-year counts are in the APR list.

Evidence, held names. The 11 names are inactive, their latest `proven_start_1d` fact failed (the latest session is unanswered because the vendor serves no bar) and d2_landed already holds their session_coverage verdicts (2026-11-21f); canonical equals the Massive raw series. They carry 202 of 1,042,561 member months (0.019 percent; PRE alone 150, 2003-12 to 2022-12). Correction to a premise of the ruling: the compute does not skip a name without a proven start; `backfill_feature_factory` reads it from the start of its series (`NO_FLOOR`) with warmup masked and missing sessions NaN. The research panel reads member years only.

Proven start, verified not an artefact. Of 551 names whose latest `proven_start_1d` fact moved earlier since the first gate records, a sample of five was checked against the bars: LSGR 2023-12-20 to 2023-06-30 (93 tradeable bars between), SNG 2009-05-06 to 2003-09-10 (1,384), MXT~1113306 2014-11-12 to 2007-10-31 (1,543), VINC 2025-04-21 to 2020-12-31 (1,077) each start equals the name's first tradeable bar and the bars between are dense; the fifth, TLTD, moved two days later (2012-10-03 to 2012-10-05), noise. The d2 clip no longer lets a sparse tail push the start past the dense history, the intended effect. The pilot's proven-start disclosure now counts 36 names (was 587).

Pre-registered? No: decided before the corpus rerun and before any counted test, after the failing set was known; the lead rules it right on the materiality grounds above, and the owner keeps the veto.

## 2026-11-22: the E21 clean-data lift for the price-derived 1d families (owner ruling, confirmed in the lead's session)

Recorded before the first counted run of the daily residual family and before any real-data number for it.

Ruling. The owner confirmed on 2026-11-22: lift the E21 clean-data rule for the price-derived 1d families, on the lead's recommendation. Scope: the 1d families that read canonical 1d and `universe_membership` through the panel (the daily residual family of todo 636, and later families of the same kind). Not lifted: the 27 `compute_eligible_1d = false` names and the entity classes stay excluded and wait on the owner; every feature-vector and intraday family still needs its own gate.

Grounds. The scope-1d data gate passes with a pinned held list (ledger 2026-11-21b and 2026-11-21g); the `d2_landed` gate passes for all 12,857 members with 24 pinned holds (2026-11-21e, 2026-11-21f); the dividend source covers 59.7 percent of member cells on the panel (2026-11-21d); the E17 battery pass for the reduced family is bound on seed bases 7,000,000 and 8,000,000 (2026-11-21c). Every remaining defect is disclosed with its class counts under the 2026-11-20 materiality rule. The 1d-first corpus run stopped at its pilot feature screen (todo 652); the daily family does not read `feature_vectors`, so that failure does not touch it.

What it permits. `scripts/research/run_spec.py` on `research/specs/daily_residual_h5.yaml` and then `daily_residual_h5_core.yaml`, each counted through the ledger at the moment it starts, six looks under A4, then the `reversal_21` pooled replication. It changes no spec hash, statistic or gate.

Pre-registered? Yes: the rule, the scope and the exclusions are stated here before any real-data number exists.

Lead ruling under the 2026-11-22 E21 lift, same day: the H-C seasonality family (4 looks, E17 pass bound in `research/battery_passes/seasonality_2026-11-21.json`) is a price-derived 1d family of the same kind and is covered by the lift; it runs after the daily residual run frees the heavy slot. Any later family is covered only if it reads canonical 1d and `universe_membership` through the panel and nothing from `feature_vectors` or intraday bars; a family that does not fits that test needs its own ruling. Owner veto reserved.
