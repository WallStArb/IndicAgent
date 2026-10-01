---
status: pending
priority: P2
filed: 2026-10-01
source: interactive session, crash-precursor check (HYG ratios are a coincident proxy only)
---

# FRED credit spread and Treasury yield reference data

## What

The DB holds no credit spread series. The only credit gauges are ETF price ratios (`HYG/LQD`,
`HYG/TLT`, `HYG/IEF`), which are coincident risk-on/off measures: on 2026-10-01 they showed no
lead before the 2007, 2018 or 2020 drawdowns, and they are price-only (HYG distributions are
missing, so the raw ratios drift down). `HYG/TLT` and `HYG/IEF` also start only in 2016 and 2017
(TLT and IEF history gap). A spread level and its trailing percentile is the standard credit input
and cannot be built from what we store. No FRED client exists anywhere in the codebase.

## Options

1. Keep the ETF ratios. Cheapest; cannot express "spreads at multi-decade tights".
2. Add FRED credit spread series as owner-approved reference data (the todo 428 dividend
   precedent): daily, free, keyed, a few thousand rows.
3. Add a paid spread source. Not justified for a daily context series.

## Recommendation

Option 2. A single new reference table with a dedicated writer, no change to `market_data_ohlcv`.

Step 0 is resolved (2026-10-01, live FRED pull with the key from the sibling `ssfi` project's
`.env`, var `SSFI_FRED_API_KEY`, provisioned 2026-08-31): the ICE BofA OAS series are limited to a
trailing 3 years (BAMLH0A0HYM2, BAMLC0A0CM, BAMLH0A3HYC, BAMLC0A4CBBB all start 2023-10-02), so
they are forward-only collection. `BAA10Y` starts 1986-01, `DGS10`/`DGS2`/`T10Y2Y` 1980-01,
`DFII10` 2003-01, `THREEFYTP10` 1990-01, `USEPUINDXD` 1985-01. History for credit is therefore
`BAA10Y` plus the 3-year ICE window. indicagent needs its own key var in `Settings`
(`FRED_API_KEY`); the secret is not copied into the repo.

## Scope: registry-driven, tiered

The provider and table are generic; what is stored is the APR list, so widening scope is a config
change, not a migration. Raw is permanent (principles: never drop data that could contain signal).
Tier 1 is the series above. Tier 2 candidates, to verify at fetch time: `VIXCLS`, `VXVCLS`
(vol term), `NFCI`, `STLFSI4` (financial conditions), `T10YIE`, `T5YIFR` (breakevens), `WALCL`,
`RRPONTSYD` (liquidity), `DFF`, `SOFR`, `DTB3` (policy rate and bills), `DTWEXBGS` (broad dollar),
`DCOILWTICO`, `ICSA` (claims), `USREC` (recession dates, label only). Series that FRED revises
(claims, CPI, payrolls, GDP) need vintage keys: use the ALFRED real-time parameters and key rows by
(`series_id`, `observation_date`, `realtime_start`) so a read as of t sees only the value known at
t. Precedent in the sibling project: `ssfi` migration 040 (vendor restatement, vintage keying);
read it before designing the key. Tier 2 enters only with a named consumer, so the store does not
become a dump; the registry row records provider, frequency, revision behavior and consumer.

## Sibling project inventory (`/home/bg/dev/ssfi`, read 2026-10-01)

`ssfi` has decided and designed its data sources but collected nothing (no ssfi database exists on
this host), so there is no data to reuse; the value is design and source research.
`docs/research/data-sources-candidates.md` there holds verified API mechanics.
- Reuse the design: vintage keying (migration 040: key includes FRED `realtime_start`, or a fetch
  date for sources with no vintage; UPDATE/DELETE revoked so append-only is enforced by the
  database) and its vendor adapter and credential conventions (`docs/foundation/data-layer.md`).
- Worth adding as Tier 2 here, free and daily, macro or market-wide: NY Fed Markets Data API
  (SOFR and the other reference rates, Primary Dealer positions and financing, SOMA securities
  lending): funding and repo stress, not in FRED at the same grain.
- Worth a separate look, per-symbol and free: FINRA daily short-sale volume and SEC fails-to-deliver
  (both list ETFs; our universe is mostly ETFs), NYSE and Nasdaq trading halts.
- Poor fit for this universe (single-stock): Form 4 insiders, 13F, 13D/G, XBRL fundamentals.
  Keep them in ssfi.

## Steps

1. Done (see above). Re-run the length check before the backfill if the licence terms change.
2. Series (APR JSON list `infra.fred.series`, behavioral list): `BAMLH0A0HYM2` (HY OAS),
   `BAMLC0A0CM` (IG OAS), `BAMLH0A3HYC` (CCC), `BAMLC0A4CBBB` (BBB), `BAA10Y`, and the rate
   level set `DGS10`, `DGS2`, `T10Y2Y`, `DFII10` (10-year real yield), `THREEFYTP10` (term
   premium). Rates are in scope because no yield level is stored either: `macro_features`
   `yield_curve_slope` is NULL and its last write is 2026-06-18, so the only rate view is TLT/IEF
   price (TLT history starts 2016). EPU
   (`USEPUINDXD`) is the second consumer, owned by `docs/ideas/signal-political-policy-regime.md`;
   build the provider generic so adding it is a list change.
3. `src/providers/fred.py`: plain HTTP GET per series, key via `Settings` (never `os.environ`).
4. Table `macro_series_observations` (concept name derives layer names per `naming-system.md`):
   `series_id`, `observation_date`, `available_at`, `value`, append-only; a revised value is a new
   row, never an overwrite. `available_at` is the first fetch time or the publication lag (FRED
   daily series arrive one business day late), so reads honour `temporal_integrity`. Missing
   observation days stay absent (`no_fill`); no forward-fill in the store.
5. A dedicated writer (`BaseWriter`/`BaseBatch` subclass) owns the table (`single_writer`); the
   provider only fetches. Daily timer, `job_completed_total` at exit, service registered in
   `_DAG_ORDER`/`_AGENT_ID_TO_UNIT`, lag threshold as an `alert.lag.*` APR key.
6. Register the series as concepts in the registry; table row in `docs/foundation/glossary.md`
   for "option-adjusted spread" before any code names it.
7. Backfill history, then verify against the source: row counts and a spot check of known dates
   (for example the 2008-12 peak and the 2020-03 spike).

## Evidence handling

Levels pulled 2026-10-01 (descriptive; one look): 10-year yield 5.26%, the highest since
2007-06-12; 10-year real yield 2.91%, the highest since 2008-11-24 (max 3.15% on 2008-11-21);
term premium 1.02%, 63rd percentile since 1990; 10s2s slope +0.41, positive; `BAA10Y` 1.46, 3rd
percentile since 1986 (near the 1989 minimum of 1.16, so the Baa-Treasury spread is compressed
while yields are high); HY OAS 3.08% against a 3-year range of 2.59 to 4.61 (53rd percentile of
that window only, tighter than the 4.61 of April 2025). Rates are high and credit is not
stressed; the 2007 parallel on the rate level holds (same 10-year yield), the credit side does
not (compressed, not widening).

Rate-shock check, 2026-10-01 (descriptive, one look): TLT closed 78.62 on 2026-09-28, its lowest in
our history (since 2016-02), 10.0% below 63 days earlier and 14.6% below its 252-day high; a
63-day move that weak is at the 5th percentile of all-time-high days. That is consistent with a
10-year yield above 5%, but the yield level itself is not stored, so the 5% claim is unverified
here. In the ATH-day sample, 63-day TLT moves worse than -8% (n=125, years 2016, 2017, 2021,
2024, 2025) were followed by a 10% drawdown in 14% of cases, the -8% to -3% bucket in 32%, and
smaller moves in 20%. No monotone pattern, about five episodes; it neither supports nor refutes
a rate-shock warning (2018Q4: -7% TLT then -20% SPY; 2024Q4: -5% then -18%).


This todo builds data only. No test runs under it. The first use is one pre-registered spec
committed before the result exists: HY OAS level percentile (and, as a second pre-registered arm only if the first is specified, the 10-year real yield change over 63 days) (trailing 10 years) at S&P all-time
highs against the forward 6-month maximum drawdown, block bootstrap over episodes, counted as one
look at the vintage. Expect about five independent episodes in the ETF era and more with Moody's
history; the spec states the power before running. A pre-2006 start needs index history from
another owner-approved source.

## Related

- TLT and IEF history start 2016-02 and 2017-08 while HYG starts 2007-04: check whether this is an
  intraday-campaign (449) or 185 backfill gap before treating it as the provider's limit.
- Policy regime idea doc: its provider plumbing section (FRED client) is this todo's step 3.
