# Scoring Engine — Transforming Intelligence State Into Actionable Scores

**Version:** 1.0
**Status:** under-review
**Priority:** high
**Last Updated:** 2026-05-31
**Tags:** pgvector, scoring, ic-calibration, composite, percentile-rank, analog-finder, vil, analog-engine-ic-factory

---

## Foundation

This document is an application of the **Vector Intelligence Layer** (`analog-engine-substrate.md`) and builds directly on the machinery defined in **Predictive Feature Intelligence** (`analog-engine-ic-factory.md`). Do not read this as a standalone design.

- VIL-01 owns the substrate: embed, retrieve, four tables, pgvector primitives
- analog-engine-ic-factory owns the production machinery: Outcome Labeler, IC Factory, Analog Finder
- **analog-engine-scoring-engine owns the transformation**: takes analog-engine-ic-factory's outputs and produces a clean, multi-representation Score Object

The scoring engine does not retrieve. It does not label. It does not calibrate features. Its input contract is exactly analog-engine-ic-factory's output: a `list[AnalogResult]` (neighbor id, cosine distance, forward returns per horizon, regime) plus the current `feature_ic_stats` (IC Sharpe weights). It transforms those into a Score Object every consumer can use without understanding the machinery underneath.

It is a pure compute/transform layer — it reads, computes, and writes Score Objects to its own table (`score_cache`). It takes no live action and has no blast radius; the calibration-and-action gate lives entirely with the consumer that would wire a score to the live lever, never here.

---

## The Question Intel-12 Answers

Given everything the intelligence pipeline knows about this bar, **what does history say price will do — at T+5, T+10, T+20 — at the level you want to examine?**

This is not a single query. It is a family of questions at different altitudes. The same computation — k-NN over embedded bar states, forward return distribution of the neighbors — answers all of them, scoped differently:

| Level | Question | Scope |
|---|---|---|
| **L0** | "What does RSI momentum on ES 1m historically say about price in 5, 10, 20 bars?" | Plugin × Symbol × TF |
| **L1** | "What does everything I know about ES 1m say right now?" | All plugins × Symbol × TF |
| **L2** | "Across 1m, 5m, 15m, 1h — where is ES going? Are all TFs pointing the same direction?" | All plugins × Symbol × All TFs |
| **L3** | "What is the overall market intelligence saying?" | All plugins × All symbols |

You drill in to understand a specific plugin's contribution. You zoom out to understand the cross-TF or cross-asset picture. The answer at each level has the same structure — a Score Object with a return distribution, sub-scores, composite, and conviction envelope — just built from a different analog set.

This is a surface system, not a control plane. The scores answer the question "where is price likely to go, and with what confidence, given what we know?" Every consumer — analyst, LLM agent, governance rule — reads those answers and applies its own logic. The scoring engine does not act; it informs.

---

## What Simons Would Demand

Renaissance's edge is not in having better signals — it is in measuring every signal's properties precisely and continuously. The scoring engine is that measurement layer. Simons would demand six things of it:

**1. One query, all representations.**
The k-NN retrieval is the expensive step. All score representations — sub-scores, composite, percentile rank, calibrated probability — are computed from the same analog set in one pass. Redundant retrieval for different views is waste that compounds at bar frequency.

**2. IC Sharpe-weighted, not manually weighted.**
Sub-score weights in the composite are derived empirically from analog-engine-ic-factory's IC Factory output. A feature whose IC is unstable (low IC Sharpe) contributes less to the composite. A feature with IC Sharpe 0.8 contributes more than one with IC Sharpe 0.2. No human tunes these weights — the data does.

**3. Cross-sectional ranking is the headline.**
Absolute scores are hard to compare across symbols, timeframes, and setups. A percentile rank — "ES 1m is 87th percentile among all current opportunities" — is comparable across everything. This is how you answer "which opportunity has the most edge right now?"

**4. Conviction is never optional.**
Every score carries its conviction envelope. A score built on 8 analogs at mean distance 0.18 is shown with wide confidence intervals. One built on 200 analogs at distance 0.04 has tight ones. No score is presented without its conviction — low conviction does not hide the score, it widens the interval.

**5. The null result is first-class.**
If the current bar has no analogs within the distance threshold, the Score Object carries `conviction=NULL` — not zero, not a flat distribution. "We have not seen conditions like these" is a meaningful output. Surface it explicitly.

**6. Scores have half-lives.**
IC Factory weights are refreshed weekly. Embeddings carry `computed_at`. Retrievals filter stale embeddings above a configurable threshold. A score whose contributing features have degraded IC does not silently maintain its weight — the weekly IC Factory run adjusts the composite automatically.

---

## The Transformation Pipeline

One k-NN query returns the analog set. The scoring engine runs a sequential transformation pipeline on that result — no additional retrieval.

```
k-NN analog set (K neighbors + their forward_returns)
        │
        ▼
   Sub-scores ─── directional_hr, expected_r, sharpe_horizon, alignment_z (L2)
   (CIS analogy)  Raw measures from the analog distribution, each independently meaningful
        │
        ▼
   Composite z-score
        IC Sharpe-weighted combination of sub-scores
        Normalized to zero-mean / unit-variance over rolling window
        Self-calibrating: weights update weekly from IC Factory output
        │
        ▼
   Percentile rank
        Where this composite sits among all current opportunities
        Cross-sectionally comparable: ES 1m vs NQ 5m vs ES 5m on the same axis
        │
        ▼
   P(up) + E[R]
        Human-readable / LLM-consumable interpretation
        Absolute (not relative): "63% probability up, expected +0.31R at T+10"
```

All four representations live in one Score Object. Consumers pick the representation they need.

---

## The Return Distribution Curve

The return distribution curve is the primitive from which all sub-scores are derived. Before any scalar aggregation, the analog set produces a full empirical distribution of forward returns — what each of the K similar historical bars actually returned at the target horizon.

This distribution carries far more information than any single summary statistic. A mean of +0.31R tells you almost nothing in isolation. The full curve tells you the probability of each outcome scenario, whether tail risk is symmetric or skewed, and whether the setup is ambiguous (bimodal) or high-conviction (tight unimodal).

```
K=47 analogs at T+10 horizon
─────────────────────────────────────────────
Percentile profile:
  p5:   -0.61R     (5% of analogs lost more than this)
  p25:  -0.08R
  p50:  +0.18R     (median)
  p75:  +0.44R
  p95:  +0.82R

Moments:
  Mean:      +0.31R
  Std:        0.38R
  Skewness:  +0.3   (positive skew — upside tail heavier than downside)
  Kurtosis:   1.8   (light tails)

Scenario probabilities:
  P(loss):        28%
  P(0 to +0.5R):  41%
  P(> +0.5R):     31%

Shape: tight_unimodal
```

Two setups can share an identical mean return and produce entirely different trading decisions. A setup with mean +0.31R and positive skewness is structurally different from one with mean +0.31R and a fat left tail — the expected value is the same but the risk profile is not. The curve surfaces this distinction; the mean alone hides it.

The `ReturnDistribution` is computed once per horizon per k-NN query and attached to the Score Object. All sub-scores are derived from it — no additional retrieval, no redundant computation.

---

## The Four Sub-Scores

These are the components of the composite. Each is computed directly from the analog set and its outcome labels — no additional queries.

### 1. Directional Hit Rate

Fraction of K analogs that moved in the predicted direction at the target horizon. The most interpretable measure — directly answers "what fraction of similar historical bars went up at T+10?"

```
directional_hr = count(analogs where direction == predicted_dir) / K
```

Distance-weighted: analogs closer in feature space contribute more than distant ones. Equal-weighting K neighbors discards the information that proximity itself carries.

### 2. Expected R-Multiple

Mean forward return of K analogs at the target horizon, in R-multiples (forward move / ATR at bar T). R-normalization makes this comparable across regimes and instruments — directly comparable to `pnl_r` in `signal_ledger`.

```
expected_r = distance_weighted_mean(analog.ret_r for analog in K)
```

The confidence interval is the standard error of this weighted mean. Wide CI = disagreement among analogs. Tight CI = analogs cluster around a common outcome.

### 3. Sharpe-at-Horizon

Risk-adjusted return from the analog distribution. E[R] / std(R) across K analogs. Distinguishes a high-mean/high-variance setup from a lower-mean/low-variance setup — the latter may be more tradeable.

```
sharpe_horizon = expected_r / std(analog.ret_r for analog in K)
```

A setup with expected_r = +0.4R and std = 2.1R (Sharpe 0.19) is not the same as expected_r = +0.4R and std = 0.3R (Sharpe 1.33). This sub-score captures that distinction.

### 4. TF Alignment (Level 2 only)

At Level 2 (all plugins × symbol × all TFs), alignment quantifies cross-timeframe confluence — replacing discretionary "I see confluence across timeframes" with measured numbers. "Fraction of TFs agreeing" is too crude: it discards both magnitude and how trustworthy each TF's read is. Level 2 instead produces **two** numbers from the per-TF Level 1 composites `z_tf` and their conviction weights `w_tf` (from analog count / distance):

```
alignment_z   = Σ w_tf · z_tf  /  Σ w_tf          # conviction-weighted aggregate — direction AND magnitude
coherence     = 1 − weighted_std(z_tf) / scale     # ∈ [0,1] — how unanimous the TFs are
```

- `alignment_z` **is** the Level 2 composite: the symbol's all-TF directional view, weighting each TF by how much its analog set can be trusted, not by an arbitrary TF-duration constant. The per-TF breakdown is always carried alongside so a consumer can apply its own horizon preference (a scalper weights 1m, a swing trader weights 1h).
- `coherence` is the confluence number. High `|alignment_z|` **with** high `coherence` = genuine multi-TF confluence. High `|alignment_z|` with **low** coherence = one dominant TF dragging the aggregate — surface it, treat with caution. The two together say something "fraction agreeing" never could.

Computed only at Level 2 by aggregating Level 1 scores per TF. Not applicable at Level 0 or Level 1.

---

## The Composite Z-Score

The naive framing — "IC Sharpe-weighted composite" — is a category error, and naming it forced the fix. IC Sharpe is measured **per feature** (analog-engine-ic-factory). The four sub-scores are **aggregations over analog outcomes**. A sub-score is not a feature, so you cannot weight a sub-score by a feature's IC Sharpe. Two different weighting questions were being conflated. Separating them is the whole solution.

### Where feature IC Sharpe legitimately enters: the metric, not the blend

A feature with zero IC should not influence *which bars count as similar* — otherwise retrieval matches neighbors on noise and every downstream score inherits it. So feature IC Sharpe weights the **distance metric**, upstream of the sub-scores:

- Plain cosine over the embedding treats every dimension equally. We want high-IC features to dominate similarity and zero-IC features to contribute nothing.
- pgvector only does plain cosine, and baking IC weights into the stored vector would force a full re-embed every time the weekly IC Factory reweights. Instead: **candidate-retrieve then IC-weighted re-rank.** VIL's HNSW returns a generous candidate set (e.g. 200) by plain cosine; analog-engine-scoring-engine re-ranks to the final K by an IC-Sharpe-weighted distance, using the current `feature_ic_stats`. ANN for recall, exact IC-weighted distance for precision — weights are always current, no re-embed churn.

This is where analog-engine-ic-factory's feature IC Sharpe does real work: it shapes the analog set itself. By the time sub-scores are computed, they are computed over an IC-clean set.

### Where the blend weighting comes from: each sub-score's own IC Sharpe

The four sub-scores are themselves predictors. Treat each as a feature and measure its IC Sharpe with the **same IC Factory machinery** — the Spearman correlation between the sub-score's historical values and realized forward returns, out-of-sample, rolling, FDR-corrected. `directional_hr` may carry a higher meta-IC than `sharpe_horizon`; the data says which.

This removes the category error cleanly: **the same IC Sharpe tool is applied at two levels** — feature level (weights the metric) and sub-score level (weights the blend).

**Shared computation, separate ownership.** The IC math is identical for a feature or a sub-score, so it is one stateless utility both layers call — never two copies, never a shared mutable table. But the two are different *grains*: feature IC is keyed `feature × horizon × regime`; sub-score IC is keyed `sub-score × scope × level × horizon`. Collapsing them into one table would mean a null-union schema (a feature has no `level`, a sub-score has no `feature_name`) and would leak analog-engine-scoring-engine's concern into analog-engine-ic-factory's store. So they live in **separate tables, each owned by the layer whose outputs it measures** — feature IC in analog-engine-ic-factory, sub-score IC in analog-engine-scoring-engine — sharing only the computation utility. analog-engine-scoring-engine measures how well its own sub-scores predict; that is its concern, in its table.

**One automated batch, negligible extra cost.** Both measurements run on the same weekly cadence as part of the same IC fabric — one timer, one failure surface, no second job to maintain and no manual step. The batch is generic over what it measures; each predictor declares its own grain and sink. The marginal compute is trivial: a handful of sub-scores against ~100 features.

### Orthogonalize before blending

The sub-scores are correlated by construction — high `directional_hr` usually means positive `expected_r`. Summing them double-counts the shared signal. So whiten the standardized sub-score vector (PCA / Cholesky over the rolling sub-score covariance) before applying the IC-Sharpe weights. The composite is the IC-Sharpe-weighted sum of the *orthogonalized* sub-scores — correlated evidence counted once.

### Normalization

Zero-mean / unit-variance over a rolling window (APR: `analog.scoring.normalization_window_days`, default 90) of historical composites at the same scope and level. A composite of +1.4 means the same thing this week as last month. Both IC-weight sets (feature and sub-score) refresh weekly from the IC Factory — no manual tuning; the composite degrades gracefully as edges decay.

> **Calibration gate — a contract on consumers, not a self-restraint here.** This section specifies the composite's *structure*, not its *constants*. The blend weights, orthogonalization, `ε`/`δ`, and the coherence scale are all open (see Open Questions). analog-engine-scoring-engine computing and writing the composite to `score_cache` is harmless — it actions nothing. The gate lives at the *action boundary*: any consumer that wires `score_cache` → the I7 raise/suppress lever must **not** do so until those constants are empirically validated against accumulated history. Structure now; the consumer acts only after calibration. The discipline belongs where the harm could occur, not on the compute layer.

---

## The Three Output Representations

Percentile rank answers two genuinely different questions, and collapsing them into one number is dishonest. So analog-engine-scoring-engine carries **both**:

**Temporal percentile (primary):** where this composite sits among the trailing 90-day history of composites at the *same* scope/level/horizon. "Is this a strong reading for ES 1m by ES 1m's own standards?" Always well-populated (thousands of historical bars), so it is a genuine smooth percentile. The composite z-score already *is* the temporal standardization; the temporal percentile is its rank form, on a friendlier 0–100 scale. This is the reliable magnitude-of-conviction signal.

**Cross-sectional rank (secondary):** where this composite sits among *all current opportunities* at the same horizon — "which of my live setups is strongest right now?" With ~5 symbols × 4 TFs the universe is ~20, so this is reported as an honest integer rank **with its universe size** ("3rd of 20"), never dressed up as an "85th percentile" that implies resolution we do not have. As the instrument set grows, this gains resolution naturally — the design degrades gracefully. Manufacturing precision the universe cannot support is exactly the kind of self-deception Simons would reject.

**P(up) + E[R]:** The human-readable form. P(up) is the distance-weighted directional hit rate expressed as a probability. E[R] is the expected R-multiple with its confidence interval. These are what goes into LLM swarm prompts: "47 similar bars found — 63% up at T+10, avg +0.31R [CI: +0.08R, +0.54R]."

---

## The Conviction Envelope

Every Score Object carries a conviction envelope. These are not sub-scores — they do not feed the composite. They describe the quality and confidence of the score.

| Field | What it measures |
|---|---|
| `analog_count` | Number of neighbors returned by k-NN |
| `mean_distance` | Average cosine distance of K analogs — lower is more similar |
| `regime_purity` | Fraction of K analogs in the same regime as current bar |
| `distribution_shape` | Characterization: `tight_unimodal`, `bimodal`, `fat_left_tail`, `flat`, `null` |
| `analog_novelty` | Distance to nearest single neighbor — if high, this bar is unprecedented |
| `ic_sharpe_stability` | Rolling std of IC Sharpe for contributing features — low = weights are stable |

`distribution_shape` is inferred from the analog outcome distribution: bimodal means two competing historical outcomes exist; fat_left_tail means asymmetric risk even when mean is positive; null means no analogs within threshold.

`conviction=NULL` when `analog_count < minimum_gate` (APR: `analog.scoring.min_analog_count`, default 10) or all analogs exceed the distance threshold (APR: `analog.retrieval.max_distance`). This is the explicit null result — unprecedented conditions, surfaced directly.

**Regime purity is conviction, never a composite multiplier.** It is tempting to scale the composite by `regime_purity` — but that conflates *how clean the evidence is* with *what the evidence says*. Shrinking a strong, correct signal just because a few off-regime analogs slipped in distorts the magnitude. The right design has two parts:

1. **Default to a hard regime filter at retrieval** (VIL regime-conditioned retrieval). Then the analog set is regime-pure by construction and `regime_purity ≈ 1.0` — the problem mostly disappears upstream.
2. **`regime_purity` measures residual contamination** from soft-matched analogs (e.g. the current bar sits near a regime boundary where I4's regime confidence is split). It acts as a **conviction cap**: below a purity floor, `conviction` is capped at `LOW` and the CI widens — but the composite magnitude is left untouched. Sub-scores are always computed over the same-regime subset.

This resolves the open question both ways at once: hard filter is the default, and purity is conviction — not a knob on the score itself.

---

## Horizon Profile

The horizon profile is a derived output — not a sub-score, not a conviction field. It is computed by running the pipeline at T+5, T+10, T+20 and comparing the composite z-scores `{z5, z10, z20}` across horizons. Classification is a deterministic function of that triple with two tunable constants — a flatness floor `ε` (default 0.3) and a decay fraction `δ` (default 0.4):

```
peak = argmax|z_h|
if max|z_h| < ε:                          character = flat        # no edge at any horizon
elif sign(z5) != sign(z20):               character = mean_revert # early move reverses
elif |z5| is peak and |z20| < δ·|z5|:     character = scalp       # edge concentrated early, decays
elif |z20| >= |z5| (same sign throughout):character = structural  # edge builds / persists
else:                                     character = mixed       # report profile, no clean label
```

Where `ε` = APR `analog.scoring.horizon_flatness_floor` (default 0.3) and `δ` = APR `analog.scoring.horizon_decay_fraction` (default 0.4).

The character is not just a label — **it tells the consumer which horizon to act on.** `scalp` means T+5 is the actionable horizon; `structural` means read T+20; `mean_revert` warns that the early and late horizons disagree and a single-horizon read is misleading. The thresholds `ε`, `δ` are surfaced with the classification so it is honest and testable, never a black box.

The profile is metadata on the Score Object — displayed in the dashboard and injected into LLM prompts as context for what kind of setup this is. It is not a component of the composite.

IC at horizon and the underlying T+5/10/20 outcome labels are owned by analog-engine-ic-factory. The profile characterization is analog-engine-scoring-engine's derived output from those inputs.

---

## The Score Object

```python
@dataclass
class ReturnDistribution:
    horizon_bars: int
    # Percentile profile
    p5: float        # 5th percentile R-multiple
    p25: float
    p50: float       # median
    p75: float
    p95: float
    # Moments
    mean: float
    std: float
    skewness: float  # positive = upside tail heavier; negative = fat left tail
    kurtosis: float  # > 3 = fat tails relative to normal
    # Scenario probabilities
    p_loss: float        # P(R < 0)
    p_small_gain: float  # P(0 < R < 0.5R)
    p_large_gain: float  # P(R > 0.5R)
    # Shape
    shape: str           # 'tight_unimodal' | 'bimodal' | 'fat_left_tail' | 'flat' | 'null'


@dataclass
class ScoreObject:
    # Identity
    scope: str           # 'ES.1m', 'ES', 'global'
    level: str           # 'plugin', 'tf', 'symbol', 'cross_asset'
    horizon_bars: int    # 5, 10, 20
    computed_at: datetime

    # Return distribution (the primitive — all sub-scores derived from this)
    distribution: ReturnDistribution

    # Sub-scores (orthogonalized + IC-Sharpe-weighted into the composite)
    directional_hr: float
    expected_r: float
    sharpe_horizon: float
    alignment_z: float | None    # Level 2 only — conviction-weighted all-TF aggregate
    coherence: float | None      # Level 2 only — TF unanimity ∈ [0,1]

    # Output representations
    composite_z: float
    temporal_percentile: float          # 0–100, vs own 90d history (primary, smooth)
    cross_sectional_rank: int | None    # Nth strongest of current opportunities
    cross_sectional_universe: int | None  # …of M (honest denominator)
    p_up: float                         # 0.0–1.0
    expected_r_ci: tuple[float, float]  # (lower, upper)

    # Conviction envelope
    analog_count: int
    mean_distance: float
    regime_purity: float         # residual after hard regime filter; caps conviction, never scales composite
    analog_novelty: float
    ic_sharpe_stability: float
    conviction: str | None       # 'HIGH' | 'MEDIUM' | 'LOW' | None (null result)

    # Horizon profile (derived across T+5/10/20 runs)
    horizon_profile: dict[int, float]   # {5: z_score, 10: z_score, 20: z_score}
    horizon_character: str | None       # 'scalp' | 'structural' | 'mean_revert' | 'flat' | None
```

---

## What the Score Surface Looks Like

```
ES 1m — T+10 horizon — 2026-05-31 14:32:00
─────────────────────────────────────────────
Level:            TF (all plugins × ES 1m)
Analogs:          47 bars (mean distance 0.06)
Composite z:      +1.42  [87th percentile]
Directional HR:   63% up
Expected R:       +0.31R  [CI: +0.08R, +0.54R]
Sharpe@T+10:      1.18
Horizon profile:  T+5: +0.12R | T+10: +0.31R | T+20: +0.28R → structural
Regime purity:    81% (38/47 analogs in trending)
Conviction:       HIGH

Return distribution (T+10):
  p5 / p25 / p50 / p75 / p95:  -0.61R / -0.08R / +0.18R / +0.44R / +0.82R
  Skewness: +0.3  Kurtosis: 1.8  Shape: tight_unimodal
  P(loss): 28%   P(0–0.5R): 41%   P(>0.5R): 31%
─────────────────────────────────────────────
TF alignment (ES):  0.74  [1m↑  5m↑  15m↑  1h→]
```

---

## Persistence: `score_cache`

analog-engine-scoring-engine owns the `score_cache` table (VIL owns the embedding/retrieval tables; this is the scoring layer's output store). One row per scope × level × predictor × horizon, overwritten each refresh — it is the queryable surface for the dashboard, Superset, and the percentile-rank universe.

```sql
CREATE TABLE score_cache (
    scope          TEXT             NOT NULL,  -- 'ES.1m', 'ES', 'global'
    level          TEXT             NOT NULL,  -- 'plugin', 'tf', 'symbol', 'cross_asset'
    predictor_id   TEXT,                       -- plugin_name, or NULL for aggregate levels
    horizon_bars   INTEGER          NOT NULL,
    -- sub-scores
    directional_hr DOUBLE PRECISION,
    expected_r     DOUBLE PRECISION,
    sharpe_horizon DOUBLE PRECISION,
    alignment_z    DOUBLE PRECISION,           -- NULL except level='tf'
    coherence      DOUBLE PRECISION,           -- NULL except level='tf'
    -- representations
    composite_z          DOUBLE PRECISION,
    temporal_percentile  DOUBLE PRECISION,     -- vs own 90d history
    cross_sectional_rank INTEGER,              -- Nth of universe
    cross_sectional_universe INTEGER,
    p_up           DOUBLE PRECISION,
    -- conviction
    analog_count   INTEGER,
    mean_distance  DOUBLE PRECISION,
    conviction     TEXT,                        -- 'HIGH'|'MEDIUM'|'LOW'|NULL
    distribution   JSONB,                       -- serialized ReturnDistribution
    computed_at    TIMESTAMPTZ      NOT NULL,
    PRIMARY KEY (scope, level, predictor_id, horizon_bars)
);
```

The full `ReturnDistribution` (percentiles, moments, scenario probabilities) is stored as JSONB rather than exploded into columns — it is read as a unit and never filtered on individual percentiles.

---

## Consumers

The Score Object's production purpose is four enrichment columns on `signal_events`, written by the nightly `analog-enricher` batch job: `analog_score`, `analog_count`, `analog_conviction_lower`, `ood_flagged`. That is what the ML training matrix sees. Everything else below is a research consumer — valuable, but secondary to the ML signal.

AnalogEngine does not govern emission. AlphaEngine's ensemble alpha is the emission trigger. AnalogEngine's scores annotate signals after the fact so the ML model can learn which analog conditions correlate with favorable `counterfactual_pnl_r` outcomes.

| Consumer | Representation used | What they do with it |
|---|---|---|
| **ML training matrix** | `analog_score`, `analog_count`, `analog_conviction_lower`, `ood_flagged` | Cold enrichment of `signal_events` via `analog-enricher`. These four columns enter the ML feature matrix; the model learns the relationship. No human encodes it. |
| **LLM swarm agents** | `p_up` + `expected_r` + `horizon_character` | Grounded evidence injected into prompts: "47 similar bars, 63% up at T+10, avg +0.31R, structural profile." Context for reasoning, not a directive. Reads pre-computed `score_cache` — not a live pgvector query. |
| **eAI fitness** | `composite_z` | Compare agent predictions against empirical score distribution. Score Object is the empirical ground truth eAI measures against. |
| **Research / Superset** | All fields | Full score surface at any scope/level/horizon. Track conviction over time. Surface null results and OOD conditions explicitly. |

---

## Separation of Concerns

```
┌─────────────┐   ┌─────────────────────┐   ┌─────────────────────────────┐
│   VIL-01    │   │      analog-engine-ic-factory        │   │          analog-engine-scoring-engine            │
│             │   │                     │   │                              │
│ embed       │→  │ Outcome Labeler      │→  │ Sub-scores                   │
│ retrieve    │   │   (T+5/10/20 labels) │   │   (directional_hr, E[R],     │
│ 4 tables    │   │ IC Factory           │   │    sharpe, alignment_z)      │
│ pgvector    │   │   (IC Sharpe weights)│   │ Composite z-score            │
└─────────────┘   │ Analog Finder        │   │   (IC Sharpe-weighted)       │
                  │   (k-NN query result)│   │ Percentile rank              │
                  └─────────────────────┘   │ P(up) + E[R]                 │
                                            │ Conviction envelope           │
                                            │ Horizon profile               │
                                            └─────────────────────────────┘
```

Intel-12 receives analog sets and IC weights. It produces Score Objects. It has no database reads beyond what the Analog Finder already retrieved. It has no model training. It has no governance logic.

---

## Compute Profile

| Step | Cadence | Cost |
|---|---|---|
| k-NN retrieval (VIL/analog-engine-ic-factory) | Nightly batch (score_cache pre-computation) | Dominant cost — pgvector query |
| Sub-score computation | Per-bar, in-memory | Negligible — math over K floats |
| Composite z-score | Per-bar, in-memory | Negligible — weighted sum + normalization |
| Percentile rank lookup | Per-bar | One `score_cache` read |
| IC Sharpe weights refresh | Weekly (IC Factory) | Batch — not on hot path |
| Nightly score_cache batch | Nightly | Pre-compute scores for all historical bars |

All four representations are derived from the same k-NN result. No additional retrieval per representation. The scoring engine adds negligible marginal compute to the cost of the Analog Finder query.

---

## Relationship to Existing Work

| Component | Relationship |
|---|---|
| `analog-engine-substrate` | Substrate. Provides k-NN retrieval and table infrastructure. |
| `analog-engine-ic-factory` | Produces all three inputs: analog set (Analog Finder), IC Sharpe weights (IC Factory), outcome labels (Outcome Labeler). |
| `analog-engine-correlation` | Sibling measurement layer (independence). It uses `similarity_pairs` from VIL; scoring engine uses `embeddings` + `forward_returns`. Independent concerns. |
| `analog-engine-ideas` (cost-aware net scoring) | Cost-aware net scoring folds a cost transform into `expected_r` → `expected_r_net`. |
| `AlphaEngine` | Parallel cold-batch system. AlphaEngine owns emission — its `ensemble_alpha` is the signal trigger. AnalogEngine owns enrichment — its `analog_score` is one feature the ML model learns from. Neither system reads the other's tables at run time. |
| `signal_ledger.pnl_r` | R-multiple convention shared. `expected_r` is directly comparable to `pnl_r`. |
| `signal_ledger.pnl_r` | R-multiple convention shared. `expected_r` is directly comparable to `pnl_r`. |
| CIS (`ctf_*` sub-scores) | Direct analogy. CIS blends tier sub-scores into a confluence signal; the scoring engine blends analog sub-scores into a composite. Same pattern, different substrate. |

---

## Open Questions

- **Minimum analog gate:** Below what `analog_count` does `conviction=NULL` fire? → APR: `analog.scoring.min_analog_count` (default 10; calibrate against first 90 days of bar embeddings).
- **Distance-weighting formula:** Inverse distance, Gaussian kernel, or rank-based? All valid — pick one, measure calibration, revisit.
- **Normalization window:** → APR: `analog.scoring.normalization_window_days` (default 90). Needs enough history to be stable but short enough to track regime changes.
- **Sub-score meta-IC cold-start:** sub-score IC needs accumulated `score_cache` history before it is meaningful (unlike feature IC, whose `intelligence_features` history already exists). The composite equal-weights its sub-scores until that history clears a floor → APR: `analog.scoring.subscore_ic_min_obs` (default 500). A consumer should treat the equal-weight cold-start phase as not-yet-actionable. (Grain/ownership is resolved: shared IC utility, separate layer-owned tables — see The Composite Z-Score.)
- **Coherence scale constant:** what normalizer turns weighted-std of per-TF `z` into a clean [0,1] `coherence`? Calibrate against observed cross-TF dispersion.
- **Horizon-character constants:** `ε` and `δ` defaults (0.3, 0.4) may need per-regime calibration → APR: `analog.scoring.horizon_flatness_floor`, `analog.scoring.horizon_decay_fraction`.
- **Score Object width (a contract caveat).** The Score Object is the widest interface in the stack (~25 fields, many consumers) — the most likely to need a breaking change. Resist field creep: a new measure must justify its place in the shared object or live in a consumer that derives it. The narrow `list[AnalogResult]` contract below is the model to imitate; this object is the one to keep disciplined.

_Resolved during gap-fill: the composite weighting knot (two-level IC), percentile universe (temporal + cross-sectional rank-of-M), TF alignment definition (`alignment_z` + `coherence`), regime purity (conviction cap, not multiplier), and horizon-character classification (deterministic rule). See the sections above._

---

## Alternatives Considered

Decisions recorded so they are not silently reopened or misread later.

**Composite: deferred vs designed-now (a deliberate reversal).** An earlier framing held that "a single distilled composite is a future concern — build the primitive first; the composite emerges from validation, not design." This document reverses that *for the structure* and preserves it *for the calibration*. We design the composite's mechanism now (two-level IC weighting, orthogonalization) because the structure is derivable from principle; we defer every constant (weights, `ε`, `δ`, coherence scale) to empirical validation, enforced at the consumer's action boundary (see the calibration gate above), not by restraining the compute layer. The original instinct was right about not fabricating weights from nothing — it was wrong to imply the *architecture* couldn't be reasoned out in advance.

**IC-at-horizon: weight, not sub-score.** Earlier drafts listed IC-at-horizon as one of four score measures. It is not a thing being blended — it is how features and sub-scores *get* their blend weight. Promoting it to the weighting layer (and replacing it in the sub-score slot with `alignment_z`) is intentional. IC-at-horizon was not dropped; it moved up a level. Re-adding it as a sub-score would double-count it.

---

## Principles Alignment

| Principle | How analog-engine-scoring-engine satisfies it |
|---|---|
| **Modularity** | One job: transform analog set → Score Object. No retrieval, no labeling, no governance. |
| **Reuse** | CIS blending pattern reused from I7 aggregation. R-multiple convention shared with signal_ledger. IC Sharpe weights shared from IC Factory. |
| **Separation of concerns** | Production (analog-engine-ic-factory), transformation (analog-engine-scoring-engine), governance (consumers) are fully independent. |
| **Compute efficiency** | One k-NN query, all representations derived in-memory from that result. Zero marginal retrieval cost per additional representation. |
| **Instrument everything** | Score Object written to score_cache — full history of what the engine believed at every point. Queryable in Superset. |
| **No action, no blast radius** | analog-engine-scoring-engine is a pure transform: it computes Score Objects and writes them to `score_cache`. It actions nothing — it informs. The calibration-and-action gate is the consumer's, at the boundary where a score would drive the live lever. |
| **Data quality over model complexity** | No parametric model. IC Sharpe weighting enforces empirical rigor. Null result surfaces uncertainty honestly. |
| **Compounding** | Every bar added to embeddings improves analog retrieval. IC Factory improves with history. Score quality compounds with age. |
