# Stop/Target Hardening — Adaptive Buffer + Institutional Levels + T1 Trail

## Status: APPROVED FOR PLANNING

## Problem

Three independent gaps in `trade_framer.py` and `lifecycle_tracker.py`:

1. **Discrete GARCH scaling:** `_garch_atr_multiplier()` maps vol regime (0/1/2) to {0.80, 1.00, 1.35}. The discrete cliff between regime 1 → 2 means a bar with `garch_vol_ratio=1.49` gets the same stop buffer as a quiet bar. Regime classification always lags realized volatility.

2. **Missing institutional targets:** Weekly pivots (R1/R2/S1/S2), Fibonacci clusters, Asian session H/L, and AVWAP bands are fully computed in I3/I4 but absent from `_collect_targets_long/short`. These are exactly the levels institutional desks defend.

3. **Static stops after T1:** Once a signal reaches T1, the original stop_loss remains. A profitable trade that has cleared T1 gives back more than necessary on reversal. No breakeven progression exists.

---

## Design

### Change 1 — Continuous adaptive buffer (trade_framer.py)

**Replace** `_garch_atr_multiplier(features)` (returns discrete float) **with** `_adaptive_buffer(features, base_mult)` (returns scaled float).

```python
def _adaptive_buffer(features: dict, base_mult: float) -> float:
    """Single continuous GARCH signal. No regime double-counting."""
    vol_ratio = float(features.get("garch_vol_ratio") or 1.0)
    vol_ratio = max(0.70, min(1.50, vol_ratio))

    # Piecewise linear through existing regime anchors:
    # vol_ratio=0.70 → ×0.80, vol_ratio=1.00 → ×1.00, vol_ratio=1.50 → ×1.35
    if vol_ratio <= 1.0:
        mult = 0.80 + (vol_ratio - 0.70) * (0.20 / 0.30)
    else:
        mult = 1.00 + (vol_ratio - 1.00) * (0.35 / 0.50)

    result = base_mult * mult

    # Extreme event floor: shock > 3σ² → never tighter than regime-2 anchor
    shock = float(features.get("garch_shock") or 0.0)
    if shock > 3.0:
        result = max(result, base_mult * 1.35)

    return result
```

**Rationale for design choices:**
- `garch_vol_ratio` is the continuous signal that was already being discretized into regime classes. Using it directly eliminates double-counting.
- Clip [0.70, 1.50]: prevents extreme ratio values from producing nonsensical buffers. 0.70 floor preserves the regime-0 minimum; 1.50 cap preserves the regime-2 maximum.
- Piecewise linear through anchors: calibrated behavior at the three reference points is preserved — only the transitions between them become smooth. No behavior change at quiet/normal/high vol anchors.
- `garch_shock` floor: GARCH regime classification reacts to *sustained* vol changes. A single shock bar (squared return > 3σ²) can be regime-1 classified but genuinely extreme. The floor ensures the buffer never under-prices extreme-event risk regardless of classification.

**Callers to update:** Every hardcoded ATR buffer literal in `_resolve_stop_long` / `_resolve_stop_short` / `_collect_targets_long` / `_collect_targets_short` that currently multiplies by a constant (0.20, 0.25, 0.30, 0.50, 2.0) should instead call `_adaptive_buffer(features, that_constant)`.

The old `_garch_atr_multiplier()` is deleted. Its only caller was in the stop resolution methods, now replaced.

**Fallback:** If `garch_vol_ratio` is None/missing (GARCH hasn't warmed up), `vol_ratio` defaults to 1.0 → `mult = 1.00` → no scaling. Identical to current regime-1 behavior. No change in behavior during warmup.

---

### Change 2 — Institutional target candidates (trade_framer.py)

Add four new candidate types to `_collect_targets_long()` and `_collect_targets_short()`. All candidates pass through the existing ATR range filter (`entry + ATR×0.5 < candidate < entry + ATR×max_mult`), which prevents absurdly distant levels from being selected. No changes to `_pick_targets()` or RR thresholds.

**Weekly pivots:**
```python
# Long targets
for field in ("weekly_r1", "weekly_r2"):
    lvl = features.get(field)
    if lvl and lvl > entry:
        candidates.append(lvl)

# Short targets
for field in ("weekly_s1", "weekly_s2"):
    lvl = features.get(field)
    if lvl and lvl < entry:
        candidates.append(lvl)
```
No additional gate. Weekly pivots are always structurally valid. ATR range filter prevents S1 from appearing as a T3 target on a small daily range.

**Fibonacci cluster:**
```python
fib_lvl = features.get("nearest_fib_level")
fib_strength = float(features.get("fib_cluster_strength") or 0.0)
if fib_lvl and fib_strength >= 0.5:
    if direction == 1 and fib_lvl > entry:
        candidates.append(fib_lvl)
    elif direction == -1 and fib_lvl < entry:
        candidates.append(fib_lvl)
```
`fib_cluster_strength >= 0.5` gate: a lone Fibonacci level is noise; a cluster (multiple levels coinciding) is signal. The 0.5 threshold selects the top half of cluster quality. `nearest_fib_level` is already the closest to price, so no directional search needed.

**Asian session H/L:**
```python
# Long: asian_session_high as resistance target
asian_h = features.get("asian_session_high")
if asian_h and direction == 1 and asian_h > entry:
    candidates.append(asian_h)

# Short: asian_session_low as support target
asian_l = features.get("asian_session_low")
if asian_l and direction == -1 and asian_l < entry:
    candidates.append(asian_l)
```
Key NY-session reference points. ATR range filter is the only gate required.

**AVWAP bands:**
```python
# Long: avwap_upper_band
avwap_upper = features.get("avwap_upper_band")
if avwap_upper and direction == 1 and avwap_upper > entry:
    candidates.append(avwap_upper)

# Short: avwap_lower_band
avwap_lower = features.get("avwap_lower_band")
if avwap_lower and direction == -1 and avwap_lower < entry:
    candidates.append(avwap_lower)
```
Structurally equivalent to VWAP bands (already included). AVWAP bands are in I4 but currently absent from the candidate list — a clear omission.

---

### Change 3 — Post-T1 breakeven trail (lifecycle_tracker.py)

**Principle:** `stop_loss` is never modified after emission. It is the signal's permanent risk anchor and structural record. The trail is a forward-looking overlay stored in `chandelier_state` alongside the existing Chandelier trail — two independent exit paths.

**State extension in `chandelier_state`:**
```python
# Added fields (alongside existing 'trailing_stop' and 'highest_high'/'lowest_low'):
"t1_hit_bar": int | None    # bar index when T1 was first confirmed
"breakeven_stop": float | None  # None → entry_price (at T1) → target_1 (at T2)
```

**Progression logic in `evaluate_signal()`:**
```python
breakeven_stop = chandelier_state.get("breakeven_stop")
t1_hit_bar = chandelier_state.get("t1_hit_bar")

# T1 confirmed: advance stop to entry
if t1_hit and t1_hit_bar is None:
    chandelier_state["t1_hit_bar"] = current_bar
    chandelier_state["breakeven_stop"] = entry_price

# T2 confirmed: advance stop to T1 level
if t2_hit and t1_hit_bar is not None:
    chandelier_state["breakeven_stop"] = target_1

# Apply: effective stop is the more protective of original and trail
if breakeven_stop is not None:
    if direction == 1:
        effective_stop = max(stop_loss, breakeven_stop)
    else:
        effective_stop = min(stop_loss, breakeven_stop)
else:
    effective_stop = stop_loss
```

`t1_hit` and `t2_hit` are detected identically to how the existing lifecycle detects target hits (low ≤ target_1 for longs, high ≥ target_1 for shorts) — no new detection logic, just new state transitions.

Exit recorded as `exit_reason="breakeven_stop"` when the trail triggers. This is a new exit reason added to the 8-class taxonomy (→ 9-class, later 10 if T2-trail also needs its own class — keep as one class for now since both are breakeven progressions).

**What does NOT change:**
- `stop_loss` field value — immutable after emission
- Chandelier computation — runs independently
- MAE/MFE tracking — unaffected
- `signal_ledger` schema — `breakeven_stop` is transient state, not persisted; only the exit outcome is written

---

## Files to change

```
src/intelligence/trading/trade_framer.py
  - Delete _garch_atr_multiplier()
  - Add _adaptive_buffer(features, base_mult) → float
  - Update all ATR buffer literals in _resolve_stop_long/short, _collect_targets_long/short
  - Add weekly pivot, Fibonacci, Asian H/L, AVWAP candidate collection

src/intelligence/trading/lifecycle_tracker.py
  - Extend chandelier_state with t1_hit_bar, breakeven_stop fields
  - Add breakeven progression logic in evaluate_signal()
  - Add "breakeven_stop" to exit_reason vocabulary
```

No schema changes. No new files. No new abstraction boundaries.

---

## Verification

```bash
# 1. No remaining calls to _garch_atr_multiplier
grep -rn "_garch_atr_multiplier" src/ --include="*.py"  # → 0 results

# 2. All ATR buffer calls route through _adaptive_buffer
grep -rn "atr \* 0\." src/intelligence/trading/trade_framer.py  # → 0 results

# 3. New target fields referenced
grep -n "weekly_r1\|nearest_fib_level\|asian_session_high\|avwap_upper_band" \
  src/intelligence/trading/trade_framer.py  # → hits in _collect_targets

# 4. breakeven_stop state present
grep -n "breakeven_stop" src/intelligence/trading/lifecycle_tracker.py  # → hits

# 5. Tests green
pytest tests/unit/ -q
```

---

## What this is NOT

- Not a change to ATR calculation — Wilder's 14-period is correct
- Not a change to the structural stop hierarchy (FVG → demand → sweep → OB → swing → EMA → S/R → fallback)
- Not a new module or abstraction — both changes live in their existing files
- Not a behavior change at the three GARCH anchor points (0.70/1.00/1.50 vol_ratio) — calibration preserved
- Not a `signal_ledger` schema migration
