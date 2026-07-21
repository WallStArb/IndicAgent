# Regime-stratified OOS promotion gate + per-timeframe ensemble eligibility thresholds

Closes todo 165 (P0) and the `1h` portion of todo 164 (P1). Files a new follow-up todo for
164's `1d` portion (out of scope here — needs its own small-sample statistical methodology,
not a threshold tweak).

## Problem

**165.** `alpha.validation.oos_start = 2025-12-24` is a single fixed date. Every promotion
decision (143.1-08 included) evaluates its criteria against whatever regime that window
happens to be in, with zero regard for whether it's representative. 143.1-08's OOS window
(2025-12-24 to 2026-07-07) was a +8.82% SPY rally; the promotion gate answered "does this
help in a rally" (no), not "does this have real regime-conditional edge" (untested).

**164 (`1h` only).** Three APR keys in `ensemble_trainer.py`
(`alpha.ensemble.min_passing_features=5`, `max_feature_weight=0.20`, `meta_fdr_min_cells=3`)
are global constants calibrated for `5m`/`15m`'s data volume. `1h` has comparable statistical
power to `15m` (median effective-N 13,754 vs. 39,776, CI width 0.0515 vs. 0.0514) but only
1,395 base-eligible cells vs. `15m`'s 4,185 (~1/3) — a population-scarcity problem, not a
power problem. Live-verified: `1h` strata are attempted on every regime and skipped on every
regime, purely from never assembling `min_passing_features=5` distinct qualifying features
in one stratum.

## Design — 165: regime-stratified OOS gate

**Regime source:** `alpha_frames.regime` (per-symbol HMM label), not `market_regimes.regime_label`
(cross-sectional). Verified empirically against the COVID window (2020-02-20 to 2020-03-25):
across thousands of (timestamp, symbol) pairs, only 6 timestamps show more than one distinct
regime label across the full ~71-symbol universe — independent per-symbol HMMs converge on
shared states during real systemic events. The theoretical "pooling confound" risk doesn't
hold up in the data. Using `alpha_frames.regime` also means zero new joins and reuses the
exact same regime vocabulary the existing in-sample FRAME-04 gate (`evaluate_frame_gate`)
already groups by — one shared regime definition end-to-end.

**No new in-sample data is ever read for gating.** Only `bar_ts >= oos_start` rows are used.
Reaching into in-sample data to "test" a regime the OOS window happens to lack would be
circular — the strategy could have been (even implicitly) shaped against that data.

**Shared core, not a duplicate.** Generalize `evaluate_frame_gate()`
(`services/counterfactual_tracker.py`) to accept an optional grouping-key function,
defaulting to `lambda row: (row["tf"], row["regime"])` — preserving today's FRAME-04
in-sample behavior byte-for-byte (tested via equivalence, same pattern used for the
`sign_symmetric` predicate in `ensemble_trainer.py`). The new OOS promotion path calls the
same core with `lambda row: (row["direction"], row["regime"])`. One day-clustered bootstrap
engine, two callers.

**Tri-state per cell, not pass/fail.** Today's frame-count floor (`alpha.scoring.min_strategy_n`,
frame-count-based) is not the same thing as a day-cluster-count floor — a cell can clear 30+
frames while resting on single-digit day-clusters (e.g., observed OOS `high_neutral` short:
261 frames, 8 days). Day-clusters are the real independence unit under day-clustered
bootstrapping. New APR key `alpha.validation.regime_gate_min_clusters` (`[initial_estimate]`,
proposed 20) classifies each `(direction, regime)` cell as:
- **INSUFFICIENT** if day-clusters < floor — excluded from the verdict, reported explicitly
  as "not enough OOS data to evaluate this regime," never silently counted as pass or fail.
- **PASS/FAIL** otherwise, via `frame_gate_passes` unchanged (`ci_lower > 0`).

**Pre-registration discipline.** `regime_gate_min_clusters` must be frozen the moment this
lands — never adjusted in response to seeing whether a specific promotion decision passes.
Same "no post-hoc gate renegotiation" discipline already documented for
`frame_gate_passes`'s `bootstrap_random_state` (WR-01). Document this explicitly at the APR
key's description field.

**Verdict combination:** PROMOTE only if every adequately-sampled cell passes (`ci_lower > 0`)
AND no adequately-sampled cell shows confident loss (`ci_upper < 0`, extends today's C7).
This is functionally a worst-regime-gate restricted to regimes the OOS window actually
samples adequately — intentionally conservative. A real edge that's weak in exactly one
adequately-sampled bucket can still HOLD under this; that's accepted as honest, not
papered over.

**Scope-narrowed from the todo's literal "all criteria" framing:** C1 (60-day floor), C3
(Sharpe), C4 (max drawdown), C6 (non-regression vs. champion) stay pooled, unstratified.
Sharpe and max-drawdown are multi-day path statistics — computing them on an 8-25 day
regime slice is not a meaningful estimate (annualizing a Sharpe from single-digit trading
days is statistically indefensible). C2/C7 are the two criteria whose day-clustered
bootstrap machinery is specifically designed to degrade gracefully (or get excluded via the
INSUFFICIENT floor) on thin cells; C3/C4 have no equivalent small-N-aware treatment and
extending naive stratification to them would manufacture false precision, not honesty.

**No new rolling/expanding-OOS-window machinery.** `oos_start` is fixed and production
keeps writing new frames forward every day, so regime coverage in the OOS window improves
for free as calendar time advances. Building an expanding-window mechanism now solves a
problem time already solves.

**Retroactive application:** update `scripts/analysis/phase143_1_08_shadow_validation.py`
to call the new stratified path and re-run it against the real champion/challenger data,
producing 143.1-08's actual updated (coverage-annotated) verdict — per the todo's own
instruction not to treat the current HOLD as final.

## Design — 164 (`1h` portion)

**Per-timeframe APR resolution**, exact precedent from `alpha.frame.hold_max_bars.<regime>.<tf>`
(`services/alpha_frame_writer.py`): `alpha.ensemble.min_passing_features.<tf>`,
`alpha.ensemble.max_feature_weight.<tf>`, `alpha.ensemble.meta_fdr_min_cells.<tf>`, each
falling back to today's global default when unset. `5m`/`15m`/`1d` behavior is byte-identical
(no per-tf key set for them) — zero risk to what's already working.

**Both `min_passing_features` and `max_feature_weight` stay independently-settable, visible
APR keys** (not collapsed into a derived formula). The project explicitly built
`/config/parameters` for per-key operator visibility and change history; hiding
`max_feature_weight` behind a computed relationship would make it invisible there. Instead,
add a **startup feasibility assertion**: for every timeframe with either key overridden,
assert `min_passing_features * max_feature_weight >= 1.0` (the exact constraint migration
164's SQL comment already documents for the global pair), raising loud rather than silently
producing an infeasible/degenerate weight vector if a human ever sets an inconsistent pair
via the dashboard. Direct application of this project's "silent wrong answers are worse than
loud crashes" principle.

**Seed values:** `min_passing_features.1h = 3`, `max_feature_weight.1h = 0.34`
(`3 * 0.34 = 1.02 >= 1.0`, feasible with slight slack), both `[initial_estimate]`.

**`meta_fdr_min_cells.1h`: mechanism built, no value seeded.** The todo's own live-debug
evidence pins 1h's current failure to `min_passing_features` (0 strata written on every
regime tested) — `meta_fdr_min_cells` isn't shown to be the binding constraint. Seeding a
number with no evidence behind it would be undisciplined tuning. Defer: after the two seeded
keys land, empirically check via a throwaway `ensemble_trainer.py` re-run whether `1h` now
writes strata; if it still doesn't, check whether `meta_fdr_min_cells` is now the binding
gate before touching it.

**`_process_stratum`/`_meta_eligible` need the raw APR `cfg` dict threaded through**
(currently only the frozen `EnsembleConfig` snapshot is passed) so `tf`-keyed resolution can
happen inline. `cfg` is already loaded once at startup (`_load_apr`, unchanged) — passing it
alongside `config` does not violate `EnsembleConfig`'s "no mid-run drift" contract; no new
DB round-trip is introduced.

## Out of scope — filed as new follow-up todo

**164's `1d` portion.** Median effective-N 1,222 (min 143), CI width 3x wider than every
other timeframe — a genuine small-sample power problem, not a threshold miscalibration. Per
the existing todo's own text, this needs a properly small-sample-appropriate statistical
treatment (e.g. a Bayesian shrinkage IC estimator, or a day-clustered bootstrap calibrated
for 1d's achievable cell count) — real methodology work, scoped as its own plan, not
attempted here.

## Testing

- Unit tests for generalized `evaluate_frame_gate` grouping-key parameter: default behavior
  unchanged (existing tests), new `(direction, regime)` grouping produces correct cells.
- Unit tests for the tri-state classification (INSUFFICIENT vs. PASS vs. FAIL) at the
  `regime_gate_min_clusters` boundary.
- Unit tests for per-tf APR resolution in `ensemble_trainer.py` (mirrors existing
  `hold_max_bars` resolution test pattern) and for the new feasibility assertion (passes when
  feasible, raises when not).
- Live verification (not just unit tests): throwaway `weight_version` re-run of
  `ensemble_trainer.py` confirming `1h` now writes strata (cleaned up after, mirrors prior
  session's `debug_1h_investigation` pattern); re-run of
  `phase143_1_08_shadow_validation.py` against real data producing the actual updated
  143.1-08 verdict.
