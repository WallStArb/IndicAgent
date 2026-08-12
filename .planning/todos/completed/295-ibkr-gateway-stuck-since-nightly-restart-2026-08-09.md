# 295 - IBKR gateway stuck at login dialog since nightly restart, ~12hr+ and counting

**Filed:** 2026-08-10
**Source:** Backfill status check, this session
**Status:** RESOLVED 2026-08-10 12:06 UTC — user manually approved 2FA (IB Key push) after a
restart; login completed on attempt 2 (attempt 1's 2FA dialog timed out at 180s before the
push was approved, per `TWOFA_TIMEOUT_ACTION: restart` auto-retrying into attempt 2, which
succeeded). Confirmed real API connect via `ib_async` (clientId 45) post-login. Client-44
backfill retry launched immediately after (PID 11823, `logs/backfill_client44_20260810.log`).
Root cause of the original ~12hr stuck state was never confirmed (2FA push likely never
delivered/never seen), but the fix each time is the same: restart the container and approve
the 2FA push promptly (within the 180s window) when it appears.

## What

`ib-gateway` container's own docker logs show IBC completed its nightly restart sequence
and opened a "Gateway" mode-selection dialog at `2026-08-09 23:59:05:802 UTC` — then
nothing. No login success, no error, no further IBC log lines at all as of
`2026-08-10 11:5x UTC` (~12 hours). This is well past the confirmed-normal ~4-4.5hr
nightly outage window (see `docs/reference/gotchas.md` /
`project_ibkr_nightly_gateway_restart` memory) — that pattern self-heals; this one hasn't.

`nc -zv 127.0.0.1 7497` succeeds (socat proxy is up) but every real API connect attempt
(`ib_async`/`ibkr.py`) times out — socat's own log is spamming
`connect(5, AF=2 127.0.0.1:4001, 16): Connection refused` continuously, meaning IBC never
got as far as opening its internal API port.

IBC's config in this container has `TradingMode=live` and `SecondFactorDevice=` (blank) —
this looks like it may be stuck waiting on a 2FA push-notification approval on the
account owner's device that nobody answered, though this wasn't directly confirmed (no
literal "second factor" string appears in the log; it stops right at "Gateway" dialog
focus, which could equally be a stuck paper/live selection dialog).

## What NOT to do

Did not restart the container or attempt any login automation this session — this is a
live-mode account and the fix plausibly requires interactive input (2FA approval,
credential re-entry) that an unattended restart won't resolve, and could just re-produce
the same stuck state. Left for the user to restart/re-authenticate directly.

## Where

- `docker logs ib-gateway --since 2026-08-09T23:59:00Z` — full sequence
- `docker restart ib-gateway` is the likely remediation once confirmed safe, followed by
  watching the log for a completed login (`LoginState is` transitioning past `LOGGED_OUT`)
- A backfill retry for the 43 still-incomplete expansion-cohort symbols is already queued
  (see command below) and can be relaunched immediately once the gateway is confirmed up:
  `.venv/bin/python scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py --client-id 44 --symbols ASML,GE,NFLX,UPS,URA,USB,VCR,VDC,VGT,VHT,VOX,VPU,VRP,VRTX,VST,VZ,WHR,WMB,WMT,WSM,WTRG,XOM,XTL,XTN,AA,CMCSA,KO,PGR,RVMD,UNH,AMD,AMZN,AVGO,CAT,DAL,FXC,HD,MS,NEE,RIOT,T,TSLA,UNP`
