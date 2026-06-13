---
created: 2026-06-05T22:00:00.000Z
title: SR Strength Calibration — Regression-Fit zone_engine default_strength weights
area: intelligence
files:
  - src/intelligence/trading/zone_engine.py
  - docs/ideas/sr-zone-engine-improvements.md
priority: 3
gate: n >= 500 signals with SR-plugin-sourced confluence score in signal_ledger (sr_support_confluence_score does not exist as a flat column — check bucket_scores JSONB or a derived metric when this gate is evaluated)
---

## Problem

The `default_strength` values in `_SUPPORT_SPECS` / `_RESISTANCE_SPECS` (0.5–0.8 across 14 sources per direction) are **v0 intuition placeholders**, not empirically calibrated. They were set in Phase 116 as reasonable defaults for the initial run. The current values encode untested beliefs:

- `nearest_hvn_below / hvn_above` at 0.8 (HVN should be strongest)
- `prior_session_low / high` at 0.7 (session levels second)
- `nearest_fib_level` at 0.6 (fib third)
- `kc_mid_20` at 0.5 (weakest)

These rankings are plausible but untested. A regression against actual signal outcomes may invert some of these rankings — e.g., Keltner midline may empirically outperform session levels on short TFs.

## Gate Condition

Do not attempt calibration until: `SELECT COUNT(*) FROM signal_ledger WHERE sr_support_confluence_score > 0` returns **>= 500** (or resistance equivalent). Below this, the confidence intervals are too wide to trust the regression coefficients.

## Action

1. Query `signal_ledger` joined to `intelligence_features` on `(symbol, feature_ts, feature_tf)`:
   - Target variable: `pnl_r` (outcome) or `win` (binary)
   - Predictors: source-level contribution to `sr_support_confluence_score` / `sr_resistance_confluence_score`
2. Fit a ridge regression (L2 regularization) per source family, per TF bucket (1m/5m/15m/1h+). Separate models per TF are necessary — session levels matter less on 1m, more on 15m+.
3. Update `default_strength` values in `_SUPPORT_SPECS` / `_RESISTANCE_SPECS` with the calibrated weights, clipped to [0.1, 1.0].
4. Shadow-mode gate: run calibrated vs uncalibrated side-by-side for 30 days before replacing defaults.
5. Document the winning weights and their confidence intervals in a dated comment alongside the specs.

## Notes

- The `_SR_VP_DIRECTION` VP block candidates (poc, val/vah, hvn_below/above) each have hardcoded strength 0.7–0.8 in `collect_sr_candidates` — these are also v0 and should be included in the calibration pass.
- The `dist_atr` inversion `1/(1+val)` in `_resolve_strength` is correct in direction but its effective weight vs other sources is uncalibrated.
- See `docs/ideas/sr-zone-engine-improvements.md` for the broader zone_engine improvement backlog.
