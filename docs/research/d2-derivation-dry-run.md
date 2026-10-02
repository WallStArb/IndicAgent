# D2 1d derivation dry run report

Generated: 2026-10-02T10:26:59.921918+00:00
Mode: dry run (no writes; --apply is plan 185-18)
Rule version: d2-v1; write method: upsert
Venue bars gate (infra.bar_derivation.venue_bars_1d): false

## Totals

| measure | count |
|---|---|
| symbols considered | 931 |
| derived | 931 |
| unchanged (changed-only) | 0 |
| no D1 observations | 0 |
| failed | 0 |
| canonical bars | 3877335 |
| stored canonical-source 1d rows compared | 3874063 |
| changed bars | 5733 |
| pre_split_unrefetched bars | 0 |
| no_provider_volume bars | 0 |

## Changed bars by reason

| reason | bars |
|---|---|
| missing | 3542 |
| d1_value_differs | 312 |
| volume_differs | 1879 |
| split_rescale | 0 |

## Top 20 symbols by changed bars

| symbol | changed | missing | d1_value_differs | volume_differs | split_rescale | pre_split |
|---|---|---|---|---|---|---|
| PLTR | 1006 | 1004 | 0 | 2 | 0 | 0 |
| V | 154 | 5 | 48 | 101 | 0 | 0 |
| EDV | 77 | 6 | 17 | 54 | 0 | 0 |
| TRV | 71 | 5 | 50 | 16 | 0 | 0 |
| MUB | 70 | 4 | 13 | 53 | 0 | 0 |
| EMB | 61 | 6 | 1 | 54 | 0 | 0 |
| FXY | 39 | 6 | 28 | 5 | 0 | 0 |
| HYG | 39 | 5 | 22 | 12 | 0 | 0 |
| IBIT | 39 | 11 | 0 | 28 | 0 | 0 |
| BIL | 34 | 6 | 0 | 28 | 0 | 0 |
| VYM | 34 | 5 | 15 | 14 | 0 | 0 |
| COIN | 31 | 9 | 0 | 22 | 0 | 0 |
| SMH | 30 | 6 | 0 | 24 | 0 | 0 |
| SPY | 30 | 6 | 0 | 24 | 0 | 0 |
| CRWD | 29 | 9 | 0 | 20 | 0 | 0 |
| IEF | 28 | 11 | 0 | 17 | 0 | 0 |
| SHY | 28 | 10 | 0 | 18 | 0 | 0 |
| SLV | 28 | 5 | 3 | 20 | 0 | 0 |
| DBA | 27 | 6 | 8 | 13 | 0 | 0 |
| GLD | 27 | 4 | 7 | 16 | 0 | 0 |

## Symbols with pre_split_unrefetched bars

None: no symbol has a pre_split_unrefetched bar.

## Sample differing bars (up to 30)

| symbol | date | stored close | canonical close | reason | fields |
|---|---|---|---|---|---|
| AA | 2026-08-03 | 44.84 | 44.84 | volume_differs | volume |
| AA | 2026-08-05 | 47.69 | 47.69 | volume_differs | volume |
| AA | 2026-09-11 | 48.26 | 48.26 | volume_differs | volume |
| AA | 2026-09-18 | 44.43 | 44.43 | volume_differs | volume |
| AAPL | 2026-07-29 | 338.19 | 338.19 | volume_differs | volume |
| AAPL | 2026-07-30 | 333.43 | 333.43 | volume_differs | volume |
| AAPL | 2026-08-03 | 303.42 | 303.42 | volume_differs | volume |
| AAPL | 2026-08-04 | 309.38 | 309.38 | volume_differs | volume |
| AAPL | 2026-08-06 | 312.41 | 312.41 | volume_differs | volume |
| AAPL | 2026-08-07 | 313.33 | 313.33 | volume_differs | volume |
| AAPL | 2026-08-10 | 308.26 | 308.26 | volume_differs | volume |
| AAPL | 2026-09-09 | 315.34 | 315.34 | volume_differs | volume |
| AAPL | 2026-09-10 | 326.57 | 326.57 | volume_differs | volume |
| AAPL | 2026-09-11 | 332.27 | 332.27 | volume_differs | volume |
| ABNB | 2026-09-21 | 166.84 | 166.84 | volume_differs | volume |
| ACGL | 2026-09-22 | 94.95 | 94.95 | volume_differs | volume |
| ACMR | 2026-09-21 | 72.77 | 72.77 | volume_differs | volume |
| ACN | 2026-09-21 | 186.11 | 186.11 | volume_differs | volume |
| ACRS | 2026-09-22 | 5.72 | 5.72 | volume_differs | volume |
| ADBE | 2026-09-21 | 249.52 | 249.52 | volume_differs | volume |
| ADBE | 2026-09-22 | 238.25 | 238.25 | volume_differs | volume |
| ADM | 2026-09-09 | 86.55 | 86.55 | volume_differs | volume |
| ADM | 2026-09-15 | 86.61 | 86.61 | volume_differs | volume |
| ADM | 2026-09-18 | 85.18 | 85.18 | volume_differs | volume |
| AEP | 2026-09-22 | 120.27 | 120.27 | volume_differs | volume |
| AES | 2026-09-21 | 14.83 | 14.83 | volume_differs | volume |
| AFL | 2026-09-21 | 115.18 | 115.18 | volume_differs | volume |
| AGG | 2026-06-15 | 98.85 | 98.85 | volume_differs | volume |
| AGG | 2026-06-16 | 98.97 | 98.97 | volume_differs | volume |
| AGG | 2026-06-18 | 98.9 | 98.9 | volume_differs | volume |

## Reading of the result (measured 2026-10-02)

All 931 1d-eligible names derived; 3,877,335 canonical bars against 3,874,063
stored canonical-source rows; 5,733 bars would change. No split exists
(corporporate_action is empty), so split_rescale and pre_split_unrefetched are
zero by construction today; the venue gate is false, so no ibkr_venue bar is
canonical. The three change buckets:

- missing (3,542). Two causes, measured by SQL over the D1-versus-stored gap:
  (a) PLTR: D1 SMART TRADES serves back to its 2020-09-30 direct listing while
  the stored corpus starts 2024-09-25 (the listing-venue move); 1,004
  pre-move bars. (b) Stored-corpus lag on recent sessions while the nightly
  1d backfill is held (todo 488): 2026-09-29 missing on 931/931 names,
  2026-09-25 on 743, 2026-09-24 on 188, 2026-09-30 on 83 (the fresh fetch ran
  before that session's close), the rest scattered. The apply run (185-18)
  writes both from D1, which is the convergence D2 exists for.
- volume_differs (1,879). Prices bit-equal, volume only. IBKR daily volume is
  not stable across fetches (late odd-lot corrections; AAPL 2026-07-29 stored
  35,047,270 vs fresh 35,047,269, one share). Concentrated in mid-2026
  sessions. The rule writes the latest fetched volume.
- d1_value_differs (312 price fields). This is the seam audit's unexplained
  set (docs/research/split-seam-audit.md), measured exactly: 226 bars in
  2006-2008 (old ETF days, 0.2-0.7%), 73 bars on 2026-08-06 (0.6-2.7%,
  MARA 2.65% the largest), 13 scattered single days 2009-2015. The rule takes
  the fresh SMART value (latest real fetch wins); plan 23's
  daily-versus-intraday check is where the two sides get settled, and a
  later re-fetch can flip them again.

Decision state for 185-18: the apply run writes all 5,733 bars under d2-v1
with lineage for all 3,877,335 canonical bars, then reruns the D2a scrub and
writes 1d month digests for every month (first run: no current digest exists).
