---
**Created:** 2026-07-11
**Updated:** 2026-07-13 — **IMPLEMENTED.** Fable sign-off obtained (Decision A: GO on the
fixed-subsampled-window estimator fix with a new APR key, w=100, mandatory threshold rescale;
Decision B: keep hold_max_bars as an independent APR family, re-derive empirically post-fix —
see "Decision (2026-07-13, Fable sign-off, implemented)" section below for full detail).
Estimator fix + threshold rescale shipped via migration 230 + code changes across
`ic_math.py`/`ic_engine.py`/`ensemble_ic_engine.py`/`ensemble_trainer.py`/
`feature_registry_service.py`/`feature_selector.py`, TDD'd (2 new stride-invariance tests in
`tests/unit/test_ic_sharpe_stride_invariance.py`), full `tests/unit/` suite green. **Remaining
work, not yet done:** the full corpus re-run (ic_engine -> ensemble_trainer reweight ->
ensemble_ic_engine decay walk) needed to re-derive every historical ic_sharpe/hold_max_bars
value under the corrected estimator — this is a data/operational step, not a code change, and
is the next actionable item before 088 (per the locked sequencing) can proceed.
**Updated:** 2026-07-12 (three passes) — v1 found a mismatch and mis-attributed it; v2 corrected
the attribution to a specific stride/window-density hypothesis; v3 (below) **quantitatively
confirms** the hypothesis via Monte Carlo against the real production function
**Area:** intelligence
**Type:** correctness / methodology — corpus-wide measurement bias, not a data quality issue
**Priority:** P0 — confirmed, quantified, corpus-wide bug in the `hold_max_bars` calibration
mechanism; every EIC-02-confirmed cell (11/36) and every future confirmation is affected until
fixed
**Effort:** S for the diagnostic (done, script committed); M-L for the fix — touches a function
shared by `ic_engine.py` and `ensemble_ic_engine.py`, requires full corpus recalibration after
**Benefit:** Removes a systematic bias that has been silently truncating `hold_max_bars` far
below the ensemble's genuine capturable horizon corpus-wide, plausibly explaining todo 093's
77%-timeout FRAME-04 failure independent of any frame-construction issue
**Risk:** low for the diagnostic (read-only, synthetic data only); the fix itself is
higher-effort/higher-blast-radius, flagged below for explicit sign-off before implementing
---

## Finding v3 (2026-07-12) — CONFIRMED via Monte Carlo, not just plausible

Built `scripts/analysis/ic_sharpe_stride_bias_check.py`, which imports the actual production
`_compute_ic_rolling_metrics` (`src/intelligence/statistics/ic_math.py`) — not a
reimplementation — and feeds it synthetic (X, Y) pairs with a **fixed, known, non-decaying**
Spearman rank correlation (Gaussian copula), subsampled at the real live-APR strides
(`fast`=5, `mid`=5, `slow`=20, `extended`=60, from `alpha.ic.lookahead.*` /
`alpha.ic.subsample_min_stride`), each replicated 150 times per rho at `sharpe_window_size=2000`
raw bars / `sharpe_min_windows=30` (live `alpha.ic.sharpe_window_size` /
`alpha.ic.sharpe_min_windows`).

Because the true correlation is held **constant by construction** across all four strides, any
systematic difference in measured `ic_sharpe` across scales is pure estimator artifact, not real
decay. Result, at three realistic signal strengths:

| true rho | fast (stride 5) | slow (stride 20) | extended (stride 60) | fast/slow ratio | fast/extended ratio |
|---|---|---|---|---|---|
| 0.03 | 0.587 | 0.291 | 0.173 | 2.02 | 3.39 |
| 0.06 | 1.203 | 0.595 | 0.342 | 2.02 | 3.52 |
| 0.10 | 2.034 | 1.007 | 0.567 | 2.02 | 3.59 |

**The observed ratios match `sqrt(window_size_fast / window_size_X)` almost exactly**
(fast/slow predicted = sqrt(400/100) = 2.00 vs. observed 2.02; fast/extended predicted =
sqrt(400/33) = 3.48 vs. observed 3.39-3.59). This is the textbook signature of a per-window
sample-size effect, not signal decay: `sharpe_window_size = sharpe_window_size_raw // stride`
keeps window **count** stride-invariant by design (documented intent), but each window's
subsampled **point count** shrinks with stride (400/400/100/33 for fast/mid/slow/extended at
current APR values) — smaller windows produce noisier per-window IC estimates, which mechanically
inflates cross-window variance and deflates `ic_sharpe = mean(window_ICs)/std(window_ICs)`,
independent of whether the true relationship decayed at all.

**Consequence, quantified:** at true rho=0.03 (a realistic weak-factor magnitude), the fast-scale
signal clears `decay_threshold=0.1` with zero failures across 150 draws, while the exact same
signal at the extended scale falls below 0.1 in 30.7% of draws — purely from the stride-driven
window-shrinkage artifact. `_select_hold_bars_from_decay`'s walk-until-below-threshold logic
means this artifact **systematically truncates `hold_max_bars` short** for any signal whose true
strength sits anywhere near the threshold at longer horizons — which is exactly the regime this
corpus's real signals live in (weak factors, IC in the 0.01-0.05 range per the discovery report).

**This also gives 093's 77%-timeout finding a coherent mechanistic explanation, independent of
any frame-construction bug**: if `hold_max_bars` is biased toward 1-5 bars corpus-wide by this
artifact, `CounterfactualTracker`'s frames never have time to travel far enough to hit a
stop or target calibrated for a longer horizon — every frame is closed by the time-based exit,
which is definitionally a "timeout." The mechanism proposed in the original v1 concern (mismatched
hold vs. selection horizon) and this v3 finding (mismeasured decay) converge on the same downstream
symptom via different, now well-understood causal paths.

## Recommended fix (flagging for sign-off before implementing — wide blast radius)

Root cause: `sharpe_window_size` is expressed in **raw bars** and floor-divided by stride, which
keeps window count stable but lets per-window statistical power (subsampled point count) collapse
with stride. Fix: express the window size in **subsampled bars directly** (a fixed target, e.g.
same subsampled-point count at every stride) rather than deriving it from a raw-bar constant
divided by stride — this keeps per-window statistical power comparable across scales, letting
`sharpe_min_windows` (not the point estimate itself) be the thing that legitimately gates
longer-lookahead cells with less absolute data.

**Why this needs explicit sign-off, not a unilateral fix:**
1. `_compute_ic_rolling_metrics` is shared by `ic_engine.py` (per-feature IC Sharpe, feeds
   `passes_fdr`/`reliable`/eligibility gates corpus-wide) and `ensemble_ic_engine.py`
   (EIC-02's `hold_max_bars` calibration) — a fix here has a second, larger blast radius beyond
   just `hold_max_bars`.
2. Every historical `ic_sharpe`/`hold_max_bars` value ever computed under the current formula is
   suspect and needs re-derivation after a fix — this is a full corpus re-run, not a config
   tweak, and should be sequenced deliberately (likely alongside or after todo 091's bootstrap-CI
   corpus re-run, not as a third independent re-run).
3. Changing `sharpe_window_size` semantics changes the meaning of `alpha.ic.sharpe_window_size`
   itself — needs an APR description update and probably a distinct key
   (`sharpe_window_size_subsampled` or similar) rather than silently reinterpreting the existing one.

## Reproduce

`python scripts/analysis/ic_sharpe_stride_bias_check.py` — self-contained, synthetic data only,
no DB writes, ~10s runtime.

## Finding v2 (2026-07-12) — corrects the fix recommendation below, not the data

The v1 finding's data (the ratio table) is accurate, but its conclusion was wrong: it assumed
`hold_max_bars` *should* match the weighted-average `lookahead_bars` that `ensemble_weights`'
constituent features were individually *selected* at, and recommended coupling the two. That
premise doesn't hold up:

- `hold_max_bars` is supposed to reflect how long the **traded quantity** (the blended
  `ensemble_alpha` score) keeps positive expectancy — which is exactly what `_calibrate_hold_max_bars`
  / `_select_hold_bars_from_decay` in `ensemble_ic_engine.py` measures: `ensemble_alpha`'s own
  `ic_sharpe` decay across lookaheads, gated on `passes_fdr AND reliable AND walk_forward_stable`.
- A blended score's own decay curve has no obligation to match a weighted average of the
  individual horizons its *constituent features* were selected at — that's a category error, not
  a bug. Combination effects mean the ensemble's own edge can legitimately peak/decay on a
  completely different horizon than any single input feature's optimal lookahead.
- Checked whether the 11/36 rigorously-**confirmed** cells (real out-of-sample evidence, e.g.
  `low_bull.5m` derived from 56 qualifying symbols, `high_neutral.5m` from 11) still show the same
  short-hold pattern as the `[initial_estimate]` guesses — they do (`low_bull.5m`: hold=5 vs.
  weighted-avg selected lookahead=18.0; `high_neutral.5m`: hold=1 vs. 16.1). If this were just
  "some cells are still unvalidated guesses," confirmed cells should look nothing like the guesses.
  They look the same. **That rules out "just re-derive/couple it" as the fix** — there's a
  candidate real reason confirmed cells are also short.

**New, better-grounded hypothesis:** `_compute_ic_rolling_metrics` (`ic_math.py`) computes
`ic_sharpe` from non-overlapping rolling windows of `sharpe_window_size = sharpe_window_size_raw
// stride` **subsampled** bars each. Window *count* (`n_windows_possible = n // sharpe_window_size`)
is deliberately stride-invariant (the doc comment confirms this is intentional), but each
window's **data density** is not — at `stride=60` (extended lookahead) a window holds ~33
subsampled points; at `stride=1` (fast lookahead) it holds ~2000. A noisier per-window IC
estimate at long lookaheads inflates cross-window variance and mechanically deflates
`ic_sharpe`, independent of whether the true underlying signal has actually decayed. If real,
`_select_hold_bars_from_decay`'s walk-until-`ic_sharpe<0.1` logic would systematically truncate
`hold_max_bars` early for genuinely long-horizon signals — not because the edge is gone, but
because the sharpe *estimate* gets noisier as window sample density shrinks with stride.

**This is a hypothesis, not yet confirmed** — I traced the stride/window-count math far enough to
rule out the naive explanation and find a specific, plausible mechanism, but haven't run the
quantitative check (e.g., simulate/measure how much of the `ic_sharpe` drop at long lookaheads is
attributable to window-count-adjusted noise vs. genuine decay). That's the actual next step, not
a config change.

## Recommendation

Do **not** implement the v1 "couple hold_max_bars to selected lookahead_bars" fix — the premise
was wrong. If this hypothesis is worth pursuing, the next step is a targeted statistical check on
`_compute_ic_rolling_metrics`'s window-density-vs-noise relationship (e.g., bootstrap the
per-window IC variance at matched raw-bar sample sizes across strides and see how much of the
`ic_sharpe` decay is noise-driven), not a change to `ensemble_ic_engine.py`'s calibration logic
before that's understood. Flagging as P1 open methodology question rather than acting further
unilaterally — this determines whether `hold_max_bars` across the whole corpus needs
re-derivation under a corrected sharpe estimator, which is a bigger and more consequential change
than the original todo assumed.

## Finding (2026-07-12, confirmed)

Ran the proposed comparison query against live `ensemble_weights` (champion weight_version
`run_2025122405150000` — the E1 shrunk-IC champion, not the rejected E2 `_mv` mean-variance
variant) and `alpha.frame.hold_max_bars.{regime}.{tf}` in `config_state`, across all 18 populated
(tf, regime) strata:

| tf | regime | weighted-avg selected lookahead_bars | hold_max_bars | ratio |
|---|---|---|---|---|
| 5m | high_bull | 17.5 | 1 | 17.45 |
| 5m | high_bear | 12.8 | 1 | 12.79 |
| 5m | high_neutral | 16.1 | 1 | 16.11 |
| 5m | low_bear | 12.8 | 1 | 12.75 |
| 15m | low_bear | 3.7 | 60 | 0.06 |
| 15m | high_neutral | 4.9 | 60 | 0.08 |
| 15m | mid_bull | 6.9 | 60 | 0.12 |
| 5m | low_neutral | 11.7 | 60 | 0.20 |
| (full 18-row table in the finding — pattern holds throughout) | | | | |

**This is not noise around 1.0 — it's a ~290x spread (0.06 to 17.45) with no systematic
direction**, confirmed by `corr(weighted_avg_lookahead, hold_max_bars)` across all 18 strata =
**0.19** (effectively uncorrelated). Some strata hold for 1 bar when the ensemble's own selected
features were calibrated to predict ~12-17 bars out (closing the position before the predictive
window has even elapsed); others hold for 60 bars when features were selected at a ~4-7 bar
horizon (holding 10-15x past the signal's calibrated horizon, dominated by noise). Both failure
directions are present, ruling out "hold includes a deliberate buffer" as an explanation — a
buffer would show up as a small, consistently-positive offset, not a near-zero correlation with a
290x spread.

**Consequence:** todo 093's pre-143.1-fix FRAME-04 baseline (16/17 cells FAIL, 77% timeout rate)
and any future FRAME-04 re-run (the eventual shadow-mode comparison in 143.1-08) cannot be
interpreted as "does a reasonable execution rule capture the ensemble's IC" until this is fixed —
in most strata the frame isn't holding for the horizon the ensemble's own feature selection
claims predictability at, so a FAIL could mean "the alpha isn't capturable" or could just mean
"we measured the wrong horizon," and the current data can't distinguish the two.

## Decision (2026-07-13, Fable sign-off, implemented)

Sent to Fable (Plan agent, model=fable) for explicit sign-off on both open decisions, with the
Monte Carlo script and full blast-radius trace as evidence. Fable independently re-ran the
diagnostic (numbers reproduced exactly) and traced the real corpus-wide consumers before
answering — corrected one claim in the original writeup: `ic_sharpe` does NOT feed
`passes_fdr`/`reliable` in `ic_engine.py` (those come from `n_valid >= min_reliable_n` and BH on
bootstrap/Fisher-z p-values respectively). The real consumers are `feature_selector.py`'s
`quality_weight` (feature selection itself — arguably a bigger effect than hold truncation,
since it shapes which lookaheads enter the ensemble at all) and `ensemble_ic_engine.py`'s decay
walk (as originally described).

**Decision A — GO.** Fix: fixed window size in **subsampled** bars (not raw-bars-divided-by-
stride), via a **new APR key** `alpha.ic.sharpe_window_size_subsampled` (not a redefinition of
the existing key — avoids silent code/config rollback skew and preserves the old key's raw-bar
provenance in `config_history`). Value **100**, not 400: 400 would NaN out the slow/extended
scales almost everywhere (freezes `hold_max_bars` short via a different mechanism — the same
disease, different cause). Mandatory same-migration threshold rescale (since
`ic_sharpe ≈ rho·√w`, halving window density from ~400 to 100 means halving every
sharpe-denominated threshold to preserve its meaning): `alpha.ensemble_ic.decay_threshold`
0.1→0.05, `alpha.ensemble.sharpe_floor` 0.05→0.025, `alpha.feature_registry.min_ic_sharpe_default`
0.5→0.25. HAC and block-bootstrap alternatives rejected — the bias is *within*-window sampling
noise, not *between*-window autocorrelation (HAC's target) or estimate uncertainty (bootstrap's
target); a fixed-w window is the only fix that makes `ic_sharpe` one comparable quantity for
every consumer with no new estimator machinery.

**Decision B — Option 2** (keep `hold_max_bars` as an independent APR key family, re-derive
empirically per stratum using the corrected estimator), not close. Coupling (`hold_max_bars`
derived directly from selected `lookahead_bars`) repeats the category error the todo's own v2
pass already refuted (a blended ensemble score's decay horizon has no obligation to match a
weighted average of its constituents' individually-selected horizons), and the 290x-spread
evidence used to argue for coupling is itself contaminated by this same bug on both sides of the
ratio — re-measure after the fix, don't design a permanent architecture around biased numbers.
Coupling would also delete the mechanism todo 088 (deliberately sequenced last) is meant to
refine.

**Implementation notes:**
- Recalibration order for the eventual corpus re-run: `ic_engine` (feature-level rows) →
  `ensemble_trainer` reweight (quality_weight now unbiased across lookaheads — expect selection
  to shift toward longer horizons) → `ensemble_ic_engine` (decay walk on the NEW champion
  weights, not stale ones).
- Two stale comments fixed in the same commit: `ensemble_ic_engine.py`'s
  `compute_walk_forward_stable` docstring (raw-bar math for the 60k-bar floor) and
  `ic_engine.py`'s daily-cadence-NaN comment (daily data now clears the sharpe gate under w=100
  where it previously didn't — intentional, not a regression).
- Migration 230 applied to the live DB 2026-07-13.

## Decision needed (project owner)

Confirmed real per the check above; the remaining open question is genuinely a design call, not
a data question:

1. **Couple `hold_max_bars` to each stratum's selected `lookahead_bars`** — e.g. derive it
   directly (weighted-avg lookahead + a fixed buffer) at calibration time instead of treating it
   as an independent APR key family. Removes the mismatch by construction; loses the
   already-invested todo 088 per-cell walk-forward-confirmed calibration work (11/36 cells) unless
   that gets re-derived under the new coupling.
2. **Keep them independent but re-derive `hold_max_bars` empirically per stratum from the actual
   selected lookahead**, preserving todo 088's confirmed/estimated distinction but fixing the
   input it's calibrated against.

Recommendation: option 1 is simpler and removes an entire class of future drift (the two APR
families going out of sync again after the next ensemble re-weighting), but is a real design
change to how `alpha.frame.hold_max_bars.*` is populated — flagging for an explicit call rather
than making it unilaterally.

# 096 — Verify frame `max_hold_bars` is commensurate with the lookahead each feature's IC was
actually measured/selected at

**Found:** 2026-07-11, flagged during a Fable architectural review of todo 094 (the long/short
imbalance root-cause fix), as a distinct, independently-actionable gap worth checking before
trusting any post-fix FRAME-04 re-run.

## The concern

`select_features_per_stratum()` (`src/intelligence/ensemble/feature_selector.py`) picks a
**specific `lookahead_bars` per feature** — the horizon at which that feature's IC was strongest/
most reliable, per the Lookahead disambiguation rule ("never average across lookaheads — that
dilutes the signal"). This is the horizon the ensemble's predictive claim is actually calibrated
against.

But `CounterfactualTracker`'s frame hold horizon comes from a completely separate source: the
`alpha.frame.hold_max_bars.{regime}.{tf}` APR key (migration 195 origin), most of which (25/36
regime/tf cells per todo 088) are still unvalidated `[initial_estimate]` guesses, not derived
from — or even cross-checked against — the `lookahead_bars` values features were actually
selected at.

**If a stratum's features were selected because they predict well at, say, 60 bars out, but that
stratum's `hold_max_bars` is set to 20 (or 200), `CounterfactualTracker` is not measuring the
alpha the ensemble gates actually certified.** This would produce exactly the pattern seen in
todo 093's early partial backfill results: 77% of frames never resolve (hit neither stop nor
target) and just time out with near-zero average P&L — consistent with a hold window that's
mismatched (too short to let the real horizon play out, or too long and dominated by noise after
the real predictive window has passed) rather than (or in addition to) `hold_max_bars` simply
being an uncalibrated guess in the todo 088 sense.

This is a **different failure mode than todo 088**: 088 is about the *methodology* for how
`hold_max_bars` gets calibrated (confirmed-decay vs. censored-data ambiguity in the median
aggregation). This todo is about whether `hold_max_bars`, however it was set, is even measuring
the same horizon the feature-selection layer claims predictability at. Both could be true
simultaneously and compound.

## Proposed check

For a sample of (symbol, tf, regime) strata, compare:
1. The `lookahead_bars` value(s) actually selected for that stratum's top-weighted features
   (`ensemble_weights` or the `selected` rows from `select_features_per_stratum`).
2. The `hold_max_bars` value applied to frames in that same stratum
   (`alpha.frame.hold_max_bars.{regime}.{tf}`).

If these are systematically mismatched (not just noisy around each other, but structurally off —
e.g. features consistently selected at long lookaheads while `hold_max_bars` is set short, or
vice versa), that's the primary lever to fix before any further `hold_max_bars` calibration work
(todo 088) is worth doing — recalibrating a fundamentally mismatched horizon just produces a
better-tuned wrong number.

## Proposed next steps

1. Run the comparison query above across a representative sample of strata (not just the 5-6
   symbols todo 093 has processed so far — wait for more coverage, or accept a partial read with
   that caveat stated explicitly).
2. If mismatched: decide whether `hold_max_bars` should be derived FROM each stratum's selected
   `lookahead_bars` (coupling the two) rather than being an independent APR key family, or
   whether they're legitimately meant to differ (e.g. hold horizon includes a deliberate buffer
   past the predictive window) — this is a design decision, not just a data fix.
3. Fold the finding into todo 088's scope if it turns out to be the same underlying issue viewed
   from a different angle; keep separate if it's genuinely a distinct bug.

**Gate:** none — runs against `ensemble_weights`/APR config that exists today. Best done once
todo 093's backfill has more coverage than the current ~7%, but the query itself doesn't depend
on 093 finishing (it compares metadata, not frame outcomes) — could run in parallel right now for
an early read, with the caveat that early symbols may not be representative.

---

**Note (2026-07-12, corrected same day):** this file briefly claimed to have merged
`.planning/todos/pending/088-hold-max-bars-censoring-not-tracked.md` in — that was wrong and has
been reverted. 088 is a locked, separately-sequenced step per `.planning/todos/PRIORITIES.md`'s
explicit "do not reorder without re-confirming" decision and multiple frozen phase artifacts
(093→091→097→094→A/B re-run→**096**→**088**, in that order, 088 deliberately last). Related — both
concern `_calibrate_hold_max_bars`/`_select_hold_bars_from_decay` — but not the same todo. See 088
directly for its own scope.
