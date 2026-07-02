# ensemble_ic_engine.py — serial N+1 DB fetch in main process

**Found:** 2026-07-02, during `/simplify` pass on Phase 142A (`services/ensemble_ic_engine.py`).

`_execute_inner` loops over every `(symbol, tf)` pair (up to ~232: 58 ETFs x 4 TFs) and
issues one `await conn.fetch(...)` per pair, sequentially, on a single connection — each a
3-way join (`alpha_events` x `forward_returns` x `market_regimes`) over years of bars. This
serializes I/O that `services/ic_engine.py` already parallelizes: each `ProcessPoolExecutor`
worker there opens its own read-only connection and fetches its own symbol's data
concurrently (see `ic_engine._run_ic_worker`, ~line 2117-2143).

`ensemble_ic_engine.py` diverges from that established pattern, fetching everything serially
in the main process before dispatching to workers. Note: CLAUDE.md's "workers are
compute-only" rule is about **write** connections/commits from worker subprocesses, not
reads — `ic_engine`'s read-per-worker precedent does not violate it, so mirroring it here is
architecturally sound.

**Action:** Either give each `ProcessPoolExecutor` worker its own DSN and let it fetch its
`(symbol, tf)` slice itself (mirroring `ic_engine._run_ic_worker`), or at minimum run the
per-pair fetches concurrently via `asyncio.gather` over a few pool connections instead of one
connection sequentially.

**Blocked on:** nothing — safe to fix anytime. Not a correctness bug (results are the same),
just a throughput ceiling that will matter as the ETF universe or TF set grows. Deferred out
of the `/simplify` pass because it's a real refactor of the core data-loading path, not a
cleanup, and needs test coverage of its own before landing.
