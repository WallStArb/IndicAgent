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
- `.planning/phases/172-hmm-regime-volatility-only-redesign/172-05-SUMMARY.md` — measured skip
  rates and root cause
- `.planning/phases/172-hmm-regime-volatility-only-redesign/evidence/172-05-relabel-coverage.json`
  — per-cell coverage data
