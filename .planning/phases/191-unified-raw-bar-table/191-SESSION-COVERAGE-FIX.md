# 1d session coverage fix

Author: data lane executor, 2026-10-29. Informed by: 191-SLOT-COVERAGE-FIX.md (todo 565, the 5m analogue), 191-20-D7-HOLDS.tsv, live read-only `ohlcv_request`, `ohlcv_load`, `ohlcv_raw` and `market_data_ohlcv` reads.

## Problem

`session_coverage` (threshold 0.999, APR `threshold.bar_integrity.session_coverage_min_1d`) counted a session answered only when the name had a canonical bar or an `ohlcv_empty_history` span (`_EMPTY_SESSIONS_SQL`). A session on which a vendor answered successfully and served no bar (no trade that day) counted as missing. ABCB: 37 sessions between 1999-10-29 and 2002-03-22, all inside successful IBKR requests and loads, coverage 0.9944.

## Semantic

A 1d session is answered when any of these holds (the first two are unchanged):

1. a canonical bar sits on it;
2. an `ohlcv_empty_history` span (IBKR confirmed empty history) covers it;
3. new: it lies inside the corroborated span of a successful canonical-vendor answer and the vendor served no raw bar on it.

An answer is either a request or a load:

| Evidence | Rows counted | Rows never counted |
|---|---|---|
| `ohlcv_request` | (ibkr, SMART, TRADES) and (alpaca, SIP, 1Day), outcome `bars`, caller not `test-%` | tradier (retired, lineage only); IBKR venue routes (NYSE, ARCA, AMEX, ISLAND, BATS); ADJUSTED_LAST; alpaca IEX; outcomes `no_data`, `failed`, `timeout`, `legacy_import` |
| `ohlcv_load` | source ibkr or alpaca, outcome `applied`, destination `raw` | `derived` loads (the daily stage's own output), tradier loads, refused, failed, loaded, short_history |

Constants: `DAILY_ANSWER_REQUESTS`, `DAILY_ANSWER_OUTCOME`, `DAILY_ANSWER_LOAD_SOURCES`, `DAILY_ANSWER_LOAD_DESTINATIONS` in `src/intelligence/bars/gap_plan.py`; the load outcome reuses `LOAD_COVERAGE_OUTCOMES`. Loaders: `_ANSWERED_1D_REQUESTS_SQL` and `_ANSWERED_1D_LOADS_SQL` (one read each for the whole corpus, in `_verdict_report_1d`). Pure rule: `answered_window_spans` in `integrity_checks.py`. No migration, no new tunable.

Corroboration (the guard against a lost insert): a window answers only the days from the vendor's first raw bar inside it to its last. A window with none of the vendor's bars answers nothing, and the days before the first or after the last bar stay unanswered (a pre-listing head, a stale tail, IBKR history that starts later).

Served sessions: a session on which the name has a raw observation but no canonical bar is never answered by a window. The vendor served a bar there; the canonical series lacking it is a derivation gap (below), not a no-trade answer. Without this guard 59 more names passed that should not (156 instead of 97 below).

## Facts established from the live data

- 1d request outcomes with `bars`: ibkr SMART TRADES 23,158; alpaca SIP 1Day 7,631; tradier 6,506 (excluded). IBKR venue routes and ADJUSTED_LAST also carry `bars` rows and are excluded.
- Window end is exclusive for IBKR. Of 147 IBKR 1d requests whose raw rows are linked by `request_id`, none holds a bar on or after its `window_end` date (ABCB: window_end 2002-03-23, last bar before it 2002-03-21, the unanswered 2002-03-22 is inside). A midnight end excludes its own date; an Alpaca nightly end (17:30 UTC) takes its day in. This is the end-exclusive rule the other 1d readers use (`timestamp < window_end`); an inclusive end is refuted for IBKR requests.
- IBKR `window_start` is unreliable on the low side: 22 of the 147 have bars before it (ABCB's first request starts 1999-12-20, its bars start 1999-10-25). Alpaca requests carry no linked raw rows.
- The applied raw loads give the missing low side. On all 19,661 applied ibkr (12,031) and alpaca (7,630) 1d raw loads, `requested_start` equals `first_bar` and `requested_end` equals `last_bar` (inclusive), so a load range is the span of the bars the vendor returned. Requests and loads go through the same corroboration, so a load adds nothing a vendor bar does not support.
- ohlcv_empty_history (the existing rule) is unchanged and its SQL still reads no request table.

## Recount (read-only: the changed loaders and the changed judge on the live data, no service, no write)

Names held by the D7 1d verdicts: 229. The recount scored 207 of the 208 that carry a `session_coverage` finding (QRVO has no canonical bar and cannot be scored: 0 bars, listing ended 2026-10-02).

| | before | after |
|---|---|---|
| names passing `session_coverage` (of 207 scored) | 0 | 97 |
| held names with no remaining finding (of 229) | 0 | 95 |

The 95 are the 97 passes less 2 (EWZ, HWKN) that still carry an unexplained_seam hold. They can leave the hold list.

The 1,273 names D7 passes: 1,273 of 1,273 still pass, no name's coverage fell (the new rule only adds answered sessions). 256 of the 1,281 canonical-bar names outside the hold list gained sessions without crossing the line; the 8 not in compute_1d (EIS, H, IOT, KNSL, PNFP, REMX, RPRX, SHEN) fail before and after and are out of D7's scope.

## The 110 names that still fail, by cause

### 1. Derivation gap: 71 names (todo 566)

For these 71 the only remaining cause is sessions where `ohlcv_raw` holds a canonical vendor's bar and `market_data_ohlcv` holds none (23,171 sessions: 12,198 before 2016-01-04 in 12 names, 10,953 from 2016-01-04 in 59 names, 20 in CTVA's stale tail). If those sessions were derived, all 71 would clear the 0.999 line. Held-by: 68 `session_coverage` alone, LKQ and MPB with an unexplained_seam, CTVA with the lineage and recompute findings.

Example: CUBE has 94 canonical IBKR bars (2011-09-19..2012-02-01), then none until Alpaca from 2016-01-04, while raw holds IBKR smart_trades for 2012-02-02..2015-12-31 (985 sessions). The latest derived load (2026-10-29, d2-v4) records no refusal, so the cause is open. Filed as todo 566.

Names: ANGI APLD APTV ARKK ASTS AUGO BCML BCPC BELFA BMNR CBAN CMDB CNR CNXC COFS CPER CTVA CUBE CVI DBMF DKNG ELE EPSN FLGT FLNG FMAO FTI FUBO GATX HIMS HYMC IDR IPO JAAA JBTM JMSB KCE KMLM KSA KTOS LION LKQ LW LZM MAMA MGY MPB MTCH NESR NEXT NUVB OKLO OMF PMTS PR QXO RCAT RNG RSPC RSPR SAFE SCL SDRL SEZL SN UNL URNM VNT VRT WULF XTL.

### 2. Genuine holes: 39 names (no raw bar, no corroborated answer)

| Class | Sessions | Names | What it is |
|---|---|---|---|
| Tradier-only history | 9,704 | ARWR BTAL CC GPRE GWRE MUSA OC PPTA RSPG RSPH RSPM RSPT RSPU TIGO TMUS WBD WEAT XHS XSW (BZH 1 day) | The only request over the session was a Tradier one. Tradier rows are deleted (plan 191-20), so the history is gone and nothing replaced it. Needs an IBKR 1d fetch for 2006..2015, or an accepted gap. |
| Inside a successful IBKR window but outside its bar span | 8,136 | AGG LQD (2007-08-31..10-16, 32 each), CBC (2,799), SSP (1,881), PPTA (1,224), TIGO (752), DFTX (449), GYRE (372), TLN (263), CME (253), VICI (47), IYT UNG RSPD MVBF FRHC (a few days each), and the first day of ARWR CC GWRE OC | The window returned bars, but none of the vendor's bars lie on the far side of the session (a dormant or relisted ticker such as SSP, whose 10-year window returned 26 bars, or a head before IBKR's history starts). A head of this kind is not evidence of no trade (IBKR history starts at the last venue move), so it stays a hole by the existing design. |
| Stale tail after the last canonical bar | 65 | ACA 4, ACVA 8, BZH 7, CCO 10, MSGS 2, PSKY 17, WBD 17 | The vendors stopped serving these names in October 2026 and `listing_end_current` has no row for them. These are the freshness_1d holds (below). |

CBC is an outlier: 2,799 sessions inside IBKR windows that returned 1 or 2 bars each, a very thinly traded name. It is the one name where genuine no-trade days might be the true answer; the rule cannot tell, and a hold is the honest outcome.

## Other holds, classified (not fixed here)

- unexplained_seam, 25 names (21 with no other finding, EWZ and HWKN with a passing coverage, LKQ and MPB with the derivation gap): single-day jumps of 8 or more robust sigmas in recent sessions, no corporate action. On all 25 (name, day) jumps Alpaca and IBKR agree on the close to the cent and the volume is 2.8 to 29 times the preceding 30-day mean (FFIV 459.36 to 365.53, PNR 55.22 to 62.29, LPLA 317.56 to 269.19). They are earnings-season gaps and a few ETF moves, not data defects. The check judges only the latest sessions, so the holds age out; nothing in the data needs repair.
- freshness_1d, 6 names: ACA (last bar 2026-10-22), ACVA (10-15), BZH (10-19), PSKY (10-05) stopped being served in October with no recorded listing end (todo 519 mechanism: record the last session and the check passes); CTVA is the derivation-gap name below (canonical ends 2026-09-30, raw to 2026-10-28); QRVO has a recorded listing end (2026-10-02), 2,703 raw rows and no canonical row at all, so its `session_coverage=0` and freshness 6,984 are a derivation gap of the same kind as todo 566, with no bars to score.
- canonical_recompute 1,868, lineage_missing 1,848, policy_conformance 1,848: one name, CTVA. All 1,848 canonical bars are IBKR `named` for 2019-05-24..2026-09-30 under a D-191-Q interim policy row (ibkr primary, `three_way` class, IBKR close at 0.1795 of Alpaca after the Dow spin-off basis difference, 191-D191Q-ARBITRATION.md). The raw table was restated (191-09-SUMMARY.md: "CTVA 1,848 ... Canonical is behind raw there; the daily stage owes the re-derivation"). A basis hold, unchanged by this fix.

## Tests

`tests/unit/bars/test_integrity_checks.py` (pure rule and judge): a missing session inside a window with bars either side is answered; a window with none of the vendor's bars, another vendor's bars, or bars outside the window answers nothing; days before the first and after the last bar stay unanswered; a midnight window end is exclusive and a midday end takes its day; a session with a raw bar but no stored bar is a derivation gap, not an answer.

`tests/unit/services/test_bar_reconciliation_audit.py` (loaders on the fake connection, driven by the arguments the loader passes): a successful IBKR request answers the gap; Tradier, IBKR venue route, ADJUSTED_LAST and Alpaca IEX requests do not; failed, timeout, legacy_import and no_data outcomes do not; a window with no stored bar inside does not; an applied raw ibkr load answers its range with `requested_end` inclusive; refused, failed, tradier, derived and archive loads do not; the empty-history rule is unchanged.

## Reproduce

The recount ran the changed `_name_inputs_1d` and `answered_window_spans` over every name with a canonical 1d bar, against the live database, read-only. Judgement uses the audit's own session calendar from the first canonical bar to the last SPY session (2026-10-28).
