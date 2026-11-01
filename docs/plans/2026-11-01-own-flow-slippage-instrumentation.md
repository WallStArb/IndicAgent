# Own-flow slippage instrumentation (todo 522, Workstream B)

Status: spec, 2026-11-01. Author: data lane session (indicagent-93). Informed by: the Alpaca
integration pilot pre-registration (docs/plans/archive/2026-10-09-alpaca-integration-pilot.md),
todo 522, and tonight's staging run against the paper endpoint. A doc, not code, until a client
build phase consumes it.

## Why

The one number no backtest contains is realized slippage on own flow; the cost model (todo 437)
needs it. This spec fixes the measurement definition before any book routes a paper order, so
the number is never redefined after first measurement.

## The order record

Every order the pilot (and later, a book) routes carries one row with all of:

- `decision_id`: the book's decision this order executes (the pilot generates
  `stage-<hex>` / `run-<hex>` ids; a book uses its decision id).
- `symbol`, `side`, `qty` (1 share in the pilot).
- `decision_time`: when the decision was made, UTC.
- `decision_mid`: the quote midpoint nearest before `decision_time`, from the IEX latest-quote
  endpoint. Feed is IEX because that is the paper account's licensed feed (SIP latest quotes
  return 403; checked 2026-11-01). The pilot draft said SIP; this correction is dated before
  the first measurement and is part of the definition, not a change to it.
- `transmit_time`: when the order left the client, UTC.
- `client_order_id` (deterministic `p522-<decision_id>`), `alpaca_order_id`.
- `fill_time`, `fill_price`: the terminal fill's timestamp and price.
- `realized_slippage_bps`: sign * (fill_price - decision_mid) / decision_mid * 1e4, sign +1 for
  buys and -1 for sells. Positive is cost.

## The protocol (pre-registered bounds)

At most 20 measured orders, 1 share each, at least 5 names, all flat by EOD. One marketable
limit per name at an open market; the decision mid is read immediately before transmit; every
order is polled to a terminal state; any order still open at the end is cancelled. The
idempotent reconnect is exercised deliberately at least once: a fresh HTTP session resolves the
order by `client_order_id` and a re-place with the same id is refused by the server. Staging
orders (deep unmarketable limits placed off-hours to validate the API surface) never reach a
fill and never count against the 20.

## Mechanics facts (staging, 2026-11-01, paper endpoint)

- Orders placed off-hours sit in `accepted` until the open; Alpaca refuses to replace an order
  in `accepted` status (422, "cannot replace order in accepted status"). Replaces work on `new`
  orders during market hours; the measured run replaces only live ones.
- Cancel of an `accepted` order flips the per-order state to `canceled` immediately, but the
  open-orders LIST keeps returning it for seconds to minutes. Zero-orphan assertions must
  settle (poll the list until empty, or judge per order), never off one list read.
- Client-order-id lookup is the dedicated `GET /v2/orders:by_client_order_id`; a
  `client_order_id` parameter on `GET /v2/orders` is silently ignored and reads as an
  unfiltered list.
- Re-placing an existing `client_order_id` is refused by the server: idempotency holds across
  reconnects with no client-side dedup needed.

## Run and resume

`stage` (off-hours surface validation) and `run` (the measured protocol, open market only) live
in `scripts/ops/alpaca_paper_lifecycle.py`; the ledger is
`data/scratch/alpaca-paper/orders.jsonl`. After any interruption: `check` (cancel anything
open), then re-run `run` — it counts only orders with no measured fill against the 20 via the
ledger. The first measured run needs an open market (next: Monday 2026-11-02 09:30 ET).
