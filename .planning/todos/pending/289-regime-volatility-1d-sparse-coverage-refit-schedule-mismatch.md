# 289 - `regime_volatility`'s 1d-timeframe coverage is sparse — `refit_every_bars.1d` never re-validated against the new 250-bar windows

**Filed:** 2026-08-09
**Source:** Phase 172 plan 172-05 (corpus-wide `regime_volatility` relabel) execution
**Status:** pending, not blocking

## The situation

Phase 172's corpus-wide `regime_volatility` relabel completed with zero failed cells, but 1d
timeframe coverage is genuinely sparse relative to the other timeframes: 45% of 1d cells were
skipped, versus 8-11% at 5m/15m/1h. Even most "labeled" 1d cells only wrote their first
walk-forward segment.

Root cause (measured, not fixed): `alpha.hmm.walk_forward.refit_every_bars.1d = 252` is a
migration-292 default that predates this phase's `vol_window`/`vol_of_vol_window = 250`
reconciliation (plan 172-01's GO verdict, migration 308) and K=3's three-way state-occupancy
requirement. The refit schedule key was never re-validated against the new 250-bar observation
windows.

## What's needed

Investigate whether `refit_every_bars.1d` should change to fit the new window sizes and K=3
occupancy needs. This key is shared with the legacy `regime` (trend) family's walk-forward
schedule, so retuning it needs its own investigation and gate — it is not a `regime_volatility`-only
parameter and could affect trend-vintage labeling too.

## Where

- `alpha.hmm.walk_forward.refit_every_bars.1d` — `config_state`/`config_schema` APR key
- `.planning/milestones/v3.1-phases/172-hmm-regime-volatility-only-redesign/172-05-SUMMARY.md` — measured skip
  rates and root cause
- `.planning/milestones/v3.1-phases/172-hmm-regime-volatility-only-redesign/evidence/172-05-relabel-coverage.json`
  — per-cell coverage data

## Triage 2026-09-26 (backlog review with the owner)

Absorbed todo 427 (`completed/427-regime-volatility-1d-mostly-null-one-segment-per-symbol.md`): 1d regime_volatility on <=31% of rows for every symbol (SPY only 2010-11), same finding. Part of the regime refit bundle anchored on todo 248: one `regime_writer` refit lands 248, 286, 292, 289, 341 and 420 together. Order: 426 step 2 (per-chunk writes for UPDATE writers), then 290 (refit memory), then the refit, then 411's refresh. Regime columns can enter books as features (todo 435), so their correctness is on the feature path.

## 186-18 decision rule (written 2026-09-30 before the measurement run)

Measured on the post-186-13 kernel (training-slice gate) from stored bars only: no return or
forward return is read, so this is not a look at outcomes and adds nothing to any vintage count.

- Metric: the pooled 1d segment skip fraction per family, (degenerate + not converged + other gate
  reason) / attempted segments, at each `hmm_refit_every_bars_1d` in {126, 252, 504}, over the
  sample below. `hmm_initial_warmup_bars_1d` stays 504 at every schedule.
- Deciding value per schedule: the larger of the two families' pooled skip fractions.
- Rule: keep 252 if its deciding value is within 0.02 of the smallest deciding value across the
  three schedules; otherwise pick the schedule with the smallest deciding value.
- Reported, not used to decide: the labeled fraction of rows after the first boundary, and the
  dominant skip reason.
- Sample: all `compute_eligible_1d` names when the runtime estimate is at most 3 hours, else the
  200 names first in sha256(symbol) order. Estimate from `manifest.json`'s measured 1d runtimes
  (trend 1.6 to 5.8 s, volatility 0.1 to 0.4 s per name at 252, about 7x for the three schedules
  together, 6 workers): at most about 43 s per name x 931 names / 6 = about 1.9 h, so all names.
