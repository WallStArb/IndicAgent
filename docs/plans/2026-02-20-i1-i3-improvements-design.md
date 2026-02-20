# I1–I3 Improvements: Coverage, Depth, and Composites

> **Date:** 2026-02-20
> **Status:** APPROVED — ready for implementation planning
> **Scope:** Three independent tracks targeting I1 indicator coverage, I3 structure depth, and a new I1.5 momentum composite

---

## Motivation

The I1–I3 foundation feeds every downstream layer (I4 context → I5 patterns → I6 SMC → I7 setups → I8 narrative). Gaps here propagate — a trading setup that lacks ATR-normalized trailing stop levels, a trend-age signal, or multi-level S/R must work around the absence or leave the signal field empty.

Three distinct improvement areas were identified after reviewing all 20 I1/I3 plugin files and their downstream consumers:

1. **Coverage gaps** — 6 high-value I1 indicators that I7 setups reference but cannot find upstream
2. **I3 structure depth** — the 3 market structure plugins produce thin outputs; S/R exposes only 1 level, swing detector exposes no impulse magnitude
3. **Composite quality** — the single MAComposite covers MA crossovers but has no momentum consensus, volatility squeeze rank, or EMA stack score — all used by I6 confluence scoring

---

## Track A: New I1 Indicators

**Branch:** `feature/i1-new-indicators`
**Target tier:** I1 Technical Indicators
**Plugin count:** +6 (17 → 23)
**Test count:** ~+35

### A1 — Parabolic SAR

**File:** `src/intelligence/indicators/parabolic_sar.py`
**Plugin name:** `ind_ParabolicSAR`

Wilder's trailing stop / reversal detector. The SAR flips sides when price crosses it, producing a clean discrete entry/exit signal. Complements ADX (which measures trend strength but gives no flip signal).

```
Outputs: psar_value, psar_direction (+1 bull / -1 bear)
Incremental: Yes — SAR(t) = SAR(t-1) + AF * (EP - SAR(t-1)); AF resets on flip
Lookback: 1 bar of state
```

**I7 use:** TrendFollowing — use `psar_direction` flip as secondary entry confirmation and `psar_value` as trailing stop reference.

### A2 — Stochastic RSI

**File:** `src/intelligence/indicators/stochastic_rsi.py`
**Plugin name:** `ind_StochRSI`

RSI of RSI with Stochastic normalization. Catches extreme overbought/oversold conditions that plain RSI misses — RSI can sit at 60 for hours while StochRSI signals the local extreme.

```
Outputs: stoch_rsi_k_14, stoch_rsi_d_14 (3-bar SMA of K)
Incremental: Yes — maintain RSI rolling window (deque of 14 RSI values), apply Stochastic formula
Lookback: 14 RSI values + 3 for D-line smoothing
```

**I7 use:** MeanReversion — `stoch_rsi_k < 20` is a strong oversold confirmation trigger.

### A3 — Chandelier Exit

**File:** `src/intelligence/indicators/chandelier.py`
**Plugin name:** `ind_ChandelierExit`

ATR-based adaptive trailing stop. Long stop = highest_high(22) − 3×ATR; Short stop = lowest_low(22) + 3×ATR. Widely used as a dynamic exit level in futures.

```
Outputs: chandelier_long_22, chandelier_short_22
Incremental: Yes — rolling deque of highs/lows (same pattern as Donchian); ATR state already exists upstream
Lookback: 22 bars
```

**I7 use:** All setups — provides ATR-calibrated stop levels as an alternative to the fixed `atr_stop_dist` already in SignalSchema. I7 can reference `chandelier_long_22` directly for long stops.

### A4 — Historical Volatility

**File:** `src/intelligence/indicators/historical_volatility.py`
**Plugin name:** `ind_HistoricalVolatility`

Realized volatility: annualized std of log returns over N bars. Critical for VIX futures traders (compare realized vol to implied vol) and for vol regime confirmation alongside GARCH.

```
Outputs: hv_20, hv_ratio_20 (hv_20 / rolling_mean_hv_20 — vol-of-vol signal)
Incremental: Yes — online variance (Welford's method, same pattern as Bollinger Bands)
Lookback: 20 bars log returns (21 bars close prices)
```

**I7 use:** SqueezeExpansion — `hv_ratio_20 > 1.5` confirms vol expansion is sustained, not a single spike. Also feeds I4 VolatilityRegime for sharper regime detection.

### A5 — Aroon

**File:** `src/intelligence/indicators/aroon.py`
**Plugin name:** `ind_Aroon`

Measures how many bars ago the highest high and lowest low occurred within a rolling window, normalized to 0–100. `aroon_up = 100*(period - bars_since_high)/period`. Unique "trend age" signal — no other current indicator captures recency of extremes.

```
Outputs: aroon_up_25, aroon_down_25, aroon_osc_25 (up - down, -100 to +100)
Incremental: Yes — rolling deque of highs and lows (same pattern as Donchian)
Lookback: 25 bars
```

**I7 use:** TrendFollowing — `aroon_osc_25 > 50` with `trend_direction = 1` confirms trend is young and likely to continue. `aroon_osc` near zero = aging trend, reduce confidence.

### A6 — Chaikin Money Flow

**File:** `src/intelligence/indicators/cmf.py`
**Plugin name:** `ind_CMF`

Windowed accumulation/distribution: CMF = sum(MFV, N) / sum(volume, N), where MFV = volume × (2×close − high − low) / (high − low). Unlike OBV (cumulative), CMF resets every N bars — better for detecting short-term institutional pressure.

```
Outputs: cmf_20 (-1 to +1)
Incremental: Yes — rolling deque of MFV and volume (same pattern as MFI)
Lookback: 20 bars
```

**I7 use:** MeanReversion and TrendFollowing — CMF sign confirms whether money is flowing with or against a breakout.

---

## Track B: I3 Market Structure Enhancements

**Branch:** `feature/i3-structure-enhancements`
**Target tier:** I3 Market Structure (enhance existing 3 plugins, no new plugins)
**Test count:** ~+20 (enhance existing test files)

### B1 — Multi-Level Support/Resistance (`struct_SupportResistance`)

**Current state:** Exposes only the single nearest resistance above and support below price.

**Problem:** I7 trading setups need at least 2 levels — the nearest for stop placement and the second for target projection (risk:reward calculation).

**Additions:**
```
New outputs:
  resistance_2          # second-nearest resistance above price
  resistance_2_strength
  resistance_2_dist_pct
  support_2             # second-nearest support below price
  support_2_strength
  support_2_dist_pct
  sr_zone_width         # cluster bandwidth as % of price (quality signal: tight cluster = precise level)
```

**Implementation:** `_cluster_levels()` already returns all clusters sorted by distance. Expose `[1]` in addition to `[0]`. `sr_zone_width = max(prices_in_cluster) - min(prices_in_cluster)` within the nearest cluster, divided by current price.

### B2 — Volume-Weighted S/R Strength

**Current state:** `strength` = count of pivots in the cluster (integer).

**Problem:** A cluster of 3 low-volume pivots is weaker than 2 high-volume pivots. Volume at the pivot bars is already in the OHLCV DataFrame.

**Addition:** Weight each pivot's contribution by its bar volume (normalized to mean volume over the window):
```
volume_weight = volume[pivot_idx] / mean_volume
weighted_strength = sum(volume_weight for pivot in cluster)
```

This replaces the current count-based `strength` with a continuous volume-weighted score. The existing `strength` field semantics remain compatible (it was a float already).

### B3 — Swing Impulse Magnitude (`struct_SwingDetector`)

**Current state:** Exposes swing price level and age but no information about the size of the most recent move.

**Problem:** A swing high 5 bars ago that moved 0.1% is noise; one that moved 1.5% is significant. I5 patterns (chart patterns) use swing size but have to infer it from the swing price levels.

**Additions:**
```
New outputs:
  swing_high_magnitude  # % move from prior swing low to current swing high
  swing_low_magnitude   # % move from prior swing high to current swing low
```

**Implementation:** If `len(swing_highs) >= 1` and `len(swing_lows) >= 1`, compute:
```
sh_mag = (high[swing_highs[-1]] - low[swing_lows[-2]]) / low[swing_lows[-2]] * 100
sl_mag = (high[swing_highs[-2]] - low[swing_lows[-1]]) / high[swing_highs[-2]] * 100
```
Guard with enough history (need at least 2 of each).

### B4 — Structure Quality Signals (`struct_TrendStructure`)

**Current state:** `structure_integrity` measures swing non-overlap but not the quality of individual legs.

**Additions:**
```
New outputs:
  recent_leg_strength   # size of most recent leg / ATR (impulse quality, ATR-normalized)
  swing_alternation     # 1.0 if H/L alternate cleanly, 0.0 if same-type swings appear consecutively
```

**Implementation:**
- `recent_leg_strength`: Read `atr_14` from `frames.get("features")` (already done in TrendStructure for ATR normalization). Most recent leg = abs(last swing high − last swing low) / atr.
- `swing_alternation`: Walk the merged swing list; penalize consecutive H–H or L–L without alternation.

---

## Track C: New I1.5 Momentum Composite Plugin

**Branch:** `feature/i1-momentum-composite`
**Target tier:** I1 Composites (alongside existing `MAComposite`)
**Plugin name:** `ind_MomentumComposite`
**File:** `src/intelligence/composites/momentum_composite.py`
**Test count:** ~+15

### Purpose

The existing `MAComposite` covers moving average relationships. A second composite plugin synthesizes momentum and volatility features into scored aggregate outputs — exactly what I6 cross-timeframe confluence and I7 setup confidence scoring need.

### Outputs

| Output | Range | Logic |
|---|---|---|
| `ema_stack_score` | −4 to +4 | Count: +1 if price>EMA9, +1 if EMA9>EMA21, +1 if EMA21>EMA50, +1 if EMA50>EMA200; negative if reversed |
| `golden_death_cross` | −1/0/+1 | SMA50 vs SMA200: +1 cross up, −1 cross down, 0 no cross |
| `adx_trend_qualified` | −1/0/+1 | ADX>25 AND +DI>−DI → +1; ADX>25 AND −DI>+DI → −1; else 0 |
| `momentum_consensus` | −3 to +3 | RSI>50 (+1/−1) + Stoch_K>50 (+1/−1) + WilliamsR>−50 (+1/−1) |
| `vol_squeeze_rank` | 0–1 | ATR percentile rank over trailing 20 bars (0=historically tight, 1=wide) |

### Design

Consumes from `frames["features"]` (upstream feature dict), same pattern as `MAComposite`. Zero OHLCV access — pure post-processing of already-computed indicator values. This keeps it lightweight and side-effect free.

```python
@dataclass
class MomentumCompositePlugin:
    name: str = "ind_MomentumComposite"
    outputs: set[str] = frozenset({
        "ema_stack_score", "golden_death_cross", "adx_trend_qualified",
        "momentum_consensus", "vol_squeeze_rank",
    })
    supports_incremental: bool = True
    inputs: list[InputSpec] = ()  # Consumes upstream features only
```

`vol_squeeze_rank` requires a rolling deque of ATR values (20 bars). This is the only state the plugin needs.

---

## Implementation Order

Recommended sequence across sessions:

1. **Track A** — highest downstream value; unlocks richer I7 signals immediately
2. **Track C** — lightest lift; single file, pure feature math
3. **Track B** — lowest urgency; I3 structure is functional, just shallow

Each track is a self-contained branch → merge → delete workflow.

---

## Success Criteria

- All new plugins pass unit tests (incremental output matches full recompute)
- `register_all_plugins()` updated in `src/intelligence/register_plugins.py`
- Plugin count in CLAUDE.md updated after each track merges
- `future-indicators-backlog.md` updated to mark completed items
- Zero regressions in existing 383 tests

---

## Not in Scope

- Wiring new outputs to dashboard SSE panels (separate dashboard session)
- Updating I7 setup plugins to consume new signals (can happen after; outputs appear in `intelligence:SYMBOL:TF` stream automatically once registered)
- `compute_next()` incremental state for I3 (confirmed dead code in production processor; not worth the complexity until `indicators_enhanced_service.py` is the primary path)
