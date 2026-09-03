# Ensemble-Variant Winner's Curse - Peer-Group Decision for OQ7 (2026-07-09)

**Author:** Fable 5 (dispatched via Claude Code Agent tool)

**What this is:** the methodology decision `docs/research/measurement-ic-engine.md` Open
Question 7 has been waiting on since 2026-07-06, and todo 069 (formerly 153) tracks: which peer
group the winning ensemble weighting variant's measured IC should shrink toward before
`scripts/ops/alpha/ops_ensemble_weight_compare.py` renders its verdict. Decided now, before the
E1/E2 judgment runs, so the correction is pre-registered rather than negotiated after seeing a
result (the same discipline as `docs/plans/OOS-EVAL-PROTOCOL.md`). This is a design decision
only; no source code is changed by this doc. Implementation shape is in §6.

---

## 1. Executive Summary

1. **Decision: no shrinkage peer group at ensemble-variant grain. The question as posed is
   malformed for the selection mechanism this codebase actually runs.** `shrink_ic()` stays a
   feature-grain tool. The winner's-curse risk OQ7 names is real, but it does not enter through
   the channel the feature-grain analogy assumes, and importing `leave_one_out_group_prior()`
   over a peer group of 1-2 correlated, non-exchangeable variants would be statistical theater.
2. The selection structure here is **pairwise champion-vs-challenger CI-ordering per stratum**,
   not a k-way argmax over noisy point estimates (§3). The residual biases decompose into three
   distinct channels, each with a cheaper and more exact instrument than shrinkage:
   - **Across-strata multiplicity** within one compare run: fix with a per-stratum
     paired-difference p-value plus BH-FDR across strata inside
     `ops_ensemble_weight_compare.py` (§5.1). This is the one code change this decision
     mandates.
   - **Post-selection reporting bias** on the promoted winner's point IC: the citable in-sample
     number is `ic_ci_lower`, and the authoritative unbiased estimate is the EnsembleICEngine
     measurement over the untouched OOS holdout per `OOS-EVAL-PROTOCOL.md` (§5.2). Held-out
     estimation is the exact correction for selection bias, and the infrastructure already
     exists.
   - **Sequential-ladder multiplicity** across E1/E2/E3/E4 rounds: handled by the standing
     `docs/plans/methodology-change-ledger.md` mechanism plus OOS spend discipline (§5.3).
3. The D-15 winner's-curse caveat in `ops_ensemble_weight_compare.py` stays until §5.1 and the
   first OOS confirmation land, then narrows to "OOS confirmation pending" wording.
4. **Revisit triggers** are named in §7; the main one is L5-3 (Bayesian averaging over 3+
   variants), which dissolves champion selection and with it this entire problem shape.

---

## 2. The Problem, Grounded in the Code

Phase 142B.1 built three `weight_version` variants of the ensemble weighter: `v1` (baseline
IC-proportional on raw `ic_sharpe_hac`), E1 (IC-proportional on shrunk `ic_shrunk` inputs), and
E2 (mean-variance `Σ⁻¹·IC`; `_VALID_WEIGHT_METHODS` at `services/ensemble_trainer.py:158` has
exactly two methods, `ic_proportional` and `mean_variance`). Each variant's pooled
cross-sectional IC is measured by `services/ensemble_ic_engine.py` into `alpha_ensemble_ic`
(Fisher-z CI at line 769, `n_independent` persisted per row, line 373).

`scripts/ops/alpha/ops_ensemble_weight_compare.py` then judges challenger against champion per
`(tf, regime)` stratum. The comparison SQL (`_COMPARE_SQL`, lines 79-92) reads exactly two
`weight_version`s at each version's own latest `scored_at` vintage, pooled rows only, at the
single APR-selected gate lookahead. The win rule (`_evaluate_win_rule`, lines 95-106, D-10) is:

    challenger beats champion iff challenger.ic_ci_lower > champion.ic_ci_upper
        AND challenger.walk_forward_stable

Promotion is per-stratum (D-11); there is no forced global winner. Since 2026-07-08 every WIN
verdict carries the D-15 caveat (lines 67-71) recording that the winner's IC is unshrunk and
selection-biased. OQ7 asks what to shrink it toward; `docs/research/fable-2026-07-07-renaissance-layer-refinements.md`
§L4-3 proposed "peer group = the variants compared within that stratum" as the concrete
candidate. This doc evaluates that and the alternatives.

Selecting the best of several noisy estimates and reporting the winner's raw measured value
overstates it; that logic is sound in general. The question is where, precisely, selection
happens in this machinery, because the correction must match the mechanism.

## 3. What Selection Actually Happens Here (the crux)

The feature-grain problem `shrink_ic()` was built for is a k-way screen: hundreds of features
per `(group_name, regime, tf)` cell, each with a noisy IC, where gates and weights consume the
point estimates directly. There, the largest estimates are the most upward-biased, the peer
group is large and quasi-exchangeable, and empirical-Bayes shrinkage toward a leave-one-out
family mean is the right tool.

The variant judgment is structurally different in three load-bearing ways:

1. **The decision does not consume the point estimate.** D-10 consumes CI ordering
   (`ic_ci_lower > ic_ci_upper`) plus a walk-forward veto. Shrinking the winner's `ic_value`
   would change nothing about which variant gets promoted; it would only change a number in a
   report. Any correction aimed at the decision must act on the CI comparison, not the point.
2. **The pairwise test is already stringent.** Requiring two 95% Fisher-z CIs to not overlap is
   far stricter than a 5% difference test: with independent estimates of equal standard error,
   non-overlap requires the gap to exceed 3.92 SE while a two-sided z-test at 5% needs 2.77 SE;
   non-overlap therefore corresponds to roughly p < 0.006 per stratum. And the two variants'
   ICs are measured on the same bars, the same forward returns, and largely overlapping alpha
   constructions, so their estimation errors are positively correlated; the true standard error
   of the difference is smaller than the independence assumption implies, making the effective
   test even more conservative than 0.006. Per-comparison winner's curse conditional on passing
   this gate is small by construction.
3. **The peer "population" is 2-3 deliberately different methodologies estimated on identical
   data.** Empirical Bayes assumes the group members are roughly exchangeable draws around a
   common mean with independent noise. E1 and E2 are neither exchangeable (they are constructed
   to differ; one of them may be structurally better) nor independently measured (same corpus).
   `leave_one_out_group_prior()` itself falls back to the self value at `n_group <= 1`
   (`src/intelligence/ensemble/shrinkage.py:94-98`); at 2 comparands the "prior" is a single
   noisy, correlated estimate, i.e. the loser's IC.

What remains genuinely uncorrected today, given (1)-(3):

- **(a) Across-strata multiplicity.** D-10 is applied independently across every `(tf, regime)`
  cell present for both versions - on the order of a few dozen strata (roughly 4 tfs by 9 live
  cross-sectional regime labels, at the single gate lookahead). Under a global null, expected
  false WINs are about 36 x 0.006 = 0.2, so the chance of at least one fluke WIN somewhere in
  the family is on the order of 20%. A challenger that "wins" in exactly one stratum out of ~36
  is the plausible-fluke shape, and nothing in the script currently distinguishes it from a
  challenger that wins in ten.
- **(b) Post-selection reporting bias.** Conditional on a WIN, the winner's `ic_value` in that
  stratum is upward-biased (small, given the stringent gate, but not zero), and that number is
  what humans will quote in later evidence chains (cost-hurdle arithmetic, Kelly inputs, OOS
  budget decisions) unless told otherwise. This is exactly what D-15 currently caveats.
- **(c) Sequential-ladder multiplicity.** D-12 makes the comparison "repeatable across E1/E2
  (and future E3/E4) rounds." A champion that survives k sequential pairwise challenges has
  been selected k times; its accumulated in-sample record carries survivorship pressure that no
  single-run correction sees. This is the pipeline-level garden of forking paths the
  methodology change ledger exists for.

## 4. Candidates Evaluated

### 4.1 Leave-one-out across variants within the stratum (L4-3's proposal) - REJECTED

The direct grain-analog: the winning variant shrinks toward the mean IC of the other variants
in the same `(tf, regime)` cell.

- For: mechanically trivial (`shrink_ic` + `leave_one_out_group_prior` run as-is; `ic_value`
  and `n_independent` are already persisted per row); it is the framing OQ7 and L4-3 both
  reached for.
- Against, decisive: with 2 comparands the LOO prior is the loser's own noisy IC - shrinking
  the winner toward the loser by construction, with weight set by `n_eff/(n_eff+k)` where `k`
  (`alpha.ic.shrinkage_k`) was calibrated for feature families, not variant pairs. If the
  winner is genuinely structurally better (the entire hypothesis being tested), this
  overcorrects toward a coin-flip prior. The exchangeability and independence assumptions
  behind empirical Bayes fail on every axis (§3, point 3). And because the decision consumes CI
  ordering rather than the point estimate, this changes no verdict; it only replaces one
  not-quite-right number in a report with a different not-quite-right number. A "leave-one-out
  among variants" framing implicitly assumes a k-way argmax selection that this codebase does
  not run.

### 4.2 Same variant across other strata - REJECTED for OQ7 (it answers a different question)

E2's IC in other `(tf, regime)` cells forms E2's prior in this cell.

- For: this is real statistics with real data behind it (dozens of strata per variant), and it
  does partially correct the per-stratum component of selection: the stratum where a variant
  wins is disproportionately the stratum where its noise realization was favorable, and
  cross-stratum pooling regresses that.
- Against, decisive: it corrects measurement noise in a stratum estimate, not selection among
  variants - the bias OQ7 is about. It also assumes IC homogeneity across strata, which
  contradicts the design premise of per-stratum promotion (D-11 exists precisely because
  variant quality is expected to vary by regime and tf; a mixed outcome is "expected and
  directly expressible" per the script's own docstring). Finally, this is hierarchical partial
  pooling across sparse strata, which is E3's territory, roadmap-locked as deferred until E1/E2
  prove insufficient (142B.1-CONTEXT.md). Building it as a side effect of a reporting fix would
  bypass that lock. It belongs to OQ8's "what is this predictor's IC now" composition question,
  not to OQ7.

### 4.3 Hierarchical two-level (shrink within variant across strata, then correct across variants) - REJECTED for now

- For: it is the textbook-complete decomposition; at a large variant count it is the correct
  answer.
- Against, decisive: level 2 (cross-variant) inherits all of 4.1's failures at k=2-3, and level
  1 inherits 4.2's homogeneity problem and roadmap lock. Neither level changes any verdict
  (decision consumes CI ordering), so the entire apparatus would exist to adjust a reported
  number for which a strictly better estimate already exists (§4.4's holdout). The 5-step
  mandate says delete before building: two estimation layers to avoid citing one biased number
  is complexity the current evidence does not support.

### 4.4 Multiple-comparisons correction on the decision + held-out estimation for the number - ADOPTED

This is the candidate that actually matches the mechanism. Split OQ7's single question into the
two things it conflates:

- **The decision.** The selection event is a family of pairwise CI-ordering tests, one per
  stratum. The correct instrument for family error in a family of tests is a multiplicity
  correction across the family, and the codebase already committed to exactly this philosophy
  at feature grain (Phase A's corpus-level BH-FDR, methodology-change-ledger E2). Compute a
  per-stratum p-value for the IC difference (two-sample z on Fisher-z transforms of
  `ic_value` with the persisted `n_independent`; conservative under the positive dependence
  noted in §3, which is the safe direction) and apply BH across the strata in the run. A WIN
  then requires D-10 AND surviving BH. This bites exactly where it should: a lone marginal WIN
  among ~36 strata gets BH-adjusted from p = 0.006 to roughly 0.2 and is downgraded, while a
  challenger winning across many strata sails through.
- **The number.** The formally exact fix for reporting a post-selection estimate is not
  shrinkage toward an ill-defined peer, it is measurement on data the selection never saw. The
  project already holds an untouched OOS window (`alpha.validation.oos_start`, enforced since
  Phase 141.1) and `OOS-EVAL-PROTOCOL.md` already names EnsembleICEngine as the authoritative
  OOS scorer. The promoted champion's citable IC is its OOS measurement; until that runs, the
  citable in-sample number is its `ic_ci_lower` (already computed, already what the decision
  consumed, and conservative under selection), never its raw `ic_value`.

For completeness, a fifth option was considered and rejected: formal conditional
post-selection inference (truncated-distribution MLE of the winner's IC given the non-overlap
selection event). It is the frequentist-exact answer to the reporting question, but it is
research-grade machinery to squeeze an honest number out of in-sample data when an untouched
holdout already exists; the holdout dominates it on both simplicity and validity.

## 5. The Decision

**No shrinkage peer group is defined at ensemble-variant grain. `shrink_ic()` is not applied to
variant ICs. OQ7 is answered by decomposition, not by a prior:**

### 5.1 Pre-registered decision fix (the one mandated code change)

`ops_ensemble_weight_compare.py` gains a per-stratum paired-difference p-value and BH-FDR
across the strata of a run; the WIN verdict becomes D-10 AND BH survival. This is decided now,
before the first E1/E2 judgment has ever run, so it is a pre-registration, not a
result-driven gate change; the implementing commit must still carry a
`methodology-change-ledger.md` entry saying exactly that (the "clean pattern" of ledger entry
E4).

### 5.2 Reporting rule

The report footer and the D-15 caveat text change to state the rule rather than an open
question: the winner's citable in-sample IC is `ic_ci_lower`; its unbiased estimate is the
EnsembleICEngine OOS measurement per `OOS-EVAL-PROTOCOL.md`, which must be run for the promoted
champion before its IC is cited in any downstream evidence chain (cost hurdle, Kelly,
promotion claims). The caveat narrows to "OOS confirmation pending" once 5.1 lands, and drops
for a given champion once its OOS confirmation exists.

### 5.3 Ladder discipline

Every judgment round (E1 vs v1, winner vs E2, future E3/E4/L5 challengers) appends a
methodology-change-ledger entry naming the round, and each round's OOS confirmation should
prefer holdout data not previously cited for a promotion claim; the holdout grows forward in
calendar time, so this is affordable. No new machinery; this is the ledger doing the job it
was created for at the meta level that no single-run correction can see.

**Why this is the Renaissance-consistent call:** it corrects the two biases that are real
(family multiplicity, post-selection reporting) with the two instruments the codebase already
believes in (BH-FDR, an enforced holdout), adds one small pure function to the shared kernel
instead of a new estimation layer, refuses to manufacture a prior from a population of one, and
leaves the champion-selection semantics (D-10/D-11) intact and pre-registered. Make the
requirement less dumb (the requirement was never "shrink the winner", it was "do not act on or
cite a selection-biased number"), delete (no variant-grain shrinkage layer), simplify (reuse
`n_independent`, `ic_value`, Fisher-z, BH - all already in the schema and kernel).

## 6. Implementation Shape (for the follow-on plan; no code changed by this doc)

1. **`src/intelligence/statistics/ic_math.py`** - add one pure kernel helper,
   `fisher_z_difference_p(ic_a: float, n_a: float, ic_b: float, n_b: float) -> float`:
   two-sided p for the difference of two ICs via Fisher-z, SE = sqrt(1/(n_a-3) + 1/(n_b-3)).
   Docstring must state it is conservative under positive dependence between the two estimates
   (same bars, same returns) and that this is the intended direction. Kernel home per the D1
   shared-kernel convention (a methodology function must not live inside one consumer script).
2. **`scripts/ops/alpha/ops_ensemble_weight_compare.py`** -
   - `_COMPARE_SQL` additionally selects `ae.ic_value, ae.n_independent`.
   - Per stratum: compute the difference p-value; after the stratum loop, BH-adjust across the
     strata present in the run (`statsmodels.stats.multitest.multipletests`, already a project
     dependency in both engines).
   - Verdict: `WIN` requires the existing D-10 rule AND BH-adjusted p below the alpha key; a
     stratum passing D-10 but failing BH reports as `WIN-FDR-VETO` (distinct verdict, since
     silently folding it into LOSS would hide exactly the multiplicity information the change
     exists to surface). Report gains `p_raw` and `p_bh` columns.
   - APR: one new key, `alpha.ensemble.compare_fdr_alpha`, seeded to the same value as the
     engines' existing `fdr_alpha` with provenance `[conventional]`; a dedicated key because
     the strata family is a different test family than the feature corpus, and coupling them
     silently would be an APR-mandate violation in spirit.
   - `_D15_WINNERS_CURSE_CAVEAT` text updated: point at this doc, replace the stale "todo 153"
     reference with 069, and rephrase from "peer group not yet decided" to "cite ic_ci_lower;
     OOS confirmation pending per fable-2026-07-09-ensemble-winners-curse-peer-group.md".
   - Footer line stating the reporting rule (§5.2).
3. **`tests/unit/test_ensemble_weight_compare.py`** - extend: BH veto on a lone marginal WIN
   among many null strata; BH pass on a multi-stratum winner; caveat text; degenerate
   `n_independent <= 3`.
4. **`docs/plans/methodology-change-ledger.md`** - entry in the implementing commit
   (pre-registered; judgment not yet run).
5. **OOS confirmation step** - no new code needed: run `services/ensemble_ic_engine.py` for the
   promoted `weight_version` over the holdout window per `OOS-EVAL-PROTOCOL.md` before citing
   its IC. If the protocol doc's degradation rules do not yet spell out the ensemble-grain
   invocation, add the two-line clarification there rather than building anything.

## 7. What Would Change This Decision

- **Variant count grows into a real population.** If a simultaneous k-way round over roughly 5+
  variants of the same family ever replaces the pairwise ladder (e.g. a grid of L5-1 blending
  temperatures), the exchangeability objection to 4.1 weakens and cross-variant shrinkage (or
  the hierarchical 4.3) becomes worth revisiting. More likely, L5-3's Bayesian averaging over
  3+ variants arrives first and dissolves champion selection entirely - a blend has no argmax
  and no winner's curse; if L5-3 is built, this doc's §5.1 machinery still governs the blend-vs-
  best-constituent comparison but the reporting question disappears.
- **Measured OOS decay quantifies a real curse.** If the first few promoted champions show OOS
  IC systematically and materially below `ic_ci_lower` (not just below `ic_value`), the
  selection bias is larger than the stringent-gate analysis in §3 predicts, and formal
  conditional post-selection inference (§4.4's rejected fifth option) should be revisited ahead
  of the next judgment round.
- **Strata multiply.** If the stratum family grows well past ~36 cells (new conditioning axes
  from v3.15, more tfs, per-asset-class regime groups), the BH step becomes more load-bearing
  and the per-stratum evidence thinner; that is the point to reconsider 4.2/4.3-style partial
  pooling as an input-side fix, through the E3 roadmap gate, not around it.
- **The D-10 rule itself changes.** The §3 stringency arithmetic is specific to the
  non-overlapping-CI rule. If the win rule is ever relaxed (e.g. to a plain one-sided
  difference test), the per-comparison winner's curse stops being negligible and the reporting
  rule in §5.2 must be re-derived, not assumed.

## 8. References

- `docs/research/measurement-ic-engine.md` OQ7 (lines 395-406) - the question this doc answers
- `docs/research/fable-2026-07-07-renaissance-layer-refinements.md` §L4-3 (the LOO-within-
  stratum proposal, evaluated as 4.1), §L5-3 (the blending alternative named as a trigger in §7)
- `.planning/todos/pending/069-winners-curse-shrink-before-e1e2-judgment.md` - tracking todo;
  stays open for §6 implementation
- `scripts/ops/alpha/ops_ensemble_weight_compare.py:79-92` (`_COMPARE_SQL`), `:95-106` (D-10
  win rule), `:67-71` (D-15 caveat) - the comparison mechanism
- `src/intelligence/ensemble/shrinkage.py:27-98` - `shrink_ic` / `leave_one_out_group_prior`,
  the feature-grain machinery deliberately not imported here
- `services/ensemble_trainer.py:158` - `_VALID_WEIGHT_METHODS` (variant count ground truth)
- `services/ensemble_ic_engine.py:769,373` - Fisher-z CI and persisted `n_independent`
- `docs/plans/OOS-EVAL-PROTOCOL.md` - holdout definition; EnsembleICEngine as authoritative OOS
  scorer
- `docs/plans/methodology-change-ledger.md` - the sequential-ladder control (§5.3)
- `.planning/milestones/v3.1-phases/142B.1-ensemble-weighting-methodology-replace-ensemble-trainer-py-s/142B.1-CONTEXT.md`
  D-10/D-11/D-12 (comparison design), E3 deferral lock (relevant to 4.2's rejection)
