---
status: pending
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
