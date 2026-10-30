# 1d session coverage: era-scoped, inference-free

Author: data lane executor, 2026-10-29. Informed by: 191-20-D7-HOLDS.tsv, two independent reviews of the first two attempts, live read-only judge runs.

## Final rule

`session_coverage` (1d, threshold 0.999, APR `threshold.bar_integrity.session_coverage_min_1d`, unchanged) is the share of NYSE sessions that hold a canonical bar or an `ohlcv_empty_history` span, judged from max(the name's first canonical bar, the era start) to the last completed session.

The era start is the session calendar's first session, `MarketCalendar.first_session("NYSE")` in `src/core/market_calendar.py` (2005-01-03; `_PMC_RANGE_START` is 2005-01-01). No feature row exists before it, so a data hole earlier than it cannot reach a feature. It is read from the calendar, not copied, and is not an APR key (a derived value, one source of truth). `judge_name_1d` takes it as the required keyword `era_start`.

An answer is a stored bar or an empty-history span. Nothing else: a session with no bar is never read as a no-trade day.

## Why no inference

Two attempts counted a missing session inside a corroborated vendor window as an answered no-trade day. Both failed independent review.

1. Commit 2bc1e2e9a (every no-bar session between the vendor's first and last raw bar in a successful window). 69 of the 97 names it newly passed passed on multi-week IBKR history holes, not no-trade days (LVS 21 sessions after its IPO, AIZ 21 sessions at 14M to 27M volume, LGND 192 consecutive, PFBC 831).
2. Commit 2fe0bc758 (the same, bounded by a run cap of 3 and a neighbour-volume cap of 50,000 shares, migration 543). A labelled test, IBKR alone against Alpaca SIP from 2016, gave a 29 percent false-answer rate (7 of 24 answered sessions traded on SIP). Vendor-wide IBKR hole dates are answered as no-trade (2007-07-02: 288 of 847 live names have no bar). IBKR serves explicit flat zero-volume bars for real no-trade days, so a missing bar is not the vendor's no-trade answer. Nothing capped the total answered share.

Absence of a bar cannot be proven to be a no-trade day, so the rule was deleted (both commits reverted; migration 543 was never applied, and `config_schema` holds no `threshold.bar_integrity.no_trade%` key).

## Measurements (live data, 2026-10-29, the real judge, read-only)

Today's data has moved since 191-20-D7-HOLDS.tsv was written (IBKR 1d backfill landed): 11 held names with a session_coverage finding already pass under the pre-era rule.

| | pre-era rule | era rule |
|---|---|---|
| names passing, of 1,501 with a canonical bar | 1,304 | 1,345 |
| the 1,273 D7-passing names | 1,272 | 1,273 (0 fail) |
| held names with a session_coverage finding, passing (of 207 scored; QRVO has no bar) | 11 | 51 |
| of those, free of every other hold | | 50 |

The 156 held names that still fail, with in-era coverage, missing sessions and the largest in-era holes, are in 191-SESSION-COVERAGE-ERA-FAILS.tsv. Causes: Tradier-only history gaps in 2007..2015 (OC, GPRE, GWRE, ARWR, TMUS, MUSA, CC), IBKR windows that returned no bars (CBC, SSP, SN, TLN, PPTA, DFTX, TIGO), derivation gaps (todo 566), October 2026 stale tails (PSKY, ACVA, ACA, CCO, BZH, MSGS, CTVA), and a long tail of 1 to 12 session IBKR holes.

Regression check: none of the 1,273 names that passed D7 fails the era rule. The lowest in-era coverage is XSD 0.99904 (5 missing of 5,215), then INSW, FXA, FXI, XLRE, RKLB, AGX, HL, MTUM, XRT and UAMY, all within 0.0005 of the line. Every non-held name's coverage fell by at most 0.00008 (the denominator shrinks, so early coverage no longer pads it). The 11 names within 0.0005 of the line would fail at the next two or three missing sessions.

Sessions that exist on the NYSE calendar but that no vendor served stay in the denominator (2007-02-08, 2007-07-02, 2007-10-22 and others; AGG and LQD miss 2007-08-31..2007-10-16). The rule does not excuse them.

## Tests

`tests/unit/bars/test_integrity_checks.py`: a missing session on 2004-12-31 is ignored and the same on 2005-01-03 counts; a name whose first bar is after the era start is judged from that bar; the empty-history rule is unchanged; a name with early holes only passes; early coverage does not pad the ratio. `tests/unit/test_market_calendar_first_session.py`: the accessor.
