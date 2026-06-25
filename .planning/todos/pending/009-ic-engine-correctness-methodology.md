# IC Engine Correctness & Methodology Improvements

## Context

Findings from a rigorous first-principles review of the IC engine (ic_engine.py,
regime_writer.py, forward_return_writer.py). Ordered by impact on correctness.
Current corpus run (2026-06-24) completed with known limitations — rerun required
after P0 fixes are applied.

---

## P0 — Correctness Issues (fix before next corpus run)

### 1. Stride = max_lookahead applied to ALL scales

**File:** `services/ic_engine.py:590-592`

```python
max_lookahead = max(lookaheads.values())  # = 60
stride = max(subsample_min_stride, max_lookahead)  # = 60 for all scales
```

A stride of 60 is applied before computing IC across all four lookaheads. The
1-bar scale only needs stride=1; 5-bar needs stride=5. The current design throws
away 60x observations for the 1-bar IC estimate and 12x for 5-bar — starving the
short-horizon estimates of statistical power for no reason.

**Fix:** subsample separately per scale with `stride = lookahead_bars` for that scale.
Each scale gets its own `sub_idx`, `X_sub`, `returns_sub`, `complete_sub`. The shared
matrix approach is the root cause — it forces worst-case stride on all scales.

### 2. Overnight gap contamination in intraday forward returns

**File:** `services/forward_return_writer.py` — LEAD()-based SQL

For 5m/15m/1h TFs, `LEAD(open, 1)` on bar T at 3:55pm gives 9:30am next morning.
The "1-bar-ahead 5m return" is dominated by the overnight gap, not 5 minutes of
intraday price action. Features computed at close[T] measure intraday microstructure;
the label includes an overnight position. IC conflates two different risk regimes
silently.

**Fix:** exclude cross-session bar transitions from forward return computation for
intraday TFs. Flag rows where `bar_ts[T+N]` is in a different trading session than
`bar_ts[T]` and set `complete_{scale} = false` for those rows. Daily TF is unaffected.

---

## P1 — Statistical Methodology Gaps

### 3. BH-FDR applied per (symbol, tf) — meta-level false discovery uncontrolled

232 separate FDR corrections (58 symbols × 4 TFs), each at α=0.05. A feature
passing FDR in 40 of 232 buckets could have ~12 false discoveries by chance.
The ensemble trainer consuming `feature_ic_scores` implicitly treats per-cell FDR
passage as cross-universe evidence — that reasoning is unsound without a meta-level
gate.

**Fix:** in the ensemble trainer, require a feature to pass FDR in a minimum fraction
of (symbol, tf) cells (e.g., >50%) before receiving ensemble weight. Alternatively,
accumulate all p-values globally and run one BH-FDR pass — architectural change but
statistically cleaner.

### 4. Feature collinearity corrupts BH-FDR and biases ensemble weights

BH-FDR assumes approximately independent hypotheses. `momentum_z_fast`,
`momentum_z_mid`, `momentum_z_slow` are correlated — testing all three inflates the
effective evidence for momentum relative to sparser factor clusters. The ensemble
over-weights dense feature clusters not because the factor is stronger but because
it was tested more times.

**Fix:** hierarchical clustering on feature correlation matrix before BH-FDR.
Run multiple-testing correction on one representative per cluster; report IC for
all cluster members but exclude redundant members from the correction. Cluster
membership metadata stored alongside IC scores for ensemble use.

### 5. IC Sharpe min_windows = 10 — estimation error too high

With 10 IC observations, standard error of Sharpe ≈ 1/√10 ≈ 0.32. An IC Sharpe
of 0.5 has a 95% CI of roughly [-0.1, 1.1] — this is noise masquerading as a signal.

**Fix:** raise `alpha.ic.sharpe_min_windows` to 30 (SE ≈ 0.18) before treating IC
Sharpe as a reliable selection criterion. Currently the gate is too loose to distinguish
stable features from lucky ones.

---

## P2 — Architectural Improvements (future milestone)

### 6. HMM parameters fitted on full history — parameter look-ahead bias

`regime_writer` fits GaussianHMM on full available history, then applies causal
forward-filter for label assignment. The forward-filter is correct, but emission
parameters and transition matrix were estimated using future data relative to any
training bar. A 2018 bar is labeled by parameters that "know" 2020 and 2022 behavior.

**Fix:** rolling HMM fit on a growing window in `regime_writer`. At each (symbol, tf),
refit on data up to bar T before assigning T's label. Expensive — likely 10-100x
slower per symbol — but eliminates parameter look-ahead for strict correctness.
Candidate for walk-forward refit on fixed 3-year window rather than full growing window.

### 7. `all_results_global` accumulates forever — OOM at scale

`services/ic_engine.py:990,1014` — list extended with every result dict, never read
after the loop. At 5000 symbols: ~17M dicts in RAM simultaneously.

**Fix:** remove the accumulation. `_emit_health_gauges` is called per-cell before
appending, so removing the global list has no functional impact.

### 8. `training_window_end` derived from live data — PK drift across runs

`SELECT MAX(bar_ts) FROM feature_vectors` is recomputed each run. Adding new symbols
in a future run shifts this timestamp, creating two IC cohorts with different PKs
that the ensemble cannot directly compare.

**Fix:** accept `--training-window-end` as a CLI argument; default to MAX if not
provided but log a warning. Operators running corpus updates should pin the timestamp
to maintain a consistent IC cohort.

---

## Not Captured Here (separate todos)

- Asset-class regime model → `008-asset-class-regime-model.md`
- Cross-sectional (Fama-MacBeth) IC → future milestone scope
- Calendar-time normalized lookaheads → future milestone scope
