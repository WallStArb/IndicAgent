# Intelligence Plugins — I1-I7 Implementation Guide

**Version:** 1.1.0
**Last Updated:** 2026-06-14
**Status:** stale (v2.x, see banner)
**Milestone:** v2.8 — AI Platform + Evolvable Agents

---

> **Staleness note (2026-08-01):** This doc describes how to implement I1-I7 `PatternPlugin`
> plugins against the ARCHIVED v2.x `IntelligencePipeline` DAG/wave system. That pipeline has
> no live consumer as of 2026-07-02 per CLAUDE.md. See CLAUDE.md's Architecture section for
> the current v3.0 pipeline. Not yet rewritten for v3.0 -- tracked for a future doc pass, not
> fixed here.

## Purpose

HOW to implement I1-I7 plugins: plugin protocol, tier registration, DAG execution, wave system, and step-by-step guidance for adding a new plugin.

---

## Plugin Protocol

### Base Contract

All plugins extend `PatternPlugin` from `src/intelligence/plugins/base.py`:

```python
class PatternPlugin(ABC):
    name: str                           # Unique identifier, becomes plugin.name
    inputs: tuple[InputSpec, ...]       # Data dependencies (OHLCVBar, other tiers)
    outputs: frozenset[str]             # Field names this plugin produces
    capability_tags: frozenset[str]    # Classification (e.g., "trend", "momentum")

    def compute(self, bar: OHLCVBar, features: dict) -> dict | None:
        """Pure function. Same input = same output. Never raise."""
        ...
```

**Rules:**
- Use `frozenset[str]` for `outputs`/`capability_tags` — not `set` or `list`
- Use `tuple[InputSpec, ...]` for `inputs` — not `list`
- `compute()` must be pure — no side effects, no database calls
- Return `None` for "no signal" — never raise for normal conditions

### InputSpec Reference

`InputSpec` declares what data a plugin needs. The DAG engine uses these declarations to derive execution order automatically.

```python
class InputSpec:
    symbol: str | Pattern[str]      # ".*" for all symbols, "ES" for specific
    timeframe: str | list[str]      # "1m" or ["1m", "5m", "15m"]
    lookback: int                   # Bars of history needed
    required: bool = True           # Fail if missing?
```

| Plugin | `inputs` | Meaning |
|--------|----------|---------|
| RSI | `InputSpec(".*", "1m", 100)` | All symbols, 1m only, 100 bars |
| CTF (I6) | `InputSpec(".*", ["1m", "5m", "15m", "1h"], 1)` | Multi-TF read |
| Divergence | `InputSpec(".*", "1m", 50)` | Needs I1 features (50 bars) |

### Registration

Register in `src/intelligence/register_plugins.py`:

```python
def register_all_plugins() -> None:
    registry.register_indicator(my_plugin)  # I1 only
    registry.register_pattern(my_plugin)    # I2-I7

# Add to tier list
TIER_I1: list[str] = [
    ...existing_plugins,
    my_plugin.name,  # MUST be in the tier list
]
```

**`TIER_I*` lists are the single source of truth.** Services import these instead of maintaining their own string lists.

### Tier Assignment

| Tier | Plugin type | Register via | Add to list |
|------|-------------|--------------|-------------|
| I1 | Indicator | `registry.register_indicator` | `TIER_I1` |
| I2-I7 | Pattern | `registry.register_pattern` | `TIER_I2`..`TIER_I7` |

---

## Tier Lists (Canonical)

Verified from `src/intelligence/register_plugins.py`:

| Tier | Count | Key plugins |
|------|-------|-------------|
| **I1** | 28 | RSI, MACD, ATR, Bollinger, OFI, CVD, volume_zscore, etc. |
| **I2** | 10 | RSI events, stochastic events, MACD events, volume events, acceleration, exhaustion |
| **I3** | 8 | Swing detector, S/R, trend structure, market profile, session levels, Fibonacci, swing momentum |
| **I4** | 12 | GARCH volatility, Kalman trend, Hurst exponent, Shannon entropy, VIX regime, cross-asset |
| **I5** | 16 | RSI divergence, squeeze, chart patterns (H&S, double top/bottom, triangles) |
| **SMC** | 16 | BOS/CHoCH, FVG, order blocks, liquidity pools, HMM (4 TFs), AMD cycle |
| **I6** | 6 | Cross-timeframe confluence, 5 sub-score plugins |
| **I7** | 36 | Trend following, mean reversion, liquidity sweeps, VWAP deviation, etc. |

**Total: 132 plugins** + 2 aggregators (CISScorer, SignalAggregator).

---

## DAG Execution Model

The intelligence pipeline is a dependency-aware DAG — not a hardcoded sequence.

### Topological Order

At startup, the DAG engine derives execution order automatically:

```
Raw OHLCV
  └─► I1 (28 plugins — no dependencies, run in parallel)
        └─► I2 (depends on I1 outputs)
  └─► I3 (reads OHLCV directly)
        └─► I4 (reads I3 + I1 outputs)
  └─► I5 (reads I1 features)
  └─► SMC (reads I1-I4 + OHLCV)
        └─► I6 CTF (reads I1-I5 + SMC, cross-timeframe; 6 plugins)
              └─► I7 Setups (reads I2-I6, regime-gated; 36 plugins)
                    └─► I8 AI Narrative (reads I7 signals, Ollama local)
```

### Why This Matters

- **Adding a plugin** means declaring its inputs. Execution order is inferred — no ordering file to maintain.
- **Circular dependencies are impossible** — the DAG engine detects them at startup and hard-crashes.
- **Parallelization is safe** — I1 and I7 execute concurrently because the DAG proves they have no inter-dependencies.
- **No plugin knows about other plugins directly** — cross-plugin communication flows through tier output schemas only.

---

## Wave System (Sub-Tier Dependencies)

Within tiers, some plugins depend on others in the same tier. The wave system handles dependency-respecting parallel execution.

### Defined Waves

**I2 Waves:**
- `I2_WAVE_A`: Independent plugins (momentum_accel, RSI events, stochastic events, etc.)
- `I2_WAVE_B`: Dependent plugins (acceleration_regime, exhaustion_score — consume Wave A outputs)

**I4 Waves:**
- `I4_WAVE_A`: Independent plugins (GARCH, Kalman inputs, etc.)
- `I4_WAVE_B`: Dependent plugins (kalman_trend — consumes GARCH output)

**SMC Waves:**
- `SMC_WAVE_A`: Independent plugins (BOS/CHoCH, FVG, order blocks, liquidity pools, HMM, etc.)
- `SMC_WAVE_B`: Dependent plugins (supply_demand_zones, breaker_blocks, mitigation_blocks — consume Wave A outputs)

### Adding to Waves

When adding a plugin that depends on another in the same tier:

1. Add the dependency plugin to `*_WAVE_A` (independent)
2. Add your plugin to `*_WAVE_B` (dependent)
3. The DAG engine executes waves sequentially: A → B

---

## Schema Coverage Validation

At startup, `validate_schema_coverage()` verifies every `extra='forbid'` schema declares all plugin output fields.

**If a plugin outputs a field not in its tier schema:**
```python
RuntimeError: Schema coverage gaps detected — add missing fields to schemas.py:
  [I4] kalman_trend: kalman_upper not in I4Context
```

**This hard-crash is intentional** — it prevents the class of bug that silently breaks seed publish on service restart.

**I1 and I2 are skipped** (they use `extra='allow'`). Validation applies to I3, I4, I5, SMC, I6.

---

## I1 — Foundation Indicators

### Characteristics

- **Pure mathematical functions** — no state, no side effects
- **Output names include period suffixes** — `rsi_14`, `atr_14`, `macd_12_26_9`, etc.
- **`extra='allow'` on schema** — too many dynamic field names to declare

### Example I1 Plugin

```python
from src.intelligence.plugins.base import PatternPlugin
from src.intelligence.plugins.inputs import InputSpec
from src.core.schemas.bar_message import OHLCVBar

class MyIndicatorPlugin(PatternPlugin):
    name = "my_indicator"
    inputs = (InputSpec(OHLCVBar),)
    outputs = frozenset({"my_value_14", "my_signal"})
    capability_tags = frozenset({"indicator"})

    def compute(self, bar: OHLCVBar, features: dict) -> dict | None:
        # Pure function — calculate indicator value
        my_val = self._calculate(bar)
        return {"my_value_14": my_val, "my_signal": 1.0 if my_val > 0 else 0.0}
```

### Key I1 Plugins

| Plugin | Outputs | Purpose |
|--------|---------|---------|
| RSI | `rsi_14` | Relative strength index |
| MACD | `macd_12_26_9`, `macd_signal_12_26_9`, `macd_histogram_12_26_9` | Moving average convergence divergence |
| ATR | `atr_14` | Average true range |
| Bollinger | `bb_20_2_upper`, `bb_20_2_lower`, `bb_20_2_mid` | Bollinger bands |
| OFI | `ind_OFI` | Order flow imbalance |
| CVD | `ind_CVD` | Cumulative volume delta |
| volume_zscore | `volume_zscore` | Z-score normalized volume |

---

## I2 — Composite Events

### Characteristics

- **Reads I1 outputs** — turns continuous values into discrete events
- **Crossovers, threshold crossings, extremes** — events, not values
- **Bridge composites** — translate I1 outputs into directional signals

### Key I2 Plugins

| Plugin | Outputs | Purpose |
|--------|---------|---------|
| RSI events | `rsi_crossed_30_up`, `rsi_crossed_70_down`, `rsi_extreme_reversal` | RSI threshold crossings |
| Stochastic events | `stoch_cross_bullish`, `stoch_oversold_reversal` | Stochastic crossovers |
| MACD events | `macd_cross_bullish`, `macd_hist_positive`, `macd_negative_support_test` | MACD-based events |
| Volume events | `vol_spike`, `vol_drying`, `bb_upper_touch` | Volume-based events |
| Acceleration | `acceleration_regime` | RSI/MACD curvature (consumed by exhaustion) |
| Exhaustion | `cmp_ExhaustionScore` | Momentum exhaustion score |

### I2 Wave Dependency

`acceleration_regime` and `exhaustion_score` depend on `momentum_accel` (produces `rsi_curvature`, `macd_hist_slope`).

---

## I3 — Market Structure

### Characteristics

- **`extra='forbid'`** — all 77 fields must be declared in schema
- **Structural facts about price** — swings, S/R levels, trend structure
- **Market profile zones** — POC, VAH/VAL

### Key I3 Plugins

| Plugin | Outputs | Purpose |
|--------|---------|---------|
| Swing detector | `swing_high`, `swing_low`, `swing_pattern`, `swing_high_type`, `swing_low_type` | Swing detection |
| Support/Resistance | `nearest_resistance`, `nearest_support`, `resistance_strength`, `support_strength` | S/R level detection |
| Trend structure | `trend_direction`, `trend_strength`, `structure_integrity`, `price_position` | Trend analysis |
| Market profile | `poc_level`, `va_high`, `va_low`, `poc_dist_pct` | Volume profile |
| Session levels | `prior_session_high`, `overnight_high`, `weekly_pivot` | Session-based levels |
| Fibonacci | `fib_236`, `fib_382`, `fib_618`, `nearest_fib_level` | Fibonacci zones |
| Swing momentum | `swing_amplitude_ratio`, `swing_velocity_bars`, `struct_energy` | Swing velocity/energy |

---

## I4 — Regime Classification

### Characteristics

- **`extra='forbid'`** — all 93 fields must be declared
- **Statistical regime detection** — GARCH, Kalman, HMM, Hurst, entropy
- **Session context** — which market session is active
- **VIX/cross-asset context** — macro regime

### Key I4 Plugins

| Plugin | Outputs | Purpose |
|--------|---------|---------|
| Volatility regime | `vol_regime`, `vol_percentile`, `vol_expansion`, `bb_width_pct` | Volatility state |
| Trend regime | `trend_regime`, `trend_confidence`, `ma_alignment` | Trend classification |
| GARCH volatility | `garch_sigma`, `garch_vol_ratio`, `garch_vol_regime`, `garch_shock` | GARCH-based volatility |
| Kalman trend | `kalman_trend`, `kalman_slope`, `kalman_price_position`, `kalman_upper`/`kalman_lower` | Kalman filter trend |
| Hurst exponent | `hurst_exponent`, `hurst_trend_quality`, `hurst_mr_quality` | Long memory detection |
| Shannon entropy | `shannon_entropy`, `entropy_quality` | Predictability score |
| Session context | `session_asia`, `session_london`, `session_ny`, `in_london_killzone`, `minutes_to_ny_open` | Session detection |
| VIX regime | `vix_level`, `vix_z` | VIX-based regime |
| Cross-asset | `eq_spread_z`, `eq_pairs_confirming` | Cross-asset confirmation |

### I4 Wave Dependency

`kalman_trend` depends on `garch_volatility` (consumes `garch_sigma`).

---

## I5 — Pattern Detection

### Characteristics

- **`extra='forbid'`** — all 91 fields must be declared
- **Discrete pattern events** — divergence, squeeze, chart patterns
- **Confluence scores** — multiple indicators agreeing

### Key I5 Plugins

| Plugin | Outputs | Purpose |
|--------|---------|---------|
| RSI divergence | `rsi_div_bullish`, `rsi_div_bearish`, `rsi_div_strength` | RSI-price divergence |
| Bollinger squeeze | `squeeze_active`, `squeeze_duration`, `squeeze_fired` | Volatility squeeze |
| Volume divergence | `vol_div_bullish`, `vol_div_bearish`, `vol_div_strength` | Volume-price divergence |
| MACD divergence | `macd_div_bullish`, `macd_div_bearish`, `macd_div_strength` | MACD-price divergence |
| CMF divergence | `cmf_div_bullish`, `cmf_div_bearish`, `cmf_div_strength` | CMF-price divergence |
| Double top/bottom | `dt_db_pattern`, `dt_db_neckline`, `dt_db_target`, `dt_db_confidence` | Double top/bottom |
| Head & shoulders | `hs_pattern`, `hs_neckline`, `hs_target`, `hs_confidence` | H&S pattern |
| Triangle/wedge | `tri_pattern`, `tri_upper_slope`, `tri_lower_slope`, `tri_breakout_bias` | Triangle patterns |
| Candlestick patterns | `engulfing_bull`, `pin_bar_bull`, `hammer_detected`, `inside_bar`, `doji_detected`, etc. | 31 candlestick patterns |
| Flag/pennant | `flag_pattern`, `pennant_pattern`, `flag_breakout_target` | Flag/pennant patterns |
| Cup & handle | `cup_handle_pattern`, `cup_depth_pct`, `cup_handle_target` | Cup & handle |
| Measured move | `abcd_pattern_active`, `abcd_direction`, `abcd_d_target` | ABCD measured move |

---

## SMC — Smart Money Concepts

### Characteristics

- **`extra='forbid'`** — all 89 fields must be declared
- **Institutional order flow analysis** — BOS/CHoCH, FVG, order blocks, liquidity
- **4 HMM timeframe instances** — 1m, 5m, 15m, 1h (all in TIER_SMC)

### Key SMC Plugins

| Plugin | Outputs | Purpose |
|--------|---------|---------|
| BOS/CHoCH | `bos_detected`, `bos_direction`, `bos_level`, `choch_detected`, `choch_direction`, `smc_trend_direction` | Break of structure / change of character |
| FVG | `fvg_type`, `fvg_top`, `fvg_bottom`, `fvg_midpoint`, `fvg_size_pct`, `fvg_open_count` | Fair value gaps |
| Order blocks | `ob_type`, `ob_top`, `ob_bottom`, `ob_strength`, `ob_mitigated`, `ob_distance_pct` | Order block zones |
| Liquidity sweeps | `sweep_detected`, `sweep_type`, `sweep_level`, `sweep_depth_pct`, `sweep_reclaimed` | Liquidity sweep detection |
| BOCPD | `cp_probability`, `cp_raw_probability`, `cp_run_length`, `cp_confirmation`, `cp_detected` | Bayesian changepoint detection |
| HMM regime | `hmm_regime`, `hmm_regime_prob`, `hmm_prob_ranging`, `hmm_prob_trending_up`, `hmm_prob_trending_down` | Hidden Markov model (4 TF instances) |
| Liquidity pools | `bsl_level`, `bsl_significance`, `ssl_level`, `ssl_significance`, `price_in_premium` | Buy/sell side liquidity |
| Supply/demand zones | `nearest_demand_high`, `nearest_demand_low`, `demand_strength`, `in_demand_zone`, `nearest_supply_high`, `nearest_supply_low`, `supply_strength`, `in_supply_zone` | Supply/demand zones |
| ICT killzones | `in_asia_killzone`, `in_london_killzone`, `in_ny_am_killzone`, `in_ny_pm_killzone`, `killzone_name`, `minutes_in_killzone` | ICT killzone detection |
| AMD cycle | `amd_phase`, `amd_manipulation_detected`, `amd_distribution_direction` | Accumulation/Manipulation/Distribution |
| Breaker blocks | `breaker_block_active`, `breaker_block_type`, `breaker_block_top`, `breaker_block_bottom` | Failed order blocks |
| Mitigation blocks | `ob_mitigation_status`, `ob_mitigation_pct` | Order block mitigation |
| Premium/discount | `equilibrium_level`, `premium_discount_pct` | Price position vs range |

### SMC Wave Dependency

`supply_demand_zones`, `breaker_blocks`, `mitigation_blocks` depend on `order_blocks` + `fvg` + `liquidity_pools`.

---

## I6 — Cross-Timeframe Confluence

### Characteristics

- **`extra='forbid'`** — 30+ fields must be declared
- **Synthesizes across all timeframes** — 1m, 5m, 15m, 1h, 4h, 1d
- **6 plugins** — main confluence + 5 sub-score plugins

### I6 Plugins

| Plugin | Outputs | Purpose |
|--------|---------|---------|
| Cross-timeframe | `ctf_score`, `ctf_trend_alignment`, `ctf_regime_agreement`, `ctf_timeframes_aligned` | Overall CTF score |
| Momentum divergence | `ctf_momentum_divergence`, `ctf_momentum_regime` | HTF-LTF momentum divergence |
| SR confluence | `ctf_sr_confluence`, `ctf_sr_regime` | HTF-LTF S/R alignment |
| HMM regime | `ctf_hmm_regime_agreement`, `ctf_hmm_regime_label` | HMM regime agreement across TFs |
| Squeeze/expansion | `ctf_volatility_divergence`, `ctf_volatility_regime` | Volatility divergence across TFs |
| Orderflow alignment | `ctf_orderflow_alignment`, `ctf_orderflow_regime` | OFI/CVD alignment across TFs |

### Per-Timeframe Alignment

I6 outputs per-TF FVG and OB alignment scores (flat fields, not dict):

```
i6_fvg_tf_1m, i6_fvg_tf_5m, i6_fvg_tf_15m, i6_fvg_tf_1h, i6_fvg_tf_4h, i6_fvg_tf_1d
i6_ob_tf_1m, i6_ob_tf_5m, i6_ob_tf_15m, i6_ob_tf_1h, i6_ob_tf_4h, i6_ob_tf_1d
```

This enables ML feature extraction with per-TF coefficients.

---

## I7 — Trading Signal Generation

### Characteristics

- **36 setup plugins + 2 aggregators** — CISScorer + SignalAggregator
- **Must declare `regime_type`** — `"trend"` | `"mean_reversion"` | `"any"`
- **Consumes relevant I6 sub-scores** — every I7 must consume `ctf_*` fields
- **Outputs trading signals** — entry zone, stop-loss, take-profit, confidence

### I7 Contract

Every I7 plugin:

1. Declares `regime_type` (class attribute)
2. Uses shared utilities from `src/intelligence/trading/`
3. Routes confidence through `compose_confidence()` (clamps to [0.10, 0.95], rounds to 4dp)
4. Uses `make_signal()` or `make_signal_from_frame()` to construct signal dict
5. Returns `None` for "no signal"

### I7 Shared Utilities

All live in `src/intelligence/trading/`:

| File | Purpose |
|------|---------|
| `plugin_utils.py` | `no_signal()`, `extract_ohlcv()`, `signal_type_for_direction()` |
| `atr_utils.py` | `get_atr(features)` — null-safe ATR accessor |
| `state_utils.py` | `track_consecutive_state()`, `reset_consecutive_state()` |
| `confidence_utils.py` | **ALL I7 confidence must route through `compose_confidence()`** |
| `microstructure_utils.py` | `detect_spike_signal()` — shared OFI/CVD spike detection |
| `volume_profile_utils.py` | `check_reversal_gate()`, POC/HVN reversal detection |
| `exhaustion_utils.py` | `apply_exhaustion_boost()`, `apply_exhaustion_guard()` |
| `signal_schema.py` | `SIGNAL_SCHEMA_VERSION`, `make_signal()`, `validate_signal()` |

### I7 Signal Output — factor_scores and context_features

Every I7 plugin emits two additional dicts alongside `raw_confidence`. These are required fields on the signal payload as of Phase 123.

**`factor_scores`** — the per-plugin intrinsic factor breakdown, collected before the weighted composite:

```python
# Collect before the composite line — keys are plugin-specific
factor_scores = {
    "ofi_divergence": round(ofi_divergence_score, 4),
    "cvd_divergence": round(cvd_divergence_score, 4),
    "confirmation":   round(confirmation_score, 4),
    "volume":         round(volume_score, 4),
}
raw = 0.35 * ofi_divergence_score + 0.30 * cvd_divergence_score \
    + 0.20 * confirmation_score + 0.15 * volume_score
confidence = compose_confidence(raw)
# Pass factor_scores=factor_scores to emit_signal
```

Values are pre-composite [0, 1] scores — not weights. This dict serves two purposes: immediate debuggability (confidence can be decomposed without re-running the plugin) and ML weight optimization (once `counterfactual_pnl_r` accumulates on `trade_frames`, the ML loop regresses each factor score against outcome to discover optimal composite weights, replacing the hand-coded constants in APR `weights.*`).

`factor_scores` defaults to `{}` (empty dict) — never `None`. An empty dict means the plugin has not been updated yet; `NULL` in the DB means the field was not written at all. The distinction matters for coverage auditing.

**`context_features`** — the full output of `capture_signal_features()`, a 30+ key dict of market context at signal fire time: CTF sub-scores, HMM regime state, volatility, session, zone proximity. This is the SignalRanker feature matrix — the ML model trains on `context_features` to predict `counterfactual_pnl_r`.

```python
# Every I7 compute_full() that calls capture_signal_features() must capture the return value:
signal["context_features"] = capture_signal_features(signal, features)
```

Before Phase 123, `capture_signal_features()` wrote into `sig["_shadow"]` and never reached the Kafka payload — `context_features` was always `NULL` in the DB. As of Phase 123 the return value is written to `sig["context_features"]` directly. Any replay window before Phase 123 will have `context_features = NULL`.

`context_features` defaults to `{}` — same convention as `factor_scores`.

The key distinction between the two: `factor_scores` is intrinsic (what the plugin computed internally — WHY the pattern fired). `context_features` is extrinsic (the regime and market context at fire time — WHAT conditions existed when it fired). They answer different questions and feed different ML models.

---

### I7 Regime Gate

The aggregator suppresses signals based on `regime_type`:

- **Trend plugins** (`regime_type="trend"`) suppressed in ranging regime (`hmm_regime=0`)
- **Mean-reversion plugins** (`regime_type="mean_reversion"`) suppressed in trending regime (`hmm_regime=1/2`)
- **Any plugins** (`regime_type="any"`) never suppressed

### Key I7 Plugins

| Plugin | Type | Purpose |
|--------|------|---------|
| Trend following | trend | Momentum-based trend continuation |
| Mean reversion | mean_reversion | Counter-trend reversals |
| Liquidity sweep reclaim | trend | Sweep-based entries |
| VWAP deviation | mean_reversion | VWAP pullback entries |
| Squeeze expansion | trend | Volatility breakout entries |
| Momentum breakout | trend | Momentum-driven entries |
| Supply/demand setup | any | Zone-based entries |
| CHoCH reversal | trend | Structure change entries |
| FVG fill | trend | Gap-based entries |
| ORB15/ORB30 | trend | Opening range breakout |
| VCP | trend | Volatility contraction pattern |

---

## How to Add a Plugin

### Step 1: Create the Plugin

```python
# src/intelligence/features/i1_indicators/my_indicator.py
from src.intelligence.plugins.base import PatternPlugin
from src.intelligence.plugins.inputs import InputSpec
from src.core.schemas.bar_message import OHLCVBar

class MyIndicatorPlugin(PatternPlugin):
    name = "my_indicator"
    inputs = (InputSpec(OHLCVBar),)
    outputs = frozenset({"my_value_14"})
    capability_tags = frozenset({"indicator"})

    def compute(self, bar: OHLCVBar, features: dict) -> dict | None:
        # Pure function calculation
        return {"my_value_14": self._calculate(bar)}
```

### Step 2: Register in Tier

```python
# src/intelligence/register_plugins.py
from .features.i1_indicators.my_indicator import plugin as my_indicator_plugin

def register_all_plugins() -> None:
    registry.register_indicator(my_indicator_plugin)

# Add to tier list
TIER_I1: list[str] = [
    ...existing,
    my_indicator_plugin.name,
]
```

### Step 3: Add Unit Test

```python
# tests/unit/intelligence/test_my_indicator.py
def test_my_indicator_compute():
    plugin = MyIndicatorPlugin()
    bar = OHLCVBar(o=100, h=101, l=99, c=100.5, v=1000)
    result = plugin.compute(bar, {})
    assert result is not None
    assert "my_value_14" in result
```

### Step 4: Restart and Verify

```bash
sudo systemctl restart indicagent-intelligence-pipeline
docker exec redpanda rpk topic consume intelligence --from-end
```

---

## Reliability & Error Handling

### Plugin Failure Isolation

Each plugin runs inside try/except in the pipeline executor. A plugin that raises an exception is skipped for that bar — the pipeline continues with other plugins. Error is logged with plugin name and bar context.

**Contract:** A plugin must never raise on bad input data. Validate inputs and return `None` outputs if data is insufficient (e.g., warmup not complete, NaN inputs).

### Plugin Validation at Startup

`PluginValidator` (`src/core/plugin_validator.py`) checks all registered plugins at pipeline startup. Hard-crash failures prevent bad data from silently propagating.

| Check | Purpose | Failure Mode |
|-------|---------|--------------|
| Tier list registration | All `TIER_*` plugins in registry | Hard crash |
| Required attributes | `name`, `outputs`, `inputs` present | Hard crash |
| Schema coverage | Outputs covered by `IntelligenceEvent` | Hard crash |
| Orphaned plugins | Imported modules with missing `.py` files | Warning |
| TREND_SETUPS sync | Trend setups match `regime_type="trend"` | Warning |

### Error State Persistence

Plugin state is checkpointed to disk (`cache/plugin_states.json`) every N bars. On restart, state is restored so warmup periods are not replayed from scratch. If a checkpoint is corrupt or missing, the plugin reinitializes from scratch (warmup period replays).

---

## See Also

- **Foundation:** `intelligence-foundation.md` — I1-I8 definitions, data flow
- **AI Agents:** `intelligence-ai.md` — Swarm agents, LLM chain
- **Operations:** `intelligence-operations.md` — Services, monitoring
- **Code:** `src/intelligence/CLAUDE.md` — Developer reference
- **Registry:** `src/intelligence/register_plugins.py` — Tier lists
- **Schemas:** `src/intelligence/schemas.py` — IntelligenceEvent, tier schemas
