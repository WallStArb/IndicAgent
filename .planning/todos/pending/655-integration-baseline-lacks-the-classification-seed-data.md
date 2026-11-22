---
status: pending
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
