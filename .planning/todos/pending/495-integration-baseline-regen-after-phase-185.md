---
status: pending
priority: P2
filed: 2026-10-06
source: 185 session, 185-18 and 185-22 close-out
---

# Regenerate the integration baseline after phase 185 closes

## What

tests/integration/conftest.py replays migrations above _BASELINE_MIGRATION_CUTOFF (433). Phase 185's
reserved migrations 404 to 408 sit below it, so the test database lacks their effects (404 retired
store_bars, 405 the intraday locks, 406 the overlap keys, 407 the reconciliation thresholds, 408 listing venue),
and 435 and 437 need the replay to stay ordered. Tests that read those APR keys against indicagent_test will
see them missing.

## Fix

When 185-24 lands, regenerate the baseline and seed files from production (todo 486's method: schema,
hypertables with the compressed-stub drop, instruments, tag, vocabulary, config seed), raise the cutoff to the
head, run pytest -m integration.
