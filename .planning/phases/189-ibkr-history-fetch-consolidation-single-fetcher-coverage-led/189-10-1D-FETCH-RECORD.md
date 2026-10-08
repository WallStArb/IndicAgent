# 189-10 Task 1b: one-time IBKR 1d fetch record

Date: 2026-10-08 (UTC). Executor: Claude (Opus 5.5), under the owner's Task 1b go and the orchestrator decisions in the 2026-10-08 amendment block of 189-10-PLAN.md. This file is the marker 185-47 checks.

Code: `--no-derive` (test 292dc47ea, feature e037ca27e); gate amendment 9604dabe9. Every invocation ran the fetcher CLI directly (`--client-id 40 --no-derive`), under FetcherLock, with the timer and service left disabled.

## Preflight

| Item | Result |
|---|---|
| ib-gateway container | up 2 days; IBC "Login has completed" 2026-10-07 23:59:06 UTC (autorestart, no 2FA); 127.0.0.1:7497 listening; no 2FA or logout event since |
| API handshake | the fetcher's own connect succeeded on every run |
| FetcherLock | free (no `lock:` session in pg_stat_activity) before each run |
| backfill_feature_factory, intraday_chain, ibkr_history_fetcher | no process before each run |
| Tradier timer | disabled, inactive |
| Fetcher timer and service | disabled, inactive (unchanged) |
| D7 | inactive before the fetch; run by hand once after (below) |

## Name sets

| Set | Names |
|---|---|
| active | 1,529 |
| no SMART TRADES 1d observation (2026-10-08 before the fetch) | 492: 473 compute_1d, 19 outside |
| of the 492, never asked / asked, never answered | 475 / 17 (the 17 are all outside compute_1d) |
| outside compute_1d | 27 (19 without SMART, 8 with) |
| refresh set (compute_1d with SMART) | 1,029 |

`--dimension backfill --timeframes 1d` selected all 27 names outside compute_1d (dry run and live run).

## Runs

| Step | fetch_run_id | Window (UTC) | Wall | Items | ok | error | Requests (all routes / SMART) | no_data answers (all routes / SMART) | failed requests | Bars landed in D1 (SMART) |
|---|---|---|---|---|---|---|---|---|---|---|
| 1a: 473 compute_1d first fetch | d8ddd16d | 11:40:41 to 14:16:01 | 2 h 35 min | 473 | 468 | 5 | 1,992 / 1,132 | 1,001 / 169 | 19 (8 SMART, 11 ISLAND) | 70,192 |
| 1b: 27 outside compute_1d (`--dimension backfill`) | 7e226ee8 | 14:18:29 to 14:19:32 | 1 min | 27 | 27 | 0 | 39 / 35 | 5 / 1 | 0 | 1,469 |
| 2: refresh 1,029 compute_1d names | 790b2d1d | 14:19:50 to 15:18:38 | 59 min | 1,114 (1,029 + 85 escalations) | 1,112 | 2 | 1,167 / 1,151 | 18 / 8 | 0 | 429,829 |
| ISLAND 8, `--full-scan` | 0627573f | 15:24:54 to 15:25:16 | 22 s | 8 | 8 | 0 | 12 / 12 | 2 / 2 | 0 | 379 |

Item errors: CHRD, CLBK, ELE, NB (SMART requests timed out, 375 s each with retries); QRVO, PSKY, WBD (contract qualification failed: "No security definition has been found", no request made). The 1d limiter fired its pauses as designed. No IBKR answer said "pacing violation"; the 57 `ibkr.hist_pacing_error` log events are error 162 "query cancelled" after our own request timeout (provider classification), and the gateway never disconnected.

Escalations in step 2 (built path, todo 507): CTVA and ETHA `split_recorded` (corporate_action rows written by the overlap judge), 39 `restated_row`, 44 `ratio_outside_tolerance`. They are names late in the alphabet: the prior SMART answers of those dates were fetched before that session's close (for example XLB 2026-09-30 fetched 19:55 UTC, close 48.84, final 48.70), so the judge compared an intraday partial bar with the final bar. Not a real restatement; each re-fetch cost one request.

## Request rate (the SMART TRADES 1d fetcher figure 185-46 could not measure)

| Shape | Requests per hour | Latency SMART bars (mean / p50 / p90) |
|---|---|---|
| Update lane (refresh, short tail spans) | 1,200.8 all routes, 1,184.4 SMART: exactly the 1d limiter ceiling (200 per 600 s) | 0.29 s / 0.11 s / 0.31 s |
| First fetch (head windows, gaps and venue fallback) | 771 all routes, 438 SMART | 0.23 s / 0.04 s / 0.16 s |

The update lane is limiter-bound, not latency-bound: 1,529 names cost about 76 minutes a night at 1,200 per hour (185-46 estimated 90 at the serial bound). The first-fetch rate is lower because the head venue chain adds 4 or 5 requests per late-start name and 19 timed-out requests cost about 86 minutes.

## What the planner actually asks (finding for 185-47)

The 1d item plans only the dates D1 does not already answer on any route; `--full-scan` and the gap-fill lane plan the full window but still skip answered dates. So no name got a 20-year SMART request over its Tradier-covered span: IBKR answered the head before Tradier's first date, interior gaps and a 28-session tail (2026-09-11 to 2026-10-07). For the 473 first-fetch names the common Tradier and SMART sessions are about 20 (the tail through 2026-10-06), so under R2 (min_overlap 60) none of them can be class B: a disagreeing name lands in class C (few_common).

## d2-v2 gate and apply

Baseline before any fetch (all 1,529 names, logs/189-10_d2v2_before_1d.tsv): 0 changed, 0 removed; new bars only on the 27 names outside compute_1d.

| Step | Gate | Dry run | Applied |
|---|---|---|---|
| 1a, 473 names (logs/189-10_d2v2_after_1d.tsv) | strict | new 53,164 (IBKR heads 52,157, admitted interior 1,007), changed 0, removed 0, refused head 1,258, refused interior 56 dates, would_refuse 0: pass | 473 applied loads: new 53,164, changed 0, removed 0 |
| 2, 1,029 names (logs/189-10_d2v2_after_refresh.tsv, per-bar list logs/189-10_d2v2_refresh_changed_bars.tsv) | removed 0; changed 0 on Tradier-sourced bars; IBKR-sourced changes recorded in ohlcv_revision | new 2,170, changed 1,877 (all IBKR-sourced: ibkr_named 1,876, ibkr_fallback 1; Tradier-sourced 0), removed 0: pass | 1,028 names (CTVA held, below): new 2,165, changed 29, removed 0; 29 ohlcv_revision rows (ibkr_named 28 on 12 names, ibkr_fallback 1) |
| 1b, 27 names outside compute_1d | not applied (orchestrator decision) | current dry run: new 82,658, changed 0, removed 0 | none |

Changed bars applied in step 2 (name, date, stored source, what moved):

| Name | Dates | Source | Change |
|---|---|---|---|
| ASML | 2026-09-25, 09-28, 09-29, 09-30 | ibkr_named | volume +1 |
| COR | 2026-09-29 | ibkr_named | volume +1 |
| EMB | 2008-02-19 | ibkr_fallback | volume 2,200 to 2,400 |
| HPE | 2026-09-23, 09-24, 09-25, 09-28, 09-30 | ibkr_named | volume +-1 to 3 |
| HPQ | 2026-09-23, 09-24, 09-28, 09-29 | ibkr_named | volume +-1 |
| IP | 2026-09-24, 09-29 | ibkr_named | volume +1 |
| NOC | 2026-09-23, 09-28 | ibkr_named | volume +-1 |
| POST | 2026-09-25 | ibkr_named | volume +1 |
| RCAT | 2026-09-25, 09-28, 09-29 | ibkr_named | volume +-1 |
| RSG | 2026-09-25, 09-29 | ibkr_named | volume +-1 |
| TMUS | 2026-09-29 | ibkr_named | volume -2 |
| XAR | 2026-09-24, 09-25 | ibkr_named | volume +-1 |
| XLY | 2026-09-30 | ibkr_named | close 108.95 to 108.84, volume 3,971,307 to 4,338,945 (the stored bar was an intraday partial) |

CTVA held (not applied; decision needed before 185-47). The step 2 overlap judge recorded a `split` for CTVA (corporate_action 90c2dc47, factor 5.5714, effective 2026-09-30, inferred_by nightly_overlap). The event is the Corteva separation (a spin-off, first post-event session 2026-10-01), not a split: IBKR restated every pre-event SMART bar by 5.5714 (2026-09-30 close 77.65 becomes 13.94) and scaled volume up by the same factor (1,852,362 becomes 10,319,565), as if the share count had changed. Tradier's adjusted 2026-09-30 close is 11.65 (a different factor, 6.66). Applying d2-v2 would rewrite 1,848 canonical ibkr_named bars (2019-05-24 onward) to a spin-adjusted price scale with split-scaled volumes. Held because it passes the gate as written but records a spin-off as a split; one command applies it if the owner accepts (`services/bar_derivation.py --stage daily --symbols CTVA --apply`). Consequence today: D7 canonical_recompute fails on CTVA (1,853) and freshness_1d fails (5 sessions).

ETHA: the corporate_action table now holds two rows for one reverse split (1:3): effective 2026-10-02 (tradier_refetch) and 2026-09-30 (nightly_overlap, this run). No canonical ETHA bar changed (Tradier primary), but the duplicate with two effective dates needs a decision before 185-47 reclassifies ETHA.

## Held names outside compute_1d (open question for the owner)

The 27 names (APG, AU, BJ, BORR, CANE, CORZ, CRCL, EIS, ELAN, EVER, FIGR, H, IOT, KNSL, MNA, NIQ, NU, OWL, PINS, PNFP, REMX, RPRX, SHEN, SNOW, SUNB, WMS, ZIP) hold no canonical 1d bar. Their D1 now holds Tradier history plus 1,469 new SMART bars. A d2-v2 apply would write 82,658 canonical bars (IBKR heads 1,243, admitted interior 509, the rest their Tradier history), changed 0, removed 0. Question: should held names (not compute_1d) carry canonical 1d at all? D7 judges only compute_1d (todo 502), so nothing would check those bars today.

## ISLAND 8 (todo 511, measured answers, no exclusions)

The new fetcher made no ISLAND request: the planner skips dates already answered, the head windows hold stored answers, and the switch is off. SMART answered the tail for all 8, CPS and SD each got one SMART no_data on the session before their SMART first bar (2013-10-16 and 2007-11-05), and USL got two 2008 interior windows (79 and 76 bars).

| Name | SMART first | SMART dates | Tradier first | Canonical first | SMART zero-volume dates | Mean SMART volume since 2026-09-11 | ISLAND asks (all time) / outcome |
|---|---|---|---|---|---|---|---|
| CPS | 2013-10-17 | 3,262 | 2011-05-23 | 2011-05-23 | 4 | 155,157 | 4 / failed |
| DAL | 2007-04-26 | 4,873 | 2007-05-03 | 2007-04-26 | 0 | 3,539,658 | 7 / failed |
| PARR | 2014-07-22 | 3,072 | 2014-05-23 | 2014-05-23 | 0 | 455,421 | 4 / failed |
| QXO | 2017-04-19 | 559 | 2012-03-15 | 2012-03-15 | 75 | 18,031,254 | 1 / failed |
| SD | 2007-11-06 | 1,170 | 2011-05-23 | 2007-11-06 | 0 | 178,368 | 1 / failed |
| SGHC | 2020-11-23 | 1,474 | 2022-01-28 | 2020-11-23 | 0 | 1,948,308 | 4 / failed |
| USL | 2007-12-06 | 4,729 | 2007-12-06 | 2007-12-06 | 7 | 5,310 | 4 / failed |
| UUUU | 2013-12-04 | 3,229 | 2014-01-15 | 2013-12-04 | 0 | 5,594,531 | 4 / failed |

Under the Tradier default, CPS, PARR and QXO are canonical from Tradier's earlier start, so their failed SMART head does not leave a canonical hole; DAL, SD, SGHC and UUUU start canonical at SMART's first bar (IBKR head earlier than Tradier's). A re-ask of ISLAND needs the switch or an explicit venue request; neither was run.

## State after

- Ledger: `--rebuild-coverage` (no IBKR) rebuilt 3,798 rows. 1,497 of 1,502 compute_1d names are current to 2026-10-07. Not current: CTVA (held, 2026-09-30), MOD (2026-10-06; d2-v2 refused the 2026-10-07 IBKR fallback bar by the interior basis rule), PSKY and WBD (2026-10-05, qualify failed), QRVO (2026-10-02, qualify failed). The 27 names outside compute_1d have no canonical 1d by decision.
- 471 of the 473 first-fetch names are now current through 2026-10-07 by IBKR fallback bars under the Tradier default policy (D is 2026-10-07): 185-47's R6 C1 ("new equal to the SMART dates on or after D" for class A) will read 0 new for those dates, since they are already canonical as ibkr_fallback.
- D7 by hand (systemd start 2026-10-08 15:27 UTC, Result success), failing names, timer run 06:05 UTC against this run:

| Check | 06:05 | 15:32 | Note |
|---|---|---|---|
| freshness_1d | 74 | 2 | QRVO (3 sessions), CTVA (5) |
| session_coverage | 326 | 191 | 137 fail to pass; APPS and OLED pass to fail (0.9997 to 0.965 and 0.9999 to 0.962), not investigated |
| coverage_cache | 235 | 0 | |
| digest_fresh | 120 | 0 | |
| canonical_recompute | 0 | 1 | CTVA (held apply) |
| vendor_basis_run | 31 | 35 | new: ELE, LION, NEXN, W (the last three class B, 28 new IBKR tail bars each) |
| unexplained_seam | 6 | 6 | |
| grid_parity, slot_coverage | 131, 240 | 131, 240 | 5m, untouched |
| policy_conformance, lineage_missing, refused_head_1d, stray_vendor_rows, report_age | 0 | 0 | |

## For 185-47

1. Decide CTVA (apply the spin-adjusted rewrite or not) and the duplicate ETHA corporate action before 185-47 runs; C3 requires canonical_recompute 0.
2. Rerun `--classify`: the 473 first-fetch names have about 20 common sessions each, so B is impossible for them under min_overlap 60.
3. C1 for class A names: the dates on or after D are already canonical as ibkr_fallback; the swap changes their source label, not their values.
4. Intraday partial 1d answers exist in D1 for fetches made before a session's close (XLB 2026-09-30 19:55 UTC). d2-v2 takes the latest fetch so the final answer wins, but the overlap judge escalates on them; worth a planner rule that never asks or stores an in-progress session.
5. QRVO, PSKY, WBD fail contract qualification; CHRD, CLBK, ELE, NB timed out on part of their windows.
