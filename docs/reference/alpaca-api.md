# Alpaca API reference card

Version: 5.61.0
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

## Role in the pipeline (decided 2026-10-09)

- **Execution venue** (paper first), zero commission; the todo 445 rerun at
  commission 0 becomes the realistic cost model, not a best case.
- **Shallow nightly writer** (1d + 5m recent window, full universe): the
  date-partitioned primary. Owner constraint: IBKR rate limits are too slow for
  the nightly. Precedent for a date-boundary primary swap: migration 456
  (Tradier -> IBKR at D = 2026-10-07).
- **Intraday depth builder**: 1m/5m back to Alpaca's depth floor for the
  intraday universe, where IBKR's 58 req/10min made 12-18 days take weeks.
- **Nightly verifier**: d2-v3 rule, a disagreeing shallow primary yields to the
  basis-tested restated IBKR answer.
- IBKR stays the **deep authority**: initial history for new names, gaps older
  than the shallow window, restatement. 1d depth is the reason (below).

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

## Data facts that bind the design

- **Daily bars: hard floor at 2016.** Minute bars ~5 years effective, with gaps
  at the old end. This is why IBKR (20-year 1d, one request per symbol) keeps
  the deep-history role: <https://alpaca.markets/support/alpaca-data-timeline>.
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
