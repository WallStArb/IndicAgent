---
phase: 185-daily-data-foundation
plan: 37
subsystem: data-integrity
tags: [vendor-basis, bar_source_policy, d2-v2, d7, exception-rows, spin-offs, gap_closure]
requires: [185-33, 185-38, 185-40, 185-41]
provides:
  - "docs/research/vendor-adjustment-basis-study.md: decision rule pre-registered (a2d9ca6e1), results (038a5774c), applied (43196882c)"
  - "scripts/research/vendor_basis_study.py: read-only study, TSV per run, JSON summary, evidence JSON per proposed row"
  - "30 bounded IBKR-primary 1d exception rows on 25 names, each with its basis run as evidence"
  - "25 names re-derived (18,922 changed, 49 new, 6 removed); vendor_basis_run blockers 46 to 31, each named"
  - "todo 508 (P0, owner tier): 45 stale-basis Tradier heads and 5 185-38 rows against continuity"
affects: [185-35, 185-42, 185-43, 185-47, 186-26]
key-files:
  created:
    - docs/research/vendor-adjustment-basis-study.md
    - scripts/research/vendor_basis_study.py
    - tests/unit/scripts/test_vendor_basis_study.py
    - .planning/todos/pending/508-stale-basis-tradier-heads-and-185-38-rows-against-continuity.md
  modified:
    - tests/unit/scripts/test_ops_source_policy.py
    - .planning/todos/PRIORITIES.md
decisions:
  - "Rows bounded at a run whose start is IBKR's first common session are withheld when Tradier holds earlier dates: Tradier's head is on the same stale basis, so the row would move the false return into a seam no check judges (deviation, narrows the rule)"
  - "Runs where IBKR answers mostly with zero-volume prints are withheld (WBD 2016); a non-trading series is not evidence of continuity (deviation, narrows the rule)"
  - "Spin-off record taken from the companies' own release pages over HTTP; SEC EDGAR documents refuse an undeclared user agent and no contact was invented"
  - "BDX is undecided under rule 4: both vendors adjust for the Waters distribution, with factors 1.8% apart; settling it needs BD's unadjusted 2026-02-09 close"
requirements: [D-06, D-10, D-21]
metrics:
  duration: about 55 minutes
  completed: 2026-10-07
  tasks: 3
  files: 6
---

# Phase 185 Plan 37: Vendor adjustment basis study Summary

The two 1d vendors' basis disagreement is measured, decomposed and decided by a rule committed before any result. 30 IBKR exception rows repair factor-of-2 to factor-of-25 false returns in canonical 1d on 25 names. The 31 names that still block are named, with the owner decision that unblocks them filed as todo 508.

## Commits

| Task | Commit | What |
|---|---|---|
| 1 | 52d324a73 | policy CLI tests: empty evidence refused, dry runs write nothing, `--close` refuses a closed row |
| 2 | a2d9ca6e1 | study doc: question and the pre-registered decision rule, alone |
| 2 | ed6eae3db | read-only study script and tests |
| 2 | 038a5774c | results, known cases with cited spin-off record, proposed rows |
| 3 | 43196882c | rows applied, re-derivation, D7 rerun, final counts, `undecided_blocking: 31`; todo 508 |

All pushed to origin/main.

## Task 1

The 185-38 CLI already covered `--add` evidence refusal for a missing value, the open-row refusal and the sweep's dry-run default. Four tests were added (fakes only) for the listed behaviors that had no test: an empty evidence object refuses before any connection; an `--add` dry run issues no statement; `--add --apply` inserts one row and leaves recorded_at to the column default; `--close` targets only the open row and exits 2 when none is open. The single_writer registry entry (migrations plus `ops_source_policy.py`) passes. The script was not changed.

## Task 2 key figures

- Study: 1,037 names with both vendors, 62 s, read-only. 2,173 basis runs on 459 names (456 compute_1d). The rule decides 129 runs (100 ibkr continuous, 29 tradier) and leaves 2,044 undecided. Of the undecided, 1,978 are gradual drifts with no boundary step, and 1,814 are shorter than 20 sessions. D7's 46 blocking names are reproduced exactly. The rule agrees with D7's `classify_run` on 63 of the 65 runs D7 decides, and decides 66 that D7 leaves open.
- Decomposition: 216,056 raw name-dates differ by more than 1% on 821 names (the design measured 216,057). Of these, 209,945 (97.2%) lie inside a basis run, 5,561 (2.6%) are isolated, and 550 (0.3%) agree on the current scale (pre-split answers).
- The decided runs are constant factors (2.0, 0.5, 3.0, 4.0, 1/3, 16, 0.04) that return to exactly 1 on one date. Most are Tradier history on a stale split basis: 25 runs end 2011-05-20, 8 span 2011-05-23 to 2015-09-10, and 6 iShares country ETFs end 2016-11-04. In those runs Tradier's volume is on the stale share scale too.
- Known cases:
  - RJF: Tradier continuous, canonical correct.
  - REX: IBKR continuous, already IBKR.
  - IBM: Tradier adjusts for Kyndryl and IBKR does not; no row.
  - LEN: Tradier adjusts for Millrose at the 2025-01-21 record date and IBKR does not; no row.
  - BDX: both vendors adjust for the Waters distribution (about 0.135 WAT, roughly 44.30 per share); their factors differ by 1.8%, so the case is undecided and gets no row.
  - ETHA: no current-scale IBKR answer exists, so no run.
  - Sources are cited with URL and retrieval date: IBM newsroom, two BD IR releases, three Lennar IR releases.

## Task 3

- Rows: 30 via `--add` (dry run of all 30 first, then `--apply`), 0 refused. Each has valid_from = the run's first session and valid_to = the day after its last. Evidence files are in `logs/185-37/evidence/`.
- Daily stage on the 25 names, run at 18:58 UTC, outside the forbidden windows:
  - Baseline dry run: 0/0/0.
  - Dry run with the rows: exactly the study's 18,922 sessions.
  - Apply: 6.1 s, exit 0, one applied ohlcv_load row per name, revision-ratio breaches waived. 18,922 changed, 49 new, 6 removed, 18,928 revision rows.
  - Dry run after the apply: 0/0/0.
  - Per-name counts are in the doc.
- D7 by hand: 709 s, exit 0.
  - vendor_basis_run blockers fell from 46 to 31.
  - The four zero-tolerance checks have 0 failures.
  - session_coverage still fails 240 names, unexplained_seam 8.
  - On the 25 names, vendor_basis_run, canonical_recompute and policy_conformance all pass.
- Plan verify passes: live blocking count 31 equals `undecided_blocking: 31`, and the names match.

## Verification

- Task verifies: the Task 1 pytest command passes. The doc has 3 commits after this plan's work and contains "Decision rule". The first commit's Results section is empty. The Task 3 count check passes.
- Full `.venv/bin/pytest tests/unit/ -q`: exit 0, 0 failures, the same 5 pre-existing skips. Run after the last code change and before the final commits.
- ruff and black are clean on every touched Python file; pre-commit 9/9 on every commit.
- repro_frozen does not apply: nothing under research/ or statistics/ was edited.
- Unit tests use fakes. The study test scans the module for write statements.

## Deviations from plan

1. [Rule 2, narrows the rule] Unmeasured range ends. The pre-registered row runs from the run's first session. When that session is IBKR's first common session and Tradier holds earlier dates, the head shares the run's stale basis (checked on ABT). A row there moves the false return into the head seam, which nothing judges: vendor_basis_run looks inside runs, and unexplained_seam only judges a recent window. 45 runs were withheld and listed (28 of them block). This was added after the first study run and labeled as such in the doc; it never adds a row the rule would not write.
2. [Rule 2, narrows the rule] No-trade IBKR series. WBD's two 2016 runs rest on IBKR answers with a flat close of 25 and zero volume on 56% and 76% of sessions, while Tradier trades millions of shares. They were withheld at a threshold of more than half zero-volume sessions. Every other proposed row has at most 3.2% zero-volume IBKR sessions.
3. [Tooling] WebFetch was not available to this executor, so the spin-off record was fetched with curl. SEC EDGAR documents refuse an undeclared user agent, and I did not invent contact details or send the owner's email. The companies' own release pages were used, which the plan allows ("or the company's investor relations page").
4. [Plan text] The plan's `--timeframe 1d` flag does not exist on `ops_source_policy.py` (the CLI writes 1d only), so it was dropped. The first dry-run loop failed on argparse and wrote nothing.
5. [Plan assumption wrong, found after the apply] The plan says rollback of a row is `--close`. That holds only for an open row. The table's trigger refuses every change to a closed row, and a row bounded by the rule is closed from insertion, so the 30 rows are permanent. Reversing one needs a migration that supersedes the append-only rule for it. The bars stay recoverable from ohlcv_revision. I should have checked this before the apply. The doc's Applied section says so.
6. [Consequence, reported] UNG's session_coverage went from pass (1.00000) to fail (0.99878). The cause is its 6 Tradier-only dates inside the run: stale half-scale prices with no IBKR answer, now holes. The 189-10 gap-fill lane asks IBKR for them. XHE and XTN improved and XPH is unchanged.
7. [Correction before commit] Two corporate-action causes I first wrote from memory (the FTV and IP distributions, KDP's special dividend) were removed from the doc and the todo. Those dates are stated as data only.
8. STATE.md, ROADMAP.md and REQUIREMENTS.md were not written. The executor brief forbids in-place writes to STATE and ROADMAP, and D-06, D-10 and D-21 are not fully met while 31 names block. The orchestrator records the plan.

## For the next plans

- 185-47: 1d symbol rows are now 74 open IBKR rows (185-38), 30 closed bounded rows (185-37, evidence plan 185-37) and VMRK's closed row. The confirm step's "74 old plus the new symbol rows open" still holds for open rows, but a check counting all symbol rows sees 105. The "a name with any 1d symbol row is decided" rule now covers the 25 names with bounded pre-D rows. All 25 are class A today, so it changes nothing, but the rule should mean an open row or a row covering D, not any row. None of the 30 rows reaches D, so the swap's from-D policy is unaffected.
- 185-35: no change to the Tradier fired-run checks. The study and its evidence are reproducible with `scripts/research/vendor_basis_study.py`.
- 185-42: nothing to delete from this plan. `ops_source_policy.py` stays as the single writer, and the study script is research tooling for the 185-43 census.
- 185-43: count `scripts/research/vendor_basis_study.py` in the census (kept as the doc's reproduction). Logs under `logs/185-37/` are evidence for the 30 rows.
- 186-26: 31 names still block vendor_basis_run, and 28 of them carry false returns of log 0.5 to 3.2 at a stale-basis boundary. Todo 508 is the gate.
- SIL's 276 refused IBKR head dates and VMRK's 2000-01-03 bar stay as they were. VMRK's date is under a closed row and cannot get another one.

## Known stubs

None.

## Threat flags

None beyond the register.
- T-185-37-01: every row carries evidence, and the CLI refused nothing.
- T-185-37-02: the rule was committed alone in a2d9ca6e1, before the script existed. The two narrowing deviations are labeled in the doc.
- T-185-37-03: the single_writer registry passes.

The study made outbound read-only HTTP requests to company investor-relations pages, two web search endpoints and the SEC full-text search index; none sent project data or the owner's contact details.

## Self-Check: PASSED
