---
phase: 184-multi-timeframe-research-inputs
plan: 03
subsystem: research
tags: [smoothing, member-memory, e17, term-structure, statistics]
requires: []
provides:
  - "smoothing.py: SMOOTHING_HALF_LIVES, smoothing_memory_sessions, smoothing_weights, smooth"
  - "member_memory.py: MemberMemory, feature_member_memory, feature_member_memory_sessions/rows, warmup_prefix_sessions"
  - "statistics/term_structure_lag.py: LagTermStructure, lag_ic_curve, lag_term_structure, K_DAILY, BAND_LEVEL"
affects: [184-06, 184-10, 184-11]
tech-stack:
  added: []
  patterns: ["finite FIR accumulated one lag at a time (bounded memory, no recursion)", "ranks once per row per array, then K lags times S shifts"]
key-files:
  created:
    - src/intelligence/research/smoothing.py
    - src/intelligence/research/member_memory.py
    - src/intelligence/statistics/term_structure_lag.py
    - tests/unit/research/test_smoothing.py
    - tests/unit/research/test_member_memory.py
    - tests/unit/research/test_term_structure_lag.py
  modified: []
decisions:
  - "E17 L is never computed in member_memory.py: tests assert book.book_memory(...).sessions equals timing.e17_memory over MemberMemory.sessions on 1d (horizons 1, 5, 20) and intraday panels"
  - "smooth() refuses non-float input and off-menu half-lives (including bool); output dtype equals input dtype, accumulation in float64"
  - "LagTermStructure.n_shifts counts the shifts whose curve had a finite IC (the band's sample size); no shifts gives a NaN band (None in the record)"
  - "lag_term_structure refuses a shift that is not a whole number of sessions and an intraday clock without in_session"
metrics:
  duration: "about 1 h of work, plus waits on shared repro_frozen and compare-all runs"
  completed: 2026-10-28
---

# Phase 184 Plan 03: smoothing menu, member memory and lag IC term structure summary

Three pure modules: a fixed half-life menu (5, 21, 63) with a causal finite FIR whose declared memory (67, 280, 838 sessions) is the MEMORY_TOLERANCE cut, one frozen MemberMemory object that the warmup prefix, S3's transform reach and E17's L (through book_memory/e17_memory) all read, and the lag IC term structure with a joint shift band, in statistics/ with no research or measure import.

## Tasks

| Task | Commit | Files |
|------|--------|-------|
| 1 smoothing menu (B5) | 051757eff | smoothing.py, test_smoothing.py (25 tests incl. 2 no_fill) |
| 2 one memory object | d91931412 | member_memory.py, test_member_memory.py (20 tests incl. 2 member_memory_object) |
| 3 lag IC term structure (B4) | 6a559dd9c | term_structure_lag.py, test_term_structure_lag.py (8 tests) |

## What was checked

- smoothing: menu and memories; weights equal the truncated exponential with the cut between the last two weights; output equals a direct window sum for all three half-lives; a constant passes through; one NaN blanks exactly the next k_max + 1 outputs of its column only; leading NaN stays NaN until a full window; causality_probe_array passes; memory_check_array at declared k_max passes with reach in (0, k_max] on seeded [1200, 30]. `grep -c 1e-4` is 0, `SignalSource` is 0.
- member memory: the plan's worked cases (253; 5; 253 x 7 rows; +838 for h = 63; refusal of smoothing off the daily clock; warmup max and 0; bad inputs). No `fwd_span` in the new files.
- term structure: closed form AR(1) curve within 0.02 of (6/pi) asin(rho_k / 2) at lags 1..10; exact match with a row-by-row reference including NaNs and ties; independent inputs inside the band in at least 90 of 100 seeded draws; in-session mode matches the reference with cross-session pairs excluded; coverage floor; JSON record with NaN as None; import grep returns 0.

## Deviations from plan

- The plan text ends with one combined commit; the executor brief requires one commit per task, so there are three task commits.
- Amendment applied: the E17 L test calls `book.book_memory` (which wraps `timing.e17_memory` in HEAD) on top of the member-memory object rather than deriving L here.
- Added `smoothing_weights(h)` as a public helper so tests and later plans read the one weight vector.

## B7 trio (verbatim)

test_spec_hashes_pinned.py:
```
........                                                                 [100%]
```

repro_frozen (scratch dir under the session scratchpad; full output):
```
  not recorded in frozen artifact, skipped: result.excess_se
phase 179 S3: bit-identical [ 0.21612308 -0.14601638 -0.10558864]
phase 181 S2 (signal from Panel): bit-identical
  not recorded in frozen artifact, skipped: result.observed_daily
  not recorded in frozen artifact, skipped: result.null_median_daily
  not recorded in frozen artifact, skipped: result.observed_weights
  not recorded in frozen artifact, skipped: result.excess_se
phase 181 S3: bit-identical [0.19424572]
```

backfill_attempt_series.py --compare-all, one shared run for 184-02, 03 and 04 from a detached worktree at origin/main d4717489105df8b511f76b24710d0b8537345103 (contains 6a559dd9c and 44ece68c5, which classifies the E16-era periodicity runs as pre_e17), started 2026-10-28T06:53:40Z:
```
     16 "outcome": "equal"
      4 "outcome": "pre_e17"
log: logs/research/series_backfill_2026-10-28T11:26:10.035417Z.json
exit=0
```
The 4 pre_e17 entries are the family1_intraday_periodicity.yaml runs (same_slot_lag1, mean5, mean20, mean40), each with reason "E16 statistic, no E17 replay (migration 377)"; every other entry is equal.

repro_frozen and the spec-hash test ran in the shared main checkout, which holds other sessions' uncommitted edits under src/intelligence/research/ (book, certificate, combiner, power, runner, spec) and the todo 553 kernels work; compare-all ran on clean origin/main.

## Full unit suite

`.venv/bin/pytest tests/unit/ -n auto`: 7101 passed, 1 skipped. On an earlier run, made while 184-01's compare-all was loading every core, `test_regime_signals_causal_rank::test_scales_near_linearithmic_not_quadratic` failed once (an 11.4x timing ratio against a 10x bound). It passed alone and in every later full run; the failure came from CPU contention, not from these files.

## Known stubs

None. The term structure has no consumer yet by design (T-184-11); plan 11 adds the record-only enforcement.

## Self-check: PASSED

All six files exist; commits 051757eff, d91931412 and 6a559dd9c are on main.
