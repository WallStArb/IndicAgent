# Databento API reference card

Version: 5.61.0
Status: draft (unverified; key created 2026-10-10, nothing integrated yet)
Author: Brandon with Claude Code (session, 2026-10-10)
Informed by: Databento docs portal (databento.com/docs, JS app; markdown
alternates unavailable) and the writer's API knowledge, both flagged below.
Anything marked **unverified** gets measured in a probe before it enters a
plan. Follows the Alpaca/Clear Street card convention.

Facts the integration design would depend on.

## Credential

- Key `IndicAgent` created 2026-10-10 (portal user `HLAK4R4E`), stored in
  `.env` as `DATABENTO_API_KEY` (gitignored; never in docs, memory, or
  code). The key is the sole credential (no separate secret); consumed via
  `src/config/Settings` when an integration lands, never `os.environ`.

## What it is

- Institutional market-data vendor: historical (batch/HTTP) and live
  (streaming) APIs with an official Python client (`databento`; Rust and
  C++ clients also exist).
- Usage-based pricing per GB/record; the portal reports spend per request.
  **unverified**: our tier's rates and any minimums.
- Data is schema-addressed per dataset: trades, MBP/TBBO/MBO book schemas,
  and aggregated OHLCV schemas including 1m bars (**unverified**: exact
  schema list and whether a 5m schema exists or 5m must aggregate from 1m).
- Datasets are licensed per feed (SIP vs direct-feed). **unverified**: the
  current dataset IDs for US equities SIP and any depth feed; portal lookup
  required.

## Why it matters here

- First candidate **third data vendor**: it lands in the bars vendor lists,
  unlike Clear Street. Candidate roles: intraday depth beyond Alpaca's
  2016-01-01 floor, and a second tape for vendor-agreement audits (the
  D7/d2-style basis machinery generalizes; Alpaca's admission built the
  precedent).
- The `VendorIngress` seam (`src/intelligence/bars/vendor_ingress.py`) was
  built for exactly this: a Databento admission is one seam row plus
  `sources.py` constants, after it passes the same measured-admission gates
  the Alpaca build went through (`source_admission.py`, todo 521 plan as
  template). No admission without a measured basis study.

## Open questions before any plan cites this card

- Equities history depth start per dataset, and SIP vs direct-feed licensing
  cost at our volume (1,529 names, 5m RTH).
- Whether 1d bars are licensable and how they compare to IBKR/Alpaca 1d
  conventions (split adjustments, session boundaries).
- Live API is recorded but irrelevant while the streaming path is dormant;
  revisit with the Alpaca live-streaming decision.
