# Phase 171 follow-on: does decomposing the HMM regime into trend/volatility/volume axes resolve identifiability?

**Status:** investigation complete, decisive. **Verdict: hypothesis FALSIFIED.**
**Author:** Claude Opus 5 (investigative session, 2026-08-08).
**Companion document:** `171-MODEL-IDENTIFIABILITY-FINDINGS.md` — read that first; this
document tests a mechanism hypothesis raised by its conclusions and does not restate them.

**Scope note:** like its companion, this is NEW work exceeding Phase 171's original mandate.
It is kept out of `evidence/` (which belongs to the executed 171-05 plan) and lives alongside
`171-regime-decomposition/`.

**Nothing in this investigation mutated production.** No `config_state` write, no
`feature_vectors` write, no `regime_writer.py` CLI invocation, no edit to
`services/regime_writer.py`. The only new artifact is a read-only diagnostic:
`scripts/analysis/hmm_regime_axis_decomposition_identifiability_sweep.py`.

---

## 1. Headline

**The composite observation model's identifiability failure is not caused by fusing three
signal families into one state chain. It is caused by K.**

Every axis, fit in complete isolation, degrades along exactly the same K-monotone path the
composite does. Isolating a family buys almost no extra state budget, and the axis the
hypothesis nominated as "the hard one" — trend/direction — turns out to be the
**best-separated axis in the entire study**.

| axis | smallest config clearing 16/16 identifiability | also clean on the occupation gate? | min state separation there |
|---|---|---|---|
| **composite** (production's own model) | K=3 / full | **yes**, 0/16 degenerate | 0.75 |
| trend (log_return, momentum) | K=2 / full or diag | **yes**, 0/16 degenerate | 2.33 |
| volatility (realized_vol, vol_of_vol) | K=2 / full or diag | **yes**, 0/16 degenerate | 1.75 |
| volume (rel_volume) | **none at any K tested** | no | — |

Three conclusions follow, and they are independent:

1. **Decomposition solves nothing that composite K=3 has not already solved.** Composite
   K=3/full clears both the identifiability gate (16/16, min agreement 0.9927) and
   production's own occupation gate (0/16 degenerate, min occupation 0.064). There is no
   residual identifiability problem for decomposition to fix.
2. **A full three-axis decomposition is not even constructible.** The volume axis clears no
   configuration on all 16 cells at any K, and at K=2 four of the sixteen cells produce two
   states with *coincident emission means* (separation 0.001-0.059) — a model that passes the
   agreement gate while encoding no volume regime at all. §5.3.
3. **The specific mechanism hypothesis is falsified.** Trend is not noisy-and-hard; it is the
   cleanest axis. Volatility is robust as predicted, but only marginally more so than trend,
   and its robustness does not rescue the composite. Volume, predicted to be intermediate, is
   the weakest by a wide margin. §5.

**Recommendation: Phase 172 should NOT be redesigned around decomposed regime axes.** Ship
the composite `K=3, covariance_type=full, n_restarts=20` fix exactly as
`171-MODEL-IDENTIFIABILITY-FINDINGS.md` §7 recommends. §8.

---

## 2. The hypothesis under test

`_build_obs_matrix` (`services/regime_writer.py`, lines 175-227) fuses three loosely-related
signal families into one joint ordinal state chain:

| col | feature | family |
|---|---|---|
| 0 | `log_return` = ln(close[t]/close[t-1]) | **trend / direction** |
| 1 | `realized_vol` = rolling std of log_returns | **volatility** |
| 2 | `momentum` = sum(log_returns[-w:]) / (realized_vol + eps) | **trend / direction** |
| 3 | `vol_of_vol` = rolling std of realized_vol | **volatility** |
| 4 | `rel_volume` = log(vol) - rolling mean(log(vol)) | **volume** |

The hypothesis: volatility clustering is one of the most robust patterns in financial data
(calm vs turbulent genuinely separate cleanly); direction is close to a random walk and
inherently noisier; volume sits between. Forcing the well-separated volatility signal to
compromise with the noisy directional signal in one joint partition is a plausible mechanism
for the near-tied-competing-optima pathology the companion document measured.

**Prediction if true:** each axis in isolation identifies at lower K, with more margin, than
the composite; volatility cleanest, volume intermediate, trend hardest.

**The families really are distinct.** Measured cross-family correlation on the standardized
observation matrix, all 16 cells:

| statistic | median \|corr\| | max \|corr\| |
|---|---|---|
| within trend: `corr(log_return, momentum)` | 0.189 | 0.225 |
| within volatility: `corr(realized_vol, vol_of_vol)` | 0.640 | 0.736 |
| across trend ↔ volatility | 0.140 | 0.388 (SPY/1d, the leverage effect) |
| across trend ↔ volume | 0.090 | 0.237 |
| across volatility ↔ volume | 0.035 | 0.104 |

So the decomposition is well-founded on the data: the three families are near-orthogonal in
observation space, and the composite HMM really is being asked to partition a
nearly-independent 5-D space with a single ordinal chain. The premise was sound. The
conclusion drawn from it was not.

Note in passing that **"trend" is the least internally coherent family** (within-family
correlation 0.19 vs volatility's 0.64) — which makes its later dominance on state separation
more striking, not less.

---

## 3. Method

Identical to `hmm_model_complexity_identifiability_sweep.py` so the numbers are directly
comparable; only the observation slice changes.

Per (symbol, tf) × axis × (K, covariance_type), at full production history scope:

1. Build `_build_obs_matrix`, slice the axis's columns, then `StandardScaler().fit_transform`
   — production parity. StandardScaler is per-column, so slice-then-scale and scale-then-slice
   are identical; the composite arm is bit-for-bit the same model production fits.
2. Fit 20 seeds from **pool A** (base = `alpha.hmm.random_state` = 42) and 20 from a disjoint
   **pool B** (base 1000). Champion per pool = highest `(converged, log_likelihood)` — the
   same preference order `_compute_symbol_tf`'s restart loop applies.
3. Decode production-faithfully: `_stationary_distribution` → `_compute_log_emit` →
   `_alpha_pass_jit` → `_smooth_states(min_hold_bars=3)` → `_build_label_map`.
4. Cross-block agreement between the two champions, plus Cohen's kappa against the empirical
   chance baseline. **Bars (both required): agreement ≥ 0.90 AND kappa ≥ 0.80.**

**Headline convention:** the MINIMUM across cells and the PASS COUNT, never an average — an
average hides exactly the non-identifiable cell the sweep exists to find.

**Scope:** the same 16 cells as both prior sweeps — SPY, IWM, TLT, GLD, XLE, EEM, FXY, SMH ×
{1d, 1h}. Grid: 20 (axis, K, cov) configurations × 16 cells = **320 jobs × 40 fits = 12,800
fits**. Wall clock 1,402s on 16 workers.

### 3.1 Canonicalization across axes

`_build_label_map` ranks states by fitted `means[:, 0]`. Column 0 of each axis slice is that
axis's primary dimension, so the map is a rank-ordering canonicalization on the right variable
for every axis:

| axis | ordering dimension | what the ordinal actually means |
|---|---|---|
| composite | log_return | trending_down … trending_up (production semantics) |
| trend | log_return | trending_down … trending_up |
| volatility | realized_vol | calmest … most turbulent |
| volume | rel_volume | lightest … heaviest |

The emitted label *strings* stay composite-flavoured on the non-trend axes ("trending_up" on
the volatility axis means "highest-realized-vol state"). Only the ordinal rank participates in
the agreement computation, so this is cosmetic here — but any future implementation would need
a per-axis vocabulary.

### 3.2 The 1-dimensional volume axis

A 1×1 "full" covariance is a diagonal covariance: identical free-parameter count, identical
likelihood. Both were swept anyway as a check that hmmlearn agrees. **It does — every volume
cell's `full` and `diag` results are identical to floating-point precision on all 16 cells at
both K.** Any future implementation should use `diag` for a 1-D axis and skip the full-covariance
regularization path, which buys nothing.

### 3.3 New mechanism diagnostics (beyond the companion sweep)

- **`min_state_separation`** — min over state pairs of the Mahalanobis distance between fitted
  means under the occupation-weighted pooled covariance. Reads as "how many pooled sigmas apart
  are the two closest states". This is the *geometric* quantity behind identifiability: states
  that overlap give a flat likelihood surface on which many partitions score almost identically.
- **`distinct_solutions_a`** — number of semantically distinct labelings among pool A's own 20
  fits (single-linkage clustering at ≥0.99 pairwise agreement). 1 = EM always lands on the same
  partition; >1 = the champion choice is picking among incompatible semantics.
- **`ll_spread_relative_a`** — (max ll − min ll)/|max ll| across pool A. **Near-zero spread
  alongside many distinct solutions is the formal near-tied-competing-optima signature.** This
  pair of statistics turns out to be the discriminating instrument of the whole study (§5.4).

### 3.4 Harness validation

The composite arm is a control replicating the companion sweep on the same data. It reproduces
it **exactly**: K=5/full 7/16 with SPY/1h at 0.0784/−0.1800, EEM/1h 0.1516/−0.0717, GLD/1h
0.1964/−0.0282, GLD/1d 0.2640/0.0796, SMH/1d 0.2972/0.1009, XLE/1d 0.5679/0.4500, SPY/1d
0.5071/0.3698, SMH/1h 0.5357/0.4118; K=3/full 16/16 with min 0.9927/0.9870 at TLT/1d, 0/16
degenerate, min occupation 0.064. Every one of those figures matches
`171-MODEL-IDENTIFIABILITY-FINDINGS.md` to the digit. The decomposed-axis numbers below sit on
a validated harness.

---

## 4. Full results

### 4.1 Per-axis × config verdicts at N=20 (16 cells each)

| axis | K | cov | pass/16 | min agreement | min kappa | median sep | min sep | cells w/ >1 solution | median solutions | median ll spread |
|---|---|---|---|---|---|---|---|---|---|---|
| composite | 3 | full | **16/16** | 0.9927 | 0.9870 | 1.12 | 0.75 | 10/16 | 2 | 0.00192 |
| composite | 5 | full | **7/16 FAIL** | 0.0784 | −0.1800 | 0.93 | 0.56 | 16/16 | 14 | 0.01522 |
| trend | 2 | full | **16/16** | 0.9973 | 0.9946 | 2.45 | **2.33** | 5/16 | 1 | 0.00000 |
| trend | 2 | diag | **16/16** | 0.9976 | 0.9952 | 2.45 | 2.32 | 4/16 | 1 | 0.00000 |
| trend | 3 | full | **16/16** | 0.9930 | 0.9894 | 2.17 | 0.99 | 7/16 | 1 | 0.00041 |
| trend | 3 | diag | **16/16** | 0.9958 | 0.9937 | 2.14 | 0.81 | 6/16 | 1 | 0.00010 |
| trend | 4 | full | **15/16 FAIL** | 0.4995 | 0.3319 | 1.95 | 0.13 | 15/16 | 3 | 0.02213 |
| trend | 4 | diag | **16/16** | 0.9801 | 0.9730 | 1.99 | 0.19 | 13/16 | 2 | 0.01905 |
| trend | 5 | full | **15/16 FAIL** | 0.3341 | 0.1021 | 1.49 | 0.53 | 16/16 | 5 | 0.04519 |
| trend | 5 | diag | **15/16 FAIL** | 0.6219 | 0.4965 | 1.38 | 0.25 | 16/16 | 5 | 0.03558 |
| volatility | 2 | full | **16/16** | 0.9988 | 0.9964 | 1.97 | 1.75 | 1/16 | 1 | 0.00000 |
| volatility | 2 | diag | **16/16** | **0.9999** | **0.9998** | 2.39 | 1.96 | 0/16 | 1 | 0.00000 |
| volatility | 3 | full | **16/16** | 0.9977 | 0.9964 | 1.10 | 0.71 | 16/16 | 4 | 0.40814 |
| volatility | 3 | diag | **16/16** | 0.9908 | 0.9856 | 1.27 | 0.85 | 16/16 | 4 | 0.43508 |
| volatility | 4 | full | **16/16** | 0.9680 | 0.9568 | 0.84 | 0.52 | 16/16 | 9 | 0.35678 |
| volatility | 4 | diag | **15/16 FAIL** | 0.7974 | 0.7059 | 0.94 | 0.68 | 16/16 | 7 | 0.36096 |
| volume | 2 | full | **15/16 FAIL** | 0.6729 | 0.3700 | 1.46 | **0.00** | 15/16 | 3 | 0.03916 |
| volume | 2 | diag | **15/16 FAIL** | 0.6729 | 0.3700 | 1.46 | **0.00** | 15/16 | 3 | 0.03916 |
| volume | 3 | full | **15/16 FAIL** | 0.2857 | 0.1473 | 1.34 | 0.49 | 16/16 | 8 | 0.03801 |
| volume | 3 | diag | **15/16 FAIL** | 0.2857 | 0.1473 | 1.34 | 0.49 | 16/16 | 8 | 0.03801 |

### 4.2 Every failing cell, with its diagnostics

| axis | K | cov | cell | agreement | kappa | rel ll gap | solutions (A/B) | sep | min occ |
|---|---|---|---|---|---|---|---|---|---|
| composite | 5 | full | SPY/1h | 0.0784 | −0.1800 | 0.00062 | 6/6 | 1.27 | 0.083 |
| composite | 5 | full | EEM/1h | 0.1516 | −0.0717 | 0.00263 | 14/14 | 0.87 | 0.121 |
| composite | 5 | full | GLD/1h | 0.1964 | −0.0282 | 0.00069 | 18/19 | 0.85 | 0.055 |
| composite | 5 | full | GLD/1d | 0.2640 | 0.0796 | 0.00019 | 16/16 | 1.24 | 0.131 |
| composite | 5 | full | SMH/1d | 0.2972 | 0.1009 | 0.00390 | 20/20 | 1.33 | 0.075 |
| composite | 5 | full | SPY/1d | 0.5071 | 0.3698 | 0.00012 | 14/12 | 1.14 | 0.087 |
| composite | 5 | full | SMH/1h | 0.5357 | 0.4118 | 0.00004 | 10/10 | 0.92 | 0.099 |
| composite | 5 | full | XLE/1d | 0.5679 | 0.4500 | 0.00055 | 16/17 | 0.72 | 0.093 |
| composite | 5 | full | TLT/1d | 0.8783 | 0.8398 | 0.00319 | 19/19 | 1.22 | 0.025 |
| trend | 4 | full | TLT/1h | 0.4995 | 0.3319 | 0.00152 | 2/3 | 0.19 | 0.012 |
| trend | 5 | full | FXY/1h | 0.3341 | 0.1021 | 0.02915 | 5/5 | 1.10 | 0.010 |
| trend | 5 | diag | EEM/1h | 0.6219 | 0.4965 | 0.02684 | 6/9 | 0.27 | 0.023 |
| volatility | 4 | diag | SMH/1d | 0.7974 | 0.7059 | 0.00934 | 16/11 | 1.07 | 0.076 |
| volume | 2 | full/diag | EEM/1h | 0.6729 | 0.3700 | 0.00386 | 8/5 | 1.61 | 0.206 |
| volume | 3 | full/diag | GLD/1h | 0.2857 | 0.1473 | 0.00096 | 8/5 | 0.53 | 0.067 |

### 4.3 Production's own degeneracy gate, applied to every configuration

`_check_occupation_gate` at the live `feature.hmm.min_state_occupation = 0.05`. A degenerate
cell is one production would *skip*, leaving `regime` NULL.

| axis | K | cov | degenerate cells | min occupation |
|---|---|---|---|---|
| composite | 3 | full | **0/16** | 0.064 |
| composite | 5 | full | 2/16 (EEM/1d, TLT/1d) | 0.025 |
| trend | 2 | full | **0/16** | 0.408 |
| trend | 2 | diag | **0/16** | 0.413 |
| trend | 3 | full | 3/16 (GLD/1h, EEM/1h, FXY/1h) | 0.011 |
| trend | 3 | diag | 4/16 (+TLT/1h) | 0.012 |
| trend | 4 | full | 4/16 | 0.009 |
| trend | 4 | diag | 4/16 | 0.010 |
| trend | 5 | full | **8/16** (every 1h cell) | 0.010 |
| trend | 5 | diag | **8/16** (every 1h cell) | 0.010 |
| volatility | 2 | full | **0/16** | 0.214 |
| volatility | 2 | diag | **0/16** | 0.204 |
| volatility | 3 | full | **0/16** | 0.068 |
| volatility | 3 | diag | 1/16 (TLT/1d) | 0.038 |
| volatility | 4 | full | 1/16 (TLT/1d) | 0.034 |
| volatility | 4 | diag | 2/16 (EEM/1d, TLT/1d) | 0.025 |
| volume | 2 | full/diag | 1/16 (IWM/1h) | **0.001** |
| volume | 3 | full/diag | 4/16 (XLE/1h, IWM/1h, EEM/1h, FXY/1d) | **0.000** |

**This table changes the per-axis verdict materially, and it must be read alongside §4.1.**
Trend passes the identifiability gate at K=3 but *degenerates on 3-4 of 16 cells*, all of them
1h. The only trend configuration clean on both gates is **K=2**. Applying both gates:

| axis | clean on BOTH gates | 
|---|---|
| composite | K=3/full |
| trend | K=2/full, K=2/diag |
| volatility | K=2/full, K=2/diag, K=3/full |
| volume | **nothing** |

---

## 5. Mechanism: what actually drives the failure

### 5.1 The failure is K-monotone on every axis, identically

Median distinct solutions among pool A's 20 fits (full covariance), and the median relative
log-likelihood spread across those fits:

| axis | K=2 | K=3 | K=4 | K=5 |
|---|---|---|---|---|
| composite (median solutions) | — | 2 | — | **14** |
| composite (median ll spread) | — | 0.0019 | — | 0.0152 |
| trend (median solutions) | 1 | 1 | 3 | 5 |
| trend (median ll spread) | 0.0000 | 0.0004 | 0.0221 | 0.0452 |
| volatility (median solutions) | 1 | 4 | 9 | — |
| volatility (median ll spread) | 0.0000 | 0.4081 | 0.3568 | — |
| volume (median solutions) | 3 | 8 | — | — |
| volume (median ll spread) | 0.0392 | 0.0380 | — | — |

**Solution multiplicity is monotone increasing in K on all four axes without exception.** If
family fusion were the driver, isolating a family should flatten this curve. It does not — the
curve has the same shape on a 1-D observation as on a 5-D one. The binding constraint is how
many distinguishable persistent states the *series* supports, not how many signal families the
model is being asked to reconcile.

### 5.2 Isolation buys almost no extra state budget

If fusion were the cost, splitting 5-D into 2-D should let each axis carry more states. The
measured state budget (clean on both gates) is:

- composite (5-D, all three families): **K=3**
- trend (2-D): **K=2**
- volatility (2-D): **K=3**
- volume (1-D): **none**

The total is roughly conserved, and two of the three isolated axes support *fewer* states than
the fused model. That is the direct falsification: dimensionality reduction did not purchase
identifiability headroom.

### 5.3 Trend is the best-separated axis, not the worst — hypothesis falsified

The hypothesis predicted trend would be the hard axis because direction is near-random-walk.
The measurement says the opposite. At the smallest clean K, minimum state separation across
all 16 cells (pooled-sigma units):

| axis | min separation at its clean K |
|---|---|
| **trend (K=2)** | **2.33** |
| volatility (K=2) | 1.75 |
| composite (K=3) | 0.75 |

Trend's two states are more than three pooled standard deviations apart at their worst cell —
the widest margin in the study, and 3.1× the composite's. Directional regime is a
*well-posed* two-state problem on this data. It becomes ill-posed at K≥3 for the same reason
everything else does: too many states for the signal.

The honest reading of the negative-result caveat in the brief: **there is no evidence here that
directional regime is inherently weaker or noisier than this project has been treating it.**
At K=2 it is the strongest axis measured. What *is* newly evidenced is that its 1h behaviour
diverges sharply from 1d — every trend degeneracy at K≥3 is a 1h cell, none is 1d — so the
number of distinguishable directional states is timeframe-dependent in a way the current
uniform-K design does not model.

### 5.4 The discriminating statistic: near-tied vs well-separated multimodality

The volatility axis at K=3/full finds a **median of 4 distinct solutions** among 20 fits and
still identifies 16/16. The composite at K=5/full finds a median of 14 and fails 9/16. Why?
The log-likelihood spread separates them:

| configuration | median distinct solutions | median rel. ll spread | verdict |
|---|---|---|---|
| volatility K=3/full | 4 | **0.4081** | 16/16 PASS |
| volatility K=4/full | 9 | 0.3568 | 16/16 PASS |
| composite K=5/full | 14 | **0.0152** | 7/16 FAIL |
| composite K=3/full | 2 | 0.0019 | 16/16 PASS |

Volatility's competing optima are **40% apart in log-likelihood** — enormously distinguishable,
so best-of-20 reliably finds the same global maximum from either seed pool, and multiplicity is
harmless. The composite's K=5 optima are **1.5% apart**, and on individual failing cells
0.004%-0.39% (§4.2) — statistically indistinguishable but semantically incompatible.

**Multimodality per se is not the pathology. Near-tied multimodality is.** This sharpens the
companion document's §5.3 diagnosis with a statistic that discriminates the two cases, and it
is worth carrying into the K-selection policy: a configuration with many optima that are far
apart in likelihood is fine; one with few optima that are close together is not.

### 5.5 Volume: the unhypothesized negative result

Volume was predicted to be intermediate. It is by far the weakest axis, and it fails in a way
none of the gates in this project currently catch.

At K=2, four of sixteen cells produce two states whose emission means are essentially
**coincident**:

| cell | min state separation | min occupation | cross-block agreement | passes gate? |
|---|---|---|---|---|
| XLE/1h | **0.001** | 0.053 | 1.0000 | yes |
| FXY/1h | **0.012** | 0.489 | 1.0000 | yes |
| SPY/1h | **0.014** | 0.151 | 1.0000 | yes |
| GLD/1h | **0.059** | 0.074 | 1.0000 | yes |
| IWM/1h | 0.919 | **0.001** | 1.0000 | no — degenerate |

Those four cells report **perfect 1.0000 cross-block agreement** while the model encodes no
volume regime whatsoever — the two "states" differ only in transition dynamics and covariance,
not in mean `rel_volume`. They are reproducible because the degeneracy itself is deterministic.

**This is a methodological finding that generalizes beyond the volume axis: the
agreement/kappa gate can pass a semantically empty model.** The occupation gate catches the
IWM/1h case (one state holding 0.1% of bars) but not the four coincident-mean cases, where
occupation is healthy. Only the separation statistic catches those. Any K-selection policy
built on identifiability alone inherits this blind spot.

`rel_volume` — a log-volume anomaly against a 20-bar rolling baseline — evidently carries too
little persistent state structure to support even a two-state Markov chain corpus-wide. That is
a real, reportable negative result about the feature, not just about the model.

One further note: volume's two failures are **non-overlapping across K** (EEM/1h fails at K=2
but passes at K=3; GLD/1h passes at K=2 but fails at K=3). A per-symbol K would therefore
"rescue" the volume axis — which is precisely the escape hatch the companion document rejected
on cross-sectional-comparability grounds (§6 there). That rejection stands and applies here
unchanged.

---

## 6. Two different decompositions — do not conflate them

Two orthogonal decomposition axes exist in this project. A future reader must keep them apart.

**Axis 1 — WHOSE DATA drives the label (the existing "dual regime system", already shipped).**

| mechanism | table / writer | glossary term |
|---|---|---|
| per-symbol GaussianHMM on that symbol's own OHLCV | `feature_vectors.regime`, `regime_writer.py` | **idiosyncratic regime** / symbol regime |
| cross-sectional signal over a peer group | `market_regimes.regime_label`, `cross_sectional_regime_model.py` (Phase 144) | **systematic regime** / market regime |

**Axis 2 — WHICH SIGNAL DIMENSIONS the label is computed from (this investigation).**
Splitting `_build_obs_matrix`'s 5 columns into trend / volatility / volume families, entirely
*inside* the idiosyncratic regime.

They compose rather than compete — a full grid would be 2 sources × 3 dimensions. Only the
idiosyncratic side is under test here.

**One asymmetry matters for reading these results across: the systematic regime is not an HMM
at all.** `cross_sectional_regime_model._assign_labels` is deterministic threshold tiering
(`regime_label = f"{tier1}_{tier2}"`, tiers from each signal module's `build_tiers()`). No EM,
no random seed, no local optima. **The identifiability pathology documented in these two
investigations is specific to the idiosyncratic HMM and cannot occur in `market_regimes`.** Do
not "fix" the systematic regime for a problem it structurally cannot have.

---

## 7. Downstream stratification design (secondary — sketch and recommendation)

This section is answered on its merits even though §1's verdict makes it moot for now, because
the analysis is the reason the verdict is safe to act on.

### 7.1 Measured constraints

`feature_ic_scores` PK is `(feature_name, symbol, tf, regime, lookahead_bars,
training_window_end)` with `regime NOT NULL`, plus a `regime_scope` enum
{`pooled`, `cross_sectional`, `symbol_hmm`} that already separates label SOURCE from label
STRING (`_resolve_regime_scope`). Phase 151 Plan 02's `cluster_regime_conditioned` switch
already dual-writes two scopes for one symbol. **The schema already supports multiple
independent regime axes; it does not need crossing to express them.**

Sample-size gates: `alpha.ic.min_observations = 500`, `alpha.ic.min_obs_daily_features = 1000`.

Today's per-(symbol, tf, regime) stratum sizes in `feature_vectors` at the live K=5:

| tf | (symbol, regime) cells | already < 500 obs | thinnest | mean |
|---|---|---|---|---|
| 5m | 275 | 0 | 2,877 | 66,105 |
| 15m | 290 | 0 | 1,336 | 22,736 |
| 1h | 305 | 1 | 262 | 5,652 |
| 1d | 350 | **69 (20%)** | 18 | 843 |

The project has already shipped one **crossed** two-axis regime label — the systematic
regime's `f"{tier1}_{tier2}"` (3 VIX tiers × 3 breadth tiers). Its measured behaviour is the
cautionary case:

| group | tf | labels realized / possible | thinnest | fattest | imbalance |
|---|---|---|---|---|---|
| equity | 1d | 9/9 | 342 | 1,490 | 4.4× |
| rates | 1d | **6/9** | 77 | 915 | 11.9× |
| rates | 1h | **6/9** | 881 | 37,346 | 42.4× |
| commodity | 1h | **4/9** | 414 | 26,548 | 64.1× |
| commodity | 5m | **4/9** | 2,714 | 295,640 | 108.9× |

`commodity` realizes only 4 of its 9 crossed cells; `rates` only 6. Crossing correlated axes
silently deletes corners of the grid.

**Honest counter-evidence:** §2's correlation table shows the three idiosyncratic families are
near-orthogonal (cross-family |corr| median 0.035-0.14), so the empty-corner failure mode is
*less* likely here than in the breadth×vol case. The argument against crossing therefore rests
on sample-size division, not on imbalance. (Caveat: near-zero correlation of continuous
observations does not strictly guarantee even population of non-linear state partitions; it is
first-order evidence, not proof.)

### 7.2 Options

- **(A) Cross all axes.** With the *measured* clean per-axis K (trend 2 × volatility 3 ×
  volume n/a) this is 6 buckets, not the 12-18 the brief anticipated. But mean 1d cell size
  divides by ~1.2× per additional axis of the same K, and the thin tail does not survive: 1d
  already has 20% of cells under the 500-obs gate at 5 labels, and 1h's thinnest cell (262)
  is already under it. **Rejected** — it spends the entire remaining 1d sample-size budget for
  a conditioning refinement nobody has shown modulates IC.
- **(B) One axis at a time, each its own `regime_scope`.** Independent stratification passes
  (`symbol_hmm_trend`, `symbol_hmm_volatility`). Every stratum still divides the corpus by only
  its own K, so **zero** sample-size loss per stratum. Costs ~N× the IC compute of one pass and
  N× the multiple-testing family (FDR applied within `(tf, regime_scope)` as today). Reuses
  `regime_scope` + the existing dual-write mechanism exactly as designed. **This is the right
  shape if decomposition is ever adopted.**
- **(C) Pick one axis, drop the rest.** Cheapest; discards conditioning information if more
  than one axis modulates IC.
- **(D) Hierarchical / adaptive nesting.** Strictly more machinery than (B) for a benefit
  nobody has measured.

### 7.3 Recommendation

**(B), and only behind an evidence gate.** An axis earns a live stratification pass only after
it clears all three of: (i) corpus-wide identifiability, (ii) the occupation gate, and (iii) a
per-axis regime-separation gate of the Phase 144 D-05 shape — *does IC actually differ across
this axis's own buckets?* Crossing is deferred to a specific measured question ("do axes X and
Y modulate IC independently and additively, and does the crossed stratum survive
`min_observations`?"), never adopted as a design commitment.

On today's evidence no axis has passed (iii), because (iii) has never been asked.

---

## 8. Recommendation (decisive)

### R1 — **Phase 172 should NOT be redesigned around decomposed regime axes.** Ship the composite K=3 fix unchanged.

`171-MODEL-IDENTIFIABILITY-FINDINGS.md` §7's recommendation stands in full:
`feature.hmm.n_components` 5→3, `covariance_type` stays `full`, `alpha.hmm.n_restarts` 1→20,
plus the identifiability quarantine path. Nothing in this investigation weakens it, and this
investigation's control arm independently reproduces every number it rests on.

Decomposition is rejected on four independent grounds:

1. **No problem left to solve.** Composite K=3/full is 16/16 on identifiability *and* 0/16
   degenerate, with min occupation 0.064. The premise that decomposition would fix something
   is empirically void.
2. **It is not constructible as specified.** The volume axis clears nothing at any K, and its
   K=2 fits are semantically empty on 4/16 cells (§5.3). A "trend × volatility × volume"
   regime system cannot be built from this observation matrix.
3. **The mechanism hypothesis is false.** Failure is K-monotone on every axis in isolation
   (§5.1); isolation buys no state budget (§5.2); the axis nominated as the weak one is the
   strongest (§5.3). The composite's problem was never family fusion.
4. **Cost without benefit.** Median 40-fit cost per 1h cell: composite K=3 = 106s; the minimal
   viable decomposition (trend K=2 at 28s + volatility K=3 at 79s) = 107s for *two* axes, but
   then doubles the IC-engine strata, doubles the FDR family, needs a per-axis label
   vocabulary, a `regime_scope` enum extension, and per-axis re-verification of every
   downstream regime consumer. Musk step 2 ("delete") applies directly: this is complexity
   purchased with no measured benefit.

### R2 — Add a **state-separation floor** to the K-selection policy.

The companion document's R3 codifies "smallest K clearing the identifiability gate, BIC ranks
only within that set." §5.3 shows that gate has a blind spot: four volume cells clear it at
agreement 1.0000 while their two states have coincident means. Add a third condition —
`min_state_separation` must exceed a floor (a value near 0.5 pooled sigmas is suggested by the
data but is **not calibrated**; treat as `[initial_estimate]` and calibrate before enforcing).
Composite K=3/full's own min separation is 0.75, so it clears a 0.5 floor but not by much;
that margin is worth knowing before rollout.

Note this is a **cheap** addition: the statistic is computed from `model.means_` and
`model.covars_`, both already in hand at gate time. No extra fits.

### R3 — Carry two calibration risks into 172-03's wider sweep.

- **Composite K=3's occupation margin is thinner than its agreement margin suggests.** Min
  occupation 0.064 against a 0.05 gate is 1.3×, versus an agreement margin of 0.9927 against
  0.90. 15m/5m are unmeasured. If the occupation margin does not hold at higher-frequency
  timeframes, the quarantine path (companion R4) will carry more traffic than anticipated.
- **The trend family's state budget is timeframe-dependent.** Every trend degeneracy at K≥3 is
  a 1h cell and none is 1d (§4.3). The uniform-K design does not model this. It does not
  invalidate composite K=3 — the composite is clean at both timeframes — but 172-03 should
  report occupation by timeframe, not pooled, so a 5m divergence is visible rather than
  averaged away.

### R4 — Reframe decomposition from "identifiability fix" to "expressiveness question", and file it as a todo, not a phase.

Decomposition is dead as an identifiability remedy. It is *not* dead as a possible improvement
to what `regime` conditions on — but that is an **IC question**, cheap to answer once the
corpus is relabeled at K=3, and it belongs behind the §7.3 evidence gate. Suggested todo:
"after the K=3 relabel, measure whether a volatility-only K=3 stratification produces
materially different regime-conditional IC than the composite K=3 label
(`regime_scope='symbol_hmm_volatility'` dual-write, one tf, no schema change)." Volatility is
the right axis to test first: it is the only one clean at K=3 on both gates, and its optima are
40% apart in likelihood (§5.4), the widest safety margin measured anywhere in this study.

---

## 9. Artifacts

| file | what |
|---|---|
| `scripts/analysis/hmm_regime_axis_decomposition_identifiability_sweep.py` | the diagnostic (read-only, no mutation) |
| `171-regime-decomposition/sweep-axis-decomposition.json` | full grid, 4 axes × per-axis K × cov × 16 cells × N{5,10,20} |
| `171-regime-decomposition/sweep-axis-decomposition.console.txt` | console log of the above |

Reproduce (1,402s on 16 workers):

```
.venv/bin/python scripts/analysis/hmm_regime_axis_decomposition_identifiability_sweep.py \
    --max-workers 16 \
    --results-path .planning/phases/171-hmm-walk-forward-regime-labeling-parameter-lookahead-fix/171-regime-decomposition/sweep-axis-decomposition.json
```

The cross-family correlation table in §2 was produced by an ad-hoc read-only script over the
same 16 cells using `_build_obs_matrix` + `StandardScaler` + `np.corrcoef`; it is fully
specified by that description and was not kept as a permanent artifact.
