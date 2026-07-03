# Feature Scoring Beyond IC

**Archived 2026-07-02.** Marginal contribution (0a), shrinkage (0b), and calibration (0c)
carried into `docs/ideas/intel-15-measurement-engine.md`'s "Measurement Gaps" section. The 0b
finding is time-sensitive: `ic_shrunk` (the column Phase 142B.1's E1 variant is specced to
consume) does not exist yet — todo 029 is still pending. Kept here for the full method detail
(residualization, empirical-Bayes shrinkage formula, Brier/reliability calibration) not
reproduced there.

Date: 2026-06-29
Status: OPEN — discovery backlog; IC remains the foundation; these extend it
Updated: 2026-07-01 — council refinement pass. Added the three missing layers (marginal
contribution, shrinkage, calibration), fixed two technical flaws in the original proposals
(MI's positive bias, breadth's independence assumption), tied scoring to the cost hurdle.
Companion concepts: `docs/ideas/intel-10-confluence-detection-persistence-layer.md` applies
the same shrinkage/calibration/effective-N discipline at confluence grain.

Renaissance Council analysis of what IC measures, what it misses, and what complementary
methods can live alongside it to build a richer picture of feature quality.

---

## What IC Is Actually Measuring

Spearman IC answers one specific question: does the rank ordering of feature values across
bars predict the rank ordering of future returns? It measures a monotone relationship in
ranks. Everything else -- magnitude, non-linearity, interaction effects, marginal value
against the existing ensemble, regime shifts, consistency across assets -- is invisible
to IC.

Simons didn't optimize IC. He optimized prediction. IC is one proxy for prediction
quality, and a narrow one.

**The organizing question for every method below:** does it change a decision? A score
that doesn't alter a weight, a promotion, or a demotion is dashboard decoration. Each
method's "Role" names the decision it feeds.

---

## The Three Missing Layers (added 2026-07-01)

These are ordered first because they correct how ALL other scores are consumed, not just
add new ones.

### 0a. Marginal Contribution (the most important score in this doc)

**What every standalone score misses:** a feature's value to the system is its
contribution *conditional on the features the ensemble already uses*, not its standalone
quality. A feature with IC = 0.06 that is 0.9-correlated with an existing active feature
adds almost nothing; a feature with IC = 0.02 orthogonal to everything adds a genuinely
new bet. Standalone IC cannot distinguish these. This is the standard institutional test
-- "does this add anything to the book" -- and it is absent from the current pipeline
(the collinearity clustering from Phase 140 controls redundancy at selection time but
does not produce a marginal-value score).

**Metric:** partial IC -- Spearman IC of the feature's residual after regressing out (in
ranks) the currently-active feature set for that (symbol, tf, regime) cell. Equivalent
frame: out-of-fold incremental R² of the ensemble with vs. without the feature.

**Role:** promotion and weighting. A feature earns `active` on marginal lift, not
standalone IC. This is also gate 1 of intel-10 at feature grain -- same concept, same
machinery, build once.

**Coexistence:** new column `partial_ic` on `feature_ic_scores`, computed in the same
pass (residualization against the active set loaded from the Feature Registry).

**APR keys:** `alpha.ic.partial_active_set_max` (cap on conditioning set size; large
conditioning sets make the residual noisy)

### 0b. Shrinkage (selection-bias correction on every persisted estimate)

**What every raw score misses:** all of these scores are computed on features that were
*searched for*. The winners of any search look better in-sample than they are -- the max
of N noisy estimates is biased upward by construction. An ensemble weighter consuming raw
IC estimates systematically over-allocates to lucky cells and the live edge undershoots
the backtest everywhere. This is not a caveat; it is a predictable, correctable bias.

**Method:** empirical-Bayes shrinkage. Shrink each cell's IC toward the cross-sectional
prior (the mean IC of its feature family × regime × tf peer group), with shrinkage weight
set by effective sample size: `ic_shrunk = w * ic_raw + (1 - w) * ic_prior` where
`w = n_eff / (n_eff + k)` and `k` is calibrated so that out-of-fold, shrunk estimates
predict realized next-window IC better than raw estimates do. That out-of-fold check is
the acceptance test for the whole mechanism -- if shrinkage doesn't improve next-window
IC prediction, the implementation is wrong.

**Role:** the ensemble weighter reads `ic_shrunk`, never `ic_value`. Raw values stay in
the table for diagnostics.

**Coexistence:** new columns `ic_shrunk`, `shrinkage_weight` on `feature_ic_scores`;
batch step after the IC pass, before ensemble_trainer reads.

**APR keys:** `alpha.ic.shrinkage_k` [initial_estimate, ML learning target]

### 0c. Calibration (is the magnitude estimate honest?)

**What IC and even R²_OOS miss:** whether the *numbers* the system persists can be
trusted, not just whether the ranking is right. If features (or the ensemble score built
from them) imply an expected return, calibration asks: across many bars, did bars with
predicted E[R] in the top quintile realize returns matching that prediction? Reliability
curve + Brier score for the directional claim. IC says the ordering correlates;
calibration says the estimate is numerically honest -- the property position sizing
actually requires.

**Role:** gate between "ranks well" and "may drive sizing." An uncalibrated score can
rank; only a calibrated score can size. Also the decay signal with the best
signal-to-noise: calibration drift on live data (rolling Brier degradation) detects a
dying edge faster than waiting for IC to cross a threshold.

**Coexistence:** ensemble-level first (calibrate `alpha_score` against realized
executable returns -- feeds Phase 142A directly), feature-level only for features that
graduate to sizing inputs.

**APR keys:** `alpha.calibration.min_eff_n`, `alpha.calibration.brier_alert_delta`
[both initial_estimate]

---

## Complementary Methods and What They Add

### 1. Mutual Information (MI)

**What IC misses:** Non-monotonic relationships. A feature that predicts high returns
when it's either very high or very low (U-shaped) has zero Spearman IC because the rank
correlation is flat. MI captures any statistical dependence -- linear, U-shaped, threshold
effects, regime-conditional sign flips.

**Technical correction (2026-07-01):** MI estimators are biased upward at finite N and MI
is non-negative by construction -- there is no "zero means nothing" reference point the
way a correlation has. Raw MI values are therefore uninterpretable without a null. Every
MI score must be reported as an excess over a permutation null (shuffle returns within
regime, re-estimate MI, repeat; report `MI_excess = MI_obs - MI_null_mean` with a
permutation p-value), and those p-values enter the same corpus-level BH-FDR as IC
p-values -- MI is a second search over the same feature space and consumes
multiple-testing budget accordingly. Without this, MI will "discover" information in
every feature.

**Role:** Discovery layer alongside IC. IC finds monotone edges; MI finds all edges.
Features that pass MI-excess-FDR but fail IC contain genuine non-monotone structure --
they deserve a transform (threshold model, sign-conditional weighting, |x| or x²
re-encoding as a new candidate feature through the normal pipeline), not direct
ensemble entry. MI never feeds a weight; it feeds the feature-candidate queue.

**Coexistence:** `feature_ic_scores` stays as-is for the ensemble weighter. MI sits in
`feature_mi_scores` as a discovery tool.

**Implementation:** k-NN entropy estimator (Kraskov et al.) over the same subsampling
discipline as IC (stride = lookahead, non-overlapping); permutation null per cell.

**APR keys:** `alpha.mi.k_neighbors`, `alpha.mi.min_reliable_n`,
`alpha.mi.n_permutations` [all initial_estimate]

### 2. IC Decay Curve (Predictive Half-Life)

**What IC misses:** The temporal structure of prediction. IC at four fixed lookaheads
(fast/mid/slow/extended) is measured independently. The *shape* of IC across lookaheads
is itself a signal:

- Decays fast (high at fast, near zero at mid): mean-reversion feature. Trade quickly,
  hold briefly.
- Builds slowly (low at fast, peaks at slow): momentum feature. Trade on confirmation,
  hold longer.
- Flat across lookaheads: structural feature.
- Negative at fast, positive at slow: microstructure noise obscuring a real
  longer-horizon signal.

**Technical correction (2026-07-01):** fitting `IC(h) = IC0 * exp(-h / tau)` to four
points is under-determined -- the tau point estimate will carry spurious precision, and
two of the four shapes above (flat, sign-flip) are not exponential at all. Do shape
*classification* first (which of the four archetypes, by sign pattern and peak location),
and fit tau only within the decaying archetype, reported with a bootstrap CI. A tau CI
spanning [2, 40] bars is the honest and common outcome at four lookaheads; downstream
consumers (hold_max_bars calibration, cross-scale combination) must handle "shape known,
tau uncertain."

**Role:** Understanding layer feeding two decisions: the ensemble weighter's cross-scale
combination (don't combine fast-decay and slow-decay features 1:1) and Phase 142A's
`hold_max_bars` calibration. Also a refinement input to Phase 143's decay monitor
(half-life as context for the flat IC-Sharpe threshold).

**Coexistence:** Derived from existing `feature_ic_scores`. Batch script writes
`feature_decay_profiles` (archetype label + tau + tau CI where applicable).

**APR keys:** none (derived metric)

### 3. Out-of-Sample R² (Predictive R², R²_OOS)

**What IC misses:** Return magnitude. IC measures rank correlation -- it says nothing
about whether the feature explains return *magnitude*. A feature that perfectly ranks the
top and bottom decile but misranks everything in between has high IC. R²_OOS measures
what fraction of return variance the feature explains out-of-sample. Position sizing
scales with predicted magnitude, not rank; Kelly's "Empirical Asset Pricing via Machine
Learning" (2019) uses R²_OOS as the primary metric for this reason.

**Formula:** `R²_OOS = 1 - SS_res / SS_tot` with the historical mean return as benchmark.
Negative R²_OOS means worse than predicting the mean -- the common case for single
features at these horizons; expect values in the 0.001-0.01 range for real edges, and
treat the *sign and stability* of R²_OOS as the signal, not its magnitude.

**Role:** Validation alongside IC; precursor to calibration (0c). R²_OOS says magnitude
is explained; calibration says the magnitude estimate is honest. A feature needs both
before it touches sizing.

**Coexistence:** column on `feature_ic_scores`, computed in the same pass.

**APR keys:** none

### 4. Cross-Symbol IC Consistency (Breadth-Adjusted Quality)

**What IC misses:** The Fundamental Law of Active Management: `IR = IC × √(Breadth)`,
where breadth is the number of **independent** bets.

**Technical correction (2026-07-01):** the original metric
`IC_breadth = IC_mean × √(n_consistent_symbols)` overstates breadth badly, because the
58 ETFs are not 58 independent bets -- XLK/SMH/QQQ/VUG are one bet wearing four tickers.
Counting symbols where `ic_ci_lower > 0` measures universe coverage, not breadth. Use
**effective breadth**: `N_eff = (Σλ_i)² / Σλ_i²` over the eigenvalues of the symbol
return correlation matrix (or the same formula over the feature's per-symbol signal
correlation matrix, which is more precise and only slightly more work). Then
`IC_breadth = IC_mean_shrunk × √(N_eff_consistent)`. For this universe expect N_eff in
the 8-15 range, not 58 -- the difference is a ~2x error in implied IR, which is the
difference between a fundable edge and noise. Note the codebase already computes
effective-N machinery in the AnalogEngine correlation service design (ANALOG-07); reuse
the concept, same math.

**Role:** Sizing input for the ensemble weighter. Features with genuinely broad edges
(high N_eff-adjusted breadth) get more weight in a multi-asset portfolio.

**Coexistence:** derived from existing `feature_ic_scores` + a symbol correlation matrix;
materialized view or computed at weight time.

**APR keys:** none (derived)

### 5. PnL Attribution (Realized Alpha Validation)

**What IC misses:** IC is a statistical proxy for alpha. PnL attribution is actual alpha.
The distinction bites when: transaction costs eat a real IC edge; the feature works in
calm regimes and blows up in tails; or the feature has positive IC but zero marginal
contribution (now caught earlier and cheaper by 0a -- PnL attribution remains the
*production* backstop for the same failure, 0a is the *pre-production* screen).

**Role:** Production demotion layer. IC earns a feature into the corpus; PnL attribution
demotes features that pass IC but fail in production. Positive IC + negative
counterfactual PnL attribution over 90 days → ensemble weight decayed regardless of
historical IC.

**Implementation:** Requires feature-level decomposition of `counterfactual_pnl_r`
(currently per signal, not per feature) -- Shapley values or a simpler contribution
heuristic. Non-trivial.

**Gate:** Requires live alpha emission and 90+ days of frames (Phase 142B+). Lowest
priority in this doc, correctly.

---

## Cost-Awareness (binds all of the above)

Every score in this doc is measured gross. The decision-relevant quantity is net: a
feature whose shrunk, calibrated edge cannot clear the transaction-cost floor (todo 030)
at its own decay horizon is research, not a weight. Once todo 030 lands, the promotion
gates here read net-of-cost estimates -- specifically, the shrunk E[R] implied at the
feature's tau-classified horizon vs. the cost hurdle for that tf. Gross scores stay in
the tables; promotion reads net.

---

## How They Coexist

| Metric | Question | Layer | Table |
|---|---|---|---|
| Spearman IC | Does rank order predict rank order? | Discovery | `feature_ic_scores` (existing) |
| Mutual Information (excess over null) | Any dependence IC can't see? | Discovery → candidate queue | `feature_mi_scores` (new) |
| **Marginal contribution (0a)** | Does it add anything to what we have? | **Promotion** | `partial_ic` column |
| **Shrinkage (0b)** | How much of the estimate is selection luck? | **All consumers** | `ic_shrunk` column |
| IC decay curve | At what horizon, via what mechanism? | Understanding | `feature_decay_profiles` (new) |
| R²_OOS | How much magnitude is explained? | Validation | column on `feature_ic_scores` |
| **Calibration (0c)** | Is the persisted number honest? | **Sizing gate + decay signal** | ensemble-level first |
| Effective-breadth consistency | How many independent bets is this edge? | Sizing | derived + correlation matrix |
| PnL attribution | Did trading on it make money net? | Production | derived from `trade_frames` |
| Trailing IC (todo 028 P1) | Is it still working now? | Production | `ic_trailing_series` (new) |

The ensemble weighter is the consumer. Today it reads raw IC. The full system reads:
`ic_shrunk × effective_breadth`, admitted by marginal contribution, sized only if
calibrated, net of cost, demoted by PnL attribution and trailing IC, with MI as the
discovery net for non-linear edges routed back through the candidate pipeline.

---

## Implementation Order

```
Near-term (derived from existing data, no new compute):
  1. Shrinkage (0b)             -- highest value per unit effort in this doc; a batch
                                   step + 2 columns; immediately corrects every weight
                                   the ensemble computes. Acceptance test: shrunk IC
                                   predicts next-window realized IC better than raw.
  2. IC decay curve (shape classification + guarded tau fit)
  3. Effective-breadth consistency (needs symbol correlation matrix; reuse ANALOG-07 math)

Medium-term (same-pass additions to ic_engine):
  4. Marginal contribution (0a) -- partial_ic column; changes the promotion criterion
  5. R²_OOS column

Medium-term (new compute pass):
  6. MI with permutation null + FDR integration

At Phase 142A (ensemble-level):
  7. Calibration (0c) on alpha_score vs realized executable returns

Post-live (Phase 142B+):
  8. PnL attribution loop
```

Ordering rationale: shrinkage moved to the front because it is the only item that
corrects decisions already being made today (ensemble weights from raw selected IC);
everything else adds information, shrinkage removes a known bias.

---

## References

- `services/ic_engine.py` -- current IC implementation
- `docs/plans/2026-06-29-ic-engine-improvements.md` -- IC engine correctness fixes
- `docs/plans/2026-06-20-alphaengine-architecture.md` -- IC methodology spec
- `docs/ideas/intel-10-confluence-detection-persistence-layer.md` -- same
  shrinkage/calibration/effective-N stack at confluence grain; build the machinery once
- ROADMAP.md Phase 146 ANALOG-07 -- existing effective-N design to reuse for breadth
- Kelly, Bryan et al. "Empirical Asset Pricing via Machine Learning" (2019)
- Kraskov, Stögbauer, Grassberger, "Estimating Mutual Information" (2004)
- Todo: `029-feature-scoring-beyond-ic.md`
