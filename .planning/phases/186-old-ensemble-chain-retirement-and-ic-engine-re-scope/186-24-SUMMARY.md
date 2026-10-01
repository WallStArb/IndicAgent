---
phase: 186-old-ensemble-chain-retirement-and-ic-engine-re-scope
plan: 24
subsystem: database
tags: [timescaledb, migration, feature-vectors, schema, registry]
requires:
  - phase: 186-15
    provides: kernel registry feature_columns() and UNOWNED_COLUMNS
  - phase: 186-18
    provides: regime kernels
provides:
  - feature_vectors_v2 empty hypertable (migration 425), 312 columns
  - evidence JSON with counted proofs for every dropped column
  - unit and integration guards pinning schema to registry
affects: [186-25, 186-26, 186-27]
key-files:
  created:
    - production/migrations/425_feature_vectors_v2.sql
    - .planning/phases/186-old-ensemble-chain-retirement-and-ic-engine-re-scope/evidence/186-24-feature-vectors-v2-schema.json
    - tests/unit/intelligence/test_feature_vectors_v2_schema.py
    - tests/integration/test_feature_vectors_v2_schema.py
  modified:
    - docs/foundation/glossary.md
key-decisions:
  - "Asian session pair kept: the vp_sr kernel computes it since 186-15, so the old table's zero counts no longer justify a drop"
  - "312 columns and 5 dropped feature columns, not 310 and 7"
requirements-completed: [D-34, D-37, D-16]
completed: 2026-10-01
---

# Phase 186 Plan 24: feature_vectors_v2 schema Summary

Migration 425 creates `feature_vectors_v2`: PK (symbol, tf, bar_ts), 1-year chunks, compression segmentby symbol,tf orderby bar_ts, no policy job, zero rows, 312 columns derived from the registry. The old `feature_vectors` is untouched (108,646,010 rows).

## Commits (branch phase-186-24)

- 1572884cc docs(186-24): counted schema evidence for the rebuilt feature_vectors table
- 6b6fe6bb6 feat(186-24): feature_vectors_v2 hypertable, 1-year chunks, compression without policy (migration 425)
- test(186-24): schema-to-registry guards for feature_vectors_v2
- this SUMMARY commit

## Process gate

`ps aux | grep -E "ic_engine|backfill_feature_factory|regime_writer|feature_vector_rebuild|ic_measure"` returned nothing.

## Evidence counts (old table, 2026-10-01)

- count(col) = 0 for momentum_rank_z, volume_rank_z, volatility_rank_z, regime_rolling (dropped) and for asian_session_high_dist_atr, asian_session_low_dist_atr (kept, see deviations).
- days_to_month_end vs 1 - month_position: 0 mismatches at 1e-6 for SPY, last 20000 rows of 5m, 15m, 1h and all 4834 1d rows (todo 115 duplicate proven).
- bar_close_ts = bar_ts + tf length: 0 mismatches on the same samples (dropped as derived).
- regime_label_source: one value, `filtered`, on all 108,646,010 rows (dropped).

## Deviations from Plan

**1. [Rule 1 - plan premise stale] Asian session pair kept.** 186-15 moved the pair into the vp_sr session-levels kernel (`kernels/vp_sr.py` computes `asian_session_high_dist_atr` and `asian_session_low_dist_atr`; they are in `feature_columns()` and no longer in `UNOWNED_COLUMNS`). The plan's own rule is that a computed column stays, so the table has 312 columns, not 310, and 5 dropped feature columns, not 7. Dropping them would have discarded a computed signal on the strength of a count that reflects the retired factory path. Recorded in the evidence JSON as `kept_computed` with the reconciliation text.

**2. `days_to_month_end` is inside `feature_columns()`.** The plan and 186-25 say it is already outside; it is not. It is dropped in this table by the proof above, so 186-25 must exclude it explicitly (the unit test's `expected_columns()` shows the derivation: `feature_columns() | UNOWNED_COLUMNS` minus the five dropped, plus keys).

**3. Catalog names.** TimescaleDB 2.27.1 has no `_timescaledb_catalog.hypertable_compression` or `hypertable.compressed_enabled`; the integration test and acceptance checks use `timescaledb_information.hypertables.compression_enabled` and `_timescaledb_catalog.compression_settings` (segmentby `{symbol,tf}`, orderby `{bar_ts}`).

**4. Migration number 425**, not 380: live tail was 424 (423 is the 480 session's rename in the main tree).

## Live schema checks

312 columns; PK `(symbol, tf, bar_ts)`; time interval 1 year; compression enabled; segmentby symbol,tf; orderby bar_ts; 0 `policy_compression` jobs (0 jobs of any kind); 0 rows; the five dropped feature columns and five metadata columns absent.

## Tests

- Unit guard: 3 passed. Integration (indicagent_test; migration 425 replayed by the conftest fixture, confirmed): 5 passed. Migration uniqueness and compressed-hypertable VACUUM checks pass.
- Full unit suite: see the final merged-main run in the coordinator report.

## Handoff for 186-25 and 186-27

- Target table: `feature_vectors_v2`; 312 columns (not 310); order keys, regime, regime_volatility, then registry order minus the five dropped.
- Dropped feature columns: momentum_rank_z, volume_rank_z, volatility_rank_z, regime_rolling, days_to_month_end. Dropped metadata: feature_vector_id, pipeline_version, feature_factory_version, bar_close_ts, regime_label_source. The drift report should treat the Asian pair as a compared column (old values all NULL, new computed).
- No scheduled compression policy by design: do not make `bulk_load` tolerate one; 186-27 adds it at the swap.
- Old table row count at handoff: 108,646,010.
- 186-25 and 186-27 plans hardcode 310 and "twelve dropped"; both need 312 and "ten dropped".

## Manual review

`/simplify` and `/review` cannot be invoked from an executor; the diff is one SQL file, one JSON, one glossary line and two small tests.

## Known Stubs

None.

## Self-Check

PASSED (files and commits verified before merge).
