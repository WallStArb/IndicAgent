VERDICT: GO

# Phase 172 Plan 01: Null-Arm Wider-Scope GO/NO-GO for the Volatility Axis

This document is the gate `172-05`'s full-corpus relabel is blocked on, per
`171-FINAL-VERDICT.md` section 6/7. Every number below is pulled directly from
`evidence/172-01-null-arm-wider-scope.json` (produced by
`scripts/analysis/hmm_production_regime_axes_null_arm_validation.py --axes volatility
--tf 15m 5m 1h 1d --symbols <30 corpus-derived symbols> --probe-windows 20 60 120 250`) and
`logs/172-01-null-arm-wider-scope.log`. Population: the 30-symbol, asset-composition-stratified
sample in `evidence/172-01-symbol-sample.json` (Task 1 of this plan) -- 4x the width of the
8-to-17-symbol sample Phase 171's own investigation was measured on.

GO requires `realized_vol` (the axis's ORDERING column -- what `_build_label_map` ranks states
by) to clear all three of the script's own criteria (`median(real) > 0.10`,
`median(real - null) > 0.10`, sign-test `p < 0.05`) at BOTH `15m` and `5m`. It does, with wide
margins at every timeframe tested, not just the two required. VERDICT: GO.

## Measured result

`realized_vol` block reliability (correlation of the block-level realized-vol estimate across
adjacent disjoint blocks; real vs. a jointly-permuted null; `evidence/172-01-null-arm-wider-scope.json`
key `probe`, filtered to `column="realized_vol"`), at the production-parity window W=20:

| tf | median(real) | median(null) | margin | sign_p | cells | real > null |
|---|---|---|---|---|---|---|
| 15m | 0.529 | -0.000 | **+0.532** | 1.86e-09 | 30 | 30/30 |
| 5m | 0.358 | -0.000 | **+0.354** | 1.86e-09 | 30 | 30/30 |
| 1h | 0.651 | 0.001 | +0.658 | 1.86e-09 | 30 | 30/30 |
| 1d | 0.612 | -0.017 | +0.633 | 1.86e-09 | 30 | 30/30 |

Phase 171 narrow-scope comparison (`171-NULL-ARM-VALIDATION-FINDINGS.md`, 8-to-17-symbol sample,
W=20, no 15m/5m coverage -- this is the gap this plan closes):

| tf | narrow-scope median(real) / median(null) | narrow-scope margin |
|---|---|---|
| 1d | +0.607 / -0.014 | +0.621 (pooled 1d+1h figure: +0.633) |
| 1h | +0.706 / +0.002 | +0.708 |

The wider-scope 1d/1h numbers (+0.633 / +0.658) land within a few hundredths of the narrow-scope
figures (+0.621-0.633 / +0.708) -- the wider, corpus-derived 30-symbol sample reproduces the
narrow-scope result rather than revising it, and the newly-covered 15m/5m timeframes clear with
comparable or larger margins (+0.532 / +0.354) than the margin floor requires. Every cell at
every timeframe agrees in direction (30/30 real > null at W=20 for all four timeframes).

`_axis_verdicts` (JSON key `axis_verdicts`, pooled across all four timeframes at W=20):

```
axis: volatility  columns=(1, 3)
  realized_vol  ORDERING  med_real=0.529  med_null=-0.000  margin=0.526  sign_p=1.50e-36  persists=yes  beats_null=yes  real=YES
  vol_of_vol              med_real=0.479  med_null=0.435   margin=0.064  sign_p=1.22e-08  persists=yes  beats_null=NO   real=NO
=> VALIDATED: 1/2 columns real (realized_vol); ordering column (realized_vol) carries real structure
```

`vol_of_vol`'s pooled-at-W=20 verdict is NO (margin 0.064 < the 0.10 floor) -- this is exactly the
window-dependence `171-FINAL-VERDICT.md` section 6 flagged, not a contradiction of the GO verdict
above: GO is gated on the ORDERING column (`realized_vol`) only, and `vol_of_vol` clears
decisively once its own window is swept (see below).

## Recommended shipped configuration

**`alpha.hmm_volatility.n_components = 3`**. Defaults to 3 per `171-FINAL-VERDICT.md` section 5
(preserves the calm/elevated/turbulent framing). K=2 is not chosen: the identifiability battery
(JSON key `sweep_summary`) shows K=2 passing 120/120 cells at min_agreement 0.9984 vs. K=3's
119/120 at min_agreement 0.8348 -- K=2 is tighter, but this is ordinary K-vs-identifiability
tradeoff (fewer states separate more cleanly), not a "materially wider margin" result: the
instrument that actually discriminates signal from noise in this investigation is block
reliability (above), which does not vary by K at all -- it measures the raw `realized_vol`/
`vol_of_vol` column series, not the HMM fit. Both K values are null-informative (real pass rate
exceeds null pass rate) and both have zero degenerate cells (0/120 each).

**`alpha.hmm_volatility.vol_window = 250`**. Selection rule: the window in `{20, 60, 120, 250}`
where `realized_vol`'s real-minus-null margin is largest at 15m and 5m jointly (JSON key `probe`,
column=`realized_vol`). Margins by window (15m / 5m):

| window | 15m margin | 5m margin |
|---|---|---|
| 20 | +0.532 | +0.354 |
| 60 | +0.680 | +0.573 |
| 120 | +0.718 | +0.641 |
| **250** | **+0.728** | **+0.732** |

W=250 is the joint maximum at both timeframes (not just one), so it is the unambiguous choice
under the plan's own rule, and it is also window-invariant in direction: `realized_vol` clears
30/30 real>null at every window tested, at every timeframe.

**`alpha.hmm_volatility.vol_of_vol_window = 250`**. Same selection rule applied to the
`vol_of_vol` column. Margins by window (15m / 5m):

| window | 15m margin | 5m margin |
|---|---|---|
| 20 | +0.070 | -0.023 |
| 60 | +0.315 | +0.221 |
| 120 | +0.403 | +0.327 |
| **250** | **+0.477** | **+0.452** |

W=250 is again the joint maximum. This confirms `171-FINAL-VERDICT.md` section 6's expectation
that `vol_of_vol` needs a window "solid from 60 up" -- the measurement finds the optimum further
out, at 250, not merely "60 or higher" as a floor. At W=250, `vol_of_vol` also individually clears
`median(real) > 0.10` AND `median(real - null) > 0.10` at both 15m (0.507 / 0.477) and 5m (0.468 /
0.452) -- unlike its pooled-W=20 reading above, `vol_of_vol` is a real signal once measured at its
own optimal window, it is simply not window-invariant the way `realized_vol` is.

## Open caveats

- **`vol_of_vol` is window-dependent, `realized_vol` is not.** Shipping `vol_window=250` and
  `vol_of_vol_window=250` uses the same window for both observation columns, which is convenient
  but not required by anything measured here -- `realized_vol` clears at every window tested, so
  a shared window of 250 costs it nothing, and `vol_of_vol` needs exactly this window to clear at
  all at 15m/5m. If a future measurement finds reason to decouple the two windows, this
  document's own data supports that (see the two margin tables above).
- **Two symbols contribute fewer blocks at 1d/W=250** (28 cells instead of 30 -- insufficient
  history for that block width at that timeframe; `_block_reliability` returns `NaN` for those
  cells and `_column_stats` drops them, per `hmm_candidate_regime_axes_identifiability_sweep.py`).
  This does not affect the GO verdict (which is measured at 15m/5m, both at full 30-cell
  coverage) or the vol_window/vol_of_vol_window recommendation (1d is not part of the
  joint-maximization rule).
- **K=3's identifiability battery has 3 failing cells, all at 1d**, all outside the GO/window
  criteria: `XLU/1d` fails on both the real and null arms (a genuinely hard cell for both, not
  evidence against K=3), `JPM/1d` and `VNQ/1d` fail only on the null arm (JSON key
  `sweep_summary[k=3].real.failing_cells` / `.null.failing_cells`). K=2 has one null-arm failure
  (`TLT/1d`). Zero degenerate cells at either K. None of this touches 15m/5m, the timeframes the
  GO decision and window sweep are measured on.
- **`vol_of_vol`'s pooled-at-W=20 axis_verdicts reading (NO) is superseded by the window-swept
  reading above (YES at W=250)**, not contradicted by it -- `_axis_verdicts` is fixed to the
  production-parity window (20) by the script's own design, and this document's window
  recommendation is exactly the correction that pooled reading needed. Anyone reading
  `axis_verdicts` in isolation without this document would see `vol_of_vol: NO` and could
  mistakenly conclude the column is dead; it is not, it was just being read at the wrong window.
- **This measurement, like Phase 171's, cannot rule out non-stationarity in the regime structure
  itself** (e.g., the 250-bar window's optimality may not hold indefinitely as market
  microstructure or trading-hour patterns shift) -- outside this plan's scope; `172-05`'s
  full-corpus relabel measures the shipped configuration against the whole corpus, which is the
  next real check.
