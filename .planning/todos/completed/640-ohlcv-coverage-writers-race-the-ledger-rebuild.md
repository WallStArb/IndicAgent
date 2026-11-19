---
status: completed
priority: P2
filed: 2026-11-19
source: 609 audit disposition (coverage_cache) and the review of `ops_coverage_rebuild`
owner: lead
---

# The ohlcv_coverage writers do not take the fetcher lock, so a rebuild or audit can race them

## What

`rebuild_from_stored_state` (`services/ohlcv_coverage_writer.py`) says it runs under the fetcher lock so no `persist_chunk_atomically` delta can interleave. The IBKR fetcher that took that lock is deleted. Today only the reconciliation audit and `services/corpus_rerun.py` take `FetcherLock`; the Alpaca nightly (`ops_bar_nightly`, `services/bar_load.py`) and the Massive loaders upsert `ohlcv_coverage` with no lock.

Under READ COMMITTED a nightly delta that commits after the rebuild's aggregate over `ohlcv_raw` is overwritten with the rebuild's stale `row_count`, `earliest_timestamp` and `latest_timestamp`, with no error. The rebuild's ledger-wide transaction also blocks every nightly upsert that touches a rebuilt row until it commits. The audit's `coverage_cache` check has the same blind spot, but it always rolls back, so there it only makes the verdict noisy.

`scripts/ops/bars/ops_coverage_rebuild.py` works around it by refusing while a ledger writer unit or `ops_massive_load` runs. That is a guard on one caller, not the invariant.

## Done when

One of: (a) the nightly, `bar_load` and the Massive loaders take the fetcher lock (or a renamed ledger-writer lock) around their ledger delta, and the rebuild and audit wait on it; or (b) the ledger delta is rebuild-safe (a rebuild computes from a snapshot and never overwrites a newer delta). The `rebuild_from_stored_state` docstring states what is actually enforced. A test proves a delta committed during a rebuild survives.

## Not blocking

The audit's `coverage_cache` check clears with one committed rebuild run while no writer is active.

## Resolution

Option (b), done 2026-11-19: `services/ohlcv_coverage_writer.py` takes a transaction-scoped advisory ledger lock (`LEDGER_LOCK_NAME`). Every delta writer (`upsert_coverage`, `record_fetch_outcome`, `refresh_1d_bounds`) takes it shared; `rebuild_from_stored_state` takes it exclusive, so a rebuild waits for in-flight deltas and none can commit until the rebuild's transaction ends. The server releases it at COMMIT or ROLLBACK. The audit's `coverage_cache_drift` and `ops_coverage_rebuild` take it exclusive before their first ledger read, so their before-snapshot cannot miss a delta. Proof: `test_a_rebuild_waits_for_an_open_delta_and_does_not_overwrite_it` (live DB, fails to `1 != 2` with the lock disabled). The `ops_coverage_rebuild` writer-unit refusal and the audit's fetcher-lock poll stay as belt and braces; deleting them is a follow-up.
