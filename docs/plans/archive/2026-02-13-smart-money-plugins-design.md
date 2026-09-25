# Smart Money Concepts — I5 Plugin Design

**Date:** 2026-02-13
**Status:** Approved
**Scope:** 4 plugins in `src/intelligence/smart_money/`

## Summary

Add 4 smart money concept plugins implementing ICT-style structural analysis: BOS/CHoCH (combined), Fair Value Gaps, Order Blocks, and Liquidity Sweeps. These extend I5 pattern detection with institutional price action concepts.

## Architecture Decisions

- **Directory:** `src/intelligence/smart_money/` (new, separate from statistical patterns)
- **Protocol:** Same `PatternPlugin` protocol, registered via `registry.register_pattern()`
- **Incremental:** `supports_incremental = False` (full recompute, same as I3/I4/I5)
- **Swing detection:** BOS/CHoCH and Liquidity Sweeps inline N-neighbor peak/trough detection (same algorithm as I3 swing detector, ~15 lines). This avoids cross-plugin coupling while staying conceptually aligned with I3.
- **FVG:** Fully self-contained on raw OHLCV
- **Order Blocks:** Reads raw OHLCV, uses inline swing detection for strength scoring
- **capability_tags:** `{"smart_money"}` for all 4

## Plugin Specifications

### 1. BOS/CHoCH (Break of Structure + Change of Character)

**File:** `src/intelligence/smart_money/bos_choch.py`

**Concept:** BOS = price closes beyond a swing high (bullish) or swing low (bearish). CHoCH = first BOS in the opposite direction of the prevailing trend, signaling potential reversal.

**Algorithm:**
1. Find all swing highs/lows via N-neighbor peak/trough detection (N=5)
2. Determine prevailing trend from the most recent 4+ swings (HH+HL = up, LH+LL = down)
3. Scan recent bars for closes beyond the most recent swing high or swing low
4. If break direction matches trend → BOS (trend continuation confirmed)
5. If break direction opposes trend → CHoCH (first sign of reversal)
6. Track the break level for downstream use

**Outputs:**
```python
outputs = frozenset({
    "bos_detected",       # 1.0 if BOS occurred in recent bars, else 0.0
    "bos_direction",      # +1.0 bullish, -1.0 bearish, 0.0 none
    "bos_level",          # Price level that was broken
    "choch_detected",     # 1.0 if this BOS is a CHoCH (trend reversal)
    "choch_direction",    # +1.0 bullish reversal, -1.0 bearish reversal, 0.0 none
    "trend_direction",    # Current prevailing trend: +1.0 up, -1.0 down, 0.0 neutral
})
```

**min_lookback:** 60 (needs enough bars for swing detection + trend determination)

### 2. Fair Value Gap (FVG)

**File:** `src/intelligence/smart_money/fair_value_gap.py`

**Concept:** A 3-candle imbalance where price moved so impulsively that a gap exists between bar1 and bar3 (bar2's body created the gap). These gaps tend to be "filled" as price retraces to them.

**Algorithm:**
1. Scan all 3-candle windows in the lookback period:
   - Bullish FVG: `bar3.low > bar1.high` (gap up, unfilled space below bar3)
   - Bearish FVG: `bar3.high < bar1.low` (gap down, unfilled space above bar3)
2. Track whether each FVG has been "filled" (price later retraced into the gap zone)
3. Output the most recent unfilled FVG and count of all open FVGs
4. FVG size (top - bottom) indicates strength of the imbalance

**Outputs:**
```python
outputs = frozenset({
    "fvg_type",           # +1.0 bullish, -1.0 bearish, 0.0 none
    "fvg_top",            # Upper boundary of most recent unfilled FVG
    "fvg_bottom",         # Lower boundary
    "fvg_midpoint",       # Midpoint (common retracement target)
    "fvg_size_pct",       # Gap size as % of price (strength measure)
    "fvg_open_count",     # Number of unfilled FVGs (imbalance pressure)
})
```

**min_lookback:** 30

### 3. Order Blocks

**File:** `src/intelligence/smart_money/order_blocks.py`

**Concept:** The last opposing candle before an impulsive move. Institutional orders are thought to cluster at these levels, making them strong S/R zones when price returns.

**Algorithm:**
1. Detect impulsive moves: 3+ consecutive same-direction candles with total move > 1.5x ATR
2. Walk backward from the impulse start to find the last opposing candle:
   - Bullish OB: last bearish candle (close < open) before a bullish impulse
   - Bearish OB: last bullish candle (close > open) before a bearish impulse
3. OB zone = that candle's [low, high] range
4. Strength scoring:
   - Volume of the impulse move relative to average
   - Whether the OB aligns with a swing level (inline detection)
   - Whether the OB has been tested (price returned to the zone)
5. Track whether the OB is "mitigated" (price traded through the zone, invalidating it)

**Outputs:**
```python
outputs = frozenset({
    "ob_type",            # +1.0 bullish, -1.0 bearish, 0.0 none
    "ob_top",             # Upper boundary of most recent unmitigated OB
    "ob_bottom",          # Lower boundary
    "ob_strength",        # 0-1 strength score (volume + swing alignment)
    "ob_mitigated",       # 1.0 if the OB has been traded through (invalidated)
    "ob_distance_pct",    # Distance from current price to OB as % (proximity)
})
```

**min_lookback:** 50

### 4. Liquidity Sweeps

**File:** `src/intelligence/smart_money/liquidity_sweeps.py`

**Concept:** Price briefly penetrates beyond a swing high/low (grabbing stop-loss liquidity) then reverses. A sweep below a swing low that closes back above it is a bullish signal (smart money bought the stops).

**Algorithm:**
1. Find all swing highs/lows via N-neighbor peak/trough detection
2. For each recent bar, check for wicks beyond swing levels:
   - Bullish sweep: `bar.low < swing_low` AND `bar.close > swing_low`
   - Bearish sweep: `bar.high > swing_high` AND `bar.close < swing_high`
3. "Reclaimed" = confirmed if the next 1-3 bars continue moving away from the swept level
4. Sweep depth = how far price penetrated beyond the level (deeper = more liquidity grabbed)

**Outputs:**
```python
outputs = frozenset({
    "sweep_detected",     # 1.0 if sweep occurred in recent bars
    "sweep_type",         # +1.0 bullish (swept lows), -1.0 bearish (swept highs)
    "sweep_level",        # The swing level that was swept
    "sweep_depth_pct",    # How far price penetrated beyond the level as %
    "sweep_reclaimed",    # 1.0 if confirmed (price moved away from swept level)
})
```

**min_lookback:** 60

## Data Flow

```
OHLCV ──> Inline swing detection ──┬──> BOS/CHoCH
     │    (shared algorithm,       ├──> Order Blocks (+ impulse detection)
     │     not shared code)        └──> Liquidity Sweeps
     └──> FVG (3-candle scan, independent)
```

## Registration

In `src/intelligence/register_plugins.py`:
```python
from .smart_money.bos_choch import plugin as bos_choch_plugin
from .smart_money.fair_value_gap import plugin as fvg_plugin
from .smart_money.order_blocks import plugin as ob_plugin
from .smart_money.liquidity_sweeps import plugin as liq_sweep_plugin

# Inside register_all_plugins():
    registry.register_pattern(bos_choch_plugin)
    registry.register_pattern(fvg_plugin)
    registry.register_pattern(ob_plugin)
    registry.register_pattern(liq_sweep_plugin)
```

**New totals:** 16 indicators + 14 patterns = **30 total plugins**

## Testing Strategy

Test file: `tests/unit/intelligence/test_smart_money_plugins.py`

Each plugin gets:
1. **Output validation** — correct keys, correct value ranges
2. **Known-pattern detection** — synthetic OHLCV data with deliberate BOS/FVG/OB/sweep patterns
3. **Empty/insufficient input** — returns `{}`
4. **No false positives** — flat/trending data without the pattern should return 0.0/none

Estimated: ~16-20 tests across 4 plugins.

## Shared Utility

A small `_swing_utils.py` in the smart_money directory with the inline peak/trough functions to avoid copy-pasting between BOS/CHoCH and Liquidity Sweeps:

```python
# src/intelligence/smart_money/_swing_utils.py
def find_peaks(data: np.ndarray, n: int) -> list[int]: ...
def find_troughs(data: np.ndarray, n: int) -> list[int]: ...
```

This is a private module (underscore prefix), not a plugin. Same algorithm as I3 swing detector.
