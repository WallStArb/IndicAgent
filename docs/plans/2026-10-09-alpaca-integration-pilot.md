# Alpaca integration pilot

Author: Brandon with Claude Code (session, 2026-10-09)
Status: workstream A executed 2026-10-09; results recorded below
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

---

## Results (2026-10-09, Workstream A executed same day as registration)

Puller: `scripts/research/alpaca_pilot_pull.py`; data and analysis under
`data/scratch/alpaca-pilot/` (scratch, not committed). All series complete:
1d and 5m full depth for all 22 names, 1m full depth for AMD, BIL, CRM, DBC,
EFA.

### Throughput and bounds (B1, B2, F1-F3)

- 3,271 + 22 requests, all HTTP 200; 0.577 h wall; 94.4 requests/min sustained
  (Basic cap 200; the client limiter at 190/min is halved by per-request
  latency). Bound B1 respected (under 10,000). B2 verified: no canonical
  writes; scratch only.
- Depth measured: 5m complete from 2016-01-01 on every name (220k-497k bars);
  1m complete from 2016 on the subset (0.86M-1.9M bars). RTH-window 5m slots
  complete every year (19.4k-19.7k/year vs ~19.6k expected) back to 2016; the
  growing raw year totals are extended-hours bars, not RTH gaps.
- F1 extrapolation, 233 names: 1d is 1 request/name; 5m averages ~120
  pages/name, so the full 5m build is ~28,000 requests, about 5 hours at the
  observed sustained rate. F2 storage: ~300k 5m rows/name at 29.3 bytes/row is
  roughly 2.0 GB; 1m would add roughly 7 GB. Both fit the design's 17 GB
  envelope comfortably.

### C1/C2: 1d close basis (criterion: per-name pass rate >= 99% at 10 bp)

First pull (default adjustment) failed structurally: every name with a split
in the window showed exactly ratio-sized offsets gated to the pre-split era
(AAPL 4:1 from 2020-08, ISRG 3:1 then cumulative 9:1, XLY and BIL 2:1).
Diagnosis: the stored canonical 1d is split-adjusted (AAPL 2016 stored close
24.615 = Alpaca raw 98.46 / 4); Alpaca's default history is split-raw.
Re-pulled all 22 names with explicit `adjustment=split` (+22 requests):

- 18 of 22 names at or above 97.4% pass, 12 at or above 99%; median basis 0.0
  bp on 18 names (exact to the float). Post-D era under-powered (1 common
  session) as pre-registered.
- Residual failures are spinoff/merger events, not noise: MMM (Solventum,
  2024), PFE (Upjohn, 2020), TMUS (Sprint merger, 2020) fail pre-event eras at
  the spinoff factor; EWT drops to 91.5% under split adjustment for reasons
  not yet characterized. The stored convention carries spinoff adjustments;
  `adjustment=split` does not replicate them and `all` would overshoot into
  dividend adjustment.

**C1 verdict: FAIL as written (all-names gate), with the failure fully
characterized.** Price basis is exact wherever adjustment conventions align.
The depth build must run the project's corporate-action adjustment layer
(`src/intelligence/bars/corporate_actions.py`) on top of Alpaca's
`adjustment=split` to align spinoff/merger conventions, or admit names
conditionally on adjustment class. Either is a build-plan decision, not an
obstacle: it is the same treatment Tradier needed for the same events.

### C3: 5m close basis (1 bp, common stored window, RTH slots)

17 of 22 names pass at 99.7%+ (13 at 99.9%+, median 0.0 bp on most). Three
names fail with structure (DBC 68.7%, UUP 57.4%, PFE 39.6%) and none of the
three has a split in the window, so this is not the C1 effect; candidate
causes are stored-side 5m quality on these names or slot alignment for the
commodity/currency vehicles. Diagnose in the depth-build plan before storing
these names; **C3 verdict: PASS on 17/22, FAIL/INSPECT on 3, no verdict on
the other 2 (FXE/EWT insufficient common slots).**

### C4/H1: volume convention

For the five 1m names: Alpaca 1m RTH-aggregated volume does NOT reproduce the
Alpaca 1d bar's volume; median relative gap 6-26% per name (AMD 17.8%, CRM
25.9%). Alpaca's 1d volume includes extended hours. Independent confirmation:
a Massive (Polygon, the upstream) free-tier key returns AAPL 2026-09-01 daily
volume 53,167,388, exactly the stored Tradier value and Yahoo's to rounding,
while Alpaca reports +0.37%. The upstream daily convention equals the stored
convention; **the deviation is Alpaca's aggregation.**

**Volume rule (decided by H1):** any stored Alpaca bar uses RTH-window
aggregation from Alpaca's own intraday bars; Alpaca 1d bars are never stored
wholesale. This rule is era-safe only when combined with the RTH filter
verified complete back to 2016.

### Boundary-D basis amendment note

Massive free tier: 2-year lookback, 5 requests/min, adjusted aggregates only
(403 beyond 2 years). Kept in `.env` (`MASSIVE_API_KEY`) as a diagnostic
reference for recent windows only; same upstream as Alpaca, so it never
substitutes for the IBKR basis check.

### Decisions this pilot hands to the depth-build plan

1. Pull 1d/5m/1m with `adjustment=split`; apply the corporate-action layer for
   spinoff/merger names, or gate their admission per adjustment class.
2. Store RTH-window aggregates only; never Alpaca 1d bars.
3. Diagnose the 3 C3 names and EWT before their admission.
4. 1m storage is affordable (~7 GB) but has no registered consumer; stays
   out of the build unless a spec pre-registers a need.
5. Full 5m build for 233 names is a ~5-hour, ~28k-request job at Basic rates.
