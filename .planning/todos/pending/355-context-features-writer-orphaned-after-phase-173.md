---
status: pending
priority: P2
filed: 2026-08-25
source: Phase 173 Plan 02 (173-02-PLAN.md Task 2) -- surfaced while deleting ic_engine.py's
  bespoke CONTEXT_FEATURES daily-cadence significance path
---

# context_features table's sole documented consumer (ic_engine.py) is gone -- writer now
# has no downstream reader

## What

`scripts/infrastructure/backfill/infrastructure_context_features_writer.py` writes daily rows
for `flight_quality`, `yield_slope_z`, and `vix_z` into the `context_features` table -- 2,995
rows each as of the last check during Phase 173 planning (2026-08-24). That script's own
docstring names the IC engine as this table's consumer.

Phase 173 Plan 02 deleted `ic_engine.py`'s only query against `context_features` (the
daily-cadence significance path, `CONTEXT_FEATURES` frozenset -- see the sibling todo 354 for
the measurement-integrity side of this same deletion). After that deletion,
`grep -c context_features services/ic_engine.py` returns 0: `ic_engine.py` has no code path
that reads this table anymore.

**Nothing is lost by this** -- `feature_vectors` carries the same three columns
(`flight_quality`/`yield_slope_z`/`vix_z`), populated per-bar rather than per-day, and those
columns are still measured (now via the ordinary per-symbol intraday path, subject to the
temporal-pseudo-replication issue tracked separately in todo 354). The `context_features`
table's daily rows are redundant with `feature_vectors`' own copy of the same three series, not
a unique data source.

## Why this matters

`infrastructure_context_features_writer.py` presumably still runs (systemd timer status not
re-checked as part of this todo's filing -- verify before acting) and continues writing daily
rows into a table with zero remaining consumers. This is exactly the kind of drift CLAUDE.md's
DAG-invariant discipline exists to catch: an unowned writer with no downstream reader is dead
infrastructure that looks alive (the job keeps succeeding, `job_completed_total` keeps
incrementing) while producing no value.

## What needs to happen (decision not made by Phase 173 -- deliberately deferred)

Two options, either is fine, but the decision has not been made:

1. **Retire the writer and drop the table.** Since `feature_vectors` already carries equivalent
   per-bar values for all three features, `context_features` and its writer are pure
   redundancy once `ic_engine.py` stops reading them. Retire the systemd unit/timer (verify
   which one first), then drop the table in a migration.
2. **Repoint the writer at a real consumer.** If some other planned consumer wants a clean
   daily-cadence (not per-bar-duplicated) version of these series -- e.g., the temporal-
   decimation fix proposed in todo 354 could plausibly read FROM `context_features` instead of
   reimplementing `DISTINCT ON (DATE(bar_ts))` deduplication against `feature_vectors` -- keep
   the table and writer, but document the new consumer explicitly so it doesn't drift orphaned
   again.

Phase 173 deliberately did NOT decide between these -- Plan 02's scope was the ic_engine.py
deletion only, gated on proving zero live rows were lost by that specific deletion (see the
pre-deletion gate result: `feature_ic_scores` had 0 rows with
`regime_label_source='context_features'` at 2026-08-25T16:02:30Z), not on resolving the
writer's now-orphaned status.

## Scope

File for future prioritization. Check `systemctl list-timers | grep context.features` (or
equivalent unit name) before acting, per CLAUDE.md's "all systemd timers are confirmed disabled
as of 2026-07-02" caveat -- the writer may already be dormant rather than actively accumulating
more orphaned rows.
