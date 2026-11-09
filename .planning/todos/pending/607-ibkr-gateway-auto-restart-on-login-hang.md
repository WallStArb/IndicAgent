---
status: pending
priority: P1
filed: 2026-11-10
source: 2026-11-09 gateway wedge (5f session report): wedged at authentication from the 2026-11-08 23:59 UTC nightly restart until a manual restart 2026-11-09 23:42 UTC; about 70 timer runs bounced, coverage frozen at 778 of 1,177 for the day; todo 395's 2FA-hang class
---

# IBKR gateway auto-restart on a login hang after the nightly restart

## What

The ib-gateway container's nightly restart (23:59 UTC) sometimes hangs at authentication (the
2FA-hang class, todo 395). On 2026-11-08/09 it hung for 23h 43m: every fetcher timer run bounced
with API connection failures, IBKR 5m intake stopped (last intake 2026-11-08 23:58 UTC), and
nothing noticed until a person looked. A silent full-day stall of the pre-2016 backfill.

## Do

A small watcher (systemd timer or a check in the fetcher's own startup): after the nightly
gateway restart, if the log's "Login has completed" marker (or the API accept) has not appeared
within an APR-timed window (`infra.ibkr.login_hang_restart_s`, seed 180), restart the container
once and alert; if the second attempt also hangs, alert and leave it (never a restart loop).
Reuse the existing watcher pattern from 5f's manual check; log every action with timestamps.

## Gates

No restart loop (bounded to one auto-retry); the watcher itself is idempotent and unit-tested on
log fixtures (a hang line, a success line, a missing log); `/simplify`, `/review`, targeted
tests. Land in a fetcher gap, in a worktree.

## Notes

The watcher confirming the 2026-11-09 23:42 restart's first intake is the immediate verification
(the lead checks the fetcher log at the next session). This mitigation matters until Massive
admission (todo 600) retires the IBKR leg; if Massive lands first, close this as superseded.
