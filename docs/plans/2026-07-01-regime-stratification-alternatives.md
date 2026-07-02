# Regime Stratification Alternatives

Date: 2026-06-29
Informed by: `.planning/research/2026-07-01-v3-architecture-review.md` (Fable 5) — HMM Variants section's structural dependency on Phase 151 added 2026-07-02 per that review.
Status: OPEN — speculative backlog; HMM foundation must be solid first (todo 026)
Updated: 2026-07-01 — three decisions from other docs now bind this one:
- Session Regime downgraded: cheap+safe is not the same as valuable — no case made for
  session effects at this system's swing (not HFT) cadence. It is no longer "evaluate ahead of
  Volume Regime" (see `docs/ideas/2026-07-01-intelligence-lifecycle-backlog-matrix.md`).
- Percentile-rank-first sequencing verdict: any dimension here that has an HMM-engine equivalent
  in `docs/ideas/multi-engine-regime-architecture.md` is built as deterministic
  percentile-rank first; an HMM engine only if that proves insufficient.
- Storage split settled: per-symbol dimensions (Volatility Regime, Volume Regime, Session
  Regime, Skew/Tail Regime) become columns on `feature_vectors` alongside `regime`;
  cross-sectional dimensions (Dispersion Regime, Factor Regime) become rows in `market_regimes`
  under their own group value (`regime_group` after Phase 151 / migration 189).

Updated: 2026-07-02 — dropped this doc's own `P1`-`P8` numbering. It looked like a priority
scheme (todo 026 legitimately uses `P0`-`P4` for priority tiers) but wasn't one here — this
doc's own recommended build order (Volatility Regime → Dispersion Regime → Session Regime →
orthogonality gate → Volume Regime → Skew/Tail Regime → Factor Regime → HMM Variants → Microstructure
Regime) is completely scrambled relative to the old P-numbers, proving they never meant
priority. Worse, the old `P4a`/`P4b`/`P4c` sub-codes collided character-for-character with
`todo 026`'s own (unrelated) `P4a`/`P4b` — same string, two different concepts, in sibling
docs. Every dimension below is now referenced by its descriptive name; short slugs
(`volatility_regime`, `iohmm_variant`, etc.) are used only where a compact cross-reference is
needed, and match the actual planned schema/APR identifiers where one exists.

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

### Volatility Regime (near-term, highest value)

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

### Dispersion Regime — Cross-Sectional Return Dispersion

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

### Factor Regime (explicit factor labels)

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

### HMM Variants (improving the HMM itself)

Three variants that preserve the HMM structure but improve it:

**IOHMM Variant — Input-Output HMM (IOHMM)**
Conditions state transitions on exogenous inputs (VIX, breadth, yield spread). The
transition matrix `A[t]` becomes a function of observed macro inputs rather than a fixed
matrix. More expressive, harder to overfit. State transitions become economically
interpretable -- not just "regime changed" but "regime changed because VIX spiked."

*Relationship to `regime_group` (Phase 151), clarified 2026-07-02:* this variant's exogenous
inputs used to mean "go compute VIX-proxy, breadth, and a curve spread from scratch." They
don't anymore. Phase 151's signal modules produce exactly these series as a side effect of
computing the cross-sectional regime label: `breadth_vol.compute()` returns
`(vix_pct_rank, breadth_fraction)`; `curve_credit.compute()` returns `(curve_z, credit_z)`.
Both are already causal (no look-ahead), already APR-governed, already tested in isolation.
The IOHMM variant's exogenous-input vector is a direct read of these two functions' outputs
(plus whichever other `regime_group` signal modules are enabled) rather than a new engineering
task -- Phase 151 is a prerequisite that makes this variant cheaper to build, not a separate
concern. This doesn't change the gate (still requires todo 026's empirical-deficiency proof
before building anything), but it does mean this variant's cost estimate should assume Phase
151 has already shipped: building it before Phase 151 means re-deriving inputs Phase 151 will
later obsolete.

**Hamilton Variant — Hamilton (1989) regime-switching model**
HMM without the full emission model -- just the switching mechanism. Simpler, more
interpretable than GaussianHMM, backed by 35 years of econometric literature. The
Hamilton model is the standard reference in empirical macro finance; it would be
defensible to any external reviewer in a way that GaussianHMM is not.

**Factor-Augmented HMM Variant**
Observes both per-symbol return and cross-sectional factor returns simultaneously.
States represent joint market conditions rather than per-symbol dynamics.

*Relationship to `regime_group`, clarified 2026-07-02:* "cross-sectional factor returns" was
underspecified -- which symbols constitute a factor, concretely? Phase 151's
`_resolve_group_symbols()` (tag-filter based peer resolution from `instrument_tags`) already
answers this for `equity`/`rates`/commodity/`fx` groupings. This variant's joint observation
universe is a natural reuse of that same peer-resolution mechanism rather than a bespoke factor
definition -- the two ideas solve adjacent problems (regime_group: what's the peer group's
shared *state*; this variant: what's one symbol's regime *conditional on* its peer group's
returns) with the same underlying peer-set primitive. Still gated identically to the other two
HMM variants.

**General note, replacing the informal "two different axes, not substitutes" framing used
verbally in the 2026-07-01 architecture review:** `regime_group` and per-symbol HMM are not
substitutes, but the IOHMM and factor-augmented variants are specifically the two designed
bridges between them -- IOHMM consumes `regime_group` signals top-down (cross-sectional state
informs one symbol's transition probabilities), factor-augmented reuses `regime_group`'s
peer-resolution bottom-up (which symbols' returns get observed jointly). The Hamilton variant
has no such bridge -- it's a pure per-symbol simplification, independent of `regime_group`
entirely. Worth remembering if either bridge variant is ever built: the dependency on Phase
151 is structural, not incidental.

**Gate:** All HMM variants require empirical evidence that current HMM labels are deficient
(see todo 026's Decision Gate, in the Rolling HMM Refit / Expanding Scaler section). Do not
implement until the IC data shows a problem.

---

### Microstructure Regime (intraday TFs only)

**What it is:** For 5m/15m TFs, classify bars by microstructure state: liquid vs
illiquid, informed flow vs noise flow. Derived from bid-ask spread, OFI imbalance,
and intraday volume profile position.

**Why it matters:** A bar in a liquidity regime with high OFI imbalance is a different
prediction problem than a bar in a noise regime. HMM trained on OHLCV cannot see this.
Microstructure regime is orthogonal to price-dynamics regime.

**Gate:** Requires order flow / bid-ask data infrastructure not currently in place.
Deferred until V2 Microstructure feature vector is built.

---

### Volume Regime (candidate; gated on orthogonality check, see below)

**What it is:** Same construction as Volatility Regime -- expanding percentile rank of
`rel_volume` per (symbol, tf), bucketed low/mid/high (or heavy/normal/light). `rel_volume`
is already computed (it's one of the HMM's 5D observation inputs), so this needs no new
data, same as Volatility Regime.

**Why it might matter:** Volume regime plausibly captures participation/liquidity-driven
price impact, distinct from volatility regime's dispersion-of-outcomes. A symbol can be
low-vol-high-volume (steady accumulation) or high-vol-low-volume (illiquid gap risk) --
different microstructure states in principle.

**Why it is not simply approved alongside Volatility Regime:** volume spikes and volatility
spikes are well documented to co-move (informed flow shows up as both). If historical
correlation between `rel_volume` percentile and `realized_vol` percentile is high (say r >
0.5-0.6), stratifying by both dimensions spends sample-size budget encoding the same
information twice under two names -- shrinking cell counts for no informational gain, which
is a more expensive version of the exact false-discovery risk already flagged in todo 039 for
tag-stratified IC. This is a measurement question, not a design question -- see
Orthogonality Gate below.

---

### Session Regime — Session / Time-of-Day Regime (intraday TFs only)

**What it is:** Classify each bar by session position -- e.g. open / midday / close (or
finer, exchange-session-aware buckets). Purely deterministic: derived from wall-clock
time relative to session boundaries (`normalize_session_type()` already exists in
`service_utils.py`), not from price or volume data at all.

**Why it matters:** Unlike every other candidate here, this dimension has zero look-ahead
risk by construction (you always know what time it is) and is near-certainly orthogonal
to every price/volume-derived dimension (HMM state, vol regime, volume regime) since
intraday liquidity/spread patterns are a structurally different axis from price dynamics.
Zero incremental compute cost, zero new data. This is the cheapest, lowest-risk addition
on this list and arguably should be evaluated ahead of Volume Regime.

**Downgraded 2026-07-01:** cheap+safe is not the same as valuable -- no case made for why
session effects matter at this system's (swing, not HFT) cadence. See
`docs/ideas/2026-07-01-intelligence-lifecycle-backlog-matrix.md`.

**Gate:** none technical -- only intraday TFs (5m/15m) benefit; daily/1h bars have no
useful session position.

---

### Skew/Tail Regime (candidate; gated on orthogonality check)

**What it is:** Rolling return skewness percentile per (symbol, tf). Already identified
as a measurable primitive in `docs/ideas/instrument-tag-calibrator.md` (`skewness`).

**Why it might matter:** Distinct information from vol level in principle -- a symbol can
be high-vol-positive-skew (lottery-like, e.g. XBI) or high-vol-negative-skew (crash risk,
e.g. HYG), which are different prediction problems at the same vol percentile.

**Why it is not simply approved:** vol clusters around crashes, which are themselves
negative-skew events -- skew and vol level are plausibly correlated in the tails, exactly
where this dimension would matter most. Needs the same correlation study as Volume Regime
before it earns a stratification slot.

---

### Explicitly rejected without further review: trend / mean-reversion (Hurst) and
### autocorrelation-sign as separate stratification dimensions

Both are substantially represented *inside* the existing 5D HMM observation vector
already (`momentum`, `vol_of_vol` are direct proxies). Adding either as a *separate*
stratification dimension on top of a `regime` label that is already conditioned on them
risks double-counting the same underlying dynamic under a different name -- collinear
with the stratifying variable itself, which is a more insidious version of the Volume
Regime / Skew-Tail Regime problem because the redundancy is with the primary HMM axis, not
a peer dimension. Not worth an orthogonality study; the redundancy is structural, not
empirical.

---

## Orthogonality Gate (required before Volume Regime, Skew/Tail Regime, or any future candidate ships)

**The rule:** no new stratification dimension is added on the strength of sounding like
a good idea. Combinatorial cost is multiplicative, not additive -- two dimensions
(HMM x5 x vol x3) already costs ~750K cells across the current feature/symbol/TF/lookahead
grid (see "Can They Coexist?" above) and requires Numba JIT just to be computable. Every
additional dimension shrinks the sample size per cell further, which directly collides
with this codebase's own promotion bar (`n >= 100`, p<0.05 -- the same bar `shadow_registry`
and IC Sharpe gating already enforce elsewhere). A dimension that isn't measurably
orthogonal to what already exists is not new information, it's wasted cells.

**Required study, run once against the existing corpus before Volume Regime / Skew-Tail
Regime (or any future candidate) is built:**
1. Compute the candidate dimension's raw values historically (e.g. `rel_volume` percentile,
   rolling skewness) alongside existing dimensions (`realized_vol` percentile, HMM state).
2. Measure correlation (Pearson on the continuous percentile/z-score, or normalized mutual
   information across the discretized labels) between the candidate and every existing
   dimension.
3. Keep only dimensions below an APR-configured correlation threshold
   (`alpha.regime_stratification.max_correlation`, no default asserted here --
   requires empirical judgment once the study is run, not a guessed constant).
4. Dimensions that fail the threshold are either dropped or merged into a single composite
   (e.g. a combined liquidity-shock label instead of separate vol + volume dimensions) --
   this is the same resolution path Microstructure Regime already implies for volume + spread
   + OFI.

Volatility Regime and Dispersion Regime are exempt from this gate -- they are
already measurably distinct in kind (per-symbol vol level vs. cross-sectional dispersion
across the universe), not just presumed distinct.

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
4 lookaheads: 54 × 58 × 4 × 4 × 15 = ~750K cells. Numba JIT (todo 026's JIT item) is a
prerequisite for this to be computationally feasible.

---

## Implementation Order

```
Gate: todo 026's Numba JIT item -- SATISFIED (shipped Phase 141 P2, 2026-06-29;
      src/intelligence/hmm_jit.py, wired at regime_writer.py:490). Volatility Regime is
      unblocked on this gate; still needs an ic_engine multi-axis stratification plan first
      (schema + APR change, not yet written -- see 2026-07-01 architecture review
      .planning/research/2026-07-01-v3-architecture-review.md #3 for the recommended
      substitution-test gate: run ic_engine stratified by volatility_regime INSTEAD
      OF the cross-sectional label first, zero schema change, measures whether the
      axis earns its cells before committing to a feature_ic_scores schema change).

Volatility Regime  -- 1 session; highest value, lowest risk
Dispersion Regime   -- 1 session; requires 58-symbol return matrix
Session Regime       -- <1 session; zero new data, zero look-ahead risk,
                                           near-certainly orthogonal -- cheapest candidate,
                                           consider evaluating alongside/before Volume Regime
--- Orthogonality Gate study (required before Volume Regime, Skew/Tail Regime) ---
Volume Regime                      -- 1 session build IF orthogonality study clears it
Skew/Tail Regime                -- 1 session build IF orthogonality study clears it
Factor Regime                      -- 2 sessions; requires factor data pipeline
HMM Variants                       -- gated on empirical proof of HMM deficiency
Microstructure Regime              -- gated on V2 order flow infrastructure
```

---

## References

- `services/regime_writer.py` -- per-symbol HMM
- `services/equity_regime_model.py` -- cross-sectional 9-regime model
- `docs/plans/2026-06-28-hmm-regime-audit-optimization.md` -- HMM audit (todo 026)
- `docs/plans/2026-06-29-ic-engine-improvements.md` -- IC engine fixes (todo 028)
- `docs/plans/2026-06-29-feature-scoring-beyond-ic.md` -- feature scoring beyond IC (todo 029)
- Hamilton, J.D. (1989) "A New Approach to the Economic Analysis of Nonstationary Time Series"
- Gate: `.planning/todos/pending/026-hmm-regime-audit-optimization.md` (the Rolling HMM Refit item's baseline-separation query — this doc's own implementation order is gated on it, not on a separate todo; no dedicated todo file exists for this doc, it is itself the backlog)
