# Alpaca integration pilot

Author: Brandon with Claude Code (session, 2026-10-09)
Status: pre-registered, pilot not started
Informed by: `docs/reference/alpaca-api.md`, the council review of 2026-10-09
(rolling-seam nightly split rejected; Alpaca scoped to intraday depth campaign,
nightly verifier, execution), `docs/reference/gotchas.md` for IBKR facts.

## Pre-registration

Everything in this section was fixed before the first pilot request of either
workstream. Later sections add results; this section is not edited after its
commit. The commit time is the registration time.

Prior reads disclosed (analysis, not pilot evidence): an auth smoke test on
2026-10-09 pulled AAPL 1d bars for 2026-09-01..09-08 from the SIP feed and
compared them to stored canonical bars and a Yahoo reference (closes identical,
Alpaca volume +0.37% vs two agreeing references). AAPL is therefore excluded as
basis evidence and retained only as a throughput/reference name. No other
Alpaca data has been read.

The pilot is read-only with respect to `market_data_ohlcv` and all canonical
bar tables. All pulled data lands in scratch storage
(`data/scratch/alpaca-pilot/`), never in a hypertable. Nothing here changes the
1d primary, launches a nightly writer, or adds a Yahoo standing role; those are
explicitly out of scope (final section).

### Name selection (fixed)

Population: `instruments` where `compute_eligible = true` (the intraday
universe, 233 names, all holding 5m coverage). Read only `instruments`; no
history, latency or return read.

- Core 20: sort by symbol (C collation), k = 20, take 0-indexed positions
  floor((2i + 1) n / (2k)) for i = 0..k-1 (k evenly spaced midpoints), same
  rule as 189-10 Task 2. Executed 2026-10-09:
  AMD BIL CRM DBC EFA EWT FXE HD ISRG KO MMM NEM PFE RIOT SLV TMUS UUP VRTX
  XBI XLY. Spread includes ETFs and commodity/FX vehicles (DBC, SLV, UUP, BIL),
  which is desirable: the asset-agnostic invariant gets tested, not assumed.
- Reference pair: SPY and AAPL, added for direct comparison against the deepest
  stored history. AAPL carries the disclosed prior read.

### Workstream A: data basis and throughput (paper keys, Basic rates)

Pulls, in one pass, scratch only:

- A1. 1d bars, full Alpaca depth (floor 2016-01-01), all 22 names.
- A2. 5m bars, full Alpaca depth, all 22 names.
- A3. 1m bars, full Alpaca depth, a fixed subset of 5 names: the first 5 of the
  core 20 in symbol order (AMD, BIL, CRM, DBC, EFA). This subset carries the
  throughput measurement for the deepest timeframe; the other 17 stay on 5m.

Measured (recorded, per name): bar counts per timeframe, first/last timestamp,
storage bytes per row (scratch file sizes over row counts), page size observed,
requests made, wall time, requests/min observed against the 200/min Basic
limit, HTTP error taxonomy.

#### Basis criteria (all must pass for the depth build to launch)

| # | Criterion | Measured by |
|---|---|---|
| C1 | 1d close basis: per name, over common sessions with stored canonical 1d (`tradier` before D = 2026-10-07, `ibkr_named`/`ibkr_venue` after), the median absolute log close ratio is within the d2 admission tolerance (`source_admission.py` `tolerance_bp`, APR value read at run time), and the pass rate per name is at least 99% of common sessions | scratch comparison, per-name table |
| C2 | 1d close basis by era: C1 holds separately for the pre-D era and the post-D era (IBKR-sourced) with at least 200 common sessions each, or the era is reported as under-powered | same |
| C3 | 5m close basis: per name, median absolute close difference against stored tradeable 5m within 1 bp of mid, pass rate at least 99% of common 5m slots | scratch comparison |
| C4 | Session-window hypothesis H1: for 5 recent complete sessions per name, Alpaca 1m bars aggregated over the RTH window (09:30-16:00 ET) reproduce the Alpaca 1d bar's volume within 0.1% | decides the volume rule below |

H1 decision rule: if H1 holds (Alpaca 1d volume includes extended hours), any
stored Alpaca bar uses RTH-window aggregation from Alpaca's own intraday bars,
and the stored volume convention is documented as such in the depth-build plan.
If H1 fails (1d volume is already RTH-only), the +0.37% volume gap against
Tradier/Yahoo is unexplained and blocks the volume fields of the depth build
until characterized; price fields are unaffected.

Volume is reported per name (median volume ratio vs stored canonical vs Yahoo
where available) but is not a C-gate on price fields; volume admission is its
own verdict after H1 is characterized.

#### Extrapolation formulas (fixed before any number is read)

Inputs measured by the pilot: p_req = mean requests per name per timeframe from
A1-A3, r_obs = observed requests/min sustained (capped by Basic), b_row =
bytes per stored row (5m), t_run = measured wall time for the A3 1m subset.

- F1, depth-build request total: R_tot = 233 x (p_req,1d + p_req,5m) + 233 x
  p_req,1m. Drain time at Basic: R_tot / r_obs minutes. Drain time on Algo
  Trader Plus: R_tot / min(10000, 3600 / (t_req + p)) minutes with the
  pilot-measured mean request latency t_req and a 0.5 s inter-request pause p.
- F2, storage: 233 x (rows_5m + rows_1m) x b_row, compared against the data
  layer integrity design's envelope (at most 17 GB 5m-class intraday).
- F3, nightly verifier cost: one 1d pull per name per night, N = 1,529 at
  scale: N x p_req,1d / r_obs minutes at Basic, reported also at the paid rate.

#### Bounds

- B1. Total pilot requests at most 10,000 (about 50 min at Basic sustained;
  generous headroom for retries, not a tuning target).
- B2. Zero writes to any canonical table; scratch only (checked by a
  `market_data_ohlcv` max(timestamp) and row-count diff across the pilot).
- B3. The depth build launches only if C1-C3 pass and F2 fits the envelope.
- B4. The nightly verifier role is feasible on Basic (yesterday's session is
  outside the 15-minute recency hold); if a same-session-evening verifier is
  ever wanted, it needs the paid plan. Recorded, not gated.

### Workstream B: execution mechanics shadow (paper account)

Not capital evidence; validates the API surface the execution client will sit
on, and specifies the measurement instrumentation before any book routes a
paper order.

- B1. Order lifecycle: place, replace, cancel on paper for up to 20 orders
  total, quantity 1 share, spread over at least 5 of the 22 names. All orders
  cancelled or flat by end of day, every day.
- B2. Pass criteria: 100% lifecycle terminal states observed (no stuck
  pending_new/pending_cancel), zero orphaned open orders at EOD, reconnect
  mid-lifecycle handled without duplicate orders (idempotency via
  client_order_id verified at least once deliberately).
- B3. Instrumentation spec (delivered, not built): every order record carries
  book decision id, decision-time mid, transmit time, fill time, fill price;
  realized slippage defined as fill price vs decision-time mid. This definition
  is fixed here so the number cannot be redefined after it is first measured.
- B4. Bound: no order larger than 1 share, no more than 20 orders total for
  the pilot, paper endpoint only.

## Sequencing

189-10 proceeds unperturbed; the Alpaca pilot shares no lane with the IBKR
fetcher (different vendor, no FetcherLock contention) but commits separately
and never edits a module a fingerprinted batch writer imports while a run is
live. Workstream A can run immediately; Workstream B is independent and may run
in parallel but reports separately.

## Explicitly out of scope (decided 2026-10-09, council review)

- The rolling-seam shallow-nightly writer (rejected; Alpaca never writes
  canonical bars in steady state; its nightly role is verifier).
- Any change to the 1d primary (IBKR stays; Alpaca's 2016 daily floor loses on
  depth).
- The Yahoo deep-history archive (deferred until a pre-registered research
  question demands pre-2006 data).
- Polygon/Databento (no measured need Alpaca cannot meet).
- Live funding or any live order (paper only).

## Sources

`docs/reference/alpaca-api.md` and the links therein.
