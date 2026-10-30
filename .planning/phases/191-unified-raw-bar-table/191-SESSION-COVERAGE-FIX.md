# 1d session coverage fix

Author: data lane executor, 2026-10-29; corrected the same day after an independent review (section "Correction after review"). Informed by: 191-SLOT-COVERAGE-FIX.md (todo 565, the 5m analogue), 191-20-D7-HOLDS.tsv, live read-only `ohlcv_request`, `ohlcv_load`, `ohlcv_raw` and `market_data_ohlcv` reads.

## Problem

`session_coverage` (threshold 0.999, APR `threshold.bar_integrity.session_coverage_min_1d`) counted a session answered only when the name had a canonical bar or an `ohlcv_empty_history` span (`_EMPTY_SESSIONS_SQL`). A session on which a vendor answered successfully and served no bar (no trade that day) counted as missing. ABCB: 37 sessions between 1999-10-29 and 2002-03-22, all inside successful IBKR requests and loads, coverage 0.9944.

## Semantic

A 1d session is answered when any of these holds (the first two are unchanged):

1. a canonical bar sits on it;
2. an `ohlcv_empty_history` span (IBKR confirmed empty history) covers it;
3. it lies inside the corroborated span of a successful canonical-vendor answer, the vendor served no raw bar on it, no answered request returned it as a partial bar, and it passes the no-trade test (the run of consecutive sessions with no stored bar containing it is short and the neighbouring bars are thin; see "Correction after review"). The first version of this rule had no no-trade test and was wrong.

An answer is either a request or a load:

| Evidence | Rows counted | Rows never counted |
|---|---|---|
| `ohlcv_request` | (ibkr, SMART, TRADES) and (alpaca, SIP, 1Day), outcome `bars`, caller not `test-%` | tradier (retired, lineage only); IBKR venue routes (NYSE, ARCA, AMEX, ISLAND, BATS); ADJUSTED_LAST; alpaca IEX; outcomes `no_data`, `failed`, `timeout`, `legacy_import` |
| `ohlcv_load` | source ibkr or alpaca, outcome `applied`, destination `raw` | `derived` loads (the daily stage's own output), tradier loads, refused, failed, loaded, short_history |

Constants: `DAILY_ANSWER_REQUESTS`, `DAILY_ANSWER_OUTCOME`, `DAILY_ANSWER_LOAD_SOURCES`, `DAILY_ANSWER_LOAD_DESTINATIONS` in `src/intelligence/bars/gap_plan.py`; the load outcome reuses `LOAD_COVERAGE_OUTCOMES`. Loaders: `_ANSWERED_1D_REQUESTS_SQL` and `_ANSWERED_1D_LOADS_SQL` (one read each for the whole corpus, in `_verdict_report_1d`). Pure rules: `answered_window_spans` and `no_trade_sessions` in `integrity_checks.py`. Three APR keys (migration 543) feed the no-trade test.

Corroboration (the guard against a lost insert): a window answers only the days from the vendor's first raw bar inside it to its last. A window with none of the vendor's bars answers nothing, and the days before the first or after the last bar stay unanswered (a pre-listing head, a stale tail, IBKR history that starts later).

Served sessions: a session on which the name has a raw observation but no canonical bar is never answered by a window. The vendor served a bar there; the canonical series lacking it is a derivation gap (below), not a no-trade answer. Without this guard 59 more names passed that should not (156 instead of 97 below).

## Facts established from the live data

- 1d request outcomes with `bars`: ibkr SMART TRADES 23,158; alpaca SIP 1Day 7,631; tradier 6,506 (excluded). IBKR venue routes and ADJUSTED_LAST also carry `bars` rows and are excluded.
- Window end is exclusive for IBKR. Of 147 IBKR 1d requests whose raw rows are linked by `request_id`, none holds a bar on or after its `window_end` date (ABCB: window_end 2002-03-23, last bar before it 2002-03-21, the unanswered 2002-03-22 is inside). A midnight end excludes its own date; an Alpaca nightly end (17:30 UTC) takes its day in. This is the end-exclusive rule the other 1d readers use (`timestamp < window_end`); an inclusive end is refuted for IBKR requests.
- IBKR `window_start` is unreliable on the low side: 22 of the 147 have bars before it (ABCB's first request starts 1999-12-20, its bars start 1999-10-25). Alpaca requests carry no linked raw rows.
- The applied raw loads give the missing low side. On all 19,661 applied ibkr (12,031) and alpaca (7,630) 1d raw loads, `requested_start` equals `first_bar` and `requested_end` equals `last_bar` (inclusive), so a load range is the span of the bars the vendor returned. Requests and loads go through the same corroboration, so a load adds nothing a vendor bar does not support.
- ohlcv_empty_history (the existing rule) is unchanged and its SQL still reads no request table.

## First recount (commit 2bc1e2e9a, superseded by the corrected recount below)

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

## Correction after review

An independent review of 2bc1e2e9a (verdict fail) found the rule too loose. Inside a corroborated window it counted every no-bar session between the vendor's first and last raw bar as an answered no-trade day, with no bound on the run and no check that the name could have gone untraded. On the 97 names it newly passed, 7,261 sessions were answered this way, all before 2013 where IBKR is the only vendor, so nothing could contradict them. Counterexamples: LVS 2004-12-16..2005-01-14 (21 sessions, the day after its IPO), AIZ 2004-02-06..2004-03-08 (21, nearby volume 14M to 27M), RDN 2008-07-14..18, EWJ 2005-12-02..07, LGND 2005-09-07..2006-06-14 (192 consecutive), PFBC (831 sessions over 2001-2011). A multi-week hole in IBKR history looks exactly like a run of no-trade days inside a window.

The 1d rule also ignored `partial_bars` on Alpaca SIP 1Day requests (3,049 requests carry them; the 5m rule already excludes those slots).

### Corrected rule

A no-bar session inside a corroborated window counts as answered only when all of these hold:

1. the vendor served no raw bar on it (unchanged: a served session with no canonical bar is a derivation gap);
2. no answered request returned a partial bar for that date (`ohlcv_request.partial_bars`, read by `_ANSWERED_1D_REQUESTS_SQL`, parsed by `_partial_bar_dates`);
3. the run of consecutive judged sessions with no stored bar that contains it is at most `threshold.bar_integrity.no_trade_run_max_sessions` long;
4. the median volume of the `threshold.bar_integrity.no_trade_neighbor_window_sessions` nearest stored bars on each side of the run is at most `threshold.bar_integrity.no_trade_neighbor_median_volume_max_shares`. A run with no neighbouring volume is not answered.

Everything else is a hole and keeps the name held. The rule is the pure function `no_trade_sessions`; the judge passes the three APR values in (`IntegrityThresholds`), and `_IntegrityParams` reads them with defaults equal to the seeds. Migration 543 seeds 3, 5 and 50,000 (provenance `[rca_analysis]`). A test parses the migration and compares it with the audit defaults.

### Calibration

The brief asked for the thresholds to come from true no-trade days in the Alpaca SIP era (from 2016-01-04): sessions inside an Alpaca SIP 1Day answered window, with stored bars on both sides, with no Alpaca bar. Read-only on the live data, 1,501 names with a stored 1d bar, sessions to 2026-10-28:

- 17,728 sessions from 2016-01-04 have no stored bar. 3,833 lie inside an Alpaca answered span (63 names); every one of them has a raw bar from a canonical vendor (2 of them also a partial-bar request), so they are derivation gaps. None is a session the consolidated feed answered as "no trade". The other 13,895 lie outside any Alpaca span.
- So the evidence set is empty: across about 3.7 million stored SIP-era name-sessions, the consolidated feed produced no observed no-trade day inside its own corroborated windows. A no-trade day is rarer than the 1,501-name universe can measure, and no quantile of a distribution of zero events exists.

The thresholds therefore come from the nearest observable thing, near-no-trade bars: SIP-era stored bars with volume at most 100 shares (2,035 bars, 0.055 percent of 3,699,705; 649 at most 10 shares). The first question is how thin the surroundings of such a bar are.

| Measure (SIP era) | n | p50 | p90 | p95 | p99 | p99.9 |
|---|---|---|---|---|---|---|
| Median volume of the 5 bars either side of a bar with volume at most 100 (shares) | 2,035 | 400 | 3,077 | 5,846 | 45,907 | 945,724 |
| Same, bars with volume at most 10 | 649 | 36 | 652 | 3,304 | 58,407 | 897,811 |
| Same, bars with volume at most 1,000 | 8,992 | 2,723 | 8,637 | 15,853 | 101,531 | 999,500 |
| Length of a run of consecutive bars with volume at most 100 (sessions) | 1,147 runs | 1 | 3 | 6 | 22 | 54.7 |
| Same, volume at most 1,000 | 4,790 runs | 1 | 4 | 5 | 12 | 104 |

Choice: `no_trade_neighbor_window_sessions` 5 (one trading week, the window of the table), `no_trade_neighbor_median_volume_max_shares` 50,000 (the 99th percentile, 45,907, of the neighbouring median around bars at most 100 shares, rounded up) and `no_trade_run_max_sessions` 3 (the 90th percentile of the run length at most 100 shares; the 95th is 6). The run cap is the tighter choice because a longer run is also the shape of an IBKR history hole. Both numbers are proxies, stated as such, and the keys are APR values for the data lane to move.

### Sensitivity on the IBKR era

Read-only over the 228 held names that carry a stored bar. "Held pass" counts names passing `session_coverage` (21 already pass with no window at all and are held for other reasons, so subtract 21 for the names the window rule frees). "Answered" counts sessions the rule answers over all 1,501 names; no name's coverage falls below its no-window value at any setting.

| run max | volume max | held pass | answered, all names |
|---|---|---|---|
| 1 | 50,000 | 44 | 4,479 |
| 2 | 50,000 | 61 | 6,838 |
| 3 | 10,000 | 54 | 7,500 |
| 3 | 50,000 (seed) | 66 | 8,245 |
| 3 | 100,000 | 69 | 8,324 |
| 3 | 1,000,000 | 71 | 8,533 |
| 5 | 50,000 | 77 | 9,937 |
| 10 | 50,000 | 83 | 11,585 |
| 10 | 100,000 | 90 | 11,672 |
| 20 | 100,000 | 96 | 12,387 |
| (2bc1e2e9a, no test) | none | 118 | not counted |

The volume cap moves the count little above 50,000; the run cap is the lever. Raising it admits the genuine thin small caps (below) and the multi-week history holes together, and the rule cannot tell them apart.

### Corrected recount (read-only: the changed loaders and judge on the live data, no service, no write)

| | before 2bc1e2e9a | 2bc1e2e9a | corrected |
|---|---|---|---|
| names passing `session_coverage` (of 207 scored held names) | 0 | 97 | 45 |
| held names with no remaining finding (of 229) | 0 | 95 | 44 |
| sessions answered on those 97 names | 0 | 7,261 | 4,472 |

The 52 names that fall back from the 97 lose 2,742 sessions: 2,261 in runs longer than 3, 102 in thin-enough runs with neighbouring median volume above 50,000, 379 in runs that are both. By dominant cause: 30 names long run, 17 long and liquid, 5 liquid. The 1,273 names D7 passes: 1,273 of 1,273 still pass, and no name's coverage fell below its no-window value.

The named counterexamples, sessions answered before and after, and the verdict now: LVS 21 to 0 (coverage 0.99600, held), AIZ 21 to 0 (0.99615, held), RDN 5 to 0 (0.99853, held), EWJ 4 to 0 (0.99840, held), LGND 192 to 0 (0.97159, held), PFBC 831 to 7 (0.86888, held). All six are held again. EWZ, which also carried a seam hold, falls back as well.

Spot check: 8,138 sessions remain answered on 108 held names; the neighbouring median volume of those runs has median 1,450 and maximum 48,515 shares. A random sample of 15 (name, session, run length, neighbouring median volume, volume the day before and after): APLD 2011-04-21, 1, 199, 833 and 2,000; VSEC 2000-10-05, 2, 5,000, 4,000 and 4,000; RCAT 2011-08-25, 3, 0, 0 and 0; LCUT 1999-05-03, 1, 8,550, 19,900 and 11,000; CPER 2013-01-14, 2, 1,000, 1,100 and 900; WULF 2002-06-14, 1, 1,125, 2,850 and 150; VSEC 2002-09-30, 1, 4,000, 1,200 and 800; STRL 2000-05-02, 1, 6,800, 14,000 and 1,000; AUGO 2013-03-05, 1, 450, 1,800 and 690; CBAN 2011-11-08, 1, 1,250, 600 and 12,500; CBAN 2004-01-22, 1, 250, 200 and 100; VSEC 2002-06-06, 1, 4,200, 3,600 and 3,200; BCML 2013-05-16, 2, 1,100, 300 and 7,800; CBAN 2005-02-10, 1, 1,000, 1,300 and 2,600; WULF 2012-04-18, 2, 1,400, 1,300 and 2,500. All 15 are single sessions or runs of two or three among neighbours of a few hundred to a few thousand shares a day, plausible no-trade days. RCAT is the odd one: its IBKR bars carry volume 0 around prices near 9,000 (a reverse-split-adjusted history where share counts round to zero), so the volume guard sees a thin name by construction.

### Where the residual goes

162 of the 207 scored names still fail `session_coverage` (110 before the correction). If the derivation gaps of todo 566 were closed, 55 of them would clear; 107 would still fail. Of the 71 derivation-gap names listed above, 55 clear after a re-derive and 16 do not (APLD AUGO BCML BELFA BMNR CBAN COFS CPER FUBO IDR KCE MPB RCAT SAFE WULF XTL). Those 16 are mostly small caps with a few hundred shares a day and runs of 5 to 23 no-bar sessions that the cap of 3 refuses to call no-trade days. Whether such runs are quiet spells or IBKR holes cannot be decided from this data; they stay held until a vendor answer outside IBKR (Alpaca 5m, a venue bar) covers them or the owner moves the cap.

### Tests added

`tests/unit/bars/test_integrity_checks.py`: a thin short run is answered; a run longer than the cap is not (and is at the cap plus one); a liquid single missing session is not (the maximum is inclusive); the neighbour volume is a median over the nearest bars each side; a run with no neighbour volume is not answered; partial, served and out-of-window sessions are not answered; the judge leaves a liquid, partial or long hole in the coverage. `tests/unit/services/test_bar_reconciliation_audit.py`: a request that served the session as a partial bar does not answer it (text and list forms of the JSON); `_partial_bar_dates` parses text, lists and null; `_IntegrityParams.from_apr` reads the three keys. `tests/unit/test_bar_integrity_no_trade_apr_migration_contract.py`: migration 543 shape, keys, provenance, and that the audit defaults equal the seeds.
