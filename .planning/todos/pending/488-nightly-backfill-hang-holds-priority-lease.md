---
status: pending
priority: P2
filed: 2026-10-02
source: interactive session, 2026-10-02 nightly wedge (25/233 symbols, 4h40m)
---

# Nightly backfill has no hang protection; a silent ib_async wedge holds the priority lease for hours

## What

`scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py` (as launched
by `indicagent-nightly-backfill.service`) issues ib_async history requests with no
per-request timeout, and the service has no watchdog. When the gateway silently stops
answering a client (socket drops, `remove Client 45` cycling in `docker logs ib-gateway`),
the pipeline sits in `select` forever: py-spy shows the event loop idle at `main` with
nothing recoverable.

On 2026-10-02 the nightly wedged at 25/233 symbols ~05:05 UTC and held
`lease:ibkr_history_stream:priority:historical-pipeline:45` for 4h40m. Consequences:

- The HTF lane (bulk tier) starved: attempts 4-11 (06:26-09:26 UTC) each spent their
  whole lease wait queued behind the dead holder and exited; the chain loop burned
  ~3.5h of wall clock with zero bars written.
- `systemctl restart` was the only recovery; the stop job needed the full SIGTERM
  grace window because the process never exits on its own.

This is the second silent-hang class incident in two days (HOOD SMART hang 2026-10-01
was name-specific; this one was a whole-client socket death mid-batch). The gateway
itself was healthy - a spare-client probe (client 41, AAPL 1d) returned instantly
while the nightly sat wedged.

## Fix

1. Bound every history request: wrap `reqHistoricalDataAsync` calls in
   `asyncio.wait_for` with an `infra.ibkr.history_request_timeout` APR key (suggest
   300s initial estimate; a healthy deep-history request is well under that even at
   bulk pacing).
2. On timeout: log `hist_request_timeout` (symbol, tf, elapsed), drop and reconnect
   the client, retry the symbol up to N times (`infra.ibkr.history_request_retries`),
   then fail the symbol and move on - never block the batch.
3. Optionally: a systemd watchdog (`WatchdogSec` + sd_notify) on the nightly service
   so a wedged event loop restarts itself without a human.

## Why now

The lease design (phase 185 D-29) assumes holders make progress and yield at
checkpoints; a holder that is alive but stuck defeats both the fair handoff and the
bulk-yield path. Every future nightly wedge repeats today's 4h lane starvation until
this lands.

## Size

Small: timeout wrapper + retry counter in the pipeline's fetch path, one APR key pair,
targeted unit tests for the timeout/reconnect path.
