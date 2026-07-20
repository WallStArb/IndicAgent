---
status: completed
priority: P1
filed: 2026-07-19
source: Fable 5 review of todo 091's residual SUSPECT cells
  (docs/research/fable-2026-07-19-lookahead-and-target-calibration-review.md, Q2) --
  spawned to give 091 a concrete close condition rather than accepting a residual
  SUSPECT rate unflagged.
---

**Closed 2026-07-19:** implemented as a standalone diagnostic,
`scripts/ops/alpha/ops_dependence_length_diagnostic.py` -- computes a 1/e-decorrelation-lag
proxy for integrated autocorrelation time per (feature, tf) from `feature_vectors`, aggregates
across sampled symbols via the median, and writes one `integrity_monitor` row per (feature, tf)
per run (`monitor_type='ic_bootstrap'`, `subject='feature=<name>|tf=<tf>'`,
`metric_name='dependence_length_ratio'`, `passed = ratio <= alpha.ic.dependence_length_flag_ratio`).
New APR key `alpha.ic.dependence_length_flag_ratio` (migration 239, seed 2.0, `[conventional]`),
applied live. `--feature-filter` added to `ops_ic_null_calibration.py` for a future stratified
confirmation run targeting `ctf_momentum`/`flight_quality` (not executed this session --
operational follow-up). Closes out todo 091. Decision recorded in
`docs/plans/methodology-change-ledger.md`.

# `_circular_block_bootstrap_ic` has no standing instrumentation for features whose
# dependence length exceeds their tf's block size -- add one, close out 091's residual

## Problem

091's 2026-07-19 confirmation run (against the fresh 143.1-07 corpus) found the
bootstrap CI fix cut the empirical-null SUSPECT rate from 38% to 21% (4/19 evaluated
cells) -- real improvement, not full resolution. Fable 5's review measured the
mechanism directly (integrated autocorrelation time vs. the feature's tf bootstrap
block size, `alpha.ic.bootstrap_block_size.{5m,15m,1h,1d}`, live values 78/26/10/10
bars):

| feature | cell | 1/e decorrelation lag | integrated autocorr time | block size | ratio |
|---|---|---|---|---|---|
| ctf_momentum | XLY/5m | 150 bars | ~300 bars | 78 | ~4x |
| ctf_momentum | EWJ/5m | 169 bars | ~300 bars | 78 | ~4x |
| ctf_momentum | QQQ/15m | 52 bars | ~104 bars | 26 | ~4x |
| flight_quality | VWO/1h | 5,678 bars | ~7,454 bars | 10 | ~750x |
| momentum_z_fast (control) | SPY/5m | 4 bars | ~5 bars | 78 | ~0.06x |

Every residual SUSPECT cell is a feature whose true dependence length exceeds its
block size -- the block bootstrap under-samples the feature's real autocorrelation
structure, so its CI comes out too narrow, so it passes gates more easily than its
evidence supports. `ctf_momentum` is structural (HTF-derived, ~4x across tfs, not
incidental) and its block could plausibly be widened. `flight_quality` (a TLT/SPY
macro-divergence feature that decorrelates on a months scale) cannot be fixed by any
feasible block size at intraday tfs -- ~4 independent blocks of 7,454 bars exist in
~30k observations, nowhere near enough for a stable CI.

Per this project's principles (proof before promotion, resist overfitting, instrument
everything): tuning block size per feature is the wrong fix (overfitting one dial to
one symptom, and doesn't help `flight_quality` at all). The right fix is standing
instrumentation -- measure the mismatch, flag affected cells as lower-trust, and let
that flag travel with the feature the way any other reliability signal does.

## Fix

### Dependence-length diagnostic (once per corpus run, per feature x tf)

Compute integrated autocorrelation time (or a cheaper proxy: 1/e decorrelation lag,
sufficient for a flag, not a publication-grade estimate) per (feature, tf) from the
same `feature_vectors` series the bootstrap resamples. Natural placement: a step
inside `ic_engine.py`'s existing per-tf pass (reuse the already-loaded feature arrays,
no new query), or a small standalone diagnostic batch if that's cleaner given
`ic_engine.py`'s size (3,600+ lines, Phase 162 is already restructuring its compute
functions -- coordinate, don't add a fifth concern to the same file mid-refactor).

### Flag: `integrity_monitor`, same pattern as todo 144's guard

Write one row per (feature, tf) per corpus run: `monitor_type='ic_bootstrap'`,
`subject='feature=<name>|tf=<tf>'`, `metric_name='dependence_length_ratio'`,
`metric_value` = integrated_tau / block_size, `threshold_value` =
`alpha.ic.dependence_length_flag_ratio` (seed 2.0, `[conventional]` -- a factor-of-2
overshoot is a reasonable first trigger; the live data above shows real cases cluster
at ~4x and ~750x, well clear of a 2x floor), `passed` = ratio <= threshold. This
reuses the exact `subject`-as-stratum-key precedent `vocabulary_drift.py` and todo
144 already established -- no new table, no new column on `feature_ic_scores`.

Downstream consumers (ensemble eligibility, quality-weight computation) can read this
as a lower-trust signal the same way `reliable`/`passes_walkforward` already gate
today -- wiring an actual consumer is a separate, later decision; this todo only
scopes the measurement + flag.

### Targeted stratified calibration sample (cheap, rides this todo)

091's own confirmation run had a 49/68 skip rate (insufficient N / stratum mismatch),
so its 21% headline sits on only 19 evaluated cells. A small follow-up run of
`ops_ic_null_calibration.py --ci-method bootstrap` specifically stratified toward
`ctf_momentum`/`flight_quality` cells (rather than the existing boundary-nearest
sampling) would confirm whether the mechanism found here generalizes across those
features' full cell population or was isolated to the 4 cells sampled. Cheap --
reuses the existing script, just needs a `--feature-filter` or similar sampling
override.

### Optional, deferred to next corpus rebuild: 5m/15m block-size revisit

`ctf_momentum`'s block ≈ integrated tau (~300 bars on 5m) is feasible (60k obs / 300 =
200 blocks, plenty) and worth considering when the corpus rebuilds next (rides Phase
162 / the same rebuild lookahead-grid changes are pre-registered against, per
docs/research/fable-2026-07-19-lookahead-and-target-calibration-review.md Q1c Step 3).
Do NOT do this per-feature -- if pursued, it's a single `alpha.ic.bootstrap_block_size`
value change backed by the measured tau distribution across ALL features at that tf,
not a `ctf_momentum`-specific carve-out.

## Close-out condition for todo 091

Per Fable's recommendation: 091's 21% residual SUSPECT rate is acceptable to carry
forward ONLY with this flag in place. Close 091 once the diagnostic + flag land here
(not before), and record the decision (91's residual rate, this flag's existence, and
the deliberate choice not to per-feature-tune block size) in
`docs/plans/methodology-change-ledger.md`.

## Sizing

Todo-sized. Diagnostic computation is cheap (autocorrelation of an already-fetched
series, O(n) per feature). The `integrity_monitor` write is a routine INSERT matching
an existing pattern. The stratified calibration sample re-runs an existing script with
a filter change. Effort: half a day to a day, most of it the diagnostic's placement
decision (inside `ic_engine.py` vs. standalone) and its unit tests.

## References

- `.planning/todos/pending/091-fisher-z-ci-empirical-null-miscalibration.md` --
  parent finding, "Confirmation run, 2026-07-19" section
- `docs/research/fable-2026-07-19-lookahead-and-target-calibration-review.md` Q2 --
  full mechanism measurement and recommendation this todo implements
- `src/intelligence/statistics/ic_math.py` `_circular_block_bootstrap_ic` -- the
  bootstrap this flag instruments, not modifies
- `.planning/todos/pending/144-ic-decay-regime-shift-guard-miscalibrated.md` -- the
  `integrity_monitor.subject`-as-stratum-key precedent this todo reuses
- `src/config/vocabulary_drift.py:182-215` -- original `subject` generic-stratum-key
  usage
