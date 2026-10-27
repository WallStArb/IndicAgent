# Alpaca API reference card

Version: 5.63.4
Status: current
Author: Brandon with Claude Code (session, 2026-10-09)
Informed by: Alpaca docs (fetched 2026-10-09, links below), measured against
`docs/reference/gotchas.md`'s IBKR facts.

Facts the Alpaca integration design depends on, with sources. Not a mirror of
their docs: every page is fetchable as markdown (append `.md` to the URL; index
at <https://docs.alpaca.markets/us/llms.txt>), so this card records only the
numbers and constraints a plan or review would otherwise have to re-derive.
Anything marked **unverified** gets measured in the pilot before it enters a
plan.

## Role in the pipeline (current 2026-10-27)

The 2026-10-09 roles (shallow nightly writer, nightly verifier under d2-v3) are superseded by
the phase 191 raw-capture design (`docs/plans/2026-10-12-unified-raw-bar-table-design.md`):
every Alpaca answer lands in `ohlcv_raw` and canonical is a selection by `bar_source_policy`.

- **5m primary from 2016-01-04** (D-191-P, done 2026-10-27): kind `sip_rth`
  (split-adjusted, regular hours selected), IBKR fallback, IBKR alone before 2016.
  `iex_rth` (feed=iex) is raw only and never selected. Capture is
  `scripts/ops/bars/ops_bar_nightly.py` (unit `indicagent-alpaca-nightly`, 04:40 UTC,
  window ending 20 minutes back for the free plan's SIP recency hold, APR `infra.alpaca.*`).
- **1d: raw capture today; primary from 2016-01-04 decided, lands with plan 191-20**
  (D-191-Q, todo 545): IBKR fallback only where Alpaca has no tradeable bar, IBKR alone
  before 2016, a zero-volume bar never serves, and spin-off or ticker-reuse exceptions are
  per-name policy rows from a one-time three-vendor arbitration (Alpaca, IBKR, Tradier).
  The reason: with Tradier deleted, IBKR alone carries a non-consolidated volume basis and
  misses sessions Alpaca SIP holds.
- **Execution venue** (paper first), zero commission; the todo 445 rerun at
  commission 0 becomes the realistic cost model, not a best case.
- IBKR stays the deep source: 1d before 2016 (Alpaca's floor, below) and 5m before 2016,
  plus the fallback wherever Alpaca has no tradeable bar.

## Account, plans, and access

- Funded brokerage account planned by the owner; Elite ($100k *maintained* net
  deposits) includes Algo Trader Plus free. Funding alone unlocks no data:
  <https://alpaca.markets/elite>.
- **Basic (free):** IEX-only real-time (~2-3% of volume, never use for
  research), SIP historical since 2016 with a 15-minute recency hold, 200 API
  calls/min. Paper-trading keys stay at Basic rates:
  <https://docs.alpaca.markets/us/docs/about-market-data-api>.
- **Algo Trader Plus ($99/mo):** real-time SIP (CTA + UTP, 100% of market
  volume) websocket, no recency restriction, 10,000 calls/min. Applies to
  market data endpoints only; trading API rate limits are separate.
- Auth: `APCA-API-KEY-ID` / `APCA-API-SECRET-KEY` headers.
- **Account type decides feed access.** Business accounts are "professional
  subscribers" and cannot receive consolidated (SIP) data at all; they fall
  back to the non-consolidated tiers. The account must be personal, or the
  SIP-based roles here (nightly verifier, intraday depth) are void.
- **The SIP tier is the Polygon.io consolidated feed behind Alpaca's API**
  (Polygon.io renamed itself Massive.com on 2025-10-30; APIs unchanged, same
  company). Alpaca's own docs name Polygon as the consolidated-data provider
  (the professional-subscriber exclusion above says "Polygon's consolidated
  market data"). What Alpaca discontinued years ago at the Market Data API 2.0
  launch was *key passthrough to Polygon's API endpoints*, not the data
  lineage: Alpaca's v2 API is the only interface, Polygon/Massive is the
  upstream. Consequences: the 2016 history floor is Polygon's floor (verified
  live: 5m bars complete back to 2016-01-01, RTH window complete every year);
  a separate Massive/Polygon subscription would not add a second source, only
  a second window onto the same one.
- **Plan tiers:** Basic $0 (IEX real-time, SIP historical at 200 calls/min);
  a $49/mo tier (historical-focused, historically rate-capped, features have
  shifted across eras); Algo Trader Plus $99/mo (real-time SIP websocket,
  10,000 calls/min; re-confirmed on alpaca.markets/data 2026-10-09). Verify a
  tier's current rate limit at signup; do not assume from either older forum
  threads or this card.

## Data facts that bind the design

- **Daily bars: hard floor at 2016.** Minute bars ~5 years effective, with gaps
  at the old end. This is why IBKR (20-year 1d, one request per symbol) keeps
  the history before 2016: <https://alpaca.markets/support/alpaca-data-timeline>.
- **Historical bars:** multi-symbol endpoint, results sorted by symbol,
  `next_page_token` pagination. Page size **unverified** (forum reports vary);
  the pilot measures bars/sec end-to-end.
- **Corporate actions:** dedicated endpoint + SSE feed, and Alpaca explicitly
  guarantees nothing about CA availability timing. Adjustment quality is a
  measured property, not an assumption: the boundary-D basis study covers it,
  and nightly basis checks catch late CA arrival.
- **Volume is the weak-fungibility field.** Consolidated vs venue-specific
  volume differs systematically (`ibkr_venue` rows get volume NULLed by design).
  Any spec consuming volume requires the basis study to cover volume fields
  explicitly, not just closes.
- **Market calendar** API, 1970-2029: candidate cross-check for
  `src/core/market_calendar.py`.
- **Regulatory fees** page exists for the net-expectation cost model (SEC/TAF
  on sells; verify current rates there when the 445 rerun runs).

## Trading facts that bind the design

- **PDT is gone.** FINRA's intraday margin rule replaced the pattern-day-trader
  restriction, removing the sub-$25k caveat from earlier account discussions.
- Paper trading exposes the same order API as live; the promotion boundary is
  configuration, not code.
- 24/5 overnight session exists; irrelevant to current specs, noted because it
  changes what "in-session" means if a spec ever crosses it.

## Client choice

Thin httpx client in `src/providers/` (Ring 0) vs `alpaca-py` SDK: decided in
the plan, not here. The provider-isolation rule is the constraint either way:
Alpaca credentials and endpoints live in one module, exactly as ib_async lives
only in `src/providers/ibkr.py`.

## Sources

- Plans and limits: <https://docs.alpaca.markets/us/docs/about-market-data-api>
- Getting started / agent index: <https://docs.alpaca.markets/us/docs/getting-started>
- Data timeline (2016 floor): <https://alpaca.markets/support/alpaca-data-timeline>
- Elite: <https://alpaca.markets/elite>
- Paper-key rate limits: <https://forum.alpaca.markets/t/key-limitations-on-paper-trading-keys/17789>
