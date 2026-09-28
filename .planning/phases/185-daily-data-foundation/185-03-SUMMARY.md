---
phase: 185-daily-data-foundation
plan: 03
subsystem: providers
tags: [d1, request-record, provider-callbacks, venue-recovery, capture]

# Dependency graph
requires:
  - 185-02 (RequestRecord mirrors the ohlcv_request row the sinks COPY)
provides:
  - src/providers/base.py RequestRecord frozen dataclass (the D-05 contract type)
  - fetch_historical_bars(on_request=, on_observation=, fetch_run_id=, route=) on IBKRProvider
  - fetch_adjusted_daily_closes(..., what_to_show=) pairing TRADES/ADJUSTED_LAST on one fetch_run_id (D5 input)
  - Venue bars delivered to on_observation under verify-only store_bars=false (D-16 capture)
  - route=<venue> single-walk requests for the D3 study (plan 13) and intraday verify-only work (plan 20)
affects: [185-09, 185-13, 185-14, 185-15, 185-17, 185-19, 185-20, 185-21, 185-22, 185-24]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Provider request reporting: sync callbacks owned by the caller (DAG invariant 3), failures logged as ibkr.request_callback_failed then re-raised"

key-files:
  created: []
  modified:
    - src/providers/base.py
    - src/providers/ibkr.py
    - tests/unit/providers/test_ibkr_provider.py

key-decisions:
  - "Non-timeout gateway exceptions are now retried and recorded as outcome failed (error_text carries the exception) instead of propagating and tearing down the walk; the plan's own test_request_record_failed_after_retries spec required it, the action text had not spelled it out"
  - "_request_back_from_now returns (bars, record) and callers emit on_observation with parsed OHLCVBar lists; the record is built whenever on_request or a fetch_run_id is passed, so on_observation-only callers still get one"
  - "Explicit venue routing returns early from _fetch_historical_bars_impl (sort+return mirrors the tail) so the SMART-only fallback gate stays untouched"

patterns-established:
  - "One RequestRecord per request at each outcome point (bars/no_data/timeout/failed), requested_at before the wire call, answered_at after"

requirements-completed: [D-05, D-16, D-20]

# Metrics
duration: about 55 min inline (orchestrator session; quota window still closed for subagents)
completed: 2026-09-27
---

# Plan 185-03: provider request records and venue observations summary

**RequestRecord contract type plus full callback threading through the SMART walk, the venue fallback walk, and the back-from-now path; verify-only no longer discards venue answers**

## Performance
- **Duration:** about 55 min (task 1 RED about 20, task 2 GREEN about 35)
- **Completed:** 2026-09-27
- **Tasks:** 2

## Accomplishments
- RequestRecord frozen dataclass in base.py, mirroring one ohlcv_request row minus caller/source
- Seven request_record tests green; all 33 pre-existing provider tests untouched and green; full tests/unit/ green
- Venue-recovered event now structlog keyword fields; no stdlib extra= remains on it

## Task commits
1. **Task 1: RequestRecord + failing tests (RED)** - `05516a18c`
2. **Task 2: callback threading (GREEN)** - `567badfad`

**Plan metadata:** this commit

## Decisions made
- Executed inline in the orchestrator (owner direction 2026-09-27: keep going rather than wait for the quota reset); simplify gate performed as an inline self-review pass for the same reason, deviations and hardening noted here
- The retry loop now catches non-timeout exceptions (retry with backoff, then outcome failed with error_text) instead of propagating; behavior aligned with how timeouts were already treated, and it is what makes every request auditable in D1

## Deviations from plan
- Gateway-exception retry semantics (above) was implied by the test spec but not in the action text; recorded rather than assumed
- Tests wrap bar answers in BarDataList to carry reqId (mechanical, the no-data path already did)

## Issues encountered
- First GREEN run failed because the test fake set reqId on plain lists (AttributeError, then correctly recorded as outcome failed by the new code); fixed in the fake
- The chunk-count test needed its own narrow window (the class-wide 2010-2026 window with 10-day chunks is ~584 chunks)

## User setup required
None.

## Next phase readiness
- Plans 09/13/14/15/17/19/20/21/22/24 wire campaigns by passing on_request/on_observation (sink.append shapes) and fetch_run_id from new_fetch_run_id()
- D5 (plan 15) pairs TRADES and ADJUSTED_LAST on one fetch_run_id via fetch_adjusted_daily_closes(what_to_show=)

---
*Phase: 185-daily-data-foundation*
*Completed: 2026-09-27*
