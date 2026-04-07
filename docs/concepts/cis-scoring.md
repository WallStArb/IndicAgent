# Composite Intelligence Score (CIS)

**Last Updated:** 2026-04-07
**Code:** `src/intelligence/trading/cis_scorer.py`

## The Problem CIS Solves

The I7 tier runs 36 setup plugins against every bar. On a typical bar during an active session, multiple plugins fire simultaneously — a TrendFollowing setup, a VWAPDeviation setup, and a CHoCHReversal might all trigger with different directions and confidence scores. How do you decide which signal to publish?

The naive approach (highest confidence wins) is fragile: a plugin with high confidence in the wrong regime still produces a bad trade. Majority voting ignores signal quality. Any hand-tuned priority ordering goes stale as market regimes shift.

CIS solves this by aggregating evidence from the *entire* intelligence pipeline — not just the I7 plugins — into a single directional score, then using that score to validate and redirect the best available signal.

---

## Architecture: 6 Buckets, 1 Score

CIS aggregates 6 intelligence buckets, each reading from a different part of the pipeline, into a single score in **[-1.0, +1.0]** (positive = bullish, negative = bearish).

### Bucket Weights (Bootstrap, version=0)

| Bucket | Top-level Weight | What it draws from |
|--------|-----------------|-------------------|
| **Trend** | 0.20 | Kalman slope, trend regime, SMC trend direction, cross-TF trend alignment, trend confluence |
| **Momentum** | 0.20 | RSI deviation from 50, MACD histogram sign, ROC sign, momentum bias, DivergenceStack plugin |
| **Structure** | 0.15 | Swing pattern, BOS detected×direction, CHoCH detected×direction, CHoCHReversal plugin |
| **Pattern** | 0.05 | Double top/bottom pattern+confidence, H&S pattern+confidence, triangle breakout bias, PatternCompletion plugin |
| **Institutional** | 0.25 | Order block type×strength, FVG type×activity, demand vs supply zone position, FVGFill plugin, SupplyDemandSetup plugin |
| **Regime** | 0.15 | HMM up vs down probability, BOCPD changepoint stability, cross-TF regime agreement, volatility regime, RegimeTransition plugin |

Each bucket score is clamped to [-1.0, +1.0] before being weighted. The final CIS score is:

```
cis_score = clamp(Σ weight_b × bucket_score_b)
```

### Bucket Detail: How Each Reads the Pipeline

**Trend bucket** (`weight=0.20`) reads statistical and structural trend evidence:
- `trend_regime` (I4 TrendRegime): -1 to +1 normalized regime score × 0.35
- Kalman slope direction (I4 KalmanTrend): sign of `kalman_slope` × 0.20
- `smc_trend_direction` (I6 SMC): SMC-derived trend × 0.25
- `ctf_trend_alignment` (I6 Confluence): cross-TF trend alignment × 0.10
- `trend_confluence_score` (I5 TrendConfluence) × 0.10

**Momentum bucket** (`weight=0.20`) reads oscillator consensus:
- RSI mapped `[0,100] → [-1,+1]` around 50: `(rsi_14 - 50) / 50` × 0.30
- MACD histogram sign × 0.25
- ROC-14 sign × 0.20
- `momentum_bias` (I4 MomentumContext) × 0.15
- DivergenceStack plugin `direction × confidence` × 0.10

**Structure bucket** (`weight=0.15`) reads market structure breaks:
- `swing_pattern` (I3 SwingDetector) × 0.30
- `bos_detected × bos_direction` (I6 SMC BOS/CHoCH) × 0.25
- `choch_detected × choch_direction` (I6 SMC BOS/CHoCH) × 0.25
- CHoCHReversal plugin `direction × confidence` × 0.20

**Pattern bucket** (`weight=0.05`) reads chart pattern completions:
- Double top (-1) / double bottom (+1) × `dt_db_confidence` × 0.40
- H&S (-1) / Inverse H&S (+1) × `hs_confidence` × 0.30
- Triangle breakout bias × `tri_confidence` × 0.20
- PatternCompletion plugin `direction × confidence` × 0.10

**Institutional bucket** (`weight=0.25`) reads smart money order flow:
- Order block type × strength (I6 SMC OrderBlocks) × 0.25
- FVG type × (active FVG count > 0) × 0.15
- `in_demand_zone - in_supply_zone` (net zone position) × 0.20
- FVGFill plugin `direction × confidence` × 0.20
- SupplyDemandSetup plugin `direction × confidence` × 0.20

**Regime bucket** (`weight=0.15`) reads hidden state and macro context:
- `hmm_prob_trending_up - hmm_prob_trending_down` (I6 HMMRegime) × 0.35
- BOCPD changepoint stability: 0 if `cp_probability > 0.5` (regime change imminent), else scaled × 0.15
- `ctf_regime_agreement` (I6 Confluence) × 0.20
- `vol_regime × -1` (high volatility is bearish for CIS risk assessment) × 0.20
- RegimeTransition plugin `direction × confidence` × 0.10

---

## The Gate: Two Conditions

CIS only "fires" (returns a non-zero direction) when **both** conditions hold:

1. **Score threshold:** `|cis_score| > 0.35` — the composite score is meaningfully directional
2. **Agreement floor:** at least **3 of 6 buckets** push in the same direction as the score (each bucket must exceed a 0.10 noise floor to count as "agreeing")

```python
CIS_THRESHOLD = 0.35
AGREE_MIN = 3
BUCKET_NOISE = 0.10
```

If either condition fails, CIS returns `direction=0` (neutral). The aggregator falls back to priority-based selection.

The agreement floor prevents a single very-high-weight bucket from dominating. Even if the institutional bucket (0.25) scores strongly, CIS won't fire unless at least two other buckets agree. This forces cross-tier confirmation.

---

## Decision Flow

```
36 I7 plugins fire → aggregator receives signals
        │
        ▼
  Regime gate (HMM eligibility filter, slow-clock 5m/15m)
  Trend plugins     → HMM state 1/2 only
  Mean-reversion    → HMM state 0 only
  Suppressed when:  hmm_regime_prob < 0.60 OR hmm_regime_duration < 5 bars
  Suppressed signals: written to signal_ledger as status='regime_suppressed'
  (shadow signals — tracked for counterfactual MAE/MFE, gate tuning data)
        │
        ▼
  Performance-weighted ranking (_build_all_ranked)
  When setup_performance data exists (n≥30 resolved signals per setup):
    adjusted_rank = perf_multiplier ∈ [0.5, 1.5]  ← Sharpe-normalized
    tiebreak: SETUP_PRIORITY descending
  When no perf data yet:
    adjusted_rank = −SETUP_PRIORITY  ← original priority ordering
  All fired signals (eligible + suppressed) ranked and stored in all_ranked
        │
        ▼
  CISScorer.score(features, plugin_outputs)
        │
   ┌────┴─────────────────────────────────────┐
   │ CIS fires                                │ CIS neutral
   │ |score|>0.35 AND ≥3 buckets agree        │ fallback: priority → majority → HMM tiebreak
   ▼                                          │
Pick best-ranked eligible signal              ▼
matching CIS direction                  Best-ranked eligible signal wins
  └─ if none match direction:           (no winner if unresolvable conflict)
     force-override direction
     on best available signal
        │
        ▼
  Winner published to signal_ledger + aggregated stream
```

**Key distinction:** CIS never drops a signal. It redirects direction. The regime gate is the only hard eligibility filter — suppressed signals are preserved as shadow data, not discarded.

---

## Adaptive Weights (Learning Path)

There are two distinct adaptive weight systems in the aggregator. They operate at different levels and should not be confused.

### 1. CIS Bucket Weights — what CIS *direction* to trust

The bucket weights above are **bootstrap weights (version=0)**: manually tuned, fixed, sufficient for early operation.

The architecture supports **learned weights** loaded from a `cis_weights` database table. When a row with `version > 0` exists, the scorer loads it at startup. Every `CISResult` carries a `weights_version` field, so all signals in `signal_ledger` are traceable to the exact weight set that produced them.

```
signal fires (weight version N)
  → signal_tracker_agent tracks outcome (stop / target / TTL)
  → outcome written to signal_ledger
  → weight-learning job reads outcomes, fits logistic regression per bucket
  → new weights written to cis_weights (version N+1)
  → scorer loads version N+1 at next restart
```

Bootstrap weights get the system producing labeled data. Labeled data trains the next weight version. CIS gradually learns which market conditions precede profitable setups — without any code changes.

### 2. Setup Performance Weights — which *setup plugin* to prefer

Independent of CIS scoring, the aggregator applies a **Sharpe-normalized performance multiplier** to the setup ranking. This governs which plugin wins when multiple eligible signals exist.

```
setup_performance table (updated nightly by weight-updater job):
  win_rate, avg_pnl_r, sample_size, sharpe_ratio — rolling 30-day window

perf_multiplier = 0.5 + (sharpe_rank / n_eligible_setups) → range [0.5, 1.5]
adjusted_rank   = perf_multiplier  (lower = higher priority)

Promotion gate: setup only receives a performance weight when sample_size ≥ 30
  → below threshold: multiplier = 1.0 (neutral, no boost or suppression)
  → prevents overfitting on insufficient data
```

Weights are written to `{env}:setup_performance:weights` in Redis and read by `IntelligencePipelineComputeAgent` at startup and every 60 minutes. Floor of 0.5 ensures no setup is fully suppressed before sufficient evidence accumulates.

**The two systems compose cleanly:** CIS governs which *direction* has cross-tier confirmation; performance weights govern which *setup plugin* to prefer within the eligible pool. Neither overwrites the other.

---

## 5 Plugins That Feed CIS Directly

Five I7 plugins exist specifically as evidence contributors to CIS buckets rather than as standalone setup generators:

| Plugin | Bucket | Contribution |
|--------|--------|-------------|
| `DivergenceStack` | Momentum | direction × confidence → momentum sub-score |
| `CHoCHReversal` | Structure | direction × confidence → structure sub-score |
| `PatternCompletion` | Pattern | direction × confidence → pattern sub-score |
| `FVGFill` | Institutional | direction × confidence → institutional sub-score |
| `RegimeTransition` | Regime | direction × confidence → regime sub-score |

These plugins fire their own signal events (written to signal_ledger) but their primary architectural role is enriching the CIS evidence base.

---

## Related Documentation

- [Intelligence Tiers](intelligence-tiers.md) — I7 setup plugin catalog
- [Regime Classification](regime-classification.md) — HMM, GARCH, BOCPD — what feeds the regime and trend buckets
- [Signal Lifecycle](signal-lifecycle.md) — what happens after a signal is published (the labeled training data)
- **Code:** `src/intelligence/trading/cis_scorer.py`, `src/intelligence/trading/aggregator.py`
