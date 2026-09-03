---
**Created:** 2026-07-10
**Updated:** 2026-07-11 — root cause **corrected** after Fable architectural review found the
2026-07-11 "Confirmed root cause" section below (the `compute_quality_weight` floor) was real but
NOT the actual cause — the true exclusion happens two gates upstream, verified against the live
DB. See "Corrected root cause" section; the original floor finding is kept below for record but
superseded.
**Area:** intelligence
**Type:** correctness
**Priority:** P0 (confirmed methodology bug excluding an entire feature population from the
champion ensemble, not a hypothesis)
**Effort:** M-L — this is NOT a small formula change. It requires a full `ic_engine` corpus
re-run (new sign-consistent walk-forward criterion), an eligibility-query redesign, a
quality-weight redesign, and a latent E2 sign-path bug fix discovered during the same review.
Sequence with 091 so the corpus only needs to be re-run once for both fixes.
**Benefit:** Activates a fully dead code path (`ic_signs` sign-correction in `compute_alpha_score`
has never fired — every eligible feature has always been `ic_sign = +1`) and roughly doubles the
candidate feature universe (788 significantly-positive vs 568 significantly-negative pooled
FDR-passing cells, pre-walk-forward). Tempered claim, not overclaimed: this is a correctness win
that lets FRAME-04 properly arbitrate whether short-side edge exists — it is not yet evidence
that P&L improves (the long side itself is currently ~breakeven gross per todo 093's partial
data).
**Risk:** low to fix correctly once designed; high if shipped without shadow-mode validation,
since it changes eligibility membership, quality-weight computation, and the champion score
distribution simultaneously.
**Scope note (2026-07-12, housekeeping audit):** while redesigning the eligibility WHERE clause
here, also pick up the undone half of `.planning/todos/completed/031-renaissance-ic-gate-redesign.md`
— that design specified `passes_walkforward` should become a continuous weight-decay factor
(`alpha.ensemble.wf_consistency_factor`, already seeded live at 0.5 but unused by any code) rather
than the hard `AND passes_walkforward = true` binary gate this file's own lines 69/94 quote. Same
clause, same PR, don't split it into a fourth eligibility-editing pass.
---

# 094 — `alpha_events`/`alpha_frames` are 99.99% long: two sign-asymmetric gates exclude every
contrarian feature before it ever reaches ensemble weighting

**Found:** 2026-07-10, while explaining the `CounterfactualTracker --backfill` mechanics (todo
093) to the project owner and checking the resulting long/short split as a sanity check.
**Root cause corrected:** 2026-07-11, via a Fable architectural review of the original diagnosis,
independently verified against the live DB before accepting it.

## The finding

Across the full `alpha_frames` backfill (11,813,874 rows, todo 093):

```
direction | count
----------+----------
long      | 11,812,395
short     |      1,479
```

Same split exists upstream in `alpha_events` (`alpha_publisher` is the sole writer) — not
introduced by `AlphaFrameWriter`/`CounterfactualTracker`, baked into the emission layer itself.
100% of the 1,479 shorts are on `tf='15m'` (zero on `5m`/`1d`); spread across ~15+ symbols, no
single-symbol artifact; regime distribution inverted from expectation (`high_bull` produces more
shorts than `low_bear`). Full original detail in git history of this file.

`alpha_publisher.py`'s emission SQL gate was checked and confirmed symmetric by construction —
same threshold/CI/cost-hurdle logic applied to both signs. The asymmetry is not there.

## Corrected root cause (2026-07-11)

**The original diagnosis (below, "Superseded finding") correctly identified a real asymmetry in
`compute_quality_weight()` but misattributed it as *the* cause.** A Fable review, verified against
the live DB before being accepted, found the actual exclusion happens two gates earlier, and is
total, not a magnitude compression:

**Gate 1 — ensemble eligibility filter** (`services/ensemble_trainer.py:92-96`,
`_ELIGIBILITY_BASE_WHERE`):
```sql
symbol = 'POOLED' AND is_pooled = true AND regime != '_pooled'
  AND ic_ci_lower > 0
  AND reliable = true AND ic_sharpe_hac IS NOT NULL
  AND passes_walkforward = true
```
`ic_ci_lower > 0` is applied to the **signed** Fisher-z CI (`_fisher_z_ci` in
`src/intelligence/statistics/ic_math.py:50-71`, returns bounds around the raw signed IC — the
same CI machinery todo 091 flags as possibly miscalibrated, a second reason this and 091 share a
trust boundary). A feature with IC = -0.05, CI = [-0.07, -0.03] — a significant, reliable
**contrarian** feature — has `ic_ci_lower = -0.07` and is excluded before `feature_selector.py`
ever sees it.

**Gate 2 — walk-forward criterion** (`services/ic_engine.py:812-814`):
```python
wf_pass_count_nd = (fold_ic_arr > 0).sum(axis=0)
passes_wf_nd = wf_pass_count_nd == walk_forward_folds
```
A fold "passes" only if `fold_ic > 0`. A perfectly consistent contrarian feature (negative IC in
every single fold — the *most* reliable kind of contrarian signal) fails 0/N by construction. The
gate measures "consistently positive," not "consistently signed."

**Verified directly against the live DB (2026-07-11, this session, independent of Fable's own
query):**
```sql
SELECT ic_sign, count(*)
FROM feature_ic_scores
WHERE symbol = 'POOLED' AND is_pooled = true AND regime != '_pooled'
  AND ic_ci_lower > 0 AND reliable = true AND ic_sharpe_hac IS NOT NULL
  AND passes_walkforward = true
GROUP BY ic_sign;
```
Result: **1,527 rows, 100% at `ic_sign = 1`. Zero contrarian features have ever passed
eligibility.** `min(ic_sharpe_hac)` among eligible rows is -0.67 — even the small minority that
slip through with a technically-negative window Sharpe (the population the original floor
diagnosis was actually describing) are near zero, nothing like a genuine strong contrarian.

**Consequence — `ic_signs` sign-correction is dead code.** `compute_alpha_score()`
(`src/intelligence/ensemble/alpha_score.py:73`, `dot(weights, ic_signs * feature_values)`) was
built specifically to let a negative-IC feature contribute inversely to its own reading. It has
never fired: the `ic_signs` vector is always all-ones in the E1 pipeline, because every eligible
feature has `ic_sign = +1` by construction of Gates 1-2. The "64,686 `ic_sign=-1` features"
figure from the original diagnosis was the *raw reliable* population (before eligibility
filtering), not the eligible one — a real but genuinely available candidate population (568
significantly-negative pooled FDR-passing cells vs 788 significantly-positive, pre-walk-forward)
that Gates 1-2 currently discard entirely, not merely under-weight.

**The E1-vs-E2 A/B judgment (E2 rejected 20/20 strata LOSS, E1 champion) tells us nothing about
short-side edge.** E2 consumed the exact same eligibility-filtered, all-positive-sign rows. Its
sign-symmetric `Σ⁻¹·IC` machinery (`mean_variance_weights()`) never received a negative-IC input
to demonstrate its intended advantage on. The judgment must be re-run once the input universe
becomes genuinely sign-symmetric — the prior result doesn't validate or invalidate anything about
this fix.

**A newly discovered, related bug: E2's downstream path would silently re-break this even after
Gates 1-2 are fixed.** Once negative-IC features become eligible, `ic_shrunk` fed to
`mean_variance_weights()` is signed, so its output (`mv_raw`) can be negative — but
`ensemble_trainer.py:260` then runs `derive_weights(mv_raw, max_feature_weight)`, and
`derive_weights()`'s own `> 0` filter (`weights.py:51`) would silently zero every contrarian
feature back out of E2 specifically. This must be fixed as part of the same effort, or the
post-fix E1-vs-E2 rerun is invalid. Tracked as sub-item in "Proposed next steps" below (folded
into this todo, not split out — same fix effort, same corpus re-run).

### Superseded finding (2026-07-10, kept for record — real but not the primary cause)

The original diagnosis found `compute_quality_weight()` (`src/intelligence/ensemble/
feature_selector.py:31-38`, `qw = ic_ci_lower * max(sharpe_floor, ic_sharpe)`) compresses any
feature with `ic_sharpe < sharpe_floor` (0.05 default) — including negative values — to the same
floor weight. This is real and affects the ~57-row population of "inconsistent" features (full-
sample IC significantly positive, i.e. they DID pass Gate 1, but window-level `ic_sharpe_hac` is
slightly negative — a decay/instability signature, not a contrarian one). The originally-proposed
fix (`abs(ic_sharpe)` magnitude preservation) was **reviewed and rejected**: applying `abs()` to
this population would up-weight features by how much their recent-window behavior *disagrees*
with the direction they'd actually be traded in (their `ic_sign` is +1 from the full-sample IC,
so no sign-flip occurs) — i.e. it would give conviction-sized weight to signals that look like
they've decayed, exactly backwards. This ~57-row population needs its own, separate diagnostic
(is their positive full-sample IC concentrated in an early, now-decayed subperiod? — see next
steps) — likely floor-or-exclude, not magnitude-preserve. Do not implement the original
`abs(ic_sharpe)` fix as written.

## Recommended fix (supersedes the original "Recommended fix" section)

Make the significance pipeline sign-symmetric end to end, working in "IC\*" (sign-adjusted) space
throughout rather than patching one formula:

1. **Eligibility** (`ensemble_trainer.py:92`, `_ELIGIBILITY_BASE_WHERE`): replace `ic_ci_lower >
   0` with "CI excludes zero on the feature's own side" —
   `(ic_sign = 1 AND ic_ci_lower > 0) OR (ic_sign = -1 AND ic_ci_upper < 0)`.
2. **Walk-forward** (`ic_engine.py:813`): a fold passes if `fold_ic * ic_sign > 0` (sign
   consistency with the full-sample estimate), not `fold_ic > 0`. Requires a full `ic_engine`
   re-run — the stored `wf_pass_count`/`passes_walkforward` for any currently-excluded
   negative-IC feature is meaningless (it counted positive folds, a criterion that structurally
   cannot be satisfied by a true contrarian).
3. **Quality weight** (`feature_selector.py:38`): `qw = (ic_sign * nearest_ci_bound) *
   max(sharpe_floor, ic_sign * ic_sharpe)`. A true contrarian has `ic_sign * ic_sharpe > 0` and
   its magnitude is preserved naturally through the existing floor logic — no `abs()`, no
   conflation with the "inconsistent" population, `derive_weights`'s "positive-input" contract
   stays intact.
4. **Score time**: `compute_alpha_score`'s existing `ic_signs` multiplication is unchanged — it
   finally starts doing the job it was built for.
5. **E2 sign path**: feed `mean_variance_weights()` sign-adjusted `ic_sign * ic_shrunk`, keep its
   output in positive-magnitude space (matching E1's convention), apply sign once at score time
   — same convention as E1, so the post-fix E1-vs-E2 rerun is comparing like with like.

**Interaction audit (from the same review, do not skip):**
- `cluster_deflate_weights()` clusters on `abs(corr)` — already correct for the signed world (two
  anti-correlated features with opposite `ic_sign` genuinely are one cluster after sign-flip). No
  change needed.
- `derive_weights()`'s stale docstring ("features with non-positive IC Sharpe are excluded") and
  its misleadingly-named `ic_sharpes` parameter (it actually receives `aged_quality_weights`, not
  raw IC Sharpe values) — fix in the same commit as the code change, not left to drift further.
- Emission thresholds (`alpha.quant.threshold.{tf}`) and cost hurdles were implicitly calibrated
  against a score distribution with a 4-23x positive-magnitude skew. A symmetric ensemble shifts
  that distribution materially — re-measure emission volume post-fix, don't assume thresholds
  still mean what they meant before.

**Shadow mode: mandatory, not optional.** This changes champion scoring behavior, eligibility
membership, and score distribution simultaneously — exactly the class of change the project's own
"shadow mode first" principle exists for, and this is the owner's own future live capital. Train
under a new `weight_version`, score in parallel, run frames + FRAME-04 on the shadow stream,
promote only on evidence.

## Proposed next steps

1. **Sequence after 091** (unchanged decision, now with an added reason): both eligibility gates
   are built directly on `ic_ci_lower`/`ic_ci_upper`. If 091 finds the Fisher-z CI is too narrow,
   the entire eligible/candidate population computed here would need to be recomputed anyway —
   fixing eligibility before 091 closes means redoing this work twice. Since the sign-symmetric
   walk-forward requires a full `ic_engine` re-run regardless, sequencing 091 first means **one**
   corpus re-run serves both fixes.
2. Implement the 5-part sign-symmetric redesign above, including the E2 sign-path fix.
3. Diagnostic on the superseded-finding's ~57-row "inconsistent" population: check whether their
   positive full-sample IC is concentrated in an early, now-decayed subperiod. If so, add
   sign-agreement (`ic_sign * ic_sharpe_hac > 0`) as an eligibility condition and exclude them —
   resolves the floor question for this population without needing `abs()`.
4. Fix the `derive_weights()` docstring/parameter-naming drift in the same commit.
5. Ship to a new shadow `weight_version`; run frames + FRAME-04 on the shadow stream before
   promoting.
6. Re-run the E1-vs-E2 A/B judgment on the now-genuinely-symmetric input universe — the prior
   20/20 result was produced on an input where E2's distinguishing capability (sign symmetry) was
   structurally unexercisable, so it doesn't carry forward.
7. Record the fix, the corrected root cause (this supersedes the 2026-07-10 diagnosis), and the
   measured before/after long/short split and candidate-population size in the
   methodology-change-ledger.

**Gate:** sequenced after todo 091 per the project owner's explicit 2026-07-10 decision, reaffirmed
2026-07-11 after this root-cause correction — 091's CI fix and this fix's eligibility redesign
both touch `ic_ci_lower`/`ic_ci_upper`, so one `ic_engine` re-run should serve both.

## Closed 2026-07-21 — HOLD verdict, sign_symmetric stays false

The 5-part sign-symmetric redesign (eligibility gate, walk-forward criterion, quality weight,
E2 sign path) shipped and was trained under a shadow `weight_version`
(`143.1-08-challenger`) against the real champion (`143.1-08-champion`) — the mandatory
shadow-mode validation this todo required, not a smaller stand-in. This is not a marginal or
ambiguous result: the sign-symmetric challenger failed every evaluated criterion decisively —
`c3_sharpe = -4.14`, `c4_max_dd = 3607x` (peak-to-trough on the cumulative-R curve), every
`direction x regime` cell with adequate coverage came back negative for both champion and
challenger. Re-confirmed independently via todo 165's regime-stratified re-evaluation (a
stricter, cell-by-cell re-test built specifically to rule out "the pooled verdict was hiding a
real regime-conditional edge") — same result, same decisive rejection, not merely unchanged
by coincidence.

**Verdict: HOLD.** `alpha.ensemble.sign_symmetric` stays `false`. The E1-vs-E2 A/B judgment
this todo's step 6 called to re-run becomes moot for promotion purposes — the underlying
sign-symmetric/short-inclusive universe itself is decisively rejected regardless of which
weighting method would be applied within it, so there is no live weighting-method question left
to adjudicate on this universe.

Full detail: `.planning/milestones/v3.1-phases/143.1-measurement-and-eligibility-integrity-fisher-z-ci-bootstrap-/143.1-08-SHADOW-VALIDATION.md`.
