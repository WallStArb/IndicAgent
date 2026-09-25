---
phase: 182-security-classification-hierarchy-todo-384
plan: 07
subsystem: database
tags: [classification, reference-data, migration, integration-tests, docs]

requires:
  - phase: 182-03
    provides: "migration 365 (rendered, reviewed, committed), render_node_guard_sql"
  - phase: 182-04
    provides: "onboarding classification gate"
  - phase: 182-05
    provides: "Instrument.sector from the level-2 node name"
  - phase: 182-06
    provides: "nightly ClassificationCoverageAuditor"
provides:
  - "indicagent_v1 live: 1 scheme, 118 nodes, 295 current assignments (every instruments row), valid_from 2026-09-25"
  - "tests/integration/test_classification_schema.py and test_instrument_classification_coverage.py (live DB, local-only)"
  - "docs/foundation/security-classification-hierarchy.md (canonical doc), CLAUDE.md SCH section"
  - "todo 384 closed"
affects: [stratification, peer-groups, onboarding, reporting]

tech-stack:
  added: []
  patterns:
    - "Live-DB integration tests run with --noconftest; writes only inside always-rolled-back transactions"

key-files:
  created:
    - tests/integration/test_classification_schema.py
    - tests/integration/test_instrument_classification_coverage.py
    - docs/foundation/security-classification-hierarchy.md
  modified:
    - docs/foundation/glossary.md
    - docs/research/stratification-security-classification-hierarchy.md
    - CLAUDE.md
    - .planning/todos/PRIORITIES.md
    - .planning/todos/completed/384-security-classification-hierarchy-build-trigger-already-fired.md
    - .planning/phases/182-security-classification-hierarchy-todo-384/deferred-items.md

key-decisions:
  - "Plan 03's approval precondition is met by the owner's recorded delegation of the review (182-CONTEXT D-06, 182-03-PLAN Task 3: 'i dont need to review i trust you'), not by a separate sign-off line in 182-03-SUMMARY"
  - "Todo 384's PRIORITIES row is dropped (completed-todo convention) and the phase 180 on-path line notes the closure"

requirements-completed: [D-01, D-05, D-06, D-07, D-08, D-09, D-10, D-11]

duration: 20min
completed: 2026-09-25
---

# Phase 182 Plan 07: Apply indicagent_v1 live, integration tests, docs, close todo 384 Summary

**Migration 365 is applied to the live DB. All 295 `instruments` rows carry a current `indicagent_v1` assignment dated 2026-09-25, and the coverage audit reports 0 uncovered active instruments. `get_active_contracts()` returns real level-2 sector names. Thirteen live-DB integration tests pass. The system is documented beside its sibling registries, and todo 384 is closed.**

## Performance

- **Duration:** about 20 min
- **Tasks:** 3
- **Files:** 3 created, 6 modified

## Task 1: live apply (no file changes)

Preconditions, all held:
- Approval: the owner delegated the review on 2026-09-25 (182-CONTEXT D-06, 182-03-PLAN Task 3).
  The two-pass review record is 182-03-REVIEW.md.
- `.venv/bin/python -m src.config.classification_seed --check production/migrations/365_indicagent_v1_classification_seed.sql`
  exited 0. The file on disk had no diff against origin/main (bf59c072a).
- Live `instruments` symbol set equals the seed's: 295 vs 295, no difference in either direction.
- The classification tables were empty before the apply (0/0/0).

Applied with `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -v ON_ERROR_STOP=1 -f production/migrations/365_indicagent_v1_classification_seed.sql`,
exit 0. Output: `INSERT 0 1` scheme, `INSERT 0 118` nodes, `INSERT 0 295` assignments, NOTICE
"seed symbols absent from instruments (skipped): 0", every guard `DO` passed, `COMMIT`. The
migration file was already committed in Plan 03 (65d2d9a59, re-rendered in 17e3a90e6) and was
not changed, so this task has no commit of its own.

Live verification after the apply:

| Check | Result |
|---|---|
| Active instruments without a current row | 0 |
| Current rows vs `instruments` rows | 295 / 295 |
| `min(valid_from)` / `max(valid_from)` | 2026-09-25 / 2026-09-25 (apply date, UTC) |
| `classification_scheme` | 1 row, authority `IndicAgent` |
| Nodes per level | 7 / 31 / 27 / 53 |
| source_ref (all / active) | ibkr_contract_details+review 168/168, fund_mandate 105/105, contract_spec 22/0 |
| `python -m src.config.classification_coverage` | Active 273, Uncovered 0, unclassified at L1 0, L2 0, L3 82, L4 94, PASS |
| `get_active_contracts(dimension='backfill')` | 273 instruments, 30 distinct sectors, all node names, no `indicagent_v1:unclassified` |

Spot checks (code, level, level-2 sector from `get_active_contracts`):

| Symbol | Code | Level | Sector |
|---|---|---|---|
| NVDA | EQ.IT.SEMI.EQUIP | 4 | Information Technology |
| JPM | EQ.FIN.BANKS.BANKS | 4 | Financials |
| XLK | EQ.IT | 2 | Information Technology |
| SPY | EQ.BROAD | 2 | Broad market (multi-sector) |
| TLT | FI.RATES | 2 | Government rates |
| GLD | CMD.PREC | 2 | Precious metals |
| CCJ | EQ.MAT.MATERIALS.METALS | 4 | Materials |
| RSPG | EQ.EN.ENERGY | 3 | Energy |
| SMH | EQ.IT.SEMI.EQUIP | 4 | Information Technology |

## Task 2: live-DB integration tests

`tests/integration/test_classification_schema.py` (7 tests, D-01/D-03): PK columns, the
current-row partial unique index and its predicate, RESTRICT on the instruments FK, node self-FK
and PK, a rolled-back second current row for SPY raising `UniqueViolationError`, the
immutability guard raising `RaiseError` for `EQ.IT.SEMI` under `EQ.HC` and passing under its
true parent `EQ.IT`, path equal to the rebuilt parent chain, and no scheme naming GICS.

`tests/integration/test_instrument_classification_coverage.py` (6 tests): D-09 coverage, D-06
source_refs, the D-07 build-date floor, D-05 depth (all single names at level 4; SPY, XLK, SMH),
the D-08 `ClassificationService` round trip including the pre-build as-of lookup, and D-10
`get_active_contracts` sectors equal to the level-2 node name for every active instrument.

`.venv/bin/pytest tests/integration/test_classification_schema.py tests/integration/test_instrument_classification_coverage.py -m integration --noconftest -q`:
13 passed. The current-row count was 295 before and after the run.

These tests are local-only and are not GitHub-CI-enforced. CI runs `tests/unit/` with no
database. They need `--noconftest` until todo 413 fixes the integration conftest's scratch-DB
rebuild. The enforcement that runs automatically is the seed guard, the onboarding gate and the
nightly coverage audit.

## Task 3: docs and todo closure

- New `docs/foundation/security-classification-hierarchy.md` covers:
  - why this is a third registry, separate from ITR and CVR
  - the three tables and their invariants
  - no history before 2026-09-25
  - `indicagent_v1`: levels, not GICS, source_ref table, depth rule, geography and style not levels
  - the read layer, the three enforcement points and the local-only integration tests
  - how to reclassify, add a node or onboard an instrument
  - Layer 2, which is not built
- Glossary `classification scheme`: status built, code surface filled in, and a note that
  `indicagent_v1` is not GICS.
- The design doc has a dated "Built" header line.
- CLAUDE.md has an SCH section after CVR.
- Todo 384 moved to `completed/` with a closure note. Its PRIORITIES row is dropped, and the
  phase 180 line now reads "384 closed 2026-09-25 by phase 182".
  `tests/unit/test_todo_priorities_link_integrity.py` passes.

## Task Commits

1. **Task 1: apply migration 365 live** - no commit (DB-only; the file was already committed in 65d2d9a59/17e3a90e6)
2. **Task 2: live-DB integration tests** - `f15f6f9d1` (test)
3. **Task 3: docs and todo 384 closure** - `2f651f13c` (docs)

## Deviations from Plan

None to the work itself. Task 1 changed no files, so it has no per-task commit.

## Deferred Issues

Recorded in deferred-items.md, not fixed here:
- RSPG's `instruments.contract_details` name and `sector` are stale. The fund has been Equal
  Weight Energy since 2023; the classification is already correct.
- VIX and VX are duplicate inactive rows for the same CFE future.
- The integration tests need `--noconftest` until todo 413 is fixed.

## Known Stubs

None.

## Next Phase Readiness

Phase 182's goal holds end to end in the live DB. The orchestrator owns STATE.md and ROADMAP.md.

---
*Phase: 182-security-classification-hierarchy-todo-384*
*Plan: 07*
*Completed: 2026-09-25*

## Self-Check: PASSED

All created files are present, and commits f15f6f9d1, 2f651f13c, 65d2d9a59 and 17e3a90e6 are in git.
