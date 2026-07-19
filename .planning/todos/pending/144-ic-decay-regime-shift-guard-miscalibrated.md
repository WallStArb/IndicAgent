---
status: pending
priority: P1
filed: 2026-07-19
source: session RCA of the first-ever regime_shift_fraction firing (fraction=0.9618 at
  training_window_end=2025-12-24); verified against live feature_ic_scores distributions
  and config_state via psql
---

# ic_engine regime-shift guard is miscalibrated below the domain's own base rate; it will hold lifecycle transitions on every run

## Problem

`_run_lifecycle_hook()` (`services/ic_engine.py:2654`) has a regime-shift guard (Step 3,
lines 2787-2815) meant to distinguish a market-wide dislocation from mass feature decay:
if the fraction of active POOLED cells that failed exceeds
`alpha.decay.regime_shift_fraction` (0.60, provenance `[initial_estimate]`, i.e. a guess),
it HOLDs all promotion/demotion transitions for that `training_window_end` and returns,
skipping Step 4 (lifecycle) and Step 6 (staleness gauge).

Two structural defects:

1. **The threshold sits ~35 points below the domain's known-normal failure rate.** The
   guard fired for the first time ever on 2026-07-19 at fraction=0.9618. Session RCA
   confirmed this is NOT a measurement bug: mean IC is indistinguishable from zero and
   mean p-value sits at a true null (~0.42-0.52) across all four tfs and both
   pooled/per-symbol slices; the project's own EIC-04 gate has already established that a
   2-4% pass rate (35/1585 = 2.21%, later 54/1425 = 3.79%) is this corpus's steady state
   under proper FDR correction. A 96-98% "failure" rate is normal, so a 0.60 trigger trips
   on effectively every future window. The Step 0 idempotency check (lines 2673-2690)
   means each HOLD permanently marks that window as evaluated, and every NEW window
   re-trips: functionally a permanent latch that freezes the feature lifecycle while
   giving false comfort that an anomaly guard exists. It carries zero information.

2. **One flat denominator, one tail.** The single SQL query (lines 2696-2719) pools every
   tf (5m/15m/1h/1d) and every regime_group (equity 9-cell, rates 6-cell; confirmed via
   `regime_scope='cross_sectional'` with 9 vs 15 distinct labels per tf) into one
   fraction at one pinned lookahead. And the guard only watches the too-much-failure
   tail. Todo 091 (open) documents the mirror risk: `_fisher_z_ci`
   (`src/intelligence/statistics/ic_math.py:122`) may be too NARROW in ~38% of a sampled
   cross-section, which would make cells pass MORE easily than they should. There is zero
   instrumentation for a suspiciously HIGH pass rate today. A real guard brackets an
   expected band, not one tail.

## Fix

### Stratification: per (tf, regime_group), with a min-cell floor, no rollup

Compute the fail fraction per `(tf, regime_group)` stratum, not one flat pool.
Justification against live data: equity and rates are different markets with different
regime grids; 1d has structurally fewer independent observations than 5m; live counts
show 900-2250 active cells per (tf, group) stratum, which is a stable denominator.
Do NOT fragment to per-regime-cell (~150 cells each is numerically fine but 15-33
strata multiply correlated trips without adding decision value; "market-wide
dislocation" is a per-market, per-horizon hypothesis, exactly the (tf, group) grain).

`feature_ic_scores` has no regime_group column; labels are disjoint vocabularies across
groups (low/mid/high x bull/neutral/bear vs steep/flat/inverted x tight/wide), so map
via one `SELECT DISTINCT regime_group, regime_label FROM market_regimes` lookup at hook
start. No schema change.

Floor: a stratum with fewer than `alpha.decay.guard_min_cells` active cells (seed 100,
`[conventional]`; binomial SE of a fraction at p~0.9, n=100 is ~0.03, tight enough to
trust) is **diagnostic-only**: its fraction is still written to `integrity_monitor` but
it never grants hold authority. Do NOT roll up to a coarser stratum; rollup re-creates
the exact pooling defect being fixed. Fail-safe direction: skip means no hold, which is
never worse than the pre-guard status quo.

### Cold-start / self-calibration: seeded rails + rolling empirical band, gated on history

Two layers, mirroring the project's own recovery_min_observations/recovery_min_passes
philosophy (gate trust on evidence):

- **Layer 1, hard rails (always active):** `alpha.decay.guard_fail_rate_max` seed 0.995
  and `alpha.decay.guard_fail_rate_min` seed 0.85, both `[rca_analysis]`, grounded in
  this session's RCA against the EIC-04 base rate: normal fail rate is 96-98%, so
  >99.5% means even the historical survivors died simultaneously (dislocation), and
  <85% means a pass rate 4-7x the known base rate (CI overconfidence per todo 091, or a
  measurement bug). These are empirically anchored, not guesses; no `[initial_estimate]`
  anywhere in this design.
- **Layer 2, empirical band (after history exists):** once a stratum has at least
  `alpha.decay.guard_min_history` (seed 8, `[conventional]`, minimum sane N for a scale
  estimate) prior evaluations, band = median +/- z * (1.4826 * MAD) over the last
  `alpha.decay.guard_history_window` (seed 20, `[conventional]`) fractions, with
  z = `alpha.decay.guard_band_z` (seed 3.0, `[conventional]`, three-sigma). Robust stats
  so anomalous (HOLD) windows do not contaminate the baseline. The effective band is the
  **intersection** of the empirical band and the Layer 1 rails: the rolling baseline can
  tighten the rails but never widen past them, so slow degradation cannot normalize
  itself into the baseline.

**History store: `integrity_monitor` itself, via the `subject` column.** Confirmed
appropriate, not just convenient: the only other writer, `vocabulary_drift.py`
(`src/config/vocabulary_drift.py:182-215`), already uses `subject` as a generic stratum
key (namespace strings), and the unique constraint already includes
`COALESCE(subject, '')`. Write one row per stratum EVERY run (metric_name
`guard_fail_fraction`, subject `tf=<tf>|group=<group>`, threshold_value = the nearest
violated/applicable bound, passed per verdict). This is the key semantic change: today
`regime_shift_fraction` is written only on HOLD, so no calibration history ever
accumulates; writing every run is what makes the threshold self-correcting. Volume is
~6-12 rows per corpus run, trivial at 10x. Step 0's idempotency IN-list gains the new
metric_name; the always-write behavior also keeps idempotency exact.

### Two-sided bracketing: one code path, asymmetric consequences

A single band check yields both tails; there is no reason for structurally distinct
code. Verdicts: `hold_high` (fraction above band: mass failure, possible dislocation)
and `alert_low` (fraction below band: suspicious mass passing, the todo 091 mirror).
Consequences differ deliberately:

- `hold_high` in ANY authoritative stratum: global hold of all transitions for the
  window (preserves current conservative semantics; now rare because calibrated).
- `alert_low`: WARNING + `passed=false` fact, NO hold. Wrong promotion is already gated
  by `recovery_min_observations`/`recovery_min_passes` counters across multiple runs,
  so one anomalous window cannot flip status by itself; holding on the low tail would
  let an overconfident-CI bug re-create the permanent-latch defect this todo removes.

One design fix rides along: on hold, still run Step 6 (staleness gauge). Skipping it on
hold was incidental, and the gauge is diagnostic-only.

### Purity: decision as a pure function in ic_math.py

Following the `ic_math.py` extraction precedent, the decision takes data in, returns a
verdict, touches no DB/clock/config:

```python
@dataclass(frozen=True)
class GuardVerdict:
    status: Literal["ok", "hold_high", "alert_low", "insufficient_cells"]
    band_lo: float
    band_hi: float
    band_source: Literal["seeded", "empirical"]
    n_history: int

def evaluate_guard_fraction(
    fail_fraction: float,
    n_cells: int,
    history: Sequence[float],  # this stratum's prior fractions, oldest to newest
    *,
    min_cells: int,
    min_history: int,
    band_z: float,
    rail_lo: float,
    rail_hi: float,
) -> GuardVerdict: ...
```

`_run_lifecycle_hook` does the I/O: stratified query, history read from
`integrity_monitor`, one `evaluate_guard_fraction` call per stratum, verdict writes.
Testable in isolation: cold-start rails, warm-band takeover at min_history, MAD
robustness to injected anomalies, floor skip, both tails, rail-intersection clamping.

### APR keys (all new keys grounded; the broken one retired)

| key | seed | provenance |
|---|---|---|
| `alpha.decay.guard_fail_rate_max` | 0.995 | `[rca_analysis]` (EIC-04 base rate, this session's RCA) |
| `alpha.decay.guard_fail_rate_min` | 0.85 | `[rca_analysis]` (4-7x base pass rate = anomalous) |
| `alpha.decay.guard_band_z` | 3.0 | `[conventional]` (three-sigma, robust-scaled) |
| `alpha.decay.guard_min_cells` | 100 | `[conventional]` (binomial SE argument in description) |
| `alpha.decay.guard_min_history` | 8 | `[conventional]` (min N for a scale estimate; mirrors recovery_min_* gating) |
| `alpha.decay.guard_history_window` | 20 | `[conventional]` (rolling evaluation window) |

`alpha.decay.regime_shift_fraction` (0.60 `[initial_estimate]`): remove the code read in
`ICEngineConfig.from_apr()` (`services/ic_engine.py:562-571`) and mark the
`config_schema` description as superseded by the guard band keys; keep the row for
`config_history` lineage rather than deleting it.

## Sizing

**Todo-sized, not a GSD phase.** Against the Phase 162 precedent's criteria: no open
design question remains after this file (grain, cold-start, both tails, and purity are
all decided here); no new table (reuses `integrity_monitor.subject`); the only
migration is a routine APR seed INSERT; effort is roughly one day (pure function +
tests + Step 3 rework + stratified query + history read); and correctness risk is
contained to lifecycle gating with fail-safe skip semantics. Coordination note only:
Phase 162 touches the same file's compute path (`_compute_symbol_tf`/
`_compute_cross_sectional_tf`), zero function overlap with this lifecycle path, but
avoid two concurrent branches editing `ic_engine.py`; land in either order, rebase is
trivial.

## Sanity check: `_evaluate_staleness` untouched

`_evaluate_staleness` (`services/ic_engine.py:2935`) stays exactly as is: it is already
a pure function, wall-clock diagnostic, ALERT-only, with no coupling to the guard's
threshold or stratification. The only interaction is the Step 6 ordering fix above
(emit the gauge even on hold), which changes the call site, not the function.

## References

- `services/ic_engine.py:2654` `_run_lifecycle_hook`; `:2673-2690` Step 0 idempotency;
  `:2696-2719` flat pooled query pinned to `config.lookahead_mid`; `:2787-2815` guard +
  HOLD + `integrity_monitor` INSERT with `subject=NULL`; `:2935` `_evaluate_staleness`
- `services/ic_engine.py:562-571` `ICEngineConfig.from_apr()` decay key loads; `:538`
  `alpha.ic.lookahead.mid`
- `src/intelligence/statistics/ic_math.py:122` `_fisher_z_ci` (todo 091's suspect);
  home for `evaluate_guard_fraction`
- `src/config/vocabulary_drift.py:182-215` existing `integrity_monitor.subject` usage as
  a generic stratum key (the reuse precedent)
- `.planning/todos/pending/091-fisher-z-ci-empirical-null-miscalibration.md` open
  CI-too-narrow finding; the low-tail guard is its instrumentation, not its fix
- `.planning/todos/deferred/134-ic-engine-incremental-recompute.md` /
  ROADMAP Phase 162: the separate compute-path work on this file; no code overlap
- Live evidence (2026-07-19 session): first-ever `regime_shift_fraction` row,
  fraction=0.9618 at `training_window_end=2025-12-24`; per-(tf, is_pooled) IC/p-value
  table showing mean p ~0.42-0.52 and fdr_fail_rate 0.976-0.999 across all tfs; EIC-04
  documented pass rates 35/1585 = 2.21% and 54/1425 = 3.79%
