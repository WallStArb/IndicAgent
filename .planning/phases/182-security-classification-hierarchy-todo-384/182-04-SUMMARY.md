---
phase: 182-security-classification-hierarchy-todo-384
plan: 04
subsystem: database
tags: [classification, onboarding, asyncpg, transaction, reference-data]

# Dependency graph
requires:
  - phase: 182-01
    provides: "classification_scheme / classification_node / instrument_classification tables (migration 364), ClassificationAssignment, DEFAULT_SCHEME, SOURCE_REF_* constants"
provides:
  - "onboard_instrument() requires classification=ClassificationAssignment with no skip escape hatch (D-09)"
  - "onboard_instrument() writes instrument_classification inside its existing transaction, after the instruments insert (D-07)"
  - "onboard_instrument() no longer writes contract_details.sector (D-10)"
  - "load_classifications() CSV parser + --classification-csv flag for universe_expansion_stratified_sourcing.py"
  - "EMLC -> FI.EM / VIXY -> VOL.EQUITY pinned in universe_expansion_onboard_gap_fill_etfs.py"
affects: [182-05, 182-06, 182-07]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "No-skip-escape-hatch required-argument gate, mirroring the existing metadata/metadata_skip_reason pair in the same function but deliberately without a skip parameter"
    - "Node-existence check via SELECT 1 ... WHERE valid_to IS NULL before the write it gates, same shape as the tag-vocabulary check two lines above it"
    - "Pre-write-loop pre-check (missing classifications) that aborts a bulk caller before any network connection or DB write, not partway through"

key-files:
  created: []
  modified:
    - src/config/instrument_onboarding.py
    - tests/unit/config/test_instrument_onboarding.py
    - scripts/infrastructure/universe_expansion_onboard_gap_fill_etfs.py
    - scripts/infrastructure/universe_expansion_stratified_sourcing.py
    - tests/unit/scripts/test_universe_expansion_stratified_sourcing.py

key-decisions:
  - "classification=None raises ValueError directly after the existing metadata check, before the qualifier runs -- matches the plan's specified check ordering exactly, no reordering needed."
  - "Node-existence check placed after the tag-vocabulary check and before the instruments insert (inside the transaction), so an unregistered tag is still reported as a tag error even when the classification code is also bad -- existing tag-rejection tests kept their original failure mode."
  - "instrument_classification INSERT has no ON CONFLICT: a brand-new symbol cannot already have a row, and any unique-violation must surface rather than be silently absorbed."
  - "FakeConnection's default known_codes={'EQ.IT.SEMI'} (mirroring known_tags' empty-set default) means every existing test that doesn't care about the node gate passes it without extra setup, while _SOME_CLASSIFICATION pins the same code as the fixture's default so both stay in sync."

requirements-completed: [D-09, D-10, D-06, D-07]

# Metrics
duration: 20min
completed: 2026-09-25
---

# Phase 182 Plan 04: Classification-required onboarding gate (D-09) and sector write retired (D-10) Summary

**`onboard_instrument()` now hard-fails without a `ClassificationAssignment` (no skip escape hatch), writes `instrument_classification` inside its existing transaction, and both onboarding callers pin their classifications explicitly.**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-09-25T11:03Z (approx, first file read)
- **Completed:** 2026-09-25T11:12:45-04:00 (last commit)
- **Tasks:** 2 (Task 1 split RED/GREEN per its `tdd="true"` flag)
- **Files modified:** 5

## Accomplishments

- `onboard_instrument()` raises `ValueError` naming D-09/todo 384 the instant `classification=None` reaches it, before the qualifier call and before any statement is issued -- there is no `classification_skip_reason` parameter anywhere (grep-verified empty).
- A classification code that is not a current `classification_node` row (`valid_to IS NULL`) is rejected via `OnboardingRejected` before the `instruments` insert; the check runs after the existing tag-vocabulary check and inside the same transaction.
- The happy path writes exactly one `INSERT INTO instrument_classification` with `(symbol, indicagent_v1, code, today's UTC date, source_ref)`, strictly after the `instruments` insert in `conn.statements`' order -- verified by an explicit index-ordering assertion, not just a count.
- `contract_details` no longer carries a `sector` key: `_CONTRACT_DETAILS_KEYS` dropped to nine keys, `grep -n '"sector"' src/config/instrument_onboarding.py` returns nothing.
- `OnboardResult.classification_code` reports the code that was assigned.
- `universe_expansion_onboard_gap_fill_etfs.py` pins `EMLC -> FI.EM` and `VIXY -> VOL.EQUITY` (both `fund_mandate`), matching Plan 03's reviewed seed exactly, as the fourth element of its existing per-instrument tuple.
- `universe_expansion_stratified_sourcing.py` adds `--classification-csv PATH` (argparse error when `--commit` is given without it), a pure `load_classifications()` parser (duplicate-symbol and bad-source_ref both raise `ValueError`, the latter via `ClassificationAssignment`'s own validation), and a missing-symbol pre-check in `_run_commit()` that raises `RuntimeError` naming every unclassified sampled symbol before the gateway pre-flight probe runs -- proven by a test that monkeypatches `_gateway_preflight` and asserts it was never called.
- 25 tests in `test_instrument_onboarding.py` (16 existing + 9 new/extended) and 4 new tests in `test_universe_expansion_stratified_sourcing.py` all green; full `tests/unit/ -q` suite green (2 pre-existing, unrelated skips only, same baseline as Plan 01).

## Task Commits

1. **Task 1 RED: failing tests for classification-required onboarding gate** - `906e012c4` (test)
2. **Task 1 GREEN: classification-required onboarding gate, sector write retired** - `5d2bce364` (feat)
3. **Task 2: wire both onboarding callers to the required classification argument** - `5dca29fa8` (feat)

**Plan metadata:** (this commit, docs: complete plan)

## Files Created/Modified

- `src/config/instrument_onboarding.py` - `classification` keyword-only arg + no-skip ValueError gate, node-existence check, `instrument_classification` insert inside the transaction, `sector` dropped from `_CONTRACT_DETAILS_KEYS`, `OnboardResult.classification_code`
- `tests/unit/config/test_instrument_onboarding.py` - every call site updated with `classification=`, plus 3 new tests (None-raises, unknown-code-rejected, no-sector-key) and ordering/args assertions on the happy path
- `scripts/infrastructure/universe_expansion_onboard_gap_fill_etfs.py` - `_EMLC_CLASSIFICATION`/`_VIXY_CLASSIFICATION` constants, threaded through the per-instrument tuple and `onboard_instrument()` call
- `scripts/infrastructure/universe_expansion_stratified_sourcing.py` - `load_classifications()`, `--classification-csv` flag + argparse gate, `_run_commit()`'s missing-symbol pre-check, `classification=` passed per symbol
- `tests/unit/scripts/test_universe_expansion_stratified_sourcing.py` - `load_classifications()` tests (valid/duplicate/bad source_ref) and the missing-classification pre-check test

## Decisions Made

See key-decisions in the frontmatter.

## Deviations from Plan

None - plan executed exactly as written. The one grep-format wrinkle (the acceptance
criterion's literal `grep -n '"sector"'` also matched the module's own explanatory
comment on first pass) was caught before committing and fixed by rephrasing the
comment without quoting the word -- not a deviation from the plan's intent, just a
self-check on the exact command the plan specifies.

## Issues Encountered

None.

## Known Stubs

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 05/06 (ClassificationService consumers) are unaffected by this plan's scope -- onboarding is a write path, not a read path.
- Plan 07 (applies migration 365) is unaffected: this plan only gates the *code* path for future onboarding, it does not touch the seed migration or the live schema.
- Both onboarding callers now satisfy the D-09 gate; a future bulk caller (e.g. a Plan-12-style run) must supply `--classification-csv` and will abort loudly, before any write, on any sampled symbol missing a row.

---
*Phase: 182-security-classification-hierarchy-todo-384*
*Plan: 04*
*Completed: 2026-09-25*
