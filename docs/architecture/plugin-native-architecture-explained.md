# Plugin-Native Architecture Explained

**Version:** 2.1.0
**Last Updated:** 2026-02-14
**Status:** 31 Plugins Operational, I1-I6 Partial (Smart Money)

## Overview

This document explains IndicAgent's plugin-native architecture — a modular intelligence platform that transforms raw market data into structured intelligence through composable plugins with dependency-aware DAG execution.

**Target Audience:** Developers and architects seeking to understand the core architectural principles and how to extend the system.

---

## What "Plugin-Native" Means

### Traditional vs Plugin-Native Approach

**Traditional Approach:** Hard-coded services that do specific calculations
```python
# Old way - rigid, hard to change
def calculate_indicators():
    rsi = calculate_rsi(data)
    macd = calculate_macd(data)
    sma = calculate_sma(data)
    # Adding new indicators requires modifying this function
    # No flexibility in composition
    # Manual state management
```

**Plugin-Native Approach:** Self-describing plugins with a common protocol
```python
# New way - add a @dataclass, register it, done
@dataclass
class RSIPlugin:
    name: str = "RSI"
    outputs: set[str] = frozenset({"rsi_14"})
    supports_incremental: bool = True

    def compute_full(self, frames): ...
    def compute_next(self, windows): ...

# Registration in register_plugins.py:
registry.register_indicator(rsi_plugin)
```

**Key Difference:** New intelligence capabilities are added by writing a single `@dataclass` file and one line of registration — no changes to the processing pipeline, DAG engine, or stream infrastructure.

---

## Core Architecture: 4 Clean Layers

### Layer 1: Data Foundation
**Purpose:** High-performance data collection and distribution

```
IBKR TWS -> High-Frequency Collection (100-500+ ticks/sec)
         -> Multi-Timeframe Aggregation (1m -> 5m -> 15m -> 1h -> 4h -> 1d)
         -> DragonflyDB Redis Streams Distribution (3,200+ ops/sec)
         -> TimescaleDB Cold Storage
```

**Key Components:**
- `production/daemons/high_frequency_tws_daemon.py` - Live tick collection
- `services/timeframes_builder_service.py` - Multi-timeframe aggregation
- `src/core/redis_streams_manager.py` - High-performance stream distribution
- `src/core/database_manager.py` - TimescaleDB persistence

**Output:** Clean `market:SYMBOL:TIMEFRAME` streams that feed all intelligence processing.

### Layer 2: Mathematical Intelligence (I1-I4) -- Implemented
**Purpose:** Plugin-based mathematical analysis, structure, and context

**I1 Raw Indicators (16 plugins, all incremental):**

| Category | Plugins |
|----------|---------|
| Trend | SMA/EMA, MACD, ADX/DMI |
| Momentum | RSI, Stochastic, Williams %R, CCI, ROC/PPO |
| Volatility | Bollinger Bands, ATR, Keltner Channels, Donchian Channels |
| Volume | OBV, MFI, VWAP |
| Composite | MA Composites (crossovers, distances) |

**I3 Market Structure (3 plugins):**
- Swing detector (HH/HL/LH/LL classification)
- Support/resistance (pivot clustering with strength scoring)
- Trend structure (swing sequence scoring, structural integrity)

**I4 Context Classification (3 plugins):**
- Volatility regime (ATR percentile + BB width)
- Trend regime (SMA-20/50 alignment, 5-state classification)
- Momentum context (multi-oscillator direction scoring)

**Output Streams:** `indicators:SYMBOL:TIMEFRAME`, `patterns:SYMBOL:TIMEFRAME`

### Layer 3: Pattern Intelligence (I5) -- Implemented
**Purpose:** Pattern detection using I1 features and raw OHLCV data

**I5 Pattern Plugins (4 plugins):**
- RSI Divergence — bullish/bearish divergence with peak/trough detection
- Bollinger Squeeze — TTM-style BB-inside-KC squeeze detection
- Volume Divergence — OBV slope vs price slope via linear regression
- Confluence — multi-indicator scoring (RSI/MACD/Stoch/CCI) from -1 to +1

**Output Streams:** `patterns:SYMBOL:TIMEFRAME`

### Layer 4: Smart Money Intelligence & Confluence (I6-I8) -- Partial Implementation
**Purpose:** Smart money flow detection, confluence scoring, institutional liquidity analysis, and future multi-factor scoring

**I6 Smart Money Plugins (6 plugins):**
- Break of Structure (BOS) / Change of Character (CHOCH) — structural bias detection and reversal identification
- Fair Value Gap (FVG) — imbalance zone identification, HTF confluence, and gap fill probability
- Order Blocks (OB) — demand/supply zone clustering with strength scoring and institutional accumulation zones
- Liquidity Sweeps — institutional liquidity extraction, swing point violation detection, and trap identification
- BOCPD Change Point Detection — Bayesian online change point detection for regime shifts and regime consistency analysis
- HMM Regime Classification — 3-state Hidden Markov Model (ranging/trending-up/trending-down) with multivariate Gaussian emissions

**Future capabilities (I7-I8):**
- **I7 Trading Outputs:** Validated setups with entry/exit/stops, position sizing, risk/reward ratios
- **I8 AI Insights:** LLM-powered pattern interpretation, market narratives, cost-controlled inference

**Output Streams:** `intelligence:SYMBOL:TIMEFRAME`, `insights:SYMBOL:TIMEFRAME`

---

## How Plugins Actually Work

### The Plugin Protocol

Every plugin satisfies either `IndicatorPlugin` or `PatternPlugin` (identical interfaces):

```python
# src/intelligence/plugins.py
class IndicatorPlugin(Protocol):
    name: ClassVar[str]                    # Unique identifier
    outputs: ClassVar[set[str]]            # Feature keys produced
    min_lookback: ClassVar[int]            # Minimum bars needed
    supports_incremental: ClassVar[bool]   # Can process single new bars
    capability_tags: ClassVar[set[str]]    # ["trend", "momentum", "volatility", "volume"]
    inputs: ClassVar[list[InputSpec]]      # Input requirements

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]: ...
    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]: ...
```

### Adding a New Plugin (Real Workflow)

**Step 1:** Create a `@dataclass` plugin file:
```python
# src/intelligence/indicators/my_indicator.py
@dataclass
class MyIndicatorPlugin:
    name: str = "MyIndicator"
    outputs: set[str] = frozenset({"my_ind_14"})
    min_lookback: int = 20
    supports_incremental: bool = True
    capability_tags: set[str] = frozenset({"momentum"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=100),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames):
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}
        # ... calculation ...
        self._seed_state(frames)
        return {"my_ind_14": value}

    def _seed_state(self, frames):
        # Extract rolling state for incremental mode
        ...

    def compute_next(self, windows):
        if not self._state:
            return self.compute_full(windows)
        # ... O(1) incremental update ...
        return {"my_ind_14": value}

plugin = MyIndicatorPlugin()
```

**Step 2:** Register it:
```python
# src/intelligence/register_plugins.py
from .indicators.my_indicator import plugin as my_ind_plugin

def register_all_plugins() -> None:
    # ... existing registrations ...
    registry.register_indicator(my_ind_plugin)
```

**Step 3:** Write tests:
```python
# tests/unit/intelligence/test_plugin_incremental.py
class TestMyIndicatorIncremental:
    def test_compute_next_matches_full(self):
        # Seed with 100 bars, feed 100 more incrementally
        # Assert final incremental == fresh full computation
        ...
```

That's it. The DAG engine picks it up, streams carry its output, and the service mesh distributes results.

---

## DAG Execution

### How Dependencies Work

The DAG engine (`src/intelligence/dag.py`) uses Kahn's algorithm for topological sorting:

```
OHLCV Data --+-- I1 Indicators (parallel) --+-- I2 Composites
             |                               +-- I5 Patterns (reads features)
             +-- I3 Structure ----- I4 Context (optional I3 blending)
             +-- I4 Context (self-contained mode)
```

Plugins declare their dependencies via `inputs` and `capability_tags`. The DAG ensures:
1. I1 indicators compute before I5 patterns (which need features)
2. I3 structure computes before I4 context (for optional blending)
3. I6 smart money plugins compute after I1-I3 (independent of I4-I5)
4. Independent plugins can execute in parallel within a stage

### Incremental Processing (141x Speedup)

The key performance optimization: after initial `compute_full()` seeds state, subsequent bars use `compute_next()` for O(1) updates:

```python
# Initial: ~50-100ms for all 16 indicators
plugin.compute_full({"main": historical_600_bars})

# Live: <1ms per indicator per bar
plugin.compute_next({"main": df_with_new_bar})
```

**How each strategy works:**
- **Wilder's Smoothing (RSI, ATR, ADX):** `new = (1 - 1/N) * old + (1/N) * current`
- **EMA State (MACD, Keltner):** `new = alpha * price + (1 - alpha) * old`
- **Rolling Deques (Stochastic, Donchian, ROC):** Fixed-size window, O(1) push/pop
- **Cumulative (OBV, VWAP):** Running sum, just add new bar
- **Online Variance (Bollinger):** Welford's algorithm for running std dev

---

## Stream-Native Processing

### Stream Architecture

Every intelligence result flows through Redis Streams:

```
market:ES:1m  -->  Indicator Service  -->  indicators:ES:1m
                                      -->  patterns:ES:1m
                                      -->  intelligence:ES:1m
                                      -->  SSE to Dashboard
```

**Stream naming** (always via `src/core/stream_keys.py`):
```
{env_prefix}:{type}:{SYMBOL}:{timeframe}

market:ES:1m          # Raw OHLCV bars
ticks:ES:live         # High-frequency tick data
indicators:ES:1m      # I1 indicator features
patterns:ES:1m        # I3-I6 pattern/structure/context/smart_money
intelligence:ES:1m    # I6+ higher-tier intelligence
```

### Hot/Warm/Cold Data Flow
- **Hot (DragonflyDB):** Real-time streams, sub-ms latency, no database in the critical path
- **Warm (Stream Processing):** Service mesh processes bars through plugins in <200ms
- **Cold (TimescaleDB):** Background archival only, historical analysis and backtesting

---

## Complete Intelligence Flow

Here's how a single 1-minute bar flows through the system:

**1. Data Ingestion:**
```
IBKR TWS -> hf-tws daemon -> market:ES:1m (DragonflyDB stream)
```

**2. Indicator Processing (I1):**
```
market:ES:1m -> Indicator Service -> 16 plugins via compute_next()
   RSI: 65.2, MACD: 2.1, ATR: 12.3, ADX: 28.4, ...
   -> indicators:ES:1m
   Latency: <1ms per plugin (incremental)
```

**3. Structure & Context (I3-I4):**
```
market:ES:1m -> Structure plugins -> swing highs/lows, S/R levels
             -> Context plugins  -> trend regime: "bullish", volatility: "normal"
   -> patterns:ES:1m
```

**4. Pattern Detection (I5):**
```
indicators:ES:1m + market:ES:1m -> Pattern plugins
   RSI divergence: bullish (strength: 0.76)
   Bollinger squeeze: active (count: 5 bars)
   -> patterns:ES:1m
```

**5. Smart Money Detection (I6):**
```
market:ES:1m -> Smart Money plugins
   BOS/CHOCH: bearish structure break detected
   FVG: imbalance zone at 5000-5010 (mitigated: 0.3)
   Order Blocks: supply zone strength: 0.82
   Liquidity Sweeps: HTF trap activated
   BOCPD: regime shift detected (bullish -> ranging)
   -> patterns:ES:1m / intelligence:ES:1m
```

**6. Dashboard Distribution:**
```
indicators:ES:1m -> SSE route -> Next.js Dashboard (live charts)
patterns:ES:1m   -> SSE route -> Next.js Dashboard (alerts)
intelligence:ES:1m -> SSE route -> Next.js Dashboard (smart money insights)
```

---

## Why This Architecture Works

| Aspect | Benefit |
|--------|---------|
| **Adding indicators** | Write a `@dataclass`, add one registration line, write tests |
| **Performance** | 141x speedup via incremental `compute_next()` |
| **Reliability** | Circuit breakers per plugin, graceful fallback |
| **Testing** | Protocol ensures every plugin is testable in isolation |
| **Independence** | Plugins have no knowledge of each other |
| **Streaming** | All results flow through Redis Streams automatically |
| **Observability** | Prometheus metrics per plugin, per service |

### What Makes It "Plugin-Native" vs Just "Has Plugins"

The distinction is that plugins aren't bolted onto an existing system — they ARE the system:

1. **The processing pipeline is empty without plugins.** There's no hardcoded RSI calculation anywhere. Remove the RSI plugin and RSI stops being calculated. Period.

2. **The DAG is built from plugin declarations.** Plugins declare what they need (`inputs`) and what they produce (`outputs`). The execution graph emerges from these declarations.

3. **Streams carry plugin output natively.** The stream infrastructure doesn't know about RSI or MACD — it carries whatever key-value pairs plugins produce.

4. **New capabilities = new plugins.** Adding ADX/DMI to the platform required one Python file and one registration line. No pipeline changes, no stream changes, no config changes.

---

## Current Status & Metrics

- **57 plugins** registered (23 I1 + 3 I3 + 5 I4 + 8 I5 + 8 SMC + 1 I6 confluence + 9 I7 setups)
- **Breakdown:** 23 I1 indicators + 3 I3 structure + 5 I4 context + 8 I5 patterns + 8 SMC smart money + 1 CTF + 9 I7 setups
- **170+ unit tests** passing, 0 ruff errors
- **141x** incremental performance boost measured
- **100-500+** ticks/sec ingestion during RTH
- **<1ms** per-plugin incremental calculation latency
- **I1-I6** tiers operational (I6 Smart Money partially implemented)
- **I7-I8** tiers planned (trading outputs, AI insights)

---

## Related Documentation
- [Plugin Registry & DAG Execution](plugin-registry-and-dag-execution.md) - Technical implementation details
- [Intelligence Tiers (I1-I8)](../concepts/intelligence-tiers.md) - Complete tier definitions
- [Layered Architecture](layered-architecture.md) - Infrastructure overview
- [Stream Schemas](stream-schemas.md) - Data format specifications
