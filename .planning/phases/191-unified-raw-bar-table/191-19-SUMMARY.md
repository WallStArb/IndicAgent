# Plan 191-19 Summary: Tradier residue measurement and the fallback-path proof

Status: not-ready (stopped at the Task 2 readiness gate; waiting on the gap-fill cycle)
Date: 2026-10-23 UTC (executed 2026-10-22 evening EDT)
Author: gsd executor session (plan 191-19)

## Task 1: readiness, measurement and proof harness (complete)

`scripts/ops/bars/ops_tradier_residue.py` (read-only; `--readiness`, `--measure`, `--prove`,
`--report`) and `tests/unit/scripts/test_ops_tradier_residue.py` landed TDD: RED commit
b0280dbbc, GREEN commit 1b4bb935e. The proof harness runs the unchanged d2-v3 rule
(`derive_daily_v2`) over `services.bar_derivation.read_daily_inputs`/`read_daily_params`
outputs with vendor tradier removed and the real `bar_source_policy` rows; the fixture cases
(DAL head, INDA interior, ETHA stale-only) characterize the rule honestly; the digest
self-check compares harness post-D output with stored canonical via the one `D-07` digest
definition; raw venue coverage uses the migration-476 route kinds (`venue_amex` ... `venue_nyse`),
never the stale bare `venue` kind. The boundary allow-list entry
(`TEMPORARY retire: 191-25 (Tradier retirement record script)`) is in
`tests/unit/test_market_data_ohlcv_boundary.py`.

Verification: 72 tests pass across the residue tests, `test_daily_rule.py`, the boundary test
and the temporary-allow-list expiry test; the no-write grep over the script is empty;
`git diff --stat -- src/intelligence/bars/daily_rule.py services/bar_derivation.py` is empty.

## Task 2: readiness exits 2; the plan stops here (waiting on the cycle)

`--readiness` (run 2026-10-23 00:3x UTC; depth change 2026-10-12 10:45:49.537152Z at 9800
days; full output at `logs/191-19/readiness.json`):

- 1,529 names with Tradier 1d raw rows
- 502 answered (a post-depth-change IBKR 1d ask, outcome bars or no_data, whose window start
  reaches max(first Tradier bar, today minus 9800 days))
- 1,027 unanswered, exit 2

Per the plan, `--measure`, `--prove` and `--report` did not run; `191-TRADIER-RESIDUE.md` was
not written. Task 2 reruns as written once readiness exits 0.

### Why the 1,027 are unanswered (per-name counts, measured 2026-10-23)

| Cause | Names | Will a finished cycle answer them? |
|---|---|---|
| A. Asked since the depth change (6,905 post-change IBKR 1d asks exist) but no ask window started at or before the threshold | 996 | see split |
| A1. ... because IBKR's evidence floor already reaches at or below the threshold (earliest smart/venue bar at or before the first Tradier bar, or an `ohlcv_empty_history` no_data window covers below it) | 481 | No. The planner sees the deep span covered and never issues a window that deep again; the readiness rule as written credits only post-depth-change ask window starts, and the deep evidence predates the depth change or was never a request window start. AAOI is the example: venue no_data 2006-10-09..2013-09-25 plus smart bars from 2013-09-26 cover the whole Tradier span, but the post-change asks are shallow gap windows (earliest 2014-01-15). ACM misses by one session (threshold 2007-05-10, earliest post-change window 2007-05-11). |
| A2. ... because IBKR's verified floor sits above the threshold (verified no 1d data below it) | 515 | No. No future ask can carry a window start at or below the threshold; the Tradier sessions below IBKR's floor are the permanent residue. Includes MOD (frozen, todo 519). |
| B. Never asked since the depth change (deepening cohort members whose deep windows the campaign never reached) | 29 | see split |
| B1. ... verified head floor (`ohlcv_provider_head`) at or below the threshold | 28 | Yes. The deep ask they are owed starts at or below the threshold, so they flip to answered the moment the cycle asks them, whatever IBKR answers. This is the set that is unanswered because the weekly gap-fill could not run in this window. |
| B2. WBD (frozen, todo 519): verified floor above the threshold | 1 | No. |
| C. QRVO (frozen, todo 519): no IBKR 1d evidence at all | 1 | No (contract fix or recorded freeze, todo 519). |
| D. PSKY (frozen, todo 519): floor verified at its own 2025-08-07 first bar; nothing owed, no ask | 1 | No. |

All four todo 519 frozen names (MOD, PSKY, QRVO, WBD) sit in the unanswered set; the cycle
alone cannot resolve any of them. Net: a completed gap-fill cycle flips at most 28 of the
1,027 (B1); 999 fail the readiness rule as written regardless of further cycles (481
covered-but-blind, 515 permanent-residue floor, WBD, QRVO, PSKY). This is a measured fact
about the rule's request-window criterion, recorded here with no rule or policy change
proposed or made (plan constraint; any change is the owner's call).

### Gateway and cycle timeline (why B1 waits)

- The deepening campaign (todo 537) ran three full passes: 2026-10-17 11:41Z (138 items, 192
  pre-2015 bars, budget exhausted), 2026-10-17 20:41Z (2 items) and 2026-10-18 01:41Z
  (1 item, errored). The gate's two-consecutive-zero-pre-2015-bar rule fired at 2026-10-18
  02:11Z and removed its own crontab driver, declaring the remaining 1,030 cohort names
  no_data-confirmed floors. That conclusion was premature for the 29 names above: run 1 ended
  budget-exhausted after 138 items and runs 2-3 planned 2 and 1 items (their summaries are in
  `logs/ibkr_1d_deepening_run.log.1`; neither left request rows).
- The gateway wedge began at the 2026-10-18 23:59Z nightly restart, AFTER the campaign ended;
  it did not stop the campaign. No IBKR 1d request has been answered since 2026-10-17
  20:41:11Z and no IBKR request of any timeframe since 2026-10-19 00:28:16Z.
- The gateway container is up (restarted about 2026-10-22 18:15Z) awaiting the owner's 2FA
  phone approval; nightly restarts re-send the request; the fetcher timer keeps firing (last
  2026-10-23 00:24Z) but every run ends without requests.
- Next weekly gap-fill session: per-series cadence `infra.backfill.gap_fill_interval_days` = 7
  (APR). No session can fetch until the gateway is re-authorized; the first session after the
  owner approves 2FA is the next opportunity, and the 28 B1 names then receive their deep asks
  as their slots come due. The accelerated driver is gone from crontab; re-arming it is an
  owner call, not made here.

## Deviations

1. Rule 1 (test defects fixed at first execution, GREEN commit 1b4bb935e): the RED tests
   (b0280dbbc) could only execute once the module existed, and three defects then surfaced:
   `datetime(date, tzinfo=UTC)` constructor calls (invalid), a readiness-threshold assertion
   that contradicted the plan's own max() rule (a 2020 listing is bounded by its own first
   Tradier bar; the 9800-day horizon binds only listings older than the horizon), and a
   proof-classification test that asserted `proven` while constructing required sessions with
   no bar. All three were corrected to the semantics the plan text states.
2. No other deviation: no edit to `daily_rule.py`, `bar_derivation.py` or any policy row; the
   database was only read.

## Verification

- Task 1 acceptance: the four test files pass (72 tests); the no-write grep is empty; the
  no-diff check on the rule and the derivation service is empty.
- Task 2 verify step: `.venv/bin/python scripts/ops/bars/ops_tradier_residue.py --readiness`
  exits 2 with the unanswered list (the plan's allowed stop; full JSON at
  `logs/191-19/readiness.json`).
- Full suite gate (`.venv/bin/pytest tests/unit/ -q`): exit 0, with exactly the 2 known
  intentional skips (`tests/unit/intelligence/test_pipeline_annotation.py:228`,
  `tests/unit/test_causal_hmm_decoding.py:114`).
