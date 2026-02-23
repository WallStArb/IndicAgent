> **HISTORICAL DOCUMENT** — `intelligence_processor_service.py` was deleted in Phase 1 (2026-02-23). References to it in this doc are for historical context only. The canonical service is now `market_analysis_service.py`.

# I7 Phase 2 — Setup Plugins Design

**Date:** 2026-02-20
**Scope:** Two new I7 trading setup plugins (Phase 4 of MASTER_ROADMAP.md)
**Plugins:** `trad_VWAPDeviation`, `trad_MomentumBreakout`

---

## Context

The current I7 layer has 5 setup plugins. Phase 4 targets 14 total (+9). This document
covers the first two Phase 2 additions.

### Available Features (Pipeline-Confirmed)

From VWAP plugin (already in I1_PLUGINS):
- `vwap`, `vwap_upper_1`, `vwap_lower_1`, `vwap_upper_2`, `vwap_lower_2`, `vwap_std`

From I3 structure (folded into features):
- `swing_high`, `swing_low` — most recent swing prices
- `nearest_resistance`, `nearest_support`, `resistance_strength`, `support_strength`
- `swing_pattern`, `trend_strength`

From I4 context:
- `trend_regime` ([-1, +1]), `trend_confidence`, `vol_regime`, `momentum_bias`
- `kalman_price_position` (z-score mean-reversion signal)

From I1 ATR: `atr_14`

**Note:** ROC_PPO is registered but not in I1_PLUGINS. Adding it is part of this work.
`bb_upper`/`bb_lower`/`bb_middle` do not exist — correct keys are `bb_20_2_upper` etc.

---

## Plugin 1: VWAP Deviation Setup

**File:** `src/intelligence/trading/vwap_deviation.py`
**Name:** `trad_VWAPDeviation`
**Roadmap spec:** Price deviates >2σ from VWAP → reversion signal
**Best for:** Mean reversion on high-volume intraday instruments (ES, NQ)

### Design Approach

Pure deviation gate (Approach A). The 2σ bands from the VWAP plugin are the hard gate.
Severity (how far beyond 2σ) is captured in the confidence score rather than separate branches.

### Logic Flow

```
1. Gate: vwap_std > 0  (VWAP has meaningful volume)
2. Gate: price < vwap_lower_2  OR  price > vwap_upper_2
3. Direction:
   - Long  if price < vwap_lower_2  (reversion upward)
   - Short if price > vwap_upper_2  (reversion downward)
4. sigma_deviation = |price - vwap| / vwap_std
5. Stop:
   - Long:  entry - atr * 1.5
   - Short: entry + atr * 1.5
6. Targets:
   - T1: vwap  (primary mean-reversion target)
   - T2: vwap_upper_1 (long) or vwap_lower_1 (short)  (extended target)
7. Confidence = weighted sum:
   - dev_score     (0.40): (sigma_deviation - 2.0) / 2.0, capped [0, 1]
   - regime_compat (0.35): trend_regime alignment with reversion direction
   - vol_contraction (0.25): 1.0 - min(1.0, volume_ratio - 1.0)  — lower vol = better fade
```

### Regime Compatibility Scoring

```
reversion_dir = +1 (long) or -1 (short)
regime_aligns  = trend_regime and reversion_dir have the same sign

if |trend_regime| < 0.3:  regime_compat = 0.50  (neutral — no opinion)
elif regime_aligns:        regime_compat = 0.70 + 0.30 * abs(trend_regime)
else:                      regime_compat = max(0.0, 0.50 - abs(trend_regime))
```

### Outputs

| Field               | Value                                           |
|---------------------|-------------------------------------------------|
| `signal_type`       | `vwap_reversion_long` / `vwap_reversion_short`  |
| `direction`         | `+1` / `-1`                                     |
| `entry_price`       | current close                                   |
| `stop_loss`         | entry ± atr * 1.5                               |
| `targets`           | [vwap, vwap_upper/lower_1]                      |
| `confidence`        | weighted [0, 1]                                 |
| `regime_context`    | `vwap_extended_high` / `vwap_extended_low`      |
| `supporting_factors`| list of strings (see below)                     |

### Supporting Factors

- `vwap_2sigma_breach` — always present (the gate condition)
- `vwap_{X:.1f}sigma_deviation` — e.g. `vwap_2.7sigma_deviation`
- `ranging_regime` — if `|trend_regime| < 0.3`
- `low_volume_deviation` — if `volume_ratio < 1.0`
- `regime_aligned` — if trend_regime supports reversion direction

### Parameters

| Param                  | Default | Description                              |
|------------------------|---------|------------------------------------------|
| `min_lookback`         | 20      | Minimum bars required                    |
| `sigma_threshold`      | 2.0     | σ multiple for gate (matches VWAP bands) |
| `atr_stop_multiplier`  | 1.5     | Stop distance in ATRs                    |
| `vol_expansion_threshold` | 1.3  | Volume ratio above which vol_contraction starts decreasing |

---

## Plugin 2: Momentum Breakout Setup

**File:** `src/intelligence/trading/momentum_breakout.py`
**Name:** `trad_MomentumBreakout`
**Roadmap spec:** ROC spike + volume confirmation + structure break
**Best for:** Trending moves after consolidation

### Design Approach

Triple-gate sequential (Approach A). All three conditions must pass; any single failure
returns no_signal. This keeps false positives low — breakouts without all three attributes
tend to fail.

### Logic Flow

```
1. Gate A — ROC spike:
   roc_14 = (close[-1] - close[-15]) / close[-15] * 100
   |roc_14| > roc_threshold (default 0.3%)

2. Gate B — Volume expansion:
   volume_sma_20 = np.mean(volume[-20:]) with fallback
   volume[-1] > volume_sma_20 * volume_expansion_threshold (default 1.5)

3. Gate C + Direction (must match Gate A direction):
   - Long:  roc_14 > 0 AND close[-1] > swing_high
   - Short: roc_14 < 0 AND close[-1] < swing_low
   (ROC direction and structure break direction must agree)

4. Stop (use broken level as new S/R):
   - Long:  swing_high - atr * 1.0   (below former resistance, now support)
   - Short: swing_low  + atr * 1.0   (above former support, now resistance)

5. Targets:
   - T1: entry ± atr * 1.5
   - T2: entry ± atr * 3.0

6. Confidence = weighted sum:
   - roc_score    (0.35): min(1.0, (|roc_14| - threshold) / threshold)
   - vol_score    (0.30): min(1.0, (volume_ratio - 1.5) / 1.5)
   - break_margin (0.20): min(1.0, max(0.0, |price - swing_level| / atr))
   - regime_score (0.15): 1.0 if aligned, 0.5 if neutral, 0.1 if against
```

### Stop Rationale

The stop goes **below the broken swing_high** (long) — not below the current price.
If the breakout is valid, the broken resistance level becomes support. A return below
it invalidates the breakout thesis. This is tighter than an ATR-from-entry stop but
more accurate to breakout mechanics.

### Outputs

| Field               | Value                                                  |
|---------------------|--------------------------------------------------------|
| `signal_type`       | `momentum_breakout_long` / `momentum_breakout_short`   |
| `direction`         | `+1` / `-1`                                            |
| `entry_price`       | current close                                          |
| `stop_loss`         | swing_high/low ± atr * 1.0                             |
| `targets`           | [entry ± 1.5*atr, entry ± 3.0*atr]                    |
| `confidence`        | weighted [0, 1]                                        |
| `regime_context`    | `breakout_bullish` / `breakout_bearish`                |
| `supporting_factors`| list of strings (see below)                            |

### Supporting Factors

- `roc_spike_{X:.1f}pct` — e.g. `roc_spike_0.5pct`
- `volume_{X:.1f}x_expansion` — e.g. `volume_2.1x_expansion`
- `structure_break_long` / `structure_break_short`
- `trend_regime_aligned` — if trend_regime supports the breakout direction

### Parameters

| Param                       | Default | Description                              |
|-----------------------------|---------|------------------------------------------|
| `min_lookback`              | 20      | Minimum bars required                    |
| `roc_period`                | 14      | Lookback for rate-of-change              |
| `roc_threshold`             | 0.3     | Minimum % ROC to qualify as a spike      |
| `volume_expansion_threshold`| 1.5     | Volume ratio gate                        |
| `atr_stop_multiplier`       | 1.0     | Stop offset from broken structure level  |
| `atr_target_multipliers`    | (1.5, 3.0) | T1, T2 in ATR multiples              |

---

## Pipeline Change

Add `"ROC_PPO"` to `I1_PLUGINS` in `services/intelligence_processor_service.py`.

ROC_PPO is already registered in `register_plugins.py` but not executed in the pipeline.
This makes `roc_14`, `ppo_12_26`, and `ppo_signal_12_26` available in the features dict
for all future plugins. The MomentumBreakout plugin also computes ROC inline as a
self-contained fallback if the feature is absent.

---

## Registration & Wiring

1. Add imports + registration calls in `src/intelligence/register_plugins.py`
2. Add plugin names to `I7_PLUGINS` in `services/signal_orchestrator_service.py`
3. No SSE or dashboard changes needed (I7 signals flow through existing aggregation path)

---

## Test Plan

### `trad_VWAPDeviation` tests

| Test | Condition | Expected |
|------|-----------|----------|
| Long gate | price below vwap_lower_2 | `vwap_reversion_long` signal |
| Short gate | price above vwap_upper_2 | `vwap_reversion_short` signal |
| No signal | price within bands | `signal_type = "none"` |
| No signal | vwap_std = 0 | `signal_type = "none"` |
| Confidence scaling | larger deviation → higher confidence | monotonic |
| Regime bonus | ranging regime → higher than trending against | ordering test |
| Target correctness | T1 = vwap, T2 = opposite 1σ band | exact values |

### `trad_MomentumBreakout` tests

| Test | Condition | Expected |
|------|-----------|----------|
| Long breakout | all three gates + roc > 0 + price > swing_high | `momentum_breakout_long` |
| Short breakout | all three gates + roc < 0 + price < swing_low | `momentum_breakout_short` |
| No signal — ROC weak | \|roc\| < threshold | `signal_type = "none"` |
| No signal — low vol | volume < sma * threshold | `signal_type = "none"` |
| No signal — no break | ROC up but price < swing_high | `signal_type = "none"` |
| Direction mismatch | ROC up but only swing_low broken | `signal_type = "none"` |
| Stop level | stop = swing_high - atr (long) | exact value |
| Confidence scaling | higher ROC → higher confidence | monotonic |
