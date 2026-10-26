---
status: pending
priority: P1
filed: 2026-10-26
source: main session incident 2026-10-26 12:12Z (a read-only SKYD contract probe)
owner: 2026-10-26
---

# An out-of-range IBKR client id restarts the gateway and costs a 2FA approval

## What

`src/providers/ibkr.py`'s connect path rotates client ids from the caller's id up to
`_MAX_CLIENT_ID` (50) on error 326, and its `while ... else` falls into phase 2
(`_restart_ib_gateway`) when the loop ends without a break. A caller id above 50 never enters
the loop, so the `else` fires at once: no connect attempt, logged as
`ibkr.client_id_rotation_exhausted`, then a gateway restart. On 2026-10-26 a probe with
client_id=77 restarted the gateway twice (12:12:03Z and 12:12:15Z), dropped the fetcher run in
progress and forced a new 2FA approval three hours after the previous one.

## Fix

Refuse a client id outside `[0, _MAX_CLIENT_ID]` with a ValueError before any connect; only an
actual all-326 rotation may reach the restart. Test: an id of `_MAX_CLIENT_ID + 1` raises and
never calls `_restart_ib_gateway`. Consider whether any library connect should be allowed to
restart a shared gateway at all (a restart needs a human 2FA approval); a loud failure is
cheaper than a silent outage that waits on a phone.
