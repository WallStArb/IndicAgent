# I7 Emission Gates - Signal Quality Enforcement

**Version:** 2.8
**Status:** stale (v2.x, see banner)
**Last Updated:** 2026-05-26

> **Staleness note (2026-08-01):** This doc describes emission gates in
> `src/intelligence/trading/signal_schema.py` enforced on I7 trading signals — the ARCHIVED
> v2.x signal system, with no live consumer as of 2026-07-02 per CLAUDE.md. Not yet rewritten
> for v3.0 -- tracked for a future doc pass, not fixed here.

## Purpose

Emission gates in `src/intelligence/trading/signal_schema.py` enforce structural validity on all I7 trading signals before publication. This prevents invalid signals from reaching the ledger and downstream systems.

## Gate Rules

### Gate 1: Stop Distance (W4)
**Location:** `signal_schema.py:176-179`

```python
if stop_distance < tick:
    raise ValueError(
        f"Emission gate: stop ({stop}) is within 1 tick ({tick}) of entry ({entry})"
    )
```

**Purpose:** Reject signals where stop loss is too tight (less than 1 tick from entry).
**Rationale:** Stops tighter than 1 tick are structurally invalid - market cannot execute at that granularity.

### Gate 2: Stop Type Identification (W4)
**Location:** `signal_schema.py:182-183`

```python
if tf.stop_type == "unknown":
    raise ValueError("Emission gate: stop_type is 'unknown' — structural stop basis required")
```

**Purpose:** Require explicit stop type (atr, swing, structural, etc.).
**Rationale:** Unknown stop types indicate incomplete signal construction.

### Gate 3: Risk/Reward Ratio (W4)
**Location:** `signal_schema.py:186-193`

```python
reward = abs(target_prices[0] - entry)
rr_t1_actual = reward / stop_distance if stop_distance > 0 else 0
if rr_t1_actual < MIN_RR_T1:
    raise ValueError(
        f"Emission gate: RR to T1 ({rr_t1_actual:.2f}) below minimum ({MIN_RR_T1})"
    )
```

**Purpose:** Enforce minimum risk/reward ratio to first target.
**Rationale:** Protect against negative-expected-value setups.

## I7 Plugin Requirements

When authoring I7 plugins, ensure:

1. **Stop price respects tick size:**
   ```python
   tick = TICK_SIZES.get(symbol, 0.01)
   stop = entry +/- (atr * stop_multiple)
   stop = round(stop / tick) * tick  # Align to tick
   if abs(stop - entry) < tick:
       stop = entry +/- (2 * tick)  # Minimum 2-tick distance
   ```

2. **Stop type is always identified:**
   ```python
   stop_type = "atr"  # or "swing", "structural", "vwap", etc.
   ```

3. **Risk/reward meets minimum:**
   ```python
   MIN_RR_T1 = 1.5  # Per src/intelligence/trading/signal_schema.py
   reward = abs(target_1 - entry)
   risk = abs(entry - stop)
   if reward / risk < MIN_RR_T1:
       return no_signal()  # Skip this setup
   ```

## Monitoring

Emission gate rejections are logged as warnings:
```
Emission gate: stop (159.19) is within 1 tick (0.001) of entry (159.1895)
```

**Frequency:** Occasional rejections are expected (quality control).
**Action required:** If rejections exceed 10% of signals, review I7 plugin logic.

## Example Fix for Tight Stops

**Problem:** `FailedBreakout` plugin generates sub-tick stops for low-priced symbols.

**Solution:** Add tick-size awareness:
```python
def _compute_stop(self, entry: float, atr: float, symbol: str) -> float:
    tick = TICK_SIZES.get(symbol, 0.01)
    stop_distance = atr * 1.5  # 1.5x ATR stop

    # Align to tick grid
    stop = entry - stop_distance
    stop = round(stop / tick) * tick

    # Enforce minimum 2-tick distance
    if abs(entry - stop) < (2 * tick):
        stop = entry - (2 * tick)

    return stop
```

## Related Files

- `src/intelligence/trading/signal_schema.py` - Gate implementations
- `src/intelligence/trading/signal_schema.py:TICK_SIZES` - Tick size registry
- `src/intelligence/trading/orb30.py` - Example with session_date state (Issue #1)
