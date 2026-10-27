---
status: pending
priority: P2
filed: 2026-10-27
source: IBKR warning 2172 in logs/ibkr_history_fetcher.log, 2026-10-27 01:31Z
owner: 2026-10-27
---

# The ib-gateway container runs a version IBKR desupports on 2026-12-15

## What

Every fetcher connect logs IBKR warning 2172: "The version of the application you are running,
1045.1, needs to be upgraded, as it will be desupported on 20261215. The minimum supported version
at that time will be 1050.1." After that date the gateway may refuse API logins, which stops all
IBKR ingestion.

## Fix

Move the `ib-gateway` image (production/docker-compose) to a 1050.1+ build before 2026-12-15, in a
fetcher gap, then re-auth (2FA push) and confirm a fetcher run lands bars. Check the IBC version
pairing and the API server version (178 today) against ib_async.
