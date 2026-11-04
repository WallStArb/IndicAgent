---
status: pending
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
