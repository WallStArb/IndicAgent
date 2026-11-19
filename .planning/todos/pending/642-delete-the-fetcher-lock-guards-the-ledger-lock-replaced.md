---
status: pending
priority: P3
filed: 2026-11-19
source: simplify review of todo 640 (altitude)
owner: lead
---

# Delete the writer-unit refusal and the audit's fetcher-lock poll that the ledger lock replaced

## What

Todo 640 made `ohlcv_coverage_writer` take a ledger advisory lock (shared per delta, exclusive per rebuild). Two guards that existed only because the writers took no lock are now redundant:

- `scripts/ops/bars/ops_coverage_rebuild.py`: `running_writers()`, `_WRITER_UNITS`, `_WRITER_PROCESS` and the `writer_running` exit. It refuses a safe run while a nightly is active; its docstring still states the race as live.
- `services/bar_reconciliation_audit.py`: `coverage_cache_drift` polls `FetcherLock` for up to hours and skips the check (returns None) while the fetcher window is open; the poll parameters and the `infra.bar_integrity.coverage_cache_lock_*` APR keys go with it.

Optional: one `rebuild_drift(cur, symbols=None)` in the writer module holding the take-lock, snapshot, rebuild, snapshot, diff sequence that both callers repeat.

## Done when

Both guards are deleted with their tests and APR keys (a migration removes the keys), the audit's coverage_cache check always runs, and no caller outside the writer takes a lock for the ledger. Edit the audit only while its timer is quiet.
