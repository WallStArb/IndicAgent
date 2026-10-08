---
phase: 185-daily-data-foundation
plan: 49
subsystem: data-integrity
tags: [todo-508, bar_source_policy, vendor-basis, stale-tradier-heads, d2-v2, d7, gap_closure]
requires: [185-37, 185-38, 185-47]
provides:
  - "38 head rows (primary ibkr, no fallback, first observation through the decided run's end): stale-basis Tradier heads are holes, raw D1 observations kept"
  - "185-38 rows of FTV, IP and STE closed at the first day plus one"
  - "vendor_basis_run failing names 35 to 13, no pass-to-fail"
  - "docs/research/stale-tradier-heads-policy.md: rule, amendment, measurements, apply record"
  - "14 undecided names handed to todo 512"
affects: [186-26, 189-10, todo 508, todo 512]
key-files:
  created:
    - docs/research/stale-tradier-heads-policy.md
    - .planning/phases/185-daily-data-foundation/185-49-SUMMARY.md
  modified:
    - .planning/todos/pending/508-stale-basis-tradier-heads-and-185-38-rows-against-continuity.md
    - .planning/todos/pending/512-exclude-or-replace-names-whose-data-defect-is-not-worth-fixing.md
    - .planning/todos/PRIORITIES.md
decisions:
  - "Owner option 1 for the stale heads, applied only where the head is measured on the run's stale basis (H2) and IBKR has no step of its own inside the run (H3)"
  - "OUT gets a head row as a data-quality exclusion of pre-listing Tradier dates (orchestrator amendment)"
  - "IP and STE 185-38 rows closed despite removing 2,414 and 1,166 IBKR bars: wrong-scale data becomes holes (orchestrator amendment)"
  - "EWS gets no row: H2 measures 10.42 bp against 10 bp; the rule was fixed before apply"
  - "FTV, IP and STE re-derivation not forced past the revision waiver; held for a waiver fix"
requirements: [D-06, D-07]
metrics:
  completed: 2026-10-08
  duration: about 4 hours including a pause
  tasks: 4
---

# Phase 185 Plan 49: stale-basis Tradier heads and 185-38 rows against continuity (todo 508) Summary

38 names now carry IBKR from their first observation through the end of the decided basis run, so
their stale-basis Tradier heads are holes instead of false returns. vendor_basis_run fails on 13
names, down from 35, and no check went from pass to fail through this plan except the expected
session_coverage holes on EWJ, EWM and EWU. The three closed 185-38 rows (FTV, IP, STE) are
written, but their re-derivation is held by a gap in the daily revision waiver.

## Commits

| Stage | Commit | What |
|---|---|---|
| Rule and pause handoff | 7525c4674 | rule, measurements, name sets, paused state |
| Amendment before apply | cd9a3229a | IP and STE closed, OUT head row, undecided names to 512 |
| H2 exact | 414167541 | EWS fails H2 at 10.42 bp, no row |
| Rows applied | e9c7217b5 | D7 baseline, 38 rows inserted, 3 closed |
| Re-derivation | d1b367031 | 38 names applied; FTV, IP, STE refused by the waiver |
| D7 after | 515942ab2 | before and after table |
| Todos | a8e746e34 | 508 status, 512 candidates, PRIORITIES row |

## Name sets

- Head row, written and re-derived (38): AAON, ABT, ADP, BAX, BDX, BF.B, CAH, CHD, COP, CVBF, DRI,
  DUK, EBAY, EQT, EWI, EWJ, EWM, EWU, FIS, FLO, GL, IBB, IRM, KIE, KMB, MAS, MS, NI, NSC, OUT, PPL,
  ROST, SPG, TT, VTR, VZ, WMB, XRT.
- Closed 185-38 row (3): FTV (valid_to 2016-06-14), IP and STE (2006-10-03). Not yet re-derived.
- IBKR rows: none (STE's IBKR-decided run fails H3).
- Undecided, no row, candidates for todo 512 (14): BNY, CF, CPAY, MGM, WELL (IBKR steps inside
  the run), DOV (IBKR steps 2014-03-03 inside the run, the run's end is one bad Tradier print), EWS
  (H2 10.42 bp), EWT, ELE, LION, W, KDP (the 185-37 rule leaves the run undecided), PATK (Tradier
  steps inside the run on 2011-05-23), NEXN (closing removes 637 IBKR interior bars; vendor noise).

## Rows and re-derivation

- bar_source_policy 1d: 38 inserted, 3 closed, 0 refused (20:14:58 to 20:15:26 UTC). Symbol rows open
  76 to 73, closed 31 to 72.
- Daily apply of the 38 (20:16:17 to 20:16:36 UTC): every per-name count equal to the read-only
  preview made before any row existed; 2 new (EWM, EWU), 50,056 changed (tradier to ibkr_named, the
  run sessions and LEGACY head dates), 54,565 removed (head dates and 1 to 6 Tradier-only run dates
  per name); a dry run afterwards shows 0/0/0. Per-name counts are in the doc's "Applied" section.
- FTV, IP, STE: preview FTV 14 removed and 2,579 changed, IP 2,414 removed and 2,618 changed, STE
  1,166 removed and 3,866 changed. Refused by the stage (revision ratio 0.999 against 0.02, no waiver).

## D7 before and after (1d failing names)

| check | before 20:03 UTC | after 20:32 UTC |
|---|---|---|
| vendor_basis_run | 35 | 13 (CF, CPAY, DOV, ELE, EWS, EWT, KDP, LION, MGM, NEXN, PATK, W, WELL) |
| unexplained_seam | 6 | 6 |
| canonical_recompute | 1 (CTVA) | 4 (CTVA, FTV, IP, STE) |
| policy_conformance | 0 | 3 (FTV, IP, STE) |
| freshness_1d | 2 (CTVA, QRVO) | 4 (plus PSKY, WBD: calendar) |
| session_coverage | 191 | 260 (EWJ, EWM, EWU from this plan; 68 untouched names from the calendar; KIE and OUT now pass) |
| lineage_missing, digest_fresh | 0 | 0 |

The baseline ran before the 2026-10-08 close and the after run past it, with the fetcher off, so
every name misses one completed session; that, not this plan, moves 68 short-history names under
session_coverage's 0.999, PSKY and WBD over freshness's 2 sessions, and the intraday coverage_cache
from 0 to 10 failing. The touched names' session_coverage now fails only on EWI (failing before),
EWJ, EWM and EWU (6 holes each: 2007-02-08 and 2007-12-06 to 12-12, dates IBKR never answered).

## Deviations from plan

1. [Rule 4 surfaced, not fixed] The daily stage refuses FTV, IP and STE: the revision waiver and the
   nightly policy_since probe read only `bar_source_policy.recorded_at`, and a close sets `valid_to`
   with no timestamp. Fixing it is a code or schema change outside this plan's mandate; the three
   rows are closed and permanent, their bars unchanged, and policy_conformance and
   canonical_recompute fail on them loudly until a fixed waiver lets the held apply run. The 38
   head-row names passed their gate exactly and were applied, so the plan did not leave 41 names
   with rows and no bars.
2. [Rule] EWS dropped from the head-row set by the exact H2 check (10.42 bp), committed before the
   first apply.
3. [Expectation] Head-row removals include 1 to 6 Tradier-only dates inside each run as well as the
   head; both are on the stale basis and the rule names them before apply (185-37's UNG precedent).
4. [Tooling] The bar-level previews use `logs/185-49/tools/policy_preview.py` (the daily stage's own
   `derive_daily_v2` and `classify` on a read-only connection with hypothetical policy rows). Kept
   under the git-ignored log directory rather than `scripts/` so no untested script enters the tree;
   promote it with a test if a later policy plan needs it.
5. [Run] The first D7 after run was cut by a 590 s shell timeout in its intraday section; a second
   full run (exit 0) is the record; both 1d tables are identical.
6. [Scope] STATE.md, ROADMAP.md and REQUIREMENTS.md not written (executor brief). Todo 508 stays
   pending: not every name is complete (FTV, IP, STE).

## For todo 515, 185-48 and the fetcher launch

- Todo 515: CTVA untouched; it is still the only canonical_recompute failure besides FTV, IP, STE.
- 185-48: nothing here reads the Tradier loader.
- Fetcher launch (189-10 Task 3): the run-end daily stage over touched names will hit the same
  waiver refusal for FTV, IP and STE whenever they are touched, failing the run's daily step unless
  the waiver fix lands first or the three are excluded from it. The 38 names now have holes on
  dates IBKR never answered (the head before IBKR's first session, and 1 to 6 run dates); the
  gap-fill lane will ask IBKR for them, and an IBKR answer fills them under the new rows.

## Known stubs

None.

## Threat flags

None. No IBKR or Tradier request, no fetcher or loader start, raw observations untouched.

## Self-Check: PASSED

- docs/research/stale-tradier-heads-policy.md exists; commits 7525c4674, cd9a3229a, 414167541,
  e9c7217b5, d1b367031, 515942ab2, a8e746e34 are in history.
- Live: 38 rows recorded in this plan's window, 3 closed; a daily dry run of the 38 shows 0/0/0;
  D7 after exit 0.
- tests/unit/test_todo_priorities_link_integrity.py passes.
