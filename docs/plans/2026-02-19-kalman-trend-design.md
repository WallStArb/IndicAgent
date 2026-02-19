# Kalman Filter Trend Plugin — Design

**Date:** 2026-02-19
**Status:** Approved
**Tier:** I4 Context
**Plugin Name:** `ctx_KalmanTrend`

---

## Problem

The current trend tools (SMA/EMA crossovers, `ctx_TrendRegime`) use fixed-window averaging. They can't adapt to changing market noise — when volatility spikes, a short EMA whipsaws; when it's calm, a long SMA lags. There's no principled measure of how confident the trend estimate is, nor a statistically meaningful "fair value" for mean reversion setups.

`trad_MeanReversion` currently lacks a rigorous deviation-from-fair-value signal. `trad_TrendFollowing` can't distinguish a high-confidence trend from a noisy one.

---

## Solution

A 1D Kalman filter (local level model) — the statistically optimal estimator that automatically balances responsiveness vs. smoothness based on market noise. It produces:

1. A filtered "fair value" price (`kalman_trend`)
2. A standardized deviation signal for mean reversion (`kalman_price_position`)
3. A trend direction signal (`kalman_slope`)
4. Confidence bands (`kalman_upper`, `kalman_lower`)
5. A filter trust indicator (`kalman_gain`) that tells I7 how confident the estimate is

---

## Algorithm

**State equation:** `x(t) = x(t-1) + w(t)`, `w ~ N(0, Q)` — "true" price evolves with process noise Q
**Observation:** `z(t) = x(t) + v(t)`, `v ~ N(0, R)` — observed close = true price + measurement noise R

```
Predict:
  x_pred = x_est                          # predicted state = last estimate
  P_pred = P_est + Q                      # predicted uncertainty grows by Q

Update (on each new close):
  K      = P_pred / (P_pred + R)          # Kalman gain (0-1)
  x_est  = x_pred + K * (close - x_pred)  # weighted blend of prediction + observation
  P_est  = (1 - K) * P_pred               # uncertainty shrinks after update
```

**Initialization:** `x_est = close[0]`, `P_est = R`

**Incremental:** Yes — O(1) per bar. State is `(x_est, P_est, kalman_trend_history[-5:])`.

---

## Parameters

| Parameter | Default | Notes |
|-----------|---------|-------|
| `Q` | `0.5` | Process noise — larger = more responsive to price moves |
| `R` | `2.0` | Measurement noise — larger = smoother trend |
| `use_garch_adaptive` | `False` | If True and `garch_sigma` in features, uses `(garch_sigma * scale_factor)^2` as R |

Q/R = 0.25 → moderate smoothing, similar to ~8-bar EMA responsiveness.

Overridable via `config/kalman_parameters.json` (same pattern as HMM, GARCH).

### Volatility-Adaptive Mode (optional)

When `use_garch_adaptive=True`, R is replaced with `max(R_min, (garch_sigma * 100)^2)` using the `garch_sigma` value from `features`. Falls back to fixed R if `garch_sigma` is not available. Ships disabled by default — zero breaking change.

---

## Outputs (7)

| Field | Formula | Range | I7 Use |
|-------|---------|-------|--------|
| `kalman_trend` | `x_est` | price units | Fair value reference for all setups |
| `kalman_slope` | `kalman_trend[t] - kalman_trend[t-5]` | price/5 bars | `trad_TrendFollowing` direction confirmation |
| `kalman_price_position` | `(close - kalman_trend) / sqrt(P_est)` | ~(-3, +3) | **Key MeanReversion signal** — >2 = extended |
| `kalman_uncertainty` | `P_est` | price² | Estimate confidence (lower = more reliable) |
| `kalman_upper` | `kalman_trend + 2*sqrt(P_est)` | price units | Stop/target reference |
| `kalman_lower` | `kalman_trend - 2*sqrt(P_est)` | price units | Stop/target reference |
| `kalman_gain` | `K = P_pred / (P_pred + R)` | [0, 1] | Filter trust — low K = confident trend, high K = noisy/uncertain |

**`kalman_gain` interpretation for I7:**
- K < 0.3 → filter confident, stable trend → weight up `trad_TrendFollowing`
- K > 0.7 → filter uncertain, noisy market → weight up `trad_MeanReversion`

---

## Placement

- **Directory:** `src/intelligence/context/kalman_trend.py`
- **Prefix:** `ctx_` (follows GARCH precedent — both are probabilistic context signals, not structural events)
- **Registration:** `registry.register_pattern(kalman_trend_plugin)` in `register_plugins.py`
- **Pattern:** Dataclass with `compute_full` + `compute_next` + `_state` dict — identical structure to `GARCHVolatilityPlugin`

---

## Integration with Existing Plugins

| Downstream | Kalman Output Used | Effect |
|------------|-------------------|--------|
| `trad_MeanReversion` | `kalman_price_position` | Replaces/supplements ad-hoc deviation logic |
| `trad_TrendFollowing` | `kalman_slope`, `kalman_gain` | Trend direction + confidence gate |
| `ctx_TrendRegime` | `kalman_slope` | Cross-validation of SMA-based regime |
| Future I7 Phase 2 | `kalman_upper`/`kalman_lower` | Stop placement reference |

Note: I7 plugins read features from the `frames["features"]` dict. No code changes required in existing I7 plugins — `kalman_price_position` will automatically appear in features once the plugin is registered. I7 plugins can adopt it incrementally.

---

## Tests (7)

1. Output keys present on sufficient history (all 7 fields)
2. `kalman_trend` within 2% of close on trending synthetic data
3. `kalman_price_position ≈ 0` at initialization
4. `compute_next` matches `compute_full` on final bar (incremental consistency)
5. Returns `{}` when fewer than `min_lookback` bars
6. `kalman_gain` bounded in [0, 1]
7. Adaptive mode: `use_garch_adaptive=True` uses `garch_sigma` from features when available, falls back to fixed R when not

---

## Complexity Estimate

- ~80 lines core implementation (slightly more than GARCH due to slope history)
- 7 tests
- 1 session to implement

---

## Not In Scope

- Multi-dimensional Kalman (constant velocity model) — more complex, marginal gain for 1m bars
- Online parameter estimation (EM algorithm for Q/R) — overkill for current use case
- Dashboard panel wiring — internal plugin, outputs flow via intelligence stream to I7 automatically
