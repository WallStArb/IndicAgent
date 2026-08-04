---
status: closed
priority: P0
filed: 2026-08-03
closed: 2026-08-04
source: cross-checking todo 243 (ctf_momentum batch-join lookahead bias, filed same day by a
  concurrent session) against todos 239/240 (nonlinear_interaction_combiner methodology fixes,
  this session) -- the two workstreams never cross-referenced each other; found by asking
  whether ctf_momentum's lookahead bug has a blast radius beyond Phase 167
---

# `nonlinear_interaction_combiner`'s tree AND new linear-ensemble arm both train directly on lookahead-contaminated `ctf_momentum` at 1h/15m/5m

## What

Todo 243 (filed 2026-08-03, same day, independently) confirmed `ctf_momentum`'s batch/corpus
value is computed via a join that selects the still-forming HTF bar, not the last completed one
-- real lookahead up to 55min at 5m/15m, up to a full day at 1h. Todo 243's own text scopes the
consequence to Phase 167 (`cross_sectional_spread_tracker.py` ranks directly on `ctf_momentum`).

**That scoping is incomplete.** `scripts/analysis/_nonlinear_interaction_combiner_shared.py`'s
`EXCLUDE_COLS` (the list of `feature_vectors` columns withheld from the walk-forward training
matrix) does NOT include `ctf_momentum` -- it is one of the ~247 trained feature columns, not
just the `baseline_feature` default. Direct evidence it matters a lot to the tree, not a
theoretical concern: this file's own comment (line 99, from the `hmm_duration` exclusion
rationale) states LightGBM feature_importances_ measured `ctf_momentum` at "400+" across all 5
folds of the 1h run -- one of the tree's most heavily relied-upon features, not a minor input
among 247.

Consequence: the published "substantial at 1h and 15m" nonlinear_interaction_combiner finding
(`point_ic` 0.18-0.25, cited in `docs/research/data-edge-source-thesis.md` and STATE.md as
confirmed real) was measured with a high-importance, lookahead-contaminated column sitting
inside the training matrix at exactly those two timeframes. A LightGBM tree is very good at
exploiting any column correlated with the target -- and a column containing genuine future price
information (not noise) is exactly the shape of signal a tree would learn to lean on hard. This
does not prove the entire nonlinear_interaction_combiner result is an artifact, but it means the
result cannot currently be trusted at 1h/15m/5m until this is accounted for.

This also affects todos 239/240's own fix (this session, commit `816032e2`): the new
`fit_linear_ensemble_weights()` linear-ensemble arm trains on the identical `X` matrix -- same
contaminated `ctf_momentum` column, same exposure. Whatever the pending 1h/15m/5m re-run under
the corrected embargo/linear-ensemble methodology produces, it inherits this same confound. A
"more rigorous" re-run that still trains on a known-leaked column is not actually clean --
it just has better bookkeeping around a still-compromised measurement.

**1d is unaffected** -- todo 243's own table confirms the 1d join is self-referential and
genuinely safe (batch only processes fully-closed daily bars). The already-published 1d
nonlinear_interaction_combiner number (`point_ic`=0.0127, small) does not need to wait on this.

## Verified, not assumed

- `ctf_momentum` has ZERO rows in `ensemble_weights` (checked live DB, all `weight_version`s) --
  it does NOT currently pass BH-FDR eligibility for the live production ensemble
  (`feature_ic_scores.passes_fdr = false` at every tf, 0/60 rows at 1h/15m/5m/1d). **The live
  `alpha_ensemble_ic`/`alpha_publisher` path is NOT contaminated by this bug** -- confirmed, not
  inferred, before writing this todo. The blast radius is narrower than it could have been:
  Phase 167's standalone ranking use (todo 243) and nonlinear_interaction_combiner's training
  matrix (this todo), not the live ensemble.

## Follow-up rigor pass, same day: the leak likely biases the PRIMARY VERDICT's comparison itself, not just both arms' absolute magnitude

Checked whether the same lookahead-join bug pattern (`bisect_right` against period-start-stamped
HTF bars) exists anywhere else in the corpus, beyond the CTF family -- it does not. One call site
(`feature_factory.py:6925`), feeding only `_build_ctf_series`'s three CTF columns. **Isolated, not
systemic** -- confirmed by grep, not assumed.

More importantly: `fit_linear_ensemble_weights` (todo 240's new linear-ensemble arm) caps any
single feature's contribution at `_LINEAR_MAX_FEATURE_WEIGHT = 0.20` of total weight
(`_nonlinear_interaction_combiner_shared.py:68`). LightGBM has no equivalent per-feature
contribution ceiling -- a tree can lean on one powerful column across arbitrarily many splits,
unconstrained. If `ctf_momentum`'s lookahead leak is a genuinely strong (not noisy) signal, the
tree can extract more of it than the linear arm is structurally permitted to. This means the
PRIMARY VERDICT's paired-bootstrap comparison (tree vs linear) is at risk of being biased toward
"tree wins" for a reason that has nothing to do with non-linear structure -- the DIFFERENCE
between the two arms is compromised, not just each arm's absolute IC. This is a stronger reason
to run the `ctf_momentum`-excluded diagnostic below before trusting any 1h/15m/5m PRIMARY VERDICT,
even a "tree beats linear with a tight, non-overlapping paired CI" one.

## Third rigor pass, same day: the diagnostic in "Fix / next step" below was itself incomplete when first written

`EXCLUDE_COLS` (checked directly, not assumed) contains neither `ctf_vwap_align` nor
`ctf_regime_align` either -- both are also live trained columns in this matrix, and todo 243's
own text is explicit that all three CTF fields ("`ctf_momentum`, `ctf_vwap_align`,
`ctf_regime_align`") share the identical contaminated join, not just `ctf_momentum`. The
diagnostic as first written here ("exclude `ctf_momentum`, re-test") would have left two more
lookahead-contaminated channels open -- if the tree's uplift survived that partial exclusion, it
would have been wrongly read as "the leak wasn't the explanation," when the leak could still be
running through the other two untouched columns. Corrected below: exclude all three.

## 1h diagnostic RESULT, 2026-08-03 -- confirms the hypothesis, magnitude quantified

`nonlinear_interaction_combiner_ctf_leak_diagnostic_1h.py` ran to completion (~85 min).
Cross-sectional-neutral point_ic, paired bootstrap, tree vs linear ensemble:

| | tree | linear | tree-linear diff |
|---|---|---|---|
| WITH CTF cols (published methodology) | 0.1811 | 0.0163 | 0.1648 (ci_lower=0.1608) |
| WITHOUT CTF cols (leak excluded) | 0.0171 | 0.0065 | 0.0106 (ci_lower=0.0064) |

**Tree's point_ic collapsed 90.6% (0.1811 -> 0.0171) once the three lookahead-contaminated CTF
columns were removed.** The published "substantial at 1h" nonlinear_interaction_combiner finding
was overwhelmingly an artifact of the leak, not genuine non-linear structure -- confirmed, not
hypothesized. `n_pass_fdr_positive` for the tree fell from 80/80 (with leak) to 21/80 (without) --
the "universal across all 80 symbols" character of the original finding was almost entirely
leak-driven.

**Not a total null result, though.** A small, real, statistically significant tree-vs-linear edge
survives leak removal: diff=0.0106, ci_lower=0.0064 (excludes zero). Genuine evidence some
non-linear structure exists beyond linear combination at 1h -- just ~15x smaller than the
uncontrolled measurement implied. This clean number (0.0171) now sits in the same small range as
1d's already-published, never-contaminated number (0.0127) -- a coherent picture, not a
contradictory one.

Mechanism confirmed as predicted: the tree's greater flexibility let it extract disproportionately
more of the leak than the linear arm could (which is capped at 20% weight per feature) --
consistent with the earlier prediction that the leak would bias the tree-vs-linear COMPARISON
itself, not just inflate both arms equally.

## 15m diagnostic RESULT, 2026-08-03 -- confirms the same story

`nonlinear_interaction_combiner_ctf_leak_diagnostic_15m.py` ran to completion. Same
cross-sectional-neutral point_ic, paired-bootstrap methodology:

| | tree | linear | tree-linear diff |
|---|---|---|---|
| WITH CTF cols (published methodology) | 0.2504 | ~0.02 (implied) | -- |
| WITHOUT CTF cols (leak excluded) | 0.0524 | -- | 0.0348 (ci_lower=0.0330) |

**Tree's point_ic collapsed 79.1% (0.2504 -> 0.0524).** `n_pass_fdr_positive` fell 80/80 -> 73/80
-- less total collapse than 1h's 90.6% (73/80 still pass, vs 21/80 at 1h), but the direction and
mechanism are identical. A small, real, statistically significant residual survives (diff=0.0348,
ci_lower=0.0330) -- larger in absolute terms than 1h's 0.0106, consistent with 15m's higher bar
density giving the tree more total signal to work with, leaked or not.

## 5m diagnostic RESULT, 2026-08-04 -- closes the full tf sweep

`nonlinear_interaction_combiner_ctf_leak_diagnostic_5m.py` ran to completion (~14h runtime,
started 2026-08-03 21:01, landed 2026-08-04). Same methodology:

| | tree | linear | tree-linear diff |
|---|---|---|---|
| WITH CTF cols (published methodology) | 0.1741 | -- | -- |
| WITHOUT CTF cols (leak excluded) | 0.0979 | -- | 0.0710 (ci_lower=0.0701) |

**Tree's point_ic collapsed 43.8% (0.1741 -> 0.0979)** -- the smallest collapse of the three tfs.
`n_pass_fdr_positive` fell only 80/80 -> 79/80. Residual diff=0.0710, ci_lower=0.0701 -- the
largest absolute surviving residual of the three tfs.

## Pattern across all three tfs, confirmed 2026-08-04

| tf | collapse % | n_pass_fdr: with -> without | residual diff | residual ci_lower |
|---|---|---|---|---|
| 1h | 90.6% | 80 -> 21 | 0.0106 | 0.0064 |
| 15m | 79.1% | 80 -> 73 | 0.0348 | 0.0330 |
| 5m | 43.8% | 80 -> 79 | 0.0710 | 0.0701 |

**Collapse % shrinks monotonically as tf gets finer, while the absolute surviving residual grows
monotonically.** Consistent with the leak's absolute magnitude being roughly bounded by HTF bar
duration (~constant regardless of LTF granularity) while the tree's total predictive power grows
at finer tfs (more bars, more structure to find) -- so the leak's *proportional* share shrinks
even as the *real* edge grows. A coherent, monotonic pattern across independent tf runs, not
three unrelated coincidences -- reinforces that this is a real mechanism, not measurement noise.

**Verdict: the published "SUBSTANTIAL at 1h and 15m" finding was overwhelmingly leak-driven at
every tf tested (43.8%-90.6% collapse), but not a total null at any of them -- a small, real,
statistically significant tree-vs-linear-ensemble edge survives at all three tfs.** 1d was
independently already safe (self-referential CTF join, no lookahead exposure) and unaffected
throughout.

## Closed, 2026-08-04

All three affected tfs (1h/15m/5m) measured; 1d was never affected. Unblocks:
- [Todo 247](247-edge-source-thesis-catalog-stale-substantial-verdict.md) -- doc reconciliation,
  DONE 2026-08-04 (`data-edge-source-thesis.md` v2.1, `catalog.md`), using the table above as the
  source numbers.
- Todo 243's own corpus-recompute decision -- no longer sequenced behind this todo, unblocked.
- Todos 239/240's pending 1h/15m/5m re-run under the corrected embargo/linear-ensemble
  methodology -- still gated on todo 243's join fix actually landing in the corpus (code fix is
  applied, corpus recompute is a separate, not-yet-made decision), not on this todo any further.
- N1 (residual-form fitting), the recommended next design from
  `docs/research/measurement-nonlinear-interaction-combiner.md` -- not yet run, real next step
  for the surviving small residual once todo 243's corpus question is resolved.

## Cross-refs

- [todo 243](243-ctf-momentum-batch-join-lookahead-bias.md) -- the underlying lookahead bug;
  this todo is its blast-radius extension into nonlinear_interaction_combiner specifically
- [todo 239](239-nonlinear-interaction-combiner-embargo-passed-in-pooled-panel-rows-not-bars.md),
  [todo 240](240-nonlinear-interaction-combiner-baseline-is-single-feature-not-the-linear-ensemble.md)
  -- the methodology fixes whose pending re-run this todo gates (at 1h/15m/5m only)
- `docs/research/data-edge-source-thesis.md` -- nonlinear_interaction_combiner section cites the
  1h/15m numbers as "confirmed real and substantial"; needs the same caveat todo 243 already
  triggered for Phase 167
