# Plan 191-19 Summary: Tradier residue measurement and the fallback-path proof

Status: not-ready (stopped at the Task 2 readiness gate; waiting on the gap-fill cycle).
The amended readiness (2026-10-23 evidence basis) also exits 2: 1,088 settled, 437 unsettled.
Date: 2026-10-23 UTC (executed 2026-10-22 evening EDT; review fixes and the readiness
amendment landed 2026-10-23)
Author: gsd executor session (plan 191-19)

Review 2026-10-23 (191-19-REVIEW.md, fresh-context): FAIL on the Task 2 cause analysis of
this record (finding 1: 446 of the 1,027 misclassified; fixed below), PASS on the Task 1
harness. STATE.md completed_plans restored to 120 (finding 2). Four P3 code fixes and the
coordinator's readiness amendment landed with it (commits e48177493 RED, 5ad1357f9 GREEN).

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
  reaches max(first Tradier bar, today minus 9800 days)) under the original ask-row predicate
- 1,027 unanswered, exit 2 (the amended evidence basis below settles 1,088 of the 1,529 and
  leaves 437)

Per the plan, `--measure`, `--prove` and `--report` did not run; `191-TRADIER-RESIDUE.md` was
not written. Task 2 reruns as written once readiness exits 0.

### Why the 1,027 are not answered by the original predicate (corrected split, review-verified 2026-10-23)

The table below replaces this record's first cause analysis, which the review showed
misclassified 446 of the 1,027: the original A2 claim ("verified floor above the threshold,
so no future ask can reach it") was false for 429 of the 515, and 17 of the 28 B1 names are
already covered deep. The corrected classes (threshold rule exactly as the harness
implements it, today = 2026-10-23):

| Class (of the 1,027) | Names | Will a finished cycle answer them? |
|---|---|---|
| Covered-but-blind: the deep span is already covered by IBKR bars or no_data answer windows (the original A1's 481 plus 17 of B1; e.g. AAOI's venue no_data 2006-10-09..2013-09-25 plus smart bars from 2013-09-26; BJ's span 2006-10-09..2011-05-21 against a 2011-05-23 threshold) | 498 | No. The gap planner never issues a window into covered ground (`_d1_gaps.py`, `_history_fetch_item.py`), so the original predicate (a post-depth-change ask window start) could never fire for them. Not strictly permanent for the empty-span-backed subset: that coverage is freshness-gated (re-verified after `infra.backfill.empty_history_reverify_days`) and re-opens on reverify, after which the re-ask satisfies the predicate. |
| Verified 1d `ohlcv_provider_head` above the threshold (it floors every future ask above it) | 75 | No (recorded evidence that nothing is below the head). |
| Settled by a deep no_data answer window (CTRE, ETSY, EXLS, FUBO, LYB, NEXT, QXO, RBLX, RSPR, TAN, TROX) | 11 | No (asked and answered nothing-traded). |
| Unasked, nothing below the floor verified: deepening run 1 ended budget-exhausted after 138 items, runs 2-3 planned 2 and 1 items, so the deep span was never asked | 429 | Yes, when their slot comes due (AMP, AOS, APA, APD, APH, ARE are examples: no IBKR bar, no_data window, empty span or head at or below their thresholds). Includes MOD (frozen, todo 519): it will not be asked. |
| Never asked, the deep ask owed (B1 remainder) | 11 | Yes. This is the set that is unanswered because the weekly gap-fill could not run in this window. |
| Frozen (todo 519): WBD (verified head 2005-07-21 above its 2005-07-08 threshold) and PSKY (head at its own 2025-08-07 first bar); QRVO (no IBKR 1d raw rows at all) | 3 | No (owner decision per todo 519). |

Net (corrected): about 440 flip when a finished cycle runs (429 plus 11; MOD, frozen under
todo 519, sits in the 429 and will not be asked), and about 587 fail the original rule
regardless (498 covered-but-blind, 75 head-floored, 11 no_data-settled, 3 frozen), not the
"at most 28 / 999" this record first claimed. The planner derives window starts as the first
uncovered session from max(today minus 9800 days, provider head), so a name with an
uncovered deep span and no head above the threshold is asked deep on its next slot.
Caveats (review): empty-span coverage is freshness-gated (so covered-but-blind is not
strictly permanent for that subset), and a horizon-bound threshold can miss by one session
(ACM: threshold 2007-05-10, earliest post-change window 2007-05-11; ACM's earliest IBKR bar
sits exactly at the threshold, so the amended basis settles it). The permanent data residue
for plan 20 is the Tradier sessions below IBKR's verified floors, roughly the 89
evidence-settled names (75 head-floored, 11 no_data-settled, WBD, PSKY, QRVO), far smaller
than the old "515 permanent residue" framing. This is a measured fact about the rule's
request-window criterion, recorded with no rule or policy change proposed or made by this
plan (the amendment below was the coordinator's, applied as instructed; any further change
is the owner's call).

### Amendment 2026-10-23 (readiness evidence basis) and the amended rerun

The coordinator amendment (now a dated section of 191-19-PLAN.md) redefines readiness:
a name's Tradier span is settled when any of (a) the original ask-row predicate, (b) an
IBKR raw bar (smart_trades or a venue route kind) at or before the threshold, (c) a
definitive no_data request window (any age, no open transport failure; the gap planner's own
`daily_no_data_coverage` definition) starting at or before it, or (d) a verified 1d provider
head above it. Freshness-gated `ohlcv_empty_history` spans never settle (they re-open on
reverify and get re-asked, which then satisfies (a)). Todo 519 frozen names are excluded
from the gate; the hold has no machine-readable surface (only MOD and QRVO carry
`bar_source_policy` class C hold rows; PSKY and WBD are on the default policy; no APR key,
no instruments flag), so the harness takes an explicit `--frozen-names` argument with no
hardcoded symbols.

Amended rerun (2026-10-23, `logs/191-19/readiness_amended.json`,
`--frozen-names MOD,PSKY,QRVO,WBD`): 1,529 Tradier names, 1,088 settled, 437 unsettled,
exit 2. Basis counts: ask 502, raw-bar 378, no_data 137, head 73 (plus the two frozen
head-floored names PSKY and WBD). The frozen four are flagged, never gated: PSKY and WBD
basis head, MOD basis none (unasked deep span), QRVO basis none (no IBKR 1d evidence).
Spot-checks match the review: BJ, ACM and AAOI settle; AMP, AOS, APA, APD, APH, ARE stay
unsettled. The 437 unsettled are the unasked deep spans the standing cycle owes; readiness
still exits 2, so Task 2 remains stopped at the gate, now waiting on the cycle for the 437
rather than the 1,027.

### Gateway and cycle timeline (why the 440 wait)

- The deepening campaign (todo 537) ran three full passes: 2026-10-17 11:41Z (138 items, 192
  pre-2015 bars, budget exhausted), 2026-10-17 20:41Z (2 items) and 2026-10-18 01:41Z
  (1 item, errored). The gate's two-consecutive-zero-pre-2015-bar rule fired at 2026-10-18
  02:11Z and removed its own crontab driver, declaring the remaining 1,030 cohort names
  no_data-confirmed floors. That conclusion was premature for the 440 cycle-flippable names
  (429 whose deep span was never reached plus 11 owed the deep ask): run 1 ended
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
  owner approves 2FA is the next opportunity, and the 440 then receive their deep asks
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
2. The plan's files list (`191-19-PLAN.md` lines 70 and 75) places the d2v2 fixture-shape
   tests (DAL head, INDA interior, ETHA stale-only) in `tests/unit/bars/test_daily_rule.py`;
   they landed in `tests/unit/scripts/test_ops_tradier_residue.py` beside the harness
   (`test_dal_head_case...`, `test_inda...`, `test_etha...`). The coverage is identical and
   `test_daily_rule.py` is untouched (review finding 6; recorded here as it should have been
   in the first record).
3. The 2026-10-23 readiness amendment (coordinator instruction after the review) changed the
   Task 2 gate from the ask-row-only predicate to the four-condition evidence basis and added
   `--frozen-names`; implemented RED-first (e48177493) then GREEN (5ad1357f9) with the plan
   amendment section. No other deviation: no edit to `daily_rule.py`, `bar_derivation.py` or
   any policy row; the database was only read.

## Verification

- Task 1 acceptance: the four test files pass (76 tests after the amendment: 24 residue,
  44 daily_rule, 2 boundary, 6 temporary-allow-list); the no-write grep is empty; the
  no-diff check on the rule and the derivation service is empty.
- Task 2 verify step: `.venv/bin/python scripts/ops/bars/ops_tradier_residue.py --readiness`
  exits 2 with the unsettled list (the plan's allowed stop; full JSON at
  `logs/191-19/readiness.json`, amended run at `logs/191-19/readiness_amended.json`; exit 2
  under both predicates, 1,027 then 437 unsettled).
- Review-fix verification (small code class, targeted): the residue, daily_rule, boundary
  and temporary-allow-list tests pass; the no-write grep and both no-diff greps are empty.
- Full suite gate before the not-ready record (`.venv/bin/pytest tests/unit/ -q`): exit 0,
  with exactly the 2 known intentional skips
  (`tests/unit/intelligence/test_pipeline_annotation.py:228`,
  `tests/unit/test_causal_hmm_decoding.py:114`).
