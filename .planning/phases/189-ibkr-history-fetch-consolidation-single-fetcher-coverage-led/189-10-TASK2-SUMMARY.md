---
phase: 189-ibkr-history-fetch-consolidation-single-fetcher-coverage-led
plan: 10
scope: Task 2 only (20-name 5m pilot); Task 3 not run
status: pre-registered, pilot not started
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
