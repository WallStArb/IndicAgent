---
status: pending
priority: P2
filed: 2026-10-27
source: plan 184-04 (B1k read boundary, 184-REVIEWS row 18)
gate: none for deletion; a migration to the runner needs 184-08 (S0 feature read wired into build_panel)
---

# Remove the legacy feature_vectors research readers

## What

`tests/unit/test_feature_vectors_read_boundary.py` allow-lists every file that reads
`feature_vectors`. Three entries are pre-184 readers that put stored features against returns
outside the research runner, so a result they produce is an uncounted look (unified design
section 12.2): it never enters the attempt ledger and carries no multiplicity charge.

- `scripts/research/feature_matrix.py` (two-pass feature-matrix fetch, plan 186-04; test
  `tests/unit/scripts/test_research_feature_matrix.py`).
- `scripts/research/todo445_5m_incremental_ic.py` (the todo 445 5m-versus-15m incremental IC
  question; test `tests/unit/test_todo445_5m_incremental_ic.py`).
- `scripts/ops/corpus/ops_oos_holdout_eval.py` (holdout evaluation of feature columns against
  forward opens).

New files fail closed: the allow-list is per file, so a new reader under `scripts/research/`
fails CI even beside these entries. The risk this todo closes is the old scripts staying
runnable.

## Plan

1. For each script, check whether any live process or doc still depends on it
   (`grep -rn <module> scripts src services tests docs`).
2. Delete it with its test, or, if its question is still open, re-express it as a runner spec
   that reads features through S0 (`src/intelligence/research/feature_inputs.py`, wired by
   184-08) so the look is counted.
3. Drop its allow-list entry in the same commit (the stale-entry test enforces this).

## Done when

No `scripts/research/` entry remains in the boundary test's allow-list and the holdout-eval
entry is gone; then this file moves to `completed/` (the boundary test requires a pending removal
todo only while a legacy entry exists).
