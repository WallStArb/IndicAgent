# Clear Street API reference card

Version: 5.61.0
Status: draft (unverified; access granted 2026-10-10, nothing integrated yet)
Author: Brandon with Claude Code (session, 2026-10-10)
Informed by: <https://docs.clearstreet.com/> (fetched 2026-10-10). Client-gated
docs; every page has a markdown alternate (append `/index.md`) and the suite
publishes an OpenAPI spec.

Facts the integration design would depend on, with sources. Follows the
Alpaca card's convention: not a docs mirror, only what a plan or review would
otherwise have to re-derive. Anything marked **unverified** gets measured
before it enters a plan.

## Credential

- Bearer token in `.env` as `CLEARSTREET_API_TOKEN` (gitignored; never in
  docs, memory, or code). Consumed via `src/config/Settings` when an
  integration lands, never `os.environ`.
- Clear Street API keys are managed in their web app and **carry expiration
  dates**; the rotation/refresh step needs an owner procedure before any
  daemon depends on it. **unverified**: this token's expiry date.

## What it is (and is not)

- REST trading API at `https://api.clearstreet.com`, Bearer auth in the
  `Authorization` header.
- Products: US stocks and options, long and short. Endpoints: balances,
  instruments, orders, positions, portfolio history.
- **No market-data endpoint.** Clear Street is an execution/custody venue
  candidate, not a data vendor; it never enters the bars/vendor-ingress
  lists. Data-layer relevance is as the second execution rail beside Alpaca.

## Open questions before any plan cites this card

- Order types supported (market/limit/stop and time-in-force set).
- Rate limits, sandbox/paper environment, and settlement/custody mechanics.
- Options support depth (we trade none today; recorded for the register).
