---
status: pending
priority: P1
filed: 2026-10-09
source: Alpaca integration pilot, Workstream B (docs/plans/2026-10-09-alpaca-integration-pilot.md)
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
