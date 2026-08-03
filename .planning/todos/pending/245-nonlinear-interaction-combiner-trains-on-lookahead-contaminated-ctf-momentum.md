---
status: pending
priority: P0
filed: 2026-08-03
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

## Fix / next step

Do not re-run todos 239/240's corrected methodology at 1h/15m/5m until one of:
1. Todo 243's join fix lands and the affected `ctf_momentum` values are recomputed for the
   scoped sample/corpus needed, or
2. A clean diagnostic re-run excludes `ctf_momentum` from `EXCLUDE_COLS` for a scoped comparison
   -- if the tree's uplift over the linear arm survives `ctf_momentum`'s removal, that's real
   evidence the result isn't just riding the leak; if it collapses, that's the answer too. Cheap
   (one extra `EXCLUDE_COLS` entry, no corpus changes), and answers the confound question
   directly without waiting on todo 243's own fix/recompute decision.

Option 2 is the faster, non-blocking path and doesn't require deciding todo 243's corpus-recompute
question first. Recommend doing option 2 before or alongside todo 243's own read-only measurement.

**1d re-run of todos 239/240's corrected methodology is safe to do right now**, independent of
this todo -- no `ctf_momentum` lookahead exposure there.

## Cross-refs

- [todo 243](243-ctf-momentum-batch-join-lookahead-bias.md) -- the underlying lookahead bug;
  this todo is its blast-radius extension into nonlinear_interaction_combiner specifically
- [todo 239](239-nonlinear-interaction-combiner-embargo-passed-in-pooled-panel-rows-not-bars.md),
  [todo 240](240-nonlinear-interaction-combiner-baseline-is-single-feature-not-the-linear-ensemble.md)
  -- the methodology fixes whose pending re-run this todo gates (at 1h/15m/5m only)
- `docs/research/data-edge-source-thesis.md` -- nonlinear_interaction_combiner section cites the
  1h/15m numbers as "confirmed real and substantial"; needs the same caveat todo 243 already
  triggered for Phase 167
