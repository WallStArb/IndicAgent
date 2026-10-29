# Slot coverage fix (todo 565)

Author: data lane executor, 2026-10-29. Informed by: todo 565, `src/intelligence/bars/gap_plan.py`, live `ohlcv_load` reads.

## Semantic

A 5m slot is answered when any of these holds (the first two are unchanged):

1. a stored bar sits on the slot (real or zero-volume provider bar);
2. the slot lies wholly inside an IBKR answered window (`ohlcv_request`, route SMART, TRADES, outcome `bars` corroborated by a stored row, or `no_data`);
3. new: the slot's UTC day lies inside the requested range of an applied Alpaca load of the series, `requested_end` inclusive.

Rule 3 reads `ohlcv_load` with `source = 'alpaca'`, `outcome = 'applied'`, `destination` in (`market_data_ohlcv`, `raw`). The constants are `LOAD_COVERAGE_SOURCES`, `LOAD_COVERAGE_OUTCOMES`, `LOAD_COVERAGE_DESTINATIONS` in `gap_plan.py`; `load_range_windows` converts the day ranges to UTC windows (midnight of the first day to midnight after the last), and the existing `AnsweredWindows` merges them with the request windows. Days without a session hold no expected slot, so a range never creates one. No new tunable; the 0.995 threshold is still `threshold.bar_integrity.slot_coverage_min_intraday` (APR). No migration.

Facts established from the live data:

- 5m outcomes: alpaca `applied` 40,579; ibkr `applied` 12,742, `refused` 75. No other value occurs on 5m. The table also allows loaded, short_history, no_data, failed, gated; none of them counts.
- `requested_end` is inclusive: of 20 sampled nightly loads with raw rows, 18 hold a bar on the end date, none holds a bar after it.
- Alpaca `destination = 'archive'` loads (11,526) are excluded. They are the archive backfill of the same ranges and, for names whose canonical history is IBKR (NFLX, T, XOM and others hold only archive and raw Alpaca loads), they prove nothing about the canonical RTH slots. Counting them would paper over real holes (XLRE 2016).
- IBKR loads are not counted: the existing request-window rule stays the only IBKR source of answers.
- History loads (`alpaca-5m-load`) are 10,000-bar pages; consecutive pages tile the span, so a multi-year page (SN, 2019-01-29 to 2024-01-11) is one answer for the whole span.
- Two nightly test loads (SPY, AAPL, 2026-10-21..26) wrote `iex_rth` rows. Each has a `sip_rth` twin for the identical range, so they change nothing; filtering them in SQL would cost a scan of the 340-partition raw table per name, so they are not filtered.

Applied to both readers of `_ANSWERED_5M_SQL` through `_answered_windows_5m`: the slot_coverage loader and the grid completeness checks (a no-trade 5m slot is the same fact there).

## Recount (read-only, 109 names: every 15th name, the 8 thinnest names, MSM, JKHY, RPM, AAPL checked separately)

Worst-year coverage against 0.995:

| | before | after |
|---|---|---|
| pass (109 sampled) | 13 | 96 |

| name | worst year before | worst year after |
|---|---|---|
| MSM | 0.9751 (2021) | 0.9952 (2026) |
| JKHY | 0.9697 (2024) | 0.9952 (2026) |
| RPM | 0.9892 (2021) | 0.9952 (2026) |
| AAPL | 0.9952 (2026) | 0.9952 (2026) |

Every other year of these four is 1.0000 after. The 2026 value is the same for all of them: 78 slots (the 2026-10-29 session) lack a bar and a load, because the nightly capture for that session runs at 04:40 UTC on the next day. That is one session in about 208, which passes by 0.0002.

Names still below 0.995 after (13 of 109):

| name | worst year after | cause |
|---|---|---|
| XLRE | 0.7439 (2015) | IBKR era 2015-10 to 2016-09 with no Alpaca canonical load (all its Alpaca loads are archive); 2,814 slots without an IBKR answer. A real hold. |
| XBI | 0.9236 (2006) | IBKR-era years 2006-2011, 1,327 slots with no answer. A real hold. |
| VYM | 0.9448 (2006) | IBKR-era 2006-2010, 1,118 slots. A real hold. |
| DE, MSFT, QCOM | 0.991-0.992 (2006) | IBKR-era single days (DE 2006-12-27 whole session) and scattered slots. Holds. |
| APMD, MFP, HONA, SPCX, MBGL, REA, FDXF | 0.984-0.992 (2026) | Listed in 2026; the only missing slots are the 78 of 2026-10-29. A short first year turns one unloaded session into more than 0.5%. Clears after tonight's capture. |

Lowest five after: XLRE, XBI, VYM, APMD, MBGL.

## Holes inside loaded ranges

Names whose canonical 5m has a gap of more than 45 days since 2016-01-04: 15 names, 16 gaps (largest SN 1,623 days 2019-02-19 to 2023-07-31, CART 1,358, LION 895 and 434, NIQ 761, PMTS 567, DOW 566, NESR 544, SMCI 510, CORZ 390, AKTS 388, EVER 385, BTU 357, SD 272, EXE 229, CRC 105). All 15 sit inside applied Alpaca load ranges, so the vendor's answer for them is no trade and the recount passes them (worst year 0.9952, from 0.0 to 0.68 before). They are dormant or relisted tickers (SN is a ticker reused by a 2023 listing), not data loss. A hole outside every load range and answered window is still reported: XLRE 2015-2016 above.

## Fragility to fix next

The gate is judged at the last completed session, but the nightly capture lands the day after. For a name whose current year holds fewer than about 200 sessions, one unloaded session breaks 0.995. Run the audit after the nightly capture, or judge through the last session the load history covers (not done here; it is a policy choice).
