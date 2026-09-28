---
phase: 185-daily-data-foundation
plan: 08
subsystem: bars
tags: [d0-labels, survivorship-bound, apr-seeds, pure-functions, d-04]

# Dependency graph
requires: [185-01]
provides:
  - src/intelligence/bars/labels.py: venue_truncation_share, dividend_label, scrub_flag_share, delisting_sensitivity, survivorship_bound, SurvivorshipRule.from_apr, DataQualityLabels.to_manifest, build_labels (the D0 label arithmetic; pure, no DB)
  - production/migrations/382_survivorship_bound_apr.sql: six alpha.survivorship.* APR seeds (Shumway 1997 / Shumway and Warther 1999), applied live 2026-09-28
affects: [185-16, 186]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Labels describe exposure and never gate a verdict: the module docstring pins D-04's bound-beside-the-statistic reading so no future caller turns a label into a filter"
    - "APR isolation: SurvivorshipRule.from_apr reads a caller-supplied mapping of full dotted keys; the pure module never touches the config service, so the label functions stay testable without a database"

key-files:
  created:
    - src/intelligence/bars/labels.py
    - production/migrations/382_survivorship_bound_apr.sql
    - tests/unit/bars/test_labels.py
  modified: []

key-decisions:
  - "expected_delisting_drag_annual is the hazard-weighted expected |delisting return| loss on GROSS exposure (a flat long/short with equal exchange mix has sensitivity 0 but still carries drag: each side's names can delist); without weights it is the conservative exchange's hazard x |return| at unit exposure (nasdaq under the seeds)"
  - "haircut_annual scales the literature haircut by the attempt's small_cap_share, so the bound sizes this attempt's exposure rather than the universe's"
  - "Unknown exchange codes map to the nasdaq bucket on purpose: its seeds (0.056 x -0.55) dominate NYSE/AMEX (0.012 x -0.30), so an unmapped exchange overstates the bound instead of understating it"
  - "SurvivorshipRule.__post_init__ mirrors migration 382's config_schema ranges (returns [-1, 0], hazards/haircut [0, 1]), so a value that escaped the schema is refused in code too"
  - "The three share functions report 0.0 on empty inputs (documented): an attempt with zero cells has no measured exposure; the per-attempt caller (plan 16) always has cells"
  - "ISLAND/NASDAQ vs NYSE/AMEX/ARCA/BATS routing codes are mirrored as module constants, same discipline as venue_study.py (the pure module must not import the provider)"

patterns-established:
  - "Label manifests convert every scalar to a plain python type before leaving the dataclass (to_manifest), so json.dumps round-trips without numpy leaking into recorded evidence"

requirements-completed: [D-04]

# Metrics
duration: under 0.5 h including context read and self-review
completed: 2026-09-28
---

# Plan 185-08: D0 label arithmetic and survivorship APR summary

**The four D0 labels are computed by tested pure functions (venue share 0.2 on a 2-of-10 moved panel, 7-of-1000 flagged cells = 0.007, a full Nasdaq long pins sensitivity at 0.056 x -0.55), the manifest block round-trips through json.dumps carrying the D2 rule version, and the six Shumway literature seeds are live APR keys**

## Performance
- **Duration:** under 0.5 h (task 1 RED/GREEN, migration apply + commit, simplify refactor, full suite)
- **Completed:** 2026-09-28
- **Tasks:** 2

## Acceptance verified
- tests/unit/bars/test_labels.py green (16 tests); full `.venv/bin/pytest tests/unit/ -q` exit 0 with only the 2 pre-existing unrelated skips (same set 185-07 recorded)
- `grep -nE "asyncpg|psycopg|src.intelligence.research" src/intelligence/bars/labels.py` returns nothing (pure module; the read helper is plan 16's job)
- 6 alpha.survivorship.* keys live in config_state (verified with a count query before the commit); `grep -c "ASSUMED"` on the migration returns 5 (>= 2 required); config_schema carries min/max bounds on all six keys
- tests/unit/test_migration_number_uniqueness.py green; migration 382 applied live with ON_ERROR_STOP and committed in the same step
- Nothing under src/intelligence/research/ or src/intelligence/statistics/ touched; no todo 449 lane scripts, no logs/backfill_ops/

## Task commits
1. **Task 1 RED: D0 label behaviors** - `7db4fcf63`
2. **Task 1 GREEN: labels.py** - `6eb56524b`
3. **Task 2: migration 382 survivorship APR seeds (applied live, same-step commit)** - `89a319955`
4. **Self-review cleanup: one per-name delisting impact helper** - `9ad29e67e`

**Plan metadata:** this commit

## Deviations from plan
- The plan names `expected_delisting_drag_annual` without defining it: implemented as the gross-exposure hazard-weighted expected |delisting return| (with weights) and the conservative exchange's hazard x |return| at unit exposure (without), documented in the SurvivorshipBound docstring; `sensitivity` stays the signed book-level number the plan's formula defines
- `haircut_annual` is small_cap_share x haircut_small_cap_annual (the bound scales to the attempt's small-cap exposure); the plan's "literature haircut plus delisting-return sensitivity" phrasing left the scaling open
- Loud-crash validation added beyond the named behaviors: dividend_label refuses non-boolean coverage dtype (a coerced integer mask would silently mislabel), scrub_flag_share refuses non-1-D key arrays, delisting_sensitivity validates shape, name-axis length, finiteness and T >= 1, survivorship_bound refuses weights without exchange_of and small_cap_share outside [0, 1], and SurvivorshipRule.__post_init__ enforces the migration's schema ranges
- Empty inputs (no cells, no coverage, no flagged keys) report 0.0 shares rather than raising; documented per function as "no measured exposure"
- The manifest round-trip test also asserts the computed values inside the block (venue 0.2, uncovered 0.15, scrub 0.007), not just the key set

## Issues encountered
- None.

## User setup required
None.

## Next phase readiness
- Plan 16 builds the DB read helper that feeds build_labels (moved symbols from the venue-move inventory, div_covered from the DividendGrid, flagged keys from bar_quality_flag, exchanges from instruments) and attaches DataQualityLabels.to_manifest() to the S0 manifest and S6 evidence; every keyword argument it needs already exists
- The bound's two [ASSUMED] values (Shumway 1997 -0.30, small-cap haircut 0.015) are disclosed in their APR descriptions and every future change lands in config_history (T-185-08-01); schema bounds refuse out-of-range edits (T-185-08-02)
- D-28's minimum data bar gains its survivorship-bound leg once plan 16 wires the labels into attempt recording

## Self-Check: PASSED
All three key files present on disk; all four task commits found in git log; 6 APR keys verified live before the migration commit.

---
*Phase: 185-daily-data-foundation*
*Completed: 2026-09-28*
