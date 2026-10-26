---
status: closed
priority: P1
filed: 2026-10-26
closed: 2026-10-26
source: main session, plan 19 full-scan pass 2026-10-26
owner: 2026-10-26
---

# FetcherLock was silently lost to the server's idle_session_timeout

## What

`FetcherLock` holds a session-level advisory lock on its own connection, which sits idle for the
whole run. The server's `idle_session_timeout` is 1h, so any fetcher run longer than an hour lost
its lock without noticing: on 2026-10-26 the plan 19 full-scan pass (started 12:23Z) lost it about
13:24Z and the 15-minute timer runs acquired it from 13:55Z, so two fetchers ran at once until the
timer was stopped at 14:27Z. Raw is last-wins, so no data was wrong; the cost was shared IBKR
pacing and a broken single-fetcher invariant. The 2026-10-17/18 deepening runs were exposed too.

## Resolution

The lock connection opens with `options="-c idle_session_timeout=0"` (verified live: the session
reports 0). Test `tests/unit/test_fetcher_lock_idle_timeout.py`. The running pass predates the
fix; the timer stays off until it exits (`logs/plan19_fullscan_20261026.log`), then restarts.
