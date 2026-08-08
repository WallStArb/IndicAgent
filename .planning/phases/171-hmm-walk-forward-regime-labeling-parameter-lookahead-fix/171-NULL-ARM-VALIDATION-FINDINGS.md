# Phase 171 follow-on: null-arm validation of the production regime axes Phase 172 would ship

> **This is the decisive document — `171-FINAL-VERDICT.md` is the short-form summary of this
> result plus the full investigation arc; read that first for the compressed version, come here
> for the full per-axis detail and raw evidence.**

**Status:** investigation complete, decisive. **Verdict: 1 of 4 axes validated. `volatility` is
real. `trend` is not. `composite` and `trend_volatility` are volatility partitions wearing trend
labels. Phase 172 proceeds, with 172-01/172-02 revised and one new plan inserted ahead of the
corpus relabel.**
**Author:** Claude Opus 5 (investigative session, 2026-08-08).
**Companion documents:** `171-MODEL-IDENTIFIABILITY-FINDINGS.md` (composite K=5 non-identifiable,
K=3 identifiable), `171-REGIME-DECOMPOSITION-FINDINGS.md` (trend/volatility/volume decomposed),
`171-CANDIDATE-REGIME-AXES-FINDINGS.md` (four new candidate axes, and the discovery that
motivated this document).

**Scope note:** like all three companions, this is NEW work exceeding Phase 171's original
mandate. It is kept out of `evidence/` (which belongs to the executed 171-05 plan) and lives
alongside `171-null-arm-validation/`.

**Nothing in this investigation mutated production.** No `config_state` write, no
`feature_vectors` write, no `regime_writer.py` CLI invocation, no edit to
`services/regime_writer.py` or to either sweep script this one imports from. The only new
artifact is a read-only diagnostic:
`scripts/analysis/hmm_production_regime_axes_null_arm_validation.py`.

---

## 1. Why this exists

Every regime axis tested in this investigation was validated with one battery: two-pool
best-of-N cross-block agreement >= 0.90 AND Cohen's kappa >= 0.80, plus production's occupation
gate and a min-state-separation check.

The candidate-axes study then showed that battery **does not discriminate regime structure from
noise**. Refitting a configuration on an IID-permuted copy of the same series - a series with
zero real structure by construction - cleared every bar just as often. The `persistence` axis was
the clean demonstration: 34/34 real, **34/34 null**, at a measured signal fraction of -0.006. A
two-state HMM on a stationary series is a deterministic threshold split of that series. It is
perfectly reproducible across disjoint seed pools, well separated, and healthily occupied, while
encoding nothing.

That gap was never checked against the axes Phase 172 actually proposes to ship. This document
closes it, for all four:

| axis | columns | K tested | prior evidence |
|---|---|---|---|
| **composite** | 0,1,2,3,4 (production's own model) | 3 | 16/16, min agreement 0.9927 |
| **trend** | 0,2 (log_return, momentum) | 2, 3 | 34/34 at K=3 on the widened 17-symbol run, with a group-specific occupation pattern |
| **volatility** | 1,3 (realized_vol, vol_of_vol) | 2, 3 | 16/16 at both K |
| **trend_volatility** | 0,1,2,3 (composite minus volume) | 3 | 16/16, min agreement 0.9801 |

`volume` is deliberately **not** re-tested. It already fails the weaker battery outright at every
K, so there is no "passes but might be noise" question to resolve for it. Only axes that already
cleared the weaker test need the stronger control.

---

## 2. Headline

**The agreement/kappa/occupation battery passes on pure noise for all four axes. Block
reliability separates them completely, and only one survives.**

| axis | K | battery, real arm | battery, **NULL arm** | ordering column's real-vs-null margin | verdict |
|---|---|---|---|---|---|
| **composite** | 3 | 34/34 | **33/34** | log_return **-0.024** | **PARTIAL - partition real, labels not** |
| **trend** | 2 | 34/34 | **34/34** | log_return **-0.024** | **NOT VALIDATED** |
| **trend** | 3 | 34/34 | **32/34** | log_return **-0.024** | **NOT VALIDATED** |
| **volatility** | 2 | 34/34 | **33/34** | realized_vol **+0.633** | **VALIDATED** |
| **volatility** | 3 | 34/34 | **33/34** | realized_vol **+0.633** | **VALIDATED** |
| **trend_volatility** | 3 | 34/34 | **33/34** | log_return **-0.024** | **PARTIAL - partition real, labels not** |

Three findings, in order of how much they change:

1. **The battery is not evidence for any of these axes.** A permuted series - production's own
   `_build_obs_matrix` rebuilt from IID-shuffled returns and volumes - clears agreement >= 0.90
   and kappa >= 0.80 on **32 to 34 of 34 cells in every single configuration tested**, including
   composite K=3 (33/34) and trend K=2 (**34/34, a perfect tie with the real arm**). Every
   identifiability number published in the three companion documents measures *fit
   reproducibility*, not regime reality. Those numbers are not wrong; they are answering a
   different question than the one they were read as answering. §4.1.
2. **Volatility is real and it is the only thing that is.** `realized_vol`'s block reliability is
   0.62 (1d) / 0.71 (1h) against a null of 0.001, on 17/17 symbols at every window and both
   timeframes, sign test p = 1.2e-10. `log_return` and `momentum` - the two columns that
   constitute the `trend` axis - measure at -0.02 against a null of -0.004, with the sign test
   failing to reject (p = 0.12) and the 1h margin significantly **negative**. There is no
   persistent directional state at 20, 60, 120 or 250 bars. §4.2.
3. **Composite's labels describe the wrong dimension.** `_build_label_map` rank-orders states by
   `means[:, 0]` - the log_return column - and emits `trending_down` / `ranging` /
   `trending_up`. That ordering variable carries a real-vs-null margin of **-0.024**. The
   partition the composite HMM actually finds is driven by `realized_vol` (+0.633). Production's
   `regime` column is a **volatility partition wearing trend labels**, and every downstream
   consumer that reads it as a directional stratification is mis-stratified. §4.3.

**Trend's group-specific-K conclusion does not survive.** The widened 17-symbol run found K=3
degeneracy concentrated in fx/commodity/rates/intl-equity at 1h while all domestic-equity
symbols were clean, and proposed group-specific K. Block reliability shows **no such split**:
equity's `log_return` reliability is +0.05 (1d) / -0.07 (1h), statistically indistinguishable
from fx (+0.06 / -0.06), commodity (-0.01 / -0.01) and rates (-0.02 / -0.14). The "clean" group
is exactly as structureless as the degenerate one. Worse, the null arm at trend K=3 produces
**more** degeneracy than the real arm (7/34 vs 3/34) and hits four domestic-equity cells
(XLF/1h, JPM/1h, SPY/1h, DIA/1h) that the real arm leaves clean. Degeneracy at K=3 is a property
of the fit, not of the data. §4.4.

---

## 3. Method

### 3.1 What is inherited unchanged

Fitting, decoding, canonicalization, the pass bars, and the axis column slices are inherited
**by direct Python import**, so these numbers sit on the same instrument the companion studies
used rather than a re-implementation:

- from `hmm_regime_axis_decomposition_identifiability_sweep.py`: `_AXIS_COLUMNS`,
  `_run_config_cell`, `_passes`, `_fetch_ohlcv`, `_load_config`, `_AGREEMENT_THRESHOLD`,
  `_KAPPA_THRESHOLD`
- from `hmm_candidate_regime_axes_identifiability_sweep.py`: `_block_reliability`,
  `_MIN_PROBE_BLOCKS`, `_sliding`, `_place`, `_rolling_sum`, `_load_regime_groups`
- from `services/regime_writer.py`: `_build_obs_matrix` (production's own observation model)

Configuration is read live from `config_state`: `feature.hmm.n_iter`, `full_cov_min_obs`,
`min_hold_bars`, `min_state_occupation` = 0.05, `vol_window` = `obs_momentum_window` =
`obs_vol_of_vol_window` = 20, `alpha.hmm.random_state` = 42 (pool A base; pool B base 1000).
20 seeds per pool, `covariance_type = full`, `StandardScaler` before every fit (production
parity - the specific bug that bit two earlier pilots in this investigation).

**Scope:** the same 17 symbols as the widened trend check - SPY, IWM, TLT, GLD, XLE, EEM, FXY,
SMH, AAPL, MSFT, GOOGL, AMZN, JPM, QQQ, DIA, XLF, XLK - x {1d, 1h} = **34 cells**. 1d cells hold
2,632-5,123 bars (median 5,049); 1h cells hold 18,377-36,825 (median 36,024). 136 probe jobs and
408 sweep jobs (4 axes x 6 axis-K configurations x 34 cells x 2 arms), 16,320 HMM fits, 1,005s
on 20 workers.

Note that this **also widens** composite, volatility and trend_volatility from the 8 symbols /
16 cells they were originally measured on to the same 17 symbols / 34 cells as trend. Their real
arms reproduce their published verdicts on the wider set (composite K=3: 34/34, min agreement
0.9889 vs 0.9927 published on 16 cells; trend_volatility K=3: 34/34, min agreement 0.9801,
identical to the published figure).

### 3.2 The null arm

Every configuration is fit twice. The null arm draws one permutation per cell (seeded at
`alpha.hmm.random_state`), applies it jointly to the cell's log returns and log volumes,
**reconstructs a price path from the permuted returns**, and hands the reconstructed
closes/volumes to production's own `_build_obs_matrix`. Every observation column is therefore
rebuilt by production's code from a series with no time dependence whatsoever.

Reconstructing the price path (rather than permuting the finished observation matrix) is what
makes this a genuine counterfactual for production's pipeline: permuting the obs matrix would
destroy the internal consistency between columns that `_build_obs_matrix` creates, and the null
would then be easy to beat for uninteresting reasons. Permutation preserves the unconditional
distribution of returns and volumes exactly, and their contemporaneous relationship exactly,
while destroying all time dependence.

### 3.3 Block reliability, measured per production column

`block_reliability` correlates a statistic estimated on **adjacent disjoint blocks** -
`[i*W, (i+1)*W)` against `[(i+1)*W, (i+2)*W)`. The two estimates share no observation, so
sampling noise cannot contribute to their correlation; by the classical two-parallel-measurements
identity the coefficient **is the fraction of the statistic's variance that is real rather than
estimation error**.

The candidate study probed one primary statistic per axis, because its axes were 2-column
constructs of a single concept. Production's axes are not: `composite` fuses five columns
spanning three families, and `_build_label_map` ranks states by column 0, so the **label
semantics** of composite/trend/trend_volatility rest on `log_return` even when the **partition**
is driven by some other column. Reliability is therefore measured for all five production
columns, and each axis read against both questions.

Block-level analogue of each production column, at block width W:

| column | block statistic | adjacent blocks share raw data? |
|---|---|---|
| `log_return` | sum of log returns over the block (block drift; correlation is scale-free, so block sum and block mean give an identical coefficient) | no |
| `realized_vol` | std of log returns over the block | no |
| `momentum` | block drift / block std - production's own `sum(r)/realized_vol` formula with both windows set to W | no |
| `vol_of_vol` | std over the block of the inner 20-bar realized-vol series | **yes, up to 19 bars** |
| `rel_volume` | mean over the block of production's rel_volume (log volume minus its 20-bar rolling mean) | **yes, up to 19 bars** |

The last two are two-window statistics whose inner estimator straddles the block boundary, which
induces adjacency correlation from overlap alone. **That contamination is present identically in
the null arm** - and it is measurable: `vol_of_vol`'s null reliability at W=20 is **0.399**,
against ~0.001 for the three single-window columns. This is precisely why the verdict is the
real-vs-null margin and not the raw coefficient. It is also why `rel_volume`'s null is a large
*negative* number (-0.499): subtracting a 20-bar rolling mean inside a 20-bar block mechanically
anti-correlates adjacent blocks.

### 3.4 Window choice

Unlike the candidate axes - second- and third-order statistics whose window was a free parameter
that had to be swept so a negative result could be attributed - these axes have an **established
window**: production's `feature.hmm.vol_window` / `obs_momentum_window` /
`obs_vol_of_vol_window`, all 20. **W = 20 is the production-parity headline.** W = 60, 120 and
250 are run alongside as a cheap sensitivity check, because a verdict that flipped with window
would be an artifact of one arbitrary choice and that has to be visible rather than assumed. No
verdict in this document flips with window (§4.2).

### 3.5 The bar

A column carries real structure only when all three hold:

- **persists**: median(real) > 0.10. A regime must survive the block boundary at all. A negative
  coefficient describes an alternating artifact, not a state that persists.
- **beats null**: median(real - null) > 0.10. It is not merely the two-window columns' overlap.
- **consistent**: exact two-sided binomial sign test on #(cells where real > null) rejects at
  p < 0.05. Under "this axis has no persistent structure", a cell's real and permuted
  reliabilities are exchangeable, so that count is Binomial(n, 0.5). This converts a median gap
  into a statement about how often the gap has the same sign.

The 0.10 floors are `[initial_estimate]` - reasoned, not calibrated, and the same magnitude the
candidate study used for its absolute signal floor. Every measured value is printed alongside
every verdict so a reader can apply a different bar without re-running. Nothing in §2 is close
enough to a floor for the choice to matter: the surviving column clears it by 6x and the
rejected columns are the wrong side of zero.

---

## 4. Results

### 4.1 The battery, real arm vs null arm

At N=20 seeds per pool, `covariance_type = full`, 34 cells.

| axis | K | real pass | **NULL pass** | real min_agree | **NULL min_agree** | real degen | NULL degen | real med_sep | NULL med_sep |
|---|---|---|---|---|---|---|---|---|---|
| composite | 3 | 34/34 | **33/34** | 0.9889 | 0.3517 | 0/34 | 0/34 | 1.09 | 1.11 |
| trend | 2 | 34/34 | **34/34** | 0.9958 | **0.9950** | 0/34 | 1/34 | 2.43 | 2.49 |
| trend | 3 | 34/34 | **32/34** | 0.9860 | 0.4613 | 3/34 | 7/34 | 2.20 | 2.24 |
| volatility | 2 | 34/34 | **33/34** | 0.9972 | 0.9147 | 0/34 | 0/34 | 1.92 | 2.04 |
| volatility | 3 | 34/34 | **33/34** | 0.9977 | 0.2293 | 0/34 | 0/34 | 1.00 | 1.04 |
| trend_volatility | 3 | 34/34 | **33/34** | 0.9801 | 0.1959 | 0/34 | 0/34 | 1.08 | 1.11 |

Read the NULL pass column first. **A series with no regime structure at all clears the project's
identifiability bar on 32-34 of 34 cells in every configuration.** trend K=2 is the sharpest
case: 34/34 on both arms, with the null arm's *worst* cell at agreement 0.9950 / kappa 0.9900 -
functionally indistinguishable from the real arm's 0.9958 / 0.9917.

Two secondary observations, both of which cut against reading anything reassuring into this
table:

- **`min_state_separation` does not rescue it.** The null arm's median separation is *higher*
  than the real arm's in all six configurations (e.g. trend K=2: 2.49 null vs 2.43 real). A
  threshold split of a stationary series produces genuinely well-separated clusters. Separation
  measures cluster geometry, and a noise series has perfectly good cluster geometry.
- **The occupation gate does not rescue it either.** It flags 0/34 on the null arm in four of
  the six configurations, and in the fifth (trend K=3) it flags **more** null cells than real
  ones.

The one place the battery does show discrimination is `min_agree` on the *worst* null cell -
0.20 to 0.46 for four configurations, against 0.98-0.99 real. That is a real difference, but it
is a difference in the tail, not in the pass count, and a pass count is what every published
verdict in this investigation was expressed as.

**What the battery does measure, and what it is still good for.** It measures whether the EM
likelihood surface has a single dominant optimum that different seed pools both find. That is a
genuine and necessary property - it is what condemned composite K=5 (7/16) and it is the correct
reason to prefer K=3. It is simply not evidence that the resulting partition corresponds to
anything in the world.

### 4.2 Block reliability, per production column

Median across cells; `margin` = median(real - null); `sign_p` = exact two-sided binomial on
#(real > null).

**W = 20 (production parity), pooled over both timeframes, 34 cells:**

| column | med_real | med_null | **margin** | sign_p | persists | beats null | **real?** |
|---|---|---|---|---|---|---|---|
| `log_return` | -0.023 | -0.004 | **-0.024** | 1.2e-01 | NO | NO | **NO** |
| `realized_vol` | **0.621** | 0.001 | **+0.633** | **1.2e-10** | yes | yes | **YES** |
| `momentum` | -0.016 | -0.002 | **-0.014** | 1.2e-01 | NO | NO | **NO** |
| `vol_of_vol` | 0.475 | 0.399 | +0.086 | 7.7e-07 | yes | NO | borderline |
| `rel_volume` | -0.295 | -0.499 | +0.203 | 1.2e-10 | NO | yes | **NO** |

**By timeframe and window** (median real / median null; cells = 17 per timeframe, 16 at 1d/W=250
where one symbol has too few blocks):

| column | W | 1d real/null | 1h real/null | 1d real>null | 1h real>null |
|---|---|---|---|---|---|
| `log_return` | 20 | +0.009 / -0.003 | **-0.052** / -0.004 | 11/17 | **1/17** |
| `log_return` | 60 | -0.016 / -0.001 | -0.002 / +0.002 | 8/17 | 8/17 |
| `log_return` | 120 | -0.002 / -0.036 | -0.013 / -0.002 | 10/17 | 7/17 |
| `log_return` | 250 | -0.122 / -0.057 | -0.062 / +0.002 | 7/16 | **3/17** |
| `realized_vol` | 20 | **+0.607** / -0.014 | **+0.706** / +0.002 | **17/17** | **17/17** |
| `realized_vol` | 60 | +0.498 / -0.044 | +0.708 / -0.003 | 17/17 | 17/17 |
| `realized_vol` | 120 | +0.423 / -0.032 | +0.674 / -0.004 | 17/17 | 17/17 |
| `realized_vol` | 250 | +0.185 / -0.015 | +0.562 / -0.017 | 15/16 | 17/17 |
| `momentum` | 20 | +0.002 / +0.001 | -0.029 / -0.003 | 8/17 | 4/17 |
| `momentum` | 60 | -0.041 / -0.010 | -0.001 / -0.000 | 6/17 | 9/17 |
| `momentum` | 120 | -0.001 / -0.041 | -0.036 / +0.003 | 12/17 | 5/17 |
| `momentum` | 250 | -0.157 / -0.056 | -0.041 / +0.004 | 4/16 | 4/17 |
| `vol_of_vol` | 20 | +0.471 / +0.386 | +0.483 / +0.414 | 14/17 | 17/17 |
| `vol_of_vol` | 60 | +0.184 / +0.070 | +0.406 / +0.111 | 16/17 | 16/17 |
| `vol_of_vol` | 120 | +0.132 / -0.001 | +0.435 / +0.048 | 16/17 | 16/17 |
| `vol_of_vol` | 250 | -0.009 / -0.008 | +0.311 / +0.001 | 8/16 | 17/17 |
| `rel_volume` | 20 | -0.276 / -0.485 | -0.298 / -0.501 | 17/17 | 17/17 |
| `rel_volume` | 250 | -0.187 / -0.478 | -0.426 / -0.501 | 14/16 | 15/17 |

Readings:

- **`realized_vol` is unambiguous and window-invariant.** 0.42-0.71 real against a null that
  never leaves +-0.05, on every cell of every window and both timeframes. Volatility clustering
  is one of the most robust documented patterns in finance and it measures exactly that way
  here. Nothing about this verdict is marginal.
- **`log_return` and `momentum` have no persistent structure at any horizon tested.** Both hover
  within +-0.05 of zero and of their own nulls at W=20/60/120, and go *negative* at W=250. The
  only statistically significant results either column produces are in the **wrong direction**:
  at 1h, `log_return`'s real arm is below its null on 16 of 17 cells (p = 2.8e-4) and at W=250
  on 14 of 17 (p = 1.3e-2). That is mild intraday mean reversion - real structure of a sort, but
  a state that reverses every block is not a regime.
- **`vol_of_vol` is real but second-order, and at production's window it is mostly overlap.** At
  W=20 its null is 0.399 - the mechanical adjacency correlation §3.3 predicted - and the margin
  is 0.086, below the floor though highly consistent (31/34 pooled, p = 7.7e-7; 17/17 at 1h
  alone, p = 1.5e-5). Once the window
  exceeds the inner 20-bar estimator the contamination drains away and the real signal is plain:
  at 1h, margins of +0.295 (W=60), +0.385 (W=120), +0.292 (W=250) on real coefficients of
  0.31-0.44. **`vol_of_vol` carries real structure; the W=20 "NO" is a limitation of measuring a
  two-window statistic at a block width equal to its inner window, not a finding about the
  column.** It does not change the volatility axis's verdict either way, because that axis is
  already validated on its ordering column.
- **`rel_volume` is the one genuinely strange column, and it fails.** Its real coefficient is
  negative at every window and timeframe (-0.19 to -0.43) while its null is more negative still
  (~-0.50). The margin is positive and hugely significant, but the absolute coefficient is on
  the wrong side of zero: block-level `rel_volume` **anti-**predicts the next block. That is the
  mechanical consequence of demeaning by a rolling window of the same length as the block. It is
  also entirely consistent with the decomposition study's finding that the volume axis never
  identifies at any K.

### 4.3 Per-axis verdicts

**`volatility` (cols 1,3) - VALIDATED.** Its ordering column, `realized_vol`, is the strongest
result in this investigation: +0.633 margin, 17/17 cells at every window and timeframe,
p = 1.2e-10. The label ordering (`calmest .. most turbulent` by `realized_vol` rank) is defined
on the dimension that actually carries the structure. Its second column, `vol_of_vol`, is real
at W >= 60 and inconclusive at W = 20 for the measurement reason above. **This axis is validated
at both K=2 and K=3 and is the only axis in the study that is.**

**`trend` (cols 0,2) - NOT VALIDATED.** Both of its columns measure at or below zero against
their own nulls, at every window and both timeframes, with the sign test failing to reject in
the favourable direction anywhere and rejecting in the *unfavourable* direction twice. Its
34/34 identifiability at K=2 and K=3 is the persistence-axis pattern reproduced exactly: a
two-or-three-way threshold split of a series with no persistent state, perfectly reproducible
across seed pools because thresholding is deterministic. **A persistent directional regime does
not exist at 20, 60, 120 or 250 bars on 1d or 1h.**

**`composite` (cols 0-4) at K=3 - PARTIAL: the partition is real, the labels are not.** Exactly
one of its five columns carries real structure (`realized_vol`, +0.633; `vol_of_vol` borderline
and pointing the same way), and it is not the ordering column. `_build_label_map` ranks states by
`means[:, 0]` = `log_return`, whose margin is **-0.024**, and emits `trending_down` /
`ranging` / `trending_up`. So the composite model finds a partition that is real - driven by the
volatility columns - and then names its states after a dimension that carries nothing. The
consequence is not cosmetic: any downstream consumer reading `feature_vectors.regime` as a
directional stratification is stratifying on volatility under a directional name, and the
ordering of the three labels is determined by a variable with no persistent signal, which means
even the *rank order* of the three states is unstable in a way the agreement test cannot see
(agreement is computed on the same canonicalization, so a consistently-wrong ordering agrees
with itself perfectly).

**`trend_volatility` (cols 0,1,2,3) at K=3 - PARTIAL, identical diagnosis.** Dropping the volume
column changes nothing about which dimension carries structure or which dimension names the
states. Its real arm reproduces its published 34/34 at min agreement 0.9801 while its null arm
passes 33/34. There is no case for shipping it over plain `volatility`: it adds two columns of
measured noise (`log_return`, `momentum`) to two columns of measured signal, and it inherits
composite's label-semantics defect in full.

### 4.4 Does trend's group-specific-K split survive?

**No, and the null arm shows why it never was a data property.**

Block reliability by `regime_group` (resolved via `ic_engine._build_symbol_regime_class` against
`alpha.regime.groups` - the same routing any group-specific K would have to be expressed
through), at W=20, median real / median null:

| column | tf | UNROUTED | commodity | equity | fx | rates |
|---|---|---|---|---|---|---|
| `log_return` | 1d | -0.06 / +0.02 | -0.01 / -0.03 | **+0.05 / -0.00** | +0.06 / +0.00 | -0.02 / -0.04 |
| `log_return` | 1h | -0.05 / -0.00 | -0.01 / -0.00 | **-0.07 / -0.00** | -0.06 / -0.03 | -0.14 / -0.02 |
| `momentum` | 1d | -0.02 / +0.03 | +0.07 / -0.02 | +0.00 / +0.01 | +0.05 / -0.01 | -0.04 / -0.04 |
| `momentum` | 1h | -0.03 / -0.00 | -0.00 / +0.00 | -0.04 / -0.00 | -0.01 / -0.03 | -0.04 / -0.01 |
| `realized_vol` | 1d | +0.54 / -0.02 | +0.59 / +0.00 | +0.63 / -0.02 | +0.53 / +0.00 | +0.37 / +0.04 |
| `realized_vol` | 1h | +0.50 / +0.00 | +0.53 / +0.02 | +0.73 / -0.01 | +0.39 / +0.00 | +0.63 / +0.01 |

(`UNROUTED` = AAPL, MSFT, GOOGL, AMZN, JPM - single names with no matching `alpha.regime.groups`
tag prefix. EEM routes to `equity`, not to a separate intl group, under the live config.)

The trend columns are flat across every group. Equity - the group the widened run called "clean
at K=3" - has a `log_return` reliability of +0.05 at 1d and **-0.07 at 1h**, no better than fx
(+0.06 / -0.06) and worse at 1h than commodity (-0.01 / -0.01). **There is no equity-vs-rest
split in the underlying structure because there is no structure in any group.**

`realized_vol`, by contrast, is strongly positive in every group (0.37-0.73), which is the shape
a genuinely universal regime dimension makes.

The occupation-gate pattern that motivated group-specific K also fails to replicate as a data
property. Real arm at trend K=3/full flags GLD/1h (min occupation 0.0287), EEM/1h (0.0319) and
FXY/1h (0.0110), reproducing the widened run's full-covariance result to the digit. (The widened
run also named TLT/1h; that degeneracy occurred only under `covariance_type = diag`, which this
study does not test because production uses `full`. Under `full` TLT/1h has min occupation
0.3132 in both runs.) The **null arm at the same
configuration flags seven cells** - GLD/1h, FXY/1h, EEM/1h **plus XLF/1h, JPM/1h, SPY/1h,
DIA/1h** - four of them domestic equities (XLF/1h, SPY/1h and DIA/1h route to `equity`; JPM/1h
is UNROUTED by tag prefix but is a domestic single name), the group the split declared clean. A
series with no
structure at all produces the same class of degeneracy, in more places, including where the real
arm does not. K=3 degeneracy is a fit pathology, not a signature of a symbol type.

**Conclusion for the group-specific-K proposal: withdraw it.** Not "refine it per group" -
withdraw it, because the axis it was going to be applied to is not validated in any group.

---

## 5. What this does and does not say

Stated explicitly, because a negative result is easy to over-read.

**It does say:**
- There is no persistent directional state at 20-250 bar horizons on 1d or 1h, on these 17
  symbols. A regime, by definition, is something a bar can be *in* for a while; drift is not.
- The identifiability battery cannot distinguish a real partition from a threshold split of
  noise, for any of the four axes, and every pass count published in this investigation must be
  read as a reproducibility measurement.
- Production's `regime` column encodes volatility and is named for direction.

**It does not say:**
- That direction is unpredictable. This measures whether *drift persists as a state*, not
  whether returns are forecastable. A signal that predicts the next bar's direction without any
  persistent regime is untouched by this result.
- That no trend regime exists at any horizon. W=250 on 1d has only 19 block pairs (SE ~ 0.24),
  so the longest horizon tested is weakly powered, and a multi-year directional regime is not
  tested at all. It is worth noting that production's HMM observes at `vol_window` = 20 and
  could not see such a regime even if one existed - so this caveat is a limit on the claim, not
  a loophole for the current model.
- That K=3 is the wrong choice for composite. K=5's non-identifiability is a separate,
  still-valid finding measured against a real property (single dominant optimum), and nothing
  here rehabilitates it.
- That `vol_of_vol` is noise. It is real at W >= 60; its W=20 result is a measurement artifact
  of block width equalling the inner estimator's window (§4.2).

---

## 6. Verdict for Phase 172

**Phase 172 should PROCEED, with 172-01 and 172-02 revised and one new plan inserted ahead of
the corpus relabel. It should not be blocked, and it should not ship as currently scoped.**

The reasoning: nothing here invalidates the *reason* Phase 172 exists. Composite K=5 is
non-identifiable, that is a real defect measured against a real property, and fixing it is
correct. What this document invalidates is (a) the claim that K=3 is *validated* rather than
merely reproducible, and (b) the label semantics the relabel would bake into the corpus.
Relabelling millions of `feature_vectors` rows with a partition whose state names describe the
wrong dimension is a worse outcome than the current state, because it launders a known defect
into a corpus that downstream work then treats as ground truth.

| plan | current scope | revision |
|---|---|---|
| **172-01** | APR migration: `n_components` 5->3, `n_restarts` 1->20, `alpha.hmm.identifiability.*` | **Proceed, amend provenance.** The `[rca_analysis]` description for `n_components` must cite this document alongside `171-MODEL-IDENTIFIABILITY-FINDINGS.md` and state plainly that K=3 is chosen for *reproducibility*, not because a 3-state regime structure was demonstrated. |
| **172-02** | Wire the two-pool agreement/kappa gate into `_compute_symbol_tf` and `_walk_forward_hmm_full` | **Proceed, reframe, and add a second gate.** Shipping the agreement/kappa gate as-is installs an instrument that passes on 32-34/34 noise cells. Keep it - it catches genuine multimodality - but name it and log it as a **reproducibility** gate, not an identifiability or validity gate, and add a `block_reliability` check on the ordering column as a companion so a cell whose ordering variable carries no structure is visible. |
| **NEW 172-01b** | - | **Fix the label semantics before any relabel.** Two options, and the choice is a real decision: (a) reorder `_build_label_map` to rank by `realized_vol` and emit volatility-flavoured labels, making the name match what the partition encodes; or (b) replace the composite axis with the standalone `volatility` axis - the only validated axis - at K=2 or K=3. This must land before 172-04, not after. |
| **172-03** | Widen the sweep to 15m/5m and 40-60 symbols | **Proceed, with both arms.** Any widened sweep must run the null arm too; a widened pass count without one repeats the exact error this document corrects. Also add the block-reliability probe, which is cheap (4s for 136 cells here against 1,001s for the HMM sweep). |
| **172-04** | Full-corpus relabel of `feature_vectors.regime` | **BLOCKED on 172-01b.** Do not relabel the corpus under the current label semantics. |
| **172-05** | Downstream re-verification | **Proceed after 172-04, expanded.** Every consumer that reads `regime` as directional needs re-examining, not just re-running: `phase144_regime_separation_gate.py`, the Gate 4 ordinal-IC pilot, and any `feature_ic_scores` stratification with `regime_scope = 'symbol_hmm'`. The ordinal interpretation of the 3 levels is only meaningful if the ordering variable is the one carrying structure. |

**On the parallel-cuts revision** (retire the single composite `regime`, replace with parallel
independent `regime_trend` / `regime_volatility` cuts, following `feature_ic_scores.regime_scope`
precedent): this survives, but reduces to **one cut**. `regime_volatility` is validated - real
ordering column, real margin, 17/17 on every window and timeframe, universal across regime
groups. `regime_trend` is not validated and must be dropped. That is a simplification, not a
loss: the parallel-cuts design was motivated by the composite fusing three families into one
compromise partition, and the measured answer is that only one of those families was ever a
regime. Ship `regime_volatility` and stop.

**This also makes 172-01b option (b) the recommendation.** If `volatility` is the only validated
axis, and composite's only real column is `realized_vol`, then replacing the composite axis with
the standalone volatility axis achieves the label fix and the parallel-cuts revision in one
change, and does it by deleting code rather than adding it. K=2 vs K=3 for that axis is open -
both are validated on reliability and both clear reproducibility (34/34), with K=2 showing far
better state separation (1.92 vs 1.00) and K=3 giving a finer stratification. That is a
Phase 172 decision, not a blocker.

---

## 7. Artifacts

| file | what |
|---|---|
| `scripts/analysis/hmm_production_regime_axes_null_arm_validation.py` | the diagnostic; read-only, no production mutation |
| `171-null-arm-validation/null-arm-validation.json` | full raw results: 136 probe rows x 5 columns x 4 windows, 408 sweep cells, per-cell agreement/kappa/separation/occupation for both arms |
| `171-null-arm-validation/null-arm-validation.console.txt` | complete console output including the per-cell progress log |

Reproduce with:

```
.venv/bin/python scripts/analysis/hmm_production_regime_axes_null_arm_validation.py \
    --max-workers 20 \
    --results-path .planning/phases/171-hmm-walk-forward-regime-labeling-parameter-lookahead-fix/171-null-arm-validation/null-arm-validation.json
```
