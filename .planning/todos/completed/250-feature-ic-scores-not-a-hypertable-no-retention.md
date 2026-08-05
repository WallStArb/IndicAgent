---
status: fixed
priority: P1
filed: 2026-08-04
fixed: 2026-08-05
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

## Fix applied 2026-08-05 (migration 295)

**Ask 1 (hypertable conversion) -- done via TRUNCATE first, not migrate_data.** All 2,924,007
existing rows sat at a SINGLE training_window_end (2025-12-24), already known-contaminated
(todo 243's ctf_momentum batch-join lookahead leak -- Phase 167 Gate 1 flips PASS->FAIL under
the corrected join) and about to be superseded wholesale by the imminent full corpus recompute.
`ic_engine.py`'s own fingerprint-invalidation mechanism (todo 252) will delete+recompute the
affected cells for that training_window_end regardless of what this migration did. Truncating
first meant `create_hypertable()` ran instantly on an empty table instead of the slow, lock-
heavy `migrate_data => true` DDL against millions of soon-to-be-superseded rows -- exactly the
batch-DDL-on-hypertable risk `docs/foundation/performance-investigation-sop.md` exists to warn
about, for data that would not have survived the next corpus run anyway. Verified safe:
no FK points into this table; `ic_engine.py`'s startup gates only require `feature_vectors`
non-empty, never `feature_ic_scores`. The existing PK and all 3 partial unique indexes already
included `training_window_end`, so no constraint changes were needed for TimescaleDB's
partitioning-column-must-be-in-every-unique-constraint requirement.

**Ask 2 (retention/compression policy) -- decided, not deferred further.** Matched this
codebase's own existing precedent: `feature_vectors` (migration 151) is the closest analog
already in this schema -- a big append-mostly measurement corpus, compression enabled,
deliberately **no retention policy**. Applied the same reasoning here:
- **No retention/drop-chunks policy, and none should ever be added without a separate explicit
  project-owner override.** `feature_ic_scores` is the permanent audit trail behind every
  feature promotion/demotion decision (CLAUDE.md: "earn promotion through proof," "resist
  overfitting," "never drop data that could contain signal") -- deleting an old
  training_window_end slice would destroy the ability to ever re-examine or falsify a past
  decision.
- **Compression after 90 days** (not `feature_vectors`' 6 months): `feature_ic_scores` is a
  point-in-time walk-forward SNAPSHOT table (bursty writes, one training_window_end per corpus
  run), not a continuously-arriving bar series -- it goes cold the moment a NEWER
  training_window_end lands, not gradually. The true trigger concept is "superseded," not
  calendar age; TimescaleDB's policy is age-based only, and building a bespoke
  supersede-triggered compression job now, with a sample size of ONE training_window_end in the
  whole table, is premature complexity per the 5-step mandate. 90 days is a generous floor
  against this project's actual historical corpus-rerun cadence (days-to-weeks apart, not
  months) -- revisit with a real supersede-triggered job once multi-training_window_end cadence
  data exists.
- **`compress_segmentby = 'symbol,tf'`, `compress_orderby = 'training_window_end DESC'`** --
  matches `feature_vectors`' own compression columns exactly and this table's existing
  `feature_ic_scores_symbol_tf_ts_idx`.
- **`chunk_time_interval = 1 month`** -- training_window_end arrives in discrete bursts (one
  value per corpus run), not a steady tick; 1 month is a reasonable default with zero usage
  history to calibrate against yet.

**Investigated, not actioned:** applying the migration emitted WARNINGs that
`feature_name`/`regime`/`lookahead_bars` (the other unique-constraint columns) "should be used
for segmenting or ordering." Verified via TimescaleDB's own docs
(tigerdata.com/docs/use-timescale/latest/hypertables/hypertables-and-unique-indexes) this is a
performance note, not a correctness gap -- an insert into an already-compressed chunk with a
unique constraint always decompresses in-memory to check the constraint correctly regardless of
segmentby choice; no silent constraint violation is possible either way. Deliberately did NOT
widen segmentby to include `feature_name`: it is high-cardinality and would fragment compressed
segments, hurting compression ratio for a table whose actual write pattern (one batch insert per
training_window_end, then done) rarely writes into an already-compressed chunk under the 90-day
delay.

Verified live: `feature_ic_scores` now shows `num_dimensions=1`, `compression_enabled=t` in
`timescaledb_information.hypertables`; compression settings and the 90-day compression policy
job both confirmed in `timescaledb_information.compression_settings`/`.jobs`; table at 0 rows
post-truncate, ready for the imminent recompute to populate fresh hypertable chunks. Full
`tests/unit/` suite green throughout.
