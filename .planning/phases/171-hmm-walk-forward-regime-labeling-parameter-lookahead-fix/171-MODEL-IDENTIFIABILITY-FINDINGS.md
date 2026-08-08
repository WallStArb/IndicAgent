# Phase 171 follow-on: HMM regime-label model-identifiability investigation

**Status:** investigation complete, decisive. **Author:** Claude Opus 5 (investigative session, 2026-08-08).
**Scope note:** this is NEW work that exceeds Phase 171's original mandate. It is deliberately
kept out of `evidence/` (which belongs to the already-executed 171-05 plan) and lives in
`171-model-identifiability/` alongside this document.

**Nothing in this investigation mutated production.** No `config_state` write, no
`feature_vectors` write, no `regime_writer.py` CLI invocation, no edit to
`services/regime_writer.py`. The only new artifact in `src/`-adjacent space is a read-only
diagnostic: `scripts/analysis/hmm_model_complexity_identifiability_sweep.py`.

---

## 1. Headline

**`feature.hmm.n_components = 5` is not a reliably estimable parameterization for this
observation model.** At production's own configuration (K=5, `covariance_type=full`,
standardized observations), best-of-20-restart model selection run twice from two disjoint
seed pools lands on **substantively different label assignments on 9 of 16 tested
(symbol, timeframe) cells**. On the worst cell (SPY/1h) the two independently-selected
champions agree on **7.8%** of bars — worse than chance for a 5-label vocabulary
(Cohen's kappa **-0.18**).

**`K=3, covariance_type=full, n_restarts=20` identifies cleanly on 16/16 cells**, minimum
cross-block agreement **0.9927**, minimum kappa **0.9870**, zero numerical failures, zero
degenerate fits.

**BIC and identifiability point in opposite directions and BIC loses.** This sweep reproduces
the 2026-06-26 BIC K-selection study's conclusion exactly — BIC prefers K=5/full on **16/16**
cells, unanimously — while the same 16 cells show K=5 is estimable on only 7. BIC answers
"which K explains the data best"; it is silent on "which K has one dominant optimum the fitter
can actually find". For this application the second question is the binding one, and it was
never asked.

---

## 2. Methodological correction to the two prior pilots (read this before citing their numbers)

`hmm_walk_forward_seed_stability_pilot.py` and `hmm_restart_convergence_pilot.py` both fit
`GaussianHMM` on `_build_obs_matrix`'s **raw** output. **Production does not.** Every
production fit path in `services/regime_writer.py` standardizes first:

| path | scaling |
|---|---|
| `_compute_symbol_tf` (line ~1197) | `StandardScaler().fit_transform(obs_matrix)`, once globally |
| `_walk_forward_hmm_full` (line ~735) | `StandardScaler` refit per segment on the training prefix only |

The raw observation dimensions are wildly heteroscedastic — measured directly:

| cell | per-dim std | max/min variance ratio | raw covariance condition number |
|---|---|---|---|
| SPY/1d | `[1.23e-2, 6.92e-3, 4.45e0, 1.52e-3, 3.20e-1]` | 8.5e6 | 1.7e7 |
| SMH/1h | `[6.66e-3, 3.16e-3, 4.84e0, 6.67e-4, 6.34e-1]` | 5.3e7 | 8.3e7 |

Fitting a full-covariance Gaussian mixture on a design matrix with condition number ~1e7-1e8
is exactly the regime that produces non-positive-definite covariance blowups and erratic EM
optima. The prior pilots therefore measured a **worse-conditioned model than production
actually runs**, and their headline numbers are not production-representative.

This does **not** overturn their directional conclusion. It sharpens it: the identifiability
problem survives the correction. See the 2x2 in §4.

This investigation's script standardizes by default (matching production) and compares the
**smoothed, canonically-labeled** sequence — `_alpha_pass_jit` → `_smooth_states(min_hold_bars=3)`
→ `_build_label_map` — i.e. the exact byte sequence that lands in `feature_vectors.regime`,
not the raw alpha-pass argmax the prior pilots compared.

---

## 3. Method

Per (symbol, tf) x (K, covariance_type) cell, at full production history scope:

1. Build `_build_obs_matrix` observations, then `StandardScaler().fit_transform` (production parity).
2. Fit 20 seeds from **pool A** (base = `alpha.hmm.random_state` = 42) and 20 from a disjoint
   **pool B** (base = 1000).
3. Champion per pool = highest `(converged, log_likelihood)` lexicographically — the same
   preference order `_compute_symbol_tf`'s own restart loop applies. Pools are seed *prefixes*,
   so N=5/10/20 are all derived from the same 20 fits.
4. `agreement` = fraction of bars where the two champions' canonical labels match.
5. `chance` = the agreement two independent labelers with those same marginal label frequencies
   would reach by luck; `kappa = (agreement - chance) / (1 - chance)`.

**Why kappa is mandatory here.** Raw agreement is not comparable across K — a 3-label
vocabulary has a ~1/3 chance floor versus ~1/5 at five labels. Without the correction, reducing
K would appear to "fix" identifiability partly by inflating the chance baseline. Measured chance
baselines at K=3 ranged 0.343-0.442, so the correction is material, and K=3 still clears
kappa >= 0.987.

**Bars (both required):** `agreement >= 0.90` (inherited unchanged from
`hmm_restart_convergence_pilot.py` for comparability) **AND** `kappa >= 0.80`.

**Scope:** the same 16 cells as the prior pilots — SPY, IWM, TLT, GLD, XLE, EEM, FXY, SMH x
1d, 1h. Grid: K in {3,4,5} x covariance_type in {full, diag} = 96 jobs x 40 fits = **3,840 fits**,
plus a 1,280-fit unstandardized control arm. Wall clock ~16 min on 16 workers.

**Headline convention:** the corpus-wide number is the **minimum** across cells and the
**pass count**, never an average — an average hides exactly the non-identifiable cell this
sweep exists to find. Same convention as `_hmm_seed_stability_check` and both prior pilots.

---

## 4. The load-bearing result: a 2x2 on (K, scaling)

Cross-block identifiability at N=20, cells clearing both bars, out of 16:

| | **unstandardized** (prior pilots' convention) | **standardized** (production parity) |
|---|---|---|
| **K=5, full** (production today) | **4/16** — min agreement 0.0096 | **7/16** — min agreement 0.0784 |
| **K=3, full** (recommended) | **14/16** — min agreement 0.7622 | **16/16** — min agreement 0.9927 |

Numerical failures (`covars must be symmetric, positive-definite` / non-finite score), out of
640 fits per arm:

| | unstandardized | standardized |
|---|---|---|
| K=5, full | **12** (9 cells: IWM/1d, SPY/1d, SMH/1d, FXY/1d x4, TLT/1h, FXY/1h, GLD/1h, XLE/1h, EEM/1h) | **0** |
| K=3, full | 1 (GLD/1d) | **0** |

Three conclusions follow directly, and they are independent:

1. **The covariance crashes were an artifact of the pilots' missing standardization.**
   171-05's G2 recorded hard non-PD `ValueError`s on 9 cells and scored each as agreement 0.0.
   Standardization eliminates them completely (0/3,840 across the entire scaled grid). Hypothesis 1
   from the root-cause session (`full_cov_min_obs` miscalibration) was correctly falsified, but for
   a reason that session did not identify: the threshold was never the problem, the conditioning
   was.
2. **Standardization alone does not fix identifiability.** At K=5 it moves the pass count from
   4/16 to 7/16 and the worst cell from 0.0096 to 0.0784. Production has been standardizing all
   along, and 9/16 cells are still non-identifiable. **The core diagnosis in the handoff stands.**
3. **Model-complexity reduction is the dominant lever.** K=5 -> K=3 moves 4/16 -> 14/16 even
   *without* the scaling fix. Both together give 16/16.

---

## 5. Full sweep results (standardized, production parity)

### 5.1 Per-config corpus-wide verdicts

| K | cov | N | pass/16 | min agreement | min kappa | worst cell |
|---|---|---|---|---|---|---|
| 3 | full | 5 | **16/16** | 0.9267 | 0.8875 | FXY/1d |
| 3 | full | 10 | **16/16** | 0.9255 | 0.8856 | FXY/1d |
| 3 | full | 20 | **16/16** | **0.9927** | **0.9870** | TLT/1d |
| 3 | diag | 5 | 15/16 | 0.4841 | 0.2917 | TLT/1d |
| 3 | diag | 10 | 15/16 | 0.4841 | 0.2917 | TLT/1d |
| 3 | diag | 20 | 15/16 | 0.4841 | 0.2917 | TLT/1d |
| 4 | full | 5 | 9/16 | 0.1156 | -0.1196 | TLT/1d |
| 4 | full | 10 | 11/16 | 0.2975 | 0.0230 | SMH/1d |
| 4 | full | 20 | 15/16 | 0.6170 | 0.4872 | IWM/1h |
| 4 | diag | 5 | 14/16 | 0.4363 | 0.1730 | TLT/1d |
| 4 | diag | 10 | 14/16 | 0.1539 | -0.1064 | GLD/1d |
| 4 | diag | 20 | 15/16 | 0.0206 | -0.3110 | SMH/1d |
| 5 | full | 5 | 6/16 | 0.0784 | -0.1800 | SPY/1h |
| 5 | full | 10 | 6/16 | 0.0784 | -0.1800 | SPY/1h |
| 5 | full | 20 | 7/16 | 0.0784 | -0.1800 | SPY/1h |
| 5 | diag | 5 | 8/16 | 0.2378 | 0.0321 | FXY/1h |
| 5 | diag | 10 | 8/16 | 0.2240 | 0.0330 | EEM/1h |
| 5 | diag | 20 | 12/16 | 0.1662 | -0.0342 | GLD/1d |

**K=3/full is the only configuration that clears every cell at any N.** It is also the only one
whose worst cell is not merely "passing" but comfortably clear (0.9927 against a 0.90 bar).

### 5.2 Per-cell matrix at N=20 (agreement / kappa; `*` = clears both bars)

| cell | K3/full | K3/diag | K4/full | K4/diag | K5/full | K5/diag |
|---|---|---|---|---|---|---|
| EEM/1d | 1.000 / 0.999 `*` | 0.998 / 0.997 `*` | 0.976 / 0.964 `*` | 0.997 / 0.996 `*` | 1.000 / 1.000 `*` | 1.000 / 1.000 `*` |
| FXY/1d | 1.000 / 1.000 `*` | 0.999 / 0.999 `*` | 1.000 / 0.999 `*` | 0.997 / 0.996 `*` | 0.984 / 0.980 `*` | 1.000 / 1.000 `*` |
| GLD/1d | 1.000 / 0.999 `*` | 1.000 / 1.000 `*` | 0.946 / 0.927 `*` | 1.000 / 1.000 `*` | **0.264 / 0.080** | **0.166 / -0.034** |
| IWM/1d | 1.000 / 0.999 `*` | 1.000 / 1.000 `*` | 1.000 / 1.000 `*` | 0.999 / 0.999 `*` | 1.000 / 1.000 `*` | 1.000 / 1.000 `*` |
| SMH/1d | 0.999 / 0.998 `*` | 1.000 / 1.000 `*` | 0.912 / 0.873 `*` | **0.021 / -0.311** | **0.297 / 0.101** | 1.000 / 1.000 `*` |
| SPY/1d | 1.000 / 1.000 `*` | 1.000 / 1.000 `*` | 1.000 / 1.000 `*` | 1.000 / 1.000 `*` | **0.507 / 0.370** | 0.975 / 0.968 `*` |
| TLT/1d | 0.993 / 0.987 `*` | **0.484 / 0.292** | 0.998 / 0.997 `*` | 1.000 / 1.000 `*` | **0.878 / 0.840** | **0.294 / 0.078** |
| XLE/1d | 1.000 / 1.000 `*` | 1.000 / 1.000 `*` | 0.985 / 0.980 `*` | 0.999 / 0.999 `*` | **0.568 / 0.450** | 0.963 / 0.952 `*` |
| EEM/1h | 1.000 / 1.000 `*` | 1.000 / 1.000 `*` | 0.993 / 0.990 `*` | 0.997 / 0.996 `*` | **0.152 / -0.072** | **0.421 / 0.265** |
| FXY/1h | 1.000 / 1.000 `*` | 1.000 / 1.000 `*` | 0.999 / 0.998 `*` | 0.996 / 0.994 `*` | 0.999 / 0.999 `*` | 1.000 / 1.000 `*` |
| GLD/1h | 0.995 / 0.991 `*` | 1.000 / 1.000 `*` | 1.000 / 1.000 `*` | 1.000 / 1.000 `*` | **0.196 / -0.028** | **0.545 / 0.429** |
| IWM/1h | 1.000 / 1.000 `*` | 0.999 / 0.999 `*` | **0.617 / 0.487** | 1.000 / 1.000 `*` | 0.998 / 0.998 `*` | 1.000 / 1.000 `*` |
| SMH/1h | 1.000 / 1.000 `*` | 1.000 / 1.000 `*` | 1.000 / 1.000 `*` | 1.000 / 1.000 `*` | **0.536 / 0.412** | 1.000 / 1.000 `*` |
| SPY/1h | 1.000 / 1.000 `*` | 0.999 / 0.999 `*` | 1.000 / 1.000 `*` | 1.000 / 1.000 `*` | **0.078 / -0.180** | 1.000 / 1.000 `*` |
| TLT/1h | 0.998 / 0.998 `*` | 1.000 / 1.000 `*` | 0.999 / 0.999 `*` | 1.000 / 1.000 `*` | 0.999 / 0.999 `*` | 0.999 / 0.999 `*` |
| XLE/1h | 1.000 / 1.000 `*` | 1.000 / 1.000 `*` | 1.000 / 1.000 `*` | 1.000 / 1.000 `*` | 1.000 / 1.000 `*` | 0.999 / 0.998 `*` |

### 5.3 The failure mechanism, quantified

The failing K=5 cells are not "bad fits". They are **near-tied competing optima with different
label semantics** — the relative log-likelihood gap between the two pools' champions:

| cell | agreement | relative ll gap | interpretation |
|---|---|---|---|
| SPY/1h | 0.0784 | 0.00062 | a 0.06% likelihood difference flips 92% of labels |
| EEM/1h | 0.1516 | 0.00263 | 0.26% likelihood, 85% of labels differ |
| GLD/1h | 0.1964 | 0.00069 | 0.07% likelihood, 80% of labels differ |
| GLD/1d | 0.2640 | 0.00019 | 0.02% likelihood, 74% of labels differ |
| SMH/1d | 0.2972 | 0.00390 | 0.39% likelihood, 70% of labels differ |

This is the formal signature of non-identifiability: the likelihood surface has multiple optima
that are statistically indistinguishable but semantically incompatible. **No amount of restart
compute resolves it** — that is precisely what `hmm_restart_convergence_pilot.py`'s
non-monotonic N behavior was showing.

### 5.4 K=5 additionally trips production's own degeneracy gate

Two of the sixteen cells' K=5 champions are flagged degenerate by `_check_occupation_gate`
at the live `feature.hmm.min_state_occupation = 0.05`:

| cell | min state occupation | production behavior |
|---|---|---|
| EEM/1d | 0.034 | write skipped, `regime` left NULL |
| TLT/1d | 0.025 | write skipped, `regime` left NULL |

At K=3/full, **zero** cells are degenerate and the minimum state occupation across all 16 cells
is 0.064 (TLT/1d) — above the gate with margin. K=5 is not just unstable, it is over-parameterized
relative to what these series support: it routinely collapses a state.

### 5.5 BIC unanimously disagrees — and is wrong

BIC of the pool-A champion at N=20, lower is better. `<<` marks the BIC-preferred config:

| cell | K3/full | K3/diag | K4/full | K4/diag | K5/full | K5/diag |
|---|---|---|---|---|---|---|
| EEM/1d | 46449 | 47187 | 43525 | 44176 | **41137** `<<` | 41805 |
| FXY/1d | 54876 | 55243 | 52405 | 53001 | **50574** `<<` | 50814 |
| GLD/1d | 52662 | 53179 | 49748 | 50451 | **48024** `<<` | 48396 |
| IWM/1d | 50487 | 51883 | 47463 | 48491 | **45305** `<<` | 46038 |
| SMH/1d | 38898 | 39825 | 37035 | 37950 | **35545** `<<` | 36164 |
| SPY/1d | 46533 | 48587 | 43405 | 45260 | **41039** `<<` | 42328 |
| TLT/1d | 26132 | 26236 | 24512 | 24865 | **23614** `<<` | 23697 |
| XLE/1d | 47309 | 48070 | 44513 | 45324 | **42334** `<<` | 42972 |
| EEM/1h | 308169 | 311380 | 291572 | 294792 | **279437** `<<` | 281938 |
| FXY/1h | 307545 | 310127 | 292941 | 295674 | **281758** `<<` | 284328 |
| GLD/1h | 391698 | 395103 | 371923 | 375295 | **359408** `<<` | 362166 |
| IWM/1h | 369773 | 374493 | 349461 | 355036 | **334992** `<<` | 338570 |
| SMH/1h | 276624 | 280070 | 263648 | 268246 | **254330** `<<` | 256867 |
| SPY/1h | 306066 | 311075 | 288033 | 292880 | **275532** `<<` | 278466 |
| TLT/1h | 199522 | 201364 | 190796 | 193010 | **183649** `<<` | 185151 |
| XLE/1h | 355927 | 359712 | 334557 | 338869 | **319864** `<<` | 324397 |

**16/16 for K=5/full — the 2026-06-26 study reproduced exactly, on different symbols and a
different timeframe.** The original study was not wrong about what it measured. It measured the
wrong thing for the decision it was used to make. BIC is monotonically improving in K across this
whole range; it would keep recommending larger K while the model becomes progressively less
estimable. **BIC alone must never again be the K-selection criterion for this model.**

---

## 6. Does K need to be per-symbol? No. That is a positive finding.

The handoff flagged per-symbol K as worth reconsidering, and the restart sweep's symbol-specific
non-monotonicity made it a live hypothesis. The sweep answers it directly: **the smallest
identifiable configuration is `K=3, full` on all 16 cells with no exceptions** (§5.2, first
column — 16/16 starred). There is no cell where K=3 fails and a larger K succeeds.

Per-symbol K should therefore be **rejected**, for three reasons:

1. **Zero measured benefit.** Every cell's answer is the same. A per-symbol selection mechanism
   would be complexity purchased with no evidence — a direct Musk-step-2 ("delete") violation.
2. **It would break cross-sectional comparability, which is the whole point of the column.**
   `ic_engine` computes regime-stratified IC by pooling across symbols, and `ensemble_trainer`
   conditions on regime cross-sectionally. A `ranging` label from a K=3 symbol partitions
   state-space differently from a `ranging` label from a K=5 symbol; pooling them silently mixes
   two different conditioning variables under one name. That is a data-integrity violation, not
   a modeling nuance.
3. **It multiplies the state surface** — per-symbol K means per-symbol `config_state` entries,
   per-symbol invalidation on refit, and per-symbol provenance. The DAG stays simpler with a
   uniform K.

The symbol-specific *instability* the restart sweep saw is real; it is a symptom of K=5's
non-identifiability being data-dependent, not evidence that different symbols want different K.
Once K is estimable, the symbol dependence disappears.

---

## 7. Recommendation (decisive)

### R1 — `feature.hmm.n_components`: 5 -> 3. `feature.hmm.covariance_type`: stays `full`.

The only configuration that clears both bars on 16/16 cells, with the worst cell at
0.9927/0.9870 rather than marginally passing. `diag` is rejected: K=3/diag fails TLT/1d
(0.484/0.292) and K=4/diag fails SMH/1d catastrophically (0.021/-0.311) — dropping the
off-diagonal terms does not buy stability, it costs expressiveness for nothing. K=4/full is
rejected: 15/16 at N=20, failing IWM/1h at 0.617, and pathologically non-monotonic in N
(9 -> 11 -> 15 pass count), which is the same near-tied-optima signature as K=5, just milder.

Free-parameter economics support this independently: K=3/full is 68 free params against
K=5/full's 124. The thinnest cell (TLT/1d, 2,613 obs) gets 38 obs/param at K=3 versus 21 at
K=5.

`config_schema` description must be rewritten with `[rca_analysis]` provenance citing this
document and explicitly recording that BIC prefers K=5 and was overruled by an identifiability
gate. Leaving the old description in place would let a future reader re-derive K=5 from the
same BIC argument.

**Accepted cost:** the label vocabulary shrinks from 5 to 3 —
`{trending_down, ranging, trending_up}`, since `_build_label_map` only emits
`transition_up`/`transition_down` at K>=4. Verified: no production code path in `src/` or
`services/` branches on those two literals (only `regime_writer.py`'s own constants). Two
analysis scripts assume the 5-level ordinal and need updating:
`scripts/analysis/phase144_regime_separation_gate.py` and
`scripts/analysis/hmm_walk_forward_gate4_ic_pilot_spy_1h.py`. Current live distribution shows
`transition_up`/`transition_down` carry ~11.97M of 26.79M non-NULL rows — those bars are not
lost, they redistribute into the three surviving labels. A 3-state regime that is *actually
measured* is worth more than a 5-state regime that is coin-flip-arbitrary on half the corpus.

### R2 — `alpha.hmm.n_restarts`: 1 -> 20, provenance `[rca_analysis]`.

At K=3/full, N=5 already clears both bars 16/16 (0.9267/0.8875) — but the floor sits only
0.027 above the bar, and 5 -> 10 is *slightly non-monotonic* (0.9267 -> 0.9255 at FXY/1d),
proving the selection has not settled. N=20 raises the floor to 0.9927/0.9870, an
order-of-magnitude larger margin. n_restarts is the only knob between a marginal pass and a
decisive one and its cost is bounded and linear.

Measured cost at K=3/full, 40 fits per cell (i.e. 2x what production's n_restarts=20 pays):
1d cells 12-32s, 1h cells 55-97s. Production at n_restarts=20 is therefore roughly 6-16s per
1d cell and 28-49s per 1h cell. **15m/5m are unmeasured and must be sized before rollout** —
5m carries ~390k-bar histories against 1h's ~30-36k.

### R3 — Selection policy: identifiability is a hard gate, BIC is a tiebreaker inside it.

Codify, in `docs/foundation/` and in the `feature.hmm.n_components` schema description: K is
selected as **the smallest K whose two-pool cross-block agreement clears the gate**; BIC ranks
only among configurations that already pass. Never the reverse. §5.5 is the standing evidence
that the reverse ordering selects an inestimable model with full confidence.

### R4 — Quarantine, not coercion, for non-identifiable cells.

16/16 passed here, but this is 8 symbols at 2 timeframes against a corpus heading for 231
symbols x 4 timeframes. A quarantine path is **required infrastructure, not a contingency**.

Design:

- New APR keys, `[rca_analysis]`: `alpha.hmm.identifiability.min_cross_block_agreement = 0.90`,
  `alpha.hmm.identifiability.min_kappa = 0.80`, `alpha.hmm.identifiability.pool_b_base = 1000`.
- `regime_writer.py` runs the second seed pool and the cross-block check as part of the fit, and
  a cell failing the gate **funnels into the existing `_check_occupation_gate` skip path** —
  `regime` stays NULL, with a new `regime_writer.non_identifiable_skipped` log event and a
  metric. It reuses a mechanism that already exists and is already monitored
  (`REGIME_WRITER_NULL_REGIME_REMAINING`); it invents nothing.
- **Explicitly rejected: writing a label with a `regime_confidence` sidecar column.** A label
  that is present will be consumed. Every downstream regime-stratified query would have to
  remember to filter on the sidecar, and the first one that forgets produces a silently wrong
  answer — the exact failure mode CLAUDE.md's design mindset ranks below a loud crash. NULL is
  already correctly handled by exclusion in `ic_engine` and `ensemble_trainer`.
- Cost: doubles fit cost per cell (2 x n_restarts). Acceptable — `regime_writer` is a batch
  service with no latency SLA, and this is the difference between a measured conditioning
  variable and an unvalidated one.

### R5 — Fix the two prior pilot scripts.

`hmm_walk_forward_seed_stability_pilot.py` and `hmm_restart_convergence_pilot.py` fit unscaled
and are therefore not production-representative. Either add the `StandardScaler` step or add a
prominent header stating their numbers describe a differently-conditioned model. Leaving them
as-is guarantees someone re-derives the falsified covariance-threshold hypothesis. Note
`_hmm_seed_stability_check` in `regime_writer.py` is **not** at fault — it takes whatever matrix
its caller supplies, and its only production-path caller would supply a scaled one. The bug is
entirely in the two callers.

---

## 8. Blast radius on already-closed work

`feature_vectors.regime` today was produced at K=5/full, `n_restarts=1`, single seed 42,
standardized. This sweep shows that **at exactly that configuration, 9 of 16 sampled cells are
non-identifiable** — meaning which of several semantically incompatible labelings got written is
determined by seed 42 rather than by the data. Two further cells (EEM/1d, TLT/1d) would trip the
degeneracy gate outright.

Everything that used `regime` as a conditioning variable inherits this. Not re-litigated here,
but explicitly flagged as needing re-verification **after** relabel, not before:

- Phase 144's D-05 regime-separation verdict (`scripts/analysis/phase144_regime_separation_gate.py`)
- Phase 148's gates (already flagged un-settled for a different reason — corpus data-integrity
  bugs, user-corrected 2026-07-31)
- todo 179's Gate 2 concentration/regime diagnostic
- `ic_engine`'s regime-stratified IC measurement and every `feature_ic_scores` row carrying a
  regime stratum
- `ensemble_trainer`'s regime-conditioned training and `alpha_ensemble_ic`

This does not mean those results are wrong. It means their conditioning variable was never
validated and the sign of any bias is unknown. That is a bigger problem than a known-wrong
number.

## 9. What happens to Phase 171

**Phase 171's walk-forward parameter-lookahead fix should resume, not be redesigned — but it
must wait, and its NO-GO gate must be re-run.**

The underlying bug is a confirmed causal-law violation (`_compute_symbol_tf` fits on the entire
history before causally decoding). Per this project's own standing rule, causal bugs get fixed
regardless of measured benefit; the fix's correctness was never in question. Plans 171-01
through 171-05 executed cleanly and `_walk_forward_hmm_full` already standardizes per segment
correctly — the walk-forward *implementation* is not implicated by anything in this document.

What is implicated is **171-05's NO-GO verdict**. G2 was measured with a diagnostic that (a) fit
unscaled, producing 9 cells of covariance crashes that are pure artifact, and (b) ran at K=5,
now known to be non-identifiable regardless of walk-forward. Both inputs to that gate are
known-wrong. The NO-GO cannot stand on that evidence and must not be cited as a settled verdict.

Sequencing: land the K/n_restarts/quarantine change first (it is a prerequisite, since a
walk-forward pilot at K=5 would just re-measure non-identifiability), then re-run 171-05's
staged pilot at K=3/full/n_restarts=20 with a standardizing diagnostic. Plans 171-06 and 171-07
stay paused until that re-run reports.

---

## 10. Proposed next phase

**Phase 172 — "HMM Regime Identifiability Remediation".** This exceeds Phase 171's mandate and
should not be absorbed into it.

| plan | scope |
|---|---|
| 172-01 | APR migration: `feature.hmm.n_components` 5->3 with `[rca_analysis]` provenance citing this doc; `alpha.hmm.n_restarts` 1->20; new `alpha.hmm.identifiability.*` keys. Rewrite `feature.hmm.n_components` and `alpha.hmm.n_restarts` schema descriptions to record the BIC-vs-identifiability conflict and its resolution. |
| 172-02 | `regime_writer.py`: two-pool cross-block identifiability gate wired into both `_compute_symbol_tf` and `_walk_forward_hmm_full`, funneling failures into the existing NULL-skip path; new log event + metric. Fix the two pilot scripts (R5). |
| 172-03 | Widen the sweep before committing the corpus: 15m + 5m timeframes, and a 40-60 symbol sample rather than 8, to confirm K=3/full holds outside this cell set and to size 5m rollout cost honestly. This is the one place I would not skip validation — 16 cells at 2 timeframes is enough to condemn K=5, not enough to certify K=3 corpus-wide. |
| 172-04 | Full-corpus relabel of `feature_vectors.regime` at the new configuration. |
| 172-05 | Downstream re-verification: `ic_engine` regime strata re-run, then re-check Phase 144 D-05 and todo 179's Gate 2 against relabeled data. Update `scripts/analysis/phase144_regime_separation_gate.py` and the Gate 4 ordinal-IC pilot for the 3-level ordinal. |
| then | Phase 171 resumes: re-run 171-05's staged pilot at the new configuration; 171-06/07 unblock on its result. |

**Priority: high, above resuming the discovery track's next candidate.** The strategic plan's
FAIL branch put priority on discovery, and this does not displace that on the merits of finding
new alpha — it displaces it because `regime` is a *measurement primitive* the discovery track
itself stratifies on. Running a 5th Signal-Extraction candidate through a regime-stratified
evaluation whose conditioning variable is seed-arbitrary on half the corpus spends real compute
to produce a result nobody can trust. This is the same class of dependency as the
"prove edge before production infra" rule's stated exception: the discovery/measurement
mechanism itself is not what that rule defers.

Estimated cost: 172-01/02 are small (a migration and a bounded change to one service).
172-03 is the real spend — a wider sweep including 5m, sized in the low hours on 16 workers.
172-04's relabel cost needs 172-03's measurement before it can be quoted honestly.

---

## 11. Artifacts

| file | what |
|---|---|
| `scripts/analysis/hmm_model_complexity_identifiability_sweep.py` | the diagnostic (read-only, no mutation) |
| `171-model-identifiability/sweep-standardized-k345-full-diag.json` | full grid results, K{3,4,5} x cov{full,diag} x N{5,10,20}, 16 cells |
| `171-model-identifiability/sweep-standardized.console.txt` | console log of the above |
| `171-model-identifiability/sweep-unstandardized-ab-k3-k5-full.json` | unstandardized control arm, K{3,5}/full |
| `171-model-identifiability/sweep-unstandardized-ab.console.txt` | console log of the above |

Reproduce:

```
.venv/bin/python scripts/analysis/hmm_model_complexity_identifiability_sweep.py \
    --k-values 3 4 5 --cov-types full diag --n-values 5 10 20 --max-n 20 --max-workers 16
.venv/bin/python scripts/analysis/hmm_model_complexity_identifiability_sweep.py \
    --k-values 3 5 --cov-types full --n-values 5 10 20 --max-n 20 --max-workers 16 --no-standardize
```
