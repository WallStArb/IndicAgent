---
phase: 187-research-core-recipe-book-selection-construction
plan: 06
status: complete
completed: 2026-10-27
commits: [723f07e62]
requirements: [R-187-07]
---

# 187-06 summary: the E18 switch

- Ledger: `RunRequest.mode` (`real` or `exploration`); exploration runs are recorded and counted
  but may repeat a spec; the book-test refusal past M is gone (`budget_m` stays on book_test
  rows as the power bar's divisor and as disclosure).
- Runner: `run_family(mode="exploration")` skips the spec-once gate and the shift-null
  diagnostic; `run_spec.py --mode exploration` (family specs only, a book spec is refused
  before any I/O with exit 2).
- `scripts/research/select_books.py`: StepM over every charged attempt of the vintage from
  `research_run_series` (statuses other than refused and guard_failed, `started` included); a
  charged run without a series refuses unless `--disclose-missing`, which lists it with its
  status. A book's horizon is the longest of its families'.
- Migration 516 (applied live): `alpha.selection.stepm.{fwer 0.05, block_mean_sessions 20,
  reps 2000, seed 187}`; budget_m and screen_alpha descriptions restated for E18.
- Methodology ledger E18: implementation note (per-draw studentization, the plan 05 battery
  numbers, the power-bar question left to plan 07).

Verification: full unit suite, ledger integration tests, repro_frozen bit-identical; /review
findings fixed (silent drop of `started` rows, exit code, horizon over all families, cached
git reads, dead columns).

Open: `select_books` has not been run live, and no selection set is a result until the full
13-cell per-draw StepM battery holds (its run was stopped by the session memory reaper and
waits on the owner's restart). The backfill of the 20 pre-515 series is also pending (12 of 20
replayed equal before the stop).
