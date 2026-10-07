---
phase: 185-daily-data-foundation
plan: 29
subsystem: data-integrity
tags: [d0, label-inputs, handoff, lineage, policy-as-of, verdict-as-of]
requires: [185-16, 185-33, 185-36]
provides:
  - "LabelInputs.d2_rule_version from canonical_bar_lineage (sorted distinct, comma-joined)"
  - "LabelInputs.policy_as_of and verdict_as_of"
  - "todo 501: apply the S0 hand-off (phase 183 research lane)"
affects: [185-VERIFICATION re-verification, research lane resumption]
key-files:
  modified:
    - src/intelligence/bars/label_inputs.py
    - tests/unit/bars/test_label_inputs.py
    - .planning/phases/185-daily-data-foundation/185-S0-HANDOFF.md
    - .planning/phases/185-daily-data-foundation/185-CONTEXT.md
    - .planning/todos/PRIORITIES.md
  created:
    - .planning/todos/pending/501-apply-185-s0-data-quality-handoff-in-snapshot-and-runner.md
decisions:
  - "Non-1d timeframes keep the bar_derivation_batch read (grid rule); only 1d reads lineage"
  - "Verdict as-of reads integrity_monitor subjects SYM|tf for bar_integrity; policy as-of takes symbol rows plus the timeframe default overlapping the span"
metrics:
  completed: 2026-10-07
---

# Phase 185 Plan 29: D0 label inputs, hand-off, CONTEXT answers Summary

Label inputs now name every canonical rule behind a panel's 1d bars and record the policy and verdict state they were built under; the S0 hand-off is current and owned by todo 501.

## D-04 stays unmet

D-04 is not met by this plan or at phase close. It is met only when the phase 183 research lane applies `185-S0-HANDOFF.md` (todo 501). Re-verification must carry an explicit override line for D-04 that names todo 501. 185-CONTEXT.md states the same.

## Commits

- a9797f1b7: label inputs read canonical_bar_lineage, add policy_as_of and verdict_as_of (tests first, fake connection)
- 69a0306a7: hand-off refresh, todo 501, PRIORITIES row, CONTEXT answers

## Tests

- `tests/unit/bars/test_label_inputs.py` and `test_labels.py`: pass. `tests/unit/bars` plus `tests/unit/test_todo_priorities_link_integrity.py`: pass. ruff and black clean on touched files. No live DB write; no file under `src/intelligence/research/` touched, so no repro_frozen run.

## New todo

501, P0, owner phase 183 research lane. PRIORITIES.md diff is a single added row (edited via scratch copy), placed in the P0 table above the research section that holds todo 442.

## Deviations from plan

- **CONTEXT owner answers (judgment call).** The plan says to cite "owner chat answers". The executor has no record of that chat, and the instructions say an answer without a findable source belongs under orchestrator calls. Owner decisions are therefore only those with a written record naming the owner (success criterion 8: ROADMAP exit notes; design approval and fetcher stop: memory; D1 mutable and Tradier primary: existing owner section). The legacy D1 deletion of 3,850,642 rows and the "todos 495, 497, 433 not blockers, 490 fixed" answer are listed under "Orchestrator calls, pending owner review". Consequence: `grep -c "source: owner chat answers"` returns 0 (no bullet claims that source). The owner can promote those two items on confirmation.
- The hand-off's Status text and pinning paragraph were extended (symbols, policy_as_of, verdict_as_of, verdicts read) to match todo 501's done-when.
- New todo file needed `git add -N` before the pathspec commit.

## Known stubs

None.

## Self-Check

Files exist: label_inputs.py, test file, todo 501, hand-off, CONTEXT. Commits a9797f1b7 and 69a0306a7 are in `git log`.

Self-Check: PASSED
