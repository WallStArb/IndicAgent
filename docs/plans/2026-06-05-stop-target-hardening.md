# Stop/Target Hardening — Adaptive Buffer + Institutional Levels + T1 Trail

## Status: APPROVED FOR PLANNING

## Problem

Three independent gaps in `trade_framer.py` and `lifecycle_tracker.py`:

1. **Discrete GARCH scaling:** The `effective_atr` block in `frame_trade()` maps `garch_vol_regime` (0/1/2) to `GARCH_MULTIPLIERS` {0.80, 1.00, 1.35}. The discrete cliff between regime 1 → 2 means a bar with `garch_vol_ratio=1.49` gets the same stop buffer as a quiet bar. Regime classification always lags realized volatility. GARCH shock — a single extreme bar that regime classification misses — is also ignored. A quiet trending day and a volatile chaotic day get the same buffer geometry.

2. **Missing institutional targets:** Weekly pivots (R1/R2/S1/S2), Fibonacci clusters, Asian session H/L, and AVWAP bands are fully computed in I3/I4 but absent from `_collect_targets_long/short`. These are exactly the levels institutional desks defend.

3. **Static stops after T1:** Once a signal reaches T1, the original stop_loss remains. A profitable trade that has cleared T1 gives back more than necessary on reversal. No breakeven progression exists.

---

## Design

### Change 1 — Adaptive buffer: GARCH-continuous + regime-confirmed Hurst tightening (trade_framer.py)

**Replace** the `effective_atr` pre-computation block and `GARCH_MULTIPLIERS` dict in `frame_trade()` **with** `_adaptive_buffer(features, base_mult, regime_type)` called inline at each buffer site.

The current code (lines 878-883 of `trade_framer.py`) computes a single `effective_atr` from discrete `garch_vol_regime` and passes it to all stop/target functions. After this change, each buffer site calls `atr * _adaptive_buffer(features, constant, regime_type)` using the raw `atr`.

**Signal selection rationale:** The buffer formula answers one question — *how volatile is the instrument right now, and is this bar an outlier?* GARCH answers that directly. Hurst is already encoded upstream in the regime gate: it determines which setups fire. Adding Hurst as a general multiplier would double-count the signal. Its one valid role is **confirmation tightening**: when Hurst aligns with the signal's expected regime type, structural levels are more reliable, so the buffer can narrow. Shannon entropy is excluded entirely — it is structurally redundant with GARCH volatility for this purpose.

```python
# New constant
ADAPTIVE_BUFFER_HARD_CAP = 1.40  # maximum multiplier — single-signal cap; no multi-factor expansion

def _adaptive_buffer(features: dict, base_mult: float, regime_type: str | None = None) -> float:
    """GARCH-continuous buffer with Hurst regime-confirmation tightening.

    regime_type: the calling plugin's regime_type class attribute
        ("trend" | "mean_reversion" | "any"). None → no Hurst adjustment.
    """
    # Primary: continuous GARCH vol ratio
    vol_ratio = float(features.get("garch_vol_ratio") or 1.0)
    vol_ratio = max(0.70, min(1.50, vol_ratio))

    # Piecewise linear through existing regime anchors:
    # vol_ratio=0.70 → ×0.80, vol_ratio=1.00 → ×1.00, vol_ratio=1.50 → ×1.35
    if vol_ratio <= 1.0:
        garch_mult = 0.80 + (vol_ratio - 0.70) * (0.20 / 0.30)
    else:
        garch_mult = 1.00 + (vol_ratio - 1.00) * (0.35 / 0.50)

    result = base_mult * garch_mult

    # Hurst regime-confirmation tightening (only — never widens).
    # When Hurst confirms the signal's expected regime, structural levels are more
    # reliable and the buffer can narrow by up to 8%.
    # Conflict (trend signal in low-Hurst market, or vice versa): no adjustment.
    # "any" regime_type: no adjustment (signal is regime-agnostic).
    hurst = features.get("hurst_exponent")
    if hurst is not None and regime_type in ("trend", "mean_reversion"):
        h = float(hurst)
        if regime_type == "trend" and h >= 0.55:
            result *= 1.0 - (h - 0.55) * 0.16  # max tighten: 0.08× at H=1.0
        elif regime_type == "mean_reversion" and h <= 0.45:
            result *= 1.0 - (0.45 - h) * 0.16  # max tighten: 0.08× at H=0.0

    # Extreme event floor: single shock bar (garch_shock > 3σ²) → never tighter than
    # regime-2 anchor. Handles cases where sustained regime is low but this bar is extreme.
    if float(features.get("garch_shock") or 0.0) > 3.0:
        result = max(result, base_mult * 1.35)

    # Hard cap: vol-driven expansion is bounded.
    return min(result, base_mult * ADAPTIVE_BUFFER_HARD_CAP)
```

**Rationale for design choices:**
- `garch_vol_ratio` continuous: replaces discrete regime cliff. Piecewise linear through the three regime anchors preserves calibrated behavior at those points — only the transitions become smooth.
- Clip [0.70, 1.50]: prevents extreme ratio values from producing nonsensical buffers.
- Hurst tightens only, never widens: Hurst is already upstream in the regime gate. A trend signal that fires has already passed a regime filter. Adding a widening Hurst component would double-count. The confirmation tightening is the only non-redundant use: a trend signal firing in a confirmed trending market (H≥0.55) can afford a tighter stop because the structural levels are more robust. ±8% maximum is intentionally small.
- Hurst conflict = no adjustment: if a trend signal fires in a low-Hurst environment (regime gate passed but Hurst is mean-reverting), the GARCH buffer is already applying the correct vol-based sizing. Widening further would be double-penalizing.
- `garch_shock` floor: regime classification reacts to *sustained* vol changes. A single shock bar can be regime-1 classified but genuinely extreme. The floor ensures the buffer never under-prices extreme-event risk.
- `ADAPTIVE_BUFFER_HARD_CAP = 1.40`: tighter than the multi-factor version — with only GARCH driving expansion (Hurst only tightens), the maximum needed is vol-ratio=1.50 → garch_mult=1.35, rounded up for headroom. 1.60 was sized for three multiplicative factors; with one it's too wide.
- Shannon entropy excluded: structurally redundant with GARCH volatility for buffer sizing. Medallion's edge came from using the right signals without redundancy.
- `kalman_uncertainty` (P_est) deferred: covariance value in price-units-squared, no natural bound. Add as a shock-floor guard once normalized by `atr²` and distribution studied.

**Callers to update:** Every hardcoded ATR buffer literal in `_resolve_stop_long` / `_resolve_stop_short` / `_collect_targets_long` / `_collect_targets_short` that currently multiplies by a constant (0.20, 0.25, 0.30, 0.50, 2.0) becomes `atr * _adaptive_buffer(features, that_constant, regime_type)`. The `min_level` / `max_level` range bounds in `_collect_targets_long/short` are similarly updated so the valid target window scales with volatility regime.

`regime_type` flows from `frame_trade()`'s caller (the I7 plugin) via a new parameter: `frame_trade(..., regime_type: str | None = None)`. All existing callers pass `None` unless they set it — no breakage.

**Removal:** Delete `GARCH_MULTIPLIERS` dict (lines 98-101) and the `effective_atr` pre-computation block (lines 878-883 of `frame_trade()`). All four stop/target functions revert to receiving raw `atr` from `frame_trade()`.

**`_classify_stop_basis()` update:** This function takes `effective_atr` to classify stops into `structure_snap` vs `garch_adaptive`. After removing the pre-computed `effective_atr`, the call in `frame_trade()` (line 975) must pass `atr * _adaptive_buffer(features, 1.0, regime_type)` as a representative scaled ATR for classification. No change to the function's interface or logic.

**Fallback:** If `garch_vol_ratio` is None/missing (GARCH hasn't warmed up), `vol_ratio` defaults to 1.0 → `garch_mult = 1.00` → result = `base_mult`. Identical to current regime-1 behavior. No change in behavior during warmup.

---

### Change 2 — Unify target collection + institutional candidates (trade_framer.py)

**Prerequisite refactor:** `_collect_targets_long` and `_collect_targets_short` are ~110 lines each with ~80% structural duplication. Every new target type requires symmetric additions in both functions — a maintenance hazard that compounds with every future institutional level added. Replace both with a single unified function before adding the new types:

```python
def _collect_target_candidates(
    entry: float, stop: float, direction: int,
    atr: float, features: dict[str, Any]
) -> list[TradeTarget]:
```

Field selection is direction-aware inline: `"nearest_resistance" if direction == 1 else "nearest_support"` etc. The return type, VP priority path, ATR range filter, and sort logic are identical — they move to the unified function unchanged. `_collect_targets_long` and `_collect_targets_short` are deleted.

`_resolve_stop_long` and `_resolve_stop_short` are NOT unified — stop resolution has genuine directional asymmetry (demand zone vs supply zone, different field names and semantics) and changes rarely. Correctness risk outweighs duplication cost.

**New candidate types** (all added to the unified function). All pass through the existing ATR range filter (`entry + ATR×0.5 < candidate < entry + ATR×max_mult`). No changes to `_pick_targets()` or RR thresholds.

**Weekly pivots:**
```python
# Long targets
for field in ("weekly_r1", "weekly_r2"):
    lvl = features.get(field)
    if lvl and lvl > entry:
        candidates.append((lvl, f"Weekly {field.upper()} {lvl:.2f}", "weekly_pivot"))

# Short targets
for field in ("weekly_s1", "weekly_s2"):
    lvl = features.get(field)
    if lvl and lvl < entry:
        candidates.append((lvl, f"Weekly {field.upper()} {lvl:.2f}", "weekly_pivot"))
```
No additional gate. Weekly pivots are always structurally valid. ATR range filter prevents S1 from appearing as a T3 target on a small daily range.

**Fibonacci cluster:**
```python
fib_lvl = features.get("nearest_fib_level")
fib_strength = float(features.get("fib_cluster_strength") or 0.0)
if fib_lvl is not None and fib_lvl > EPSILON_TOLERANCE and fib_strength >= 0.5:
    if direction == 1 and fib_lvl > entry:
        candidates.append((fib_lvl, f"Fib cluster {fib_lvl:.2f}", "fib"))
    elif direction == -1 and fib_lvl < entry:
        candidates.append((fib_lvl, f"Fib cluster {fib_lvl:.2f}", "fib"))
```
`fib_cluster_strength >= 0.5` gate: a lone Fibonacci level is noise; a cluster (multiple levels coinciding) is signal. `EPSILON_TOLERANCE` guard is consistent with all other candidates in the function. `nearest_fib_level` is already the closest to price, so no directional search needed.

**Asian session H/L:**
```python
asian_h = features.get("asian_session_high")
if asian_h and direction == 1 and asian_h > entry:
    candidates.append((asian_h, f"Asian H {asian_h:.2f}", "asian_session"))

asian_l = features.get("asian_session_low")
if asian_l and direction == -1 and asian_l < entry:
    candidates.append((asian_l, f"Asian L {asian_l:.2f}", "asian_session"))
```
Key NY-session reference points. ATR range filter is the only gate required.

**AVWAP bands:**
```python
avwap_upper = features.get("avwap_upper_band")
if avwap_upper and direction == 1 and avwap_upper > entry:
    candidates.append((avwap_upper, f"AVWAP upper {avwap_upper:.2f}", "avwap"))

avwap_lower = features.get("avwap_lower_band")
if avwap_lower and direction == -1 and avwap_lower < entry:
    candidates.append((avwap_lower, f"AVWAP lower {avwap_lower:.2f}", "avwap"))
```
Structurally equivalent to VWAP bands (already included). AVWAP bands are in I4 but currently absent from the candidate list — a clear omission.

---

### Change 3 — Post-T1 chandelier floor (lifecycle_tracker.py)

**Approach:** Rather than a parallel exit path, the T1/T2 progression is implemented as a moving floor constraint on the existing chandelier stop. After T1, the chandelier is clamped so it can never trail below entry. After T2, clamped so it can never trail below T1 price. The chandelier still exits the trade — exit reason stays `"chandelier_stop"` throughout.

This eliminates the ordering problem (no competing exit paths), the same-bar ambiguity (chandelier check is unchanged), and the state complexity (one field instead of two).

**Architectural prerequisite:** The current exit model in `_check_active_exit()` fully closes a signal when T1 is hit (`exit_reason = "target_1"`). Change 3 requires modifying this: **T1 hit advances the chandelier floor and continues the trade; only T2, T3, chandelier, staleness, or TTL trigger a full exit.**

This means `_check_active_exit()` must not return a Transition on T1 detection — it instead updates `chandelier_state` and returns None. Only the two higher targets (T2, T3) produce a target-based full exit.

**Principle:** `stop_loss` is never modified after emission. The floor is a forward-looking constraint stored in `chandelier_state` — a clamp on the existing trail, not a new mechanism.

**Exit model change in `_check_active_exit()`:**
```python
# Target checks — T1 advances chandelier floor (does NOT exit); T2+ exits
for i in range(len(targets) - 1, -1, -1):
    target = targets[i]
    hit = (direction == 1 and high >= target) or (direction == -1 and low <= target)
    if hit:
        if i == 0:
            # T1 hit: advance floor, continue trade
            # (chandelier_state mutation handled in evaluate_signal before this call)
            break
        return _make_exit(
            sid, f"target_{i + 1}_hit", f"target_{i + 1}",
            target, entry, direction, risk, point_value,
            current_mae, current_mfe, target_index=i,
        )
```

**State extension in `chandelier_state`:**
```python
# One new field (alongside existing 'trailing_stop', 'highest_high', 'lowest_low'):
"be_floor": float | None  # None → entry_price (at T1) → target_1 (at T2)
```

**Floor advancement logic in `evaluate_signal()` — runs before the chandelier check:**
```python
if chandelier_state is not None:
    target_1 = targets[0] if targets else None
    target_2 = targets[1] if len(targets) > 1 else None

    t1_hit = target_1 is not None and (
        (direction == 1 and high >= target_1) or (direction == -1 and low <= target_1)
    )
    t2_hit = target_2 is not None and (
        (direction == 1 and high >= target_2) or (direction == -1 and low <= target_2)
    )

    if t1_hit and chandelier_state.get("be_floor") is None:
        chandelier_state["be_floor"] = entry

    if t2_hit and chandelier_state.get("be_floor") is not None:
        chandelier_state["be_floor"] = target_1
```

**Chandelier check update — apply floor clamp before comparing to price:**
```python
trailing_stop = chandelier_state.get("trailing_stop")
be_floor = chandelier_state.get("be_floor")
if trailing_stop is not None:
    if be_floor is not None:
        # Clamp: chandelier can never trail past the floor
        if direction == 1:
            trailing_stop = max(trailing_stop, be_floor)
        else:
            trailing_stop = min(trailing_stop, be_floor)
    chandelier_hit = (direction == 1 and low <= trailing_stop) or (
        direction == -1 and high >= trailing_stop
    )
    if chandelier_hit:
        # exit as chandelier_stop — exit payload includes be_floor for analytics
        ...
```

**Analytics:** Add `"be_floor_active": be_floor is not None` to the chandelier exit log payload. This preserves observability (how often the floor vs. the natural trail was binding) without a separate exit reason.

**Ordering in `evaluate_signal()`:**
1. Zone activation check (PENDING only) — unchanged
2. Floor advancement (T1/T2 detection) — new, before chandelier check
3. `_check_active_exit` (stop loss + T2/T3 targets) — T1 no longer exits here
4. Chandelier trailing stop with floor clamp — modified
5. Staleness condition_expired — unchanged
6. TTL expiry — unchanged

**What does NOT change:**
- `stop_loss` field value — immutable after emission
- Chandelier H/L ratchet computation — unchanged
- Exit reason vocabulary — `"chandelier_stop"` remains the sole chandelier exit reason
- MAE/MFE tracking — unaffected
- `signal_ledger` schema — `be_floor` is transient state, not persisted; only exit outcome is written
- T2/T3 target exits — unchanged behavior

---

## Files to change

```
src/intelligence/trading/trade_framer.py
  - Delete GARCH_MULTIPLIERS dict
  - Delete effective_atr pre-computation block in frame_trade()
  - Add ADAPTIVE_BUFFER_HARD_CAP constant
  - Add _adaptive_buffer(features, base_mult, regime_type=None) → float
  - Add regime_type: str | None = None parameter to frame_trade()
  - Update all ATR buffer literals in _resolve_stop_long/short and the unified target function
    (including min_level/max_level range bounds) to call _adaptive_buffer(..., regime_type)
  - Update _classify_stop_basis() call: pass atr * _adaptive_buffer(features, 1.0, regime_type)
  - Delete _collect_targets_long() and _collect_targets_short()
  - Add _collect_target_candidates(entry, stop, direction, atr, features) → list[TradeTarget]
  - Add weekly pivot, Fibonacci, Asian H/L, AVWAP candidates to unified function

src/intelligence/trading/lifecycle_tracker.py
  - Extend chandelier_state with be_floor: float | None
  - Add floor advancement logic in evaluate_signal() before chandelier check (T1 → entry, T2 → target_1)
  - Modify _check_active_exit(): T1 hit advances floor, does not exit
  - Apply be_floor clamp in chandelier check before comparing to price
  - Add be_floor_active to chandelier exit log payload
```

No schema changes. No new files. No new abstraction boundaries.

---

## Verification

```bash
# 1. No remaining GARCH_MULTIPLIERS or effective_atr
grep -rn "GARCH_MULTIPLIERS\|effective_atr" src/intelligence/trading/trade_framer.py  # → 0 results

# 2. All ATR buffer calls route through _adaptive_buffer
grep -rn "atr \* 0\.\|atr \* ATR_STOP\|atr \* ATR_FALLBACK" \
  src/intelligence/trading/trade_framer.py  # → 0 results (only _adaptive_buffer calls remain)

# 3. Unified target function exists; old long/short functions gone
grep -n "def _collect_target" src/intelligence/trading/trade_framer.py   # → _collect_target_candidates only
grep -n "def _collect_targets_long\|def _collect_targets_short" \
  src/intelligence/trading/trade_framer.py                                # → 0 results

# 4. New target fields present in unified function
grep -n "weekly_r1\|nearest_fib_level\|asian_session_high\|avwap_upper_band" \
  src/intelligence/trading/trade_framer.py  # → hits in _collect_target_candidates

# 5. be_floor state present, T1 no longer exits, no breakeven_stop exit reason
grep -n "be_floor" src/intelligence/trading/lifecycle_tracker.py        # → hits
grep -n "target_1_hit\|breakeven_stop" src/intelligence/trading/lifecycle_tracker.py  # → 0 results

# 6. Tests green
pytest tests/unit/ -q
```

---

## What this is NOT

- Not a change to ATR calculation — Wilder's 14-period is correct
- Not a change to the structural stop hierarchy (FVG → demand → sweep → OB → swing → EMA → S/R → fallback)
- Not a new module or abstraction — all changes live in their existing files
- Not a behavior change at the three GARCH anchor points (0.70/1.00/1.50 vol_ratio) — calibration preserved
- Not a `signal_ledger` schema migration
- Not using `kalman_uncertainty` yet — requires distribution study before threshold selection
