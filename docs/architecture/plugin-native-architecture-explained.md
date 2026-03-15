# Plugin-Native Architecture Explained

**Version:** 3.0.0
**Last Updated:** 2026-03-11
**Status:** I1-I8 Complete — 98 Plugins Operational

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
         -> Redpanda Topic Distribution (3,200+ ops/sec)
         -> TimescaleDB Cold Storage
```

**Key Components:**
- `production/daemons/high_frequency_tws_daemon.py` - Live tick collection
- `src/core/stream_keys.py` - All Redis stream key construction
- `src/core/database_manager.py` - TimescaleDB persistence

**Output:** Clean `market:SYMBOL:TIMEFRAME` streams that feed all intelligence processing.

### Layer 2: Mathematical Intelligence (I1-I4) — Operational
**Purpose:** Plugin-based mathematical analysis, structure, and context

**I1 Raw Indicators (25 plugins, all incremental):**

| Category | Plugins |
|----------|---------|
| Trend | SMA/EMA (MA), MACompare, MACD, ADX/DMI, Supertrend, HMA |
| Momentum | RSI, Stochastic, Williams %R, CCI, ROC/PPO, Aroon, StochRSI, ACOscillator |
| Volatility | Bollinger Bands, ATR, Keltner, Donchian, HistoricalVolatility, ChandelierExit, PSAR |
| Volume | OBV, MFI, VWAP, CMF |

**I2 Second-Derivative / Event (10 plugins):**
- MACD Events, RSI Events, Stoch Events, ADX Events, Volume Events
- MomentumAccel, DonchianPos, OBVMomentum, DerivOsc, ExhaustionScore

**I3 Market Structure (8 plugins):**
- Swing (HH/HL/LH/LL classification), SR (pivot clustering with strength scoring), TrendStructure (swing sequence scoring)
- MarketProfile, SessionLevels, AnchoredVWAP, FibZones, SwingMomentum

**I4 Context Classification (7 plugins):**
- VolRegime, TrendRegime, MomentumCtx
- GARCHVol, KalmanTrend, SessionCtx, MTFVol

**Output Streams:** `indicators:SYMBOL:TIMEFRAME`

### Layer 3: Pattern Intelligence (I5 + SMC) — Operational
**Purpose:** Pattern detection using I1 features, raw OHLCV, and smart money flow

**I5 Pattern Plugins (14 plugins):**
- RSIDivergence, BollingerSqueeze, VolDivergence, Confluence, TrendConfluence
- DoubleTB, HeadShoulders, TriangleWedge, Candlestick, FlagPennant, CupHandle
- MeasuredMove, VolumeProfile, KeyLevelReaction

**SMC Smart Money Plugins (13 plugins):**
- BOS/CHoCH (structural bias and reversal detection)
- FVG (imbalance zones, gap fill probability)
- OrderBlocks (institutional demand/supply zone clustering)
- LiquiditySweeps (institutional trap identification)
- BOCPD (Bayesian online change point detection)
- HMM (3-state Hidden Markov Model: ranging/trending-up/trending-down)
- LiquidityPools, SupplyDemandZones, ICTKillzones, AMDCycle
- BreakerBlocks, MitigationBlocks, PremiumDiscount

### Layer 4: Signal Intelligence (I6-I8) — Operational
**Purpose:** Cross-timeframe confluence, trading setups, and AI narrative

**I6 CrossTimeframe (1 plugin):**
- CTF: alignment scoring across 1m/5m/15m/1h — scores trend/structure/regime/pattern alignment

**I7 Trading Setups (17 plugins + 2 aggregation components):**

| Setup Type | Plugin |
|-----------|--------|
| Trend | TrendFollowing, MTFAlignment, MomentumBreakout |
| Reversal | MeanReversion, CHoCHReversal, DivergenceStack |
| Liquidity | LiquiditySweepReclaim, LiquidityHunt, VWAPDeviation |
| Pattern | SqueezeExpansion, SupplyDemandSetup, FVGFill, PatternCompletion |
| Regime | RegimeTransition, GapAnalysis, CandlestickPatternSetup, SessionExtremes |
| Aggregation | **CISScorer** (composite intelligence scoring), **SignalAggregator** (winner selection) |

**I8 AI Narrative — Operational:**
- Ollama `qwen3.5:9b` per-signal narrative, `phi4-mini:3.8b` group synthesis
- LLM Writer service: full audit log to `llm_calls` hypertable, model scoring via `llm_model_scores`

**Output Streams:** `intelligence:SYMBOL:TIMEFRAME`, `signals:SYMBOL:TIMEFRAME:aggregated`, `narratives:SYMBOL:TIMEFRAME`

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

The DAG engine (`src/intelligence/dag.py`) uses Kahn's algorithm for topological sorting. Current execution order within `market_analysis_service`:

```
OHLCV Data --+-- I1 indicators (parallel, incremental)
             +-- I2 composites (depend on I1 outputs)
             +-- I3 structure (parallel, on raw OHLCV)
             +-- I4 context (on OHLCV, optionally blends I3)
             +-- I5 patterns (depend on I1 features)
             +-- SMC (on OHLCV + I1 features)
             +-- I6 CTF (reads cross-TF intelligence cache)
             --> intelligence:SYMBOL:TF (typed IntelligenceEvent)
             --> signal_generator_service --> I7 setups --> signals:SYMBOL:TF:aggregated
```

Plugins declare their dependencies via `inputs` and `capability_tags`. The DAG ensures:
1. I1 indicators compute before I2 composites and I5 patterns (which need features)
2. I3 structure computes before I4 context (for optional blending)
3. SMC plugins compute on OHLCV + I1 features, independent of I4-I5
4. I6 CTF reads the cross-TF intelligence cache after all prior tiers complete
5. I7 setups run in `signal_generator_service` on the full `IntelligenceEvent`
6. Independent plugins can execute in parallel within a stage

### Plugin State Management

Plugin state is managed entirely in-memory within each service — no Redis-backed state in the hot path:

- **`_plugin_cache`** — plugin singletons built at init, reused per-bar (no registry lookup)
- **`_plugin_states`** — `dict[tuple[str, str, str], dict]` keyed by `(plugin_name, symbol, timeframe)`; swapped onto `p._state` before `compute_full()` and written back after (write-back is load-bearing for GARCH/HMM which fully reassign `_state`)
- **`_plugin_call_counts`** — `defaultdict(int)` keyed by `(plugin_name, tier)`; records Prometheus success metrics every `PLUGIN_METRICS_SAMPLE_RATE=10` total calls; errors always recorded

### Incremental Processing (141x Speedup)

The key performance optimization: after initial `compute_full()` seeds state, subsequent bars use `compute_next()` for O(1) updates:

```python
# Initial: ~50-100ms for all 25 indicators
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
                                      -->  (I1+I2 features)

indicators:ES:1m  -->  Market Analysis Service  -->  intelligence:ES:1m
                                                     (I3→I4→I5→SMC→I6 pipeline)

intelligence:ES:1m  -->  Signal Generator Service  -->  signals:ES:1m:aggregated
                                                        signal_ledger (DB)

intelligence:ES:1m  -->  AI Narrative Service  -->  narratives:ES:1m
                    -->  Feature Writer Service -->  intelligence_features (DB)
```

**Stream naming** (always via `src/core/stream_keys.py`):
```
{env_prefix}:{type}:{SYMBOL}:{timeframe}

market:ES:1m              # Raw OHLCV bars from IBKR TWS
indicators:ES:1m          # I1+I2 indicator features
intelligence:ES:1m        # I3-I6 typed IntelligenceEvent
signals:ES:1m:aggregated  # I7 winning setup signal
narratives:ES:1m          # I8 AI narrative
```

### Hot/Warm/Cold Data Flow
- **Hot (Redpanda):** Real-time topics, sub-ms latency, no database in the critical path
- **Warm (Stream Processing):** Service mesh processes bars through plugins in <200ms
- **Cold (TimescaleDB):** Background archival only — `feature_writer_service` batches `intelligence_features`; `signal_ledger` written by `signal_generator_service`

---

## Complete Intelligence Flow

Here's how a single 1-minute bar flows through the full system:

**1. Data Ingestion:**
```
IBKR TWS -> hf-tws daemon -> market:ES:1m + market:ES:5m/15m/1h/4h/1d
```

**2. I1+I2 Processing (Indicator Service):**
```
market:ES:TF -> 25 I1 plugins via compute_next() + 10 I2 composites
   RSI: 65.2, MACD: 2.1, ATR: 12.3, ADX: 28.4, ...
   MomentumAccel: 0.82, ExhaustionScore: 0.31, ...
   -> indicators:ES:TF
   Latency: <1ms per plugin (incremental)
```

**3. I3 Structure (Market Analysis Service, 8 plugins):**
```
market:ES:TF -> Swing highs/lows, S/R levels, trend structure,
               market profile, session levels, anchored VWAP,
               fib zones, swing momentum
```

**4. I4 Context (7 plugins):**
```
market:ES:TF -> vol regime, trend regime, momentum context,
               GARCH vol, Kalman trend, session context, MTF vol
   trend regime: "bullish", volatility: "normal"
```

**5. I5 Patterns (14 plugins):**
```
indicators:ES:TF + market:ES:TF ->
   RSI divergence: bullish (strength: 0.76)
   Bollinger squeeze: active (count: 5 bars)
   Double bottom: forming, H&S: not detected
   Key level reaction: confirmed
```

**6. SMC Smart Money (13 plugins):**
```
market:ES:TF + I1 features ->
   BOS/CHoCH: bearish structure break detected
   FVG: imbalance zone at 5000-5010 (mitigated: 0.3)
   Order Blocks: supply zone strength: 0.82
   Liquidity Sweeps: HTF trap activated
   ICT Killzone: London open active
   AMD Cycle: accumulation phase
   BOCPD: regime shift detected (bullish -> ranging)
```

**7. I6 CTF (1 plugin):**
```
Cross-TF intelligence cache ->
   alignment score across 1m/5m/15m/1h: 0.74 (trend/structure/regime/pattern)
   -> intelligence:ES:TF (typed IntelligenceEvent, tiered JSONB: i1/i3/i4/i5/smc/i6)
```

**8. I7 Signal Generation (Signal Generator Service, 17 setup plugins):**
```
intelligence:ES:TF ->
   TrendFollowing: long setup (rank: 0.81)
   LiquiditySweepReclaim: long setup (rank: 0.73)
   CISScorer: composite score 0.79 (bucket: high_confidence)
   SignalAggregator: TrendFollowing wins -> signals:ES:TF:aggregated
   -> signal_ledger (pending, zone_low/zone_high, targets, stops)
```

**9. Signal Lifecycle:**
```
market:ES:1m -> Signal Lifecycle Service ->
   Activation: price enters zone -> status: active
   MAE/MFE tracking per bar
   Exit classification: 8-class outcome
   (never_activated / stopped_at_entry / stopped_in_trade /
    target_1 / target_1_2 / target_full / ttl_expired_ahead / ttl_expired_behind)
   -> signal_ledger outcome/pnl_r/mae/mfe updated
```

**10. I8 AI Narrative (AI Narrative Service):**
```
intelligence:ES:TF -> Ollama qwen3.5:9b -> narratives:ES:TF
   LLM Writer: llm_calls:stream -> llm_calls hypertable
              outcome back-fill from llm_outcomes:stream
              model scoring -> llm_model_scores (refreshed every 15 min)
```

**11. Feature Persistence (Feature Writer Service):**
```
intelligence:ES:TF -> intelligence_features hypertable (async batch)
   Full feature vectors per bar including i7/i8 JSONB — ML training dataset
```

**12. Dashboard:**
```
signals:ES:TF:aggregated + intelligence:ES:TF + narratives:ES:TF
   -> SSE routes -> Next.js Dashboard (live charts, signal cards, drill panel)
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

4. **New capabilities = new plugins.** Adding a new setup type to I7 required one Python file and one registration line. No pipeline changes, no stream changes, no config changes.

---

## Current Status & Metrics

- **98 active plugins** + 2 aggregation components (CISScorer, SignalAggregator)
- **Breakdown:** 25 I1 + 11 I2 + 8 I3 + 9 I4 + 14 I5 + 13 SMC + 1 I6 + 17 I7 = 98 plugins
- **1754 unit tests** passing
- **141x** incremental performance boost measured
- **100-500+** ticks/sec ingestion during RTH
- **<1ms** per-plugin incremental calculation latency
- **I1-I8** all tiers operational

**Services:**
| Service | Tier | Purpose |
|---------|------|---------|
| `indicagent-indicator` | I1+I2 | 25+10 plugins → `indicators:SYMBOL:TF` |
| `indicagent-market-analysis` | I3→I6 | DAG pipeline → `intelligence:SYMBOL:TF` |
| `indicagent-signal-generator` | I7 | 17 setups + CIS → `signals:SYMBOL:TF:aggregated` + `signal_ledger` |
| `indicagent-signal-lifecycle` | I7 outcome | Zone activation, MAE/MFE, 8-class outcome |
| `indicagent-ai-narrative` | I8 | Ollama qwen3.5:9b → `narratives:SYMBOL:TF` |
| `indicagent-feature-writer` | Storage | Redis → `intelligence_features` hypertable |
| `indicagent-llm-writer` | Storage | `llm_calls:stream` → `llm_calls` hypertable + model scoring |
| `indicagent-api` | API | FastAPI + SSE on :8000 → Dashboard |

---

## Related Documentation
- [Plugin Registry & DAG Execution](plugin-registry-and-dag-execution.md) - Technical implementation details
- [Intelligence Tiers (I1-I8)](../concepts/intelligence-tiers.md) - Complete tier definitions
- [Layered Architecture](layered-architecture.md) - Infrastructure overview
- [Stream Schemas](../reference/schemas/stream-schemas.md) - Data format specifications
