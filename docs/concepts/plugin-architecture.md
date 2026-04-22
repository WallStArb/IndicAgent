# Plugin Architecture

**Current Plugin Count:** 123 plugins + 2 aggregation — source of truth: `src/intelligence/register_plugins.py`
**Last Updated:** 2026-04-22

## Executive Summary

IndicAgent's Intelligence Plugin Registry and DAG Execution Framework provides the foundation for market intelligence processing. The framework uses a simple, protocol-based plugin architecture with dependency-aware DAG execution, supporting the I1-I8 intelligence tiers.

**Core Capability:** Extensible intelligence processing framework that transforms raw market data into structured intelligence through modular, dependency-aware plugin execution.

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
- **`insight.v1`** - I8 AI Intelligence (planned — not yet implemented)

### Data Format Standards
- **Stream Format:** Kafka (Redpanda-compatible) with JSONB payloads
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
    # ... 27 I1 indicators total ...
    registry.register_pattern(rsi_div_plugin)
    # ... 70 patterns/structure/context/SMC/I7 total ...
```

No auto-discovery or hot-reload — registration is explicit Python code.

---

## Registered Plugins (123 Total + 2 Aggregation)

See [Intelligence Tiers](intelligence-tiers.md) for the full plugin list. Summary below.

### I1 Indicator Plugins (27) — All support incremental `compute_next()`

| Plugin | Category | Key Outputs |
|--------|----------|-------------|
| RSI | Momentum | `rsi_14` |
| MACD | Trend | `macd_12_26_9`, `macd_signal_12_26_9`, `macd_hist_12_26_9` |
| MA (SMA/EMA) | Trend | `sma_20`, `sma_50`, `sma_100`, `sma_200`, `ema_8`, `ema_9`, `ema_13`, `ema_21`, `ema_55` |
| MACompare | Trend | `ma_cross_20_50`, `ma_distance_20`, `ma_distance_50` |
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
| AC Oscillator | Momentum | `ac_osc` (Awesome Oscillator) |
| HMA | Trend | `hma_value` (Hull Moving Average) |
| OFI | Volume/Flow | `ofi_value`, `ofi_cumulative`, `ofi_normalized` (Order Flow Imbalance) |
| CVD | Volume/Flow | `cvd_value`, `cvd_delta`, `cvd_slope` (Cumulative Volume Delta) |

### I2 Composite Event Plugins (10) — detect state changes in I1 outputs

| Plugin | Outputs |
|--------|---------|
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
| MACD Events | `macd_cross_up`, `macd_cross_dn`, `macd_hist_flip` |
| Swing Detector | Swing highs/lows, HH/HL/LH/LL classification |
| Support/Resistance | Pivot clustering, strength scoring, nearest S/R levels |
| Trend Structure | Swing sequence scoring, structural integrity, price position |
| Market Profile | POC, value area high/low, TPO distribution |
| Session Levels | Prior session high/low/mid, overnight range |
| Fibonacci Zones | Fib retracement and extension zones from swing range |
| Swing Momentum | Momentum at swing highs/lows for divergence context |

### I4 Context Plugins (12) — `supports_incremental = False`

| Plugin | Outputs |
|--------|---------|
| Volatility Regime | ATR percentile, BB width, expansion/contraction |
| Trend Regime | SMA-20/50 alignment, 5-state classification |
| Momentum Context | Multi-oscillator direction scoring (RSI/MACD/Stoch/CCI) |
| GARCH Volatility | `garch_vol_regime`, `garch_sigma`, conditional vol forecast (Wave A) |
| Hurst Exponent | `hurst_exponent`, `hurst_trend_quality`, `hurst_mr_quality` |
| Shannon Entropy | `shannon_entropy`, `entropy_quality` |
| Kalman Trend | `kalman_price_position`, `kalman_trend_slope`, 7 outputs; GARCH-adaptive R matrix (Wave B) |
| Session Context | Active session (London/NY/Asia/overlap), killzone timing |
| Anchored VWAP | VWAP anchored to swing points or session opens (`ctx_AnchoredVWAP`) |
| Volume Profile | Session + rolling volume distribution: POC, VAH, VAL, HVN/LVN (`ctx_VolumeProfile`) |
| VIX Regime | VIX-based macro volatility regime; cross-asset fear gauge |
| Cross-Asset Context | Cross-asset correlation and divergence signals |

### I5 Pattern Plugins (16) — `supports_incremental = False`

| Plugin | Category | Outputs |
|--------|----------|---------|
| MTF Volatility | Volatility | Multi-timeframe volatility spread and compression |
| RSI Divergence | Divergence | Bullish/bearish divergence type and strength |
| Bollinger Squeeze | Momentum | TTM-style BB-inside-KC squeeze detection |
| Volume Divergence | Volume | OBV slope vs price slope via linear regression |
| MACD Divergence | Divergence | Bullish/bearish MACD histogram divergence vs price |
| CMF Divergence | Divergence | Chaikin Money Flow divergence vs price |
| Confluence | Oscillator | RSI/MACD/Stoch/CCI scoring from -1 to +1 |
| TrendConfluence | Trend | 6-signal trend aggregation score |
| Double Top/Bottom | Chart | Double top and double bottom detection |
| Head & Shoulders | Chart | H&S with sloped neckline |
| Triangle/Wedge | Chart | Triangle/wedge convergence ratio |
| Candlestick Patterns | Candlestick | Hammer, engulfing, doji, pin bar, morning/evening star |
| Flag/Pennant | Continuation | Flag and pennant continuation patterns |
| Cup & Handle | Continuation | Cup & handle accumulation pattern |
| Measured Move | Projection | AB=CD measured move projection |
| Key Level Reaction | Price Action | Reaction strength at S/R levels from I3 |

### I6 SMC / Smart Money Plugins (13) — `supports_incremental = False`

| Plugin | Outputs |
|--------|---------|
| BOS/CHoCH | Break of structure, change of character levels |
| FVG | Fair value gaps (bullish/bearish, size, fill%) |
| Order Blocks | OB zones, strength, touch count |
| Liquidity Sweeps | Sweep events, reclaim signals |
| BOCPD | Changepoint probability, hazard function |
| HMM Regime | 3-state HMM (ranging/trend↑/trend↓), forward probabilities |
| Liquidity Pools | BSL/SSL pool levels and proximity |
| Supply/Demand Zones | S/D zones with strength scoring |
| ICT Killzones | London/NY/Asia killzone timing and bias |
| AMD Cycle | Accumulation/Manipulation/Distribution phase detection |
| Breaker Blocks | Failed order blocks converted to breakers |
| Mitigation Blocks | Unmitigated order block tracking |
| Premium/Discount | Price position relative to range equilibrium |

### I6 Cross-Timeframe Confluence (1)

Single plugin scoring trend/structure/regime/pattern alignment across 1m/5m/15m/1h.

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

The DAG determines plugin execution order through topological sorting. Tiers execute sequentially; within each tier, sub-waves allow safe parallelism where intra-tier dependencies allow it:

1. **I1** — all 27 indicators (no dependencies)
2. **I2** — 2 waves: Wave A (base events), Wave B (AccelerationRegime + ExhaustionScore consume Wave A outputs)
3. **I3** — structure + MACDEvents (requires I1/I2)
4. **I4** — 2 waves: Wave A (GARCH, VIXRegime, CrossAssetContext, etc.), Wave B (KalmanTrend consumes `garch_sigma`)
5. **I5** — patterns (require I1–I4)
6. **I6 SMC** — 2 waves: Wave A (base SMC), Wave B (SupplyDemandZones, BreakerBlocks, MitigationBlocks consume Wave A)
7. **I6 Confluence** — reads all prior tiers across timeframes
8. **I7** — all 36 setup plugins run after I6

```
OHLCV Data ──► I1 (27) ──► I2 (10, 2 waves) ──► I3 (8) ──► I4 (12, 2 waves)
                                                                    │
                                                                    ▼
                                              I5 (16) ──► I6 SMC (13, 2 waves)
                                                                    │
                                                                    ▼
                                                         I6 Conf (1) ──► I7 (36 + 2 agg)
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

## Reliability & Error Handling (Implemented)

### Plugin Error Handling
Each plugin call is wrapped with error isolation. If a plugin raises an exception, the service logs it, records a Prometheus error metric, and continues processing with the remaining plugins. A single plugin failure never blocks the bar from being processed.

- **Prometheus metrics:** Per-plugin success/error counters sampled every `PLUGIN_METRICS_SAMPLE_RATE=10` calls
- **Error isolation:** Exceptions are caught per-plugin; stack trace logged with `plugin_name`, `symbol`, `timeframe`
- **No circuit breakers** in the hot path — failed plugins simply return `{}` (empty result)

### Plugin Validation
- Incremental vs full computation parity: `tests/unit/intelligence/test_plugin_incremental.py` (27 tests)
- Pattern detection correctness: `tests/unit/intelligence/test_pattern_plugins.py` (16 tests)
- Structure plugins: `tests/unit/intelligence/test_structure_plugins.py` (12 tests)
- Context plugins: `tests/unit/intelligence/test_context_plugins.py` (13 tests)
- **Total: 1754 unit tests passing**

---

## Stream Distribution

### Intelligence Stream Architecture

**Topic naming:** `{env}.{domain}[.{sublayer}]` — dots only, never colons. Key is typically `SYMBOL:TF`.

```
# Examples (always built via src/core/stream_keys.py):
development.market.bars            # Canonical 1m OHLCV bars
development.market.bars.htf        # 5m–1d aggregated bars
development.intelligence           # I1–I7 IntelligenceEvent (keyed SYMBOL:TF)
development.intelligence.i7.signals  # All ranked I7 signals per bar
development.intelligence.journal   # High-confidence signals → I8 narrative
development.intelligence.lifecycle # LifecycleTransition events
development.intelligence.signal_metrics  # Signal performance stats
development.narratives             # I8 per-signal narrative (keyed SYMBOL:TF)
development.llm.calls              # LLM call audit
```

- **Environment Prefixing:** Via `INDICAGENT_ENV` setting (empty string in production)
- **Consumer Groups:** `<concept>_consumer` — idempotent on restart
- **Key Construction:** Always via `src/core/stream_keys.py` — never hardcode topic strings

---

## Performance Characteristics

### Current Production Performance
- **Tick Ingestion:** 100-500+ ticks/sec during RTH
- **Hot Path Latency:** Sub-millisecond Redpanda stream writes
- **Indicator Calculation:** <1ms per plugin via incremental compute_next()
- **Full Recomputation:** ~50-100ms for all 27 indicators (batch mode)
- **Incremental vs Batch:** 141x speedup measured

### SLO Targets
| Metric | Target | Status |
|--------|--------|--------|
| Plugin execution latency | <50ms p99 | Achieved (<1ms incremental) |
| End-to-end bar-to-indicator | <200ms | Achieved |
| Stream backlog | <30s | Achieved |
| Test suite pass rate | 100% | 1754/1754 passing |

---

---

## Related Documentation

- [High-Level Concepts](../architecture/concepts.md) — Core architectural patterns including DAG, microservices, and ML/AI layers
- [Intelligence Tiers](intelligence-tiers.md) — complete tier-by-tier plugin reference
- [DAG Execution](dag-execution.md) — how plugin dependencies are ordered via topological sort
- [Incremental Computation](incremental-computation.md) — 141x speedup, state patterns by indicator type
- [Data Pipeline](data-pipeline.md) — hot/warm/cold tiers, stream keys, consumer groups
- **ML/AI Architecture:** `../ideas/ml-agent-architecture.md` — Multi-agent orchestrator and swarm intelligence
- **Intelligence Swarm:** `../ideas/intelligence-swarm-manifest.md` — Task/job-based agents for market friction analysis
- **Architecture:** `docs/architecture/plugin-native-architecture-explained.md`
- **Code:** `src/intelligence/plugins.py`, `src/intelligence/dag.py`, `src/intelligence/register_plugins.py`

---

**Framework Philosophy:** *Modular, dependency-aware plugin architecture progressing from mathematical features to AI-powered insights — keeping the implementation simple and the abstractions honest.*
