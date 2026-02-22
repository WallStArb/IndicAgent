# Liquidity Pools & Supply/Demand Zones — Design Document

**Date:** 2026-02-22
**Status:** Approved
**Scope:** Two new I6 detection plugins + two new I7 signal plugins + enhancements to four existing I7 plugins

---

## Problem Statement

The current SMC layer detects *generic* swing-based sweeps (`smc_LiquiditySweeps`) but has no concept of:
- **Named institutional levels** (PDH/PDL, PWH/PWL, equal highs/lows) that carry far more weight than random swing points
- **Zone origin patterns** (base→impulse) where institutional orders remain unfilled and price often returns
- **Market equilibrium context** (premium/discount) that determines whether a zone is aligned with smart-money bias

The existing `trad_LiquiditySweepReclaim` fires on any sweep + reclaim. This delivers too many low-confidence signals at meaningless swing levels. We need to distinguish *where* stops are clustered from *random* price extremes.

Additionally, the Act 1-2-3 ICT confirmation model — liquidity sweep → FVG displacement → S/D zone retest — is the highest-quality setup in the SMC framework. Our existing `smc_FVG` and `smc_LiquiditySweeps` already cover Acts 1-2. This design completes the model.

---

## Conceptual Definitions

### Liquidity Zones (Buy-side / Sell-side)
Areas where stop-loss orders cluster — *above* key highs (buy-side liquidity, BSL) and *below* key lows (sell-side liquidity, SSL). These stops are effectively pending orders in the opposite direction. Smart money sweeps through these levels to trigger the stops, fill their own positions, then reverses. The sweep is the setup, not the breakout.

**BSL sources:** Equal highs, PDH, PWH, session highs, obvious resistance
**SSL sources:** Equal lows, PDL, PWL, session lows, obvious support

### Supply/Demand Zones
Areas of institutional order imbalance — the *origin* of a strong impulse move. When price returned quickly from a base, unfilled orders remain in that range. Price often returns to those zones to fill the remaining orders. A **fresh** zone (untested) is the highest probability.

- **Demand zone (DBR — Drop-Base-Rally):** base before bullish impulse
- **Supply zone (RBD — Rally-Base-Drop):** base before bearish impulse

### Premium / Discount
The 20-bar range midpoint divides the market into premium (above midpoint — favors selling) and discount (below midpoint — favors buying). Supply zones in premium are structurally stronger; demand zones in discount are stronger. This is a free confidence layer.

### Why These Are Different
Liquidity zones = *where stops are clustered* (head-fake fuel). S/D zones = *where orders originated* (reversal/continuation points). A liquidity sweep of a BSL level often propels price into a nearby supply zone — this is the Act 1-2-3 model.

---

## Architecture

```
I6 Detection Layer (new)
  smc_LiquidityPools       → names + classifies BSL/SSL levels, premium/discount flag
  smc_SupplyDemandZones    → detects RBD/DBR origin zones on 15m, tracks freshness

I7 Signal Layer (new)
  trad_LiquidityHunt       → sweep of named BSL/SSL pool + reversal → signal
  trad_SupplyDemandSetup   → price enters fresh S/D zone + rejection → signal

I7 Signal Layer (existing — enhanced with new I6 features)
  trad_LiquiditySweepReclaim   → confidence boost if sweep was at named pool level
  trad_MomentumBreakout        → confidence penalty if breaking into opposing S/D zone
  trad_TrendFollowing          → confidence penalty if trending into opposing S/D zone
  trad_VWAPDeviation           → confidence boost if zone boundary aligns with VWAP target
```

**Why I6 for detection:** Once `smc_LiquidityPools` and `smc_SupplyDemandZones` outputs are in the `features` dict, every existing and future I7 plugin can consume them for free. Zone-awareness becomes a platform-wide capability, not a one-off plugin.

---

## Plugin 1: `smc_LiquidityPools` (I6)

**File:** `src/intelligence/smart_money/liquidity_pools.py`

### InputSpec
- `1m` — 150 bars (equal highs/lows, session tracking)
- `1d` — 5 bars (PDH/PDL/PWH/PWL)

### Level Detection — Priority Order

| Level | Detection Method | Significance |
|---|---|---|
| PWH / PWL | max/min of daily high/low across prior 5 trading days | 1.00 |
| PDH / PDL | yesterday's daily high / daily low | 0.85 |
| Equal highs 3+ | ≥3 swing highs within ATR × 0.75 band | 0.75 |
| Equal lows 3+ | ≥3 swing lows within ATR × 0.75 band | 0.75 |
| Equal highs 2 | 2 swing highs within ATR × 0.75 band | 0.60 |
| Equal lows 2 | 2 swing lows within ATR × 0.75 band | 0.60 |
| Session high / low | running max/min since midnight UTC | 0.50 |

**Equal highs/lows algorithm:**
1. Identify swing highs/lows using existing `_swing_utils.find_swing_highs/lows` (neighbor=5)
2. Cluster: group swing points within ATR × 0.75 of each other
3. A cluster of N touches → level = mean of cluster prices, touches = N
4. Prefer the most recently formed cluster if multiple exist on same side

**PDH/PDL/PWH/PWL from 1d data:**
- PDH = `df_1d["high"].iloc[-2]`, PDL = `df_1d["low"].iloc[-2]`
- PWH = `df_1d["high"].iloc[-6:-1].max()`, PWL = `df_1d["low"].iloc[-6:-1].min()`

### Premium / Discount
```python
range_high = df_1m["high"].iloc[-20:].max()
range_low  = df_1m["low"].iloc[-20:].min()
midpoint   = (range_high + range_low) / 2
price_in_premium = 1.0 if df_1m["close"].iloc[-1] >= midpoint else 0.0
premium_position = (close - midpoint) / (range_high - midpoint)  # -1 to +1
```

### Outputs (13 fields)
| Field | Type | Description |
|---|---|---|
| `bsl_level` | float | Price of nearest buy-side liquidity above current price |
| `bsl_type` | float | Encoded: pwh=1.0, pdh=0.85, eq_highs_3=0.75, eq_highs_2=0.60, session_h=0.50 |
| `bsl_significance` | float | 0.0–1.0 significance score |
| `bsl_dist_atr` | float | Distance from close to BSL level in ATR units |
| `bsl_touches` | float | Number of touches at BSL level (1 for PDH/PWH) |
| `ssl_level` | float | Price of nearest sell-side liquidity below current price |
| `ssl_type` | float | Encoded: pwl=1.0, pdl=0.85, eq_lows_3=0.75, eq_lows_2=0.60, session_l=0.50 |
| `ssl_significance` | float | 0.0–1.0 significance score |
| `ssl_dist_atr` | float | Distance from close to SSL level in ATR units |
| `ssl_touches` | float | Number of touches at SSL level |
| `price_in_premium` | float | 1.0 = premium zone, 0.0 = discount zone |
| `premium_position` | float | -1.0 (max discount) to +1.0 (max premium) |
| `pool_count` | float | Total named liquidity levels currently tracked |

---

## Plugin 2: `smc_SupplyDemandZones` (I6)

**File:** `src/intelligence/smart_money/supply_demand_zones.py`

### InputSpec
- `15m` — 150 bars (~37.5 hours — enough for meaningful institutional zones)
- `1m` — 5 bars (rejection confirmation at zone boundary)

### Zone Origin Detection (on 15m)

**Step 1: Identify impulse bars**
- Impulse criteria: `abs(close[i] - close[i-1]) > ATR_15m × 1.5`
- Candle overlap check: `max(0, min(high[i], high[i-1]) - max(low[i], low[i-1])) < ATR_15m × 0.3`
- Direction: bullish impulse (close > open) → DBR candidate; bearish → RBD candidate

**Step 2: Find the base (left of impulse)**
- Scan back up to 5 bars from impulse start
- Base candle criteria: `(high - low) < ATR_15m × 1.0` AND `abs(close - open) / (high - low) < 0.5`
- Require ≥1 base candle; take all consecutive qualifying candles
- Zone range: `zone_high = max(base candles high)`, `zone_low = min(base candles low)`
- Zone height capped at `ATR_15m × 2.0`

**Step 3: Zone classification**
- **DBR (demand):** base → bullish impulse
- **RBD (supply):** base → bearish impulse
- **DBD (demand continuation):** drop→base→drop (weaker, store separately)
- **RBR (supply continuation):** rally→base→rally (weaker, store separately)

### Zone Lifecycle
```
fresh (1.0)  →  tested (0.5)  →  mitigated (0.0, remove)

fresh:     price has not entered zone since creation
tested:    price entered zone (1m close inside zone boundary) but closed back out
           each subsequent test: freshness -= 0.15 (floor 0.1)
mitigated: price closed BEYOND the distal zone boundary on 15m → remove from active
```

### Zone Strength Scoring
```python
base_strength = freshness  # 1.0 / 0.5 / 0.1

# Premium/Discount alignment
if zone_type == "supply" and price_in_premium:
    base_strength *= 1.20
elif zone_type == "demand" and not price_in_premium:
    base_strength *= 1.20

# FVG inside zone (cross-check fvg_midpoint from features)
if fvg_midpoint and zone_low <= fvg_midpoint <= zone_high:
    base_strength *= 1.15

# Zone age decay (each 20 15m-bars = 5 hours)
age_bars = current_bar_idx - zone_creation_idx
age_penalty = max(0.70, 1.0 - (age_bars / 200) * 0.30)
base_strength *= age_penalty

strength = min(1.0, base_strength)
```

### Active Zone Tracking
- Maintain up to **5 active demand zones** and **5 active supply zones**, sorted by distance from current price
- On each new 15m bar: check all active zones for lifecycle transitions
- Output the **nearest** zone on each side

### Outputs (14 fields)
| Field | Type | Description |
|---|---|---|
| `nearest_demand_high` | float | Upper edge of nearest demand zone |
| `nearest_demand_low` | float | Lower edge of nearest demand zone |
| `demand_freshness` | float | 1.0 fresh / 0.5 tested / 0.1 near-mitigated |
| `demand_strength` | float | 0.0–1.0 composite strength score |
| `demand_dist_atr` | float | Distance from close to nearest demand zone in ATR units |
| `in_demand_zone` | float | 1.0 if current price inside demand zone |
| `nearest_supply_high` | float | Upper edge of nearest supply zone |
| `nearest_supply_low` | float | Lower edge of nearest supply zone |
| `supply_freshness` | float | 1.0 fresh / 0.5 tested / 0.1 near-mitigated |
| `supply_strength` | float | 0.0–1.0 composite strength score |
| `supply_dist_atr` | float | Distance from close to nearest supply zone in ATR units |
| `in_supply_zone` | float | 1.0 if current price inside supply zone |
| `active_demand_zones` | float | Count of active demand zones |
| `active_supply_zones` | float | Count of active supply zones |

---

## Plugin 3: `trad_LiquidityHunt` (I7)

**File:** `src/intelligence/trading/liquidity_hunt.py`

### Concept
Fires when price sweeps a *named, significant* BSL/SSL pool and closes back through it. This is "trading with the hunters" — the sweep IS the signal, not the breakout.

### Entry Gates (all required)
1. `bsl_significance >= 0.60` OR `ssl_significance >= 0.60` — a named level exists
2. `sweep_detected == 1.0` (from `smc_LiquiditySweeps`) AND `sweep_level` within ATR × 0.75 of `bsl_level` or `ssl_level` — confirms the sweep was at the named level
3. `sweep_reclaimed == 1.0` — price closed back through the level
4. ATR > 0 — basic sanity check

### Direction
- BSL swept (high wicked above `bsl_level`, close below) → SHORT (`direction = -1`)
- SSL swept (low wicked below `ssl_level`, close above) → LONG (`direction = +1`)

### Stops and Targets
```python
# Stop: beyond the swept level with ATR buffer
stop = bsl_level + atr * 0.3   # short
stop = ssl_level - atr * 0.3   # long

# T1: minimum 1.5R from entry
t1 = entry - atr * 1.5   # short
t1 = entry + atr * 1.5   # long

# T2: nearest opposing pool or S/D zone (whichever is closer and further than T1)
# Short T2: ssl_level (nearest sell-side pool) or nearest_demand_high
# Long T2: bsl_level (nearest buy-side pool) or nearest_supply_low
```

### Confidence Scoring
```python
confidence = 0.55  # base

# Pool significance premium
if significance >= 1.0:    confidence += 0.12  # PWH/PWL
elif significance >= 0.85: confidence += 0.08  # PDH/PDL
elif significance >= 0.75: confidence += 0.05  # equal highs/lows 3+

# Premium/discount alignment (selling from premium, buying from discount)
if direction == -1 and price_in_premium:  confidence += 0.06
if direction == +1 and not price_in_premium: confidence += 0.06

# FVG alignment in sweep direction
if fvg_detected == 1.0 and fvg_type == float(direction): confidence += 0.08

# Order block alignment
if ob_detected == 1.0 and ob_type == float(direction): confidence += 0.06

# BOS/CHoCH confirmation after sweep
if bos_detected == 1.0 and bos_direction == float(direction): confidence += 0.07
if choch_detected == 1.0: confidence += 0.10  # stronger signal

# NOT breaking into opposing S/D zone
if direction == -1 and in_supply_zone == 1.0:  confidence += 0.05  # aligned
if direction == +1 and in_demand_zone == 1.0:  confidence += 0.05  # aligned
if direction == -1 and in_demand_zone == 1.0:  confidence -= 0.10  # opposing zone ahead
if direction == +1 and in_supply_zone == 1.0:  confidence -= 0.10

# CTF confluence
if abs(ctf_score) > 0.3 and np.sign(ctf_score) == direction: confidence += 0.05

confidence = round(min(0.95, max(0.10, confidence)), 4)
```

### Signal Type
`"liquidity_hunt_long"` / `"liquidity_hunt_short"`

### Distinction from `trad_LiquiditySweepReclaim`
`trad_LiquiditySweepReclaim` fires on ANY sweep + reclaim (generic swing level). `trad_LiquidityHunt` **requires** the sweep to be at a named institutional level (significance ≥ 0.60). These are complementary — `LiquidityHunt` is the higher-conviction subset.

---

## Plugin 4: `trad_SupplyDemandSetup` (I7)

**File:** `src/intelligence/trading/supply_demand_setup.py`

### Concept
Fires when price enters a fresh or tested S/D zone and shows rejection confirmation. The highest-confidence variant is the Act 1-2-3 completion: prior liquidity sweep (Act 1) + FVG displacement (Act 2) + zone retest (Act 3).

### Entry Gates (all required)
1. `in_demand_zone == 1.0` OR `in_supply_zone == 1.0`
2. `demand_freshness >= 0.40` OR `supply_freshness >= 0.40` — not fully mitigated
3. **Rejection confirmation on 1m:** either:
   - Wick beyond zone boundary + close back inside (sweep of zone edge)
   - OR: 2+ consecutive closes moving away from the zone interior

### Direction
- In demand zone → LONG (`direction = +1`)
- In supply zone → SHORT (`direction = -1`)
- If both (overlapping zones): skip — ambiguous

### Stops and Targets
```python
# Stop: beyond the distal (far) zone edge
stop = nearest_demand_low - atr * 0.25   # long (below demand zone)
stop = nearest_supply_high + atr * 0.25  # short (above supply zone)

# T1: proximal zone edge (internal to zone — first partial profit)
t1_long  = nearest_demand_high  # top of demand zone
t1_short = nearest_supply_low   # bottom of supply zone

# T2: 2.5R from entry
t2_long  = entry + (entry - stop) * 2.5
t2_short = entry - (entry - stop) * 2.5
```

### Confidence Scoring
```python
# Base confidence by freshness
if demand_freshness >= 0.9 or supply_freshness >= 0.9:
    confidence = 0.58   # fresh zone
elif demand_freshness >= 0.5 or supply_freshness >= 0.5:
    confidence = 0.46   # tested zone
else:
    confidence = 0.35   # heavily tested

# Zone strength premium
strength = demand_strength if direction == 1 else supply_strength
confidence += (strength - 0.5) * 0.20  # +/-0.10 depending on strength

# Premium/Discount alignment
if direction == +1 and price_in_premium == 0.0:  confidence += 0.08  # demand in discount
if direction == -1 and price_in_premium == 1.0:  confidence += 0.08  # supply in premium
if direction == +1 and price_in_premium == 1.0:  confidence -= 0.06  # demand in premium (weaker)
if direction == -1 and price_in_premium == 0.0:  confidence -= 0.06  # supply in discount (weaker)

# *** ACT 1-2-3 MODEL — highest conviction ***
# Act 1: recent liquidity sweep in same direction
if sweep_detected == 1.0 and sweep_reclaimed == 1.0:
    if (direction == +1 and sweep_type == +1.0) or (direction == -1 and sweep_type == -1.0):
        confidence += 0.14  # sweep → displacement → zone retest = full ICT model
        supporting.append("act_1_2_3_confirmed")

# Act 2: FVG in displacement zone (price moved through FVG to reach this zone)
if fvg_detected == 1.0 and fvg_type == float(direction):
    confidence += 0.09
    supporting.append("fvg_displacement")

# Order block coincidence (zone aligns with OB)
if ob_detected == 1.0 and ob_type == float(direction):
    if ob_high >= nearest_demand_low and ob_low <= nearest_demand_high:  # OB overlaps zone
        confidence += 0.08
        supporting.append("ob_zone_overlap")

# BOS/CHoCH confirmation
if choch_detected == 1.0: confidence += 0.09
elif bos_detected == 1.0 and bos_direction == float(direction): confidence += 0.05

# CTF alignment
if abs(ctf_score) > 0.3 and np.sign(ctf_score) == direction: confidence += 0.05

confidence = round(min(0.95, max(0.10, confidence)), 4)
```

### Signal Type
`"supply_demand_long"` / `"supply_demand_short"`

---

## Enhancements to Existing I7 Plugins

### `trad_LiquiditySweepReclaim` — confidence boost for named levels
```python
# After existing confidence scoring, add:
bsl_sig = features.get("bsl_significance", 0.0)
ssl_sig = features.get("ssl_significance", 0.0)
sweep_type = features.get("sweep_type", 0.0)

if sweep_type > 0 and ssl_sig >= 0.60:  # SSL swept (long setup)
    confidence += min(0.10, ssl_sig * 0.12)
    supporting.append(f"named_ssl_level_{ssl_sig:.2f}")
elif sweep_type < 0 and bsl_sig >= 0.60:  # BSL swept (short setup)
    confidence += min(0.10, bsl_sig * 0.12)
    supporting.append(f"named_bsl_level_{bsl_sig:.2f}")
```

### `trad_MomentumBreakout` — zone friction penalty
```python
# Before returning signal, apply zone penalties:
in_supply = features.get("in_supply_zone", 0.0)
in_demand = features.get("in_demand_zone", 0.0)
supply_str = features.get("supply_strength", 0.0)
demand_str = features.get("demand_strength", 0.0)

if direction == +1 and in_supply_zone == 1.0:
    confidence -= 0.12 * supply_str  # breaking into supply = friction
    supporting.append("penalty_supply_zone_ahead")
if direction == -1 and in_demand_zone == 1.0:
    confidence -= 0.12 * demand_str  # breaking into demand = friction
    supporting.append("penalty_demand_zone_ahead")
```

### `trad_TrendFollowing` — same zone penalty
Same logic as MomentumBreakout — trending into an opposing institutional zone reduces conviction.

### `trad_VWAPDeviation` — zone target confluence
```python
# T2 is already VWAP ±1σ. If an S/D zone edge aligns with T2:
supply_low = features.get("nearest_supply_low", 0.0)
demand_high = features.get("nearest_demand_high", 0.0)

if direction == -1 and supply_low and abs(supply_low - t2) < atr * 0.5:
    confidence += 0.05
    supporting.append("supply_zone_aligns_vwap_t2")
if direction == +1 and demand_high and abs(demand_high - t2) < atr * 0.5:
    confidence += 0.05
    supporting.append("demand_zone_aligns_vwap_t2")
```

---

## The Act 1-2-3 Model — Full Integration

The highest-conviction setup in the system chains existing + new plugins:

```
Act 1 — Liquidity Sweep (smc_LiquiditySweeps → trad_LiquidityHunt)
  ↓  Price sweeps a BSL/SSL pool, triggers stops, closes back through

Act 2 — FVG Displacement (smc_FVG)
  ↓  Strong move away from the swept level creates a Fair Value Gap
     (the imbalance proving institutional intent)

Act 3 — S/D Zone Retest (smc_SupplyDemandZones → trad_SupplyDemandSetup)
  ↓  Price retraces to fill the FVG or retest the S/D zone origin
     trad_SupplyDemandSetup fires with +0.14 "act_1_2_3_confirmed" bonus
```

The `trad_SupplyDemandSetup` plugin detects this automatically via the `sweep_detected` + `fvg_detected` feature flags that are already flowing through the pipeline.

---

## Files to Create

| File | Type | Description |
|---|---|---|
| `src/intelligence/smart_money/liquidity_pools.py` | New I6 | BSL/SSL detection, premium/discount |
| `src/intelligence/smart_money/supply_demand_zones.py` | New I6 | RBD/DBR zone detection, lifecycle |
| `src/intelligence/trading/liquidity_hunt.py` | New I7 | Named-pool sweep + reversal signal |
| `src/intelligence/trading/supply_demand_setup.py` | New I7 | Zone retest + rejection signal |
| `tests/unit/smart_money/test_liquidity_pools.py` | Tests | ~15 tests |
| `tests/unit/smart_money/test_supply_demand_zones.py` | Tests | ~18 tests |
| `tests/unit/trading/test_liquidity_hunt.py` | Tests | ~12 tests |
| `tests/unit/trading/test_supply_demand_setup.py` | Tests | ~15 tests |

### Files to Modify
| File | Change |
|---|---|
| `src/intelligence/register_plugins.py` | Register 4 new plugins |
| `src/intelligence/trading/liquidity_sweep_reclaim.py` | Add named-level confidence boost |
| `src/intelligence/trading/momentum_breakout.py` | Add zone friction penalty |
| `src/intelligence/trading/trend_following.py` | Add zone friction penalty |
| `src/intelligence/trading/vwap_deviation.py` | Add zone T2 confluence boost |

---

## Test Strategy

### Unit Tests — I6 Plugins
- `smc_LiquidityPools`: equal highs detection with ATR tolerance; PDH/PDL from 1d data; premium/discount flag; empty data returns zeros
- `smc_SupplyDemandZones`: DBR detection (impulse threshold); RBD detection; lifecycle transitions (fresh → tested → mitigated); zone strength with premium/discount modifier; zone age decay

### Unit Tests — I7 Plugins
- `trad_LiquidityHunt`: gates correctly (no signal if significance < 0.60); BSL sweep → short; SSL sweep → long; confidence scaling by level significance; zone penalties applied; Act 1-2-3 bonus in `trad_SupplyDemandSetup`
- `trad_SupplyDemandSetup`: no signal on mitigated zone; fresh > tested base confidence; premium/discount modifier; Act 1-2-3 bonus when sweep + FVG present; no signal when both zones overlap

---

## Success Criteria

- [ ] `smc_LiquidityPools`: equal highs/lows detected with ATR-relative tolerance; PDH/PDL/PWH/PWL from 1d InputSpec; premium/discount flag correct; 15 tests passing
- [ ] `smc_SupplyDemandZones`: DBR/RBD origin zones detected on 15m; lifecycle transitions work; strength scoring applies premium/discount; 18 tests passing
- [ ] `trad_LiquidityHunt`: fires only on named-level sweeps (significance ≥ 0.60); confidence scored correctly; 12 tests passing
- [ ] `trad_SupplyDemandSetup`: Act 1-2-3 bonus applied when sweep + FVG preceded zone entry; zone friction penalties applied to momentum/trend plugins; 15 tests passing
- [ ] All 4 plugins registered in `register_plugins.py`
- [ ] Existing I7 enhancements: `trad_LiquiditySweepReclaim` confidence boosted by named-level significance; `trad_MomentumBreakout` / `trad_TrendFollowing` penalized for zone friction
- [ ] Full test suite passes (476+ → ~536+ tests)
- [ ] 0 ruff errors
