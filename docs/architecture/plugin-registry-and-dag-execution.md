# Intelligence Plugin Registry & DAG Execution Framework

**Version:** 6.1.0
**Last Updated:** 2026-03-15
**Status:** I1-I8 Complete — 98 Plugins + 2 Aggregation Components Operational

## Executive Summary

IndicAgent's Intelligence Plugin Registry and DAG Execution Framework provides the foundation for market intelligence processing. The framework uses a simple, protocol-based plugin architecture with dependency-aware DAG execution, supporting the I1-I8 intelligence tiers.

**Core Capability:** 98 plugins + 2 aggregation components across I1-I8 tiers, 1754 passing tests, all tiers operational.

---

## Framework Objectives

### Intelligence Platform Goals
- **Extensible Intelligence:** Protocol-based plugin architecture for unlimited intelligence capabilities
- **Real-Time Processing:** Sub-second intelligence generation via incremental `compute_next()`
- **Progressive Intelligence:** Support for I1-I8 intelligence tier progression
- **Observability:** Prometheus metrics and circuit breaker monitoring

### Non-Goals
- Trading strategy implementation (intelligence analysis only)
- Order execution or broker integration (external system responsibility)
- UI/dashboard concerns (intelligence distribution only)

---

## Intelligence Data Contracts

### Core Event Types
The framework processes intelligence through data contracts aligned with the I1-I8 tiers:

**Foundation Data Types:**
- **`bar.v1`** - OHLCV market data (symbol, timeframe, timestamp, open, high, low, close, volume)
- **`features.v1`** - I1 Raw Features (RSI, MACD, SMA, EMA, ADX, ATR, etc.)
- **`composite.v1`** - I2 Composite Intelligence (crossovers, distances)
- **`pattern.v1`** - I3-I5 Pattern/Structure/Context Intelligence
- **`regime.v1`** - I4 Market Context (trend/volatility regimes)
- **`insight.v1`** - I8 AI Intelligence (`narratives:SYMBOL:TF`, `narratives:group:GROUP_NAME`)

### Data Format Standards
- **Stream Format:** String-encoded key-value pairs in Redis Streams
- **Storage Format:** JSONB for flexible `features` and `intelligence_data` columns
- **Field Naming:** Flat, snake_case keys (e.g., `rsi_14`, `adx_14`, `bb_20_2_mid`)
- **Timestamps:** UTC ISO-8601 format
- **Schema Versioning:** Explicit `schema_version` field in events

### Intelligence Event Example
```python
# Example I5 Pattern Intelligence output from RSI Divergence plugin
pattern_output = {
    "rsi_divergence_type": "bullish",
    "rsi_divergence_strength": 0.76,
    "rsi_divergence_price_delta": -12.5,
    "rsi_divergence_rsi_delta": 8.3,
}
```

**Reference:** [Stream Schemas](stream-schemas.md) - Complete data format specifications

---

## Plugin Architecture (Implemented)

### Plugin Protocol

All plugins implement one of two identical protocols defined in `src/intelligence/plugins.py`:

```python
from dataclasses import dataclass
from re import Pattern as RePattern
from typing import Any, ClassVar, Protocol

@dataclass
class InputSpec:
    symbol: str | RePattern[str]
    timeframe: str | list[str]
    lookback: int
    required: bool = True

class IndicatorPlugin(Protocol):
    name: ClassVar[str]
    outputs: ClassVar[set[str]]
    min_lookback: ClassVar[int]
    supports_incremental: ClassVar[bool]
    capability_tags: ClassVar[set[str]]
    inputs: ClassVar[list[InputSpec]]

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]: ...
    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]: ...

class PatternPlugin(Protocol):
    # Identical interface to IndicatorPlugin
    ...
```

**Key Design Decisions:**
- **Protocol, not ABC:** Structural subtyping — any `@dataclass` with the right shape satisfies the protocol. No inheritance required.
- **Two methods only:** `compute_full()` for batch and `compute_next()` for incremental. No `validate_inputs()` or other ceremony.
- **`frames["main"]`:** Convention — the primary OHLCV DataFrame is always at key `"main"`.

### Plugin Implementation Pattern

Every plugin follows this exact structure (see any file in `src/intelligence/indicators/`):

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
import pandas as pd
from ..plugins import InputSpec

@dataclass
class RSIPlugin:
    name: str = "RSI"
    outputs: set[str] = frozenset({"rsi_14"})
    min_lookback: int = 20
    supports_incremental: bool = True
    capability_tags: set[str] = frozenset({"momentum"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=100),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}
        # ... full batch computation ...
        self._seed_state(frames)  # Always seed state for incremental
        return {"rsi_14": value}

    def _seed_state(self, frames: dict[str, pd.DataFrame]) -> None:
        # Extract EMA/rolling state for incremental updates
        ...

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        if not self._state:
            return self.compute_full(windows)  # Fallback
        # ... single-bar incremental update using self._state ...
        return {"rsi_14": value}

plugin = RSIPlugin()  # Module-level singleton
```

**Conventions:**
- `compute_full()` always calls `_seed_state()` to prepare for incremental updates
- `compute_next()` falls back to `compute_full()` when state is empty
- Output keys use format `indicator_param` (e.g., `rsi_14`, `adx_14`, `kc_upper_20`)
- Module ends with `plugin = PluginClass()` singleton
- Empty/insufficient data returns `{}`

### Plugin Registry

```python
# src/intelligence/plugins.py
class PluginRegistry:
    def __init__(self) -> None:
        self.indicators: dict[str, IndicatorPlugin] = {}
        self.patterns: dict[str, PatternPlugin] = {}

    def register_indicator(self, plugin: IndicatorPlugin) -> None:
        self.indicators[plugin.name] = plugin

    def register_pattern(self, plugin: PatternPlugin) -> None:
        self.patterns[plugin.name] = plugin

    def get_indicator(self, name: str) -> IndicatorPlugin: ...
    def get_pattern(self, name: str) -> PatternPlugin: ...
    def list_indicators(self) -> list[str]: ...
    def list_patterns(self) -> list[str]: ...

registry = PluginRegistry()  # Global singleton
```

**Registration:** All plugins are registered explicitly in `src/intelligence/register_plugins.py`:

```python
from .indicators.rsi import plugin as rsi_plugin
from .indicators.adx import plugin as adx_plugin
# ... all imports ...

def register_all_plugins() -> None:
    registry.register_indicator(rsi_plugin)
    registry.register_indicator(adx_plugin)
    # ... all plugins ...
```

No auto-discovery or hot-reload — registration is explicit Python code.

---

## Registered Plugins (98 Total + 2 Aggregation Components)

### I1 Indicator Plugins (25) — All support incremental `compute_next()`

| Plugin | Category | Key Outputs |
|--------|----------|-------------|
| RSI | Momentum | `rsi_14` |
| MA (SMA/EMA) | Trend | `sma_20`, `sma_50`, `sma_100`, `sma_200`, `ema_8`, `ema_9`, `ema_13`, `ema_21`, `ema_55` |
| MACompare | Trend | `ma_cross_20_50`, `ma_distance_20`, `ma_distance_50` |
| MACD | Trend | `macd_12_26_9`, `macd_signal_12_26_9`, `macd_histogram_12_26_9` |
| ATR | Volatility | `atr_14` |
| Bollinger Bands | Volatility | `bb_20_2_upper`, `bb_20_2_mid`, `bb_20_2_lower` |
| Stochastic | Momentum | `stoch_k_14`, `stoch_d_14` |
| CCI | Momentum | `cci_20` |
| Williams %R | Momentum | `willr_14` |
| MFI | Volume | `mfi_14` |
| OBV | Volume | `obv_value`, `obv_slope` |
| VWAP | Volume | `vwap_value` |
| Supertrend | Trend | `supertrend_direction`, `supertrend_trend` |
| ADX/DMI | Trend | `adx_14`, `plus_di_14`, `minus_di_14` |
| Keltner Channels | Volatility | `kc_upper_20`, `kc_mid_20`, `kc_lower_20` |
| Donchian Channels | Volatility | `donchian_upper_20`, `donchian_mid_20`, `donchian_lower_20` |
| ROC/PPO | Momentum | `roc_14`, `ppo_12_26`, `ppo_signal_12_26` |
| Aroon | Trend | `aroon_up`, `aroon_down`, `aroon_os` |
| Chandelier Exit | Trend | `chandelier_exit_long`, `chandelier_exit_short` |
| CMF | Volume | `cmf_value` |
| Historical Volatility | Volatility | `hist_vol_mean`, `hist_vol_upper`, `hist_vol_lower` |
| PSAR | Trend | `psar` |
| StochRSI | Momentum | `stochrsi_k`, `stochrsi_d` |
| AC Oscillator | Momentum | `ac_osc` |
| HMA | Trend | `hma_value` |

### I2 Second-Derivative / Event Plugins (11) — detect state changes in I1 outputs

| Plugin | Outputs |
|--------|---------|
| MACD Events | `macd_cross_up`, `macd_cross_dn`, `macd_hist_flip` |
| RSI Events | `rsi_ob`, `rsi_os`, `rsi_cross_mid` |
| Stoch Events | `stoch_cross_up`, `stoch_cross_dn`, `stoch_ob`, `stoch_os` |
| ADX Events | `adx_rising`, `adx_falling`, `adx_strong_trend` |
| Volume Events | `vol_spike`, `vol_dry`, `vol_expanding` |
| MomentumAccel | `mom_accel`, `mom_decel` |
| DonchianPos | `price_near_upper`, `price_near_lower`, `donchian_position` |
| OBV Momentum | `obv_momentum`, `obv_trend_align` |
| DerivOsc (AO) | `ao_value`, `ao_cross_zero` |
| ExhaustionScore | `exhaustion_score`, `exhaustion_signal` |
| AccelerationRegime | `accel_regime`, `accel_score`, `accel_agreement` |

### I3 Structure Plugins (8) — `supports_incremental = False`

| Plugin | Outputs |
|--------|---------|
| Swing Detector | Swing highs/lows, HH/HL/LH/LL classification |
| Support/Resistance | Pivot clustering, strength scoring, nearest S/R levels |
| Trend Structure | Swing sequence scoring, structural integrity, price position |
| Market Profile | Value area, POC, TPO distribution |
| Session Levels | Prior day H/L/C, overnight range |
| Anchored VWAP | AVWAP from session open, prior day close |
| Fibonacci Zones | Auto-fib from swing H/L, key retracement levels |
| Swing Momentum | Momentum at swing highs/lows for divergence context |

### I4 Context Plugins (9) — `supports_incremental = False`

| Plugin | Outputs |
|--------|---------|
| Volatility Regime | ATR percentile, BB width, expansion/contraction |
| Trend Regime | SMA-20/50 alignment, 5-state classification |
| Momentum Context | Multi-oscillator direction scoring (RSI/MACD/Stoch/CCI) |
| GARCH Volatility | `garch_vol_regime`, `garch_sigma`, conditional vol forecast |
| Hurst Exponent | `hurst_exponent`, `hurst_trend_quality`, `hurst_mr_quality` |
| Shannon Entropy | `shannon_entropy`, `entropy_quality` |
| Kalman Trend | `kalman_price_position`, `kalman_trend_slope`, 7 outputs |
| Session Context | Active session (London/NY/Asia/overlap), killzone timing |
| MTF Volatility | Multi-timeframe volatility alignment score |

### I5 Pattern Plugins (14) — `supports_incremental = False`

| Plugin | Category | Outputs |
|--------|----------|---------|
| RSI Divergence | Oscillator | Bullish/bearish divergence type and strength |
| Bollinger Squeeze | Momentum | TTM-style BB-inside-KC squeeze detection |
| Volume Divergence | Volume | OBV slope vs price slope via linear regression |
| Confluence | Oscillator | RSI/MACD/Stoch/CCI scoring from -1 to +1 |
| TrendConfluence | Trend | 6-signal trend aggregation score |
| Double Top/Bottom | Chart | Double top/bottom detection |
| Head & Shoulders | Chart | H&S with sloped neckline |
| Triangle/Wedge | Chart | Triangle/wedge convergence ratio |
| Candlestick | Candlestick | Hammer, engulfing, doji, pin bar patterns |
| Flag/Pennant | Continuation | Flag and pennant pattern detection |
| Cup & Handle | Continuation | Cup & handle pattern |
| Measured Move | Projection | AB=CD measured move projection |
| Volume Profile | Volume | Volume at price, high-volume nodes |
| Key Level Reaction | Price Action | Reaction strength at key levels |

### I6 SMC / Smart Money Plugins (13) — `supports_incremental = False`

| Plugin | Outputs |
|--------|---------|
| BOS/CHoCH | Break of structure, change of character |
| FVG | Fair value gaps (bullish/bearish, size, fill%) |
| Order Blocks | OB zones, strength, touch count |
| Liquidity Sweeps | Sweep events, reclaim signals |
| BOCPD | Changepoint probability, hazard function |
| HMM Regime | 3-state HMM (ranging/trend↑/trend↓) |
| Liquidity Pools | BSL/SSL pool levels and proximity |
| Supply/Demand Zones | S/D zones with strength scoring |
| ICT Killzones | London/NY/Asia killzone timing and bias |
| AMD Cycle | Accumulation/Manipulation/Distribution cycle detection |
| Breaker Blocks | Failed order blocks converted to breakers |
| Mitigation Blocks | Unmitigated order block tracking |
| Premium/Discount | Price position relative to range midpoint |

### I6 Cross-Timeframe Confluence (1)

Single CTF plugin scoring trend/structure/regime/pattern alignment across 1m/5m/15m/1h timeframes.

### I7 Trading Setup Plugins (17) + 2 Aggregation Components

| Plugin | Type |
|--------|------|
| TrendFollowing | Setup |
| MeanReversion | Setup |
| LiquiditySweepReclaim | Setup |
| MTFAlignment | Setup |
| SqueezeExpansion | Setup |
| VWAPDeviation | Setup |
| MomentumBreakout | Setup |
| LiquidityHunt | Setup |
| SupplyDemandSetup | Setup |
| CHoCHReversal | Setup (CIS) |
| FVGFill | Setup (CIS) |
| PatternCompletion | Setup (CIS) |
| DivergenceStack | Setup (CIS) |
| RegimeTransition | Setup (CIS) |
| GapAnalysis | Setup |
| CandlestickPatternSetup | Setup |
| SessionExtremes | Setup |

Aggregation components (not plugins): **CISScorer** (Confluence Intelligence Score across all fired setups), **SignalAggregator** (selects winning signal per bar using adjusted_rank from all_ranked)

---

## DAG Execution Engine (Implemented)

### DAG Data Structure

The DAG engine (`src/intelligence/dag.py`) provides dependency-aware execution ordering:

```python
@dataclass
class DagNode:
    node_id: str
    node_type: str  # plugin | join | sink | source
    config: dict[str, Any] = field(default_factory=dict)
    inputs: list[str] = field(default_factory=list)

@dataclass
class Dag:
    nodes: dict[str, DagNode] = field(default_factory=dict)
    edges: list[tuple[str, str]] = field(default_factory=list)

    def add_node(self, node: DagNode) -> None: ...
    def add_edge(self, src: str, dst: str) -> None: ...

    def topological_order(self) -> list[str]:
        """Kahn's algorithm topological sort.
        Raises ValueError if DAG contains a cycle."""
        ...
```

### Current Execution Model

The DAG determines plugin execution order through topological sorting. Currently:

1. **I1 indicators** compute first (no dependencies)
2. **I2 composites** compute next (depend on I1 outputs)
3. **I3 structure** computes on raw OHLCV (independent of I1)
4. **I4 context** computes on raw OHLCV + optionally blends I3 results
5. **I5 patterns** compute after I1 (depend on I1 features via `frames["features"]`)
6. **SMC plugins** compute in parallel with I3-I5, read OHLCV + I1
7. **I6 CTF** reads cross-TF intelligence cache, runs last in market_analysis_service
8. **I7 setups** run in signal_generator_service (separate service)

```
OHLCV Data ──┬── I1 Indicators (parallel) ──┬── I2 Composites (depend on I1)
             │                               └── I5 Patterns (read I1 features)
             ├── I3 Structure ──── I4 Context (optional I3 blending)
             ├── SMC Plugins (parallel with I3-I5, read OHLCV + I1)
             └── I6 CTF (reads cross-TF intelligence cache, runs last)
                                ↓
                        I7 Setups (in signal_generator_service, separate service)
```

### Incremental Processing

The 141x performance boost comes from incremental `compute_next()`:

```python
# First call: full batch computation (seeds state)
plugin.compute_full({"main": historical_df})

# Subsequent calls: O(1) single-bar updates
for new_bar in live_stream:
    result = plugin.compute_next({"main": df_with_new_bar})
    # Uses Wilder's smoothing, EMA state, rolling deques — no recomputation
```

**Incremental Strategies by Plugin:**
- **OBV/VWAP:** Cumulative sum — add new bar's contribution
- **RSI/ATR:** Wilder's smoothing — `(1 - 1/N) * prev + (1/N) * new`
- **MACD/EMA:** EMA state — `alpha * new + (1-alpha) * prev`
- **Bollinger:** Online variance — Welford's algorithm
- **Stochastic/Williams %R/Donchian:** Rolling deques with maxlen
- **CCI/MFI:** Rolling windows of typical price / money flow
- **ADX/DMI:** Triple Wilder's smoothing (+DM, -DM, TR) + ADX smoothing
- **Keltner:** EMA + Wilder's ATR state
- **ROC/PPO:** Close deque + dual EMA state

---

## Reliability & Circuit Breaking (Implemented)

### Circuit Breakers
Circuit breakers protect against cascade failures via LangGraph integration:

- **Config:** `failure_threshold=3`, `recovery_timeout=300s`, `success_threshold=2`
- **States:** CLOSED (normal) → OPEN (failing) → HALF_OPEN (testing recovery)
- **Scope:** Per-plugin and per-external-dependency (Redis, IBKR, DB)
- **Implementation:** `src/intelligence/langgraph_event_processor.py`

### Plugin Validation
- Incremental vs full computation parity: `tests/unit/intelligence/test_plugin_incremental.py`
- Pattern detection correctness: `tests/unit/intelligence/test_pattern_plugins.py`
- Structure plugins: `tests/unit/intelligence/test_structure_plugins.py`
- Context plugins: `tests/unit/intelligence/test_context_plugins.py`
- **Total: 1754 unit tests passing**

---

## Stream Distribution

### Intelligence Stream Architecture

**Stream Naming Convention:**
```
{env_prefix}:{stream_type}:{SYMBOL}:{timeframe}

# Examples (built via src/core/stream_keys.py):
market:ES:1m          # OHLCV bars
indicators:ES:1m      # I1 indicator features
patterns:ES:1m        # I5 pattern detections
intelligence:ES:1m    # Higher-tier intelligence
ticks:ES:live         # Raw tick data
```

**Stream Lifecycle:**
- **Environment Prefixing:** Via `INDICAGENT_ENV` variable
- **Consumer Groups:** Multiple consumers for horizontal scaling
- **Retention:** Configurable MAXLEN per stream
- **Key Construction:** Always via `src/core/stream_keys.py` — never hardcoded

---

## Performance Characteristics

### Current Production Performance
- **Tick Ingestion:** 100-500+ ticks/sec during RTH
- **Hot Path Latency:** Sub-millisecond Redpanda stream writes
- **I1 Indicator Calculation:** <1ms per plugin via incremental compute_next()
- **I3-I6 Pipeline:** <10ms per bar (market_analysis_service)
- **I7 Signal Generation:** <50ms per bar
- **Full Recomputation (I1):** ~50-100ms for all 25 indicators (batch mode)
- **Incremental vs Batch:** 141x speedup measured
- **Tests:** 1754 passing

### SLO Targets
| Metric | Target | Status |
|--------|--------|--------|
| Plugin execution latency | <50ms p99 | Achieved (<1ms incremental) |
| End-to-end bar-to-indicator | <200ms | Achieved |
| Stream backlog | <30s | Achieved |
| Test suite pass rate | 100% | 1754 passing |

---

## Future Enhancements (Not Yet Implemented)

### Planned Architecture Additions

**YAML Pipeline Configuration:**
- Configuration-driven pipeline composition (currently Python-only)
- Hot-reloading with zero-downtime updates

**Parallel DAG Execution:**
- Async parallel execution within DAG stages (independent plugins)
- Symbol sharding across processing instances

**Backpressure & Autoscaling:**
- Stream queue depth monitoring
- Dynamic concurrency adjustment
- Graceful degradation under load

---

## Related Documentation

### Core Architecture
- [Intelligence Tiers (I1-I8)](../concepts/intelligence-tiers.md) - Complete intelligence tier definitions
- [Layered Architecture](layered-architecture.md) - Foundation infrastructure overview
- [Stream Schemas](stream-schemas.md) - Data format and event specifications
- [Plugin-Native Architecture Explained](plugin-native-architecture-explained.md) - Architectural principles

### Service Integration
- [Event-Driven Indicator System](event-driven-indicator-system.md) - Service-based processing
- [Comprehensive Intelligence Architecture](comprehensive-intelligence-architecture.md) - Executive overview

---

**Framework Philosophy:** *Modular, dependency-aware plugin architecture progressing from mathematical features to AI-powered insights — keeping the implementation simple and the abstractions honest.*
