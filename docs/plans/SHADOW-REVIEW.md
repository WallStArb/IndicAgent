# SHADOW-REVIEW: Phase 147 Live Promotion Criteria

**Frozen as of the commit date of this document. This document must exist in the repository
before any counterfactual data is collected** — `AlphaFrameWriter` and `CounterfactualTracker`
must not run against production `alpha_events` until these criteria are committed.

**Status: FROZEN.** Post-hoc gate negotiation ("the numbers were close, lower the threshold")
is not permitted. If the gate fails, diagnose — don't renegotiate.

## Purpose

This document specifies the exact, numerically-evaluable criteria `alpha_frames` (primary
variant) must satisfy before Phase 147 promotes the AlphaEngine to live trading capital. The
criteria are committed here, before any shadow data exists, precisely so they cannot be tuned
to whatever data eventually arrives.

## Pass/Fail Criteria (five, all must pass)

All five criteria below are evaluated on **GROSS** `counterfactual_pnl_r` (see "Gross vs. net
cost basis (D-01)" below for the reasoned rationale).

### 1. Minimum sample

At least **60 trading days** of closed `alpha_frames` rows (`frame_variant = 'primary'`),
out-of-sample (`bar_ts >= alpha.validation.oos_start`).

### 2. Mean counterfactual P&L positive at 95% CI

`mean(counterfactual_pnl_r) > 0` at 95% CI (one-tailed) on OOS data, evaluated via a
**day-clustered block bootstrap** (review H4 — see "Statistical caveats (frozen)" below for the
full method and its residual-correlation caveat):

- Frames are first aggregated to a per-calendar-day mean `pnl_r` **within each (tf, regime)
  cell**, before any resampling.
- The bootstrap resamples day-clusters, not individual frames — frames opened on nearly every
  bar with hold horizons up to `alpha.frame.hold_max_bars.<regime>.<tf>` (up to 60 bars) share
  massively overlapping price paths; resampling individual frames as i.i.d. observations
  produces a drastically too-tight (anticonservative) confidence interval.
- Method: `scipy.stats.bootstrap` with `method='BCa'` for day-cluster counts
  `<= alpha.scoring.bootstrap_max_n`; above that ceiling, an analytic one-sided CLT lower bound
  is used instead (BCa's bias-correction jackknife is both unnecessary and computationally
  infeasible at high cluster counts).
- **Passes iff the day-clustered CI lower bound > 0.**

### 3. Sharpe

Sharpe of `counterfactual_pnl_r` **> 0.5 annualized**.

### 4. Maximum drawdown

The maximum peak-to-trough decline of the cumulative `counterfactual_pnl_r` equity curve, **in
R units**, does not exceed 25% of the running peak cumulative R at the trough:

```
max_peak_to_trough_decline_R / peak_cumulative_R_at_trough < 0.25
```

The base is explicitly the **peak cumulative R** at the point of maximum decline — not an
unspecified percentage of account equity, capital, or any other base.

### 5. No IC-Sharpe cliff

EnsembleICEngine IC Sharpe over the trailing 20 trading days of the shadow period must be at
least 50% of the full-shadow-period IC Sharpe:

```
last_20d_IC_Sharpe / full_period_IC_Sharpe >= 0.5
```

This is the numeric definition of "no cliff" — a cliff is any last-20-day IC Sharpe below half
the full-period value.

## Gross vs. net cost basis (D-01)

All five criteria above are evaluated on **GROSS** `counterfactual_pnl_r`. Gating on the
externally-calibrated `alpha.quant.cost_hurdle.*` keys (calibrated at the emission-threshold
layer, todo 030 — not validated against real fills) would conflate two independent questions:
"does the frame capture IC as P&L" and "is our unvalidated cost estimate right." The whole
point of splitting Phase 142A (signal) from Phase 142B (frame) was to never answer two
questions with one number; gating the frame gate on an unvalidated cost model would reintroduce
exactly that conflation one layer up.

## Mandatory reporting column: net_expected_r (D-02)

`net_expected_r` (gross `alpha_frames.gross_expected_r` minus the calibrated
`alpha.quant.cost_hurdle.*` keys, snapshotted per-row as `alpha_frames.cost_r`) is reported
**alongside every gross metric above** — it is **REPORTING ONLY, NOT A GATE**. This closes the
"gross P&L reads optimistic" gap the platform-canonical-simulator design flags (most events sit
in the cost-marginal band per todo 030's calibration) and makes the shared cost kernel's first
real consumer land inside Phase 142B.

**Interpretation of the diagnostic `gross_expected_r` / `net_expected_r` columns (review M5):**
`gross_expected_r = abs(alpha_score) × alpha.frame.target_r_multiple` is an **ex-ante expected
payoff MAGNITUDE in R** at frame-creation time — a diagnostic quantity, not a realized P&L and
not a win-probability. `alpha_score` is an IC-weighted ensemble score, not a probability; this
column scales that directional-confidence magnitude by the frame's design R-multiple on a win.
`net_expected_r = gross_expected_r - cost_r` is the same diagnostic net of the calibrated cost
snapshot. **Both `gross_expected_r` and `net_expected_r` are reporting-only and must never be
confused with the realized `counterfactual_pnl_r` that the five gate criteria above actually
evaluate.** `counterfactual_pnl_r` is the outcome `CounterfactualTracker` measures by walking
the real price path to a stop/target/max-hold/IC-decay exit; `gross_expected_r`/`net_expected_r`
are snapshots computed once at frame creation from the signal alone, before any price is
observed.

## Statistical caveats (frozen)

The day-clustered block bootstrap (criterion 2) removes the dominant source of overlap bias —
within-symbol intraday and multi-day path overlap from frames opened on nearly every bar with
hold horizons up to `hold_max_bars` — by collapsing all frames sharing a calendar date within a
(tf, regime) cell into a single cluster before resampling. It does **not** remove the residual
**cross-symbol same-day correlation**: multiple symbols in the same (tf, regime) cell on the
same calendar day still contribute to the same day-cluster's mean, and market-wide moves
correlate returns across symbols on that day regardless of clustering. This residual
correlation is a **known, direction-conservative, accepted residual** — day-clustering already
removes the larger and more anticonservative bias (within-symbol path overlap), and the
remaining cross-symbol correlation understates rather than overstates the true variance of the
day-cluster mean, making the resulting CI, if anything, still slightly narrower than a fully
independent-day estimate would be.

**This caveat is frozen with the five criteria above and may NOT be renegotiated after data
collection.**

## No post-hoc negotiation

Post-hoc gate negotiation ("the numbers were close, lower the threshold") is not permitted. If
the gate fails, diagnose — don't renegotiate.
