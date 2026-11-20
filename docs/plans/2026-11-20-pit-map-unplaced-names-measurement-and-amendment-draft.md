# Unplaced names in the pit map: measurement and amendment draft

Status: DRAFT 2026-11-20, read-only measurement; nothing applied, no map or database change. Owner decision needed before any of Part 3 runs. Prereg context: `docs/plans/2026-11-13-stage2-universe-preregistration.md` (closed list, Amendment 2026-11-18; candidate pin, Amendment 2026-11-20); todo 624 (reused tickers); pit map `data/ticker_entity_map/20261118_6195ae11abff` (gap list, spans).

## 1. What is unplaced

Source: the 5,834,681 entries of the Massive `pit_snapshots` lists (37,470 tickers, 2003-09-30 to 2026-11-09), read through temp tables only; the `@inactive` lists are ignored (they carry delisted names at every month-end, so an unplaced inactive entry is not a missing month). A ticker-month is placed when a live `ticker_event` span of that ticker covers the month-end. Scripts and outputs: `logs/unplaced_reach_20261120/` (reach.sql, reach2.sql, chg.sql, tier.sql, per_ticker.csv, cik_changes_active.csv).

| Measure (active lists, CS and ADRC) | Value |
|---|---|
| ticker-months | 1,092,370 |
| unplaced ticker-months | 35,495 (3.25 percent), 798 tickers |
| ticker-years with an unplaced month | 3,634 |
| tickers live in the list at L = 2026-11-09 that have an unplaced month | 241 |
| tickers unplaced at L itself (never candidates under the closed list) | 128 (CS 127, ADRC 1; ETF 0 of 5,555) |
| unplaced ticker-years with at least 60 canonical 1d sessions under the symbol that year | 1,203 ticker-years, 223 tickers |
| of those, median dollar volume at least $25M (tier entry) | 728 ticker-years, 122 tickers |
| of those, median dollar volume at least $12.5M (tier exit) | 862 ticker-years, 140 tickers |
| unplaced at L with a 2026 median dollar volume of at least $25M / $100M | 88 / 61 names |

The names at L are not obscure: Agilent (A), Accenture (ACN), Aon (AON), Aptiv, Amcor, Allegion, Ares Management, Amer Sports, Warner Bros Discovery (WBD), Paramount Skydance (PSKY), Smurfit Westrock (SW). Full list: `logs/unplaced_active_at_L/unplaced_active_cs_adrc.csv`. Dollar volume is by symbol from canonical 1d, so for a reused ticker a year's figure may belong to an earlier issuer; it is a size indication, not a membership verdict.

### Causes

By pattern over the 798 tickers: never placed 467 tickers (23,215 months, 99 live at L); partly placed with a CIK change 88 (5,099 months, 28 unplaced at L); partly placed with one CIK 243 (7,181 months, 1 unplaced at L).

- Existing instruments the earlier FIGI and events map could not place. The map's own gap list (`gap_list.csv`, scope `instrument`) names the reason: of the 128 unplaced at L, 121 are on it: `massive_no_figi` 94 (ACN, AON, SW), `event_chain_head_mismatch` 17 (A: the Massive events chain for A has head AWD), `asset_class_outside_vendor` 6, `no_span_survived` 3, `events_malformed` 1. The pit install is additive, so an existing instrument with no identity stayed without a span although a pit run of its own ticker and CIK exists.
- Records with no CIK and no FIGI. Of 363 never-placed tickers not on the gap list, 249 carry no CIK in any month and 239 no FIGI; they are unplaced by the key rule (key kind needs a FIGI or a CIK); 107 appear in one month only; only 38 are instruments and 7 are live at L. This is the already disclosed residual (unplaced share 0.0442, counted in ticker-years, not by name).
- CIK change. The premise that a CIK change across lists is the cause is mostly false. Across the active lists there are 1,281 CIK changes (1,073 tickers): 852 follow a gap, 323 are contiguous with a similar name, 102 contiguous with a dissimilar name, 4 change exchange. In 1,227 of them (96 percent) both sides are placed (the map keeps each CIK run as its own security, `X~cik`). Only 54 changes leave a side unplaced (41 after the change, 11 before, 2 both); 15 of the 41 are contiguous with a similar name, 12 of those live (ACN 2009-09, AU, BATRA, BG, BK, BZH, DUK, ETN, FWONK, MDT, MSG, NE).
- SW is a different case: WRK (CIK 1732845) to SW (CIK 2005951) is a ticker change with a new CIK, and SW has no span although the list holds SW from 2024-07-31. It is on the gap list as `massive_no_figi`, so it is the first cause, and the A3 sweep's identity line for SW 2016-05-16 clears when SW is placed from 2024-07-08.

## 2. Evaluation of a continuity rule

A rule that merges across a CIK change (same ticker, contiguous month-ends, same exchange, name token overlap of at least 0.5 after legal suffixes and class words are dropped) acts on 323 changes. On the 624 reused-ticker population in the same data it is correct on the three CIK-change cases it can see: FAF 2010 (spin-off child reuses the ticker; contiguous, same exchange, name overlap 0.25, so not merged), SN 2019 to 2023 (gap, not merged), HLT 2007 to 2013 (gap, not merged). The other 624 cases (THRM, SSB) are inactive-list cases outside this test. With 0 of 3 wrong the false-positive rate is not estimated; the upper 95 percent bound is 63 percent. A name-overlap threshold also fails on legal renames (ASH to Ashland Global, ANGI, APA, all dissimilar). Conclusion: a merge-across-CIK rule is not needed for the bulk and its false-positive rate cannot be shown, so it is not proposed as an automatic rule; the 15 contiguous-similar cases with an unplaced side are a hand-reviewed list.

## 3. Proposed amendment (for the owner)

Rule P1, placement onto an existing instrument with no identity. For an instrument whose symbol s is on the gap list at scope `instrument`, and a pit run of ticker s with one CIK c (consecutive active month-ends with at most one missing, the existing run definition) that has no overlapping live span of that symbol: insert a `ticker_event` span (symbol s, ticker s) from the run's first month-end (or the archive start) to its end (open when the run reaches L). No merge across a CIK change: a run with another CIK of the same ticker stays its own security (`s~cik`). Deterministic from the pit lists and the gap list; no returns or prices. Evidence recorded per span as in the existing install. SW is placed from 2024-07-31 by P1 (the list's first month-end; the 2024-07-08 listing date is not in the lists), so its pre-2024-07-31 Alpaca bars stay unplaced, which is what the identity disposition says.

P1 covers 121 of the 128 unplaced at L. The other 7 are not instruments on the gap list; they and the 15 contiguous-similar CIK changes are a hand-reviewed list with per-name evidence (an owner call whether it is worth doing; they are 22 of 128 names).

Not proposed: placing the 249 key-less tickers (no CIK, no FIGI: no identity to key on), and an automatic merge across a CIK change.

## 4. Re-run cost and effects

- Map: an additive amend through the existing `--amend` path of `services/ticker_entity_map_writer.py` (spans for existing instruments; no instrument or identifier is added). Minutes of database work; one dated amendment with the span file digest.
- Membership: `universe_membership` and its ledger are insert-only, so the rows must be rebuilt, not extended: a migration that clears the two tables under the same pattern as the first build (owner approval, nothing has consumed membership yet), then the writer (s5): 156 s rehearsal and 232 s apply on 2026-11-19. Members at month-ends gain the placed names; counts move by up to about 120 names in the later years and fewer earlier (728 name-years at the tier entry over the whole history).
- s3 is not re-run. s6 (counts by year) and s7 (5m tier cost estimate) are re-read after the rebuild, minutes. The 1d canonical bars of these instruments exist; 5m for the new tier names is derived by the planned tier run (about 122 names of 4,938 in the tier today, a few percent more rows than the 0.97B planning figure). Disk: no new raw; derived 5m about 2 to 3 percent above the plan.
- The closed-list digest pin (`CLOSED_LIST_CANDIDATES_SHA256`, 13,103 lines, `e13546aa78be46026b204ea5de46cbd09a181c177f6a14cc206cbbeaf3b1b29c`) changes: the candidate set at L gains about 121 symbols. It is repinned in the same dated amendment from the post-amend data, before any closed-list month is built; the pin tests and the report line follow. The pin stays pre-registered, not APR.
- Gates: independent review of the span file (a sample of names plus every name above $100M a day), the member-history audit and the unplaced reach script rerun (this document's numbers are the before), `repro_frozen` untouched because no file under `src/intelligence/research/` or `statistics/` moves.

## 5. Decisions needed

1. Adopt P1 (placement of same-CIK runs onto existing instruments that lack identity): yes or no.
2. The reviewed list for the 15 contiguous-similar CIK changes and the 7 off-list names: do it, or disclose as a residual.
3. Reset and rebuild the membership tables (now, before any counted look) and repin the candidate digest in the same amendment.
