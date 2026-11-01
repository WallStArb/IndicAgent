---
status: pending
priority: P1
filed: 2026-11-01
source: indicagent-2c, observed during the backfill health check (2026-11-01 04:11 UTC)
---

# Fetcher APR fallback storm: ConfigService reads fail under rebuild load, the queue runs on defaults

## What

`fetch_queue.apr_fallback_used` fired 253 times in one night (2026-10-31 22:00 through
2026-11-01 04:15 UTC), all ten `infra.backfill.*` keys at once, in bursts. The keys all exist in
`config_state` (verified live: `fetch_concurrency = 4` among them), so the fallback is not a
missing-key problem: `ConfigService.get_sync` is failing at read time. Prime suspect is database
contention with the 186-26 stage-2 rebuild (`backfill_feature_factory`, 8 workers) and the paused
compression, the same contention that produced the todo 443 exporter stalls.

## Why it matters

While the fallback is active the fetcher runs on its hard-coded defaults instead of the APR
values, so the 534 campaign's calibrated `fetch_concurrency = 4` and budget knobs silently
revert to whatever the code default is. That is a hidden bias on THE data-acquisition goal, and
it is invisible unless someone reads the fetcher log during a wedge.

## Fix direction

1. Capture the actual exception behind the fallback (the warning currently logs only the key
   list, not the reason). One-line change in `_fetch_queue`.
2. Decide whether `get_sync` should retry briefly (the failures look transient and bursty) or
   whether a cached-at-init read is the right pattern (the queue reads at init per run_summary;
   if it reads per item, cache).
3. If the failures are pool/connection exhaustion under rebuild load, that is a capacity fact
   for the 443 lane, not a fetcher bug.

## Evidence

- `logs/ibkr_history_fetcher.log`: 253 `apr_fallback_used` events 2026-10-31T22:xx through
  2026-11-01T04:11, always the same ten-key list, in sub-second bursts.
- `config_state` holds all ten keys as of 2026-11-01 04:16 UTC.

## Diagnosis (research lane, 2026-11-01, read-only): not a storm, not production

The 253 events are all from unit-test runs, zero from production. Method: in
`logs/ibkr_fetcher.log.1` (the rotated file holding the window), attribute each
`fetch_queue.apr_fallback_used` event to the nearest preceding `fetcher_lock.acquired` and read
its lock name: 32 test runs (lock names `test_ibkr_fetcher_*`, holders `test-holder`, dry-run
outputs under `/tmp/pytest-of-bg/`) vs 10 production runs; 253 of 253 fallback events are
test-context, 0 are production-context. The bursts line up with the lanes' pytest windows, not
with rebuild load: every suite run appends to the shared class log
`logs/ibkr_history_fetcher.log`, interleaved with production lines, and the health check read
test traffic as campaign traffic.

Two premise corrections. First, the read is not `ConfigService.get_sync`: it is one direct SQL
SELECT in `_fetch_queue.load_queue_config` (ohlcv_history_fetcher.prepare, once per run), so the
proposed get_sync retry/cache and the exception-capture one-liner have no target. Second,
nothing failed: the fallback fires only when keys are genuinely absent, and the production keys
exist (`fetch_concurrency = 8` live in config_state, the v4 raise from 4; verified 2026-11-01).
The ten production runs in the window logged no fallback: the 534 campaign has been running on
its APR values throughout, including during both burst windows.

No code change is needed, so the 186-26 closure check is moot (the fetcher files are gated
anyway). The only real finding is the log-shared-between-tests-and-production confusion: if a
future health check wants production-only fallback counts, filter events by the nearest
preceding `fetcher_lock.acquired` lock name (the `test_` prefix); optionally, ungated, the unit
tests could point structlog at a tmp file so the class log is production-only. The todo 443
capacity question is unrelated to this signal (its stalls were diagnosed separately).
