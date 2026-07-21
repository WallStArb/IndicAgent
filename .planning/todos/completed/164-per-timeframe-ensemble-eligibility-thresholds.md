---
status: pending
priority: P1
filed: 2026-07-21
source: found investigating why 1h has produced zero alpha signals (long or short)
  since ensemble_trainer's methodology went live; user confirmed domain conviction
  that 1h carries real signal and directed treating the exclusion as a miscalibrated
  threshold, not an open question needing more proof.
---

# min_passing_features / max_feature_weight / meta_fdr_min_cells are global constants calibrated for 5m/15m's data volume -- they structurally exclude 1h and mismeasure 1d

## What's wrong

Three APR keys in `ensemble_trainer.py` are single global constants applied identically
across all four timeframes, despite those timeframes having wildly different achievable
statistical evidence:

- `alpha.ensemble.min_passing_features = 5` -- mathematically tied to `max_feature_weight`
  (migration 164: `5 * 0.20 = 1.0`, the minimum feature count for a valid normalized weight
  vector under the cap). Not arbitrary in isolation, but never revisited per-timeframe.
- `alpha.ensemble.meta_fdr_min_cells = 3` -- cross-cell replication requirement in
  `_meta_eligible()`, before a feature's per-cell significance is even considered.
- `alpha.ensemble.max_feature_weight = 0.20` -- concentration cap.

## The two failure modes are DIFFERENT and need different fixes -- confirmed empirically, not assumed

**`1h` is NOT power-starved.** Median effective-N (`n_independent`) = 13,754, CI width
(`ic_ci_upper - ic_ci_lower`) = 0.0515 -- statistically indistinguishable from `15m`'s
median N=39,776 / CI width=0.0514. Per-stage funnel pass rates (base eligibility, FDR) are
also comparable to `15m`'s at every stage. The problem is purely **population size**: `1h`
has only 1,395 total base-eligible (symbol x regime x lookahead) cells vs `15m`'s 4,185 --
roughly 1/3. That smaller population mechanically produces fewer (feature, cell) pairs for
`_meta_eligible()`'s cross-cell consistency check to accumulate evidence from, leaving only
3 total meta-eligible feature names for `1h`, each concentrated in different regimes
(`momentum_z_fast`: `high_bear`, `low_neutral`, `mid_neutral` -- never co-occurring), so no
single `(1h, regime)` stratum can ever assemble 5 distinct qualifying features. Live-verified
via a real `ensemble_trainer.py --sign-symmetric` re-run (weight_version
`debug_1h_investigation`, cleaned up after): `1d` strata DID write successfully
(`high_bear`: 9 features, `mid_bull`: 5 features -- both cleared the floor), `1h` strata were
attempted (confirmed via the coverage-tracking fix, prior commit) and skipped on every
single regime.

**`1d` IS genuinely underpowered.** Median effective-N = 1,222 (min 143!), ~32x fewer than
`15m`. Avg CI width = 0.166 -- over 3x wider than every other timeframe. With ~20 years of
history fragmenting to ~5,000-7,500 daily bars total, further split across regime cells,
1d's `ic_ci_lower > 0` significance test is running with an order of magnitude less
statistical power than 5m/15m/1h. A real IC effect that would easily clear the bar at higher
frequencies can fail here purely from estimation noise (wide CI), not a weak point estimate.
This is a Type II error risk, not evidence of absent signal.

## What NOT to do

Do not just lower `min_passing_features` and raise `max_feature_weight` uniformly for
sparse timeframes as a blanket fix -- that manufactures coverage rather than earning it,
and produces a hidden-bias landmine: a concentrated 3-feature, 33%+-weighted `1h` ensemble
wearing the same `ensemble_alpha` label as a diversified 5-feature, 20%-capped `5m`/`15m`
ensemble, with wildly different statistical footing invisible to every downstream consumer.

## Fix direction (needs real design, not a parameter tweak)

**For `1h`** (population-scarcity problem, not power problem): make
`min_passing_features` / `max_feature_weight` / `meta_fdr_min_cells` resolvable per-timeframe
APR keys (e.g. `alpha.ensemble.min_passing_features.1h`), falling back to today's shared
default -- exact precedent already exists in this codebase
(`alpha.frame.hold_max_bars.<regime>.<tf>`, 36 keys). Calibrate `1h`'s values against its
*actual* achievable population (1,395 cells, ~1/3 of `15m`'s) rather than guessing --
e.g. a proportionally relaxed `min_passing_features` (3?) paired with a compensating
`max_feature_weight` (0.34, satisfying `3 * 0.34 ~= 1.0`) is a defensible starting point,
labeled `[initial_estimate]` per this project's APR provenance convention, not asserted as
final. `5m`/`15m` keep byte-identical current behavior (zero risk to what's already working).

**For `1d`** (genuine power problem): needs a properly small-sample-appropriate statistical
treatment, not a threshold tweak -- e.g. a Bayesian shrinkage IC estimator that correctly
widens its own uncertainty bounds rather than a frequentist CI too wide to ever exclude zero
with confidence at N~1,000-2,000, or a day-clustered bootstrap calibrated for the achievable
cell count (mirrors FRAME-04's own day-clustered bootstrap CI machinery, already built).
This is real methodology work, not a config change -- scope it as its own plan.

## References

- `services/ensemble_trainer.py`: `_meta_eligible()` (min_cells gate), `_process_stratum()`
  (min_passing_features gate), `EnsembleConfig`/`from_apr` (all three constants)
- `production/migrations/164_ensemble_tables.sql` -- the `5 * 0.20 = 1.0` math this is tied to
- Prior commit (this session): silent-skip logging fix that made this investigation possible
  (`fix(ensemble): never silently skip a stratum`)
- Live numbers above from direct queries against `feature_ic_scores`/`alpha_ensemble_ic` and
  a live debug re-run of `ensemble_trainer.py`, 2026-07-21 -- not theoretical

## Closed 2026-07-21 (1h portion only)

`1h` fixed via two migrations, not one — migration 245 alone (per-tf
`min_passing_features`/`max_feature_weight` override) proved insufficient on live re-run (1h
still wrote zero strata on every regime); root cause traced one gate upstream to
`meta_fdr_min_cells`, fixed with an emergent follow-up (migration 246,
`alpha.ensemble.meta_fdr_min_cells.1h=2`, live-queried against `feature_ic_scores` before
seeding). `_resolve_per_tf`/`_assert_feasible_thresholds` added to `services/ensemble_trainer.py`
with a startup feasibility assertion guarding `min_passing_features * max_feature_weight >= 1.0`.

Live-verified via a full completed `ensemble_trainer.py --sign-symmetric` re-run under a
throwaway `weight_version` (`debug_164_1h_verify2`, cleaned up after): the service's own
coverage-tracking mechanism confirms `{"tf": "1h", "n_attempted": 7, "n_written": 5}` —
5 of `1h`'s 7 regimes now write (`high_bear`: 4 features, `low_bull`: 3, `mid_bear`: 3,
`mid_bull`: 5, `mid_neutral`: 3), previously 0 on every regime. An honest partial fix, not
every 1h regime: `low_neutral` (2 meta-eligible features, one short of the floor) and
`high_neutral` (zero IC rows entirely, a different and deeper population gap) remain
unfixed, exactly as migration 246's own evidence predicted before the run. `5m`/`15m`/`1d`
unaffected (no per-tf key set, byte-identical default behavior: `5m` 15/6, `15m` 9/7, `1d`
4/2 attempted/written, matching the pre-existing baseline). `1d`'s genuinely different
small-sample power problem split out to **todo 166** (pending), per this todo's own scoping.
