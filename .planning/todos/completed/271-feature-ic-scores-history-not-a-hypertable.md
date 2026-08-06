---
status: fixed
priority: P1
filed: 2026-08-05
fixed: 2026-08-05
source: checking todo 252's closure note (feature_ic_scores_history's own design) while
  cleaning up PRIORITIES.md's stale P0 entries
---

# `feature_ic_scores_history` (todo 252's archive table) is not a hypertable either

## What

Todo 252 (closed 2026-08-04) added `feature_ic_scores_history` as the archive-before-delete
target for `ic_engine.py`'s fingerprint-invalidation mechanism -- an append-only audit trail of
every `feature_ic_scores` row that gets overwritten by a rerun against an already-computed
`training_window_end`. Same shape of gap as todo 250 (closed 2026-08-05, `feature_ic_scores`
itself): plain Postgres table, no chunking, no compression, no retention policy, despite being
exactly the shape CLAUDE.md's performance-investigation-sop warns about.

Already live and growing, not hypothetical: 29,382 rows as of 2026-08-05, despite the corpus
still being frozen at a single `training_window_end` -- fingerprint invalidation has already
fired for real.

## Different from todo 250 in one important way

`feature_ic_scores` was safe to truncate before converting (all rows were known-contaminated
and about to be superseded by an imminent recompute). `feature_ic_scores_history` is NOT --
its entire purpose is to be the permanent, never-recomputed audit record of what a feature's IC
looked like before each invalidating change. Truncating it would defeat the whole reason todo
252 built it. Conversion here needs `create_hypertable(..., migrate_data => true)`, not the
truncate-first shortcut -- acceptable at this row count (29,382), unlike the 2.9M-row concern
that motivated the truncate-first approach for `feature_ic_scores`.

## Design notes for the fix

- No PK, no unique constraint at all on this table (confirmed via `\d feature_ic_scores_history`
  -- genuinely append-only per todo 252's own design) -- simpler than `feature_ic_scores`'
  conversion, no unique-constraint-must-include-partition-column concern to solve.
- Partition column: `archived_at`, not `training_window_end`. Rows arrive keyed to when an
  invalidation event fires (real-world time), not the walk-forward data boundary they describe
  -- `archived_at` is what actually grows monotonically with inserts and is what TimescaleDB
  chunk exclusion should track.
- Compression delay should almost certainly be SHORTER than `feature_ic_scores`' 90 days:
  archived rows are cold from nearly the moment they land (read only for retrospective/audit
  queries, never re-touched by day-to-day operations) -- closer to the 30-day precedent already
  used for `forward_returns`/`ensemble_alpha`/`alpha_events` (migration 193) than
  `feature_ic_scores`' own point-in-time-snapshot reasoning.
- No retention/drop-chunks policy, ever -- even more directly than `feature_ic_scores` itself,
  since this table's entire purpose is being the permanent audit trail.
- segmentby/orderby: match `feature_ic_scores`' own choice for consistency (`symbol,tf`
  segmentby) rather than the high-cardinality `feature_name` the existing
  `feature_ic_scores_history_cell_idx` leads with.

## Fix applied 2026-08-05 (migration 300)

All design notes above implemented as specified: `create_hypertable(..., 'archived_at',
chunk_time_interval => '1 month', migrate_data => true)` -- no truncate-first shortcut needed
at this row count. Compression enabled (`symbol,tf` segmentby, `archived_at DESC` orderby),
30-day compression policy (shorter than `feature_ic_scores`' 90 days, per the "cold from the
moment it's archived" reasoning above), no retention policy.

Verified live: `num_dimensions=1`, `compression_enabled=t` in
`timescaledb_information.hypertables`; all 29,382 pre-migration rows confirmed present
post-`migrate_data`; compression policy job confirmed in `timescaledb_information.jobs`
(`compress_after: 30 days`). No FK constraints reference this table (checked before applying).
Full `tests/unit/` suite green throughout.
