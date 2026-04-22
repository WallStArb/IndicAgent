# Incremental Computation

**Last Updated:** 2026-04-22

## The Problem with Full Recomputation

Most technical indicators are defined as functions over a trailing window of bars. Naively, every new bar triggers a full recompute over the entire history:

```
New bar arrives → recompute RSI over last 14 bars → recompute MACD over last 26 bars → ...
```

With 27 indicators, 55+ contracts, and 4 timeframes, that's 27 × 55 × 4 = ~5,940 full recomputations per bar. Each one reprocesses data that hasn't changed. At scale, this creates a processing backlog that grows faster than bars arrive.

---

## The Solution: Stateful Incremental Updates

All I1 plugins implement **`compute_next()`** — a single-bar update that uses cached state from the previous bar instead of reprocessing history.

```python
# First call: full batch over historical data (seeds state)
plugin.compute_full({"main": historical_df})

# Every subsequent call: O(1) single-bar update
result = plugin.compute_next({"main": df_with_new_bar})
```

The state is a small dictionary — typically a few floats — stored per plugin per symbol per timeframe. No dataframe re-allocation, no rolling window scan.

**Measured speedup: 141× faster than full recomputation.**

---

## State Patterns by Indicator Type

Different indicators use different incremental strategies:

### EMA / MACD
State: previous EMA value + smoothing factor (α)
```
new_ema = α × new_close + (1 - α) × prev_ema
```
One multiply, one add. No window.

### RSI / ATR (Wilder's Smoothing)
State: previous smoothed gain, previous smoothed loss (RSI); previous TR average (ATR)
```
smoothed_gain = ((N-1) × prev_gain + new_gain) / N
```
Wilder's formula is equivalent to EMA with `α = 1/N`. State is two floats.

### Bollinger Bands (Welford's Algorithm)
State: running count, running mean, running M2 (sum of squared deviations)
```
delta = new_value - mean
mean += delta / count
M2 += delta × (new_value - mean)
variance = M2 / (count - 1)
```
Online variance with no accumulated floating point error. State is three floats.

### Stochastic / Williams %R / Donchian Channels
State: rolling deque of closes (or high/low) with fixed `maxlen`
```
deque.append(new_close)      # O(1) — deque auto-evicts oldest
high_n = max(deque)          # O(N) but N is small (14-20 bars)
```
The deque replaces the window scan. Max/min over a fixed small window is fast.

### OBV / VWAP
State: running cumulative sum
```
obv = prev_obv + (volume if close > prev_close else -volume)
```
Single addition. The running sum is the state.

### ADX / DMI
State: three Wilder-smoothed values (+DM, -DM, TR) plus the ADX smoothing
```
smoothed_TR = prev_TR - (prev_TR / N) + new_TR
smoothed_pDM = prev_pDM - (prev_pDM / N) + new_pDM
ADX = ((N-1) × prev_ADX + new_DX) / N
```
Four state values, four Wilder updates per bar.

### CCI / MFI
State: rolling deque of typical prices (or money flow values)
```
typical_price = (high + low + close) / 3
deque.append(typical_price)
mean_deviation = mean(|x - mean(deque)| for x in deque)
CCI = (typical_price - mean(deque)) / (0.015 × mean_deviation)
```
Deque replaces rolling window. Mean deviation is O(N) over a fixed small window.

---

## State Lifecycle

State is managed by the service, not the plugin. This separation allows:
- The same plugin class to serve multiple (symbol, timeframe) pairs simultaneously
- State to be swapped in/out per bar without object re-creation

```python
# market_analysis_service.py (simplified)
state_key = (plugin.name, symbol, timeframe)

plugin._state = self._plugin_states[state_key]   # load state
result = plugin.compute_full(frames)              # or compute_next
self._plugin_states[state_key] = plugin._state   # write back
```

The write-back is load-bearing for plugins like GARCH and HMM that fully reassign `_state` internally (rather than mutating it in place).

---

## Fallback Behavior

If `_state` is empty (first bar after a restart, or state was evicted), `compute_next()` calls `compute_full()` as a fallback. After `compute_full()` seeds the state, subsequent bars use the incremental path.

```python
def compute_next(self, windows):
    if not self._state:
        return self.compute_full(windows)  # seeds state as a side effect
    # ... fast incremental path ...
```

---

## Plugins That Don't Use Incremental Computation

I3 (structure), I4 (regime), and I5 (pattern) plugins set `supports_incremental = False`. These plugins require a multi-bar window for correctness. I2 (composite/event) plugins also set `supports_incremental = False` — they detect state transitions across recent bars, which requires the full recent window.

- **SwingDetector** — needs to look back N bars to confirm swing points
- **GARCHVolatility** — fits a parametric model over a window; can't update with a single bar
- **HMMRegime** — Baum-Welch/Viterbi over the full observation sequence
- **Pattern plugins** — chart patterns are multi-bar by definition

These run `compute_full()` every bar. Their window size is small enough that this is acceptable, but they do not get the 141× speedup.

---

## Related Documentation

- [Plugin Architecture](plugin-architecture.md) — plugin protocol, `compute_full` / `compute_next` signatures
- [DAG Execution](dag-execution.md) — how plugin execution is ordered across tiers
- **Code:** `src/intelligence/indicators/` — every I1 plugin implements `compute_next()`
- **Tests:** `tests/unit/intelligence/test_plugin_incremental.py` — verifies parity between full and incremental paths
