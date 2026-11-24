---
status: completed
priority: P2
filed: 2026-11-22
source: integration harness lane (conftest 605 fix), 2026-11-22; todo 495 stays closed, this is a separate gap
---

# The integration baseline carries no classification seed data: 16 tests fail on a fresh indicagent_test

## What

With the harness fixed (migration 605 no longer replays; stale tests removed), the integration suite outside the live-database files runs 173 tests: 156 pass, 1 skips (`test_ingress_write_contract.py:269`, `ohlcv_raw` has no compressible chunk) and 16 fail, all classification:

- `tests/integration/test_classification_schema.py` (11) and `test_instrument_classification_coverage.py` (5).
- Cause: the scheme row, the nodes and the instrument classifications come from migrations 364 to 372, all at or below the baseline cutoff (576), and the baseline is schema only plus four seeds (instruments, tag vocabulary, controlled vocabulary, config). `classification_node` and `instrument_classification` rows are in none of them, so the tests see no `indicagent_v1` scheme (`ForeignKeyViolationError`, `None == 'IndicAgent'`, `{} == {'SPY': ...}`).
- Todo 495's closure stands: its scope (the baseline schema to 576) was met. This is the data-seed class of the same problem its fix note names.

## Done when

- `scripts/infrastructure/regenerate_integration_baseline.py` also produces a classification seed (scheme, nodes, current instrument classifications) and `conftest._apply_baseline` loads it, or the 16 tests build their own fixtures.
- `pytest -m integration` outside the live files is green on a fresh `indicagent_test`.
- Part of the harness redesign (per-session database, live tests fenced, baseline bump); do not hand-write rows.

## Closed 2026-11-23 (indicagent-af)

`scripts/infrastructure/regenerate_integration_baseline.py` gains a `classification` seed (`classification_scheme`, `classification_node`, `instrument_classification`) and an `--only SEED` option; `conftest._apply_baseline` loads `seed_classification_2026-11-05.sql` after the instruments seed. It is a data dump of the current rows (139 nodes, 1,551 assignments, all of whose symbols are in the instruments seed), not a render of `src/config/classification_seed_data.py`: that module holds only the migration 365 state (118 nodes, 295 assignments), and migrations 370 and 372 extended production beyond it, so a render would not be the baseline snapshot. The dump uses `--disable-triggers` (the node table references itself; the 367/368 guards are skipped so the history loads as it is). No migration above the cutoff touches the three tables. Result on a rebuilt `indicagent_test`: `test_classification_schema.py` and `test_instrument_classification_coverage.py` 19 passed, 0 failed (exit 0). Todo 656's phase 3 regenerates the whole baseline and picks this seed up with the rest.
