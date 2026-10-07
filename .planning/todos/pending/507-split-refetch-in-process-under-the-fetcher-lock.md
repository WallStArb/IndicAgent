---
status: pending
priority: P1
filed: 2026-10-07
source: plan 189-08 (split re-fetch moved onto the fetcher CLI; flagged by 189-04-SUMMARY item 4)
owner: phase 189 fetcher (189-10 Task 1)
---

# Split re-fetch inside a fetcher run is refused by the fetcher's own lock

## What

`scripts/ops/bars/ops_split_detect.py` records a split found in a run's 1d overlap, re-fetches the
symbol's full 1d history, then re-derives it (185-22, D-21). Until plan 189-08 the re-fetch launched
the historical pipeline, which took the ibkr_history_stream lease, so it worked while the fetcher held
FetcherLock. 189-08 removed the pipeline CLI and the lease; the re-fetch now runs
`ibkr_history_fetcher.py --symbols ... --full-scan --overlap-sessions N`, which takes FetcherLock.

When split detection runs as the fetcher's own run-end stage, the parent fetcher still holds that
lock, so the child is refused. The refusal is loud by design: `run_refetch` maps the
`LOCK_HELD_MESSAGE` line to exit 3, the derivation is skipped, the fetcher run ends `partial`, and
D2 keeps the symbol's older bars flagged `pre_split_unrefetched` (quarantined). Recovery is by hand
after the fetcher exits: `ops_split_detect.py --refetch-only SYM`. Correct, but not automatic.

## Fix

Do the re-fetch in-process in the fetcher, after split detection records the corporate action and
before the daily stage (D2 counts only a fetch made after the recording as post-split): record, then
fetch the recorded symbols at 1d with the split overlap on the open provider connection, then derive.
189-10 Task 1's overlap-verified update lane escalates a restated name to a full-depth re-fetch in the
same run; build both on one path, and keep the order record, re-fetch, derive. A unit test drives a
detected split through a fetcher run and asserts the re-fetch happened under the run's own lock and
the stage exits 0.

## Gate

Before 189-10 Task 1b runs the fetcher over names that already hold IBKR 1d observations (the refresh
step), since that is the first run that can detect a split.

## Done when

A split detected in a fetcher run is re-fetched and re-derived in that run without a second process,
and `ops_split_detect.py`'s docstring no longer describes the refusal.
