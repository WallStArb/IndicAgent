# Regime Stratification Alternatives

Date: 2026-06-29
Status: OPEN — speculative backlog; HMM foundation must be solid first (todo 026)

Renaissance Council analysis of alternatives and complements to HMM regime detection.
The HMM is a means to an end: conditioning IC measurement on regime. The question
is whether there are better or parallel ways to stratify IC.

---

## What the Regime Layer Is Actually Doing

The regime system serves one purpose: **conditioning IC measurement and ensemble weights
on regime**. It answers "what kind of market are we in?" so the IC engine can
answer "does this feature predict returns *in this kind of market*?"

Simons's insight wasn't to build a better regime detector. It was that signals behave
differently across regimes, and that naively pooling observations across all regimes
produces a blurred, attenuated signal. The regime layer sharpens the IC estimate by
stratifying it.

The right framing: each regime method is a **stratification dimension** -- an observable
regime variable used to condition IC measurement. The HMM state is one dimension;
realized vol percentile is another; cross-sectional dispersion is a third. All can
coexist. The IC engine runs stratified by any combination, and the combination that
maximizes IC separation is learned empirically.

---

## Current Regime Systems

Two independent systems coexist (see MEMORY.md dual regime system):

| System | Service | Table | Labels | Granularity |
|---|---|---|---|---|
| Per-symbol HMM | `regime_writer.py` | `feature_vectors.regime` | 5: trending_down, transition_down, ranging, transition_up, trending_up | Per (symbol, TF) |
| Cross-sectional | `equity_regime_model.py` | `market_regimes` | 9: {low/mid/high}_{bull/neutral/bear} | Market-wide per TF |

The IC engine reads `market_regimes` when `equity_model_enabled=True` -- the 9
cross-sectional labels are the primary IC stratification source.

---

## Naming Gap

The architecture doc defines Layer 1/2/3 (Prediction/Portfolio/Execution), but
sub-components within Layer 1 lack canonical names. The glossary defines `regime` as
"the HMM-classified state" -- but adding parallel stratification dimensions overloads
that term.

**Proposed canonical name for the layer:** `Regime Stratification Layer`
-- the system that classifies each bar into context variables used to condition all
downstream IC estimates and ensemble weights.

**Proposed term for individual methods:** `stratification dimension` -- an observable
regime variable (HMM state, vol percentile, factor regime, dispersion) used as a
conditioning axis for IC measurement. Avoids overloading `regime`.

Current code/glossary misalignment:

| Component | Code | Glossary | Gap |
|---|---|---|---|
| State classification | `regime_writer`, `equity_regime_model` | `regime` (HMM state) | Two services, one concept; no layer name |
| IC stratification source | `market_regimes` table | undefined | No canonical term |
| Stratification dimension | (not a concept) | (not a concept) | Missing entirely |

---

## Alternative / Parallel Stratification Dimensions

### P1 — Realized Volatility Percentile Regime (near-term, highest value)

**What it is:** Classify each bar by its trailing realized volatility expanding percentile
rank. Low vol = one regime; high vol = another. Three buckets (low/mid/high) aligned with
the cross-sectional VIX axis.

**Why it matters:** Volatility is the most economically meaningful regime variable because
it directly controls position sizing (Kelly), spread costs, and mean reversion speed.
Factor relationships are well-documented to flip across volatility regimes. This is a per-symbol
version of the cross-sectional VIX proxy already in `market_regimes`.

**Advantages over HMM:** Causal by construction (expanding rank = no look-ahead bias),
no distributional assumptions, directly observable, stable across re-runs (no
non-convex EM), interpretable.

**Implementation:**
- New column `feature_vectors.volatility_regime` (low/mid/high)
- Expanding percentile rank of `realized_vol` per (symbol, tf) in `regime_writer.py`
- IC engine reads `volatility_regime` as a secondary stratification axis
- APR keys: `alpha.volatility_regime.low_pct` (default 0.33), `alpha.volatility_regime.high_pct` (0.67)

**Schema:** `feature_vectors.volatility_regime VARCHAR` -- same pattern as `feature_vectors.regime`

---

### P2 — Cross-Sectional Return Dispersion

**What it is:** Measure how spread out returns are across the 58-symbol universe on a
given bar. High dispersion = stock-picker's market (idiosyncratic factors dominate). Low
dispersion = macro market (everything moves together, factor exposures swamp selection).

**Why it matters:** This stratification dimension is invisible to per-symbol HMM because
it's a cross-sectional property. A feature's IC in a low-dispersion macro market is
fundamentally different from its IC in a high-dispersion stock-picker's market.

**Implementation:**
- Compute cross-sectional return std across all 58 symbols per bar_ts per TF
- Expanding rank → low/mid/high dispersion label
- Store in `market_regimes` with `asset_class='dispersion'`
- IC engine optional stratification axis: `dispersion_regime`

---

### P3 — Factor Regime (explicit factor labels)

**What it is:** Classify each bar by which factor is driving cross-sectional returns:
momentum, value, quality, low-vol, growth. Derived from cross-sectional factor portfolio
returns (long top quintile, short bottom quintile per factor), labeled by which factor
had the highest absolute return in the trailing window.

**Why it matters:** HMM learns latent states from price dynamics. Factor regime is
explicit -- it directly labels the economic mechanism driving returns. A feature's IC
may be high in momentum regimes and negative in mean-reversion regimes in a way that
HMM states don't capture, because HMM state boundaries are learned from price dynamics,
not from which factor is in control.

**Implementation:** Requires factor return time series (derivable from the 58-symbol
universe using known ETF factor exposures). Medium effort; medium value until factor
data is richer.

---

### P4 — HMM Variants (improving the HMM itself)

Three variants that preserve the HMM structure but improve it:

**P4a — Input-Output HMM (IOHMM)**
Conditions state transitions on exogenous inputs (VIX, breadth, yield spread). The
transition matrix `A[t]` becomes a function of observed macro inputs rather than a fixed
matrix. More expressive, harder to overfit. State transitions become economically
interpretable -- not just "regime changed" but "regime changed because VIX spiked."

**P4b — Hamilton (1989) regime-switching model**
HMM without the full emission model -- just the switching mechanism. Simpler, more
interpretable than GaussianHMM, backed by 35 years of econometric literature. The
Hamilton model is the standard reference in empirical macro finance; it would be
defensible to any external reviewer in a way that GaussianHMM is not.

**P4c — Factor-augmented HMM**
Observes both per-symbol return and cross-sectional factor returns simultaneously.
States represent joint market conditions rather than per-symbol dynamics.

**Gate:** All P4 variants require empirical evidence that current HMM labels are deficient
(see todo 026 P4a gate). Do not implement until the IC data shows a problem.

---

### P5 — Microstructure Regime (intraday TFs only)

**What it is:** For 5m/15m TFs, classify bars by microstructure state: liquid vs
illiquid, informed flow vs noise flow. Derived from bid-ask spread, OFI imbalance,
and intraday volume profile position.

**Why it matters:** A bar in a liquidity regime with high OFI imbalance is a different
prediction problem than a bar in a noise regime. HMM trained on OHLCV cannot see this.
Microstructure regime is orthogonal to price-dynamics regime.

**Gate:** Requires order flow / bid-ask data infrastructure not currently in place.
Deferred until V2 Microstructure feature vector is built.

---

## Can They Coexist? Yes -- Multi-Dimensional IC Stratification

The right architecture: each stratification method produces independent labels per bar.
The IC engine runs stratified by any combination. A feature's IC profile becomes:

```
IC(feature, symbol, tf, hmm_state, volatility_regime, dispersion_regime, lookahead)
```

**Storage:** The `feature_ic_scores` table gains additional stratification columns.
Or: separate tables per stratification dimension, joined at ensemble weight time.
Recommended: separate columns with NULLs for unused dimensions (extensible, single table).

**Ensemble weighter:** reads IC stratified by the combination that produced the lowest
CI width (most data-efficient stratification) for each feature. The combination is
itself a learned parameter, not a human choice.

**Compute cost:** Each new stratification dimension multiplies the IC engine runtime by
the number of regime labels. Vol regime (3 labels) = 3x. Combined HMM(5) × vol(3) =
15 cells per (feature, symbol, tf, lookahead). With 54 features × 58 symbols × 4 TFs ×
4 lookaheads: 54 × 58 × 4 × 4 × 15 = ~750K cells. Numba JIT (todo 026 P0) is a
prerequisite for this to be computationally feasible.

---

## Implementation Order

```
Gate: todo 026 P0 (Numba JIT) must ship first -- multi-dimensional IC is too slow
      without it.

P1: Realized vol percentile regime     -- 1 session; highest value, lowest risk
P2: Cross-sectional return dispersion  -- 1 session; requires 58-symbol return matrix
P3: Factor regime                      -- 2 sessions; requires factor data pipeline
P4: HMM variants                       -- gated on empirical proof of HMM deficiency
P5: Microstructure regime              -- gated on V2 order flow infrastructure
```

---

## References

- `services/regime_writer.py` -- per-symbol HMM
- `services/equity_regime_model.py` -- cross-sectional 9-regime model
- `docs/plans/2026-06-28-hmm-regime-audit-optimization.md` -- HMM audit (todo 026)
- `docs/plans/2026-06-29-ic-engine-improvements.md` -- IC engine fixes (todo 028)
- `docs/plans/2026-06-29-feature-scoring-beyond-ic.md` -- feature scoring beyond IC (todo 029)
- Hamilton, J.D. (1989) "A New Approach to the Economic Analysis of Nonstationary Time Series"
- Todo: `030-regime-stratification-alternatives.md`
