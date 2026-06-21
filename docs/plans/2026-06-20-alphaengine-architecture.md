# v3.0 Ground-Up Architecture — Renaissance-Grade Intelligence Platform

**Date:** 2026-06-20
**Status:** Approved design — pre-implementation
**Milestone:** v3.0
**North star:** The researcher produces features. The data discovers confluence. The IC engine arbitrates. No human defines what combinations constitute edge.

---

## Context

The v2.x I1-I7 pipeline is sophisticated feature engineering with a structural flaw that cannot be fixed by tuning: at I5/I6/I7, researchers encoded their hypotheses about what constitutes edge — named patterns, confluence rules, signal firing conditions. This is confirmation bias with extra steps. The system can only discover edges the researcher already believed in. Outcomes are only observed for bars that match the researcher's filter. 138 plugins watching the same chart produce perhaps 15 independent views, not 138.

This design eliminates the signal concept entirely and replaces it with empirical discovery: many simple, orthogonal features measured against forward returns, combined by the data into an ensemble. No human defines what combinations matter. The IC engine finds it.

---

## What Gets Thrown Away

| Component | Reason |
|-----------|--------|
| **I5** (chart patterns, divergences) | Binary researcher-defined pattern detection. "Head and shoulders found" has never had measured IC. |
| **I6** (confluence scoring) | Researcher-defined combination rules. Confluence is discovered by the ensemble, not defined by a human. |
| **I7** (signal plugins, trading setups) | The emission decision, firing conditions, setup logic. The ensemble IS the new I7. |
| **Plugin registry architecture** | Optimizes for "easy to add." Renaissance demands "impossible to add without intent." Replaced by typed function library. |
| **`signal_events` as primary output** | Replaced by `alpha_events`. One emission = ensemble conviction crossed threshold. No predefined theory. |
| **Binary signal concept** | Replaced by a probability estimate: E[return], alpha_score, CI bounds, per bar. |

---

## What Gets Kept (Rewritten Clean)

| Component | Why it survives |
|-----------|----------------|
| **I1-I4 as primitive measurements** | These measure real things: price dynamics, volume/flow, structural geometry, regime state. Measurements, not theories. Rewritten as pure functions. |
| **HMM regime detection** | The stratification mechanism for all IC measurement. Every IC estimate is regime-conditioned. |
| **TimescaleDB + APR + Shadow Governance** | Infrastructure unchanged. APR governs every weight and threshold. Shadow gates every promotion. |
| **Three-table outcome architecture** | alpha_events → trade_frames → trade_executions. Same structure, first table renamed. |

---

## Three-Layer Architecture

The current system collapses prediction, allocation, and execution into a single "signal fired" event. These are separated absolutely.

```
Layer 1: PREDICTION        "What will happen, and how confident are we?"
Layer 2: PORTFOLIO          "Where and when do we act, and at what size?"
Layer 3: EXECUTION          "How do we get filled?"
```

---

## Layer 1: Prediction Engine

### Feature Factory

A single module. 54 pure functions. One typed output. No plugin registry. No dynamic dispatch. No tiers.

Adding a feature = adding a field to `FeatureVector` = a schema migration. The architecture enforces discipline the plugin registry never could.

**Why simple features:** Simons was explicit -- simple features with positive IC beat complex ones with higher in-sample IC because they are more robust. Complex features overfit. The FeatureVector is deliberately constructed from primitives with documented statistical properties and near-zero mutual correlation:

| Feature | Known property |
|---------|---------------|
| Short-term momentum (momentum_z_5/20) | Behavioral persistence (under-reaction); well-documented in equity microstructure |
| Range position | Mean reversion signal; reversal predictor at extremes |
| Gap (gap_z) | Gaps created by order imbalance tend to fill; structural artifact |
| Informed flow (informed_flow) | Separates overnight informed flow from intraday uninformed flow |
| Volatility-normalized return (atr_z) | Removes regime noise; makes returns comparable across vol states |
| Bar close position (bar_close_pos) | Buying/selling pressure within bar |
| Volume deviation (volume_z, rel_volume) | Attention and conviction proxy; high volume = informed participation |

None of these alone is tradeable. An IC-weighted ensemble of genuinely orthogonal primitives is the edge. The 54-feature FeatureVector extends these seed concepts across all cadence layers (session, regime, cross-asset, calendar, cross-timeframe).

Features organized by natural update cadence:

**Bar-level** — computed in-process, every bar, real-time:
```
momentum_z_5      5-bar log return, z-scored (252-bar rolling window)
momentum_z_20     20-bar log return, z-scored
range_position    (close - N-bar low) / (N-bar high - N-bar low)
bar_close_pos     (close - low) / (high - low)
gap_z             (open - prev_close) / ATR, z-scored
informed_flow     (close - open) / ATR
volume_z          volume vs 20-bar mean, z-scored
ofi_z             (buy_vol - sell_vol) / total_vol, z-scored
cvd_slope_z       CVD slope over 5 bars, z-scored
cmf               Chaikin money flow 20
rel_volume        volume / 20-bar average volume
vwap_dev_sigma    (close - session_vwap) / vwap_std
atr_z             ATR normalized by price, z-scored
vol_ratio         5-bar realized vol / 20-bar realized vol
```

**Session-level** — incremental per bar, reset at session open:
```
poc_dist_atr      (close - poc_price) / ATR
va_position       0 below VAL / 0.5 inside VA / 1 above VAH
sr_support_dist   distance to nearest support / ATR
sr_resist_dist    distance to nearest resistance / ATR
```

**Regime-level** — every 30 bars, served from cache (HMM over 500 bars doesn't change meaningfully bar-to-bar; recomputing every bar is waste with no information gain):
```
hmm_regime_prob   P(current regime) from Viterbi filter
hmm_entropy       regime uncertainty (-Σ p_i log p_i)
hurst             Hurst exponent, rolling 252-bar window
shannon           price entropy
garch_ratio       GARCH conditional vol / realized vol
hma_slope_z       Hull MA slope, z-scored
adx               ADX 14
```

**Cross-asset** — per bar of reference instrument:
```
vix_z             VIX level z-scored vs 252-day window
flight_quality    TLT/SPY divergence signal
yield_slope_z     2y-10y spread, z-scored
```

**Calendar** — pre-computed daily, pure timestamp arithmetic, zero runtime cost:
```
in_ny_session     binary
in_overlap        binary (London-NY)
dow_sin           sin(2π × day_of_week / 5)
dow_cos           cos(2π × day_of_week / 5)
month_position    day_of_month / days_in_month
```

**Cross-timeframe** — per bar, reads HTF cached state:
```
ctf_momentum      sign(1h momentum_z) × sign(current TF momentum_z)
ctf_vwap_align    price above/below HTF session VWAP (binary as float)
ctf_regime_align  current TF regime matches HTF regime (binary as float)
```

**Total: 54 features. Zero redundancy. One distinct information dimension each.**

### FeatureVector Contract

```python
@dataclass(frozen=True)
class FeatureVector:
    # Schema is source of truth. Adding a feature = adding a field here.
    # Frozen: immutable after construction, safe to pass across threads.
    momentum_z_5:     float
    momentum_z_20:    float
    range_position:   float
    bar_close_pos:    float
    gap_z:            float
    informed_flow:    float
    volume_z:         float
    ofi_z:            float
    cvd_slope_z:      float
    cmf:              float
    rel_volume:       float
    vwap_dev_sigma:   float
    atr_z:            float
    vol_ratio:        float
    poc_dist_atr:     float
    va_position:      float
    sr_support_dist:  float
    sr_resist_dist:   float
    hmm_regime_prob:  float
    hmm_entropy:      float
    hurst:            float
    shannon:          float
    garch_ratio:      float
    hma_slope_z:      float
    adx:              float
    vix_z:            float
    flight_quality:   float
    yield_slope_z:    float
    in_ny_session:    float
    in_overlap:       float
    dow_sin:          float
    dow_cos:          float
    month_position:   float
    ctf_momentum:     float
    ctf_vwap_align:   float
    ctf_regime_align: float

def compute_features(bar: BarState, cache: FeatureCache) -> FeatureVector:
    # One call per bar. Pure. Testable. No registry. No dynamic dispatch.
    # Bar-level features computed inline.
    # Regime-level features read from cache (updated every 30 bars).
    # Calendar features read from cache (updated once per day).
    ...
```

### IC Engine (cold batch)

Measures Spearman IC between each `FeatureVector` field and forward returns, per `(feature, symbol, TF, regime, lookahead)`:

- Forward return: `ln(open[T+N+1] / open[T+1])` — executable, no look-ahead
- Lookahead windows: 1, 5, 20, 60 bars
- Non-overlapping sub-sampling (every Nth bar) for independence
- Bootstrap CI: 2000 resamples, percentile method
- BH-FDR correction across full test batch (54 features × symbols × TFs × lookaheads)
- 3-fold expanding walk-forward validation
- Gate: `ic_ci_lower > 0.0` at `n >= 500` independent observations

### Ensemble

IC-weighted, Ledoit-Wolf covariance-shrinkage-optimized, effective-N adjusted:

```
alpha_raw = Σ sign(ic[f]) × centered_score[f] × weight[f]
            for f in features where ic_ci_lower[f] > 0

alpha_score = z-score(alpha_raw, rolling 20-day window)
```

Output per bar:
```
alpha_score     IC-weighted conviction [-1, +1], z-scored
E_return        expected return at best-IC lookahead
ci_lower        bootstrap CI lower bound (> 0 required to emit)
direction       long | short
regime          HMM state at bar
effective_n     Ledoit-Wolf adjusted independent predictor count
top_features    JSONB: [{feature, score, ic_weight, ic_sign}] top 5
```

**Alpha emission:** `|alpha_score| > threshold[regime][symbol][tf]` AND `ci_lower > 0`

Threshold empirically derived: minimum alpha_score where `E[return] > estimated_transaction_cost`. Stored in APR under `alpha.threshold.<symbol>.<tf>`.

---

## Layer 2: Portfolio Construction

Takes all alpha emissions across all symbols and TFs. This is where "where and when" is answered. Missing entirely from v2.x.

**Kelly sizing:**
```
position_size = kelly_fraction × (E[return] / vol_estimate)
kelly_fraction: APR alpha.kelly.fraction (default 0.25 — fractional Kelly for robustness)
vol_estimate:   rolling realized vol of the symbol at current TF
```

**Correlation constraints:**
Two correlated alpha emissions don't both receive full Kelly weight. The same effective-N logic from the IC engine applies at the portfolio level — correlated positions share allocation.

**VaR ceiling:**
Portfolio-level max daily drawdown constraint governs total exposure. Per-trade stops are not the primary risk management mechanism — portfolio-level VaR is.

### Vector-Specific Trade Framing → Composite

Each vector produces an opinion on how to frame the trade. The composite is weighted by each vector's IC on `counterfactual_pnl_r` — the data decides which vector frames better, not the researcher.

**V1 Quant frame (only vector initially):**
```
Entry:      open of T+1  — IC-consistent, same price used in IC measurement
Stop:       min(nearest sr_support_dist level, entry - 1.5×ATR)  — tighter wins
Target:     nearest sr_resist_dist level OR hold until alpha reverses
Hold max:   APR alpha.hold_max.<regime>.<tf>  — regime-specific
Early exit: alpha_score sign reversal before target → exit at next open
```

**V3/V6/V7 frame opinions (future):**
Each new vector adds its framing opinion. Composite = weighted average by `counterfactual_pnl_r` IC. No researcher arbitration.

---

## Layer 3: Execution

Routes alpha emissions to IBKR at open of T+1. Records fills in `trade_executions`. Slippage feeds back into Layer 2's transaction cost model for threshold recalibration.

---

## Intelligence Vectors

The architecture is vector-agnostic. Every vector feeds the same Feature Factory → IC Engine pipeline. The IC engine doesn't know or care whether a feature came from price patterns, order flow, or COT data.

| Vector | Domain | V1 status | Feeds |
|--------|--------|-----------|-------|
| V1 Quant | Price/volume/structure/regime | Build now (54 features) | Layer 1 alpha_score |
| V2 Microstructure | Order flow | OFI/CVD in V1; tick upgrade later | Layer 1 |
| V3 Macro | Cross-asset | VIX/yield in V1; expand later | Layer 1 |
| V4 Calendar | Time structure | In V1 (session, dow, month) | Layer 1 |
| V5 Flow | Institutional positioning | Future (CFTC COT) | Layer 2 ambient modifier |
| V6 Gamma | Options market | Future (OPRA) | Layer 2 ambient modifier |
| V7 Qualitative | Sentiment/narrative | Future | Layer 2 ambient modifier |
| V8 Fundamental | Financials | Future (FRED, SEC) | Layer 2 ambient modifier |

**V5-V8 are ambient:** they produce scores at their natural cadence (weekly, event-driven, quarterly), held in in-memory cache. They modify the Kelly threshold in Layer 2 -- they don't feed Layer 1's alpha score. Prediction and allocation remain separated.

---

## Data Model

### New tables

**`feature_vectors`** — one row per (symbol, TF, bar_ts), raw computed values from FeatureFactory:
```sql
CREATE TABLE feature_vectors (
    symbol              text             NOT NULL,
    tf                  text             NOT NULL,
    bar_ts              timestamptz      NOT NULL,
    pipeline_version    text             NOT NULL,
    regime              text,
    regime_label_source text             NOT NULL DEFAULT 'filtered',  -- v3.0 always 'filtered' (forward Viterbi)
    -- All FeatureVector fields, raw computed values (rank normalization applied by IC Engine at measurement time)
    -- Momentum
    momentum_z_5        double precision,
    momentum_z_20       double precision,
    range_position      double precision,
    bar_close_pos       double precision,
    gap_z               double precision,
    -- Oscillators — semantic scale names; periods stored in APR under feature.period.*
    rsi_fast            double precision,
    rsi_mid             double precision,
    rsi_slow            double precision,
    cci_fast            double precision,
    cci_mid             double precision,
    cci_slow            double precision,
    -- Trend freshness — semantic scale names; periods in APR
    aroon_fast          double precision,
    aroon_slow          double precision,
    hma_slope_z         double precision,
    adx                 double precision,
    -- Volume and order flow
    informed_flow       double precision,
    volume_z            double precision,
    ofi_z               double precision,
    ofi_div             double precision,
    cvd_slope_z         double precision,
    cmf                 double precision,
    rel_volume          double precision,
    -- Volatility and regime quality
    vwap_dev_sigma      double precision,
    atr_z               double precision,
    vol_ratio           double precision,
    hurst               double precision,
    shannon             double precision,
    garch_ratio         double precision,
    -- HMM regime state
    hmm_regime_prob     double precision,
    hmm_entropy         double precision,
    hmm_duration        double precision,
    -- Market structure
    poc_dist_atr        double precision,
    va_position         double precision,
    sr_support_dist     double precision,
    sr_resist_dist      double precision,
    -- Macro context
    vix_z               double precision,
    flight_quality      double precision,
    yield_slope_z       double precision,
    -- Calendar / session
    in_ny_session       double precision,
    in_london_kz        double precision,
    in_overlap          double precision,
    power_hour          double precision,
    opening_range       double precision,
    above_wk_vwap       double precision,
    dow_sin             double precision,
    dow_cos             double precision,
    month_position      double precision,
    -- Cross-timeframe
    ctf_momentum        double precision,
    ctf_vwap_align      double precision,
    ctf_regime_align    double precision,
    PRIMARY KEY (symbol, tf, bar_ts)
);
SELECT create_hypertable('feature_vectors', 'bar_ts', chunk_time_interval => INTERVAL '3 months');
```

**`alpha_events`** — one row per alpha emission:
```sql
CREATE TABLE alpha_events (
    symbol              text             NOT NULL,
    tf                  text             NOT NULL,
    bar_ts              timestamptz      NOT NULL,
    direction           text             NOT NULL CHECK (direction IN ('long', 'short')),
    alpha_score         double precision NOT NULL,
    alpha_ci_lower      double precision NOT NULL,
    e_return            double precision NOT NULL,
    effective_n         double precision NOT NULL,
    regime              text,
    weight_version      int              NOT NULL,
    top_features        jsonb,
    -- Frame (composite vector framing opinion)
    entry_price         double precision,   -- open of T+1, populated by execution layer
    stop_price          double precision,
    target_price        double precision,
    hold_bars_max       int,
    -- Lifecycle
    status              text             NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'labeled', 'expired')),
    emitted_at          timestamptz      NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, tf, bar_ts)
);
SELECT create_hypertable('alpha_events', 'bar_ts', chunk_time_interval => INTERVAL '3 months');
```

**Existing tables unchanged:** `outcome_labels`, `feature_ic_scores`, `ensemble_weights`, `ensemble_alpha`, `trade_frames`, `trade_executions`, `market_data_ohlcv`.

**Retired:**
- `signal_events` → `alpha_events`
- `signal_ledger` view → `alpha_ledger` (alpha_events + trade_frames + trade_executions)
- `feature_candidates` (long format) → `feature_vectors` (wide, all 54 features first-class)
- `feature_matrix` (promoted-only wide) → `feature_vectors` (no promotion split needed)

---

## Shadow Governance

Nothing earns weight without measured evidence. Self-correcting at every layer.

- **New feature:** enters at weight=0. IC observations accumulate. `ci_lower > 0` at n≥100 → earns proportional IC Sharpe weight automatically via APR.
- **New vector frame opinion:** enters at weight=0. `counterfactual_pnl_r` measured vs existing composite. Significance gate before any weight assigned.
- **Alpha decay:** `AlphaDecayMonitor` flags decaying (feature, symbol, tf, regime) cells in `feature_ic_scores`. Triggers `EnsembleBuilder` for a full Ledoit-Wolf re-solve — new `weight_version`, all weights updated atomically. APR never holds feature weights. Recovery requires non-overlapping new evidence (≥2,000 new independent observations after decay detection); no fractional partial restore — the re-solve assigns the correct weight empirically.
- **Regime-shift guard:** if ≥60% of feature-regime cells decay simultaneously, the system classifies it as a market regime shift and holds weights — temporary regime unfavorability is not evidence of feature death.
- **All weight changes** produce a new `weight_version` in `ensemble_weights`. APR stores emission thresholds, Kelly params, governance gates — not feature weights. All APR writes logged to `config_history`.

---

## Build Order

**Prerequisite (hard gate):** ETF historical backfill (SPY, QQQ, IWM, TLT) through existing I1-I4 pipeline. IC Sharpe requires 20,000 independent observations per (feature, symbol, TF). Single ETF at 1m over 5 years = ~98K independent observations.

**Phase A — Feature Factory**
Archive I5-I7. Rewrite I1-I4 as pure function library producing `FeatureVector`. Cadence-matched computation (bar-level in-process, regime-level cached every 30 bars, calendar pre-computed daily). Write to `feature_vectors` table. Intelligence pipeline unchanged in DAG topology -- Feature Factory replaces the plugin registry as the per-bar computation unit.

**Phase B — IC Engine + Outcome Labels**
Outcome Labeler: LEAD()-based executable returns → `outcome_labels`. IC Engine: Spearman IC per feature × symbol × TF × regime × lookahead → `feature_ic_scores`. FDR correction, walk-forward, IC discovery report. Reveals which of 35 features actually predict returns.

**Phase C — Ensemble + Alpha Emission**
Ledoit-Wolf ensemble weights → `ensemble_weights`. Score all historical bars → `ensemble_alpha`. Empirical emission threshold from transaction cost model. Alpha Emitter → `alpha_events`. **Shadow mode only -- no live execution.**

**Phase D — Portfolio Construction + Trade Framing**
V1 quant frame opinion (entry/stop/target from sr_support_dist, sr_resist_dist, ATR). Kelly sizing. VaR constraints. Route to IBKR in shadow mode. Measure `counterfactual_pnl_r`. Validate framing quality before live.

**Phase E — Live + Alpha Decay Monitor**
Promote to live execution after shadow validation. Alpha Decay Monitor running daily. Rolling IC monitor auto-zeroes decaying features. System self-corrects without human intervention.

**Phase F+ — Additional Vectors**
Each new vector enters at weight=0. Earns weight through IC and `counterfactual_pnl_r`. Architecture is additive -- new vectors don't change Phases A-E.

---

## APR Parameter Registry

All numeric thresholds, weights, periods, and counts are APR-backed. Hard-coded magic numbers in `src/` are an architecture violation. New namespace: `alpha.*` (added to CLAUDE.md).

Every parameter follows the pattern: INSERT into `config_schema` + `config_state` in a migration, load via `ConfigService.get(key, default)` at init, no inline constants.

### `feature.*` namespace — Feature Factory computation parameters

| APR key | Default | Description | Provenance |
|---------|---------|-------------|------------|
| `feature.momentum.window_short` | 5 | Short momentum lookback (bars) | [conventional] |
| `feature.momentum.window_long` | 20 | Long momentum lookback (bars) | [conventional] |
| `feature.momentum.zscore_window` | 252 | Rolling window for z-scoring returns | [conventional] — approx 1 trading year |
| `feature.volume.zscore_window` | 20 | Rolling window for volume z-score | [conventional] |
| `feature.ofi.zscore_window` | 20 | Rolling window for OFI z-score | [conventional] |
| `feature.cvd.slope_bars` | 5 | CVD slope lookback (bars) | [conventional] |
| `feature.cmf.period` | 20 | Chaikin money flow period | [conventional] |
| `feature.vol.short_bars` | 5 | Short realized vol window | [conventional] |
| `feature.vol.long_bars` | 20 | Long realized vol window | [conventional] |
| `feature.hma.period` | 20 | HMA period for slope computation | [conventional] |
| `feature.adx.period` | 14 | ADX period | [conventional] |
| `feature.hurst.window` | 252 | Hurst exponent rolling window (bars) | [conventional] |
| `feature.garch.window` | 100 | GARCH estimation window (bars) | [initial_estimate] |
| `feature.vix.zscore_window` | 252 | VIX z-score rolling window | [conventional] |
| `feature.yield_curve.zscore_window` | 252 | Yield curve spread z-score window | [conventional] |
| `feature.regime.cache_refresh_bars` | 30 | Regime-level feature recompute cadence | [initial_estimate] — HMM doesn't change meaningfully bar-to-bar |

### `alpha.*` namespace — IC Engine, Ensemble, Emission, Portfolio

| APR key | Default | Description | Provenance |
|---------|---------|-------------|------------|
| `alpha.ic.min_observations` | 500 | Minimum independent observations for IC estimation | [rca_analysis] — IC CI too wide below this |
| `alpha.ic.bootstrap_resamples` | 2000 | Bootstrap resamples for CI | [conventional] |
| `alpha.ic.fdr_alpha` | 0.05 | BH-FDR correction q-value | [conventional] |
| `alpha.ic.walk_forward_folds` | 3 | Walk-forward validation fold count | [conventional] |
| `alpha.ic.sharpe_window_size` | 2000 | Observations per IC Sharpe rolling window | [rca_analysis] — see IC spec §X.1 |
| `alpha.ic.sharpe_min_windows` | 10 | Minimum IC windows for IC Sharpe computation | [conventional] |
| `alpha.ensemble.max_feature_weight` | 0.20 | Max weight cap per feature (post Ledoit-Wolf) | [initial_estimate] — prevents single-feature dominance |
| `alpha.ensemble.zscore_window_days` | 20 | Rolling window (days) for alpha_score z-scoring | [conventional] |
| `alpha.ensemble.min_effective_n` | 3.0 | Minimum effective-N to permit emission | [initial_estimate] |
| `alpha.decay.ci_lower_threshold` | 0.0 | Rolling IC CI lower bound triggering decay flag | [conventional] — zero = no longer statistically positive |
| `alpha.decay.materiality_threshold` | 0.005 | Min (weight × \|ic_ci_lower\|) to trigger EnsembleBuilder re-solve | [initial_estimate] — prevents re-solve on negligible weight features |
| `alpha.decay.regime_shift_fraction` | 0.60 | Fraction of cells decaying simultaneously → classified as regime shift, not feature decay | [initial_estimate] — hold weights during market-wide IC collapse |
| `alpha.decay.recovery_min_observations` | 2000 | New independent observations required before recovery eligible | [rca_analysis] — must be non-overlapping with decay detection window |
| `alpha.kelly.fraction` | 0.25 | Fractional Kelly multiplier (shared across all vectors) | [initial_estimate] — ML learning target |
| `alpha.portfolio.var_limit_pct` | 0.02 | Max daily VaR as fraction of equity | [user_preference] |
| `alpha.portfolio.max_position_correlation` | 0.70 | Max pairwise correlation between open positions | [initial_estimate] |

### Vector-specific `alpha.<vector>.*` — one sub-namespace per intelligence vector

Vector-specific parameters are namespaced by vector domain name (not number — stable as vectors are added):

| APR key | Default | Description | Provenance |
|---------|---------|-------------|------------|
| `alpha.quant.threshold.<symbol>.<tf>` | (derived) | V1 Quant emission threshold per symbol/TF | [initial_estimate] — recalibrated when ensemble IC changes >15% |
| `alpha.quant.frame.stop_atr_multiple` | 1.5 | V1 stop distance in ATR multiples | [initial_estimate] — ML learning target |
| `alpha.quant.frame.hold_max.<regime>.<tf>` | (per-regime) | V1 max hold bars (e.g. `alpha.quant.frame.hold_max.trending.5m` = 20) | [initial_estimate] — ML learning target |
| `alpha.micro.threshold.<symbol>.<tf>` | (derived) | V2 Microstructure emission threshold | — |
| `alpha.macro.threshold.<symbol>.<tf>` | (derived) | V3 Macro emission threshold | — |
| `alpha.calendar.threshold.<symbol>.<tf>` | (derived) | V4 Calendar emission threshold | — |
| `alpha.flow.threshold.<symbol>.<tf>` | (derived) | V5 Flow/Positioning threshold | — |
| `alpha.gamma.threshold.<symbol>.<tf>` | (derived) | V6 Gamma threshold | — |
| `alpha.qual.threshold.<symbol>.<tf>` | (derived) | V7 Qualitative threshold | — |
| `alpha.fund.threshold.<symbol>.<tf>` | (derived) | V8 Fundamental threshold | — |

Shared methodology parameters (`alpha.ic.*`, `alpha.ensemble.*`, `alpha.decay.*`, `alpha.portfolio.*`, `alpha.kelly.*`) apply to all vectors identically. The IC engine methodology does not vary by vector.

### Loading pattern in Feature Factory

```python
# Module-level cache (Ring 1 pattern from CLAUDE.md)
_config_service: Any | None = None

def set_config_service(cfg: Any) -> None:
    global _config_service
    _config_service = cfg

def _cfg(key: str, fallback: float) -> float:
    return _config_service.get_sync(key, fallback) if _config_service else fallback

# Usage inside compute functions:
window = int(_cfg("feature.momentum.window_short", 5))
```

Registered in `IntelligencePipeline._prewarm_threshold_config()` alongside existing APR pre-warming.

---

## Naming Derivations

Concept name (`snake_case`) drives all layer names per CLAUDE.md naming system.

| Concept | Class | Service unit | Table / topic | Ring |
|---------|-------|-------------|---------------|------|
| `feature_factory` | `FeatureFactory` | (in-process, no service) | `feature_vectors` table | Ring 1 `src/intelligence/` |
| `feature_vector` | `FeatureVector` | - | - | Ring 1 `src/intelligence/` |
| `feature_cache` | `FeatureCache` | - | - | Ring 1 `src/intelligence/` |
| `outcome_labeler` | `OutcomeLabeler` | `indicagent-outcome-labeler.service` | `outcome_labels` table | Ring 2 `services/` |
| `ic_engine` | `ICEngine` | `indicagent-ic-engine.service` (oneshot) | `feature_ic_scores` table | Ring 2 `services/` |
| `ensemble_builder` | `EnsembleBuilder` | `indicagent-ensemble-builder.service` (oneshot) | `ensemble_weights`, `ensemble_alpha` tables | Ring 2 `services/` |
| `alpha_emitter` | `AlphaEmitter` | `indicagent-alpha-emitter.service` (oneshot) | `alpha_events` table | Ring 2 `services/` |
| `alpha_decay_monitor` | `AlphaDecayMonitor` | `indicagent-alpha-decay-monitor.service` | `feature_ic_scores` (decay flags) → triggers `EnsembleBuilder` | Ring 2 `services/` |
| `portfolio_constructor` | `PortfolioConstructor` | `indicagent-portfolio-constructor.service` | - | Ring 2 `services/` |

**File locations:**
```
src/intelligence/feature_factory.py     — FeatureVector dataclass + compute_features()
src/intelligence/feature_cache.py       — FeatureCache (regime-level + calendar state)
services/outcome_labeler.py             — OutcomeLabeler (oneshot batch)
services/ic_engine.py                   — ICEngine (oneshot batch, weekly)
services/ensemble_builder.py            — EnsembleBuilder (oneshot batch, weekly)
services/alpha_emitter.py               — AlphaEmitter (oneshot batch, nightly)
services/alpha_decay_monitor.py         — AlphaDecayMonitor (daemon, daily)
services/portfolio_constructor.py       — PortfolioConstructor (daemon)
```

New services must be registered in `_DAG_ORDER`, `_LAG_THRESHOLDS`, `_AGENT_ID_TO_UNIT` in `services/service_auditor.py`.

---

## Observability Contract

Every v3.0 service inherits the existing OTel stack unchanged: `init_otel_providers(service_name)` at startup, `flush_and_shutdown_metrics()` at exit for oneshots, `observed_span()` for hot-path tracing, metrics emitted via the OTel SDK instruments in `src/observability/metrics.py`. No new collector infrastructure needed.

The contract below specifies what each AlphaEngine layer must instrument. All metric names follow the existing `component_noun_verb_total` / `component_noun_metric_unit` convention. Definitions are added to `metrics.py` in the same phase that implements the component -- not retroactively.

### Traceability Chain

A live position must be fully traceable backward through the system without querying multiple tables manually:

```
trade_executions
  └─ trade_frames           (frame_id FK)
       └─ alpha_events       (alpha_id FK) → top_features JSONB (feature attribution)
            └─ feature_ic_scores  (feature, symbol, tf, regime) → IC, CI, weight
                 └─ feature_vectors    (symbol, tf, bar_ts) → raw computed values
                      └─ market_data_ohlcv  (symbol, tf, bar_ts) → source bars
```

`top_features` JSONB in `alpha_events` is the primary audit artifact -- it records `{feature, score, ic_weight, ic_sign}` for the top 5 contributors to every emission. This is non-negotiable: an emission with no `top_features` is untraceable and must be treated as a data integrity failure.

### Infrastructure (all v3.0 services)

```python
# Every Ring 2 service -- startup
init_otel_providers(service_name="indicagent-<service-unit-suffix>")

# Every oneshot -- before process exit
flush_and_shutdown_metrics()

# Every Ring 2 service -- mandatory OTel health contract (inherited from BaseDaemon)
# agent_last_message_timestamp_seconds, agent_crash_total, agent_dlq_total,
# watchdog_notify_total, watchdog_notify_suppressed_total  (all labeled agent_id)
```

### Feature Factory (Ring 1, in-process)

Instrumented inside `IntelligencePipeline` at the call site for `compute_features()`.

**Spans:**
```python
async with observed_span("feature_factory.compute", symbol=symbol, tf=tf):
    fv = compute_features(bar, cache)
```

**Metrics (add to `metrics.py`):**

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `feature_factory_compute_ms` | Histogram | `symbol`, `tf` | Per-bar compute latency -- alert if p99 > 5ms |
| `feature_factory_nan_total` | Counter | `feature`, `symbol`, `tf` | NaN outputs per feature -- warmup gaps are expected; post-warmup NaN is a bug |
| `feature_factory_warmup_skip_total` | Counter | `symbol`, `tf` | Bars skipped due to insufficient history (< min lookback) |
| `feature_factory_regime_cache_refresh_total` | Counter | `symbol`, `tf` | Regime-level recompute events (every 30 bars per APR) |
| `feature_factory_bars_computed_total` | Counter | `symbol`, `tf` | Throughput counter -- north star for backfill progress |

**Distribution probes** (sampled every 500 bars, not every bar -- labels include `feature`):

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `feature_factory_feature_mean` | Gauge | `feature`, `symbol`, `tf` | Rolling mean of each feature output -- drift detection |
| `feature_factory_feature_std` | Gauge | `feature`, `symbol`, `tf` | Rolling std -- collapse signals degenerate feature |

### IC Engine (Ring 2, oneshot)

**Spans:**
```python
with observed_span("ic_engine.run", symbols=n_symbols, features=n_features, folds=n_folds):
    ...
with observed_span("ic_engine.feature_test", feature=feature_name, symbol=symbol, tf=tf, regime=regime):
    ...
```

**Metrics (add to `metrics.py`):**

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `ic_engine_features_tested_total` | Counter | `symbol`, `tf`, `regime` | Total (feature, lookahead) pairs tested per run |
| `ic_engine_features_passing_fdr_total` | Counter | `symbol`, `tf`, `regime` | Features surviving BH-FDR correction -- IC discovery rate |
| `ic_engine_ic_score` | Gauge | `feature`, `symbol`, `tf`, `regime`, `lookahead` | Current IC estimate per cell -- primary signal health metric |
| `ic_engine_ic_ci_lower` | Gauge | `feature`, `symbol`, `tf`, `regime`, `lookahead` | Bootstrap CI lower bound -- gate threshold is > 0.0 |
| `ic_engine_observations_n` | Gauge | `feature`, `symbol`, `tf`, `regime` | Independent observation count -- track approach to n=500 gate |
| `ic_engine_walk_forward_stability` | Gauge | `feature`, `symbol`, `tf` | IC Sharpe across walk-forward folds -- low value = regime-specific, not structural |
| `ic_engine_run_duration_seconds` | Histogram | _(none)_ | Full run duration -- weekly batch budget |

### Ensemble Builder (Ring 2, oneshot)

**Spans:**
```python
with observed_span("ensemble_builder.solve", weight_version=new_version, n_features=n):
    ...
```

**Metrics (add to `metrics.py`):**

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `ensemble_feature_weight` | Gauge | `feature`, `symbol`, `tf`, `weight_version` | Current weight per feature -- primary IC health dashboard metric |
| `ensemble_effective_n` | Gauge | `symbol`, `tf`, `weight_version` | Ledoit-Wolf effective predictor count -- should stay > `alpha.ensemble.min_effective_n` |
| `ensemble_shrinkage_intensity` | Gauge | `symbol`, `tf`, `weight_version` | Ledoit-Wolf shrinkage coefficient -- high value = correlated features dominating |
| `ensemble_weight_version` | Gauge | `symbol`, `tf` | Current weight version counter -- monotonically increasing; alerts on unexpected freeze |
| `ensemble_features_zero_weight_total` | Gauge | `symbol`, `tf`, `weight_version` | Features with weight = 0 (IC gate not yet passed) -- tracks shadow pipeline depth |
| `ensemble_solve_duration_seconds` | Histogram | _(none)_ | Ledoit-Wolf solve duration |
| `ensemble_resolve_trigger_total` | Counter | `trigger_reason` | What caused a re-solve: `decay_detected`, `scheduled_weekly`, `manual` |

### Alpha Emitter (Ring 2, oneshot)

**Spans:**
```python
with observed_span("alpha_emitter.score_bar", symbol=symbol, tf=tf):
    ...
with observed_span("alpha_emitter.emit", symbol=symbol, tf=tf, direction=direction):
    ...
```

**Metrics (add to `metrics.py`):**

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `alpha_emitter_bars_scored_total` | Counter | `symbol`, `tf` | Bars evaluated by ensemble (denominator for emission rate) |
| `alpha_emitter_emissions_total` | Counter | `symbol`, `tf`, `direction`, `regime` | Alpha events written -- primary emission rate KPI |
| `alpha_emitter_rejections_total` | Counter | `symbol`, `tf`, `rejection_reason` | Bars failing gate; `rejection_reason` in {`ci_lower_negative`, `effective_n_low`, `threshold_miss`} |
| `alpha_emitter_alpha_score` | Histogram | `symbol`, `tf`, `direction` | Distribution of alpha_score at emission -- monitors score drift |
| `alpha_emitter_threshold` | Gauge | `symbol`, `tf`, `regime` | Current emission threshold from APR -- rises/falls with transaction cost recalibration |
| `alpha_emitter_run_duration_seconds` | Histogram | _(none)_ | Nightly batch duration |

### Alpha Decay Monitor (Ring 2, daemon)

**Spans:**
```python
async with observed_span("alpha_decay.scan", cells_checked=n, cells_decaying=k):
    ...
async with observed_span("alpha_decay.regime_shift_check", decaying_fraction=f):
    ...
```

**Metrics (add to `metrics.py`):**

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `alpha_decay_cells_monitored` | Gauge | `symbol`, `tf` | Total (feature, regime) cells under monitoring |
| `alpha_decay_cells_flagged` | Gauge | `symbol`, `tf` | Cells currently flagged as decaying -- north star: stays near 0 in stable regimes |
| `alpha_decay_regime_shift_total` | Counter | `symbol`, `tf` | Events classified as regime shift (>60% cells decaying simultaneously) -- weights held |
| `alpha_decay_ensemble_rebuild_total` | Counter | `trigger` | EnsembleBuilder re-solves triggered by decay monitor |
| `alpha_decay_recovery_observations_n` | Gauge | `feature`, `symbol`, `tf`, `regime` | New observations accumulated post-decay -- gate is 2000 before recovery eligible |
| `alpha_decay_scan_duration_seconds` | Histogram | _(none)_ | Daily scan duration |

### Portfolio Constructor (Ring 2, daemon)

**Spans:**
```python
async with observed_span("portfolio.size", symbol=symbol, tf=tf, direction=direction):
    ...
```

**Metrics (add to `metrics.py`):**

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `portfolio_emissions_received_total` | Counter | `symbol`, `tf` | Alpha events received from alpha_emitter |
| `portfolio_positions_sized_total` | Counter | `symbol`, `tf`, `direction` | Positions that passed all portfolio constraints |
| `portfolio_correlation_blocked_total` | Counter | `symbol`, `tf` | Emissions blocked by max correlation constraint |
| `portfolio_var_ceiling_blocked_total` | Counter | _(none)_ | Emissions blocked by VaR ceiling |
| `portfolio_kelly_fraction_applied` | Histogram | `symbol`, `tf`, `regime` | Actual Kelly fraction used (may be reduced by VaR or correlation) |
| `portfolio_var_headroom` | Gauge | _(none)_ | Current VaR utilization as fraction of limit -- alert at > 0.80 |
| `portfolio_open_positions` | Gauge | _(none)_ | Current open position count |

### Data Quality (cross-cutting)

These are monitored by the existing `feature_validation_agent` and `bar_auditor`, extended for v3.0 tables.

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `feature_vectors_completeness` | Gauge | `feature`, `symbol`, `tf` | Fraction of expected bars with non-null value -- < 0.95 triggers alert |
| `feature_vectors_rows_total` | Gauge | `symbol`, `tf` | Total rows per (symbol, TF) -- monitors backfill progress |
| `alpha_events_rows_total` | Gauge | `symbol`, `tf` | Alpha events accumulated -- IC Sharpe requires 20K independent obs |
| `outcome_labels_coverage` | Gauge | `lookahead`, `symbol`, `tf` | Fraction of `feature_vectors` rows with labeled forward returns |

### Grafana Dashboard Requirements

Each new service gets a panel row in the existing Grafana instance. Required panels per service:

- **Feature Factory row:** bars/min per symbol, NaN rate heatmap (feature × symbol), compute p99 latency, warmup skip rate
- **IC Engine row:** IC score per feature (color by regime), features passing FDR gate, walk-forward stability distribution, observation count toward n=500 gate
- **Ensemble row:** feature weight heatmap (feature × symbol), effective_N trend, weight version monotonicity
- **Alpha Emitter row:** emission rate per symbol/TF, alpha_score distribution, rejection reason breakdown, threshold per regime
- **Alpha Decay row:** decaying cells gauge (should be near 0), regime-shift event markers, recovery observation count
- **Portfolio row:** VaR headroom gauge, Kelly fraction distribution, open positions, correlation blocks

---

## Resilience Contract

v3.0's service topology is fundamentally different from v2.x: most services are batch DB-to-DB oneshots, not Kafka-consuming daemons. The resilience problems are different and the patterns must match.

### Resilience Pattern by Service Type

| Service type | Primary failure modes | Pattern |
|---|---|---|
| In-process (Feature Factory) | Single feature throws, corrupts bar | Per-feature circuit breaker |
| Oneshot batch (IC Engine, Ensemble Builder, Alpha Emitter) | Crash mid-run, double-write on re-run | Idempotency + partial completion checkpoint |
| Daemon (Alpha Decay Monitor) | Stall, crash loop, EnsembleBuilder trigger failure | BaseDaemon watchdog + circuit breaker on trigger |
| Kafka-consuming daemon (Portfolio Constructor, if in scope) | Unprocessable message, poison pill | DLQ via existing `DLQPayload` / `BaseWriter` pattern |

**DLQ applies only to Kafka-consuming daemons.** It is not a pattern for batch DB jobs.

### Feature Factory - Per-Feature Circuit Breaker

One feature computation failure must never block the bar. A bug in `compute_hurst()` for one symbol must not propagate NaN across the other 34 features or block bar processing entirely.

**Pattern:** wrap each feature computation call in the existing `CircuitBreaker` (from `src/observability/circuit_breaker.py`). One breaker instance per `(feature_name, symbol)`. If the breaker opens, emit `NaN` for that feature on that symbol and continue.

```python
# One breaker per (feature_func, symbol) — instantiated in FeatureCache at startup
_breakers: dict[tuple[str, str], CircuitBreaker] = {}

def _compute_with_breaker(feature_name: str, symbol: str, func, *args) -> float:
    breaker = _breakers[(feature_name, symbol)]
    if not breaker.allow_request():
        return float("nan")  # open circuit: emit NaN, not crash
    try:
        result = func(*args)
        breaker.record_success()
        return result
    except Exception as error:
        breaker.record_failure()
        _log.warning("feature_factory.compute_failed", feature=feature_name, symbol=symbol, error=str(error))
        return float("nan")
```

**A bar with NaN features is still written to `feature_vectors`.** NaN is explicit signal that a value was unavailable -- it is not a silent zero. The IC Engine must handle NaN columns (exclude from IC measurement for that cell; do not impute). This preserves the invariant that every bar produces a row unconditionally.

**Breakers start in shadow mode** (`enabled=False`) on first deploy. Activate via `PLUGIN_CB_ENABLED=true` after confirming NaN propagation is handled correctly downstream.

### IC Engine - Idempotency + Partial Completion

The IC Engine processes up to `54 features × 58 symbols × 4 TFs × 4 regimes × 4 lookaheads = ~200K cells`. A crash at cell 80K must resume from 80K, not restart from zero.

**Idempotency:** all writes use `INSERT ... ON CONFLICT (feature, symbol, tf, regime, lookahead_bars, computed_at) DO NOTHING`. A re-run on a completed cell is a no-op.

**Partial completion:** the IC Engine tracks progress via `feature_ic_scores` itself -- on startup, it queries which `(feature, symbol, tf, regime, lookahead_bars)` cells already have a row with `computed_at >= run_start_ts` and skips them. No separate checkpoint table needed; the output table is the checkpoint.

**Atomicity per cell:** each `(feature, symbol, tf, regime, lookahead_bars)` row is a single `INSERT` -- the smallest meaningful unit. No transaction wrapping multiple cells; a partial write of a cell is worse than a missing one because it looks complete.

### Ensemble Builder - Atomic Weight Version Commit

A partial Ledoit-Wolf solve must never be observable. The system must not read a `weight_version` where some features have new weights and others have old weights.

**Pattern:** wrap the entire batch insert for a new `weight_version` in a single Postgres transaction. Either all 54 weight rows for the new version commit or none do. `weight_version` increments inside the transaction -- it is never visible until the commit completes.

```python
async with pool.acquire() as conn:
    async with conn.transaction():
        new_version = await conn.fetchval(
            "INSERT INTO ensemble_weights (weight_version, ...) VALUES (...) RETURNING weight_version"
        )
        await conn.executemany(
            "INSERT INTO ensemble_weights (weight_version, feature, symbol, tf, weight) VALUES ($1,$2,$3,$4,$5)",
            [(new_version, f, s, tf, w) for f, s, tf, w in weights]
        )
        # Transaction commits here -- new_version becomes visible atomically
```

**Idempotency:** if the process crashes after commit, a re-run finds `weight_version` already exists and skips. If it crashes before commit, the transaction rolled back and the re-run proceeds as if it never ran.

### Alpha Emitter - Idempotency via PK

`alpha_events` has PRIMARY KEY `(symbol, tf, bar_ts)`. Every `INSERT` uses `ON CONFLICT DO NOTHING`. A re-run of the nightly batch is fully safe -- already-emitted events are skipped silently.

**Partial completion:** same as IC Engine -- on startup, query the max `emitted_at` timestamp already in `alpha_events` for the current `weight_version` and skip bars already processed. The output table is the checkpoint.

**Data integrity invariant:** `top_features` must never be NULL on insert. An `alpha_events` row with `top_features IS NULL` is a data integrity failure -- it means the emission happened without a traceable feature attribution. Enforce as a `NOT NULL` constraint or a pre-insert assertion.

### Alpha Decay Monitor - Watchdog + Trigger Circuit Breaker

Inherits `BaseDaemon` -- gets the full OTel health contract (5 mandatory metrics labeled `agent_id`) and systemd `WatchdogNotify` for free.

**EnsembleBuilder trigger circuit breaker:** triggering an EnsembleBuilder re-solve is an expensive operation. If the re-solve consistently fails (DB unavailable, compute error), the decay monitor must not enter a trigger storm.

```python
_rebuild_breaker = CircuitBreaker(
    failure_threshold=3,
    timeout_sec=3600,  # back off for 1h after 3 consecutive failures
    name="alpha_decay.ensemble_rebuild",
    enabled=True,
)
```

If the breaker opens, the decay monitor logs the decaying cells, emits `alpha_decay_ensemble_rebuild_total{trigger="circuit_open"}`, and continues its scan cycle without triggering. The cells remain flagged. The next successful trigger clears them.

### Portfolio Constructor - DLQ (scope TBD for V1)

**Note:** whether `PortfolioConstructor` exists as a separate daemon for V1 Quant is an open scope question. The three-layer architecture (Prediction/Portfolio/Execution) includes it in Phase D, but the V1 trade framing may be simple enough to fold into the Alpha Emitter's emission path rather than a separate Kafka-consuming service. Resolve before Phase D planning.

**If implemented as a Kafka-consuming daemon:** inherits `BaseWriter` / `DLQPayload` pattern from v2.x unchanged. Unprocessable `alpha_events` messages route to `dlq.topic_alpha_events` using the existing `DLQPayload` schema. No new DLQ infrastructure needed.

### General Rules

1. **Silent wrong answers are worse than loud crashes.** A crashed oneshot triggers a systemd restart and an alert. A partial write that looks complete corrupts downstream IC measurement silently. Design for crash-loudness, not crash-prevention.
2. **The output table is the checkpoint for batch jobs.** Do not build separate checkpoint tables -- they create a consistency problem (checkpoint says done, output row missing). Query the output table at startup to determine what to skip.
3. **Circuit breakers on all external triggers.** Any call that reaches outside the process (DB write, EnsembleBuilder trigger, Kafka publish) gets a circuit breaker. Internal pure computation does not.
4. **NaN is explicit, zero is not.** A missing feature value is `NaN`, not `0.0`. Imputing zero changes the IC measurement. Let NaN propagate; handle it explicitly downstream.

---

## Key Invariants (non-negotiable)

1. **Every feature produces a score on every bar, unconditionally.** Selective scoring = selection bias = corrupted IC.
2. **IC measured on `feature_vectors` (all bars), never on `alpha_events` (emission bars only).** Selection bias at measurement corrupts every downstream weight.
3. **Feature universe locked before IC measurement begins.** Post-hoc feature addition is p-hacking.
4. **All IC measurement regime-stratified.** Pooled IC masks regime-specific predictability and produces wrong weights.
5. **No per-bar DB reads in the hot path.** APR is the only feedback channel from cold batch to live pipeline.
6. **Adding a feature = adding a field to `FeatureVector` = schema migration.** Not a registration. Intentional, visible, auditable.
7. **Transaction costs are first-class in emission threshold derivation.** `E[return] < estimated_cost` → no emission.
8. **Shadow before live, always.** Every new feature, vector, or framing parameter accumulates shadow observations before any weight is assigned.
