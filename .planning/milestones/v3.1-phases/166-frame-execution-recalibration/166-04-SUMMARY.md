---
phase: 166-frame-execution-recalibration
plan: 04
subsystem: database
tags: [alpha-frames, gate-evaluations, bootstrap, oos-validation, timescaledb, asyncpg]

# Dependency graph
requires:
  - phase: 142B
    provides: alpha_frames hypertable, counterfactual_pnl_r, frame_gate_passes/evaluate_frame_gate (services/counterfactual_tracker.py)
  - phase: 148
    provides: gate_evaluations table (migration 248), score03_gate2_execution_eval.py analog + SHADOW-REVIEW.md frozen five criteria
provides:
  - scripts/analysis/gate166_frame_recalibration_eval.py — the fresh validation gate scoring any candidate's OOS alpha_frames population
  - assemble_gate166_evidence() — pure evidence-assembly core (pooled frozen five + regime companion + population footprint + coverage disclosure)
  - _GATE_IDS mapping (gate166_scalar / gate166_structural / gate166_baseline) — new gate_ids, never a gate2_execution re-run
  - _check_and_record_dryrun() — Pitfall 5 enforced in code via a local JSON sentinel
affects: [166-06]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Per-candidate gate_id derivation via a module-level dict, validated inside the pure evidence-assembly function (raises ValueError on unknown candidate) rather than left to caller discipline"
    - "Local JSON sentinel file enforcing a one-dry-run-per-key discipline in code (Pitfall 5 / Codex concern 4) — same shape as gate_evaluations' own DB-side one-shot check, but for the pre-flight dry-run peek"
    - "Descriptive-only disclosure blocks (population footprint, tf/regime coverage) assembled alongside but structurally excluded from the pass/fail computation"

key-files:
  created:
    - scripts/analysis/gate166_frame_recalibration_eval.py
    - tests/unit/test_gate166_frame_recalibration_eval.py
  modified: []

key-decisions:
  - "Reused SHADOW-REVIEW.md's frozen five criteria and score03's exact machinery (frame_gate_passes/evaluate_frame_gate/_annualized_sharpe/_max_drawdown/_json_safe) verbatim — zero new thresholds invented (OQ3)"
  - "Per-candidate gate_id validated inside assemble_gate166_evidence itself (raises ValueError on an unknown candidate) so D-04's 'never gate2_execution' guarantee is structural, not merely a convention followed at call sites"
  - "baseline candidate defaults its weight_epoch to 143.1-08-champion (the exact population Gate 2 already scored) — the natural comparative anchor for 'did recalibration beat the status quo'; scalar/structural default to placeholder weight_epoch names (166-scalar-candidate / 166-structural-candidate) that Plan 166-06's frame-regeneration runs will actually write under, overridable via --weight-epoch"
  - "Population footprint and coverage disclosure blocks are computed and attached to the evidence dict but never participate in the pooled result='pass'/'fail' computation — verified structurally in tests (population dict carries no passes/result key of its own)"
  - "Split Task 1 (pure evidence-assembly core) and Task 2 (write path + dry-run sentinel + CLI) into two separate atomic commits even though both were authored in the same working session, to honor the plan's per-task commit protocol"

patterns-established:
  - "Pattern: local JSON dry-run sentinel (gate_id -> ISO timestamp) as the enforcement mechanism for a 'peek at holdout data at most once' discipline — reusable by any future one-shot OOS gate that wants a pre-flight dev-time check without consuming the real one-shot write"

requirements-completed: [D-01d, D-04, D-05]

# Metrics
duration: ~35min
completed: 2026-07-23
---

# Phase 166 Plan 04: Fresh Validation Gate (Scalar/Structural/Baseline) Summary

**`gate166_frame_recalibration_eval.py` scores any candidate's OOS `alpha_frames` population against SHADOW-REVIEW.md's frozen five criteria unmodified, writes exactly one `gate_evaluations` row under a new per-candidate `gate_id` (never `gate2_execution`), and discloses a population footprint + tf/regime coverage limits that never gate the verdict — with a code-enforced one-dry-run-per-candidate sentinel guarding against an OOS holdout leak.**

## Performance

- **Duration:** ~35 min
- **Completed:** 2026-07-23T12:17:00Z
- **Tasks:** 2/2 completed
- **Files modified:** 2 (1 script created + 1 test file created)

## Accomplishments

- **Task 1 (pure evidence-assembly core):** `assemble_gate166_evidence(rows, candidate, ...)` reuses SHADOW-REVIEW.md's frozen five criteria (`c1`-`c5`) via `frame_gate_passes`/`evaluate_frame_gate` unmodified, always attaches the mandatory regime-stratified companion (D-05/D-07 — disclose insufficient-coverage cells, never count them as failing), aggregates same-`bar_ts` frames by SUM before any cumulative statistic (todo 172 regression guard), and derives a per-candidate `gate_id` from a validated lookup that raises on anything outside `{scalar, structural, baseline}`. Added two new descriptive-only blocks beyond score03's shape: `population` (frame_count / eligible_cell_count / per-(regime,tf) `cell_frame_counts`, Codex concern 2) and `disclosure` (observed tfs/regimes + `tf_5m_15m_only`/`regime_mid_bull_only` flags, D-05/todo 173) — both verified structurally to carry no `passes`/`result` key of their own.
- **Task 2 (atomic write + dry-run sentinel + CLI):** `_write_gate166_row()` mirrors score03's atomic re-check-then-insert transaction, keyed by the evidence's own `gate_id` (D-04 one-shot per candidate). `_check_and_record_dryrun()` is a new mechanism this plan adds beyond score03's analog — a local JSON sentinel file enforcing Pitfall 5 (one dry-run per candidate) in code rather than by convention: a second `--dry-run` for the same `gate_id` raises unless `--force` is passed deliberately, and the check runs FIRST in `main()`, before any scoring, so a repeat peek is refused before touching the DB. `main()` exposes `--candidate` (required), `--dry-run`, `--force`, and override flags for `--weight-epoch`/`--look-log-path`/`--dryrun-sentinel-path`.
- 13 unit tests total (9 Task 1 + 4 Task 2), all passing; full `tests/unit/` suite (existing tests across the whole repo) stays green; `--help` exits 0 showing `--candidate {baseline,scalar,structural}`, `--dry-run`, `--force`.

## Task Commits

Each task was committed atomically:

1. **Task 1: Pure evidence-assembly core (pooled criteria + regime companion + population footprint + 172 aggregation)** - `2c77ad8c` (feat)
2. **Task 2: Atomic one-shot write + dry-run main() + candidate arg + dry-run sentinel** - `e935900c` (feat)

**Plan metadata:** committed separately as part of this SUMMARY's own commit (worktree mode — orchestrator handles final merge)

## Files Created/Modified

- `scripts/analysis/gate166_frame_recalibration_eval.py` - Fresh validation gate: `assemble_gate166_evidence()` (pure evidence assembly), `_write_gate166_row()` (atomic one-shot write), `_check_and_record_dryrun()` (Pitfall 5 sentinel), `main()` (CLI with `--candidate`/`--dry-run`/`--force`). Zero real-run execution in this plan — the one-shot OOS runs happen in Plan 166-06 after each candidate's frames are regenerated.
- `tests/unit/test_gate166_frame_recalibration_eval.py` - 13 unit tests: full evidence-dict shape, 172 same-`bar_ts` aggregation (22-row tied fixture), regime companion always-present + insufficient-coverage exclusion, gate_id derivation (parametrized over all 3 candidates) + unknown-candidate rejection, `_json_safe` non-finite conversion, population footprint sparse-cell visibility, atomic write + look-log, second-write refusal, zero-write dry-run, and dry-run sentinel refuse/force/per-gate_id-isolation behavior.

## Decisions Made

- Reused score03's exact frozen-five machinery and helper functions (`_annualized_sharpe`, `_max_drawdown`, `frame_gate_passes`, `evaluate_frame_gate`, `_json_safe`) verbatim rather than re-deriving — OQ3 explicitly forbids inventing new thresholds for this gate.
- `_GATE_IDS` validation lives inside `assemble_gate166_evidence()` itself (raises `ValueError`), not left as a convention at call sites — makes D-04's "never gate2_execution" guarantee structural.
- `baseline` candidate's default `weight_epoch` is `143.1-08-champion` — reuses the exact population Gate 2 already scored, giving 166-06's eventual verdict doc a direct apples-to-apples comparison point against the pre-recalibration status quo. `scalar`/`structural` default to placeholder `weight_epoch` values (`166-scalar-candidate`/`166-structural-candidate`) documented as subject to being overridden via `--weight-epoch` once Plan 166-06 confirms the real weight_epoch each candidate's frame-regeneration run writes under.
- Population footprint and coverage disclosure are computed but never touch the `result` computation — verified structurally, not just documented, via a test asserting the population dict has no `passes`/`result` key.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Symlinked the worktree's missing `.venv` to the main repo's**
- **Found during:** Task 1, before running the first test
- **Issue:** This git worktree has no `.venv` (gitignored, not copied on worktree creation — same known GSD worktree gotcha documented in 166-01's SUMMARY). Running `.venv/bin/pytest` would have failed with no such file.
- **Fix:** `ln -s /home/bg/dev/indicagent/.venv /home/bg/dev/indicagent/.claude/worktrees/agent-a955d88b848e96526/.venv` — a symlink to the already-installed main-repo venv, not a new package install (no package-manager command invoked, so the Rule 3 install-exclusion does not apply).
- **Files modified:** none tracked (symlink only, outside git; confirmed absent from `git status --short` before and after)
- **Committed in:** N/A (not a tracked file)

**2. [Process deviation, not a Rule 1-4 fix] Split Task 1 and Task 2 into two atomic commits after writing them together**
- **Found during:** Preparing to commit
- **Issue:** Both tasks' code was authored together in one editing pass (natural given how tightly Task 2's write path depends on Task 1's evidence dict shape), which would have produced a single combined commit rather than the plan's mandated per-task atomic commits.
- **Fix:** Reconstructed the Task-1-only subset of both files (pure evidence-assembly functions + tests 1-6 minus write-path/CLI/sentinel code), committed that first (`2c77ad8c`), then added the Task 2 additions (write path, sentinel, `main()`, tests 7-9) via `Edit` and committed separately (`e935900c`). Both commits' test suites were independently verified green before committing (9/9 then 13/13).
- **Files modified:** scripts/analysis/gate166_frame_recalibration_eval.py, tests/unit/test_gate166_frame_recalibration_eval.py
- **Committed in:** `2c77ad8c` (Task 1), `e935900c` (Task 2)

---

**Total deviations:** 1 auto-fixed (Rule 3, environment-only), 1 process correction (commit granularity, no code impact)
**Impact on plan:** Zero scope creep. The symlink is a pure environment fix identical to 166-01's. The commit split has no functional impact — both commits pass their own independent test runs and the final state is byte-identical to what a single combined commit would have produced.

## Issues Encountered

None beyond the two items documented under Deviations above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 166-06 (one-shot OOS scoring + verdict) can invoke this script directly once each candidate's frames exist: `.venv/bin/python scripts/analysis/gate166_frame_recalibration_eval.py --candidate {scalar,structural,baseline} --dry-run` for a zero-write pre-flight check (refused a second time per gate_id without `--force`), then the real run without `--dry-run` for the one-shot write.
- The `--weight-epoch` default for `scalar`/`structural` (`166-scalar-candidate`/`166-structural-candidate`) is a placeholder — Plan 166-06 must either confirm these match the actual `weight_epoch` values Plans 166-02/166-03's frame-regeneration runs write under, or pass `--weight-epoch` explicitly to override.
- No blockers. All 13 tests pass on synthetic rows; the real DB-touching path (`_load_apr`, `_read_oos_start`, the `_OOS_QUERY_SQL` fetch, `_write_gate166_row`) is exercised only via mocks in this plan, matching its explicit scope boundary ("This plan builds the SCRIPT and its unit tests... The one-shot OOS RUNS happen in Plan 166-06").

---
*Phase: 166-frame-execution-recalibration*
*Completed: 2026-07-23*

## Self-Check: PASSED

All created files verified present on disk (`gate166_frame_recalibration_eval.py`, its test
file, this SUMMARY). Both task commits (`2c77ad8c`, `e935900c`) verified present in
`git log --oneline --all`. No missing items.
