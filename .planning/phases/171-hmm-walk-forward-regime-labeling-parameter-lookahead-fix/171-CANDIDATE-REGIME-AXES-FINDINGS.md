# Phase 171 follow-on: four candidate single-security regime axes, tested for standalone identifiability

**Status:** investigation complete, decisive. **Verdict: 2 rejected outright, 2 rebuilt as features rather than regimes. Nothing is added to Phase 172 as a `regime_*` HMM column.**
**Author:** Claude Opus 5 (investigative session, 2026-08-08).
**Companion documents:** `171-MODEL-IDENTIFIABILITY-FINDINGS.md` (why production's composite
K=5 label is non-identifiable) and `171-REGIME-DECOMPOSITION-FINDINGS.md` (why decomposing the
existing 5-column observation matrix into trend/volatility/volume does not fix it). Read those
first; this document tests four *new* concepts and does not restate them.

**Scope note:** like both companions, this is NEW work exceeding Phase 171's original mandate.
It is kept out of `evidence/` (which belongs to the executed 171-05 plan) and lives alongside
`171-candidate-regime-axes/`.

**Nothing in this investigation mutated production.** No `config_state` write, no
`feature_vectors` write, no `regime_writer.py` CLI invocation, no edit to
`services/regime_writer.py`. The only new artifact is a read-only diagnostic:
`scripts/analysis/hmm_candidate_regime_axes_identifiability_sweep.py`.

---

## 1. Headline

**None of the four candidates should be built as an HMM regime axis. Two of them should not be
built at all.**

| candidate | is the underlying statistic real? | does the HMM identify on it? | verdict |
|---|---|---|---|
| **systematic** (idio-vs-systematic dominance) | **yes** — signal fraction 0.21-0.40 | 32/32 at K=2/w250 only | **BUILD AS FEATURE, reject as regime** |
| **persistence** (momentum vs mean reversion) | **no** — signal fraction **-0.01** | 34/34 at K=2 (and 34/34 on pure noise) | **REJECT** |
| **tail** (skew / crash asymmetry) | **no** — signal fraction 0.00-0.11 | 31-32/34 at K=2 (null does better) | **REJECT** |
| **volume_price** (volume-price confirmation) | **yes** — signal fraction 0.32 at 250 bars | degrades to 27/34 exactly where the statistic is best | **DEFER — build as feature, gate on IC** |

Three findings drive every verdict, and the first is the most important thing in this document:

1. **The identifiability gate this project has been using does not discriminate signal from
   noise.** Every configuration was re-fit on an IID-permuted copy of the same series — a series
   containing no regime by construction. The null arm clears the agreement ≥ 0.90 / kappa ≥ 0.80
   bars just as often as the real arm, and on several configurations *more* often. The
   `persistence` axis is the cleanest demonstration: 34/34 real, **34/34 null**, at a measured
   signal fraction of −0.006. A two-state HMM on a stationary noise series is a deterministic
   threshold split of that series — perfectly reproducible across disjoint seed pools, well
   separated, healthily occupied. It clears every gate this project currently owns while
   encoding nothing. §5.1.
2. **Two of the four candidates have no persistent structure to find, at any window tested.**
   Return autocorrelation / variance ratio and rolling skew both measure at a signal fraction
   indistinguishable from zero at 20, 60, 120 and 250 bars. This is a genuine "no regime exists"
   result, explicitly *not* a "the window was too short" artifact — the whole point of sweeping
   four windows and running a permutation null was to be able to tell those apart. §5.2.
3. **Where the statistic IS real, the HMM layer is where the quality is lost.** `volume_price`'s
   signal fraction rises monotonically with window (0.06 → 0.17 → 0.26 → 0.32) while its HMM
   identifiability *falls* over the same range (32/34 → 32/34 → 27/34). Identifiability and
   signal are close to uncorrelated across this study. §5.3.

**Recommendation for Phase 172: add no new regime axis. Ship the composite K=3 fix as the two
companion documents already recommend.** Two of the four statistics (systematic dominance,
volume-price confirmation) are worth adding to the *feature vector* as continuous columns in a
Phase-151-style primitive expansion, which is a different phase and a different evidence bar.
§8.

---

## 2. Context: the architectural decision this was scoped against

An earlier session in this same investigation settled how multiple regime dimensions would be
combined *if* any new axis earned its place. Recording it here so this document stands alone.

**Decision: parallel independent cuts, not a crossed grid.** The project already has a clean
precedent — `feature_ic_scores.regime_scope` keeps `pooled`, `symbol_hmm`, and `cross_sectional`
as **parallel independent stratification cuts**, never fused into one blended label. The plan
was to retire the single composite `regime` label and replace it with parallel single-symbol
cuts (`regime_trend`, `regime_volatility`, …), each independently identified, matching that
existing pattern. Crossing was explicitly rejected: it divides per-cell sample size (1d already
has 20% of `(symbol, regime)` cells under the 500-observation gate at K=5) and the project's one
shipped crossed label — the systematic regime's `f"{tier1}_{tier2}"` — realizes only 4 of 9
possible cells in the `commodity` group. Reuse of an existing mechanism beat new invention.

**Group-specific K rides on existing routing.** `_build_symbol_regime_class` in
`services/ic_engine.py` already resolves each symbol to a `regime_group`
(equity / rates / commodity / fx) from `instrument_tags` against the `alpha.regime.groups` APR
config. Any group-specific K choice was to be expressed through *that* mechanism, not a new one.
This sweep therefore reports every failure tagged with its `regime_group`, resolved by importing
that exact function (§6).

**What prompted this document.** The widened 17-symbol trend check found K=3 (down/flat/up)
passes agreement + kappa on all 34 cells, but the occupation gate exposed a real pattern: only
FXY (`fx_major`), GLD (`commodity_metals`), TLT (`fi_treasury`) and EEM (`intl_em`) produce a
near-empty third state at 1h, while all 13 domestic-equity-tagged symbols are clean at both 1d
and 1h. That raised the natural question — *what other single-security regime concepts would a
Renaissance-caliber shop consider?* — and four candidates were nominated for testing. This
document answers that question and, in doing so, undermines the instrument the trend result was
measured with (§5.1, §8.3).

---

## 3. Method

Fitting, decoding, canonicalization, the mechanism diagnostics, and the pass bars are inherited
**unchanged, by direct Python import**, from
`hmm_regime_axis_decomposition_identifiability_sweep.py` (`_fit_one`, `_run_config_cell`,
`_agreement_stats`, `_pick_champion`, `_count_distinct_solutions`, `_min_state_separation`,
`_passes`). That harness was validated in the companion study against a composite control arm
that reproduced every published figure to the digit. Only the observation matrix is new here, so
these numbers sit on a known-good instrument rather than a re-implementation.

Per (symbol, tf) × axis × window × K × arm:

1. Build the axis's 2-column feature matrix from raw OHLCV (plus a benchmark series for
   `systematic`), trim the warm-up prefix, then `StandardScaler().fit_transform` — production
   parity, and the specific bug that bit two earlier pilots in this investigation.
2. Fit 20 seeds from **pool A** (base = `alpha.hmm.random_state` = 42) and 20 from a disjoint
   **pool B** (base 1000). Champion per pool = highest `(converged, log_likelihood)`.
3. Decode production-faithfully: `_stationary_distribution` → `_compute_log_emit` →
   `_alpha_pass_jit` → `_smooth_states(min_hold_bars=3)` → `_build_label_map`.
4. Cross-block agreement between the two champions plus Cohen's kappa. **Bars (both required):
   agreement ≥ 0.90 AND kappa ≥ 0.80.** Plus production's own `_check_occupation_gate` at the
   live `feature.hmm.min_state_occupation = 0.05`.

**Headline convention:** the MINIMUM across cells and the PASS COUNT, never an average.

**Scope:** the same 17 symbols as the widened trend check — SPY, IWM, TLT, GLD, XLE, EEM, FXY,
SMH, AAPL, MSFT, GOOGL, AMZN, JPM, QQQ, DIA, XLF, XLK × {1d, 1h} = **34 cells**. The
`systematic` axis has **32**: SPY is the benchmark and cannot be regressed on itself (R² ≡ 1,
β ≡ 1 — a degenerate cell that would silently pad the pass count), so it is excluded from that
axis only. K ∈ {2, 3}; `covariance_type = full` only (the companion study swept full-vs-diag on
every 2-D axis and diag never changed a verdict). Two runs, 1,200 jobs, 48,000 fits, 1,855s
total on 16 workers.

### 3.1 Canonicalization

`_build_label_map` rank-orders states by fitted `means[:, 0]`. Column 0 of every axis is that
axis's primary dimension, so the map is a rank-ordering canonicalization on the right variable
in each case. The emitted label *strings* stay trend-flavoured ("trending_up" on the tail axis
means "most right-skewed state"); only the ordinal rank participates in agreement, exactly as in
the companion study.

### 3.2 The two instruments this study adds

Neither existed in the companion sweeps, and the conclusions turn on both.

**(a) The block-reliability probe.** Every candidate here is a second- or higher-order statistic
(correlation, autocorrelation, third moment) rather than a raw return, so its own sampling
variance at a short window can swamp any real structure — and a failed HMM result would then be
ambiguous between "no regime exists" and "the window was too short". The probe removes the
ambiguity: it correlates the statistic estimated on **adjacent disjoint windows** (blocks
`[i·W, (i+1)·W)` and `[(i+1)·W, (i+2)·W)`). The two estimates share no observation, so sampling
noise cannot contribute to their correlation; by the classical two-parallel-measurements
identity the coefficient **is the fraction of the statistic's variance that is real rather than
estimation error**. 0.05 means 95% of what the HMM would be fitting is noise. Run at
W ∈ {20, 60, 120, 250} for every axis, so a window explanation can be tested rather than
assumed. Its own calibration check is the same measure on a permuted series, which must return
≈ 0 — it does, median |null| ≤ 0.06 everywhere with more than 40 block pairs.

*An overlapping-window statistic was deliberately not used for this, and the reason is worth
recording.* The first version of the probe compared `std(real)/std(permuted null)` of the
rolling statistic. It reported a ratio of **0.38** for rolling skew — the real series varying
*less* than its own noise floor, which is nonsense as a signal measure. The cause is real and
instructive: under permutation a fat left tail's single worst return lands in a random window
and inflates that window's skewness enormously, whereas in the true series extreme returns
cluster inside already-high-variance windows and are normalized away by the `m2^1.5`
denominator. Both quantities are still recorded in the JSON as descriptive statistics; neither
is a verdict.

**(b) The null arm.** Every (axis, window, K) configuration is *also* fit on features built from
an IID-permuted copy of the series. Permutation preserves the unconditional distribution exactly
— same marginal skewness, same contemporaneous cross-series correlation — while destroying all
time dependence, so the null arm contains no regime by construction. If it clears the bars as
cleanly as the real arm, those bars are not discriminating and a passing real-arm number is
worth nothing on its own. This is what §5.1 rests on.

### 3.3 Feature construction and window choice, per axis

Windows are stated with their reasoning up front and then checked empirically by the probe.
`vol_window = 20` (production's own default, and what `_build_obs_matrix` uses) is the wrong
order of magnitude for all four of these statistics, and the probe confirms it — every axis's
signal fraction at W=20 is at or near its minimum.

| axis | columns (col 0 = primary/ordering) | a priori window reasoning |
|---|---|---|
| **systematic** | `R²` vs SPY, `β` vs SPY | Rolling correlation's SE is ≈ (1−ρ²)/√(n−3): **0.22 at n=20**, 0.13 at n=60. A regression statistic needs materially more history than a raw return. Swept 60/120/250. |
| **persistence** | Lo-MacKinlay `VR(q=5)`, lag-1 return autocorrelation | Autocorrelation SE ≈ 1/√n: 0.22 at n=20, 0.13 at n=60. The variance ratio additionally consumes q=5 bars per aggregated observation, so a 20-bar window holds only ~4 independent q-sums — not enough to estimate a variance. |
| **tail** | rolling skewness, `log(downside/upside semideviation)` | Skewness is a **third** moment: SE ≈ √(6/n) = **0.55 at n=20**, 0.32 at 60, 0.22 at 120, 0.15 at 250 — and fat tails inflate all of these. Swept at 120 **and** 250 specifically so a negative result could be attributed. |
| **volume_price** | `corr(\|r\|, rel_volume)`, `corr(r, rel_volume)` | Same correlation-SE argument. `rel_volume` is built exactly as `_build_obs_matrix` builds column 4 (log volume minus its own 20-bar rolling mean), so this measures a relationship involving production's own volume anomaly, not a new definition of it. Swept 60/120/250. |

Design choices worth flagging:

- **`systematic` uses R², not signed correlation, as the ordering dimension.** R² is the
  fraction of variance explained by the market, which is precisely "systematic dominance", and
  it is sign-agnostic — a reliably negative-beta instrument (TLT, FXY in risk-off) is *strongly*
  systematic even though its correlation is negative. β is the second column because R² alone
  cannot separate a 0.3-beta name whose moves are fully market-explained from a 1.5-beta one.
- **`systematic` uses SPY as a single universal benchmark, deliberately.** Per-`regime_group`
  peer averaging is a separate refinement; mixing it in here would confound "does this axis
  identify at all" with "is the peer group right". If the axis is ever revived, the peer-group
  question is a distinct follow-up, not a detail.
- **`persistence` uses q=5, not q=2.** VR(2) is an affine function of lag-1 autocorrelation
  (VR(2) = 1 + AC1), which would have made the two columns near-duplicates. q=5 aggregates lags
  1..4.
- **`tail` pairs the third moment with a second-moment asymmetry measure.** The
  downside/upside semideviation ratio measures the same underlying asymmetry but is far better
  conditioned, so the axis is not resting on skewness alone. It did not rescue the axis.
- **`volume_price` is the relationship, not the level.** The companion study already killed raw
  `rel_volume` as a standalone axis (never identifies at any K). Magnitude correlation is
  primary — high = moves come with participation (confirmation), near-zero or negative = price
  moving on thin or contrarian volume (divergence). The signed correlation separates
  accumulation from distribution, which the magnitude correlation cannot see.

Clip guards (β to ±5, VR to ±4, skew to ±8) exist because each statistic's denominator can
collapse on a near-flat window and emit a single 1e4-magnitude value that would dominate
`StandardScaler`. Their firing rates were recorded per cell:

- **Forward-fill: zero on all 300 real-arm cells.** No statistic was ever undefined in the
  interior, so no verdict rests on an imputed value.
- **β: zero clips on all 32 `systematic` cells.** The clip guard never fired on the axis whose
  verdict is most favourable.
- **Variance ratio: 9 cells clipped, max rate 0.106%** (AMZN/1h, 39 of 36,753 bars), median
  0.014%. Negligible.
- **Skewness: 10 cells clipped, max rate 4.03%** (AMZN/1h at W=250, 1,473 of 36,567 bars),
  median 0.73%. All ten are 1h cells and eight are single-name equities — names whose 1h returns
  carry the sharpest earnings-gap outliers, which is exactly where a third moment blows up.

Only the skew rate is large enough to mention in a verdict, and it cuts the safe way: clipping
*reduces* the variance of an already-noisy statistic, so it can only have flattered the tail
axis. The tail axis is rejected anyway, and the cells with the heaviest clipping (AMZN/1h,
GOOGL/1h, MSFT/1h) have signal fractions of −0.07, −0.19 and +0.10 — indistinguishable from the
unclipped cells around them. No verdict here depends on the guards.

---

## 4. Full results

### 4.1 The probe: what fraction of each statistic is real

Median across cells, per timeframe. `null` is the same measure on the permuted series and is the
instrument's calibration check.

| axis | W=20 (1d / 1h) | W=60 (1d / 1h) | W=120 (1d / 1h) | W=250 (1d / 1h) |
|---|---|---|---|---|
| **systematic** | 0.274 / 0.119 | **0.401 / 0.213** | 0.359 / 0.274 | 0.234 / **0.287** |
| **persistence** | −0.075 / −0.039 | 0.044 / −0.052 | 0.005 / −0.065 | 0.093 / −0.072 |
| **tail** | 0.032 / −0.009 | 0.046 / 0.017 | 0.022 / −0.005 | 0.111 / −0.024 |
| **volume_price** | 0.061 / 0.064 | 0.184 / 0.166 | 0.299 / 0.234 | **0.375 / 0.310** |
| *null (all axes)* | −0.010 / +0.014 | −0.059 … +0.035 | −0.102 … +0.054 | −0.123 … +0.058 |

Read this table before any other. It separates the four candidates completely, and it does so
*before* any HMM is fit:

- **systematic** and **volume_price** carry real, persistent, measurable structure. Their signal
  fractions are 4-6× the null's magnitude and are positive on essentially every cell.
- **persistence** and **tail** do not. Their medians straddle zero at all four windows and on
  both timeframes, and at 1h `persistence` is negative at every single window.
- The two live axes peak at **different** windows: `systematic` at 60 bars on 1d and 120-250 on
  1h; `volume_price` monotonically increasing right through 250 on both. Neither peaks anywhere
  near production's `vol_window = 20`.

**Caveat, stated because it cuts against a number above:** at W=250 on 1d there are only 18-19
block pairs, so those reliability estimates carry an SE of roughly 0.24. The 1d/W=250 column is
the least trustworthy in the table, and the larger |null| values (up to 0.12) appear there for
exactly that reason. The 1h column at W=250 has 78-79 pairs and is sound. Nothing in §5 depends
on a 1d/W=250 figure.

### 4.2 Identifiability, real arm vs null arm, at N=20

| axis | W | K | **real** pass | **null** pass | real min agree | real min kappa | null min agree | real med sep | null med sep | degenerate |
|---|---|---|---|---|---|---|---|---|---|---|
| systematic | 60 | 2 | **31/32** | 32/32 | 0.7935 | 0.5803 | 0.9966 | 2.62 | 2.51 | 0/32 |
| systematic | 60 | 3 | 28/32 | 21/32 | 0.3660 | 0.0647 | 0.4247 | 2.18 | 2.33 | 0/32 |
| systematic | 120 | 2 | **31/32** | 30/32 | 0.8037 | 0.6217 | 0.6902 | 2.69 | 2.65 | 0/32 |
| systematic | 120 | 3 | 22/32 | 24/32 | 0.3363 | 0.0167 | 0.4049 | 2.31 | 2.28 | 0/32 |
| **systematic** | **250** | **2** | **32/32** | 29/32 | **0.9996** | **0.9992** | 0.7717 | 2.84 | 2.72 | **0/32** |
| systematic | 250 | 3 | 24/32 | 26/32 | 0.1672 | −0.2447 | 0.4135 | 2.49 | 2.26 | 0/32 |
| **persistence** | 60 | 2 | **34/34** | **34/34** | 0.9990 | 0.9980 | 0.9925 | 2.51 | 2.45 | 0/34 |
| persistence | 60 | 3 | **34/34** | 32/34 | 0.9527 | 0.9281 | 0.7205 | 2.33 | 2.31 | 0/34 |
| tail | 120 | 2 | 32/34 | 33/34 | 0.3746 | −0.2549 | 0.2640 | 2.40 | 0.33 | 0/34 |
| tail | 120 | 3 | 24/34 | 26/34 | 0.5335 | 0.2993 | 0.2700 | 2.11 | 2.29 | 0/34 |
| tail | 250 | 2 | 31/34 | 32/34 | 0.4135 | −0.2936 | 0.6579 | 2.48 | 1.10 | 0/34 |
| tail | 250 | 3 | 21/34 | 23/34 | 0.1905 | −0.2046 | 0.1521 | 2.24 | 2.13 | 0/34 |
| volume_price | 60 | 2 | 32/34 | 29/34 | 0.1196 | −0.7586 | 0.2280 | 2.76 | 2.65 | 0/34 |
| volume_price | 60 | 3 | 27/34 | 18/34 | 0.0513 | −0.4149 | 0.1019 | 2.44 | 2.36 | 0/34 |
| volume_price | 120 | 2 | 32/34 | 27/34 | 0.3440 | −0.3101 | 0.2152 | 2.79 | 2.71 | 0/34 |
| volume_price | 120 | 3 | 19/34 | 13/34 | 0.2311 | −0.1522 | 0.1362 | 2.48 | 2.39 | 0/34 |
| volume_price | 250 | 2 | 27/34 | 30/34 | 0.2962 | −0.4082 | 0.7757 | 2.90 | 2.72 | 0/34 |
| volume_price | 250 | 3 | 23/34 | 15/34 | 0.2029 | −0.1964 | 0.2571 | 2.54 | 2.25 | 0/34 |

Two structural observations, both visible without reading a single number in detail:

- **The null arm is competitive everywhere and wins outright in six configurations** (systematic
  60/2 and 120/3 and 250/3; tail 120/2, 120/3, 250/2, 250/3; volume_price 250/2). A control that
  contains no regime by construction is out-performing the real data on the project's own
  identifiability gate.
- **Production's occupation gate fires on nothing.** 0/34 degenerate on every single
  configuration, real and null alike. On the trend axis it was the gate that caught the
  fx/commodity/rates behaviour; here it is completely silent, including on the pure-noise arm.
  It is not a defence against this failure mode.

### 4.3 K=3 fails broadly on every axis

Only `persistence` — the axis with *zero* measured signal — clears K=3 at all (34/34, and its
null clears 32/34). Every other axis drops to 19-28 of 32-34 at K=3, with minimum kappa
frequently negative. Solution multiplicity confirms the mechanism inherited from both companion
documents: max distinct solutions among pool A's 20 fits rises from 6-11 at K=2 to 15-18 at K=3
on every axis. **The K-monotone identifiability decay documented in
`171-REGIME-DECOMPOSITION-FINDINGS.md` §5.1 reproduces exactly on four observation matrices that
study never touched.** That is an independent replication of its central mechanism finding, and
it is the one result here that strengthens rather than undercuts the existing conclusions.

No higher K was swept. The brief authorized it only if K=2 and K=3 both clearly failed for a
reason more states would plausibly fix; the measured reason (more states → more near-tied optima
on a signal that mostly is not there) is the opposite of that.

---

## 5. Mechanism

### 5.1 The identifiability gate does not discriminate signal from noise

This is the load-bearing finding, and `persistence` is its cleanest demonstration:

| | signal fraction | real arm | null arm |
|---|---|---|---|
| persistence, W=60, K=2 | **−0.006** | **34/34** pass, min agreement 0.9990, min kappa 0.9980, median separation 2.51 | **34/34** pass, min agreement 0.9925, median separation 2.45 |

A two-state Gaussian HMM fit to a stationary series with no time structure converges on a
**threshold split** of that series — everything above a cut point in one state, everything below
in the other. That partition is a deterministic function of the data, so two disjoint seed pools
find the identical answer (agreement ≈ 1.0), the two clusters sit either side of the cut and are
therefore well separated (2.5 pooled sigmas), and the split is roughly balanced so occupation is
healthy (~0.48). It clears **every gate this project currently owns** — agreement, kappa,
`min_state_separation`, `_check_occupation_gate` — while encoding nothing whatsoever.

This is a strictly harder version of the coincident-means trap the companion study found on the
volume axis (`171-REGIME-DECOMPOSITION-FINDINGS.md` §5.5). There, the empty model betrayed
itself through a near-zero separation statistic, and R2 of that document proposed a separation
floor to catch it. **A separation floor does not catch this one** — the noise split's separation
is 2.51, higher than composite K=3's 0.75 and higher than most real-arm configurations measured
anywhere in this investigation.

The general statement: **identifiability is a property of the likelihood surface, not of the
data's information content.** A well-conditioned partition of noise is highly identifiable. The
gate answers "would a different seed have given the same answer", which is a necessary condition
for a usable label and was the right question for the composite-K=5 investigation — but it is
silent on "is there anything here to label". Nothing in the two companion documents is wrong;
their scope simply did not include a signal-free control, because they were comparing
configurations of a model everyone already believed was measuring *something*.

### 5.2 `persistence` and `tail` are genuine negative results, not window artifacts

The brief specifically required this distinction, and the probe was built to supply it.

**Both axes measure a signal fraction indistinguishable from zero at every window tested**
(20, 60, 120, 250), on both timeframes, on 17 symbols. The candidate windows span a 12.5× range
and bracket every estimator-SE argument in §3.3 from "far too short" to "a full trading year".
There is no window at which either statistic's variation is materially more than its own
estimation error.

- **persistence**: median −0.075 to +0.093 across the eight (window, tf) combinations; **negative
  at all four windows on 1h**. Per-symbol at W=60/1d the best cell is XLE at 0.19 and the worst
  is FXY at −0.14 — a spread entirely consistent with sampling noise around zero across 17
  symbols. Financial returns being close to a random walk is not a surprising result; that the
  *degree* of departure does not itself persist as a regime is the actual finding.
- **tail**: median −0.024 to +0.111. The single largest value (0.111, 1d/W=250) sits in exactly
  the column §4.1 flags as having an SE of ~0.24 on 18 block pairs. On 1h at W=250, with 79
  pairs, the median is **−0.024**.

So the honest reading is unambiguous: **no persistent momentum-persistence regime and no
persistent skew regime exist in this data at these timescales.** This is not "the window was too
short" — the longer windows were run, and 250 bars does not rescue either axis. Their HMM
results (34/34 for persistence, 31-32/34 for tail) are threshold splits of noise per §5.1 and
should be read as evidence *for* the §5.1 conclusion, not as evidence the axes work.

One caveat stated plainly: this is a null result about **persistent, single-security, ordinal
regime structure** in these particular estimators. It does not say skewness or mean-reversion are
uninformative as *features* — a fast-moving skew reading can carry information without being a
regime that lasts. It says they do not support a state-machine abstraction.

### 5.3 Where the statistic is real, the HMM is where quality is lost

`volume_price` is the demonstration, because its signal fraction and its identifiability move in
**opposite** directions over the same window sweep:

| W | signal fraction (1d / 1h) | HMM identifies (K=2) | null arm |
|---|---|---|---|
| 60 | 0.184 / 0.166 | 32/34 | 29/34 |
| 120 | 0.299 / 0.234 | 32/34 | 27/34 |
| 250 | **0.375 / 0.310** | **27/34** | 30/34 |

At the window where the underlying statistic is most reliable, the HMM is *least* able to
produce a reproducible partition of it — and the noise control beats it. The same pattern holds
on `systematic`, inverted: it identifies best (32/32) at W=250, where its 1d signal fraction is
at its *lowest* (0.234, down from 0.401 at W=60).

Across all 18 (axis, window, K) configurations, identifiability and signal fraction are close to
unrelated. The mechanism is not mysterious: a longer window makes the statistic smoother and
more autocorrelated, which is exactly what makes a Gaussian HMM's states harder to separate in
the *time* dimension even as the per-window estimate gets cleaner. The two objectives are in
tension, and the HMM is optimizing neither of the things that matter.

**Implication: the state-machine abstraction is the wrong wrapper for these statistics.** Both
live candidates are smooth, slowly-varying, continuously-valued quantities. Discretizing them
through EM buys an identifiability question that a deterministic quantile tiering — the exact
mechanism `cross_sectional_regime_model._assign_labels` already uses for the systematic regime,
with no EM, no seed and no local optima — would not have. That is the shape of the
recommendation in §8.

### 5.4 No fx/commodity/rates/intl-equity split, on any axis

The brief asked directly whether the pattern the widened trend check found reappears here. **It
does not.** Real-arm failures and degeneracies by `regime_group`, resolved through
`_build_symbol_regime_class`, at the K=2 configurations:

| axis | W | equity | rates | commodity | fx | UNROUTED |
|---|---|---|---|---|---|---|
| systematic | 60 | 1/16 | 0/2 | 0/2 | 0/2 | 0/10 |
| systematic | 120 | 1/16 | 0/2 | 0/2 | 0/2 | 0/10 |
| systematic | 250 | 0/16 | 0/2 | 0/2 | 0/2 | 0/10 |
| persistence | 60 | 0/18 | 0/2 | 0/2 | 0/2 | 0/10 |
| tail | 120 | 1/18 | 0/2 | 0/2 | 0/2 | 1/10 |
| tail | 250 | 3/18 | 0/2 | 0/2 | 0/2 | 0/10 |
| volume_price | 60 | 2/18 | 0/2 | 0/2 | 0/2 | 0/10 |
| volume_price | 120 | 1/18 | 0/2 | 0/2 | 1/2 | 0/10 |
| volume_price | 250 | 5/18 | 0/2 | 0/2 | 0/2 | 2/10 |

The specific symbols that fail are broad domestic-equity ETFs — XLF/1d, QQQ/1h, QQQ/1d, IWM/1d,
XLE/1h, SMH/1h, SPY/1d, XLK/1d — i.e. the *opposite* of the trend axis's pattern, where every
problem cell was FXY, GLD, TLT or EEM and every domestic-equity symbol was clean. The four
"awkward" symbols of the trend result are essentially clean on all four axes here (a single
FXY/1d failure on volume_price at W=120, and nothing else).

Two readings are available and this study cannot separate them, so both are stated:

1. The trend axis's group split is specific to *directional* regime structure — which is
   plausible on economic grounds, since a non-equity instrument's drift genuinely has a different
   character from an equity's.
2. Given §5.1, the failure pattern on these four axes is largely a property of where a
   threshold-split-of-noise happens to be marginally less reproducible, and carries no group
   information because there is little group signal to carry.

Reading (2) is more likely for `persistence` and `tail`, where there is demonstrably no signal.
For `systematic` and `volume_price` reading (1) is the better fit. Either way: **no candidate
axis reproduces the trend axis's group pattern, and none of them motivates a group-specific K.**

### 5.5 An incidental finding worth acting on: five symbols are unrouted

Resolving the 17 symbols through `_build_symbol_regime_class` against the live
`alpha.regime.groups` config returns **no `regime_group` at all for AAPL, MSFT, GOOGL, AMZN and
JPM**. Their only relevant `instrument_tags` entry is `single_name_equity`, which does not match
the equity group's `eq_*` / `intl_*` prefix filters, nor any other enabled group's.

This is working exactly as `_build_symbol_regime_class` documents — unmatched symbols are omitted
deliberately, and its docstring is explicit that an explicit gap beats silent mislabeling, with
the caller logging unrouted symbols loudly. But the consequence is real and probably unintended:
**every single-name equity in the universe is excluded from regime-stratified IC entirely.** The
pooled pass still covers them, so no data is dropped, but a whole instrument class gets no
regime-conditional cut. Given the universe recently expanded 111 → 231 instruments, the unrouted
set is likely much larger than these five.

This is out of scope for Phase 172 and is filed as a todo, not fixed here. Worth confirming
against the full 231-symbol universe before deciding whether `single_name_equity` should be
added to the equity group's `tag_filter` or given a group of its own.

---

## 6. Per-axis verdicts

### 6.1 `systematic` — **BUILD AS A FEATURE, REJECT AS A REGIME**

**The statistic is real.** Signal fraction 0.401 (1d) / 0.213 (1h) at W=60, positive on **32 of
32 cells** at that window, against a null of −0.031 / −0.021. Per-symbol it behaves exactly as
theory predicts: highest for instruments with a stable market relationship (XLE 0.65, DIA 0.59,
AAPL 0.57 on 1d) and lowest for the one instrument whose relationship to SPY is genuinely
unstable (GLD 0.04 on 1d, 0.11 on 1h). A statistic that ranks GLD last and DIA first is
measuring what it claims to measure.

**The HMM adds nothing.** The single clean configuration is K=2 / W=250 (32/32, min agreement
0.9996, min kappa 0.9992, 0/32 degenerate) — and even there the null arm passes 29/32. At W=60,
where the statistic is *most* reliable, the real arm fails XLF/1d (0.7935/0.5803) while the null
arm passes 32/32. K=3 fails on 8-10 cells at every window.

**Verdict: build the underlying quantities as continuous feature-vector columns** (rolling R²
and β versus a benchmark, W=60 for 1d and W=120 for 1h), in a Phase-151-style primitive
expansion. **Do not build a `regime_systematic` HMM column.** If a discrete cut is wanted later,
use deterministic quantile tiering via the `build_tiers()` mechanism the systematic regime
already uses, which has no identifiability question by construction — and gate it behind a
Phase-144 D-05-shaped test that IC actually differs across its buckets, which has never been
asked of any regime axis in this project.

### 6.2 `persistence` — **REJECT**

Signal fraction **−0.006** pooled; negative at all four windows on 1h. The HMM's 34/34 at K=2 is
a threshold split of noise, proven by a null arm that also scores 34/34 with min agreement
0.9925. There is nothing here. Do not build it in any form — not as a regime, not as a feature.

This is not a window problem: 20, 60, 120 and 250 were all measured. It is not an estimator
problem either — the variance ratio and lag-1 autocorrelation agree with each other, and both
agree with zero.

### 6.3 `tail` — **REJECT**

Signal fraction 0.00-0.11 across four windows and two timeframes, with the only value above 0.05
sitting in the thinnest, highest-SE cell of the whole probe table. HMM identifiability is poor
(31-32/34 at K=2, 21-24/34 at K=3) *and* the null arm does better at three of four
configurations.

**Explicitly attributed, per the brief's requirement:** this is a genuine "no persistent skew
regime exists" finding, **not** "the window was too short to estimate skew". The third-moment SE
argument in §3.3 was taken seriously and answered empirically — 250 bars gives skewness an SE of
~0.15, more than adequate, and the signal fraction there on 1h is −0.024. Pairing the noisy third
moment with a well-conditioned second-moment asymmetry measure did not rescue it either. Do not
build it.

### 6.4 `volume_price` — **DEFER: build as a feature, gate on IC**

**The statistic is real and was materially under-served by the initial window choice.** Signal
fraction rises monotonically 0.06 → 0.17 → 0.26 → **0.375/0.310** from W=20 to W=250, positive on
15/16 (1d) and 16/17 (1h) cells at W=250. It is genuinely a different statistical object from raw
volume level, which the companion study killed outright — testing it fresh was the right call.

**But the HMM layer degrades exactly where the statistic improves** (§5.3): 32/34 at W=120 falls
to 27/34 at W=250, where the null arm scores 30/34. K=3 is far worse (19-27/34).

**Verdict: defer, pending a specific further check.** Build `corr(|r|, rel_volume)` and
`corr(r, rel_volume)` at W=250 as continuous feature-vector columns, then ask the question that
has never been asked of any regime axis in this project: **does IC actually differ across this
statistic's own quantile buckets?** If yes, a deterministic tiering earns its place as a
stratification cut. If no, the axis is dead regardless of how reliable the statistic is. Do not
build a `regime_volume_price` HMM column under any outcome.

---

## 7. What this means for the two companion documents

Both companions' conclusions survive, but one of them needs a correction and the other needs a
caveat carried forward.

**`171-REGIME-DECOMPOSITION-FINDINGS.md` R2 — the proposed state-separation floor — is
necessary but insufficient, and should not be shipped as if it closes the gap.** That
recommendation was written to catch the volume axis's coincident-means degeneracy, and it does.
It does not catch the failure mode documented in §5.1: the pure-noise threshold split has a
separation of 2.51, far above any floor near 0.5 that document suggests. Shipping the separation
floor is still correct; believing it makes the gate sufficient is not.

**The composite K=3 recommendation is unaffected and is not weakened by anything here.** Nothing
in this study tested the composite observation matrix, and the K-monotone decay mechanism both
companions rest on is independently replicated here on four new observation matrices (§4.3).

**The widened trend result inherits a caveat.** The trend axis at K=3 was measured with the same
agreement/kappa instrument that §5.1 shows is non-discriminating. That does *not* invalidate it —
trend measured a min separation of 2.33 at K=2 in the companion study, the widest margin
anywhere in this investigation, and the occupation gate produced a coherent economic pattern
(fx/commodity/rates/intl) that a noise split would not produce. But the trend axis has never been
run against a null arm, and it should be before its group-specific-K conclusion is acted on. That
is a cheap check — the script in this study supports it directly — and it is recommended in §8.3
rather than assumed.

---

## 8. Recommendation

### R1 — Phase 172 scope: **add no new regime axis. Do not widen 172 for any of these four.**

The phase should ship exactly what the two companion documents recommend: composite
`feature.hmm.n_components` 5→3, `covariance_type` stays `full`, `alpha.hmm.n_restarts` 1→20, plus
the identifiability quarantine path. Two of the four candidates measure no signal at all; the two
that do measure signal are demonstrably better served by a continuous feature than by a state
machine, and building either as a regime would add a `regime_scope` enum extension, a per-axis
label vocabulary, N× the IC strata, N× the FDR family, and per-axis re-verification of every
downstream regime consumer — in exchange for a discretization that the measurement says loses
information rather than adding it. Musk step 2 applies directly.

### R2 — Add a **null-arm requirement** to the K-selection policy. This is the one change this study argues *for*.

The companion documents' K-selection policy is "smallest K clearing the identifiability gate, BIC
ranks within that set", plus a separation floor. §5.1 shows that policy admits a partition of
pure noise. Add a third condition, and note it is cheap: **re-fit the champion configuration once
on an IID-permuted copy of the same observation matrix; if the null arm clears the same bars, the
configuration is not evidence of a regime.** One extra fit per cell against 20 for the real
champion — under 5% overhead on `regime_writer`'s existing restart loop.

For any *new* candidate feature intended as a regime, additionally require a block-reliability
floor before an HMM is fit at all — it is a rolling-correlation computation, costs nothing, and
would have killed `persistence` and `tail` in seconds without any of the 48,000 HMM fits this
study spent to reach the same conclusion.

The floor used here (median block reliability > 0.10) is **`[initial_estimate]`, uncalibrated**.
The measured value is printed alongside every verdict so a different bar can be applied without
re-running. It should be calibrated before it gates anything in production.

### R3 — File two follow-ups, neither blocking Phase 172.

- **Feature-primitive todo:** add rolling R²/β versus benchmark (W=60 on 1d, W=120 on 1h) and
  rolling `corr(|r|, rel_volume)` / `corr(r, rel_volume)` (W=250) as continuous
  `feature_vectors` columns in the next Phase-151-style expansion, then measure regime-conditional
  IC separation across their own quantile buckets. This is the §7.3 evidence gate of
  `171-REGIME-DECOMPOSITION-FINDINGS.md` applied to two statistics that have now cleared its
  first two conditions but not its third.
- **Routing todo:** `single_name_equity`-tagged symbols (AAPL, MSFT, GOOGL, AMZN, JPM here, and
  likely many more across the expanded 231-instrument universe) match no enabled
  `alpha.regime.groups` filter and are silently excluded from all regime-stratified IC. Audit
  the full universe's unrouted set and decide whether to extend the equity `tag_filter` or add a
  group. §5.5.

### R4 — Run the trend axis against a null arm before acting on its group-specific-K conclusion.

Cheap, directly supported by this study's script, and §7 explains why it matters. If trend's null
arm also passes at K=3, the fx/commodity/rates/intl pattern needs re-reading before any
group-specific K is designed around it. If it fails while the real arm passes — the likely
outcome given trend's exceptional separation margin — the widened-trend conclusion is confirmed
on a strictly better instrument and can be acted on with confidence.

---

## 9. Artifacts

| file | what |
|---|---|
| `scripts/analysis/hmm_candidate_regime_axes_identifiability_sweep.py` | the diagnostic (read-only, no mutation) |
| `171-candidate-regime-axes/sweep-candidate-axes.json` | primary grid: 4 axes × default windows × K{2,3} × 2 arms × 34 cells × N{5,10,20} |
| `171-candidate-regime-axes/sweep-candidate-axes.console.txt` | console log of the above (672 jobs, 1,122s on 16 workers) |
| `171-candidate-regime-axes/sweep-candidate-axes-long-windows.json` | probe-directed follow-up: systematic and volume_price at W ∈ {120, 250} |
| `171-candidate-regime-axes/sweep-candidate-axes-long-windows.console.txt` | console log of the above (528 jobs, 717s on 16 workers) |

Reproduce:

```
.venv/bin/python scripts/analysis/hmm_candidate_regime_axes_identifiability_sweep.py \
    --max-workers 16 \
    --results-path .planning/phases/171-hmm-walk-forward-regime-labeling-parameter-lookahead-fix/171-candidate-regime-axes/sweep-candidate-axes.json

.venv/bin/python scripts/analysis/hmm_candidate_regime_axes_identifiability_sweep.py \
    --axes systematic volume_price --axis-windows 'systematic:120,250;volume_price:120,250' \
    --max-workers 16 \
    --results-path .planning/phases/171-hmm-walk-forward-regime-labeling-parameter-lookahead-fix/171-candidate-regime-axes/sweep-candidate-axes-long-windows.json
```

The `--skip-null-arm` flag halves runtime but must not be used for a verdict run — without the
control arm a passing identifiability number cannot be distinguished from a reproducible
threshold split of noise, which is the entire lesson of §5.1.
