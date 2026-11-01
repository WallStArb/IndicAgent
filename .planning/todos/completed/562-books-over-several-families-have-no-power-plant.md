---
status: completed
priority: P1
filed: 2026-10-29
source: found while testing 187-14 (tests/unit/research/test_runner_contribution.py stubs it)
---

# A book over several families cannot run: no power plant spans families

## What

`runner.check_family_plant` raises `RunRefused("no power plant spans N families")` for any book with
more than one family: the refusal-before-the-statistic power check plants a signal through one
family's `make_plant`, and no family module defines a plant that plants several at once. The S7
combiner exists to combine families (periodicity, residual, overnight) and 187-14's contribution
accounting (leave-one-family-out, Shapley) is only meaningful for them, but no such book can run today.
The 187-14 tests stub the check with the first family's plant.

## Plan

1. Decide the plant: one plant per family run in turn (each family's planted IC through the book's
   combiner, the power the minimum or the product), or a joint plant over the combined forecast.
2. Whichever it is, the battery certifies it (a power plant is part of the refusal rule) and
   `repro_frozen` stays bit-identical for single-family books.
3. Remove the 187-14 test stub.

## Done when

A two-family synthetic book runs through `run_book` without a stub, powered or refused on its merits, and
a real two-family book can be started.

## Landed 2026-11-01 (f6bbbe2e5)

Per-family plants in turn, the book's power the minimum over its families; the
one-family refusal is gone, the refusal names the underpowered families, the
187-14 stub is removed and the two-family synthetic book runs run_book
unstubbed. Single-family books take the exact old path (repro_frozen
bit-identical). Design note:
docs/plans/2026-11-01-multi-family-book-power-plant.md.
