# AlphaEngine — IC Measurement Methodology

**Status:** current — living reference
**Last Updated:** 2026-07-15 (added IC Shrinkage, Weight Combination Methods, Ensemble
Output Validation, Weighting Recipe Governance — these existed in code since Phase 142A/
142B.1 but were undocumented here; the old "Ensemble Weight Derivation" section described
a class, `EnsembleBuilder`, that no longer exists)
**Milestone:** v3.0+
**See also:** `intelligence-alphaengine.md` (conceptual overview), `intelligence-alphaengine.md` (architecture)

---

## Invariants

Non-negotiable statistical constraints. Violating any produces IC measurements that are wrong, biased, or meaningless.

| Invariant | Description | Status |
|-----------|-------------|--------|
| **Executable returns** | `ln(open[T+N+1] / open[T+1])`, not `ln(close[T+N] / close[T])` | ✅ Implemented |
| **Walk-forward gate** | No feature enters the ensemble without held-out validation | ✅ Implemented |
| **IC Sharpe weights** | Stability over time, not raw IC magnitude | ✅ Implemented |
| **Regime-stratified** | Pooled IC is diagnostic only; ensemble uses per-regime IC | ✅ Implemented |
| **Automated decay** | Rolling IC monitor triggers re-solve; no human gates | ⚠️ Designed, not yet built — see `docs/plans/2026-06-30-alphaengine-unfinished.md` |
| **Causal regimes** | Forward-filtered Viterbi only; no smoothed labels in `feature_vectors` | ✅ Implemented |
| **Non-overlapping windows** | Sub-sampled at stride N for IC Sharpe; each observation is independent | ✅ Implemented |

---

## Feature Universe — V1 (54 features)

All features are explicit typed columns in `feature_vectors`. "Promotion" means earning non-zero weight in `ensemble_weights`, not a schema migration.

**Momentum (5)**
| Column | Character |
|--------|-----------|
| `momentum_z_fast` | Fast-scale log return z-scored |
| `momentum_z_mid` | Mid-scale log return z-scored |
| `range_position` | `(close - low) / (high - low)` |
| `bar_close_pos` | Buying pressure: close position within day range |
| `gap_z` | Overnight gap z-scored vs rolling gap distribution |

**Oscillators — APR-backed periods (6)**
| Column | Scale | Character |
|--------|-------|-----------|
| `rsi_fast` | fast | Mean-reversion, short horizon |
| `rsi_mid` | mid | Mid-cycle mean-reversion |
| `rsi_slow` | slow | Longer-cycle mean-reversion |
| `cci_fast` | fast | CCI: deviation from mean, MAD-normalized, short |
| `cci_mid` | mid | CCI: mid-cycle deviation |
| `cci_slow` | slow | CCI: longer-cycle deviation |

RSI and CCI test different mean-reversion hypotheses: RSI uses range normalization; CCI uses mean absolute deviation. Column names encode scale, not period — periods live in APR under `feature.period.{rsi,cci}.{fast,mid,slow}`.

**Trend freshness and strength (4)**
| Column | Character |
|--------|-----------|
| `aroon_fast` | Time since recent high, short window |
| `aroon_slow` | Time since recent high, long window |
| `hma_slope_z` | Hull MA slope z-scored |
| `adx` | Average Directional Index (trend strength) |

**Volume and order flow (7)**
| Column | Character |
|--------|-----------|
| `informed_flow` | Composite informed trader flow signal |
| `volume_z` | Bar volume z-score vs rolling mean |
| `ofi_z` | Order flow imbalance z-scored |
| `ofi_div` | OFI vs price divergence |
| `cvd_slope_z` | Cumulative volume delta slope, z-scored |
| `cmf` | Chaikin money flow |
| `rel_volume` | Volume ratio vs rolling average |

**Volatility and market character (5)**
| Column | Character |
|--------|-----------|
| `vwap_dev_sigma` | Session VWAP deviation in sigma units |
| `atr_z` | ATR z-scored vs rolling ATR |
| `vol_ratio` | Short/long realized vol ratio |
| `hurst` | Hurst exponent (trending vs mean-reverting) |
| `shannon` | Shannon entropy of price |

**HMM regime state (4)**
| Column | Character |
|--------|-----------|
| `hmm_regime_prob` | HMM confidence in current regime state |
| `hmm_entropy` | Regime distribution entropy (clarity) |
| `hmm_duration` | Bars in current regime (maturity signal) |
| `garch_ratio` | GARCH conditional vol vs realized vol ratio |

`hmm_duration` and `hmm_entropy` are orthogonal: entropy measures certainty of the current state; duration measures how long we have been in it.

**Market structure (4)**
| Column | Character |
|--------|-----------|
| `poc_dist_atr` | Distance from Point of Control in ATR units |
| `va_position` | Position within Value Area (0=VAL, 1=VAH) |
| `sr_support_dist` | Distance to nearest support in ATR units |
| `sr_resist_dist` | Distance to nearest resistance in ATR units |

**Macro context (3)**
| Column | Character |
|--------|-----------|
| `vix_z` | VIX level z-scored vs rolling mean |
| `flight_quality` | Flight-to-quality signal (equity/bond ratio) |
| `yield_slope_z` | Yield curve slope z-scored |

**Calendar / session (9)**
| Column | Character |
|--------|-----------|
| `in_ny_session` | NY session active |
| `in_london_kz` | London killzone active (distinct from overlap) |
| `in_overlap` | London/NY overlap active |
| `power_hour` | 3-4 PM ET active |
| `opening_range` | First 30 min of session active |
| `above_wk_vwap` | Price above weekly VWAP |
| `dow_sin` | Day-of-week cyclical encoding (sin) |
| `dow_cos` | Day-of-week cyclical encoding (cos) |
| `month_position` | Position within month [0,1] |

**Cross-timeframe (3)**
| Column | Character |
|--------|-----------|
| `ctf_momentum` | HTF/LTF momentum divergence |
| `ctf_vwap_align` | Cross-TF VWAP alignment |
| `ctf_regime_align` | Cross-TF HMM regime agreement |

**Statistical process / liquidity (4)**
| Column | Character |
|--------|-----------|
| `amihud_illiq_z` | `\|return\| / dollar_volume` z-scored — price impact proxy (Amihud 2002) |
| `high_52w_dist` | Distance from 52-week high — momentum anchor (George & Hwang 2004) |
| `ret_skew_z` | Rolling return skewness z-scored |
| `ret_acf1_z` | Spearman autocorrelation of return[t] vs return[t-1], z-scored |

`ret_acf1_z` is distinct from `momentum_z`: momentum is cumulative return; autocorrelation measures serial dependence of individual bar returns.

### Feature-to-Vector Domain

| Group | `vector_domain` |
|-------|----------------|
| Momentum, oscillators, trend, volume, volatility, HMM, market structure, statistical | `'quant'` |
| Macro context | `'macro'` |
| Calendar / session | `'calendar'` |
| Cross-timeframe | `'quant'` |

`vector_domain` is written to every `feature_ic_scores` and `ensemble_weights` row, enabling per-vector IC aggregation and decay monitoring.

### V1 Exclusions

| Excluded | Reason |
|----------|--------|
| FX pairs | ~21 rows — statistically negligible; different microstructure |
| Candlestick patterns | Low base rate; needs >= 500 true events for IC |
| Categoricals (`smc.amd_phase`, `swing_low_type`, `trend_direction`) | IC requires continuous or binary |
| `obv` (raw) | Unbounded; meaningless without price normalization |
| `macd_line` (raw) | In price units; not cross-sectionally comparable |
| Any feature with null rate > 1% | Missing data biases IC estimates |
| Cross-sectional relative strength | Requires inter-symbol dependency at compute time — breaks pure per-symbol FeatureFactory |

---

## Forward Returns

### The Executable Return

```
R(T, N) = ln( open[T+N+1] / open[T+1] )
```

- T is the `ts` of the observation bar
- T+1 is the first executable entry (open of next bar)
- T+N+1 is the exit bar

`ln(close[T+N] / close[T])` is wrong because close[T] is the observation price, not the executable entry. The difference is material at short horizons (5m/15m) and in markets with opening gaps.

### Lookahead Horizons

Up to four horizons per TF, stored as gradient column names. Horizon count is now per-tf, not a fixed four for every tf: `alpha.ic.active_scales.{tf}` controls which scales are actually attempted for a given tf (e.g. `1h` has only `fast`/`mid` active as of the 2026-07-30 per-tf active-scale-set design), and the bar count for each active scale comes from the per-tf `alpha.ic.lookahead.{tf}.{scale}` APR keys (todo 146 replaced the old single global `alpha.ic.lookahead.{scale}` grid with these).

| Column | Description |
|--------|-------------|
| `return_fast` | Shortest lookahead (APR: `alpha.ic.lookahead.{tf}.fast`) |
| `return_mid` | Mid lookahead |
| `return_slow` | Slow lookahead |
| `return_extended` | Longest lookahead |

The IC engine measures all active scales for a tf. The ensemble uses the horizon with the highest IC Sharpe per (feature, TF, regime) — the researcher does not pre-select.

### Gap Flag

`forward_returns.has_gap_before_entry` is populated but not yet used in IC stratification. A gap means an overnight or holiday break exists between the observation bar and entry — a structurally different return distribution from intraday IC. See unfinished plan for gap-stratified IC.

---

## Feature Normalization

### Cross-Sectional Rank Transform

All features are normalized via within-symbol percentile rank before IC computation. `feature_vectors` stores raw values; rank normalization is applied by the IC Engine at measurement time.

```
pct_rank(v, window) = (rank_of_v_in_window - 0.5) / count_non_null_in_window
```

Result: (0, 1) exclusive. The `- 0.5` avoids boundary effects.

### Why Rank, Not Z-Score

Z-score assumes a distribution shape. RSI is bounded [0,100]. Volume z-score is right-skewed. ATR is in price units. Rank normalization makes none of these assumptions and produces comparable unit-free outputs correct for Spearman IC (which is already a rank correlation).

### Direction Centering

```
centered_score = pct_rank - 0.5     # range: (-0.5, +0.5)
```

Whether high = bullish or bearish is determined empirically by the sign of IC. The same feature (e.g., RSI) may have positive IC in trending regimes and negative IC in ranging ones.

---

## IC Estimation

### Estimator

For each (feature, symbol, TF, regime, lookahead):

```
IC = Spearman( centered_score_t, R(t, N) )
```

Computed over observations where the forward return window is complete (`complete_{horizon} = true`).

**Spearman over Pearson:** returns have fat tails; Spearman is more robust and consistent with the rank-normalized feature inputs.

### Non-Overlapping Sub-Sampling

Consecutive bars are not independent — the N-bar return at T and T+1 share N-1 bars. Using every bar produces IC standard errors that are far too small.

**Solution:** sample every Nth bar (stride = lookahead_bars):

```
observations = rows where (row_index % N) == 0
```

This ensures no forward return window overlaps. Each observation is genuinely independent.

**Effective N:** `floor(T / N)` where T is total bar count. For 25,000 bars at N=5: 5,000 independent observations.

### Bootstrap Confidence Interval

2,000 bootstrap resamples (percentile method, with replacement on sub-sampled pairs). `ic_ci_lower` (2.5th pct) and `ic_ci_upper` (97.5th pct) are stored. Gate: `ic_ci_lower > 0.0` for ensemble eligibility.

### Minimum N

| Condition | Treatment |
|-----------|-----------|
| n_independent < 100 | `reliable = false` — stored, never enters ensemble |
| 100 <= n_independent < 500 | `reliable = true`, IC Sharpe not computed |
| n_independent >= 500 | IC Sharpe eligible |

IC Sharpe computation requires 20,000 independent observations (10 windows × 2,000). Without this, IC Sharpe is undefined and the feature does not enter the ensemble. Get more data — there is no interim path.

---

## Multiple Testing

### BH-FDR Correction

Applied globally across all IC tests in the batch:

1. Sort all p-values ascending: p(1) ≤ p(2) ≤ ... ≤ p(M)
2. Find the largest k such that p(k) ≤ (k/M) × q
3. Reject H₀ for all p(i) where i ≤ k

`q = 0.05`. All tests within the pre-specified feature universe are included — no separate correction per feature or TF.

The feature universe is **fully specified before any IC is measured**. Adding features after observing IC results is p-hacking. The pre-specified count determines the multiple-testing correction threshold.

### Walk-Forward Validation

Primary statistical guard. BH-FDR controls false discovery rate within training; walk-forward confirms out-of-sample replication.

```
Initial training end: training_start + 70% of available data
Fold size:           10% of available data
Number of folds:     3 (APR: alpha.ic.walk_forward_folds)
```

Expanding window (not rolling) — each fold includes all prior data.

**Validation criteria per feature:**

| Criterion | Threshold |
|-----------|-----------|
| IC > 0 in validation fold | >= 2 of 3 folds |
| IC Sharpe across folds | >= 0.4 |
| IC sign consistent | Same sign in >= 2 of 3 folds |

Failure is permanent for the current measurement cycle. The only valid re-evaluation path is additional data, re-running the full protocol from scratch.

**Holdout integrity:** Validation windows are used exactly once. If results are disappointing, the path forward is more data — not relaxed thresholds or adjusted features.

---

## IC Sharpe Computation

IC Sharpe is the primary ensemble weighting signal. A feature with IC=0.04 and IC std=0.01 is far more valuable than IC=0.06 and IC std=0.10.

### Rolling IC Time Series

For each feature passing FDR + walk-forward:

```
IC_Sharpe = mean(IC_t) / std(IC_t)

IC_t computed on non-overlapping windows of W = 2,000 independent observations:
    Window 1: observations [0, 2000)
    Window 2: observations [2000, 4000)
    ...
```

Non-overlapping windows ensure IC_t estimates are independent — required for IC Sharpe to be well-defined.

---

## IC Shrinkage

Computed by `scripts/ops/alpha/ops_ensemble_weight_compare.py`'s upstream sibling,
`scripts/ops/alpha/ops_ic_shrinkage.py` (`src/intelligence/ensemble/shrinkage.py` for the
pure math) — runs between `ic_engine` and `ensemble_trainer` in the corpus pipeline
(`scripts/ops/corpus/ops_corpus_pipeline_run.sh` step 6 of 8).

### The Problem

A single `feature_ic_scores` cell's `ic_sharpe_hac` is a noisy point estimate — especially
for cells near the `n_independent` reliability floor. Two features in the same family
(e.g. `rsi_fast` / `rsi_mid` / `rsi_slow`, all `group_name='oscillator'`) measured in the
same `(regime, tf)` should have correlated true IC; a cell's own noisy draw can be improved
by borrowing strength from its peer group.

### Empirical-Bayes Shrinkage Toward a Leave-One-Out Peer-Group Prior

For every `reliable = true` row, `ic_sharpe_hac` is shrunk toward the mean of its peer
group — same `(feature_registry.group_name, regime, tf)`, excluding the cell itself:

```
prior[cell] = mean(peer_group_ic_values excluding cell)      # leave-one-out
w = n_eff / (n_eff + k)                                      # k = alpha.ic.shrinkage_k (100)
ic_shrunk = w * ic_raw + (1 - w) * prior
```

`n_eff` is the cell's own `n_independent` (from `ic_engine`). As `n_eff → ∞`, `w → 1` (trust
the raw estimate); as `n_eff → 0`, `w → 0` (trust the peer-group prior). `k` is the
"effective observation count" the prior is worth — a cell needs roughly `k` independent
observations of its own before its raw estimate outweighs the group prior. Excluding the
cell itself from its own prior (leave-one-out) is deliberate: including it would let a
cell partially shrink toward a mean containing its own noise, inflating the apparent
benefit of shrinkage. Peer group is keyed on `(group_name, regime, tf)` only — not scoped
to symbol or lookahead — matching the "feature family × regime × tf" spec. Degenerate
cases: `n_eff <= 0` → full shrinkage to the prior (`w=0`); a peer group of size 1 → prior
equals the cell's own value (no leave-one-out is possible).

Writes `ic_shrunk` and `shrinkage_weight` back onto the same `feature_ic_scores` rows
(bulk `UPDATE` by the 6-column PK — `ic_engine.py`'s own write path is untouched).

### Out-of-Fold Acceptance Gate (Hard Gate)

Shrinkage is not trusted by construction — it must prove it predicts *future* IC better
than the raw estimate before the live ensemble is allowed to read it. For every
cross-sectional POOLED reliable cell, the **already in-sample** corpus (`bar_ts <
alpha.validation.oos_start`; Phase 144's true OOS boundary is never touched by this gate)
is split into a train window T and a held-out window T+1 with a lookahead-sized embargo
between them. On window T: compute `ic_raw_T` (Spearman) and a **fresh, window-T-only**
leave-one-out prior → `ic_shrunk_T` (deliberately not the full-corpus prior from the
compute pass above — the test must use only information a live re-run over window T would
have had). Compare both to the realized IC in T+1:

```
PASS iff mean(|ic_shrunk_T − ic_realized_T+1|) < mean(|ic_raw_T − ic_realized_T+1|)
         across all evaluated cells
```

**On PASS:** `alpha.ensemble.ic_input` is flipped from `'ic_sharpe_hac'` to `'ic_shrunk'`
via `ConfigService.set()` (audited in `config_history`). **On FAIL:** the APR value is left
untouched and `ensemble_trainer` keeps reading `ic_sharpe_hac`. `ensemble_trainer` never
checks the gate itself — it just reads whatever `alpha.ensemble.ic_input` currently says;
`ops_ic_shrinkage.py`'s PASS branch is the sole writer of that flip. This step always exits
0 (a gate FAIL is a valid, expected report, not an operational failure) so it never halts
the nightly corpus pipeline between `ic_engine` and `ensemble_trainer`.

**Live status (2026-07-15):** `alpha.ensemble.ic_input = 'ic_shrunk'` — the gate has
passed and shrunk IC is the production input.

---

## Weight Combination Methods

Given the resolved per-feature IC input (`ic_sharpe_hac` or `ic_shrunk`, per above),
`ensemble_trainer.py` turns the vector of eligible per-feature IC values into a portfolio
weight vector. Two methods are implemented, selected by `alpha.ensemble.weight_method`:

### `ic_proportional` (default; live as of 2026-07-15)

The v1 baseline. Two steps, both pure functions in `src/intelligence/ensemble/weights.py`:

1. **`derive_weights`** — normalize each feature's positive-magnitude weight input
   (age-decayed IC-derived "quality" — see Weight Aging below) to sum to 1.0, then cap
   any single feature at `alpha.ensemble.max_feature_weight` (0.20), redistributing excess
   proportionally to uncapped features (iterative, up to 100 passes, converges at
   excess < 1e-10).
2. **`cluster_deflate_weights`** — features are the same underlying signal wearing
   different clothes when pairwise-correlated above `alpha.ensemble.max_cluster_correlation`
   (0.80, computed from the Ledoit-Wolf-shrunk covariance's correlation matrix). A greedy
   union-find merges any such pair into one cluster; any cluster whose summed weight
   exceeds `alpha.ensemble.max_cluster_weight` (0.40) is scaled down proportionally across
   its members. This is what prevents `momentum_z_fast`/`momentum_z_mid`/`momentum_z_slow`
   (typically corr > 0.80) from each drawing full IC-Sharpe weight as if they were three
   independent views.

### `mean_variance` (candidate; not live by default)

Grinold & Kahn's textbook mean-variance-optimal signal combination: `w ∝ Σ⁻¹ · ic_shrunk`,
where `Σ` is the Ledoit-Wolf-shrunk feature covariance. Unlike `ic_proportional`'s binary
cap-and-deflate, this is a full covariance-aware combination — it can down-weight a feature
because of *how* it's correlated with others, not just a pairwise threshold breach.
Numerically gated: `np.linalg.solve` is used (never explicit matrix inversion, standard
numerical-linear-algebra practice), and if the covariance matrix's condition number exceeds
`alpha.ensemble.mv_condition_max` (1000), the solve is judged unreliable and
`ensemble_trainer` **falls back to the `ic_proportional`/`cluster_deflate_weights` path**
rather than emit unstable weights from an ill-conditioned solve. `StratumWeightResult`
records which method actually produced the final vector (`'mean_variance_fallback'`
distinguishes a tripped gate from a clean `mean_variance` solve) for diagnostics.

### Both Methods, Shared Downstream Steps

- **Sign application:** each feature's `ic_sign` (+1/-1, resolved once, not before the
  `mean_variance` solve — see `resolve_stratum_weights`) converts the positive-magnitude
  weight back to a signed contribution at scoring time:
  `alpha_score = Σ(sign(ic[f]) × centered_score[f] × weight[f])`.
- **Weight aging:** IC-derived weight inputs are exponentially decayed by staleness —
  `weight × exp(-days_since_training_window_end / alpha.ensemble.weight_half_life_days)`
  (default 30 days) — before either combination method runs. Beyond
  `alpha.ensemble.weight_stale_max_days` (90), the ensemble falls back to equal weighting
  entirely rather than trust an ordering derived from stale IC. **This is a global,
  single-half-life staleness discount, not the per-feature decay-trigger system described
  in "Alpha Decay Protocol" below** — the two are easy to conflate; only this one is built.
- **`effective_n`** (inverse HHI of the final weight vector) is computed and stored per
  stratum — the `EFFECTIVE_N_GAUGE` OTel signal referenced earlier reads this.
- **Weight versioning:** every `ensemble_trainer` run is stamped with a `weight_version`
  string (e.g. `run_2025122405150000`), written atomically as one transaction per
  `(tf, regime, weight_version, feature_name)` row in `ensemble_weights` — there is no
  `is_active` column; which `weight_version` is live is an APR pointer
  (`alpha.ensemble.weight_version`), not a table flag. `ensemble_alpha` (the per-bar
  composite `alpha_score`) is bulk-inserted per `weight_version` in the same run via
  vectorized matmul (`X @ signed_weights`), never a per-bar Python loop. Writing a partial
  update (e.g. zeroing one feature's weight in place) is an architecture violation — the
  Ledoit-Wolf/cluster/mean-variance combination is invalid for the untouched features
  without a full re-solve; every weight change is a brand new `weight_version`.

---

## Ensemble Output Validation (`EnsembleICEngine`)

Everything above validates *inputs* to the ensemble (per-feature IC). A separate service,
`services/ensemble_ic_engine.py` (`EnsembleICEngine`, Phase 142A), validates the ensemble's
own *composite output* — does `alpha_score` itself correlate with forward returns, using
the same corrected IC methodology as `ic_engine.py` (Fisher-z CI, corpus-level BH-FDR,
expanding-window walk-forward with scale-specific embargo) applied to a single predictor
(`alpha_score`) instead of 54 features. Writes `alpha_ensemble_ic`, one row per
`(symbol, tf, regime, lookahead, weight_version)`.

**Measurement population is `ensemble_alpha` (every scored bar), not `alpha_events`** (the
post-emission-threshold execution subset) — measuring IC only on bars that already cleared
a confidence threshold is post-selection bias: it conditions the correlation test on the
thing being validated. `alpha_events` is the correct population for a downstream question
("is this execution *rule* profitable?"), not this one ("does the ensemble *predictor* have
real IC?"). All queries restrict `bar_ts < alpha.validation.oos_start` — the true
out-of-sample half is reserved for Phase 144's separate OOS gates, never touched here.

---

## Weighting Recipe Governance

A "weighting recipe" is a specific `(ic_input, weight_method)` combination — e.g. shrunk-IC
input with `ic_proportional` combination, or mean-variance combination over the same shrunk
IC vector. New recipes are never promoted to production by assertion; they go through the
same champion/challenger discipline as everything else in this pipeline.

### The Comparison Gate (`ops_ensemble_weight_compare.py`)

Reads `alpha_ensemble_ic` for two `weight_version`s (a champion and a challenger) and
applies a **per-stratum** win rule independently for every `(tf, regime)`:

```
challenger beats champion iff
    challenger.ic_ci_lower > champion.ic_ci_upper     (non-overlapping confidence intervals)
    AND challenger.walk_forward_stable is True         (walk-forward veto — ANDed, not scored)
```

BH-FDR correction is applied across strata. There is no forced single global winner — a
challenger can win on `1h`/trending and lose on `5m`/ranging simultaneously, and both
results are reported and recorded as-is. Every non-`'_pooled'` regime-stratified result
carries a caveat: it is re-validatable once the causal HMM regime refit (todo 026/034)
lands, since regime labels are the one input this gate cannot yet fully certify.

### Recording the Outcome (`concept_registry`, `domain='ensemble_strategy'`)

The comparison's outcome is recorded through `ConceptRegistryService` into the
`concept_registry` / `concept_gate` / `concept_transition_log` tables (migration 231/232,
todo 058) — a live, queryable table, not prose in a plan document. **This is the canonical
place to check "what weighting recipe is live right now and why"** — it does not require
reading `ensemble_trainer.py` or any historical plan doc:

```sql
SELECT name, status, enabled, description
FROM concept_registry WHERE domain = 'ensemble_strategy';
```

As of 2026-07-15, five recipes are registered:

| `name` | `status` | What it is |
|---|---|---|
| `ic_proportional` | `active` | v1 incumbent: per-stratum weights ∝ raw HAC IC Sharpe, cap + cluster-deflate. Genesis incumbent — never evidence-demoted. |
| `e1_shrunk_ic` | `candidate`, but operationally the deployed champion by default | Empirical-Bayes shrunk IC feeding `ic_proportional` weighting (the two sections above, combined). Its deployment is recorded as an `observation` annotation, not a `status` value — the OOS shrinkage gate above is what actually put it live, this row records that fact. |
| `e2_mean_variance` | `candidate` | Mean-variance weighting (`Σ⁻¹ · ic_shrunk`). A 2026-07-09 A/B rejected it (20/20 strata LOSS), but that verdict was later invalidated as an all-long-vs-all-long comparison bug (pre-todo-094); a clean re-run is sequenced in Phase 143.1. |
| `e3_hierarchical_pooling` | `candidate` | Hierarchical partial pooling of per-stratum IC estimates toward `tf`/regime-level means. **No code exists yet** — thesis-only. |
| `e4_decay_half_life` | `candidate` | Per-feature IC decay half-lives, replacing the single global `alpha.ensemble.weight_half_life_days`. **No code exists yet.** Not to be confused with the already-built global half-life above — that is one number for all features, this would be one per feature. |

`domain='ensemble_strategy'` is documented as an explicit exception to the mandatory
`shadow_only` staging state other concept domains require: these candidates are
human-authored, not AI-proposer-sourced, so the OOS A/B judged by `EnsembleICEngine` +
`ops_ensemble_weight_compare.py` is treated as the evidentiary substitute for a live shadow
period, and promotion runs `candidate → active` directly. Every promotion's
`concept_transition_log.notes` cites this exception explicitly.

---

## Design Rationale — Why These Methods, Not Others

The weighting mechanism above (shrinkage, then weight combination, then output validation,
then governed promotion) replaced a working-but-structurally-weak v1 scheme. This section
records what was wrong with the prior approach, what alternatives were considered for each
piece, and why each choice was made — so a future reader does not have to reconstruct this
from `.planning/milestones/v3.1-phases/142B.1-*/142B.1-RESEARCH.md` (a transient phase artifact, not a
durable reference) or from code comments scattered across three files.

### What v1 Got Wrong

The pre-142B.1 scheme (`quality_weight = ic_ci_lower × max(sharpe_floor, ic_sharpe_hac)`,
capped + cluster-deflated — i.e. today's `ic_proportional` method fed with unshrunk IC) is
transparent and sign-safe, but has two defects:

1. **It consumes raw, winner's-curse-biased IC estimates.** Among many measured cells, the
   ones with the largest raw `ic_sharpe_hac` are disproportionately likely to be noisy
   overestimates, not genuinely the best features — the same selection-bias mechanism BH-FDR
   guards against at the *inclusion* decision doesn't protect the *magnitude* used for
   weighting. Feeding this magnitude straight into portfolio weights systematically
   overweights the luckiest draws.
2. **It computes a Ledoit-Wolf covariance matrix every run but only ever uses it for a binary
   clustering heuristic.** Two features correlated at 0.79 (just under the 0.80 cluster-merge
   threshold) both receive full, uncapped-by-correlation weight — the covariance information
   that would tell you exactly how much they overlap is computed and then thrown away.

### Why Shrinkage Before Combination (Not the Reverse, Not Simultaneous)

Shrinking IC estimates (empirical-Bayes toward peer-group prior) and combining them via
covariance-aware weighting (mean-variance) are separable problems, but they are sequenced
deliberately: **shrink first, combine second.** Running `Σ⁻¹ · IC` mean-variance combination
on raw, biased IC would bake winner's-curse bias into weights that *look* statistically
sophisticated (a matrix solve) while still resting on the same overestimated inputs — optimal
weights for noise are not optimal weights for signal. This is standard practice, not
project-specific: shrink inputs before combining, not after.

### Why Leave-One-Out, Not a Naive Full-Group Mean

A prior computed as `AVG(peer_group_ic)` including the cell's own value partially shrinks
that cell toward a mean that contains itself — this understates how much independent
information the prior actually contributes, and inflates the apparent benefit the
out-of-fold gate measures (a false-positive risk on the hard gate itself). This is
immaterial for large peer groups but *not* immaterial for the smallest ones (`feature_registry`
has `group_name` groups as small as n=3, e.g. `cross_tf`, `macro`) — exactly where a
self-inclusive mean would distort the prior most. Leave-one-out is the textbook-correct
empirical-Bayes construction and was implemented rather than approximated.

### Why `solve()`, Not Explicit Matrix Inversion

`mean_variance_weights` uses `np.linalg.solve(Sigma, ic_shrunk)`, never
`np.linalg.inv(Sigma) @ ic_shrunk`. Forming the explicit inverse introduces additional
floating-point rounding error beyond what solving the linear system directly requires —
standard numerical-linear-algebra practice, not a project-specific judgment call.

### Why a Condition-Number Gate With Fallback, Not a Constrained Optimizer

An alternative considered was routing the mean-variance combination through
`scipy.optimize` with explicit constraints (e.g. weight bounds baked into the solve itself)
rather than an unconstrained closed-form `Σ⁻¹·IC` followed by the existing post-hoc cap
logic. Rejected: the existing per-feature cap (`derive_weights`) and `ic_sign` application
must stay unchanged regardless of which combination method produced the raw weights — this
is the minimal-footprint approach, reusing one post-processing path for both methods rather
than building two. The tradeoff this accepts: on an ill-conditioned covariance (features too
collinear for a numerically trustworthy solve — the same near-duplicate-feature population
the 0.80 cluster threshold already targets), the unconstrained solve can produce enormous
offsetting long/short weights on nearly-identical features. Rather than let that happen
silently, `alpha.ensemble.mv_condition_max` (seeded conservatively at 1000, an
`[initial_estimate]` — condition numbers near the ~1e10-1e12 double-precision reliability
ceiling are a looser, riskier bound this project chose not to use) gates the solve and falls
back to the proven `cluster_deflate_weights` path, logged, never a silent skip.

### Why Mean-Variance Skips Cluster Deflation on Success (Not Both)

Once `mean_variance_weights` succeeds, `cluster_deflate_weights` is **not** also applied —
confirmed live in `services/ensemble_trainer.py` (`resolve_stratum_weights`, "cluster
deflation skipped on success"). Running both would double-penalize: `Σ⁻¹·IC` already
performs continuous, covariance-aware decorrelation, making the binary cluster cap redundant
(and potentially over-shrinking) on top of it. Cluster deflation is `mean_variance`'s
*fallback*, not its companion — it only runs when the condition-number gate trips and the
method reverts to `ic_proportional`'s combination path entirely.

### Why the Out-of-Fold Gate Compares Predictions of a Future Window, Not In-Sample Fit

The most tempting wrong implementation of the shrinkage acceptance gate would check "does
`ic_shrunk` fit the *same* window's data better than `ic_raw`" — this trivially passes,
because shrinkage is explicitly constructed to move toward a prior computed from that same
corpus, not because it has demonstrated any predictive value. The gate instead asks a
genuinely out-of-fold question: does `ic_shrunk_T` (computed from window T alone) predict
window T+1's *realized* IC better than `ic_raw_T` does? A healthy gate result shows
heterogeneity — larger shrinkage benefit in sparse/noisy cells, and shrinkage benefit
shrinking toward zero as `n_eff` grows large (since `w → 1` and `ic_shrunk ≈ ic_raw` by
construction there). A gate that passes uniformly on every single cell with no exceptions
would be the warning sign, not the reassurance.

### Why Hierarchical Partial Pooling (E3) and Per-Feature Decay (E4) Were Not Built Yet

Both are registered in `concept_registry` as `candidate` with thesis-only descriptions and
zero implementation. This was a sequencing choice, not a rejection: empirical-Bayes shrinkage
toward a single peer-group mean (what's built) is the simplest member of the same family of
techniques a full hierarchical Bayesian model (E3) would generalize — building the simple
version first, proving it clears its own out-of-fold gate, and only then reaching for a more
complex model if the simple one under-delivers, is the same "prove edge before adding
complexity" discipline applied everywhere else in this codebase. E4 (per-feature IC decay
half-lives) is a genuine capability gap — the live system has only ever had one global
`alpha.ensemble.weight_half_life_days` for all features — but has not yet been prioritized
over other work.

---

## Emission Threshold

### Current Implementation (APR-backed)

Emission thresholds are stored in APR under `alpha.quant.threshold.{tf}` and loaded at publisher startup. Default seeds: 5m=1.5, 15m=1.2, 1h=1.0, 1d=0.8 (alpha_score standard deviations).

These are researcher estimates, not empirically derived. The intended design (empirical sweep over ensemble IC and transaction costs) is not yet implemented — see unfinished plan.

### Cost Gate

`alpha.quant.cost_hurdle.{tf}` gates CI bounds: long requires `alpha_ci_lower > hurdle`; short requires `alpha_ci_upper < -hurdle`. Seeds at 0.0 pending corpus-derived calibration (todo 030).

---

## Alpha Decay Protocol (Designed, Not Yet Built)

The decay system design is recorded here as binding intent. Implementation status: not started — see `docs/plans/2026-06-30-alphaengine-unfinished.md`.

### Architectural Invariants

1. **`ensemble_weights` is the only valid weight store.** Individual feature weight updates are invalid. Any change requires a full Ledoit-Wolf re-solve producing a new `weight_version`.

2. **Decay is regime-stratified.** A feature decaying in one HMM regime does not imply decay in others. The monitor evaluates each (feature, symbol, tf, regime) cell independently.

### Decay Trigger

```
rolling_ic_ci_lower <= alpha.decay.ci_lower_threshold (default: 0.0)
AND
weight[feature][tf][regime] × |rolling_ic_ci_lower| > alpha.decay.materiality_threshold
```

The materiality filter prevents a 0.5%-weight feature triggering a full re-solve on a marginal CI exceedance.

**Regime-shift detection:** If >= `alpha.decay.regime_shift_fraction` (default: 0.60) of features simultaneously show `ic_ci_lower <= 0`, classify as a market regime shift, not individual decay. Do not zero weights — wait for normalization.

### Automated Response

1. Set `feature_ic_scores.is_decaying = true` for affected cells
2. Trigger `EnsembleBuilder` re-solve (excluding decayed cells)
3. New `weight_version` written atomically

### Recovery Gate

Recovery requires genuinely new evidence — not the same data re-examined. Minimum: `W_recovery = 2,000` new independent observations that did not overlap the decay detection window.

```
recovery_eligible_at = decay_triggered_at + (W_recovery × N_subsample × bar_duration)
```

At 5m with N=5: ~128 trading days. At 1h: ~26 trading days.

**No partial restoration.** The Ledoit-Wolf re-solve assigns the correct weight from the recovery evidence. A hard-coded fraction ("restore to 50%") is researcher intervention in an empirical process.
