---
phase: 189-ibkr-history-fetch-consolidation-single-fetcher-coverage-led
plan: 10
scope: Task 2 only (20-name 5m pilot); Task 3 not run
status: pilot run 2026-10-09 (4 fetch passes, 1,553 requests); criterion 4 of 9 pass; C4 launch gate FAILED
---

# Phase 189 plan 10, Task 2: 20-name 5m pilot

## Pre-registration (written 2026-10-09 before the first pilot request; the commit time is the registration time)

Everything in this section was fixed before any IBKR request of the pilot and before any 5m bar,
1d bar or return of a pilot name was read. Later sections add results; this section is not edited
after its commit.

### Name selection rule

Read only `instruments` (is_active, compute_eligible_1d, created_at), the `ohlcv_coverage` 5m row
(earliest_timestamp null or not) and the existence of an `ohlcv_intraday_raw_archive` 15m or 1h row.
No history, latency or return was read.

- Wave 1: active compute_eligible_1d names created on 2026-09-26 (config/universe/README.md batches
  1, 1b and 2). Wave 2: created on 2026-10-03 (batch 3, "wave 2").
- Drain population: names with no 5m coverage (earliest_timestamp null). Counts: wave 1 652 (431
  with vendor archive rows, 221 without), wave 2 570 (none with archive rows). The other 40 drain
  names (created 2026-09-16) are outside the waves.
- Strata and counts, fixed: wave 1 with archive 7, wave 1 without archive 3 (proportional to 431:221,
  rounded; guarantees at least 5 parity-testable names), wave 2 10.
- Within a stratum: sort by symbol (C collation), n names, take the 0-indexed positions
  floor((2i + 1) n / (2k)) for i = 0..k-1 (k evenly spaced midpoints).

| Stratum | n | k | Names |
|---|---|---|---|
| wave 1, archive rows | 431 | 7 | APH, CSCO, KEYS, MRVL, RLAY, TER, WEAT |
| wave 1, no archive rows | 221 | 3 | CEG, EWL, NTRS |
| wave 2 | 570 | 10 | ANF, CACI, DBMF, FNB, IDA, MDGL, OII, RLI, TAP, VSAT |

Tail-update case (plan text: "re-fetch the tail of 2 names that already hold 5m, e.g. SPY and
AAPL"): SPY and AAPL, added to the 20 as the plan's example names. Both are in the update lane in
the fetcher's dry run (`ok` last fetch, 5m through 2026-10-05 and 2026-09-30), so their item re-asks
the 3-day overlap (infra.backfill.update_overlap_days_5m) plus the missing tail in one request.

Why the tail names are not wave names: all 7 wave 1 names holding 5m (A, AAP, ABBV, ACRS, ACVA,
ADBE, ADP) have no recorded fetch by the new fetcher, so the queue puts them in the backfill lane
(full depth, stored slots skipped) and none would exercise the overlap path. A first draft of this
rule took 2 of those 7 (AAP, ADBE) inside the 20; the fetcher dry run (queue read only, no bar
read) showed both in the backfill lane, and the rule was replaced by the one above before this
commit. So the pilot names 22 symbols: 20 drain names and 2 tail names.

Fetcher dry run of the 22 (2026-10-09 about 02:40 UTC, queue read only,
logs/189-10_task2_pilot_dryrun.tsv): 22 series, all 5m; lanes backfill 16, gap_fill 4 (CACI, TER,
VSAT, RLAY; both lanes plan the full depth for a name with no 5m), update 2 (SPY, AAPL).

### Run plan

- Preflight (all must hold, else stop): ib-gateway up with a completed IBC login after the last
  nightly restart; FetcherLock free (no advisory lock); no process matching
  backfill_feature_factory, intraday_chain, ibkr_history_fetcher, bar_derivation; fetcher timer
  and service disabled and inactive; no Tradier unit; CTVA row in bar_hold_current; D7 not running.
- Command, repeated until no pilot series plans another request:
  `.venv/bin/python scripts/infrastructure/backfill/ibkr_history_fetcher.py --symbols <22>
  --dimension compute_1d --timeframes 5m --client-id 40 --no-derive`, backgrounded, log under
  logs/. No 1d item exists in this scope, so no daily stage runs; the fetcher's run-end grid stage
  (`bar_derivation.py --stage grid --changed-only --apply`) derives 15m and 1h from the new 5m.
  Limits unchanged (5m limiter 58 per 600 s, inter_item_pause 2.0 s, 150-day chunks).
- Before the first run: a grid dry run `--changed-only` over all names records which names outside
  the pilot the run-end grid stage would also derive (the stage takes no symbol list).
- After the last run: `bar_derivation.py --stage grid --symbols <22>` dry run (idempotence), D7 by
  hand (`systemctl start indicagent-bar-reconciliation-audit.service`), the checks below.
- Stop on a pacing violation answer (IBKR error 162 with pacing text that is not our own timeout
  cancel) or a gateway disconnect; record it; do not loosen any limit.

### Pass criterion (all lines must pass; plan 189-10 Task 2 text)

| # | Criterion | Measured by |
|---|---|---|
| C1 | No item error outside a recorded gateway outage | run summaries (n_error), ohlcv_request outcomes timeout/failed with the item's final status |
| C2 | 0 revision-ratio refusals on the 22 | `ohlcv_load` source ibkr, timeframe 5m, outcome refused, pilot window: 0 |
| C3 | Tail update correct on SPY and AAPL: the overlap was re-asked, restated rows written and each recorded in `ohlcv_revision` (none refused) | the tail request windows cover the 3 stored days; n_changed of their 5m loads equals their new ohlcv_revision rows; C2 |
| C4 | Extrapolated full drain duration D_proj at most 18 days | formula F3 below |
| C5 | Grid stage completed for all 22: an applied 15m and 1h derived load for each name after its last 5m write, stage exit code 0 | `ohlcv_load` source derived; run summaries stage codes |
| C6 | Derived 15m/1h correct: (a) a grid dry run over the 22 after the last apply reports 0 new, 0 changed, 0 removed; (b) D7 digest_fresh passes on 5m, 15m and 1h for each of the 22; (c) an independent SQL re-aggregation of the stored tradeable 5m (15-minute buckets on the clock quarter, 1-hour buckets offset 30 minutes, i.e. session anchored at 09:30 ET) equals every stored derived 15m and 1h bar that carries no partial or constituent flag, on open, high, low, close and volume, for all 22 | three checks |
| C7 | D7 grid_parity 15m mismatches 0 on every pilot name holding archive rows (the 7 wave 1 archive names, SPY, AAPL) | D7 verdict rows; mismatches also split into price and volume-only as a diagnostic, which does not change the verdict |
| C8 | D7 slot_coverage at or above threshold.bar_integrity.slot_coverage_min_intraday (0.995) per name, or every year below it explained by an ohlcv_empty_history span or the head before the name's first IBKR 5m bar (late listing) | D7 verdicts plus the per-year shortfall |
| C9 | D7 stray_vendor_rows 0 on the 22 (15m and 1h) | D7 verdicts |

Recorded, not pass/fail: requests, wall time, requests per hour, mean, median and p90 request
latency, rows per name, no_data answers, revision rows, grid batch outcomes, vendor rows moved to
the archive, storage added (`hypertable_size('market_data_ohlcv')` and the archive before and after).

### Extrapolation formulas (written before any number is read)

Inputs measured by the pilot (fetch runs of the pilot, caller ibkr-history-fetcher, timeframe 5m):

- n_req: ohlcv_request rows, all routes and outcomes. Latency of a request: answered_at minus
  requested_at.
- H_loop: sum over the pilot runs of (last answered_at minus first requested_at) in hours: the
  stream time of the fetch loop, excluding startup and the run-end grid stage.
- r_d = n_req / H_loop: drain requests per stream hour (the 2 tail requests are inside; their
  effect is under 0.3 percent).
- R_W1, R_W2: mean requests per name over the 10 wave 1 and the 10 wave 2 drain names, counted to
  completion (a name is complete when its series plans no further request).
- T_grid: median minutes of the run-end grid stage per pilot run.
- t_u: median latency of the tail requests (SPY, AAPL; 2 requests, a small sample, stated as such).
  u: mean requests per tail name.

Fixed inputs (not from this pilot): B = 240 min (infra.backfill.run_budget_minutes); g = 15 min
(timer OnUnitInactiveSec); G = 1 h a day (gateway restart window 23:30 to 00:30 UTC); p = 2.0 s
(infra.ibkr.inter_item_pause_s); L5 = 3600 x 58 / 600 = 348 requests an hour (5m limiter, APR
unchanged); S_1d = 1,529 / 1,200.8 h = 1.273 h (the 1d update lane measured by Task 1b,
189-10-1D-FETCH-RECORD.md); 5 of 7 calendar days carry a nightly update (weekdays with a session).

- F1, requests per drain name for the 1,262: R_hat = (692 x R_W1 + 570 x R_W2) / 1,262 (the 40
  names created 2026-09-16 are weighted with wave 1, the older onboarding era). Q = 1,262 x R_hat.
  Rows and storage scale the same way: rows_hat from the per-wave mean rows per name; storage =
  measured bytes added per row added x 1,262 x rows_hat.
- F2, nightly 5m update cost for N names holding 5m: r_u = min(L5, 3600 / (t_u + p)) requests an
  hour; U(N) = 60 x N x u / r_u minutes. Reported at N = 242 (today's 5m holders) and N = 1,502.
- F3, drain duration: available drain hours a calendar day
  H_bar = 24 x B / (B + T_grid + g) - G - (5/7) x (S_1d + U(N_bar) / 60), with N_bar = (242 + 1,502) / 2
  = 872 (5m holders grow linearly over the drain). D_proj = Q / (r_d x H_bar) days. Sensitivity
  line (not the criterion): the same with a further (5/7) x 64 min a day for the 5m gap-fill lane
  (185-46's "at least 63.9 min" figure; the pilot cannot measure that lane).
- Comparison lines: the design's floor (10.6 days) and expectation (12 to 18 days), 185-46's
  restated 12.7 and 14.4 to 21.6 days, the design's storage (at most 17 GB 5m, 7 GB derived).

### Bounds (owner instruction 2026-10-08: the 120-minute daily-lane bound is not loosened; the 5m drain gets its own lane and bound)

- Daily lane, R4 as pre-registered in docs/research/1d-primary-swap-evidence.md: the nightly
  update lane (1d plus 5m, one short request a name) at most 120 minutes. Judged unchanged with
  S_1d and U(N) at N = 242 and N = 1,502, and reported pass or fail as it falls.
- 5m drain lane: C4 (D_proj at most 18 days) gates the launch. For the drain itself (judged by
  189-11 when it completes): the drain's calendar duration from the timer launch to the last of the
  1,262 names complete is at most B_drain = 1.25 x D_proj days, the 1.25 covering gateway outages
  and restarts the pilot cannot see.
- Nightly 5m update lane: feasibility bound, the 5m update for all 1,502 names finishes before the
  next session's open after the daily lane: U(1,502) at most 990 - 120 = 870 minutes (16:00 ET close
  to 09:30 ET open is 17.5 h, minus the 1 h gateway restart window, minus the daily lane's 120).
  Monitoring bound for Task 3 and 189-11: an observed nightly 5m update slice for N names at most
  1.25 x U(N).
- Todo 505 resolves here only if U(1,502) fits R4 with S_1d, that is U(1,502) at most 120 - 76.4
  minutes; otherwise 505 stays open with the pilot's numbers, since measuring a ceiling above the
  limiter needs the rate probe, which this task does not run (limits are not loosened here).

## Results (measured 2026-10-09; the pre-registration above is unchanged)

Scoring session note: the session that launched the pilot died with an SSH drop 10 minutes into run 4.
The run 4 fetcher process survived orphaned and completed cleanly; a successor session re-derived every
number below from ohlcv_request, ohlcv_load, ohlcv_revision, integrity_monitor and the logs. Nothing was
taken from the dead session's memory.

### Runs

| run | fetch_run_id | items | ok | no_data | error | bars returned | lanes | budget used out | gateway lost | sla breached | requests | stream h |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | afb85c58 | 10 | 8 | 0 | 2 | 4,528,883 | backfill 7, gap_fill 1, update 2 | yes | no | 2 | 392 | 4.468 |
| 2 | f6725b27 | 8 | 8 | 0 | 0 | 4,525,675 | backfill 6, gap_fill 2 | yes | no | 0 | 392 | 4.400 |
| 3 | f1399695 | 22 | 9 | 0 | 13 | 1,811,930 | backfill 5, gap_fill 4, update 13 | no | no | 0 | 270 | 2.112 |
| 4 | 64a17037 | 22 | 22 | 0 | 0 | 81,497 | backfill 13, gap_fill 4, update 5 | no | no | 0 | 499 | 1.356 |

Totals: 1,553 requests, 10,947,985 bars returned, 7,540,086 5m rows stored for the 22 names
(RTH-only persist; returned bars include extended hours, dropped at the session filter, ANF check:
392,695 RTH vs 12 extended rows stored). Derived adds 3,152,490 15m/1h rows. All 22 names hold 5m from
their first IBKR bar through 2026-10-09 14:10 UTC, gap_days 0, staleness 0, no series due (dry run
after run 4). no_data answers: 0.

Request latency, all 1,553: mean 24.7 s, median 27.5 s, p90 47.4 s. Depth chunks (150 days) average
40 s; update and gap answers median 0.1 s. Run-end grid stages: 347, 351, 363, 376 s (median 357 s).

### Criterion verdicts

| # | verdict | evidence |
|---|---|---|
| C1 | FAIL as written, then fixed | 15 item errors, none from a gateway outage (gateway_lost null in all runs). Root cause one bug: the update lane's `_stored_closes` read passed the coverage ledger's DESTINATION_GRID ("grid") as a `_STORED_TABLES` key, `KeyError('grid')` on every update-lane item with stored rows (SPY and AAPL in run 1, the same 13 items in run 3; both items made zero requests before failing). Fail-loud, no bad data written. Failing test 03f6c411b + fix efa1efb72 committed 10:10 ET; run 4 launched 23 s later: 22/22 ok, 0 errors. Final state satisfies C1's intent; the pre-registered line did not hold over the pilot's four runs. |
| C2 | PASS | ohlcv_load, source ibkr, timeframe 5m, pilot window: outcome refused = 0 (1,228 applied). |
| C3 | PASS | SPY and AAPL: overlap re-asked inside full-depth re-fetches; every changed row recorded: AAPL n_changed 41 = 41 ohlcv_revision rows (window 2026-03-06..2026-10-08), SPY 16 = 16 (2025-11-24..2026-07-01); 0 refusals. New tail bars: AAPL 479, SPY 243, through 2026-10-09. Note the restatements were mid-history, found by the depth re-ask, not the 3-day tail. |
| C4 | FAIL | D_proj = 37.3 days (formula F3 below), sensitivity with the 5m gap-fill lane 38.9 days; bound 18. Root cause measured, not noise: depth requests take ~40 s each, capping the drain at ~88 requests/hour across runs 1-2, a quarter of the L5 = 348/h limiter ceiling the design's 12-18 day expectation assumed. Clean-pass sensitivity (single pass per name, no re-plan churn, u = 1): ~32.6 days, still 1.8x the bound. The launch gate does not open at the measured throughput. |
| C5 | PASS | All 22 names have an applied 15m and 1h derived load after their last 5m write; all four run-end grid stages exit 0. |
| C6 | PASS | (a) grid dry run over the 22 after the last apply: derived 22, 0 new, 0 changed, 0 removed (3,152,490 rows unchanged). (b) digest_fresh passes on 5m, 15m and 1h for all 22 (1d too). (c) independent SQL re-aggregation of stored tradeable 5m equals every unflagged derived bar exactly: 15m 2,476,820 compared, 0 mismatches; 1h 673,265 compared, 0 mismatches. The checker had to reproduce two documented writer-side semantics: quarantined 5m bars are excluded (one SPY 2007 confirmed_corrupt bar) and buckets obey the half-open session mask with calendar closes (13:00 ET close prints and extended stamps on the 44 early-close days; verified exact on SPY 2009-11-27: derived volume 14,027,100 = the 6 pre-close bars exactly). |
| C7 | FAIL | Mismatches on 6 of the 11 archive-compared names, exact counts and the diagnostic split (price vs volume-only): WEAT 15m 12,207 / 1h 6,332, all volume-only, prices match exactly; AAPL 24 (8 price / 16 vol) / 11 (3 / 8); SPY 11 (3 / 8) / 8 (1 / 7); CEG 10 (9 / 1) / 6 (4 / 2); APH 7 (all price) / 1 (vol); EWL 2 (price) / 2 (price). Zero mismatches: CSCO, KEYS, MRVL, RLAY, TER. Reading: the small price sets sit on dividend-era buckets (vendor adjusted, ours price-only); WEAT's uniform volume-only signature is a vendor-vs-IBKR volume basis difference, not a derivation error (C6c proves the derivation faithful). Strata note: CEG and EWL were selected as "no archive rows" but the archive holds rows for them and parity compared. |
| C8 | FAIL on one name-year | Worst per-year slot coverage: DBMF 2019 = 0.99389 (below 0.995); every other name-year at or above (EWL 0.99889, WEAT 0.99918, OII 0.99968, RLI/TAP/TER 0.99984, rest 1.0). DBMF's shortfall is exactly 3 single-day IBKR 5m gaps: 2019-10-16 (78 slots, the whole session; the 1d row exists so DBMF traded), 2021-01-08 (73), 2021-11-04 (7). Neither allowed explanation holds today: no 5m ohlcv_empty_history row exists (the recorded span is 1d pre-listing through 2019-05-07) and the gaps are after the first stored bar. The days are provider-empty inside answered chunks; recording them needs an IBKR definitive-empty answer the backward walk cannot produce when neighbors return bars. |
| C9 | PASS | stray_vendor_rows 0 on all 22, both timeframes. |

Overall: the pre-registered pass criterion (all lines) does not hold. C4 is the launch gate and it
failed by 2.1x. C1's failure was a fixed code bug with a clean final pass; C7 and C8 are vendor-basis
and provider-gap findings, exactly the class of fact the pilot exists to surface before 1,262 names.

### Extrapolation (formulas F1-F3 as registered)

Inputs: n_req 1,553; H_loop 12.336 h (4.468 + 4.400 + 2.112 + 1.356); r_d = 125.9 requests/h.
R_W1 = 62.4 (624 requests to completion over the 10 wave 1 names), R_W2 = 75.5 (755/10).
T_grid = 5.96 min (median of 357.4 s). Tail requests: u = 38 requests per tail name (SPY 40, AAPL 36),
t_u median 0.11 s, a 2-request sample as registered, and contaminated: run 4's SPY/AAPL requests are
ledger-gap patches (1-2 day windows scattered through history), not the designed one-request tail.

F1: Q = 692 x 62.4 + 570 x 75.5 = 86,216 requests. rows_hat = (692 x 269,401 + 570 x 314,079)/1262 =
289,582 5m rows per name (stored basis).
F2: r_u = min(348, 3600/(0.11 + 2.0)) = 348/h. U(N) = 60 x N x 38/348 = 6.552 x N minutes:
U(242) = 1,586 min, U(872) = 5,713 min, U(1,502) = 9,841 min.
F3: with the measured u, U(N_bar)/60 = 95.2 h and H_bar goes negative: the registered formula has no
solution for a tail lane that re-patches 38 requests a name, which is the honest reading. With the
design-intent tail update (u = 1, one overlap-plus-tail request per name per night, stated as a
substitution, not a measurement): U(872) = 150.3 min, H_bar = 22.07 - 1 - (5/7) x (1.273 + 2.505) =
18.37 h, D_proj = 86,216 / (125.9 x 18.37) = 37.3 days (gap-fill sensitivity 38.9 days).

Sensitivity, clearly not the registered number: a clean single-pass drain (no KeyError re-plans, no
re-asks of complete names, so Q = 52,944 at R_W1 = 38.9, R_W2 = 45.9; r_d = 88.4/h from runs 1-2, pure
depth pacing) gives 32.6 days. Even clean, the drain is latency-bound at ~40 s per 150-day 5m chunk,
4x slower than the limiter ceiling, and no limit change inside the current design closes that.

Nightly lanes at u = 1: U(242) = 41.7 min; R4 daily lane 76.4 + 41.7 = 118.1 of 120 minutes (pass,
margin 1.9 min). U(1,502) = 259.0 min; R4 at full adoption 76.4 + 259.0 = 335.4 > 120 (fail), so
todo 505 stays open. Nightly feasibility U(1,502) = 259.0 of the 870-minute bound (pass, 3.4x slack).

Comparison lines: design floor 10.6 days, expectation 12-18; 185-46's 12.7 and 14.4-21.6. Measured
37.3 (registered formula at u = 1) exceeds all of them.

### Storage (recorded, not pass/fail)

market_data_ohlcv 6,132,301,824 -> 6,863,454,208 bytes (+731.2 MB); ohlcv_intraday_raw_archive
3,251,593,216 -> 3,309,019,136 (+57.4 MB, vendor rows moved). Rows added for the 22: about 6.75M 5m
plus 3,152,490 derived = about 9.9M rows, 73.9 bytes per row added. Registered F1 storage projection:
73.9 x 1,262 x 289,582 = 27.0 GB of 5m alone; at the measured derived ratio (0.467 rows derived per
5m row) about 39.6 GB total, against the design's at-most 17 GB 5m plus 7 GB derived. The projection
is on fresh uncompressed chunks; compression changes it and was not measured here.

### Operational notes

- The run 3 FetcherLock release hit a Postgres idle-session timeout (release_failed warning); run 4
  acquired the lock normally. One warning, no stuck lock.
- The run-end grid stage derives beyond the pilot (it takes no symbol list): 25 names got 15m/1h loads
  across the four runs. The pre-run dry run recorded this; the 3 names outside the pilot are spillover
  the stage would have covered at its next scheduled run.
- D7 (incremental sweep, 260 names, all 22 included) passed digest_fresh 780, stray_vendor_rows 520;
  coverage_cache failed on 33 audited names (drift rows of 0-2; not a scored criterion here; the
  fetcher's rebuild-coverage path is the remedy).
- The D7 1h checker comparisons in C6c are on the tradeable 5m per the registration; the derivation
  additionally aggregates zero-volume stored bars, which the spot checks confirm matches on every
  compared bucket.

### What follows

1. C4 blocks the 5m drain launch at the measured latency. The wide-ask probe (2026-10-09, SPY 5m:
   150d OK 18.7 s, 180d OK 48.1 s, 270d/365d/730d all refuse with Error 162 after retries) kills the
   wider-chunks lever: IBKR will not serve 5m asks beyond about 180 days. The next lever is a second
   tape: Alpaca (Polygon/Massive upstream) measures complete 5m from 2016-01-01 and admits through
   todo 521, leaving the IBKR drain for the 2006-2015 tail only (about half the requests, still
   18-19 days at the measured pace). The owner decision is now: admit the second tape first and run
   the IBKR drain only for the tail, or accept the full 37-day drain; running both at once is the
   one outcome to avoid (two drains, one archive).
2. WEAT's volume-basis signature and the dividend-era price buckets belong in the parity-followup
   todo: decide whether archive parity tolerates a volume basis difference per name or the archive
   rebuckets to IBKR volumes.
3. DBMF's 3 gap days: either record a 5m ohlcv_empty_history span for them (needs a definitive-empty
   answer path for mid-history single days) or extend C8's allowed explanations to provider gaps
   evidenced by answered-chunk neighbors.
4. U(242) leaves 1.9 minutes of R4 margin at u = 1: the nightly 5m update has no room for the tail
   names' gap patches. The u = 38 measured behavior must not reach the nightly lane.
