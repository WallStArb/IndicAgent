# Lookahead Gradient and Return-Target Calibration - Review of Todos 091/097 Residuals

**Version:** 1.0
**Status:** answered - all three questions resolved with live evidence; recommendations are
calibration/sequencing calls, not a redesign proposal
**Priority:** high (Q1's coverage finding is a measurement-integrity gap in the same class Phase
143.1 exists to fix; Q2/Q3 gate how todos 091/097 get closed)
**Milestone:** none - informs Phase 143.1 Plan 07 sequencing and the next corpus rebuild
(post-Phase 162)
**Last Updated:** 2026-07-19
**Tags:** ic-engine, lookahead, forward-returns, bootstrap-ci, vol-normalized-target,
component-f, todo-091, todo-097
**Source:** same-day session handoff (091 confirmation run, Component F sampled A/B); every claim
re-verified independently against live code and DB 2026-07-19 - Author: Fable 5

**What was independently verified this review (not taken from the handoff):**

1. APR: `alpha.ic.lookahead.{fast,mid,slow,extended} = 1/5/20/60`, all `[initial_estimate]`, all
   marked ML learning targets never learned (`config_state`/`config_schema` join, live).
2. No tf-scaling of lookaheads anywhere: `ICEngineConfig.from_apr` (`services/ic_engine.py:537-540`)
   loads one flat dict; `forward_return_writer.py:479-483` loads the same keys once and
   `_build_forward_return_sql(lookaheads, tf)` uses `tf` only for the intraday same-ET-date
   completeness gate, never to scale bar counts. Contrast: `_tf_window()`
   (`src/intelligence/regime_signals/tf_window.py`, `_BARS_PER_DAY = {1d:1, 1h:7, 15m:26, 5m:78}`)
   does scale day-denominated windows per tf, and the bootstrap block sizes
   (`alpha.ic.bootstrap_block_size.{5m,15m,1h,1d} = 78/26/10/10`) are also tf-differentiated
   (roughly one trading day for intraday). The lookahead grid is the one remaining un-scaled
   temporal parameter family in the measurement layer.
3. `_circular_block_bootstrap_ic` is unconditionally live at all three CI call sites
   (`ic_engine.py:1093`, `:1369` serial per-symbol paths; `:1963` cross-sectional), no flag gate.
   `alpha.ic.bootstrap_resamples=2000`, `bootstrap_seed=42` (live APR).
4. 091 confirmation-run numbers (21% SUSPECT, 4/19, `ctf_momentum` x3 + `flight_quality`/VWO/1h,
   all `is_pooled=false`) match the committed record in
   `.planning/todos/pending/091-fisher-z-ci-empirical-null-miscalibration.md` (commit `f1574d0b`).
5. Component F 1d slice independently re-run this review
   (`ops_vol_normalized_target_ab.py --tf 1d --max-regimes-per-tf 2`, vintage
   `2025-12-24 05:15:00+00`): 8/8 strata evaluated, median rank corr 0.5964, and
   `1d/high_bull/extended(60)` reproduced as the extreme outlier at **-0.0400** (every other
   stratum 0.41-0.83). The handoff reported -0.0948 for the same stratum from its default-mode
   run; the exact value differs but the qualitative claim (that one stratum is ~zero, far below
   all others) reproduces. Neither run's output was previously committed anywhere; this doc is
   now the durable record of the reproduction.
6. New measurements run for this review: `forward_returns` completeness rates per (tf, scale),
   `feature_ic_scores` cell coverage and `n_independent` per (tf, lookahead), and autocorrelation
   decay lengths of the SUSPECT features vs. their bootstrap block sizes (all below).

---

## Q1 - The lookahead gradient (1/5/20/60 uniform across tfs)

### (a) Verified: uniform bar-counts are a real design smell, and worse than "inconsistent economic horizons"

The handed-off framing (60 bars = 5 hours on 5m vs ~3 months on 1d) is correct but understates
the problem. The uniform grid collides with `forward_return_writer`'s intraday same-ET-session
completeness gate (a deliberate, correct gate - overnight gaps are untradeable for intraday
entries per Invariant 1) and **structurally amputates or biases a third of the design grid**.
Measured live from `forward_returns` (`return_type='executable_open_to_open'`):

| tf | fast(1) | mid(5) | slow(20) | extended(60) |
|----|---------|--------|----------|--------------|
| 5m (78 bars/session) | 0.972 | 0.917 | 0.713 | **0.196** |
| 15m (26 bars/session) | 0.920 | 0.762 | **0.182** | **0.000** |
| 1h (7 bars/session) | 0.689 | **0.077** | **0.000** | **0.000** |
| 1d | 1.000 | 0.999 | 0.995 | 0.985 |

(completeness fraction = share of bars with a valid same-session forward return)

Consequences, confirmed in `feature_ic_scores` cell counts:

- **1h is effectively a fast-only timeframe.** slow/extended have zero rows anywhere in the
  table; mid survives at 7.7% completeness, meaning essentially only the first bar of each
  session - a severe time-of-day selection bias on what little remains.
- **15m has no extended horizon at all**, and slow is measured only on the first ~5 bars of the
  session (18.2%, predicted 5/26 = 19.2%).
- **5m extended is measured only on first-~90-minutes bars** (19.6%, predicted 17/78 = 21.8%).
  This one is the silent-wrong-answer case: rows exist, gates run on them, but the measured
  population is "morning entries only" while nothing downstream knows that.
- **1d extended collapses effective N**: `n_independent` averages 372-451 per POOLED regime cell
  (stride=60 subsampling on top of regime slicing), fdr pass rate 0.83% vs 3-14% at shorter
  horizons.

The empty cells fail loud-ish (missing rows); the biased cells fail silently. Per this project's
own principles doc, the silent ones are the worse defect. The codebase already recognizes that
day-denominated temporal parameters must be tf-scaled (`_tf_window()`) and that temporal
dependence is tf-specific (per-tf bootstrap block sizes); the lookahead grid is the inconsistent
holdout. Verdict on (a): **yes, design smell, confirmed empirically, not adequate to carry
indefinitely as-is** - not because 1/5/20/60 are bad numbers on 1d (they are fine there), but
because "one grid for all tfs" makes three of the four tfs measure a different and partly
degenerate design than the one the naming implies.

### (b) The Component F worst-stratum connection: corroborating, not load-bearing

The `1d/high_bull/extended` rank-correlation collapse reproduces independently (-0.0400 this
review), so it is not a fluke of one run. But the parsimonious explanation is effective-N
attenuation, not a special raw-vs-vol-normalized disagreement at long horizons: at ~372
independent observations per cell, per-feature IC estimates are noisy, and the Spearman
correlation between two noisy rankings attenuates toward zero mechanically. Both 60-bar 1d
strata also have near-empty qualifying sets (raw_only 4/1, both=0). Note `1d/high_bear/extended`
came out at 0.5470 in the same run, so "divergence concentrates at extended" is really
"measurement resolution collapses at extended, so the A/B reads noise there." Treat it as
corroboration that the extended horizon is the least-trustworthy corner of the grid, which the
coverage/N data above establishes independently and much more strongly. It is not, by itself,
evidence that the horizon choice distorts the vol-normalization verdict elsewhere.

### (c) Calibration shape and sizing

The existing 4-point horizon curve in `feature_ic_scores` already says something: fdr pass rate
peaks at mid(5) on every tf (5m 11.6%, 15m 13.9%, 1d 9.5%) - but pass rates confound signal
with statistical power (stride and N fall mechanically with lookahead), so this motivates a
diagnostic rather than settles anything.

**Step 1 - horizon-response diagnostic (todo-sized, ~1-2 days).** A read-only ops script in the
house style of `ops_ic_null_calibration.py`: compute POOLED IC across a dense per-tf horizon
grid denominated in session-feasible bars (e.g. 5m: {1,3,6,12,26,39,66}; 15m: {1,2,5,10,22};
1h: {1,2,4,6}; 1d: {1,2,5,10,20,40,60,90}), using the same LEAD-based executable open-to-open
construction `_build_forward_return_sql` uses, on a stratified sample of regimes. Report IC
magnitude and CI width separately (so power and signal are not conflated). Output: per-tf IC
decay curves; decide per-tf grids where the curve, not a guess, puts fast/mid/slow/extended.
This is the APR-lifecycle step the key descriptions themselves promise ("ML learning target:
IC horizon calibration") - it has simply never been run.

**Step 2 - one design decision inside that todo.** For intraday tfs, the same-session executable
constraint caps the max horizon at one session. Either (i) accept session-bounded per-tf grids
(1h's "extended" is ~6 bars, and that is honest), or (ii) define an overnight-inclusive return
type for intraday extended horizons. Recommend (i) unless Step 1 shows IC still rising at the
session boundary; (ii) is a new return_type and a Component-F-adjacent target-definition change,
not a parameter tweak.

**Step 3 - apply at the next corpus rebuild (rides Phase 162, pre-registered in the methodology
ledger).** The gradient-naming design already paid for this: `forward_returns` columns are
scale-named, `feature_ic_scores` stores `lookahead_bars` explicitly, and
`_build_forward_return_sql` is already invoked per tf - making the APR keys per-tf (or a JSON
per-tf grid) requires no schema migration. Do not trigger a corpus rebuild for this alone;
bundle it exactly the way Component F rode 143.1.

Overall Q1 verdict: **prioritize the diagnostic now (P1 todo), apply the grid change at the next
scheduled rebuild.** The 1h/15m dead cells mean the ensemble's training population is currently
lopsided toward 5m/1d at the slow/extended scales, and nobody decided that on purpose.

---

## Q2 - 091 residual: `ctf_momentum` block-size mismatch

The targeted investigation the todo deferred is, as of this review, essentially done - it was a
bounded empirical question ("measure, don't defer"), so this review measured it. Autocorrelation
decay of the SUSPECT features vs. their tf's bootstrap block size (last 60k bars per series,
live `feature_vectors`):

| feature | cell | 1/e decorrelation lag | integrated autocorr time | block size |
|---|---|---|---|---|
| ctf_momentum | XLY/5m | 150 bars | ~300 bars | 78 |
| ctf_momentum | EWJ/5m | 169 bars | ~300 bars | 78 |
| ctf_momentum | QQQ/15m | 52 bars | ~104 bars | 26 |
| flight_quality | VWO/1h | 5,678 bars | ~7,454 bars | 10 |
| momentum_z_fast (control) | SPY/5m | 4 bars | ~5 bars | 78 |

The mechanism is confirmed, cleanly: every residual SUSPECT cell is a feature whose dependence
length exceeds its block size by 4x (`ctf_momentum`, consistently ~4x across tfs - it is built
from HTF momentum, so this is structural, not incidental) to ~750x (`flight_quality`, a TLT/SPY
macro divergence that decorrelates on a months scale). The control shows why the other ~79% of
cells calibrate fine. (Caveat: these are raw-feature-series measurements, not the strided IC
observation stream the bootstrap actually resamples; stride shrinks but does not remove the gap,
and the calibration script's empirical null is the authoritative instrument. Directionally this
is decisive.)

**Recommendation: do not close 091 as "acceptable residual," but the remaining work is todo-sized
flagging, not machinery reopening.**

- Against "proof before promotion": these features' per-symbol CIs are too narrow, so they pass
  gates more easily than their evidence supports - exactly the failure mode the principle
  exists to prevent. Carrying 21% unflagged would be carrying known gate inflation on named
  features.
- Against "resist overfitting": the wrong fix is per-feature block-size tuning. For
  `ctf_momentum`, block ~= integrated tau (~300 on 5m) is feasible (60k obs / 300 = 200 blocks)
  and worth considering at the next rebuild; for `flight_quality` at 1h, no feasible block size
  rescues the CI (~4 independent blocks of 7,454 bars in ~30k obs) - the honest statement is
  that such macro features have almost no independent per-symbol observations at intraday tfs,
  and no resampling scheme conjures them.
- Against "instrument everything": the right close-out is a dependence-length diagnostic - measure
  integrated tau per (feature, tf) once per corpus run, write a lower-trust flag (natural home:
  `feature_registry` lifecycle state or an `integrity_monitor` fact, same pattern todo 144 uses
  for the guard band) whenever tau materially exceeds block size. That converts a one-off
  finding into standing instrumentation, and it doubles as the low-tail counterpart 091's
  finding already motivated in todo 144's design.

So: 21% residual is acceptable to carry **only with the flag in place**; with it, 091 can close
with a follow-up todo (diagnostic + flag + optional 5m/15m block-size revisit at the next
rebuild, pre-registered in the methodology ledger). Also honor the todo's own caveat: this run's
skip rate (49/68) means the 21% headline sits on 19 cells; the targeted stratified sample over
`ctf_momentum`/`flight_quality` cells it proposes is cheap and should ride the same follow-up.

---

## Q3 - Component F sequencing

### (a) Fix the FDR-family mismatch in the diagnostic first - it is trivially cheap relative to what it gates

The rank-correlation result (median ~0.60-0.64 across both today's runs; "real partial
agreement") is the pre-registered primary metric per ledger entry E8's locked contract
("if rankings are materially identical, retire"), and it alone justifies proceeding to the
definitive run: rankings are clearly not identical, so the transform carries information the raw
target does not. But the qualifying-feature-count comparison as currently coded (production
corpus-wide BH family vs. this script's per-stratum families) is not evidence in either
direction - the 12x `vol_only` disparity (51/611/127 in the session's run; 35/184/44 in this
review's 1d slice) is inflated by the weaker per-stratum correction, exactly as the script's own
docstring states. Since the `--all-regimes` run is multi-hour, corpus-scale (script's own scope
note), and its stdout is the verdict-of-record appended to ledger E8, spending it on a report
whose secondary metric is known-incomparable would waste the run. The fix is small: pool the
script's own freshly computed p-values across all evaluated strata into one BH family for the
vol side (mirroring production's one-family convention) before the `--all-regimes` invocation.
Add per-stratum `n_independent` to the report at the same time (next point). Then greenlight.

### (b) The entanglement: real but resolvable by conditioning, not sequencing

The coupling exists and has a specific mechanism: the uniform 60-bar horizon collapses effective
N on 1d (and admits only session-truncated, morning-biased populations on 5m), so extended-horizon
strata are the lowest-resolution cells in the A/B - the -0.04/-0.09 stratum is what an A/B
read through ~372 observations looks like. But full sequencing (calibrate horizons, rebuild the
corpus, then run Component F) buys almost nothing for its cost: the well-populated strata
(fast/mid everywhere, slow on 5m/1d) dominate the verdict and are essentially unaffected by
where the horizon grid sits, and the vol-normalization question (what the return target is
divided by) is approximately orthogonal to the horizon question (how far ahead it is measured)
wherever measurement resolution is adequate.

**Recommendation: run Component F's full-corpus verdict now (after the (a) fix), with the verdict
conditioned on stratum reliability** - flag or exclude strata below an `n_independent` floor
(the structurally broken cells from Q1's table: 1d/extended, everything intraday
slow/extended-adjacent) from the keep/retire aggregation, and say so in the E8 addendum. If the
lookahead grid later changes at the post-162 rebuild, the A/B script is cheap to re-invoke
against the rebuilt corpus as a confirmation pass; the expensive artifact (the corpus) gets
rebuilt then anyway. Strict sequencing would be an overread of one noise-dominated stratum;
ignoring the coupling entirely would repeat the silent-population mistake Q1 documents.

---

## Recommended order of operations

1. **Now:** fix the A/B script's vol-side FDR family (one pooled BH family across the run) and
   add `n_independent` per stratum to its report. Then run `--all-regimes` for the definitive
   Component F verdict, conditioned on stratum reliability; record as the E8 addendum.
2. **Now (parallel, todo-sized):** file and run the lookahead horizon-response diagnostic
   (Q1c Step 1-2). File the 091 follow-up (dependence-length flag + targeted
   `ctf_momentum`/`flight_quality` stratified calibration sample); close 091 when the flag
   lands, recording the decision in the methodology ledger.
3. **Next corpus rebuild (post-Phase 162):** apply per-tf lookahead grids (APR-only change,
   pre-registered), optionally revisit 5m/15m block sizes toward integrated-tau scale in the
   same pre-registration.

Nothing here proposes new machinery beyond one diagnostic script, one report fix, and one
standing flag - the grid change itself is an APR value change the gradient-naming design
explicitly reserved the right to make.
