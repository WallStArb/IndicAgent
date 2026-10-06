---
status: done
priority: P1
filed: 2026-09-26
source: forward-return parity check (2026-09-26 session); feeds phase 185 (intraday derivation) and the phase 186 feature_vectors rebuild
---

# Stored 1h bars drop the 09:30-10:00 half hour on 39 symbols, including SPY

## What

The stored 1h grid is anchored two ways. On 192 of 231 symbols (2025-01 to 2025-11) the session
opens with a partial 09:30 bar (09:30-09:59) and then clock hours from 10:00. On the other 39 the
raw table holds a 09:00 row with zero volume (a placeholder, filtered out by
`market_data_ohlcv_tradeable`) and the first real bar is 10:00, so the first half hour of every
session is missing from their 1h series. SPY has no 09:30 1h bar in any year 2006-2025; 87
appear in 2026.

Affected (2025): AGG AMLP ARKK BIL BTAL CIBR CWB DBA DBB DBC DIA EDV EEM EFA EMB EWG EWJ EWT
EWY EWZ EZU FXA FXE FXI FXY IBIT IPO IYT MCHI PPLT SDOG SPHB SPY UUP VTV VWO VYM XLU XLV.

Where a 1h bar exists it equals the aggregate of the 5m bars exactly (open, close and volume,
SPY/AAPL/XLE/IWM 2024-2025). Stored 15m equals aggregated 5m exactly on the same names. The 5m
series is complete; only the stored 1h is short.

## Consequences

- 1h `feature_vectors` for these symbols never see the open's half hour, and the 1h grid differs
  across symbols, so a cross-sectional 1h row compares different intervals.
- `forward_returns` 1h rows for these symbols enter at 10:00, not 09:30.
- S0's 1h grid keeps 09:30 as a slot (present on at least half of sessions) and gives these 39
  names NaN there.

## Fix

Derive 15m and 1h from 5m on session-anchored edges in the data layer (phase 185, the
derivation stage), write them as the only 15m and 1h bars, and rebuild 1h features on them in
phase 186. Measure first: whether other timeframes or years carry the same placeholder pattern,
and whether the 39 share a fetch path (client, exchange routing, request type).

## Planned (2026-09-27)

Phase 185 plans 06 (session grid and digest), 11 (writer, raw archive, single-writer CI) and 12 (live rewrite, IBKR 15m/1h kept as raw observations with a parity check, the 42-name 09:30 refetch).

## Closed 2026-10-06 (phase 185 plan 24)

Fixed by the derived grid (D2b): plan 185-11 built the writer (15m/1h from tradeable 5m on
session-anchored edges, IBKR answers archived in `ohlcv_intraday_raw_archive`), plan 185-12
rewrote the stored grid and chained it into the nightly, and plan 185-25 removed every
placeholder row. SPY now holds 5,086 1h bars starting 09:30 ET (2006-07-07 to 2026-09-29). The
185-23 audit's `masked_slots` check reports zero masked 15m and 1h slots on derived symbols.
Phase 186's rebuild computes 1h features on these bars.
