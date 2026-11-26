---
status: pending
priority: P2
filed: 2026-11-26
source: first CI skip-count line (annotation "unit test skips" on 93918b722), lead ruling 2026-11-26
---

# CI skips eleven tests that read untracked data

## What

The first CI skip count (86 skipped on 93918b722) shows 64 skips for a missing database (todo 676) and eleven for data that is not in the checkout:
- Nine Massive reader tests that need real day files under `data/massive/files/minute_aggs_v1/` (the real-day bucketing cases at 2003-09-10, 2005-06-01, 2024-03-11, 2024-07-03, 2026-02-23 and 2026-02-25, plus the day-file tests): the reader's bucketing is checked against a naive reference only on this host.
- Three frozen-verdict tests that need `logs/phase179/rerun_e14/s3_4dead18ade3bde16.pkl`, `logs/phase181/s3_d3c9294661215c6d.pkl` and the frozen `logs/` directory.

## Decision (lead, 2026-11-26)

- Massive reader tests: commit tiny fixtures (a few hundred rows cut from one real day per case, kept under a few hundred kilobytes in total) so CI runs the bucketing-against-reference check. The host keeps the full real-day cases.
- Frozen-artifact tests: they stay on `scripts/research/determinism/repro_frozen.py` on this host as the real gate (the artifacts are large and generated). CI prints the line "frozen artifacts not checked in CI" (a notice in the unit job) so the gap is explicit, not a silent skip.

## Done when

The Massive tests run in CI from committed fixtures (the skip line drops by nine), the notice is in the job, and the remaining skips are only the database ones tracked in todo 676.

Related: [676](676-ci-unit-job-has-no-database-so-the-live-db-tests-never-run-in-ci.md).
