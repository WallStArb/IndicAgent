# Phase 176 Plan 07: Earnings-Season Corpus Backfill — Recompute Log

Operational evidence for the migration-351 backfill of `feature_vectors.earnings_season_flag`
and `days_since_quarter_end` (plans 176-07 Task 1 pre-flight, Task 2 run telemetry, Task 3
coverage verification + `COVERED_SCOPE` manifest). Written as the work happened; nothing here
is projected from a plan — every number was observed against the live database on 2026-09-23.

---

## Task 1: Pre-flight gate (2026-09-23, ~13:45-14:00 UTC)

All five checks observed before anything was written. Any failure would have aborted the plan.

### Check 1 — competing corpus processes

```
$ ps aux | grep -E "backfill_feature_factory|ic_engine|regime_writer|forward_return_writer" | grep -v grep
(no output — exit 1 from grep = zero matches)
```

The todo-340 `--compute-only --symbols IHF --workers 1` run that was active at plan time
(2026-09-22 16:45) has exited. No corpus job owns `feature_vectors`.

### Check 2 — lock / chunk-operation check

```
SELECT pid, state, wait_event_type, wait_event, ... FROM pg_stat_activity
WHERE state <> 'idle' AND (query ILIKE '%decompress_chunk%' OR query ILIKE '%compress_chunk%'
  OR query ILIKE '%autovacuum%' OR ...hyper/feature_vectors...);
→ 0 rows

SELECT ... FROM pg_stat_activity WHERE backend_type = 'autovacuum worker'
  OR (state = 'active' AND now() - query_start > interval '5 minutes');
→ 0 rows

SELECT ... FROM pg_locks l JOIN pg_stat_activity a ... WHERE relation = feature_vectors
  OR relation IN (all 86 chunk regclasses);
→ 0 rows (no session holds any lock on the hypertable or any chunk)
```

No `decompress_chunk`/`compress_chunk`/autovacuum activity against `feature_vectors` (RESEARCH.md
Pitfall 5's 2026-09-22 contention window has fully cleared), no long-running queries, no lock
holders.

### Check 3 — schema and APR seed preconditions

```
information_schema.columns, feature_vectors:
  days_since_quarter_end | real | nullable YES
  earnings_season_flag   | real | nullable YES      (both exist — migration 350 landed)

config_state:
  feature.earnings_season.start_days = '14'   (text, castable to int)
  feature.earnings_season.end_days   = '42'   (text, castable to int)
```

Both APR values read at run time: **start_days = 14, end_days = 42**; `14 <= 42` so the window is
non-empty. The SQL reads these from `config_state` inside the statement (contract test forbids a
bare 14/42 literal), so an operator APR change between pre-flight and a future re-run is honored
by design.

### Check 4 — disk headroom (measured, not assumed)

Relation size (the parent-relation call returns 24 kB because data lives in chunks, so the
hypertable-level figure is the real one):

```
hypertable_size('feature_vectors') = 82,292,506,624 bytes (77 GB)   [== hypertable_approximate_size]
86 chunks, 86 compressed, 0 uncompressed (range 2005-09-24 → 2026-12-03)

Data filesystem (docker exec timescaledb df -h /var/lib/postgresql):
  /dev/mapper/ubuntu--vg-ubuntu--lv  913.3G total  335.1G used  540.1G avail  38% used
```

Gate arithmetic: required = 2.5 × 77 GB ≈ **193 GB**; available = **540.1 GB** → PASS.

Beyond the plan's 2.5x gate, the decompressed-heap footprint itself was probed rather than
estimated (the table is ~4.1x the row count it had at the migration-312 incident, so the 57 GB
prior does not transfer directly): decompressed the smallest chunk
(`_hyper_85_75954_chunk`, 2005 Q4, 30,969 rows), measured, recompressed it, and ran a bare
`VACUUM feature_vectors;` to leave the probe without residue:

```
decompressed chunk total relation: 43,819,008 bytes / 30,969 rows = 1,415 bytes/row (heap+index+toast)
post-recompress uncompressed chunk count: 0; hypertable size back to 77 GB
```

Extrapolated cost of the whole-table form on the live 108,639,338 rows:

| Phase | Δ disk | Free space after |
|---|---|---|
| decompress all chunks | +~154 GB (108.6M × 1,415 B) | ~386 GB |
| UPDATE rewrites every row (dead + new versions coexist) | +~154 GB worst case | ~232 GB |
| recompress + bare VACUUM reclaims dead tuples | −~154 GB | ~380 GB+ |

**Decision: whole-table form** (not the batched fallback). The plan's 2.5x gate passes
(540 > 193 GB) and the measured worst-case floor (~232 GB free at peak, >10x the 20 GB abort
line) makes batching unnecessary schedule risk. Batching changes the schedule, not the scope;
it stays documented here as the fallback if a re-run ever faces less headroom.

### Check 5 — baseline

```
count(*)                                       = 108,639,338
count(*) FILTER (earnings_season_flag IS NULL)     = 108,639,338
count(*) FILTER (days_since_quarter_end IS NULL)   = 108,639,338
```

Every row in the corpus is this backfill's responsibility (both columns were added as NULL by
migration 350; plan 176-03 only wired new-row compute). Row note: the plan's objective text
estimated "~40M rows"; the live corpus is 108.6M — the Phase 174-era universe expansion
(233 symbols present in `feature_vectors`) grew it since planning. Scope is whatever the table
holds, not the estimate. Per-tf breakdown: 5m = 75,051,415; 15m = 25,659,325; 1h = 6,961,503;
1d = 967,095.

### Artifacts written in Task 1

- `production/migrations/351_earnings_season_backfill.sql` — four-step round trip (APR guard →
  decompress → scoped two-column UPDATE → recompress → bare VACUUM), idempotent via
  `IS DISTINCT FROM` scoping, window bounds read from `config_state` at run time, temporary
  `_m351_*` SQL helpers written once and dropped in-transaction
- `tests/unit/test_earnings_season_backfill_contract.py` — 8 source-level assertions including
  the structural two-column SET-list parse (T-176-07-03's proof), no 14/42 literals, bare
  top-level VACUUM, `if_compressed => true`, idempotency scoping, RAISE EXCEPTION guard,
  explicit UTC cast
- TDD gates: RED commit `519e3cd70` (8/8 failing), GREEN after the migration landed (8/8 +
  `test_compressed_hypertable_migration_vacuum_check.py` all passing)
