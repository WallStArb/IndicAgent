---
phase: 175-itr-materiality-filtered-empirical-tags-for-breadth-peer-gro
plan: 04
subsystem: analytics
tags: [python, statistics, itr, shadow-mode, diagnostic, read-only]

# Dependency graph
requires:
  - phase: 175-01
    provides: instrument_tags eleven Pass 4 evidence columns, instrument_tags_active view, discovery_state CHECK constraint, eleven alpha.tag_calibrator.materiality.* APR keys (migration 346)
  - phase: 175-03
    provides: is_materiality_eligible (canonical read-time predicate), MaterialityConfig, decide_materiality, measure_partial_loadings (services/tag_calibrator.py Pass 4)
provides:
  - "scripts/analysis/itr_materiality_shadow_diagnostic.py: read-only D-03 shadow-mode diagnostic reporting membership delta, gate attribution, and near-miss distributions for all four enabled regime groups"
  - "First live measured evidence: TagCalibrator's Pass 4 run against the real corpus (2170 empirical pairs measured, 222 passing the statistical gate, 0 symbols currently admitted to any group)"
affects: [175-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Split a single-file two-task plan into two commits by extracting a truncated Task-1-only file version (pure functions + minimal imports), verifying it independently (pytest+ruff), committing, then restoring the full file for Task 2's commit -- used because both tasks target the same file and the DB-layer/report code was written together with the pure functions for efficiency."
    - "null_arm gate reconstructed at read time from persisted null_arm_bh_p <= null_arm_alpha rather than the transient null_arm_passes_fdr boolean tag_calibrator.py computes in-run -- statsmodels' multipletests(method='fdr_bh') reject array is exactly p_corrected <= alpha for this method, so the reconstruction is exact, not an approximation."

key-files:
  created: [scripts/analysis/itr_materiality_shadow_diagnostic.py, tests/unit/test_itr_materiality_shadow_diagnostic.py]
  modified: []

key-decisions:
  - "The plan's <interfaces> section names a _load_group_configs(cfg) helper on services/cross_sectional_regime_model.py that does not exist in the live file -- the actual function is _parse_group_configs(raw), which takes the already-fetched raw JSON (string or already-parsed list), not a ConfigService instance. Adapted: import _parse_group_configs and _DEFAULT_GROUPS_JSON, call cfg.get_sync('alpha.regime.groups', _DEFAULT_GROUPS_JSON) then _parse_group_configs(raw_groups) -- the exact two-step sequence main() itself uses. Same read-only-reuse intent as the plan specified, correct function name."
  - "attribute_gate_failures/sign_stability_near_miss both gate on is_materiality_eligible(row) (the persisted three-gate conjunction) to determine the non-eligible population, not a live re-derivation of decide_materiality's six conditions against freshly-loaded thresholds. This matches D-02's single-source-of-truth intent (one measurement engine, N read-time cutoffs) and is safe because Task 3's workflow runs TagCalibrator immediately before the diagnostic, so persisted passes_materiality/discovery_state are current against the same thresholds this run reads."
  - "gate_value_distributions reports the raw signed partial_loading value (not abs()) for the partial_loading gate's failing-row distribution -- literally 'the failing rows' own statistic value' per the plan's wording, avoiding an extra transformation the plan did not specify."

requirements-completed: [P175-03, P175-06, P175-07]

# Metrics
duration: ~55min
completed: 2026-09-23
---

# Phase 175 Plan 04: ITR Materiality Shadow Diagnostic Summary

**Built and ran the D-03 shadow-mode diagnostic: a read-only script reporting what breadth/peer-group membership would change under a materiality-filtered admission rule, then ran it against the real corpus for the first time -- zero symbols currently qualify, the min_partial_loading and incremental_r2 gates are the binding constraints, and the report's near-miss section is now the evidence base for any future threshold recalibration.**

## Performance

- **Duration:** ~55 min
- **Completed:** 2026-09-23
- **Tasks:** 3
- **Files created:** 2 (scripts/analysis/itr_materiality_shadow_diagnostic.py, tests/unit/test_itr_materiality_shadow_diagnostic.py)

## Task 0: Worktree base correction

The worktree's HEAD was found sitting on a stale, unrelated commit chain (`525cdae6d`, migration-346-renumbering / max_cell_rows fixes) that was an ancestor of, but not equal to, the orchestrator-specified wave base `31832cfc1`. Per the mandated `worktree_branch_check` protocol this is an explicit, authorized correction (not a self-decided destructive operation): `git reset --hard 31832cfc1` was run, HEAD verified to land exactly on the expected commit, and execution proceeded from there. `.venv` was also missing (known GSD worktree gotcha, `.venv` is gitignored) -- symlinked to the main repo's `.venv` so pytest/ruff/black could run.

## Accomplishments

- `build_tag_arms`, `membership_delta`, `attribute_gate_failures`, `sign_stability_near_miss`, and `gate_value_distributions` -- five pure functions, no DB/I/O, importing `is_materiality_eligible` from `services.tag_calibrator` and `_resolve_group_symbols` from `services.cross_sectional_regime_model` rather than re-deriving either (D-02's "one measurement engine, N read-time cutoffs")
- 26 unit tests covering the todo-125 temporal gate (`pending_oos` row excluded from both arms), the todo-126 expiry gate (`valid_to` set excludes even a confirmed+passing row, asserted in code even though the view already filters it), `source='ai'` exclusion, prefix-matching delegation, the `removed`-always-empty invariant, per-gate failure attribution with a distinct `sole_failure` count, the sign-stability near-miss histograms (including the `(2, 4)`-fails-by-one-window / `(3, 3)`-passes boundary case), and `gate_value_distributions`' NaN-never-coerced-to-zero contract
- Read-only DB layer: `_fetch_active_tag_rows` reads through `instrument_tags_active` (never a bare `instrument_tags` read), `_fetch_live_baseline` reproduces `cross_sectional_regime_model._load_tags_by_symbol`'s stopgap query byte-for-byte on a single line (grep-verifiable), and `_detect_baseline_drift` cross-checks the two -- confirmed to agree exactly on the live corpus (zero `BASELINE DRIFT` in the actual run output)
- `main()` prints MEMBERSHIP DELTA (per enabled regime group), GATE ATTRIBUTION (with `sole_failure` counts), and NEAR MISS (both sign-stability histograms plus per-scalar-gate order statistics) sections, closes with a SHADOW MODE banner restating that no consumer query changed
- Static read-only grep gate (`grep -cE '^[^#]*\b(INSERT|UPDATE|DELETE|CREATE|DROP|ALTER)\b'`) returns 0 against the finished file
- Ran `TagCalibrator` against the live corpus for the first time since Pass 4 landed (plan 03) -- populated all eleven `instrument_tags` evidence columns for 2170 empirical pairs, then ran the diagnostic against that live data and captured the full report verbatim below
- `market_regimes` row count and `max(ts)` confirmed byte-identical before and after both the `TagCalibrator` run and the diagnostic run -- proves D-03's shadow-mode boundary held mechanically, not just by inspection

## Task Commits

1. **Task 1: Pure membership-delta and gate-attribution logic** - `1bb426d8c` (feat) -- committed as a truncated Task-1-only file (pure functions + minimal imports only; the DB-layer/report code, though already drafted, was excluded from this commit and re-added in Task 2's commit so the two tasks land as genuinely separable diffs)
2. **Task 2: Read-only data layer, dual-baseline cross-check, and report output** - `03988631f` (feat)
3. **Task 3: this SUMMARY.md** (docs commit, see below)

## Files Created

- `scripts/analysis/itr_materiality_shadow_diagnostic.py` - the D-03 shadow-mode diagnostic: `build_tag_arms`/`membership_delta`/`attribute_gate_failures`/`sign_stability_near_miss`/`gate_value_distributions` (pure), `_fetch_active_tag_rows`/`_fetch_live_baseline`/`_detect_baseline_drift`/`_fetch_materiality_thresholds` (read-only DB layer), `main()` (report)
- `tests/unit/test_itr_materiality_shadow_diagnostic.py` - 26 tests, pure-function/no-DB style matching `test_tag_calibrator.py`'s convention

## Decisions Made

- **Interface correction (blocking, Rule 3):** the plan's `<interfaces>` block names `_load_group_configs(cfg) -> list[dict]` as an existing function on `services/cross_sectional_regime_model.py`. Live-verified via `grep -n "^def " services/cross_sectional_regime_model.py`: no such function exists. The actual function is `_parse_group_configs(raw: str | list[dict]) -> list[dict]`, which takes the already-fetched raw JSON value (not a `ConfigService`), used in the live `main()` as `cfg.get_sync("alpha.regime.groups", _DEFAULT_GROUPS_JSON)` followed by `_parse_group_configs(raw_groups)`. Adapted the diagnostic to import `_parse_group_configs` and `_DEFAULT_GROUPS_JSON` and reproduce that exact two-step sequence -- same read-only-reuse intent the plan specified (reuse the live group-config resolution, never reimplement it), just the correct names.
- **Eligibility population for gate attribution:** `attribute_gate_failures`/`sign_stability_near_miss` scope their "non-eligible" population via `is_materiality_eligible(row)` (the persisted three-gate conjunction: statistical + temporal + expiry), not a live re-derivation of `decide_materiality`'s six statistical conditions alone. This is D-02-consistent (one canonical predicate, reused everywhere) and safe under this plan's own workflow (`TagCalibrator` run immediately before the diagnostic, so persisted state is current).
- **Task-file split:** wrote the complete script (pure functions + DB layer + report) in one pass for implementation efficiency, then split it into a Task-1-only truncated version (verified independently green under pytest+ruff) for the first commit, restoring the full file for Task 2's commit -- preserves the plan's per-task commit granularity without redoing work.
- Kept the plan's exact SQL column list, thresholds dict key names, and report section labels (MEMBERSHIP DELTA / GATE ATTRIBUTION / NEAR MISS / SHADOW MODE) as specified.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking issue] `_load_group_configs` interface named in the plan does not exist**
- **Found during:** Task 2, reading `services/cross_sectional_regime_model.py` per the plan's own `<read_first>` instruction
- **Issue:** The plan's `<interfaces>` block specifies importing and calling `_load_group_configs(cfg) -> list[dict]`. `grep -n "^def " services/cross_sectional_regime_model.py` confirms this function does not exist anywhere in the file.
- **Fix:** Imported the actual function (`_parse_group_configs`) and the module's `_DEFAULT_GROUPS_JSON` default constant, and reproduced `main()`'s own two-step group-loading sequence (`cfg.get_sync("alpha.regime.groups", _DEFAULT_GROUPS_JSON)` then `_parse_group_configs(raw_groups)`) exactly.
- **Files modified:** scripts/analysis/itr_materiality_shadow_diagnostic.py
- **Verification:** the diagnostic's MEMBERSHIP DELTA section printed all four enabled regime groups (equity/rates/commodity/fx) correctly against the live `alpha.regime.groups` APR value in the Task 3 run below.
- **Committed in:** `03988631f` (Task 2)

---

**Total deviations:** 1 auto-fixed (Rule 3 - blocking interface mismatch)
**Impact on plan:** Necessary for correctness -- the plan's specified function name does not exist in the codebase; the fix preserves the exact intent (reuse the live group-config resolution read-only) with the correct name.

## Task 3: Live Run -- TagCalibrator + Shadow Diagnostic

### TagCalibrator confirmation (no ProcessPoolExecutor)

`grep -n "ProcessPoolExecutor" services/tag_calibrator.py` returns zero matches; `TagCalibrator(BaseBatch)` is a plain async oneshot. Confirmed before running -- the orphan-worker reap rule (CLAUDE.md) does not apply to this service.

### `TagCalibrator` run (`.venv/bin/python services/tag_calibrator.py`)

Run twice in immediate succession while confirming stdout/exit-code behavior (the process logs to `logs/tag_calibrator.log` via `structlog`, not stdout, so the first invocation's silent completion looked like a hang and was re-run to confirm; both runs succeeded, exit code 0, and the write path is idempotent -- the second run's `outcome_counts` show the first run's 22 `discovered` rows correctly re-classified as `kept` on the second pass, exactly the expected discovery-to-kept transition). Final `tag_calibrator.run_complete` log line (verbatim from `logs/tag_calibrator.log`):

```json
{
  "n_measured": 4856,
  "n_self_regression_skipped": 22,
  "n_insufficient_data_skipped": 36,
  "n_tags_not_measurable": 0,
  "outcome_counts": {
    "no_op": 2450,
    "kept": 2233,
    "confirmed_human": 94,
    "failing": 42,
    "contradiction": 35,
    "expired": 2
  },
  "n_factor_correlations_written": 153,
  "n_materiality_measured": 2263,
  "n_materiality_no_controls": 0,
  "n_materiality_insufficient_sample": 64,
  "n_passes_materiality": 222
}
```

### Column-population verification

```sql
SELECT count(*) FILTER (WHERE partial_loading IS NOT NULL) AS measured,
       count(*) FILTER (WHERE passes_materiality) AS passing,
       count(*) FILTER (WHERE discovery_state = 'pending_oos') AS pending_oos,
       count(*) FILTER (WHERE discovery_state = 'confirmed') AS confirmed
FROM instrument_tags WHERE source = 'empirical';
```

| measured | passing | pending_oos | confirmed |
|---------:|--------:|------------:|----------:|
| 2170     | 182     | 1764        | 469       |

(Before this run: all four counts were 0 -- this is the first live Pass 4 measurement since plan 03 shipped the code.)

### `market_regimes` before/after (D-03 mechanical proof)

```sql
SELECT count(*), max(ts) FROM market_regimes;
```

| When | count | max(ts) |
|------|------:|---------|
| Before TagCalibrator run | 5,354,790 | 2026-08-14 19:55:00+00 |
| After TagCalibrator run | 5,354,790 | 2026-08-14 19:55:00+00 |
| After diagnostic run | 5,354,790 | 2026-08-14 19:55:00+00 |

Byte-identical across all three checkpoints -- neither `TagCalibrator` nor the diagnostic touched this consumer table.

### Shadow diagnostic run (`.venv/bin/python scripts/analysis/itr_materiality_shadow_diagnostic.py`) -- verbatim output

```
Baseline cross-check OK: live stopgap query and view-derived arm agree exactly.

======================================================================
MEMBERSHIP DELTA (per enabled regime group)
======================================================================

[equity] signal_type=breadth_vol
  baseline: 103 symbols   candidate: 103 symbols
  ADDED (0): []

[rates] signal_type=curve_credit
  baseline: 17 symbols   candidate: 17 symbols
  ADDED (0): []

[commodity] signal_type=commodity_momentum_ts
  baseline: 27 symbols   candidate: 27 symbols
  ADDED (0): []

[fx] signal_type=fx_dollar_carry
  baseline: 12 symbols   candidate: 12 symbols
  ADDED (0): []

======================================================================
GATE ATTRIBUTION (non-eligible empirical rows)
======================================================================
  sample_n           count=    0   sole_failure=    0
  partial_loading    count= 1960   sole_failure=   84
  ci_low             count= 1786   sole_failure=    0
  incremental_r2     count= 1899   sole_failure=   27
  sign_stability     count=  565   sole_failure=    1
  null_arm           count=  584   sole_failure=    0
  unmeasured         count=  105
  never measured this run (passes_materiality IS NULL): 63

======================================================================
NEAR MISS
======================================================================
  sign-stability (sign_stable_windows, sign_stable_windows_total) -- ALL failing rows:
    (2, 4): 365
    (1, 4): 142
    (0, 4): 53
    (2, 3): 5
  sign-stability -- rows a sign-stability recalibration ALONE would admit (fail only this gate):
    (2, 4): 1
  Sliding bar: a symbol at the min_sample_n floor can only ever reach three evaluable windows and therefore needs 3-of-3 agreement, while a full-history symbol needs 3-of-4 -- deliberate and recorded in plan 03's R-07 resolution (services.tag_calibrator.decide_materiality's docstring), not a bug.
  sample_n           n=   0  n_unmeasured= 105  min=None  median=None  max=None
  partial_loading    n=1960  n_unmeasured= 105  min=-0.3475701616131825  median=0.04550933146127201  max=0.34878465200752806
  ci_low             n=1786  n_unmeasured= 105  min=-0.06142624430186203  median=0.029283630090999897  max=0.19952674951254804
  incremental_r2     n=1899  n_unmeasured= 105  min=2.338041649174727e-09  median=0.0031922550259606552  max=0.04988853830052209

======================================================================
SHADOW MODE
======================================================================
  No consumer query changed. breadth_vol.py and cross_sectional_regime_model.py still read source='human' only. Cutting either consumer over to the materiality-filtered arm is a separate, later phase gated on this report plus the D-07 cross-AI review and the user's own review.
```

`BASELINE DRIFT` occurrences in the run output: **0** (matches Task 3's automated verify command exactly).

### Reading the result

Zero symbols would currently be added to any of the four enabled regime groups under the materiality-filtered rule -- the `min_partial_loading` gate (`0.35`) is the dominant binding constraint (1960 of 2170 measured rows fail it, 84 failing on that gate alone), followed by `incremental_r2` (1899 failing, 27 sole) and `ci_low` (1786 failing, none sole -- every `ci_low` failure co-occurs with another gate's failure). `sign_stability` fails 565 rows but only 1 fails it alone, and the near-miss histogram shows the failure mass concentrated at `(2, 4)` (365 rows -- two of four windows sign-stable, one short of the `min_sign_stable_windows=3` bar) and `(1, 4)`/`(0, 4)` further out; essentially none of the sign-stability failures are close misses a small threshold adjustment alone would flip. 105 rows are `unmeasured` (a core Pass 4 statistic came back NaN/NULL -- typically an ill-conditioned control matrix or insufficient aligned observations), and 63 empirical rows were never measured this run at all (`passes_materiality IS NULL`, i.e. Pass 1-3 didn't keep them). The seeded `[initial_estimate]` thresholds (D-05, Codex's conservative proposal) are, on this first live measurement, conservative enough to admit nothing -- consistent with D-05's framing that these are unvalidated starting points, not the empirical result of any calibration exercise. This is the exact evidence gap the NEAR MISS section exists to fill for a future recalibration decision.

## Cross-AI review gate (D-07)

This report -- the verbatim GATE ATTRIBUTION and NEAR MISS sections above, not the diagnostic's source code -- is what Fable plus Codex/AGY must review next, per D-03/D-07. No consumer cutover (`breadth_vol.py`, `cross_sectional_regime_model.py`) may be planned or scoped until both that cross-AI review and the user's own review of this report have happened. The zero-symbols-added result and the binding-gate breakdown above are the primary inputs to that review; the finding that `min_partial_loading` and `incremental_r2` are jointly the dominant constraints (not `sign_stability`, which plan 03's R-07 discussion anticipated might be the contentious one) is itself worth flagging to reviewers as a finding that shifts where recalibration attention should go, if any.

## Issues Encountered

None beyond the interface-name deviation and the worktree-base correction documented above. Both `TagCalibrator` runs and the diagnostic run completed cleanly on the first live attempt against the real corpus.

## User Setup Required

None -- no external service configuration required. This is a read-only diagnostic; no consumer service, systemd unit, or dashboard needs configuration.

## Next Phase Readiness

- The shadow-mode diagnostic exists, is unit-tested, and has produced its first real measured report against the live corpus -- ready for the D-07 cross-AI review and the user's own review (plan 05, or wherever this phase's next review step lands).
- Zero symbols currently qualify for admission under the seeded thresholds; any future consumer-cutover phase is blocked on either (a) a real recalibration of the `[initial_estimate]` thresholds using this run's NEAR MISS evidence, or (b) an explicit decision that zero-admission is an acceptable interim state to ship shadow-mode-only.
- `market_regimes` and both consumer files (`breadth_vol.py`, `cross_sectional_regime_model.py`) are confirmed untouched -- D-03's shadow-mode boundary held mechanically through this plan's execution.
- No blockers for plan 05.

---
*Phase: 175-itr-materiality-filtered-empirical-tags-for-breadth-peer-gro*
*Completed: 2026-09-23*

## Self-Check: PASSED

- FOUND: scripts/analysis/itr_materiality_shadow_diagnostic.py
- FOUND: tests/unit/test_itr_materiality_shadow_diagnostic.py
- FOUND: .planning/phases/175-itr-materiality-filtered-empirical-tags-for-breadth-peer-gro/175-04-SUMMARY.md
- FOUND: commit 1bb426d8c (Task 1)
- FOUND: commit 03988631f (Task 2)
