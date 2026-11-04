# 577: Fetcher qualify-on-dead-socket is misclassified as a plain error, never GatewayLost

**Filed:** 2026-11-01 · **Priority:** P1 (runs only after the 186-26 rebuild finishes; the rebuild's `kernel_code_key` hashes `services/backfill_feature_factory.py:79` -> `scripts.infrastructure.backfill._history_fetch` -> `src.providers`, so the fetch import closure is frozen while the rebuild is live) · **Status:** done (core fix landed 7f3343608; the summary-surface item is superseded per the landed note)

## What happened (2026-11-01, measured)

- The gateway dropped around 11:31 UTC (ib_async Error 1100 "Connectivity between IBKR and Trader Workstation has been lost" x5, Warning 2110 at every login). The TCP socket to the gateway container stayed up, so `provider.is_connected()` stayed True.
- Run `e82e6cbd` (11:31-14:00 UTC): 1,109 items, `n_ok=0`, `n_error=1109`, `gateway_lost=null`. Every item died at qualify (`qualify_instrument failed`, logged at `src/providers/ibkr.py:1913`), classified as a plain error at `scripts/infrastructure/backfill/_history_fetch_item.py:792-793`.
- 2h29m of run budget burned re-failing every queued item instead of fast-failing via the `RuntimeError` at `scripts/infrastructure/backfill/ohlcv_history_fetcher.py:1278-1279` (the path a real `GatewayLost` takes), and the run summary shows `gateway_lost: null`, hiding the cause.

## Root cause

`_ensure_qualified` (`scripts/infrastructure/backfill/_history_fetch_item.py:523-534`) raises `GatewayLost` only when `is_connected()` is False AND `connect()` fails (`:533`). With the socket up but the IBKR session dead, qualify returns False exactly like a genuine unknown contract, and that False is cached for the run at `:534` (the todo 051 comment at `:526` already documents this hazard). No other `gateway_lost` setter is reachable in this state (`:1057-1059`, `:1072`).

## Fix shape

In `_ensure_qualified`, before caching a qualify False, distinguish session-down from unknown-contract:

- probe with a cheap request (head timestamp or `currentTime`), or
- treat a recent Error 1100 / 2103 / 2110 from the ib_async error stream as `GatewayLost`.

Also consider: when qualify fails for every item in a run, the run summary should surface the error class (a run where 100% of items fail one way is never a normal run).

## Constraints

- Wait for the rebuild to finish (import closure frozen; see above). Same window logic as todo 576's code fix.
- The APR lever `infra.backfill.fetch_concurrency` 4->8 (2026-11-01, `config_history` version 4) already restores the 175/h throughput expectation; this todo is about not burning run budget and preserving the diagnosis trail, not throughput.

## Fix landed (research lane, session b0, 2026-11-01)

Two premise updates from tonight's live evidence before the fix. First, the gate: the closure
check with the authoritative helper (`kernel_code_modules`, the exact function `kernel_code_key`
hashes) returns 23 modules and includes NO `scripts.*` and NO `src.providers` module —
`import_closure` does not traverse into `scripts`, so the todo header's frozen-closure premise
was wrong and the fetcher files are editable without moving the rebuild pin (verified before
editing; the running fetcher PID is unaffected by disk edits, and the fetcher-window rule is
satisfied by the campaign running as one long-lived process rather than timer reruns). Second,
tonight's incident (18:34Z stall, kill-and-resume 18:42Z, coordinated by indicagent-43) is the
same wedge: `hist_request_outer_timeout`/`hist_chunk_retry` loops for 55 minutes while a fresh
probe session got instant history from the same gateway.

The fix: `IBKRProvider.session_alive(timeout_sec=10)` — a `reqCurrentTimeAsync` probe, the
cheapest request only a live session answers, not rate-limited (not a history request); and
`_ensure_qualified` probes before caching a qualify False: dead session raises GatewayLost so
the run fast-fails through the existing gateway-lost path and the summary records
`gateway_lost`, instead of re-failing every queued item as plain errors. A live session that
answers the probe keeps the False cached as a genuine unknown contract (todo 051's semantics
preserved). Run-budget and diagnosis-trail goals both met; the two new fetcher tests cover both
branches. The todo's second consideration (a run failing 100% of items one way should surface
the error class) is superseded: with this fix that shape raises instead of reaching the summary.

Landed 2026-11-01, commit 7f3343608 (session b0; an earlier local draft of this commit briefly
carried an attribution line and was amended away in the worktree before pushing — no such commit
reached main).

Follow-up 2026-11-04: the probe added here read a live session as lost after IBKR's Error 200 for
LXP and ended five runs on 2026-11-03; an Error 200 answer now skips the probe (todo 585).
