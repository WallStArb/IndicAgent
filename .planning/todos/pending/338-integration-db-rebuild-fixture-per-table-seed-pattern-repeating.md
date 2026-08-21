# 338 - `tests/integration/conftest.py`'s per-table seed pattern has now repeated twice — watch for a third before generalizing

**Filed:** 2026-08-20
**Source:** `/simplify` altitude pass on commit `4ade8463b` (todo 293's `tag_vocabulary` seed fix).

## The pattern

`tests/integration/conftest.py`'s `_apply_baseline()` rebuilds `indicagent_test` from a
schema-only baseline dump (no data). Any reference table whose rows were seeded by a
pre-`_BASELINE_MIGRATION_CUTOFF` migration (DML, not DDL) ends up empty in the rebuilt test DB —
invisible until some post-cutoff migration's FK reference to one of those rows fails and blocks
the *entire* session-scoped rebuild fixture (not just one test).

This has now happened twice, same shape both times:
1. `instruments` (todo 064/119) — fixed with `seed_instruments_2026-07-18.sql`.
2. `tag_vocabulary` (todo 293, 2026-08-20) — fixed with `seed_tag_vocabulary_2026-07-18.sql`,
   same pattern.

## Why this is filed, not fixed

CLAUDE.md's own standing policy for exactly this shape of gap: "Two independent incidents hit the
same shape of bug two weeks apart; don't make it three" (re todos 149/161, TimescaleDB VACUUM).
Two occurrences is defensible as one-off fixes under YAGNI — generalizing `_apply_baseline()` to
auto-detect and seed every reference table with pre-cutoff DML dependencies would be real design
work (how to detect which tables need it, whether to snapshot-dump all small tables defensively vs.
reactively) that isn't justified by two data points. But nothing currently watches for a third.

## Fix, if a third occurrence happens

At that point, generalize: either (a) `_apply_baseline()` snapshot-dumps every small reference
table below some row-count threshold defensively (proactive), or (b) a one-time audit diffs
production's DML-seeded reference tables against what pre-cutoff migrations wrote data into, and
seeds all of them at once rather than waiting for each to individually break a test run (reactive
but complete). Until then: if a *third* table hits this exact failure mode, that's the trigger —
don't file a fourth narrow single-table todo, come back to this one instead.

## Priority

P3 — no live impact today (both known occurrences are fixed), purely a "watch for the third"
tripwire. Not a real gap yet.
