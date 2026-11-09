---
status: pending
priority: P2
filed: 2026-11-09
source: 0b's registry reconciliation lane (601 findings, 8dca39ff5); simplify-pass altitude finding
---

# Feature registration wired into the add-list path (close the forgotten-concept-row class)

## What

The registry drift class is structural: a stored-column landing (migration 526 was the instance
measured: kernels + columns + APR seeds) can ship while the `concept_registry` row is a forgotten
manual step, so a stored, measured column exists with no registered concept. The 601/0b
reconciliation found two live instances (`high_low_spread`, `roll_spread`, fixed by migration
585) and the class generalizes: every future add-list column risks the same gap, and the E21
sweep counts features through their registered concepts, so an unregistered column is invisible
to counting.

## Do

1. Wire concept registration into the add-list path: when a landing adds a stored feature
   column (kernel registry output plus `feature_vectors` column), the same change registers the
   `candidate` row through `ConceptRegistryService` (or a migration following the 585 template
   when the service cannot run in a migration context). The gate is mechanical: the
   kernel-registry outputs and the concept rows reconcile, the same way
   `test_doc_schema_numbers` reconciles doc numbers against code.
2. Add the reconciliation check as a CI test: every stored numeric `feature_vectors` column has
   a concept row, and every active concept row has either a stored column or an explicit
   kernel-only annotation (metadata key), so the 19-name class and the
   `days_to_month_end` class both fail loudly next time.
3. Item 0 (trivial, first): fix the stale docstring in `ops_concept_registry_override` - it
   claims free-text reasons are unpersisted, but the CLI passes `--reason` into
   `concept_transition_log.notes` (verified 2026-11-09).

## Gates

`/simplify` and `/review` on the check; `pytest tests/unit/ -n auto`; no DDL expected (data and
test code only). Registered rows only through `ConceptRegistryService` or the 585 data-migration
template.

## Notes

The calendar_cycles vestigial declaration (declares the days_to_month_end output from ts_dt,
consumed by no kernel) is flagged for the feature-factory lane, not this todo.
