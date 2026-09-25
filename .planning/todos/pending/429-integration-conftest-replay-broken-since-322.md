---
status: pending
priority: P2
filed: 2026-09-25
source: phase 183 plan 02 (research_run ledger integration test)
---

# Integration suite cannot rebuild indicagent_test: migration replay fails at 322 and 328

## What

`tests/integration/conftest.py` rebuilds `indicagent_test` from the 2026-07-18 schema baseline
and replays every migration above 234. Two replays now fail, so every test under
`tests/integration/` errors at fixture setup (confirmed on `test_concept_parent_lineage.py`):

- 322 (`timeframe_intraday_hourly_vocabulary_group`): `vocabulary_group_member` FK violation,
  `(timeframe, 1m)` is not in `controlled_vocabulary`. The baseline is schema-only; the CVR
  rows 322 references were seeded by a pre-cutoff migration whose data the baseline lacks
  (same class of bug as the 237 incident in the conftest docstring).
- 328 (`concept_registry_phase148_placement_verdict`): inserts a `domain = 'construction'`
  row before 329 extends `concept_registry_domain_check` to allow that domain.

## Why it matters

The suite runs only under `pytest -m integration`, never in CI, so nothing caught this. Every
DB-level invariant test (append-only triggers, lineage guard, schema sync) is currently
unrunnable through the normal path. Phase 183 verified its ledger tests by applying 323-366 to
the partly rebuilt test DB by hand and running with `--noconftest`.

## Done when

The baseline is regenerated from current production and `_BASELINE_MIGRATION_CUTOFF` bumped
(the fix the conftest docstring prescribes), and `pytest tests/integration -m integration`
reaches the tests again.
