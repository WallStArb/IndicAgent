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
