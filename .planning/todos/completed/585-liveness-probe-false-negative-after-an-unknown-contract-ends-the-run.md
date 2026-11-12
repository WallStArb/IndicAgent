---
status: closed
closed: 2026-11-12
---

# 585: The liveness probe after an unknown-contract qualify reads a live session as lost and ends the run

**Filed:** 2026-11-04 (session ab, todo 534 lane) · **Priority:** P1 (lead 2026-11-04: ahead of the vendor memo) · **Status:** core fix landed 2026-11-04; step 1 (why the probe misses) open

## What happened (measured from logs/ibkr_history_fetcher.log)

On 2026-11-03, five fetcher runs (ended 07:08, 08:21, 09:50, 10:53 and 12:01Z) each fetched 4 to 7
items with bars, then died at `ibkr/LXP/1d` with `ibkr_history_fetcher.gateway_lost`: "IBKR session
did not answer the liveness probe before qualifying LXP". IBKR answers LXP with Error 200 "No security
definition has been found" (a genuine unknown contract). Todo 577's fix (7f3343608) probes the session
before caching a qualify False; here the probe failed although the same session had just served
history, so a live session was read as lost and each run ended early (about an hour of campaign time
per death, counting the 15-minute timer gap).

`gateway_lost` is never charged to the series, so LXP stayed at the queue head and repeated the
pattern until later runs, whose probe answered, charged it as plain errors. LXP 1d now sits at
`consecutive_failures = 6` (excluded at > 5), which ended the loop for this name only.

## Fix

1. Find why the probe misses after Error 200: probe timeout (`infra.ibkr.history_probe_timeout_s`)
   against a busy session with history requests in flight, or an ib_async error-event interaction.
   Reproduce by hand with a clientId <= 50 session: qualify LXP, then run the probe.
2. Whatever the cause, a qualify that IBKR answers with Error 200 is an answer, which proves the
   session is alive. Classify it as an unknown contract without probing, and keep the probe for
   qualify timeouts and other non-answers.
3. LXP itself: confirm the instrument (ticker change or delisting) through the onboarding SOP. Never
   hand-edit `instruments`.

## Landed 2026-11-04 (session ab)

- `IBKRProvider.qualify_instrument` records IBKR's Error 200 for the request's own contract (an
  `errorEvent` handler, the exception path included) per symbol; `is_undefined_contract(symbol)`
  reads it. Keyed by symbol, so the workers sharing one provider never read each other's answer.
- `_ensure_qualified` never probes after an Error 200: the False is cached and the item ends error,
  charged toward the name's exclusion. Every other qualify False (timeout, any other error code)
  is still probed, so a dead session still raises GatewayLost (todo 577's tests pass unchanged).
- The probe's 10 s literal is APR `infra.ibkr.session_probe_timeout_s` (migration 565).

Open: step 1, why reqCurrentTime missed on a live session. A qualify timeout under load could still
end a run the same way; a measured probe miss rate (or one retry after spacing, as history_alive
does) decides the fix. LXP itself (step 3) is still to confirm through the onboarding SOP.

## Closure 2026-11-12

Closed 2026-11-12 (lead): superseded by Massive (todo 600). The data-complete gate is Massive admission, the IBKR fetcher timer is disabled, and the IBKR leg joins todo 600's deletion list once step 7 proves itself (owner 2026-11-10: stop polishing IBKR/Alpaca-era data).
