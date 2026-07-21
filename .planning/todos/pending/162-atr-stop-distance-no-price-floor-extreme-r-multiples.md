---
status: pending
priority: P2
filed: 2026-07-21
source: found while writing up 143.1-08's shadow-validation criteria (D-19-style
  data-quality check before trusting the champion/challenger numbers)
---

# ATR-based stop distance has no minimum-price-fraction floor — produces extreme R-multiple outliers on thin-ATR instruments

## What's wrong

`compute_frame_geometry()` (`services/alpha_frame_writer.py:64`) derives `stop_price` as
`entry_price ± stop_atr_mult * atr`, guarding only against `atr <= 0` (a genuinely degenerate/
stale-bar case, raises `ValueError`, caller skips and counts it via `degenerate_atr_skip_count`).
It does NOT guard against `atr` being a small but perfectly legitimate positive value on a
low-absolute-volatility instrument at a short timeframe — e.g. an FX or commodity ETF (FXY, FXE,
DBB, DBC, GLD, SLV, EWT, MCHI, INDA) on 5m bars, where a real ATR can be ~0.02-0.3% of price.
The resulting stop is razor-thin in absolute terms; ordinary 5m price noise (not a real adverse
move) blows through it by many multiples, producing `counterfactual_pnl_r` values far beyond a
normal stop-out's ~-1.0R — observed down to **-57.27R** in the 143.1-08 shadow-validation corpus.

This is not the `degenerate_atr_skip` bug (that guard is working correctly, catching truly
zero/stale ATR — 754 frames skipped in the 2026-07-21 full backfill). This is a distinct,
previously-undetected gap: a *small-but-valid* ATR that still produces an economically
meaningless stop distance.

## Evidence (2026-07-21, 143.1-08 OOS window, `bar_ts >= 2025-12-24`)

- 766 champion + 3,439 challenger closed frames have `abs(counterfactual_pnl_r) > 5` (out of
  33,892 / 740,204 total — 2.3% / 0.46% of each population respectively).
- Sample extreme rows: FXY 5m stop 0.0236 price-units away from entry (0.04% of price) ->
  `counterfactual_pnl_r = -57.27`; similar pattern across FXE/DBB/BIL/SLV/EWT/DBC/GLD/MCHI/INDA,
  concentrated in 5m (and some 15m) bars.
- Confirmed NOT solely responsible for the qualitative shadow-validation result: trimming
  `abs(pnl_r) > 10` still leaves both champion (mean -0.136) and challenger (mean -0.040)
  net-negative over the OOS window — but these outliers materially inflate the *magnitude* of
  Sharpe and max-drawdown statistics computed from the full (untrimmed) population, which is
  what 143.1-08's pre-committed criteria actually gate on (GROSS `counterfactual_pnl_r`, no
  filtering).

## Why this matters beyond 143.1-08

Any current or future corpus-wide statistic computed from `alpha_frames.counterfactual_pnl_r`
(Sharpe, drawdown, mean-CI) inherits this same tail contamination whenever ATR-based framing runs
against thin-absolute-volatility instrument/timeframe combinations — not specific to the
champion/challenger comparison that surfaced it.

## Candidate fix directions (not decided — needs its own scoping)

- A minimum stop-distance floor as a fraction of price (e.g. `max(stop_atr_mult * atr,
  min_stop_price_fraction * entry_price)`), APR-backed (`alpha.frame.min_stop_price_fraction`
  or similar namespace).
- Alternative: widen the existing `degenerate_atr_skip` guard from `atr <= 0` to `atr <=
  some_price_relative_floor`, same skip-and-count mechanism, no new stop-sizing logic.
- Needs a real decision on which instruments/timeframes are most affected (looks concentrated
  in FX/commodity ETFs at 5m/15m) and whether this is a stop-sizing issue specifically or also
  affects `target_price`/`r_multiple` (same `stop_atr_mult`-derived `stop_distance` feeds both).

## References

- `services/alpha_frame_writer.py:64` (`compute_frame_geometry` — the `atr <= 0` guard that
  doesn't catch this case)
- `services/counterfactual_tracker.py:441-455` (the try/except around `compute_frame_geometry`,
  `degenerate_atr_skip_count`)
- `.planning/phases/143.1-measurement-and-eligibility-integrity-fisher-z-ci-bootstrap-/143.1-08-SHADOW-VALIDATION.md`
  Section 6 — where this was found
