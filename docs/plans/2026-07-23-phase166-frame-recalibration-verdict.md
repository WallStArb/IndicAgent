# Phase 166 Verdict: Frame/Execution Recalibration

Author: Claude Sonnet 5 (GSD executor, phase 166-06), synthesizing three independent one-shot
gate runs (`gate166_baseline`, `gate166_scalar`; `gate166_structural` not evaluable this
session -- see below) against live production data.

Status: FINAL for the 2-of-3-arm outcome this session produced. Per D-04
(`docs/plans/OOS-EVAL-PROTOCOL.md`), `gate166_baseline` and `gate166_scalar` cannot be re-run.
`gate166_structural` remains available for a future one-shot run once Phase 163 executes (see
"Structural Candidate" section).

## Purpose

Phase 166 exists to diagnose why Phase 148's Gate 2 (execution proof) failed
(`docs/plans/2026-07-22-phase148-promotion-decision.md`) while Gate 1 (signal proof) passed, and
to determine empirically whether a recalibrated frame (scalar per-(regime,tf) calibration, or a
structural VP/S-R confluence candidate) can turn the measured `alpha_score` signal into
profitable OOS P&L under the frozen `docs/plans/SHADOW-REVIEW.md` criteria. This document
records that empirical comparison (D-01/D-03) and the phase's overall recommendation.

## Diagnosis Recap (166-01)

The current global `alpha.frame.stop_atr_mult=1.5`/`target_r_multiple=2.0` scalars were never
conditioned on regime or timeframe (D-02) -- single `[initial_estimate]` values from migration
205/214, unrevisited since Phase 142B. `diagnose166_frame_calibration.py`'s live in-sample run
confirmed these scalars are systematically too wide against every measured (regime, tf) cell's
empirical uncensored MAE/MFE excursion percentile (166-01-SUMMARY.md). This is the real,
confirmed gap the scalar candidate below closes.

## Arm 1: Baseline (control -- current global scalars, unrecalibrated)

**Verdict: FAIL.** `gate_id='gate166_baseline'`, `run_ts=2026-07-23T13:07:38Z`.

Reuses the exact `weight_epoch='143.1-08-champion'` population Phase 148's `gate2_execution`
already scored (D-06-style anchor, matching that gate's own precedent) -- confirmed via direct
SQL inspection that every existing primary frame for this population already carried
`stop_atr_mult=1.5`/`target_r_multiple=2.0` (the current live global scalar, unchanged since
Phase 148 ran), so no `AlphaFrameWriter --backfill`/`CounterfactualTracker --backfill`
regeneration could have produced a different population than what already existed
(`AlphaFrameWriter --backfill` was run and confirmed 0 partitions written before this was
verified by direct query; `CounterfactualTracker --backfill` confirmed 0 rows written, i.e. the
population was already fully simulated).

| # | Criterion | Threshold | Value | Verdict |
|---|-----------|-----------|-------|---------|
| c1 | Minimum sample | >= 60 OOS days | 69 days | **PASS** |
| c2 | Mean P&L CI lower bound | > 0 | -0.12148963463689896 | **FAIL** |
| c3 | Sharpe | > 0.5 annualized | 0.38512018365944 | **FAIL** |
| c4 | Max drawdown ratio | < 0.25 | 9.596266492204737 | **FAIL** |
| c5 | No confident loss (proxy) | no confident loss | False | **PASS** |

n_rows=33,892; n_days=69. This exactly reproduces Phase 148's `gate2_execution` numbers to
within float-summation noise (c4: 9.596266492204737 here vs. 9.596266492204732 there) --
confirming this arm is a faithful, unmodified reproduction of the already-known-FAIL population,
not a fresh independent measurement of a different scalar.

**Regime-stratified companion:** 2 of 8 (direction, regime) cells clear `min_clusters=20`
day-coverage, both `mid_bull`, both FAIL (long: ci_lower=-0.077; short: ci_lower=-0.278) --
identical to Phase 148's own finding.

**Population footprint:** 33,892 frames, 7 eligible (regime, tf) cells, `5m`/`15m` only (no
`1h`/`1d` coverage -- todo 173), `mid_bull` is not the only regime observed (`high_bear`,
`high_neutral`, `low_bull`, `mid_bull`, `mid_neutral` all present) but is the only regime with
evaluable (>= 20 cluster) coverage on either side.

## Arm 2: Scalar Candidate (per-(regime,tf) empirically-calibrated stop/target)

**Verdict: FAIL.** `gate_id='gate166_scalar'`, `run_ts=2026-07-23T13:21:13Z`.

**Calibration (in-sample only, D-02/D-03.1):** `EnsembleICEngine._calibrate_stop_target()`
(166-02) ran end-to-end against the champion population
(`alpha_ensemble_ic`/`ensemble_alpha` scoped to `weight_version='143.1-08-champion'`, 20,793,843
rows, 80 symbols x 2 tfs, 184.68s wall-clock), writing 14 `alpha.frame.stop_atr_mult.<regime>.<tf>`/
`target_r_multiple.<regime>.<tf>` keys (7 cells) from uncensored `closed_target`-MAE /
`closed_max_hold`-MFE excursion percentiles (90th / 50th respectively). The other 29 possible
(regime, tf) cells had zero qualifying symbols and correctly kept the global-scalar fallback
(`_resolve_scalar_geometry`'s designed behavior, not a bug).

**Calibrated values written (7 cells):**

| regime | tf | stop_atr_mult | target_r_multiple |
|--------|-----|---------------|--------------------|
| low_bull | 5m | 0.495 | 0.456 |
| high_bear | 5m | 0.504 | 0.644 |
| high_neutral | 5m | 0.558 | 0.596 |
| mid_neutral | 15m | 0.818 | 0.235 |
| mid_bull | 5m | 0.828 | 0.465 |
| mid_bull | 15m | 1.208 | 1.585 |
| high_neutral | 15m | 1.256 | 1.669 |

All 7 cells calibrated to a NARROWER stop than the global 1.5x ATR (0.495x-1.256x), consistent
with the diagnosis. Target R-multiples span a much wider range (0.235-1.669) than the global
2.0, several well below 1:1 reward:risk.

**Regeneration:** OOS population (33,898 primary champion frames, `bar_ts >= oos_start`) deleted
and regenerated under `alpha.frame.geometry_source=per_cell_scalar`, then simulated via
`CounterfactualTracker --backfill` (28,100 closed, 5,798 still open -- right-censored near the
corpus edge, consistent with the baseline arm's own censoring pattern).

| # | Criterion | Threshold | Value | Verdict | vs. baseline |
|---|-----------|-----------|-------|---------|---------------|
| c1 | Minimum sample | >= 60 OOS days | 65 days | **PASS** | -4 days (fewer closed frames near the edge) |
| c2 | Mean P&L CI lower bound | > 0 | -0.04496637067918886 | **FAIL** | improved (less negative) |
| c3 | Sharpe | > 0.5 annualized | 0.44077851167037235 | **FAIL** | improved, still below threshold |
| c4 | Max drawdown ratio | < 0.25 | 26.17785604695943 | **FAIL** | **worse by 2.7x** |
| c5 | No confident loss (proxy) | no confident loss | False | **PASS** | unchanged |

n_rows=28,100; n_days=65.

**What this means:** tightening stops and narrowing target R-multiples per-cell moved c2 (mean
P&L CI) and c3 (Sharpe) in the right direction -- both closer to their thresholds, though neither
clears the bar -- but made c4 (max drawdown) dramatically WORSE (26.18 vs. 9.60, a 2.7x
deterioration). This is a real, informative negative result, not a wash: narrower stops fire
more often (more frequent `closed_stop` exits at a smaller R loss each, but the cumulative
sequence of losses evidently compounds into deeper peak-to-trough drawdown than the wider,
less-frequently-triggered baseline stop, especially compounded with several cells' sub-1.0
target R-multiples reducing the win-side offset). The scalar candidate does not clear the
frozen five criteria and is **not recommended for promotion**.

**Regime-stratified companion:** 2 of 7 cells clear `min_clusters=20` coverage (both `mid_bull`,
matching baseline), both FAIL (long: ci_lower=-0.119; short: ci_lower=-0.554, notably worse than
baseline's short/mid_bull of -0.278).

**Population footprint:** 28,100 frames (baseline: 33,892 -- a 5,792-frame / 17% reduction, driven
by the right-censoring difference at 65 vs. 69 days, not a methodology change), 7 eligible cells,
same `5m`/`15m`-only / non-`mid_bull`-only regime coverage shape as baseline.

**Coverage delta (baseline -> scalar):** frame_count -5,792 (-17.1%); eligible_cell_count
unchanged (7); tf/regime coverage shape unchanged (`5m`/`15m` only; `high_bear`/`high_neutral`/
`low_bull`/`mid_bull`/`mid_neutral` all still present). The scalar arm's smaller population is
attributable to its 4-fewer-day OOS closure window (censoring), not a narrower candidate
universe -- disclosed here so the smaller population cannot be mistaken for a favorable-looking
sparser result (Codex concern 2).

**Known reproducibility note (disclosed):** the OOS champion `alpha_frames` population for
`bar_ts >= oos_start` was DELETED and regenerated under `per_cell_scalar` geometry as part of
scoring this arm (per this plan's own "candidates run strictly sequentially... each overwrites
the shared alpha_frames rows via geometry_source" design). The baseline arm's original
global-scalar-geometry population is therefore no longer reconstructable from the live
`alpha_frames` table -- both arms' full pooled/regime-stratified/population evidence is
preserved in `gate_evaluations.evidence` (JSONB) for `gate166_baseline`/`gate166_scalar`
respectively, and `gate2_execution`'s own evidence (Phase 148) independently preserves the
original baseline numbers. Reproducing the raw baseline row population exactly would require
resetting `alpha.frame.geometry_source=global` and re-running the regenerate+simulate cycle.
`alpha.frame.geometry_source` was reverted to `global` (the safe, backward-compatible default)
after this arm's scoring completed -- no candidate's geometry is left as the live default,
since neither cleared the gate.
