# Review of 191-06 (886e9c212 code, 1ae865663 summary)

Read-only. All DB checks symbol-bounded or on small tables (ohlcv_request 48k rows, ohlcv_coverage), statement_timeout set.

## Ranked findings

### F1 High (wasted pulls, live evidence) 1d planner cannot ask a completed session between its close and 00:00 UTC; the 1d due rule then re-queues every name every run
- scripts/infrastructure/backfill/_d1_gaps.py:277-292 (run_end = now; window end .date() truncation), _history_fetch_item.py:642-657 (_with_verification_asks overlap window ends at midnight of eligible[-1]), _d1_gaps.py:295-323.
- Mechanism: slot D (midnight UTC) < now, so plan_gaps caps the window at now: (D 00:00, D 21:00) -> .date() -> (D, D) -> midnight -> zero-length. The provider walk (`while chunk_end > start`) asks nothing. The 1d overlap window is (eligible[-20], D) -> ends D 00:00, so it re-asks the 19 prior sessions and never D. Request window_end = D 00:00 < last_close, so daily_due_reason returns not_current and the name is due again next run.
- Repro (scratchpad sim/sim_1d.py, real code, fake conn): now = 2026-10-12 20:00 and 22:00 UTC -> plan [(10-12, 10-12)], with overlap [(10-06 00:00, 10-12 00:00)]; at 10-13 00:05 -> [(10-12, 10-13)].
- Live: ohlcv_request 2026-10-12 20:11-23:23 UTC: 1,495 SMART 1d requests, 1,495 names, every window_end = 2026-10-12 00:00 (Monday's completed session excluded); the whole universe is asked again after 00:00 UTC 10-13 (AAPL 10-12 bar served 01:27 UTC). One wasted universe cycle per evening (~1,500 requests, ~4 h at 58/10 min); half-days waste 6 h of window.
- The D-191-J text ("a bar answered at or after the close is complete") and the summary's "an unfinished session is never asked for" hold for acceptance, not for asking. tests/unit/scripts/test_d1_gaps.py:269-280 asserts the zero-length (D2, D2) window as correct.
- Fix: in detect_gaps_1d_from_d1 keep only slots whose session close <= now (session_complete_at(day, now, sessions)) and plan with run_end = midnight(end)+1d (never cap a 1d window at now); in with_overlap_window make the appended window end-exclusive (last + 1 day) and merge on `start <= prev_end`.

### F2 High (perf, run-blocking) load_first_bars per vendor takes hours
- scripts/infrastructure/backfill/_empty_history.py:213-222; called from ohlcv_history_fetcher._default_context (line ~751) for every candidate on every run.
- `min(timestamp) FROM ohlcv_raw WHERE symbol AND vendor` has no timeframe, so idx (symbol, timeframe, timestamp) cannot serve it and every compressed chunk segment of the symbol is touched.
- Measured: 3 symbols 28.5 s cold / 2.9 s warm; 30 random active symbols > 170 s (timeout); old tradeable-view query 3.4 s for 30; per-timeframe variant 5.8 s for 30. 1,529 candidates => > 2.4 h before the first item. The summary's dry run used a harness around _plan_gaps, so prepare/_default_context was never exercised.
- Fix: min over per-timeframe scalar subqueries (`WHERE symbol=s AND timeframe=tf AND vendor=v`) for the run's timeframes (measured 0.2 s/symbol).

### F3 High (pre-history re-asked forever; series excluded) seeded tape floors pose as verified per-symbol heads
- Root cause outside the 06 diff but it answers ask (2): migration 465 lines 53-62 seed every active name with ibkr 5m head 2006-07-01 22:00 and 1d head 2000-01-03, verified_at NOW() (1,529 and 826 rows, verified 2026-10-10 11:57:35). load_fresh_heads (_empty_history.py:202-209) reads them as fresh verified heads for 90 days (infra.backfill.empty_history_reverify_days = 90) and keys by symbol only, so the 5m and 1d rows overwrite each other arbitrarily. _head_floor (_history_fetch_item.py:501-516) then never calls get_head_timestamp and floors at the tape start, so every full-window 1d item asks from 2000-01-03 even for a 2020-2025 IPO.
- Live: 13 ibkr 1d series are excluded (status error, consecutive_failures >= 5 = infra.backfill.max_consecutive_failures): BEPC, DTM, IONQ, RAL, LION, VTS ask 2000-01-03..2006-10-14 each run and get failed/timeout; NB, CHRD, CLBK, ELE ask 2006..IPO (failed). A failed outcome never confirms an empty span, so nothing ends the loop and the excluded names get no daily updates. Plan 06's per-vendor reads widen the exposure (QRVO has zero IBKR 1d raw; DBX 31 rows).
- Fix: treat seeded floors as floors, not heads (separate column or verified_at NULL), still run get_head_timestamp when first_bar is None or > start_dt; read heads per timeframe (load_fresh_heads_per_tf); never charge consecutive_failures for a window wholly before the vendor's head.

### F4 Medium (ledger correctness) rebuild never zeroes a provider row whose vendor holds no raw and no requests
- services/ohlcv_coverage_writer.py:197-245 (FULL OUTER JOIN only emits series present in raw or requests), refresh_1d_bounds (175-190, "left untouched").
- Live: QRVO 1d ibkr row = 2015-01-02..2026-10-02, 2,954 rows; IBKR holds zero QRVO 1d raw (only tradier consolidated 2,955) and no ibkr requests. The row is the pre-191 Tradier-era bound under the ibkr label, violating the plan truth "each (symbol, timeframe, provider) row equals a direct count over raw". Every other row's bounds exist in raw (checked all rows with row_count > 0 by point lookup).
- Effect: update lane tails from a Tradier-era latest; today masked only because QRVO is status error.
- Fix: in rebuild, also UPDATE existing rows of the provider in scope that match no raw row to NULL bounds and row_count 0 (LEFT JOIN from ohlcv_coverage), same in refresh_1d_bounds.

### F5 Medium (pre-existing, mis-described) 1h expected grid mismatches IBKR stamps in both seasons
- src/intelligence/bars/gap_plan.py:217-228: slot = session_open + n*1h -> 13:30, 14:30, ... (summer) / 14:30, 15:30 (winter). IBKR stamps 13:30, 14:00, 15:00 ... (AAPL 2026-07-14) and 14:30, 15:00, 16:00 (2026-01-14). Docstring says "then clock hours"; code does not. Summary item 3 says winter only.
- Stored-slot evidence never covers 6 of 7 slots, so 1h coverage rests on answered windows alone. Not a loop: once a bars answer lands its window covers. Cost: 170 of 888 ibkr 1h series have history before their first answered window (~1.19M calendar days, ~1,100 requests of 1,095 d, about 3 h of IBKR budget) plus any interior ledger holes; bar_auditor shares the rule and reports the same false gaps.
- Fix: _rth_grid_slots for 1h: [open] + clock hours from ceil(open to hour) while < close.

### F6 Medium (latent hole, pre-existing semantics kept) any single route's no_data covers a 1d session
- _d1_gaps.py:53-72 + 91-92: route = ANY(SMART + venues), outcome no_data, no requirement that the other routes agree. The empty-history rule (confirmed_empty_spans) requires every route.
- Live evidence of the mechanism: SCHW SMART no_data 2006-10-05..2010-03-04 holds 651 venue bars; DAL ISLAND failed 2006-10..2007-04 while SMART/ARCA/AMEX/BATS no_data in the same run. DAL/VRP there are genuinely pre-listing, so no hole found today, but a failed listing-venue walk under a SMART no_data window would never be re-asked.
- Fix: for 1d use the confirmed spans (all required routes no_data in one run) as the no_data coverage, not per-route windows.

### F7 Low (latent) empty-history and first-bar state is loaded for ibkr regardless of ctx.vendor
- ohlcv_history_fetcher.py:746-753 and _history_fetch_item.py:514, 803, 827 use _EMPTY_HISTORY_PROVIDER while the planner uses ctx.vendor. Only the ibkr registry entry exists today, so no effect; a second entry through fetch_item would get IBKR's empty spans and heads. Fix: key by ctx.vendor.

### F8 Low 1d currency read and 1d coverage count smart_adjusted rows the planner excludes
- _fetch_queue.py:725-729, ohlcv_coverage_writer.py:162-172. The adjusted series holds forming bars (AAPL/SPY 2026-09-30 served 18:01 / 19:34 UTC). Today trades rows are newer, so no effect. Fix: same `kind <> ALL(not-coverage kinds)` filter in both.

### F9 Low (summary accuracy) "Nothing in the fetch process reads ohlcv_observation"
- ohlcv_history_fetcher.py:147 imports split_detection.overlap_pairs (services/split_detection.py:63,71 read ohlcv_observation); run-end daily stage via bar_derivation.py:425,505. The summary's Unresolved 1 admits it; the headline claim and the plan truth "No fetch-process module references ohlcv_observation" are not met. Fetcher held, so no runtime effect yet.

### F10 Low intraday forming slot is asked and pinned for 15m/1h
- plan_gaps caps the forming slot at now; IBKR returns the partial bar; it is stored and counts as a slot. 5m is re-asked by the update overlap (last-wins), 15m/1h have no overlap lane. Limited reach (15m/1h are parity/derived). Fix: drop intraday slots whose end > now from the horizon.

## Verified sound
- Vendor filter on every planner read (_RAW_SLOTS_SQL, _ANSWERED_WINDOWS_SQL incl. its EXISTS, _1D_STORED_SQL, detect_gaps, has_bar_before/has_bar_between, _confirmed_spans, candidate read, _LATEST_OWN_1D_SQL); overlap pairs read the same (vendor, kind) only (read_stored_closes).
- 1d kind set: ibkr kinds are smart_trades, smart_adjusted, venue_amex/arca/bats/island/nyse; all 1d stamps are midnight UTC (7 names checked); served_at never NULL in the sample.
- Coverage re-verification, new seeded sample (md5 'review06b'), 20 of 20 match on count(distinct), earliest, latest: alpaca 5m GLNG HYD LHX T; ibkr 5m AAP EWG EWZ NEM; ibkr 15m FE HOG MBX PENG; ibkr 1h ALRM BSX LIN TRMB; ibkr 1d AME BWIN DBX URA (1d raw count(*) is about 2x distinct: smart_adjusted shares stamps). Bound check over every row with row_count > 0: only QRVO 1d fails (F4).
- 15m grid matches IBKR stamps across DST (open-anchored, 15 min step).
- _with_verification_asks cannot loop on 5m: judge_overlap for 5m escalates only on the median ratio, so routine restatements and forming bars do not escalate. 1d overlap adds no extra request in the common case (merged into the gap window).
- Tests: no assertion weakened except the 100 -> 50 pending count, which follows 64c004f63's dedupe; boundary allow-list entries for _d1_gaps/_history_fetch were removed (tightened). The new SQL tests are string checks against fakes (thin but not empty).
- _LATEST_OWN_1D_SQL costs 0.6 s for all active names.

## Could not verify
- Whether the per-source 5m plan for names with no IBKR 5m raw (BEPC 94 windows) is actually queued for IBKR (depends on bar_source_policy rows, plan 07).
- Live behaviour of the split/waiver path (plans 08/10 still read ohlcv_observation).
- Interior gaps in 1h answered windows beyond the head estimate in F5.
