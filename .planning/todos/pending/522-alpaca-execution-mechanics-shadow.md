---
status: pending
priority: P1
filed: 2026-10-09
source: Alpaca integration pilot, Workstream B (docs/plans/archive/2026-10-09-alpaca-integration-pilot.md)
---

# Alpaca execution mechanics shadow on paper (Workstream B)

Pending 2026-10-09, P1. Single session, paper endpoint only, zero canonical
writes, no capital. The pre-registration's bounds already fix it: at most 20
orders, 1 share each, spread over 5+ names, all flat by EOD.

## What

Validate the API surface the execution client will sit on and fix the
measurement definition before any book routes a paper order:

- Place, replace, cancel on paper; every order reaches a terminal state; zero
  orphaned open orders at EOD.
- Reconnect mid-lifecycle without duplicate orders (idempotency via
  client_order_id, exercised deliberately at least once).
- Deliver the instrumentation spec: every order record carries book decision
  id, decision-time mid, transmit time, fill time, fill price; realized
  slippage = fill price vs decision-time mid (definition fixed in the
  pre-registration; it must not be redefined after first measurement).

## Why now

Fastest path to the one number no backtest contains (realized slippage on own
flow) and it is independent of the 189-10 lanes and the depth build. Paper
keys are already wired in `.env` and smoke-tested.

## Acceptance

B2 criteria of the pilot doc pass (terminal states, no orphans, idempotent
reconnect); the instrumentation spec is a doc, not code, until a client build
phase consumes it.

## Built 2026-11-01 (harness + spec; staging passed off-hours; measured run resumes at the next open)

- Harness: `scripts/ops/alpaca_paper_lifecycle.py` (paper endpoint asserted in code; JSONL
  ledger `data/scratch/alpaca-paper/orders.jsonl`; bounds asserted: 20 measured orders, 1
  share, 5+ names, EOD flat). Commands: `stage` (off-hours surface validation),
  `run` (measured, open market only), `check` (orphan sweep), `status`.
- Spec: `docs/plans/2026-11-01-own-flow-slippage-instrumentation.md` fixes the record and the
  definition (decision-time IEX mid; realized slippage bps signed by side) before any
  measurement. The pilot draft's SIP mid is corrected to IEX, dated, because the paper
  account's licensed feed is IEX (SIP latest quotes 403).
- Staging passed off-hours: 5 orders placed across 5 names, idempotent reconnect exercised
  (fresh session resolves the order by client_order_id; duplicate re-place refused by the
  server), all cancelled, 0 open at end. Mechanics recorded in the spec: off-hours orders sit
  in `accepted` and refuse replace (422); the open-orders list lags the per-order cancel by
  seconds to minutes (settle before asserting); client-order-id lookup is the dedicated
  `orders:by_client_order_id` endpoint (a filter on the list endpoint is silently ignored).
- Paper endpoint accepts and queues orders off-hours: confirmed (orders placed 23:56 ET
  Saturday sit in `accepted`).
- Not done tonight, deliberately: the 20 measured orders need fills, so the measured run waits
  for the next open (Monday 2026-11-02 09:30 ET). Resume: `check` then
  `.venv/bin/python scripts/ops/alpaca_paper_lifecycle.py run` any time after the open; the
  ledger counts the remaining budget; 0 of the 20 measured orders are consumed.

## Status 2026-11-02 (indicagent-02)

`alpaca_paper_lifecycle.py run` is a stub: `main()` ends in `SystemExit("run: the measured protocol
needs an open market; see the todo")`. Only `stage`, `check` and `status` are implemented, so the
"run after the open" steps above do nothing. The 2026-11-02 pre-open `check` cancelled 0 orders
(account flat); no measured order has been placed. Next: implement `run()` from the file docstring
and `docs/plans/2026-11-01-own-flow-slippage-instrumentation.md` (RUN_NAMES, 1 share each, at most
20 orders, IEX quote midpoint before decision_time recorded before transmit, every order polled to a
terminal state, leftovers cancelled so the account ends flat, slippage_bps definition unchanged),
then run it any session day before the 16:00 ET close, then `check`.
