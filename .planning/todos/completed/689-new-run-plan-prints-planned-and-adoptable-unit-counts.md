---
objective: O1
status: completed
priority: P2
filed: 2026-11-28
source: indicagent-03 (lead), successor-run adoption proof
---

# The new-run plan prints planned and adoptable unit counts

## What

`services.corpus_rerun --new-run --plan-only` prints rows only: the bar-based estimate (`fetch_row_counts`, tradeable bars from each name's proven start) next to the stored rows of adoptable units. The two are different measures, so a run that adopts every unit still shows a gap (2026-11-28: 27,557,393 planned against 24,417,050 stored for a successor that adopts all 515 units of run dcb7caa4). The gap read as "3.14 M rows would compute" and held the launch until a by-hand proof matched every planned `batch_key` against the stored `provenance_batch` rows (515 of 515 both ways, 0 digest-blind).

`_print_plan` should print, per tf, the planned units, the units already completed under that identity (adopt) and the units to compute, from the same `planned_units` and `_COMPLETED_KEYS_SQL` that `stored_row_counts` already runs, and label the row line as a bar-based estimate. Record the three counts in `measured` at `--new-run`.

## Done when

The plan line reads `1d units: planned N, adopt A, compute C`; `tests/unit/services/test_corpus_rerun.py` covers a full-adopt and a partial plan. `corpus_rerun.py` is outside the rebuild code key (check `module_files()` before landing; if it is inside, land between runs).

## Closed 2026-11-28 (indicagent-b9)

`plan_run` takes the unit counts from the one planning pass `stored_row_counts` already makes (`Adoption`: stored rows, `UnitCounts` per tf, digest-blind symbol count). `--new-run` and `--plan-only` print `1d units: planned N, adopt A, compute C`, label the row line a bar-based estimate, and print the digest-blind symbol count when it is nonzero; `--new-run` records `unit_counts` and `digest_blind_symbols` in `measured` (`launch_measured`). Adopt is every completed `batch_key`, as the stage skips them without looking at blindness; blindness is a plan-wide symbol set, so it is reported as a count, never split per unit. Tests: full-adopt, partial, digest-blind and the printed and recorded lines. `corpus_rerun.py` is outside the rebuild code key (487f4ab434 before and after). Not covered: a `--plan-only` refused by the span budget still prints no unit line.
