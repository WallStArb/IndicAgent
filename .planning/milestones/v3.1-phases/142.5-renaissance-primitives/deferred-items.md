# Phase 142.5 — Deferred Items (Out of Scope Discoveries)

Logged during Plan 06 execution per the executor's scope-boundary rule: only
auto-fix issues directly caused by the current task's changes; pre-existing
issues in unrelated files are logged here, not fixed.

## 1. `indicagent_test` database has no schema (pre-existing, widespread)

**Discovered during:** Task 4 (schema validation test), verifying
`tests/integration/test_feature_vectors_schema.py::test_renaissance_columns_exist`
against the DB pointer `tests/conftest.py` sets by default
(`DATABASE_URL=postgresql://postgres:postgres@localhost:5432/indicagent_test`).

**Finding:** `indicagent_test` exists as a database but contains only 3 legacy
v2.x SLA tables (`signal_events`, `trade_frames`, `trade_executions`) —
verified via `psql -d indicagent_test -c '\dt'`. None of the ~200 migrations
applied to the real `indicagent` dev database (including `feature_vectors`,
`feature_registry`, `config_schema`, `config_state`, `instruments`, etc.) have
ever been replayed against `indicagent_test` in this environment.

**Impact:** Any `tests/integration/*.py` test that uses `get_settings()` (whose
module-level `Settings` singleton caches whatever `DATABASE_URL` was in the
environment at first construction — i.e. `indicagent_test`, set by
`conftest.py` at collection time) fails, because the tables/columns it queries
don't exist. Confirmed reproducible on an unrelated file:
`tests/integration/test_instrument_registry.py` (3/3 tests fail — no
`instruments` table, no `trg_instruments_notify` trigger — in `indicagent_test`).

**Existing precedent:** `tests/integration/test_pipeline_flow.py` already works
around this by hardcoding `DATABASE_URL` to the real `indicagent` DB at module
level, bypassing `get_settings()` entirely, with an explicit comment: "This
test uses the REAL database (indicagent), not indicagent_test."

**Action taken (in scope):** Applied the same override idiom to
`tests/integration/test_feature_vectors_schema.py` only (the one file this
plan's Task 4 modifies), since this plan's own acceptance criteria requires
that specific test to pass against the real migrated DB.

**Not done (out of scope):** Did not attempt to sync `indicagent_test`'s
schema with `indicagent` (would require replaying ~200 migrations from
scratch — a standalone infrastructure task, not a Renaissance-primitives
concern), and did not audit/fix the other `tests/integration/*.py` files that
presumably have the same latent failure mode (`test_instrument_registry.py`
confirmed failing; others not individually audited).

**Suggested follow-up:** A dedicated infra todo to either (a) replay the full
migration history against `indicagent_test` and add it to a setup/CI step, or
(b) apply the `test_pipeline_flow.py`-style real-DB override to every
`tests/integration/*.py` file that needs live DB state, standardizing on one
approach.

## 2. `pytest.ini` uses `[tool:pytest]` header instead of `[pytest]`

**Discovered during:** Task 4 test runs — every test file with
`pytestmark = pytest.mark.integration` (or `@pytest.mark.unit`) emits
`PytestUnknownMarkWarning`, even though `pytest.ini`'s `markers =` section
lists `integration`, `unit`, etc.

**Finding:** `pytest.ini`'s section header is `[tool:pytest]`, which is the
correct header for `setup.cfg`-embedded pytest config — not for a standalone
`pytest.ini` file, which should use `[pytest]`. Pytest still detects the file
(`configfile: pytest.ini` appears in test output) and `-m integration`
filtering still works correctly (confirmed: `--collect-only -m integration`
correctly selects only marked files), so `addopts`/`markers` appear to be
partially honored, but the strict-markers warning still fires — suggesting the
section is not being fully parsed as expected.

**Impact:** Cosmetic only in this run (does not block test execution or
change results) — every marked test in the suite prints one warning line.

**Not done (out of scope):** This is a repo-wide pytest configuration file
unrelated to Renaissance primitives; fixing it risks changing `addopts`
behavior for the entire test suite (`--strict-markers`, `--asyncio-mode`) and
was not touched.
