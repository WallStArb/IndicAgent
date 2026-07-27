# Edge Source Thesis -- Where Does Our Edge Come From?

**Version:** 1.3
**Status:** draft -- standing document; every claim here is falsifiable and must be revisited
as evidence lands
**Priority:** high -- **T3 passed 2026-07-26** (first thesis on this list to clear its own bar
convincingly); **T5 cleared its canary-leakage check 2026-07-26** (genuinely interesting lead,
not yet a confirmed pass -- independent replication is the next step); T4 remains the only
untested thesis
**Milestone:** standing -- not tied to a phase
**Last Updated:** 2026-07-26
**Tags:** edge, thesis, counterparty, renaissance, falsifiable, first-principles

**Reviewed 2026-07-25** -- re-read in full against todo 179's 2026-07-24 finding (an exhaustive
234-cell regime × symbol_hmm × lookahead-scale sweep for any absolute-direction, regime-
conditional edge in the current champion population). This doc's own T2 falsification
criterion, written 2026-07-01 before that sweep existed, predicted exactly the test that
killed it -- see T2 below. Still the correct standing doc; nothing here is stale, it's now
partially *resolved*. Added candidate thesis T5 (non-linear interaction structure) below,
prompted by the same finding: the one interaction axis the system already models explicitly
(regime × feature) just failed exhaustively, which raises the question of whether the *linear*
combiner is blind to interaction structure the 150 features already contain, independent of
whether more features (Phase 164/165) get added.

**Updated 2026-07-26** -- ran both cheap falsification scripts item 5 (below) recommended
before committing to Phase 164/165. T3 passed decisively; T5 came back with a suspiciously
large uplift that needs one more check before it's trustworthy. See T3/T5 sections below for
full results. Scripts: `scripts/analysis/t3_cross_sectional_long_short_ctf_momentum_check.py`,
`scripts/analysis/t5_nonlinear_combiner_lightgbm_check.py`. **Also caught and flagged a
methodology gap in T2** (below): its falsification ran under cross-sectional regime labels
that were themselves found miscalibrated and fixed the same day (todo 092) -- never
re-verified under the corrected labels through the full production pipeline, which is exactly
what's blocked right now behind todo 183's corpus-recompute halt. T2's death stands as
provisional, not final, until that re-run happens.

---

## The Question Nobody Has Answered

The entire v3.0 stack -- Feature Factory, IC engine, ensemble, frames -- assumes edge exists
in this feature × universe × horizon combination and pours rigor into *measuring* it. No
document states what the edge *is*: a falsifiable claim about **who is on the other side of
the trade and why they are systematically wrong**.

Every durable trading edge is one of a small number of things:
1. **Information** someone else doesn't have (unique data, faster data, better-cleaned data)
2. **Processing** someone else can't do (better models on the same data)
3. **A counterparty constraint** -- someone must trade for non-price reasons (index rebalance,
   fund flows, hedging mandates, tax, margin calls) and pays for immediacy
4. **A behavioral bias** stable enough to persist after being published
5. **A risk premium** -- compensation for bearing a risk others won't (this is beta wearing a
   costume, and it's fine, but it should be named as such, not called alpha)

Renaissance's actual moat was overwhelmingly #1 and #2 at a time when almost nobody else did
either -- data nobody else had cleaned, on instruments nobody else priced carefully. It was
never "better statistical validation of features everyone can compute."

## The Uncomfortable Facts About Our Setup

Stated plainly so they can be argued with, not glossed:

- **The features are public.** All 54 are OHLCV-derived quantities (momentum z-scores, VWAP
  deviation, ATR, calendar position) computable by anyone with a market data subscription.
  Every systematic shop has tested them.
- **The universe is the most efficient corner of the market.** 58 of the most liquid,
  most-studied ETFs on earth. SPY's order book is the most competitive pricing environment
  in existence.
- **The horizons are heavily mined.** 5m-1d is exactly where institutional stat-arb operates.
- **The early evidence is consistent with the skeptical read.** Top qualifying features are
  calendar effects (`quarter_position`, `days_to_month_end`, `dow_sin`) and macro proxies
  (`yield_slope_z`), ICs 0.02-0.08 gross. Calendar anomalies are the most published, most
  arbitraged effects in the literature.

None of this proves there is no edge. It proves the *default hypothesis must be no edge*,
and the burden of proof sits on every positive result -- which is exactly the posture the
gate stack (FDR, shrinkage, OOS, cost hurdle) implements. This doc's job is to name what a
surviving result would actually *be*.

## Candidate Edge Theses (each falsifiable)

### T1 -- Small-scale immediacy provision (counterparty: constrained flow)
At this account size (retail, no capacity pressure), the system can take the other side of
flows too small for institutions to bother with: end-of-day rebalance pressure in
lower-liquidity sector ETFs, overnight-gap mean reversion where market makers widen out.
**Why we might win:** capacity constraints don't bind at this size; institutions leave
crumbs below their minimum ticket. **Falsification:** the surviving cells should
concentrate in the less-liquid half of the universe and around session boundaries; if edge
concentrates in SPY/QQQ mid-session, T1 is wrong.

### T2 -- Regime-conditional persistence (counterparty: unconditional models) -- **FALSIFIED 2026-07-24, under regime labels since superseded -- see caveat below**
Features with zero pooled IC but real conditional IC (the whole stratification premise).
Participants running unconditional models mis-price bars in minority regimes.
**Why we might win:** most simple systematic flows are not regime-conditioned; conditioning
is our one genuine structural bet. **Falsification:** regime-stratified IC must materially
exceed pooled IC for the same features OOS (not just in-sample, where stratification
mechanically inflates cell significance), and the regime labels themselves must pass the
026 validation. If conditional ≈ pooled OOS, T2 is dead and most of the stratification
machinery is measurement theater.

**Result (todo 179, 2026-07-24):** this exact test was run, at full rigor. All 9
cross-sectional regimes × 6 symbol_hmm states × 3 lookahead scales (234 cells, 126 with
sufficient day-cluster coverage), day-clustered bootstrap + BH-FDR. Exactly 2 cells passed
initially (`low_bull`×`trending_down`, 5m, both lookahead scales, `ci_lower` positive). Neither
survived out-of-window replication against 12 independent historical episodes back to 2008 -- critically, the finding didn't even hold in its *own* discovery window once the ensemble's own
`alpha_score > 0` conditioning was removed (`ci_lower` negative at every scale on raw regime
labels alone). **Zero cells, at any granularity tested, show real non-circular positive
expectancy.** T2 is dead by this doc's own pre-registered criterion -- regime conditioning,
as currently implemented (a single categorical stratification dimension feeding a linear
IC-weighted combiner), is not where this system's edge lives. Full trail:
`.planning/todos/pending/179-gate166-concurrent-exposure-diagnostic.md`.

**Caveat, added 2026-07-26, load-bearing:** this 234-cell sweep ran entirely against the
**old, pre-todo-092** cross-sectional regime labels -- the raw-value cuts (`breadth_frac`
0.40/0.60, `curve_z`/`credit_z` ±0.5/0.0) that were themselves found miscalibrated and fixed
*later that same day* (migrations 257/258, `causal_rank.py`). The champion population tested
(`143.1-08-champion`/`run_2025122405150000`) was scored under the old labels; todo 092's fix
has never propagated through the full production pipeline (`ic_engine` → `ensemble_trainer` →
a fresh Gate 1/2 verdict) -- that recompute is the one currently halted behind
`.planning/todos/pending/183-ic-engine-max-cell-rows-breached-by-todo092-rebalance.md`. A
partial, offline re-check under the *new* labels (raw-return regime sweep, not the full
pipeline) surfaced `high_bear` conflating buyable-dip vs. structural-bear regimes -- a new
lead, not a re-confirmation of this falsification. **T2's death should be read as "the
categorical-regime-stratification mechanism, as tested under the labels live at the time,
found nothing" -- not yet re-verified under corrected labels.** Separately, this test also
only covers the feature set live as of 2026-07-24 (through Phase 163, with the 17 new
structural columns still incomplete on historical rows per todo 176) -- it says nothing about
features Phase 164/165 hasn't built yet; no corpus rerun was needed for that because there was
no new feature to test. Re-run todo 179's sweep in full, through the production pipeline,
once todo 183 resolves and the todo 092 recompute completes, before treating T2 as a final
verdict rather than a provisional one.

**What T2's death does NOT prove:** that regime information is worthless, or that no
interaction effect involving regime exists -- only that a *linear*, single-dimension,
categorical treatment of it doesn't clear a bar. See T5 below.

### T3 -- Cross-sectional relative mispricing (counterparty: single-name flows) -- **PASSED 2026-07-26, PRODUCTIONIZED AND GATED 2026-07-27**
Individual ETFs get pushed off fair relative value by idiosyncratic flows (sector rotation,
thematic retail); the *ranking* across 58 correlated instruments mean-reverts even when no
single instrument is predictable directionally. **Why we might win:** relative-value noise
cancellation is statistically much easier than directional prediction; this is the
lowest-IC-requirement thesis on the list. **Falsification:** cross-sectional long-short
spread portfolios built from feature rankings must show positive net return where per-symbol
directional trades on the same features don't. Requires the cross-sectional rank IC measurement
mode (`docs/research/measurement-ic-engine.md`, "Addendum: Cross-Sectional Rank IC") to even
test. If the spread portfolio is no better than directional, T3 is dead.

**Result (`scripts/analysis/t3_cross_sectional_long_short_ctf_momentum_check.py`, 2026-07-26):**
equity/15m, `ctf_momentum` (the strongest, most cross-regime-consistent-sign symbol-varying
feature per a live `feature_ic_scores` query), top/bottom decile, dollar-neutral,
day-clustered bootstrap (`services/counterfactual_tracker.py`'s `frame_gate_passes`,
verbatim -- no new statistics). **Passed decisively at both lookahead scales:**

| Scale | n_bars | mean spread | ci_lower | shuffled-null P(null ≥ observed) |
|---|---|---|---|---|
| fast (lookahead=1) | 24,924 | 0.000587 | 0.000562 | 0.0000 |
| slow (lookahead=20) | 24,924 | 0.001115 | 0.000969 | 0.0000 |

The shuffled-ranking null (permute feature-to-symbol assignment within each bar, rebuild the
identical decile construction, 40 draws) is the required guard against this being a pure
dollar-neutral-bucketing artifact -- it isn't; the real result clears every null draw. This is
the first thesis on this list to clear its own pre-registered bar convincingly. Gross spread
only (no cost model applied yet) -- before treating this as an actionable finding it still
needs: (1) the todo 030 cost-hurdle treatment applied to the spread construction specifically
(a long-short spread's cost dynamics differ from a directional trade's), and (2) scoping
`docs/research/trade-construction-layer.md` as a real phase rather than a one-off script.

**Productionized and gated (Phase 167, 2026-07-27):** the falsification script became a real
service, `services/cross_sectional_spread_tracker.py`, and both items above are now done. A
full 2006-2026 backfill populated `construction_spreads` (24,924 bars), and both live
Validation Gates ran against the real OOS population with the cost-hurdle sweep applied at
every tier: Gate 1 (shadow spread Sharpe, net of cost) PASSED, and Gate 2 (attribution
honesty -- is the P&L a disguised static factor tilt) PASSED. Full numeric detail, the binding
Gate 1 pass rule, and the Gate 2 retrospective-versus-causal caveat are recorded in
`docs/research/trade-construction-layer.md`'s Validation Gates section (not duplicated here --
one doc owns the gate numbers). **Both gates clearing means the Phase 156-159
execution/sizing chain's stated precondition is now met for this construction** -- unlike
Phase 148's per-symbol directional construction, which passed Gate 1 but failed Gate 2.

### T4 -- Horizon arbitrage at 1h/1d (counterparty: nobody -- risk premium)
The honest fallback: at longer horizons with low turnover, small conditional tilts
(vol-conditioned momentum, flight-to-quality) earn modest risk-adjusted returns that are
partly repackaged risk premia. **Why we might win:** we don't need to win against anyone;
we need to harvest systematically without behavioral errors. **Falsification:** returns
should survive but shrink substantially when regressed against standard factor exposures.
This thesis caps expectations at "good systematic beta," which is a legitimate but
different product.

### T5 -- Non-linear interaction structure (counterparty: linear-model participants) -- candidate, added 2026-07-25
The ensemble combiner (`ensemble_trainer.py`) is a linear, shrunk-IC-weighted sum of
per-feature marginal predictive power. It can express "feature X predicts returns" but
structurally cannot express "feature X predicts returns only when feature Y crosses a
threshold" -- any conditional/interaction structure across the 150 features is invisible to
it by construction, the same way T2's single categorical regime axis was one narrow,
already-tested instance of exactly this blind spot. **Why we might win:** this is a specific,
named processing advantage (per the "deliberately NOT on this list" rule below) -- not "our ML
is better" in general, but "the current combiner is linear and 150 features have 11,175
pairwise-interaction slots it never evaluates." **Falsification:** a non-linear combiner
(gradient-boosted trees or a shallow net) over the identical `feature_vectors`/
`forward_returns` corpus, evaluated with the same walk-forward OOS discipline, day-clustered
bootstrap CI, and BH-FDR correction as everything else in this doc, must show a statistically
significant Sharpe/IC uplift over the existing linear ensemble on the *same* features. If it
doesn't, T5 is dead -- the bottleneck isn't the combiner's linearity, which strengthens the
case for either T3 (construction, not modeling) or that this feature set genuinely has no
edge to extract regardless of how it's combined. Full design and overfitting controls:
`docs/ideas/measurement-nonlinear-interaction-combiner.md`.

**Result (`scripts/analysis/t5_nonlinear_combiner_lightgbm_check.py`, 2026-07-26): canary-leakage
check clears this specific failure mode -- genuinely interesting, still not a confirmed pass.**
Equity/1h, shallow regularized LightGBM (200 trees, depth 4, walk-forward folds via
`ic_math.py`'s `build_walk_forward_folds`, 24-bar embargo), compared against `ctf_momentum`
alone on identical OOS rows. During development this run already caught one real leak: naive
pooled training showed mean_ic≈0.30 with 80/80 symbols passing, traced to the tree implicitly
learning each ETF's own persistent long-run drift (a fixed-membership factor-exposure leak, not
bar-level signal) -- fixed by subtracting each symbol's own causal (shift(1), expanding) mean
return before training/measuring. **After that fix, the tree still comes back at mean OOS
point_ic=0.30 (80/80 symbols pass CI) vs. `ctf_momentum`'s 0.09 (79/80 pass)** -- a ~3.4x
uplift, and a within-bar_ts cross-sectional-neutral decomposition confirms it isn't purely a
common-market-factor artifact (tree: point_ic=0.258, `ci_lower`=0.254; feature: point_ic=0.080,
`ci_lower`=0.076).

**Canary-leakage check (todo 184, `scripts/analysis/t5_canary_leakage_check.py`, 2026-07-26):**
reran the identical walk-forward pipeline with the corpus's 5 built-in leakage canaries included
as features. Negative controls (`canary_constant`, `canary_near_constant`,
`canary_noise_gaussian`, `canary_noise_uniform`) all come back clean by the calibrated,
unambiguous statistic -- standalone per-symbol IC, not gain importance, which turned out to be
poorly discriminating in this shallow/152-feature regime (median real feature's own gain
importance is only 2.0, barely above what a noise column gets by chance -- two rounds of
tuning an importance-based threshold produced misleading verdicts before this was caught and
the check was rebuilt around IC instead). All 4 negative controls: 0/10 symbols clear
`ci_lower>0`, mean IC negative or (`canary_constant`) correctly undefined (zero variance).
`canary_acausal_placebo` (the deliberate look-ahead-leak positive control -- pairs bar i with
bars i+1→i+2's return) shows a small standalone IC (0.016, 5/10 symbols pass) and moderate
gain-importance rank (13.4/152) -- expected, correct behavior for a working positive control
(it genuinely contains future-return information via market autocorrelation), not evidence of
a pipeline bug. **The decisive check: aggregate tree IC is unchanged whether or not this
maximally-leaky feature is available (0.2992 → 0.2999, Δ=+0.0007).** If look-ahead-style
leakage were a meaningful driver of the 0.30 result, adding a stronger version of that exact
leak class should have moved the needle; it didn't.

**Verdict: this specific, well-targeted leak-detection test does NOT explain the 0.30 result as
a look-ahead-leakage artifact.** This does not, by itself, prove T5 is real -- the result is
still ~3x anything else measured in this corpus and warrants continued skepticism (independent
replication across other tfs/periods, per this project's resist-overfitting discipline) before
any production consideration. But the specific failure mode todo 184 was filed to rule out is
ruled out with real evidence, not absence of a red flag. T5 moves from "preliminary, blocked on
this check" to "genuinely interesting lead, not yet a confirmed pass" -- the next legitimate
step is independent replication (a different tf, a different OOS window), not further leakage
investigation on this same result.

### What is deliberately NOT on this list
"Our features are better" (they are public) and "our ML is better" (we run a linear
IC-weighted combiner; the institutions we'd be beating run more) as *unqualified* claims. Any
future thesis of type #2 (processing) must name the specific processing advantage -- e.g.,
regime-conditional structure (T2, now falsified), the AnalogEngine's non-parametric
retrieval, or T5's named linear-vs-non-linear gap -- not assert generic model superiority.

## Breadth Is the Binding Constraint (added 2026-07-01, Simons-lens review)

Whatever thesis survives, the arithmetic above it is fixed: IR ≈ IC × √(effective breadth).
This universe has effective breadth ~8-15 (58 correlated ETFs; the completed ETF Universe Expansion's 79 barely moves it -- more sector funds are more of the same bets). At IC ≈ 0.03 and breadth 10, there is almost
nothing to harvest; at breadth 300, the *same IC* is a business. Medallion's expansion to
higher frequency and thousands of instruments was this arithmetic, not bigger edges. The
concrete long-term move this pipeline is well-positioned for: liquid single-name equities
(e.g., S&P 500 constituents) for cross-sectional work -- the pipeline is symbol-agnostic and
the trade-construction layer is exactly what monetizes wide universes.

**Sequencing decision (operator, 2026-07-01):** universe expansion waits until the end-to-end
system is proven -- pipeline through P&L, validated through the canonical simulator
(`docs/research/platform-canonical-simulator.md`). Multiplying the universe before the path is trusted
multiplies unvalidated machinery, not returns. Breadth is the biggest lever; it is deliberately
pulled last.

## What This Doc Demands From the Roadmap

1. **Todo 030's external cost floor runs first -- DONE 2026-07-01, verdict recorded.**
   5m fast/mid and 15m fast are net-negative-to-marginal against realistic spread (0.26,
   0.84, 0.55 bps gross vs 1-10bp cost floors, on unshrunk IC -- the real numbers are worse).
   1h/1d and the longer-lookahead 5m/15m cells clear comfortably. Todo 030 itself is closed and
   removed from `.planning/todos/`; this paragraph is now the only surviving record of its full
   table. **This kills or badly
   wounds T1 (immediacy provision) as a short-horizon thesis** -- if the crumbs institutions
   leave below their minimum ticket can't clear spread either, T1 only survives at longer
   holds, which changes what "small-scale immediacy" means. T2/T3/T4 are horizon-agnostic
   and unaffected in direction, though T3 (cross-sectional) may specifically rescue some of
   the dead directional cells -- a spread portfolio's cost dynamics differ from a directional
   trade's (see `docs/research/trade-construction-layer.md`).
2. **Every future analysis report tags which thesis its result supports or damages.** A
   qualifying feature is not evidence of edge; it is evidence *for a specific thesis* or it
   is unexplained (and unexplained results get the skeptical prior).
3. **T3 requires the PortfolioTrack to be testable at all** -- this is the strongest
   argument for scoping intel-11's PortfolioTrack, stronger than "firms do it."
4. **If, after 142A OOS + cost hurdle, no thesis has supporting evidence** -- the honest
   conclusion is T4-only: reframe the system as systematic conditional risk-premium
   harvesting at 1h/1d, cut the 5m/15m compute, and stop calling it alpha. That outcome is
   a success of the process, not a failure of the project.
5. **Added 2026-07-25, post-T2-falsification.** With T1 mostly killed by the cost hurdle and
   T2 now dead, the live decision is no longer "which thesis wins" in the abstract -- it's a
   concrete choice between three cheap-to-test candidates before committing to Phase 164/165's
   multi-week feature-expansion effort: **T3** (cross-sectional relative value -- construction
   change, no new features, `docs/research/trade-construction-layer.md`, now unblocked since
   Phase 142A's OOS gate cleared 2026-07-22) and **T5** (non-linear combiner -- modeling change,
   no new features, `docs/ideas/measurement-nonlinear-interaction-combiner.md`). Both attack
   the *construction/modeling* side of the failure with the existing 150 features; Phase
   164/165 attacks the *feature* side using the same linear/absolute-direction construction
   that T2 just falsified. T3 and T5 are cheaper to test (reuse existing corpus and
   infrastructure, no multi-week build) and directly target what's actually confirmed broken -- recommend running both before deciding whether 164/165 is warranted at all.
6. **Added 2026-07-26, post-T3-pass.** Both cheap tests from item 5 ran. **T3 passed
   decisively** (see T3 above) -- this is now the strongest evidence-backed candidate on the
   whole doc, and the recommended next move is scoping `docs/research/trade-construction-layer.md`
   as a real phase (cost-hurdle-adjusted spread construction, then shadow measurement), ahead
   of Phase 164/165. **T5 came back suspicious**, not confirmed -- a 0.30 mean OOS IC is far
   outside this corpus's observed range and needs the canary-leakage check (see T5 above)
   before it can support or damage anything. Until that check runs, T5 is neither evidence
   for nor against committing to Phase 164/165 -- don't cite it either way.

## References

- `docs/intelligence/intelligence-alphaengine.md` -- the epistemology this doc completes:
  "the data discovers confluence" answers HOW to find edge; this doc asks WHY edge should
  exist at all
- `docs/research/measurement-ic-engine.md` -- Cross-Sectional Rank IC addendum (T3's test
  vehicle; retired from `intel-11`, see `docs/research/archive/intel-11-dual-system-discrete-vs-portfolio.md`)
- Todo 030 (cost-hurdle APR calibration) -- the first falsification pass against realistic cost
  floors; closed and removed from `.planning/todos/`, its result summarized in this doc above
- `docs/plans/archive/2026-06-29-feature-scoring-beyond-ic.md` -- marginal contribution / shrinkage
  (the machinery that keeps thesis evidence honest)
- `.planning/todos/pending/179-gate166-concurrent-exposure-diagnostic.md` -- T2's falsification
  evidence, full 234-cell sweep and historical replication check
- `docs/research/trade-construction-layer.md` -- T3's construction and validation design
- `docs/ideas/measurement-nonlinear-interaction-combiner.md` -- T5's design and overfitting
  controls (new, 2026-07-25)
- `scripts/analysis/t3_cross_sectional_long_short_ctf_momentum_check.py` -- T3's falsification
  script and 2026-07-26 pass result
- `scripts/analysis/t5_nonlinear_combiner_lightgbm_check.py` -- T5's falsification script and
  2026-07-26 preliminary (pending canary check) result
