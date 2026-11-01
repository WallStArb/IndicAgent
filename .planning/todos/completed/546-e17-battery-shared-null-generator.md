---
status: pending
priority: P2
filed: 2026-10-27
source: indicagent-5b, review of the research lane against the design mindset (owner 2026-10-27)
---

# One shared H0 generator for the E17 batteries

## What

Three battery modules (`null_battery.py`, `null_battery_overnight_intraday.py`,
`null_battery_daily_residual.py`) each re-implement the same H0 stresses: Student t4 noise,
volatility clustering (AR(1) log-vol 0.97, shock sd 0.15), a common factor with uniform
loadings, static per-cell means and late listings. Phase 184's persistent battery (184-05) would
add a fourth copy. Copies drift: a fix to one stress in one module silently leaves the other
families' gates certified on the old one.

## Plan

1. One pure generator, `null_panels.py`: a row layout (cells per session) and a stress spec in,
   H0 returns out; each family battery keeps only its own panel shape, members and target.
2. Every existing cell must reproduce bit for bit at fixed seeds (the 187-08 check pattern),
   so no recorded battery result or static gate moves.
3. Land it after the batteries now running finish (never edit a module a live battery
   imports), and before 184-05 so the persistent battery is built on it.

## Done when

The three modules share the generator, every existing cell is bit-identical at fixed seeds, and
184-05 builds on it.

## Landed (research lane, session b0, 2026-11-01)

`src/intelligence/research/null_panels.py`: the five stresses as single-sourced primitives
(noise, vol_clustering, cell_means, factor_term, listing_starts/listing_mask) with the stress
constants (t4 dof and variance scale, AR(1) 0.97/0.15, the loading range, the 60% late span) in
one place. The three battery modules compose the primitives in their original draw order and
keep only their own panel shapes, members and targets.

Bit-identity: ten panel/target hash pairs (five scenario-seed pairs spanning every stress,
captured from the pre-refactor inline code immediately before the refactor) pinned in
tests/unit/test_null_panels.py, all passing; repro_frozen bit-identical (the modules are in the
repro ring). One historical divergence surfaced and preserved behind a documented flag: the slot
and legs batteries draw factor loadings before the shock, the daily battery draws the shock
first — swapping the order changes values at a fixed seed, so the flag keeps every family's
pins. 184-05 builds on the primitives.
