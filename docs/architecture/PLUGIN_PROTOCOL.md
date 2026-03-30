# Plugin Protocol

**Version:** 2.1
**Last Updated:** 2026-03-30
**Status:** I1-I8 Complete — 121 Plugins Operational

> **Developer-facing.** For system-level DAG methodology, see `DAG_TOPOLOGY.md`. For implementation examples, see `src/intelligence/CLAUDE.md`.

## Overview

IndicAgent's intelligence pipeline is built from self-describing plugins. The system is an empty container — there is no hardcoded RSI, MACD, or signal logic. All intelligence emerges from plugins that declare their inputs and outputs.

## Protocol Definition

Every plugin satisfies the `IndicatorPlugin` or `PatternPlugin` protocol:

```python
class IndicatorPlugin(Protocol):
    name: ClassVar[str]                    # Unique identifier
    outputs: ClassVar[set[str]]            # Feature keys produced
    min_lookback: ClassVar[int]            # Minimum bars needed
    supports_incremental: ClassVar[bool]   # Can process single new bars
    capability_tags: ClassVar[set[str]]    # Categorization
    inputs: ClassVar[list[InputSpec]]      # Dependency declarations

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]: ...
    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]: ...
```

**Key Design Decisions:**
- **Protocol, not ABC:** Structural subtyping — any `@dataclass` with the right shape works
- **Two methods only:** `compute_full()` for batch, `compute_next()` for incremental
- **`frames["main"]`:** Convention — primary OHLCV DataFrame at key `"main"`

## Plugin Attributes

| Attribute | Type | Purpose | Example |
|-----------|------|---------|---------|
| `name` | `str` | Unique identifier | `"RSI"`, `"MACD"`, `"BOS_CHoCH"` |
| `outputs` | `set[str]` | Feature keys produced | `{"rsi_14", "macd_12_26_9"}` |
| `min_lookback` | `int` | Minimum bars for computation | `20` for RSI-14 |
| `supports_incremental` | `bool` | Can do O(1) updates | `True` for I1, `False` for I3/I5 |
| `capability_tags` | `set[str]` | Categorization | `{"trend"}`, `{"momentum"}`, `{"smc"}` |
| `inputs` | `list[InputSpec]` | Dependency declarations | `[InputSpec(symbol=".*", timeframe="1m", lookback=100)]` |

## InputSpec Format

```python
class InputSpec:
    symbol: str | Pattern[str]      # ".*" for all, "ES" for specific
    timeframe: str | list[str]      # "1m" or ["1m", "5m", "15m"]
    lookback: int                   # Bars of history needed
    required: bool = True           # Fail if missing?
```

**Examples:**
| Plugin | `inputs` | Meaning |
|--------|----------|---------|
| RSI | `InputSpec(".*", "1m", 100)` | All symbols, 1m only, 100 bars |
| CTF (I6) | `InputSpec(".*", ["1m", "5m", "15m", "1h"], 1)` | Multi-TF read |
| Divergence | `InputSpec(".*", "1m", 50)` | Needs I1 features (50 bars) |

## Output Naming Convention

Flat, snake_case keys following `indicator_param` format:

| Indicator | Outputs |
|-----------|---------|
| RSI | `rsi_14` |
| MACD | `macd_12_26_9`, `macd_signal_12_26_9`, `macd_histogram_12_26_9` |
| Bollinger | `bb_20_2_upper`, `bb_20_2_mid`, `bb_20_2_lower` |
| ADX | `adx_14`, `plus_di_14`, `minus_di_14` |

## Plugin Registry

Plugins are registered explicitly in `src/intelligence/register_plugins.py`:

```python
from .indicators.rsi import plugin as rsi_plugin
from .indicators.macd import plugin as macd_plugin

def register_all_plugins() -> None:
    registry.register_indicator(rsi_plugin)
    registry.register_indicator(macd_plugin)
```

**No auto-discovery** — registration is explicit Python code. This prevents accidental plugin activation.

## Capability Tags

Used for categorization and asset-class filtering:

| Tag | Meaning | Example Plugins |
|-----|---------|-----------------|
| `trend` | Trend-following | RSI, MACD, ADX, Supertrend, HMA |
| `momentum` | Momentum oscillators | Stochastic, Williams %R, CCI, ROC |
| `volatility` | Volatility measures | ATR, Bollinger, Keltner, Donchian |
| `volume` | Volume analysis | OBV, MFI, VWAP, CMF |
| `structure` | Market structure | Swing, S/R, Trend Structure |
| `regime` | Regime classification | GARCH, Kalman, HMM, BOCPD |
| `pattern` | Chart patterns | Double top/bottom, H&S, triangles |
| `smc` | Smart Money Concepts | BOS/CHoCH, FVG, Order Blocks, Liquidity |
| `setup` | Trading setups | TrendFollowing, MeanReversion, LiquiditySweep |

## Incremental Processing

Plugins with `supports_incremental=True` implement O(1) updates via `compute_next()`:

| Strategy | Used By | Update Method |
|----------|---------|---------------|
| Wilder's Smoothing | RSI, ATR, ADX | `new = (1 - 1/N) * old + (1/N) * current` |
| EMA State | MACD, Keltner | `new = alpha * price + (1 - alpha) * old` |
| Rolling Deques | Stochastic, Donchian | Fixed-size window, O(1) push/pop |
| Cumulative | OBV, VWAP | Running sum, add new bar |
| Online Variance | Bollinger | Welford's algorithm |

**Result:** ~141x speedup vs. full recomputation. 25 I1 indicators complete in <1ms per bar.

## Plugin Lifecycle

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Plugin Lifecycle                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  1. Import                                                             │
│     └─→ Plugin module imported, singleton instantiated                │
│                                                                         │
│  2. Register                                                           │
│     └─→ registry.register_indicator(plugin)                           │
│                                                                         │
│  3. DAG Resolution                                                     │
│     └─→ inputs/outputs scanned for dependencies                       │
│     └─→ Topological sort determines execution order                   │
│                                                                         │
│  4. Warmup (first bar per symbol/TF)                                  │
│     └─→ compute_full() called with historical data                    │
│     └─→ State seeded for incremental mode                             │
│                                                                         │
│  5. Live Processing                                                   │
│     └─→ compute_next() called per new bar (O(1) update)               │
│     └─→ Output published to intelligence bus                         │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

## Plugin Validation

Startup validation (`src/core/plugin_validator.py`) ensures system integrity:

| Check | Purpose | Failure Mode |
|-------|---------|--------------|
| Tier list registration | All `TIER_*` plugins in registry | Hard crash |
| Required attributes | `name`, `outputs`, `inputs` present | Hard crash |
| Schema coverage | Outputs covered by `IntelligenceEvent` | Hard crash |
| Orphaned plugins | Imported modules with missing `.py` files | Warning |
| TREND_SETUPS sync | Trend setups match `regime_type="trend"` | Warning |

## State Management

Plugin state is in-memory within `IntelligencePipelineComputeAgent`:

- **`_plugin_cache`**: Plugin singletons, reused per-bar
- **`_plugin_states`**: `dict[(plugin_name, symbol, timeframe), dict]` — rolling state
- **`_plugin_call_counts`**: Prometheus metrics every 10 calls

State is NOT persisted across service restarts. Warmup re-seeds from historical data on startup.

## Error Handling

| Error Type | Handling |
|------------|----------|
| Insufficient data | Return `{}` (empty dict), no output |
| Missing dependency | DAG engine prevents execution (dependency ordering) |
| Compute exception | Logged, metric emitted, continues to next bar |
| Circuit breaker open | Plugin skipped, fallback value if available |

## Plugin Inventory (v2.1)

| Tier | Count | Incremental | Examples |
|------|-------|-------------|----------|
| I1 | 27 | ✅ Yes | RSI, MACD, ATR, ADX, BB, VWAP, Stoch, HMA |
| I3 | 15 | ❌ No | FVG, Order Blocks, Breaker Blocks |
| I4 | 11 | ❌ No | CTF, Regime, TOD, Kalman, HMM, BOCPD |
| I7 | 36 | ❌ No | TrendFollowing, MeanReversion, LiquiditySweep, CHoCH |

**Total:** 121 plugins + 2 aggregation (CISScorer, SignalAggregator)

## See Also

- `DAG_TOPOLOGY.md` — System-level DAG methodology and agent topology
- `plugin-native-architecture-explained.md` — Architectural principles
- `CURRENT_STATE.md` — Active agent inventory
