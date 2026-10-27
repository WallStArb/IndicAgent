---
phase: 187-research-core-recipe-book-selection-construction
plan: 05
status: code-complete; full battery run pending
completed: 2026-10-27
commits: [4599ed3f0]
requirements: [R-187-06]
---

# 187-05 summary: StepM through the E17 H0 battery

- `scripts/research/stepm_null_battery.py`: per battery cell, 1,000 null universes (family 1's
  four members and their equal-weight book), StepM at family-wise 0.05, size bound the upper
  99% binomial quantile (67 of 1,000); finished cells are appended to `<out>.partial.jsonl`.
- `null_battery.simulate_series` exposes each arm's null D_s series.
- Pass 1 (sample studentization) failed `slot_effects` at 74 of 67. `stepm` now studentizes
  each bootstrap draw by its own HAC se (`studentize="draw"`, the default); the probe put
  slot_effects at 52, gaussian 57, factor 63. Details: `187-05-BATTERY.md`.

Open: the full 13-cell battery under per-draw studentization was stopped by the memory reaper
before any cell was saved; it waits on the owner's restart go-ahead and must hold in every
gating cell before a selection set counts as a result.
