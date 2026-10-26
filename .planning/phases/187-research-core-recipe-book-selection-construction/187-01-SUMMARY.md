---
phase: 187-research-core-recipe-book-selection-construction
plan: 01
status: complete
completed: 2026-10-26
commits: [c1e44863f]
requirements: [R-187-01, R-187-03, R-187-24]
---

# 187-01 summary: research attempt schema (migration 515)

- `concept_recipe` created, append-only (UPDATE, DELETE, TRUNCATE refused), unique
  `(concept_id, version)` and unique `recipe_hash`.
- `research_run` gained `recipe_hash` and `informed_by` (frozen at insert) and eight headline
  columns (NULL at insert, set once at the terminal update); `mode` accepts `exploration`,
  `kind` accepts `pod_book` and `legacy_verdict`; the budget check now binds `book_test` only.
- `research_run_series` created: `sessions date[]`, `d_s float8[]`, equal non-zero lengths,
  insert-only, parent must be terminal as completed or failed.
- FK indexes: `concept_registry.parent_concept_id`, `research_run.concept_id`,
  `research_run.informed_by`, `concept_recipe.concept_id`, `instrument_classification.scheme`.

Verification: contract test `tests/unit/research/test_attempt_schema_contract.py` (7 tests);
live guard proofs (series before terminal, second headline write, series update, recipe
delete, headline at insert: all refused) ran in one rolled-back transaction on the live DB;
the 21 existing rows hash identically on every pre-515 column before and after apply.

Deviation: the plan's `tests/integration/test_attempt_schema_live.py` was not written. The
integration harness replays migrations into `indicagent_test`, which todo 429 records as broken
since migration 322, so the live rolled-back proof above replaces it. Migration number moved
from 514 to 515 (514 landed from another session meanwhile).
