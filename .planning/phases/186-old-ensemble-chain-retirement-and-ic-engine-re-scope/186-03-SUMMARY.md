---
phase: 186-old-ensemble-chain-retirement-and-ic-engine-re-scope
plan: "03"
subsystem: testing
tags: [determinism, pickle-remap, repro-frozen, bit-identity, research-tools]

requires:
  - phase: 179 (E14 frozen artifacts) and 181 (TSMOM frozen artifacts)
    provides: frozen S2/S3 pickles and the phase 181 snapshot under logs/phase179/rerun_e14 and logs/phase181 (local, not in git)
provides:
  - scripts/research/determinism/repro_frozen.py, the bit-identity check that survives the sleeve directory deletion (186-16, 186-29)
  - remapping unpickler (_RENAMED_MODULES + _RemappingUnpickler) that loads frozen S3 pickles naming the pre-move evaluate module path
  - promoted HarnessConfig, refit_dates, signals, snapshot_io support modules outside the research package
  - todo 448 item 1 progress note (promoted and bit-identical)
affects: [186-16, 186-29, 187, research lane (every src/intelligence/research change runs this check)]

tech-stack:
  added: []
  patterns:
    - "pickle.Unpickler.find_class remap table with exactly one entry, test-asserted, for loading frozen artifacts across a module move"
    - "worktree-aware frozen_logs_dir: explicit path, else repo logs/, else main checkout logs/ via git-common-dir"

key-files:
  created:
    - scripts/research/determinism/__init__.py
    - scripts/research/determinism/config.py
    - scripts/research/determinism/results.py
    - scripts/research/determinism/sessions.py
    - scripts/research/determinism/signals.py
    - scripts/research/determinism/snapshot_io.py
    - scripts/research/determinism/repro_frozen.py
    - tests/unit/research_tools/__init__.py
    - tests/unit/research_tools/test_determinism_modules.py
    - tests/unit/research_tools/test_repro_frozen.py
  modified:
    - .planning/todos/pending/448-research-lane-dependencies-for-phases-186-187.md

key-decisions:
  - "Remap table holds exactly one entry (the old evaluate shim path); everything else loads unchanged, so the unpickler cannot redirect arbitrary classes"
  - "No code key in the promoted s2sig stage: the comparison ignores the snapshot key and the code key, matching the original lines 104-108"
  - "Fixture pickle route: protocol 0 GLOBAL opcode with bytes.replace on the module string (no length-prefix rewrite needed)"

patterns-established:
  - "Promoted modules carry provenance docstrings naming their sleeve source; config.py stays byte-identical instead (test-asserted with cmp, skip-guarded for 186-29)"
  - "AST import scan in tests asserts the promoted package never imports scripts.analysis, services.ic_engine, services.ensemble_trainer, services.cross_sectional_regime_model, asyncpg, or src.config"

requirements-completed: [D-11, R-05, D-02, R-11]

duration: 16 min (resumed session; Task 1 and Task 2 code were committed 2026-09-27 by the prior executor)
completed: 2026-09-28
---

# Phase 186 Plan 03: Determinism tool promotion Summary

**repro_frozen promoted to scripts/research/determinism/ with a one-entry remapping unpickler; all three frozen books (phase 179 S3, phase 181 S2, phase 181 S3) rerun bit-identical with the shim module blocked**

## Performance

- **Duration:** 16 min for the resumed session (Task 2 acceptance + Task 3 + close-out); Tasks 1-2 were committed 2026-09-27 by the previous executor, which hit the usage limit during Task 2 acceptance
- **Started:** 2026-09-28T05:30Z (resumed session)
- **Completed:** 2026-09-28T05:46Z
- **Tasks:** 3 of 3
- **Files modified:** 11 (10 created, 1 todo note appended)

## Accomplishments
- All five support modules plus repro_frozen live under `scripts/research/determinism/` with zero imports of `scripts.analysis`, `services.ic_engine`, `services.ensemble_trainer`, `services.cross_sectional_regime_model`, asyncpg, or `src.config` (AST-scan test-enforced)
- The three frozen outputs rerun bit-identical through the promoted tool, matching the original tool's baseline excess arrays exactly, with and without the old shim module importable
- Todo 448 item 1 carries its dated progress note; the sleeve directory deletion (186-16, 186-29) no longer blocks the bit-identity check

## Task Commits

Each task was committed atomically on branch `phase-186-03-determinism` (worktree `/home/bg/dev/indicagent-186-03`):

1. **Task 1: support modules + tests** - `7cff85aa3` (feat)
2. **Task 2 RED: failing tests for the promoted tool** - `97ea34e51` (test)
3. **Task 2 GREEN: promoted repro_frozen** - `dc1985fc1` (feat)
4. **Task 3: todo 448 item 1 note** - `09eab702c` (docs)

_TDD: Task 2 followed RED (97ea34e51) then GREEN (dc1985fc1); no refactor needed._

## Files Created/Modified
- `scripts/research/determinism/repro_frozen.py` - the promoted bit-identity check: inline s2sig stage, `_RemappingUnpickler` with `_RENAMED_MODULES` (one entry), `frozen_logs_dir` worktree resolution, `same()` verbatim
- `scripts/research/determinism/config.py` - byte-identical `HarnessConfig` copy (cmp-asserted; 186-29 switches research test imports to it)
- `scripts/research/determinism/results.py` - `GroupArrays`, `Snapshot` (refit-path dataclasses dropped)
- `scripts/research/determinism/sessions.py` - `refit_dates` only
- `scripts/research/determinism/signals.py` - whole file (`TSMOM_LOOKBACK_SESSIONS`, `tsmom`, `SIGNALS`)
- `scripts/research/determinism/snapshot_io.py` - `verify_snapshot`/`load_snapshot` only, no database imports
- `tests/unit/research_tools/test_determinism_modules.py` - byte-identity, behavior ports, snapshot round-trip, AST import scan
- `tests/unit/research_tools/test_repro_frozen.py` - remap on fixture and real frozen S3 pickles, `same()` semantics, import hygiene in a fresh subprocess, `frozen_logs_dir`
- `.planning/todos/pending/448-research-lane-dependencies-for-phases-186-187.md` - dated item-1 progress note (status stays pending; items 2-4 open)

## Decisions Made
- Remap table restricted to exactly one entry and test-asserted (`_RENAMED_MODULES == {old: new}`), per the tamper-model disposition T-186-03-01
- Fixture pickle used the protocol 0 route (GLOBAL opcode stores the module as newline-terminated text; plain `bytes.replace` stays valid), so the protocol 2 length-prefix rewrite was not needed
- The promoted `_save_s2sig` names the artifact `s2sig_<sha256(payload)[:16]>.pkl` and writes it for inspection without printing the path (the original's path print came from `run.main`, which is not promoted)

## Bit-identity runs (Task 3, D-11)

Worktree HEAD at run time: `dc1985fc1` (Task 2 implementation commit; the runs preceded the todo-note commit `09eab702c`).

Commands, from `/home/bg/dev/indicagent-186-03` with the venv on PATH:

1. Baseline (original tool): `python scripts/analysis/sleeve_walk_forward/repro_frozen.py /tmp/186-03-task3/repro_old --logs /home/bg/dev/indicagent/logs` - wall clock 19.54 s, exit 0
2. Promoted (no --logs, exercising `frozen_logs_dir` from the worktree): `python -m scripts.research.determinism.repro_frozen /tmp/186-03-task3/repro_new` - wall clock 18.85 s, exit 0
3. Blocked-module check (`sys.modules["scripts.analysis.sleeve_walk_forward.evaluate"] = None` before `main`): wall clock 19.17 s, exit 0, same three lines

Baseline stdout:

```
  not recorded in frozen artifact, skipped: result.excess_se
phase 179 S3: bit-identical [ 0.21612308 -0.14601638 -0.10558864]
/tmp/186-03-task3/repro_old/s2sig_a6c7f774e8ffdfe8.pkl
phase 181 S2 (signal from Panel): bit-identical
  not recorded in frozen artifact, skipped: result.observed_daily
  not recorded in frozen artifact, skipped: result.null_median_daily
  not recorded in frozen artifact, skipped: result.observed_weights
  not recorded in frozen artifact, skipped: result.excess_se
phase 181 S3: bit-identical [0.19424572]
```

Promoted stdout (identical except the s2sig path line, which the promoted tool does not print; the artifact lands in the out dir as `s2sig_998a2da733caaeff.pkl`):

```
  not recorded in frozen artifact, skipped: result.excess_se
phase 179 S3: bit-identical [ 0.21612308 -0.14601638 -0.10558864]
phase 181 S2 (signal from Panel): bit-identical
  not recorded in frozen artifact, skipped: result.observed_daily
  not recorded in frozen artifact, skipped: result.null_median_daily
  not recorded in frozen artifact, skipped: result.observed_weights
  not recorded in frozen artifact, skipped: result.excess_se
phase 181 S3: bit-identical [0.19424572]
```

Exactly three `bit-identical` lines in each run (grep-counted: 3/3/3), excess arrays equal to the baseline's, exit 0 everywhere. The blocked-module run printing the same three lines proves the remap path is the one exercised (T-186-03-02).

## D-11 import list

`grep -rln "sleeve_walk_forward" --include=*.py .` from the worktree, 37 files (what 186-16/186-29 act on; the five `scripts/research/determinism/` hits are provenance docstrings plus the remap key, not imports):

- `scripts/analysis/extreme_volume_divergence_track1.py`, `scripts/analysis/residual_breadth_diagnostic.py`
- `scripts/analysis/sleeve_walk_forward/`: `refit.py`, `repro_frozen.py`, `run.py`, `score.py`, `snapshot.py`, `synthetic.py`, `v4.py`, `v4b.py`, `v5.py`, `verdict.py`
- `scripts/research/determinism/`: `repro_frozen.py`, `results.py`, `sessions.py`, `signals.py`, `snapshot_io.py`
- `tests/live/test_sleeve_walk_forward_snapshot.py`
- `tests/unit/research/`: `test_evaluate.py`, `test_evaluate_intraday.py`, `test_evaluate_session_scoring.py`, `test_portfolio.py`, `test_portfolio_r1.py`
- `tests/unit/research_tools/`: `test_determinism_modules.py`, `test_repro_frozen.py`
- `tests/unit/sleeve_walk_forward/`: `test_config.py`, `test_refit.py`, `test_run.py`, `test_score.py`, `test_sessions.py`, `test_signals.py`, `test_snapshot_io.py`, `test_synthetic.py`, `test_v4.py`, `test_v4b.py`, `test_v5.py`, `test_verdict.py`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Task 2 acceptance completed by the resumed executor**
- **Found during:** Task 2 (previous executor killed by the usage limit mid-acceptance)
- **Issue:** Task 2's acceptance criteria and verify block were unverified at the kill
- **Fix:** Re-ran all six criteria from the worktree: find_class 2 / old-path 1, no bare `pickle.loads(...read_bytes...)`, no forbidden imports, no `sys.argv`, 28/28 tests green with no skips, `pytest tests/unit -q --co` exit 0 with 0 errors
- **Files modified:** none (verification only)
- **Committed in:** n/a (existing commits 97ea34e51 / dc1985fc1)

**2. [Rule 3 - Blocking] AC4 evaluated from the merge base**
- **Found during:** Task 3 acceptance
- **Issue:** two-dot `git diff main -- docs` shows `docs/research/scrub-historical-pass.md` (82 lines), which is phase 185-10's file committed on main after this branch's point (f8cbcd9ad); the branch never touched it
- **Fix:** verified `git diff --stat main...HEAD -- scripts/analysis src/intelligence/research docs tests/unit/research tests/unit/sleeve_walk_forward` is empty (the branch's own changes touch only its plan files); no rebase or reorder of main
- **Files modified:** none
- **Committed in:** n/a

**3. [Rule 1 - Record accuracy] Todo note dated 2026-09-28, not the plan's literal 2026-09-27**
- **Found during:** Task 3
- **Issue:** the plan quotes the note with "2026-09-27" (its expected run date); the runs actually executed 2026-09-28 UTC
- **Fix:** dated the note 2026-09-28 for a truthful record; wording otherwise exactly as prescribed
- **Files modified:** `.planning/todos/pending/448-research-lane-dependencies-for-phases-186-187.md`
- **Committed in:** 09eab702c

---

**Total deviations:** 3 auto-fixed (1 resume completion, 1 environment interpretation, 1 record accuracy)
**Impact on plan:** None on scope or behavior; the bit-identity result and file set are exactly the plan's.

## Issues Encountered
- The previous executor was killed by the usage limit during Task 2 acceptance; this session inherited the clean worktree at dc1985fc1 and completed acceptance plus Task 3 without redoing committed work.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- 186-16 and 186-29 can delete the sleeve directory and its tests; the bit-identity check no longer depends on it (the promoted package imports nothing from it)
- 186-29 switches the research tests' `HarnessConfig` imports to `scripts/research.determinism.config` (D-03); the byte-identity test already carries its skip guard
- The frozen artifacts under `logs/phase179` and `logs/phase181` remain the read-only inputs; every future `src/intelligence/research/` change runs the promoted tool with no `--logs` needed from a worktree

## Self-Check: PASSED

- All 10 created files exist on the branch; todo 448 still starts `status: pending` with items 2-4 open
- Commits 7cff85aa3, 97ea34e51, dc1985fc1, 09eab702c present on `phase-186-03-determinism`
- Task acceptance criteria re-run post-commit: Task 3 grep-counts (3/3/3 bit-identical lines), combined test sweep `pytest tests/unit/research_tools/ tests/unit/sleeve_walk_forward/ tests/unit/research/ -q` exit 0, plan verify command exit 0/0 with count 3
- No diff from the merge base under `scripts/analysis`, `src/intelligence/research`, `docs`, `tests/unit/research`, `tests/unit/sleeve_walk_forward`

---
*Phase: 186-old-ensemble-chain-retirement-and-ic-engine-re-scope*
*Completed: 2026-09-28*
