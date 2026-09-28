---
phase: 185-daily-data-foundation
plan: 06
subsystem: bars
tags: [d2b-session-grid, derived-bars, content-digest, pure-functions, dst-edge-days]

# Dependency graph
requires: [185-01]
provides:
  - src/intelligence/bars/sessions.py: nyse_sessions (mcal NYSE schedule as UTC datetimes keyed by trading date, lru-cached; market_calendar.py untouched)
  - src/intelligence/bars/session_grid.py: aggregate_session_grid + GridBars (session-anchored 15m/1h buckets from 5m, first_index/last_index for constituent flag unions, n_outside_session drop count)
  - src/intelligence/bars/digest.py: bar_content_digest + month_ranges + DIGEST_ALGORITHM "sha256-bars-v1" + EMPTY_INPUT_DIGEST (the cross-phase digest definition)
affects: [185-11, 185-12, 185-16, 185-17, 185-20, 185-23, 186]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Buckets anchor at the injected session open, never midnight UTC: the D-15 fix for aggregate_bars_from_1m's :00-edge flooring; numpy reduceat does first open / max high / min low / last close / volume sum"
    - "Digest = sha256 over rows argsorted by ts with float.hex prices, null-token volume and sorted per-row rule sets; rule version is deliberately not an input"

key-files:
  created:
    - src/intelligence/bars/sessions.py
    - src/intelligence/bars/session_grid.py
    - src/intelligence/bars/digest.py
    - tests/unit/bars/test_session_grid.py
    - tests/unit/bars/test_digest.py
  modified: []

key-decisions:
  - "Cross-phase interface (phase 186 planner): 185 defines the bar content digest as digest.py's bar_content_digest (sha256-bars-v1); the bar_content_digest table (plan 11) stores what it computes, and 186's COPY primitive in services/_batch_utils.py (D-24) reads the table and never recomputes the digest differently"
  - "The digest covers values plus quarantine state and excludes the rule version (D-07): a rule change that moves no value forces no downstream recompute; the rule version is recorded beside the digest in the table"
  - "Volume NaN or None serializes as the literal 'null' because NULL volume is a real data state (recovered venue bars, D-18); OHLC floats always go through float.hex, NaN included"
  - "aggregate_session_grid keys a bar to its America/New_York calendar date (not its UTC date): an after-close 20:00 ET bar lands on the next UTC day, and the test pins that edge"
  - "sessions.py is a new module over the same mcal NYSE schedule; src/core/market_calendar.py stays byte-identical (ic_engine import, live-run rule)"
  - "minutes is a statistic definition (15 or 60) passed by the caller, APR-exempt per the plan; the lru_cache bound (32) on nyse_sessions is an internal implementation detail, not an operator-visible tunable"

patterns-established:
  - "Direct-loop oracle in tests: derived bars are compared bar-for-bar against an independent Python-loop aggregation over the same inputs, so the vectorized reduceat path is never trusted on faith"

requirements-completed: [D-07, D-15]

# Metrics
duration: about 0.5 h including context read and self-review
completed: 2026-09-28
---

# Plan 185-06: session grid aggregation and bar content digest summary

**5m bars aggregate onto session-anchored 15m/1h edges (first open, max high, min low, last close, volume sum, never across a session) and the bar content digest fixes the content-identity definition phase 186's recompute detection consumes, both as pure functions proven on the 2025-11-28 half day, both 2025 DST days and the committed SPY fixtures**

## Performance
- **Duration:** about 0.5 h (task 1 RED/GREEN, task 2 RED/GREEN, self-review)
- **Completed:** 2026-09-28
- **Tasks:** 2

## Acceptance verified
- tests/unit/bars/ green (73 tests total in the directory: 26 session grid, 11 digest, 36 prior); full `.venv/bin/pytest tests/unit/ -q` green (2 pre-existing unrelated skips)
- `git diff --quiet src/core/market_calendar.py src/core/bar_normalizer.py services/_batch_utils.py` holds; no asyncpg/psycopg/ConfigService in any new module; no `hash(` in digest.py, sha256 only
- SPY fixtures: half day gives 4 1h bars (last 12:30 ET, 6 constituents) and 14 15m bars; each DST day gives 7 1h bars on 09:30..15:30 ET edges; derived volume sums equal the 5m sums exactly
- Two consecutive synthetic sessions: every bucket's constituents lie inside one session window and only a session's last bucket may end past its close
- Outside-session bars (pre-open, at-close half-open boundary, post-close on the next UTC day, non-session Sunday) are dropped and counted, leaving the derived grid identical
- Digest: shuffle-stable, sensitive to a one-cent close / one-unit volume / one added quarantine rule / rule order within a row, identical across subprocesses under PYTHONHASHSEED 0/1/12345

## Task commits
1. **Task 1 RED: session grid behaviors** - `c023cc405`
2. **Task 1 GREEN: nyse_sessions + aggregate_session_grid** - `8417a77aa`
3. **Task 2 RED: digest behaviors** - `82d4aa95f`
4. **Task 2 GREEN: bar_content_digest + month_ranges** - `4c3ef1744`

**Plan metadata:** this commit

## Deviations from plan
- digest.py exports EMPTY_INPUT_DIGEST (the documented empty-serialization constant the behavior block asks for) alongside the three interface names; test_digest.py additionally pins ts/open/high/low sensitivity and the None-volume token beyond the listed behaviors
- aggregate_session_grid validates and raises ValueError on unsorted stamps, mismatched array lengths and non-positive minutes (inputs the interface declares but does not error-define); covered by tests

## Issues encountered
- None.

## User setup required
None.

## Next phase readiness
- Plan 11 (D2b writer) reads nyse_sessions, calls aggregate_session_grid per (symbol, tf) segment with minutes 15/60, unions constituent 5m quarantine flags through first_index/last_index, and records bar_content_digest per month_ranges bucket in the bar_content_digest table
- Plan 12/17/20/23 reuse the same two modules for their grid and digest needs; 186 reads the table only
- No migration this plan (185-06 owns none; 380/381 already applied)

## Self-Check: PASSED
All five key files present on disk; all four task commits found in git log.

---
*Phase: 185-daily-data-foundation*
*Completed: 2026-09-28*
