# Feature Scoring Beyond IC

Date: 2026-06-29
Status: OPEN — discovery backlog; IC remains the foundation; these extend it

Renaissance Council analysis of what IC measures, what it misses, and what complementary
methods can live alongside it to build a richer picture of feature quality.

---

## What IC Is Actually Measuring

Spearman IC answers one specific question: does the rank ordering of feature values across
bars predict the rank ordering of future returns? It measures a monotone, linear-in-ranks
relationship. Everything else -- magnitude, non-linearity, interaction effects, regime
shifts, consistency across assets -- is invisible to IC.

Simons didn't optimize IC. He optimized prediction. IC is one proxy for prediction
quality, and a narrow one.

---

## Complementary Methods and What They Add

### 1. Mutual Information (MI)

**What IC misses:** Non-monotonic relationships. A feature that predicts high returns
when it's either very high or very low (U-shaped) has zero Spearman IC because the rank
correlation is flat. MI captures any statistical dependence -- linear, U-shaped, threshold
effects, regime-conditional sign flips.

**Role:** Discovery layer alongside IC. IC finds monotone edges; MI finds all edges.
Features that pass MI but fail IC contain genuine information but with a non-linear
structure -- they deserve investigation (threshold model, sign-conditional weighting).

**Coexistence:** `feature_ic_scores` stays as-is for the ensemble weighter (which needs
a signed directional signal). MI sits in `feature_mi_scores` as a discovery tool --
surfacing features IC rejects but that contain information IC cannot see.

**Implementation:** `sklearn.feature_selection.mutual_info_regression` or an estimator
based on k-nearest-neighbor entropy estimation (Kraskov et al.). One pass per
(feature, symbol, tf, regime) cell, same subsampling discipline as IC (stride = lookahead,
non-overlapping).

**APR keys:** `alpha.mi.k_neighbors`, `alpha.mi.min_reliable_n`

---

### 2. IC Decay Curve (Predictive Half-Life)

**What IC misses:** The temporal structure of prediction. IC at four fixed lookaheads
(1, 5, 20, 60 bars) is measured independently. The *shape* of IC across lookaheads is
itself a signal:

- IC decays fast (high at 1 bar, near zero at 5 bars): mean-reversion feature, 1-bar
  half-life. Trade quickly, hold briefly.
- IC builds slowly (low at 1 bar, peaks at 20 bars): momentum feature. Trade on
  confirmation, hold longer.
- IC flat across lookaheads: structural feature. Measures something persistent about
  the asset.
- IC negative at short lookahead, positive at long: microstructure noise at short
  horizon obscures a real longer-horizon signal.

**Role:** Understanding layer. Doesn't replace IC measurements; derives richer structure
from them. Informs the ensemble weighter's cross-scale combination logic -- features
with fast decay should not be combined 1:1 with features with slow decay.

**Coexistence:** Derived from existing `feature_ic_scores` data. No new measurement pass.
A batch script computes the decay profile per feature × symbol × regime and stores in
`feature_decay_profiles`. Could also be visualized in the dashboard.

**Implementation:** Fit an exponential decay model `IC(h) = IC0 * exp(-h / tau)` to the
four lookahead measurements. `tau` is the predictive half-life in bars. Features with
`tau < 2` bars are microstructure features; `tau > 40` bars are structural.

**APR keys:** none (derived metric, no tunable parameters)

---

### 3. Out-of-Sample R² (Predictive R², R²_OOS)

**What IC misses:** Return magnitude. IC measures rank correlation -- it says nothing
about whether the feature explains return *magnitude*. A feature that perfectly ranks the
top and bottom decile but misranks everything in between has high IC. R²_OOS measures
what fraction of return variance the feature actually explains out-of-sample.

This matters because position sizing scales with predicted magnitude, not just rank. A
feature that explains 0.1% of return variance is worth less than one explaining 1% even
if their IC is similar. Bryan Kelly's "Empirical Asset Pricing via Machine Learning"
(AQR, 2019) uses R²_OOS as the primary evaluation metric for exactly this reason.

**Formula:** `R²_OOS = 1 - SS_res / SS_tot` where SS_tot uses the historical mean return
as the benchmark. Negative R²_OOS means the feature's predictions are worse than just
predicting the historical mean.

**Role:** Validation alongside IC. IC earns a feature into the corpus; R²_OOS provides
a magnitude-adjusted quality score.

**Coexistence:** Can be added as a column to `feature_ic_scores` -- computed in the same
pass as IC with minimal additional overhead (same data, different calculation). No new
table required.

**APR keys:** none (same data as IC, no new parameters)

---

### 4. Cross-Symbol IC Consistency (Breadth-Adjusted Quality)

**What IC misses:** The Fundamental Law of Active Management states
`IR = IC × √(Breadth)`. Breadth is the number of independent bets. A feature with
IC=0.05 consistently across all 58 symbols provides 58 bets per period. A feature with
IC=0.30 for SPY only provides 1 bet. The second feature needs 36x higher IC to match the
first's IR.

Currently the IC engine computes IC per symbol independently. There is no score for how
*consistent* a feature is across the universe. A feature with mean IC=0.04 and low
cross-symbol variance is more valuable than one with mean IC=0.04 and high variance
(some symbols positive, some negative).

**Metric:** `IC_breadth = IC_mean × √(n_consistent_symbols)` where `n_consistent` is the
number of symbols where `ic_ci_lower > 0`. This is the breadth-adjusted IC quality score.

**Role:** Sizing input for the ensemble weighter. Features with high IC_breadth get more
weight in a multi-asset portfolio because their edge is genuinely broad.

**Coexistence:** Derived from existing `feature_ic_scores` -- a query that aggregates
across symbols per (feature, tf, regime, lookahead). No new compute pass. Could be a
materialized view or computed in the ensemble weighter at weight-calculation time.

**APR keys:** none (derived metric)

---

### 5. PnL Attribution (Realized Alpha Validation)

**What IC misses:** IC is a statistical proxy for alpha. PnL attribution is actual alpha.
The system already has `trade_frames.counterfactual_pnl_r` -- a feature-level PnL signal
waiting to be used as a validation layer.

The distinction: IC answers "did the rank order of this feature predict the rank order of
returns in the training data?" PnL attribution answers "if we had traded on this feature's
signal, did we make money?" These diverge when:
- The IC edge is real but transaction costs eat it.
- The feature works in calm regimes but blows up in tail events.
- The IC is real but the signal is correlated with features the ensemble already uses
  (no marginal contribution despite positive IC).

**Role:** Production demotion layer. IC earns a feature into the corpus; PnL attribution
demotes features that pass IC but fail in production. A feature with positive IC but
negative counterfactual PnL attribution over 90 days should have its ensemble weight
decayed, regardless of its historical IC.

**Coexistence:** Sits above IC in the feature lifecycle. IC is the entry criterion;
PnL attribution is the ongoing validation. The ensemble weighter reads both and applies
a PnL-based multiplier to IC-derived weights.

**Implementation:** Requires the `trade_frames` table to be populated with
counterfactual PnL per feature (currently per signal, not per feature). Feature-level
attribution requires decomposing signal PnL by which features drove the entry. This is
non-trivial -- either use Shapley values or a simpler feature contribution heuristic.

**Gate:** Requires live signal flow and sufficient trade_frames history (90+ days). Lower
priority until v3.0 alpha emission is live.

---

## How They Coexist

Each method answers a different question at a different layer of the feature lifecycle:

| Metric | Question | Layer | Table |
|---|---|---|---|
| Spearman IC | Does rank order predict rank order? | Discovery | `feature_ic_scores` (existing) |
| Mutual Information | Is there any statistical dependence? | Discovery | `feature_mi_scores` (new) |
| IC decay curve | At what horizon and via what mechanism? | Understanding | `feature_decay_profiles` (new) |
| R²_OOS | How much return variance is explained? | Validation | column on `feature_ic_scores` |
| Cross-symbol consistency | How broad is the IC edge? | Sizing | derived from `feature_ic_scores` |
| PnL attribution | Did trading on this make money? | Production | derived from `trade_frames` |
| Trailing IC (todo 028 P1) | Is it still working now? | Production | `ic_trailing_series` (new) |

The ensemble weighter is the consumer of all of these. Today it reads IC. The full system
reads: `IC × breadth_consistency`, gated by PnL attribution, decayed by trailing IC
recency, with MI as a safety net to catch non-linear edges the IC pass rejected.

---

## Implementation Order

```
Near-term (derived from existing data, no new compute):
  - IC decay curve: batch script over feature_ic_scores → feature_decay_profiles
  - Cross-symbol IC consistency: query over feature_ic_scores → breadth score

Medium-term (new measurement pass, additive):
  - R²_OOS: add column to IC engine output (same data, trivial overhead)
  - Mutual Information: new compute pass, feature_mi_scores table

Long-term (production validation, requires live alpha emission):
  - PnL attribution loop: wire trade_frames.counterfactual_pnl_r into feature scoring
```

---

## References

- `services/ic_engine.py` -- current IC implementation
- `docs/plans/2026-06-29-ic-engine-improvements.md` -- IC engine correctness fixes
- `docs/plans/2026-06-20-alphaengine-architecture.md` -- IC methodology spec
- Kelly, Bryan et al. "Empirical Asset Pricing via Machine Learning" (2019)
- Todo: `029-feature-scoring-beyond-ic.md`
