---
status: pending
priority: P1
filed: 2026-08-04
source: architecture review of the feature_registry -> concept_registry unification (todo 118)
  and the broader "where do we see what has edge" question -- checked feature_ic_scores against
  timescaledb_information.hypertables while auditing the measurement/governance/reporting split.
---

# `feature_ic_scores` is a plain Postgres table, not a TimescaleDB hypertable -- no chunking, no compression, no retention policy on the platform's core edge-measurement table

## What

`feature_ic_scores` is the raw source of truth for "does this feature have edge" -- one row
per (feature_name, symbol, tf, regime, lookahead_bars, training_window_end), already at
2,924,007 rows for a single training_window_end (2025-12-24). It is time-partitioned in
principle (a new corpus run adds a new training_window_end slice over the whole feature x
symbol x tf x regime x lookahead cross product) but verified against live DB it does not
appear in `timescaledb_information.hypertables` at all -- it is a plain table, so there is no
chunk_time_interval, no compression policy, and no retention/drop-chunks job (confirmed via
`timescaledb_information.jobs`, zero rows for this table).

CLAUDE.md's own performance-investigation-sop calls out chunk count/compression status as a
first-class suspect for exactly this shape of table (millions of rows, TimescaleDB, batch
writer). Every subsequent corpus run appends another full cross-product slice with no pruning
mechanism -- this table only grows. Once the corpus pipeline resumes its normal cadence
(currently mid-rebuild per Corpus Pipeline state notes), each new training_window_end adds
~3M more rows with no compression and no eviction path, on a table with no partitioning to
make old-slice reads/writes cheap.

Two independent asks, don't conflate:
1. Convert to a proper hypertable partitioned on `training_window_end` (or `computed_at`),
   matching the pattern already used by `concept_transition_log`/other hypertables in this
   schema. Needs a migration (backfill existing rows into the new hypertable, verify PK/unique
   index compatibility with partitioning -- several of feature_ic_scores' existing unique
   indexes are partial (`WHERE is_pooled = true AND symbol = 'POOLED'` etc.), check these
   convert cleanly).
2. Decide a retention/compression policy: does old training_window_end history need to stay
   query-hot forever (walk-forward / decay-rate research wants years of history), or should
   older slices compress/roll off after N corpus cycles? This is a judgment call for the
   project owner, not something to default silently.

## Why P1, not P0

Not an active incident today -- the table is currently frozen at a single stale
training_window_end, so nothing is actively degrading right now. But it is exactly the kind
of "survives 10x volume?" failure this project's design mindset checklist calls out, and the
corpus rebuild in flight will start adding new slices soon. Fix before the next few corpus
cycles land, not after a query on this table shows up in a slow-query investigation.
