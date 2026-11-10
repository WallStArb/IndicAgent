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
- Market data exists but is thin (corrected 2026-11-10; the 2026-10-10 card said "no
  market-data endpoint", which was wrong for the Trading API). Read from the docs on
  2026-11-10, nothing called live:
  - `GET /v1/market-data/snapshot` (latest quote, last trade, session OHLV, open interest;
    1 to 100 instruments or an option chain). No historical bars, timeframe or history-depth
    parameter is documented; real-time versus delayed and feed coverage are not stated. A
    daily-summary endpoint is deprecated.
  - Fundamentals, income statement, balance sheet, cash flow (history "back multiple years",
    no date parameters listed), analyst consensus (latest snapshot only), earnings
    transcripts, events and news (`GET /v1/news`, filterable by date range, history not stated).
  - Locates: `GET /v1/locates/rates` (indicative annualized borrow rate with `as_of`, up to
    1,000 instruments; no rate history stated) and account locates. No market-wide shortable
    quantity.
  - Calendar (`/v1/calendars/market-hours`, `/v1/clock`, economic events) and a screener
    (`POST /v1/screener`, lookbacks one day to one year, no time series).
  - Rate limits: 1,000 requests a minute each for read, write and Omni AI per user. Licensing,
    redistribution and entitlement terms are not stated on any page read.
- Studio v2 is a separate API (`api.clearstreet.io/studio/v2`, OAuth2 client credentials,
  separate demo environment that replays recorded data for a handful of symbols): orders,
  locate orders and lending inventory. It lists no market data beyond a digital-asset
  WebSocket.
- Role for us: still an execution and custody rail first. Its data is a candidate for
  borrow cost (the locate rate feeds the `borrow_availability_snapshots` idea), news, and a
  second witness on the latest quote, not a source of bar history (Alpaca and Massive are).

## Open questions before any plan cites this card

- Order types supported (market/limit/stop and time-in-force set).
- Rate limits, sandbox/paper environment, and settlement/custody mechanics.
- Options support depth (we trade none today; recorded for the register).
