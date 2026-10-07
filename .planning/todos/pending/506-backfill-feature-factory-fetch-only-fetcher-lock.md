---
status: pending
priority: P3
filed: 2026-10-07
source: plan 189-08 Task 2 (CI guard rewritten around FetcherLock)
owner: phase 186 rebuild writer (services/backfill_feature_factory.py)
---

# backfill_feature_factory --fetch-only takes FetcherLock

## What

`services/backfill_feature_factory.py --fetch-only` calls `fetch_historical_bars` without any IBKR
history coordination. Plan 189-08 replaced the ibkr_history_stream ResourceLease with the phase 189
FetcherLock as the one coordination primitive and rewrote the CI guard
(`tests/unit/test_ibkr_history_lock_boundary.py`): every module that calls `fetch_historical_bars`,
`fetch_adjusted_daily_closes` or `get_head_timestamp` must reference `FetcherLock` in code or be
allow-listed with a reason. The factory is allow-listed TEMPORARY with `retire: todo 506`.

It is not scheduled today, so nothing runs it beside the fetcher (threat T-189-29, accepted). It was
left alone because it is the phase 186 rebuild writer: editing a module the fingerprinted rebuild
imports discards its completed cells (`code_content_key`).

## Fix

Take `FetcherLock` (fail fast, `LOCK_HELD_MESSAGE` on refusal) around the `--fetch-only` stage's IBKR
connection, the way `ops_d1_bootstrap.py` and `ops_intraday_venue_recovery.py` do. Remove the
TEMPORARY entry from the lock guard's allow-list in the same commit.

## Gate

After phase 186-26's single rebuild completes (no live or resumable rebuild run; check
`ps -eo pid,args | grep '[b]ackfill_feature_factory'` first).

## Done when

The factory references `FetcherLock`, the guard's allow-list has no factory entry, and the guard passes.
