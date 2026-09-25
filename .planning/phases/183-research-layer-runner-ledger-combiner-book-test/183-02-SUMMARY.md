---
phase: 183
plan: 02
status: complete
requirements: [D-02, D-05, D-06, D-07, D-08, D-18]
---

# 183-02 summary: S6 ledger

Migration, jsonable and ledger.py were written by the wave-1 executor before it stopped on an
API limit; the orchestrator reviewed them, finished the sole-writer guard commit and wrote the
integration tests.

## What was built

- Migration 366 (`research_run_ledger`, applied live and pushed): `research_run` with a
  `started`-only insert, a single move to a terminal status, immutable columns, snapshot hash
  NULL-to-value only, DELETE and TRUNCATE refused; partial unique index `(spec_hash,
  concept_id) WHERE mode = 'real'`; APR keys `alpha.research.vintage_id` (vintage_1),
  `alpha.research.budget_m` (30), `alpha.research.screen_alpha` (0.05),
  `infra.research_runner.workers` (8).
- `src/intelligence/research/ledger.py`: `PostgresLedger` (has_real_run, charged_book_tests,
  start_runs under `pg_advisory_xact_lock(183366)`, finish_run with strict serialization that
  writes `failed` rather than leaving a row started), `Identity`, `RunRequest`,
  `LedgerRefusal`, `jsonable`.
- `test_ledger_sole_writer.py`: no other file under services/src/scripts/production writes
  `research_run` or construction `concept_registry` rows (legacy migrations allow-listed);
  a probe file writing `research_run` makes it fail.

## Verification

- Unit: `test_ledger_jsonable.py`, `test_ledger_sole_writer.py` pass.
- Integration: 11 tests pass (`-k spec_once` 2, `-k trigger` 4, `-k budget` 2). Run with
  `--noconftest` after applying migrations 323-366 to the partly rebuilt `indicagent_test`:
  the normal conftest rebuild is broken at migration 322 and 328 for reasons unrelated to this
  phase (filed as todo 429).
- Live `research_run` has 0 rows after the tests.

## Deviations

- Integration tests could not run through `tests/integration/conftest.py` (todo 429).
