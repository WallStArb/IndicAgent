---
status: completed
priority: P2
filed: 2026-11-04
source: /review of the feature_vectors one-name swap (todo 584 item 3, migration 570)
---

# Regenerate the integration baseline so indicagent_test has the kernel feature_vectors

## What

`tests/integration/conftest.py` replays migrations above 433 onto the 2026-10-02 baseline. Migration
462 drops `feature_vectors_v2` after that baseline, so the replay never has the kernel table. Two
things follow:

- Migration 569's unguarded `TRUNCATE feature_vectors_v2` stops the replay under ON_ERROR_STOP,
  so the session rebuild errors today.
- Migration 570 is guarded, so on indicagent_test it is a no-op, and `feature_vectors` there keeps
  the v1 schema while every reader and writer now targets the kernel schema.
  `tests/integration/test_feature_vectors_schema.py` and the integration `ic_measure` fixtures
  that insert v1 rows prove nothing about production.

Regenerate the six baseline/seed files from production after 570, bump `_BASELINE_MIGRATION_CUTOFF`
past 570, and move the integration fixtures that write v1 columns onto the kernel row contract.

## Done when

The integration session rebuild passes, `test_feature_vectors_schema.py` passes against the kernel
table, and no integration fixture writes a v1-only column into `feature_vectors`.

## Closed 2026-11-05 (indicagent-cb; migration 577)

- `scripts/infrastructure/regenerate_integration_baseline.py` writes all six fixtures in one
  command (schema-only dump, the four seed groups as `--inserts`, and the hypertables file built
  from the TimescaleDB catalog, `DESC` order terms included). Baseline 2026-11-05, cutoff 576; the
  2026-10-02/10-16 files are gone.
- `tests/integration/conftest.py` gains `_NOT_IN_BASELINE = {568, 571-574}`: numbers at or below
  the cutoff that the 587 landing reserved and had not applied when the dump was taken, so they
  still replay when they land. Empty it at the next regeneration.
- `tests/integration/test_ic_measure.py` seeds the kernel contract (no `pipeline_version`).
- Migration 577 (lead ruling 2026-11-05, applied live) dropped the 13 retired columns from the
  empty `feature_vectors` (the 11 D5 session columns, `hmm_vol_prob_elevated`,
  `sweep_detected`), so the table equals the registry derivation (311 columns) and both schema
  tests pass on their real expectation; the unit schema test now parses DROP COLUMN.
- The replay rebuilds clean through 577 and the feature and IC integration tests pass. Six
  bar-layer integration tests are red on the new baseline and were hidden before (the old replay
  stopped at 569): `test_ohlcv_coverage_atomic_write.py` (3), `test_scrub_pass_live.py` (2),
  `test_ingress_write_contract.py` (1). They belong to the bar area (587 owner) and are reported
  to the lead, not fixed here.

