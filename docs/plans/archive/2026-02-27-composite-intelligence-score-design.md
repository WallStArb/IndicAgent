# Composite Intelligence Score (CIS) — Design

Date: 2026-02-27
Status: Shipped — CISScorer live in aggregator.py
Superseded by: `docs/plans/2026-05-19-cis-stf-mtf-per-bar-design.md`

## Problem

The current I7 aggregator picks a winner from 9 independent plugins using confidence
ranking + regime tiebreak. This is unprincipled: plugins are largely correlated
(most are momentum/trend-based), the confidence scores are hand-crafted floats, and
large amounts of computed intelligence are never consumed by any signal.

Specifically unused: CHoCH detection, FVG open count, all I5 confirmed patterns
(H&S, DT/DB, triangle), RSI+volume divergence stacking, HMM regime probabilities,
BOCPD change-point probability.

## Goal

Replace the current aggregator with a **Composite Intelligence Score (CIS)** that:
- Aggregates ALL intelligence tiers (I1–I6) into 6 decorrelated factor buckets
- Produces a single directional probability score per bar
- Self-improves via logistic regression trained on live signal outcomes
- Starts with designed weights, transitions to learned weights automatically

---

## Architecture

### Overview

```
14 I7 plugins (9 existing + 5 new)
        ↓
6 Factor Bucket Scorers  [-1.0 → +1.0 each]
        ↓
CIS = Σ(w_i × bucket_score_i)     weights from cis_weights table
        ↓
Signal fires when |CIS| > threshold AND ≥ 3 buckets agree direction
        ↓
signal_ledger records: signal + bucket scores + weights_version
        ↓
nightly: weight_updater.py retrains on resolved outcomes → cis_weights v+1
```

### The 5 New I7 Plugins

These are **evidence contributors only** — they compute scores fed to CIS buckets,
not standalone signals. Each is a standard PatternPlugin registered in TIER_I7.

| Plugin | Signal | Key Inputs | Bucket |
|--------|--------|-----------|--------|
| `trad_CHoCHReversal` | Early trend flip | `choch_detected`, `choch_direction`, `hmm_regime` | Structure + Regime |
| `trad_FVGFill` | FVG magnetism | `fvg_type`, `fvg_open_count`, `fvg_top/bottom` | Institutional |
| `trad_PatternCompletion` | Confirmed patterns | `dt_db_*`, `hs_*`, `tri_*` from I5 | Pattern |
| `trad_DivergenceStack` | Dual divergence | `rsi_div_*` + `vol_div_*` (both must agree) | Momentum + Pattern |
| `trad_RegimeTransition` | Regime flip bet | `cp_probability`, `choch_detected`, `hmm_regime` flip | Regime + Structure |

### 6 Factor Buckets

Each bucket aggregates inputs into a `[-1.0, +1.0]` directional score.
Positive = bullish, negative = bearish, near-zero = no edge.

```
Bucket          Weight*   Key Inputs
────────────────────────────────────────────────────────────────
Trend           0.20      trend_regime, kalman_slope,
                          smc_trend_direction, ctf_trend_alignment,
                          trend_confluence_score

Momentum        0.20      roc_14, macd_histogram, rsi_14 vs 50,
                          momentum_context, stoch_k position,
                          DivergenceStack output

Structure       0.15      swing_pattern, bos_detected+direction,
                          choch_detected+direction, trend_strength,
                          CHoCHReversal output

Pattern         0.05†     dt_db_confidence+direction, hs_confidence,
                          tri_confidence+breakout_bias,
                          PatternCompletion output

Institutional   0.25      ob_type+strength, fvg_type, in_demand/supply_zone,
                          sweep_type, premium_position, bsl/ssl_significance,
                          FVGFill output, SupplyDemand output

Regime          0.15      hmm_prob_trending_up/down/ranging, cp_probability,
                          garch_vol_state, vol_regime, ctf_regime_agreement,
                          RegimeTransition output
```

*Bootstrap designed weights. † Pattern starts low — least validated signal class.
 All weights transition to logistic regression learned values after 100 resolved signals.

### CIS Computation

```python
CIS = sum(weights[i] * bucket_scores[i] for i in range(6))
# CIS ∈ [-1.0, +1.0]

direction = +1 if CIS > threshold else -1 if CIS < -threshold else 0
buckets_agreeing = count(s > 0.1 for s in bucket_scores) if direction == 1
                   else count(s < -0.1 for s in bucket_scores)

fires = abs(CIS) > 0.35 AND buckets_agreeing >= 3
```

Signal type label derived from the two highest-weighted agreeing buckets:
- Institutional + Structure dominant → `"cis_smc_structure_long/short"`
- Trend + Momentum dominant → `"cis_trend_momentum_long/short"`
- Pattern + Regime dominant → `"cis_pattern_regime_long/short"`
- etc.

---

## Adaptive Weight Learning

### Outcome Metric

```
signal_quality = (rr_achieved × confidence_at_fire) / vol_regime_at_fire
```

Rewards: large RR wins + high confidence at firing + calm vol regime.
Penalizes: lucky low-confidence wins, volatility-noise wins.

### cis_weights Table

```sql
CREATE TABLE cis_weights (
    id            SERIAL PRIMARY KEY,
    version       INTEGER NOT NULL,
    weights_type  TEXT NOT NULL,          -- 'designed' | 'learned'
    symbol        TEXT DEFAULT 'global',  -- 'global' or e.g. 'ES' for per-symbol (future)
    timeframe     TEXT DEFAULT 'global',
    trend_w       FLOAT NOT NULL,
    momentum_w    FLOAT NOT NULL,
    structure_w   FLOAT NOT NULL,
    pattern_w     FLOAT NOT NULL,
    institutional_w FLOAT NOT NULL,
    regime_w      FLOAT NOT NULL,
    threshold     FLOAT NOT NULL DEFAULT 0.35,
    n_training_samples INTEGER,
    signal_quality_mean FLOAT,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);
-- Active weights = MAX(version) WHERE symbol = 'global'
```

Global weights first. `symbol` column reserved for per-symbol rows once
≥100 resolved signals per symbol are available (23 symbols × 100 = deferred).

### weight_updater.py

Nightly script (or triggered when 20 new outcomes accumulate):

```python
# 1. Load resolved signals with bucket scores + outcomes
query = """
    SELECT sl.bucket_scores, sl.signal_quality
    FROM signal_ledger sl
    JOIN intelligence_features if ON (sl.symbol = if.symbol
        AND sl.feature_ts = if.feature_ts AND sl.feature_tf = if.feature_tf)
    WHERE sl.outcome IS NOT NULL
    AND sl.weights_version IS NOT NULL
"""

# 2. Train logistic regression
X = [[s['trend'], s['momentum'], s['structure'],
      s['pattern'], s['institutional'], s['regime']]
     for s in bucket_scores]
y = [signal_quality > 0]  # binary: quality above mean threshold
model = LogisticRegression(C=1.0, max_iter=500)
model.fit(X, y)

# 3. Normalize coefficients to sum=1, enforce minimums
weights = softmax(model.coef_[0])
weights = clip_and_renormalize(weights, min_w=0.05)

# 4. Write new version to cis_weights
INSERT INTO cis_weights (version, weights_type, ...) VALUES (v+1, 'learned', ...)
```

### Bootstrap Transition

```
n_resolved < 50:   use 'designed' weights, no retraining
50 ≤ n < 100:      train but keep 70% designed / 30% learned blend
n ≥ 100:           full learned weights, nightly retraining
```

All transitions automatic — no code changes required.

---

## Entry Type Improvements (parallel workstream)

Four setup types currently use `at_close` (chase entry) but should use limit entries:

| Setup | New entry type | Limit level |
|-------|---------------|-------------|
| `momentum_breakout_*` | `at_limit` | `swing_high/low` (broken structure level) |
| `squeeze_expansion_*` | `at_limit` | `bb_middle` (squeeze centre) |
| `trend_long/short` | `at_pullback` | `nearest_support/resistance` or key MA |
| `mtf_alignment_*` | `at_pullback` | `ctf` confluence level |

`_resolve_entry()` in `trade_framer.py` gains two new entry type cases.

---

## signal_ledger Schema Additions

New columns to record CIS state at signal firing time:

```sql
ALTER TABLE signal_ledger ADD COLUMN cis_score FLOAT;
ALTER TABLE signal_ledger ADD COLUMN bucket_scores JSONB;
  -- {"trend": 0.4, "momentum": 0.3, "structure": 0.2,
  --  "pattern": 0.0, "institutional": 0.6, "regime": 0.1}
ALTER TABLE signal_ledger ADD COLUMN weights_version INTEGER;
ALTER TABLE signal_ledger ADD COLUMN signal_quality FLOAT;
  -- populated when outcome resolves: (rr_achieved × confidence) / vol_regime
```

---

## What Stays the Same

- All 9 existing I7 plugins — unchanged, still register in TIER_I7
- Plugin protocol (PatternPlugin) — unchanged
- Stream keys — unchanged (`signals:SYMBOL:TF:aggregated`)
- Signal format — unchanged (entry/stop/targets/confidence/signal_type)
- trade_framer.py structural stop/target logic — unchanged
- Dashboard — signal_type label changes but field names stay the same

---

## Implementation Phases

### Phase A: New I7 Plugins (5 plugins)
CHoCHReversal, FVGFill, PatternCompletion, DivergenceStack, RegimeTransition.
Standard plugin protocol. Full unit test coverage. No aggregator changes yet.

### Phase B: CIS Scorer + Aggregator Replacement
CIS bucket scorer as new component. Replace current aggregator with CIS aggregator.
signal_ledger schema additions. Bootstrap with designed weights.

### Phase C: Weight Updater + Adaptive Learning
`weight_updater.py` script. `cis_weights` table migration.
Bootstrap → learned transition logic. Nightly schedule.

### Phase D: Entry Type Improvements
`at_limit` and `at_pullback` in `_resolve_entry()` for 4 setup types.
Dashboard renders new entry type labels.

---

## Success Criteria

- All 602 existing tests pass
- 14 I7 plugins registered and validated by `registry.validate_tier()`
- CIS fires signals in production with `weights_version` logged
- `weight_updater.py` runs without error on ≥50 resolved signals
- `signal_quality` mean improves from bootstrap → learned weights (observable in signal_ledger)
