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
