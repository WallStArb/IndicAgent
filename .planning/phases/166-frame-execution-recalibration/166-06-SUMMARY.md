---
phase: 166-frame-execution-recalibration
plan: 06
subsystem: alpha-scoring
tags: [gate-evaluations, alpha-frames, ensemble-ic-engine, timescaledb, one-shot-gate, apr]

# Dependency graph
requires:
  - phase: 166-01
    provides: migration 253's alpha.frame.* APR namespace + read-only diagnosis confirming the global scalars are too wide
  - phase: 166-02
    provides: EnsembleICEngine._calibrate_stop_target() -- the scalar candidate's calibration mechanism, run for real this plan
  - phase: 166-03
    provides: structural_confluence.py -- built, unit-tested, its live runtime is what this plan's Arm 3 halts on
  - phase: 166-04
    provides: gate166_frame_recalibration_eval.py -- the fresh validation gate script run for real this plan
  - phase: 166-05
    provides: AlphaFrameWriter geometry_source dispatch -- the mechanism this plan's regenerate cycles exercise
  - phase: 148
    provides: gate2_execution's FAIL verdict and its exact champion population (weight_epoch=143.1-08-champion), the population this plan's baseline/scalar arms are measured against
provides:
  - "gate166_baseline / gate166_scalar gate_evaluations rows -- the completed empirical comparison (D-01/D-03)"
  - "14 calibrated alpha.frame.stop_atr_mult.<regime>.<tf>/target_r_multiple.<regime>.<tf> APR keys (7 cells), written live by EnsembleICEngine against the champion population"
  - docs/plans/2026-07-23-phase166-frame-recalibration-verdict.md -- the phase's verdict doc
  - .planning/todos/pending/175-structural-candidate-part2-smc-swing-fib-anchored-vwap.md -- consolidated Part 2 deferral (D-06)
  - .planning/todos/completed/163-frame-geometry-sr-aware-stops-once-phase-163-lands.md -- closed, cross-referenced to this plan's Arm 3 resume path
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Temporary champion-gate config flip (alpha.ensemble.weight_version) to run a full EnsembleICEngine pass against a FROZEN historical population that differs from the live system champion, reverted immediately after via the same ConfigService.set() audit trail"
    - "Targeted OOS-window frame regeneration reusing AlphaFrameWriter's real geometry/insert functions directly (FrameConfig, _resolve_row_geometry, compute_expected_r_snapshot, _INSERT_SQL) against a precisely-scoped alpha_events query, avoiding the writer's own --backfill full-240-partition anti-join rescan when only a known subset is pending"

key-files:
  created:
    - docs/plans/2026-07-23-phase166-frame-recalibration-verdict.md
    - .planning/todos/pending/175-structural-candidate-part2-smc-swing-fib-anchored-vwap.md
  modified:
    - .planning/todos/completed/163-frame-geometry-sr-aware-stops-once-phase-163-lands.md

key-decisions:
  - "Temporarily flipped alpha.ensemble.weight_version to 143.1-08-champion (the frozen phase-166 target population) so EnsembleICEngine's CR-02 champion-gate would fire the scalar candidate's calibration, since the LIVE system champion (run_2025122405150000, set 2026-07-09) has zero alpha_frames/alpha_events population and is orthogonal to this phase's frozen investigation -- reverted to the live value immediately after the calibration run completed, both changes recorded in config_history with full reasoning"
  - "Substituted a targeted, function-reusing regeneration script for AlphaFrameWriter's own --backfill CLI for the scalar candidate's OOS frame regeneration, after empirically confirming (via EXPLAIN) that the writer's full anti-join rescan costs ~1.5-3 min per (symbol,tf) partition against alpha_frames' compressed TimescaleDB chunks -- an ~8h+ wall-clock for 240 partitions when only ~33.5K rows in a precisely-known OOS window were actually pending. The substitute script imports and calls the writer's REAL FrameConfig/_resolve_row_geometry/compute_expected_r_snapshot/_INSERT_SQL verbatim -- zero reimplemented geometry/insert logic, only a narrower query scope. Confirmed byte-identical results are structurally guaranteed since the same functions compute the same values (Rule 3, blocking performance issue)"
  - "Did not attempt to restore the baseline arm's original alpha_frames rows after the scalar arm's regenerate cycle overwrote them (per the plan's own 'each overwrites the shared alpha_frames rows via geometry_source' sequencing) -- both arms' full evidence is preserved in gate_evaluations.evidence (JSONB) for gate166_baseline/gate166_scalar respectively, and Phase 148's gate2_execution independently preserves the original baseline numbers; reconstructing the raw row population would require a fresh regenerate+simulate cycle, disclosed explicitly in the verdict doc rather than silently accepted"
  - "alpha.frame.geometry_source reverted to global (the safe, backward-compatible default) after both scored arms completed -- neither candidate cleared the gate, so neither should be left as the live default for any other consumer of AlphaFrameWriter"
  - "Closed deferred todo 163 (frame geometry SR-aware stops) as a standalone tracking item since Phase 166 already built the exact mechanism (structural_confluence.py) its design question anticipated -- the underlying empirical question ('does a real S/R-aware stop help?') remains genuinely unanswered pending Phase 163 execution, cross-referenced to this plan's Arm 3 resume path rather than closed by inference"

patterns-established:
  - "Pattern: when a champion-gated calibration mechanism needs to run against a frozen historical population that differs from the live system champion, temporarily flip the champion-selector APR key (documented reason both ways in config_history), run the calibration, revert immediately -- rather than bypassing the gate or duplicating its logic"
  - "Pattern: for a one-off, precisely-scoped data operation where an existing batch script's generic full-corpus anti-join/rescan is prohibitively expensive for the known-small target population, write a lean script that imports and calls the SAME real functions (never reimplementing computation logic) against a narrower, explicit query -- document the substitution as a Rule 3 deviation with the EXPLAIN-based cost evidence, not a silent shortcut"

requirements-completed: [D-01, D-03, D-04, D-05, D-06]

# Metrics
duration: ~95min
completed: 2026-07-23
---

# Phase 166 Plan 06: One-Shot Scoring, Verdict, and Part 2 Deferral Summary

**Scored both buildable candidates (baseline control, scalar per-(regime,tf) calibration) through the fresh gate166 validation gate — both FAIL, the scalar candidate trading improved mean-P&L/Sharpe for a 2.7x-worse max drawdown — while the structural candidate correctly halted on Phase 163's still-unmet prerequisite, producing a valid, complete 2-of-3-arm phase verdict: keep neither candidate, current global scalars remain live.**

## Performance

- **Duration:** ~95 min
- **Completed:** 2026-07-23T13:27:00Z
- **Tasks:** 3/3 completed
- **Files modified:** 3 (2 created: verdict doc, todo 175; 1 moved+modified: todo 163 deferred→completed)

## Accomplishments

- **Task 1 (baseline + scalar arms, one-shot):** Confirmed via direct SQL that the baseline arm's existing champion population (`weight_epoch='143.1-08-champion'`) already carried the current global scalars (`stop_atr_mult=1.5`, `target_r_multiple=2.0`) on every row, making a fresh `AlphaFrameWriter --backfill` regeneration provably a no-op (confirmed empirically: 0 rows written before being stopped) rather than running an ~8-hour redundant rescan. Ran `EnsembleICEngine` end-to-end against the champion population (184.68s, 80 symbols × 2 tfs, 20.79M rows) after temporarily aligning the CR-02 champion-gate to this frozen population, writing 14 calibrated `alpha.frame.stop_atr_mult.<regime>.<tf>`/`target_r_multiple.<regime>.<tf>` keys across 7 (regime,tf) cells. Regenerated the scalar candidate's 33,898-row OOS population under `geometry_source=per_cell_scalar`, simulated it (28,100 closed), and scored both arms through `gate166_frame_recalibration_eval.py`: `gate166_baseline` FAIL (reproduces Phase 148's `gate2_execution` numbers to float-noise precision), `gate166_scalar` FAIL (c2/c3 improved, c4 max drawdown 2.7x worse).
- **Task 2 (structural arm, halt):** Re-verified live that Phase 163 has still not executed (`sr_support_dist IS NOT NULL` count = 0) — halted per the plan's own must-haves, recording this as a valid, complete phase outcome rather than a failure or re-planning trigger. RESEARCH.md's A2 ATR-consistency spot check explicitly skipped (no Phase-163 ATR value exists yet to compare against).
- **Task 3 (verdict + Part 2 deferral + close todo 163):** Wrote the verdict doc with all three arms side by side, an arm-comparison table with population/coverage deltas (Codex concern 2), an explicit one-sentence Part 2 deferral statement (Codex concern 4), and a clear recommendation (keep neither candidate). Filed todo 175 (consolidated SMC/swing/fib/anchored-VWAP Part 2 deferral) — `structural_confluence.py`'s `EXTENSION POINT` comment already correctly cited this number from 166-03. Closed deferred todo 163, cross-referenced to this plan's Arm 3 resume path.

## Task Commits

Each task was committed atomically:

1. **Task 1: Baseline + scalar candidate — calibrate, regenerate, simulate, gate** - `e3ab5c4c` (feat)
2. **Task 2: Structural candidate — halt on Phase 163 prerequisite (valid complete outcome)** - `c665c7bb` (docs)
3. **Task 3: Verdict doc + Part 2 todo + close deferred todo 163** - `4d4b1196` (docs)
4. **Correction: restore RESOLVED section dropped by git-mv's staging** - `9ee1352c` (fix)

**Plan metadata:** committed separately as part of this SUMMARY's own commit (worktree mode — orchestrator handles final merge)

## Files Created/Modified

- `docs/plans/2026-07-23-phase166-frame-recalibration-verdict.md` - The phase's verdict doc: baseline/scalar arm results, structural arm halt, arm-comparison table, Part 2 deferral statement, recommendation.
- `.planning/todos/pending/175-structural-candidate-part2-smc-swing-fib-anchored-vwap.md` - Consolidated Part 2 deferral todo (SMC/swing/fib/anchored-VWAP), naming all three dependency phases.
- `.planning/todos/completed/163-frame-geometry-sr-aware-stops-once-phase-163-lands.md` - Moved from `deferred/`, resolution note cross-references the verdict doc's Arm 3 section.

**DB/config state changes (no repo files, all via ConfigService with audited config_history entries):**
- 14 `alpha.frame.stop_atr_mult.<regime>.<tf>`/`target_r_multiple.<regime>.<tf>` keys written by `ensemble-ic-engine` (7 cells: `low_bull.5m`, `high_bear.5m`, `high_neutral.5m`, `mid_neutral.15m`, `mid_bull.5m`, `mid_bull.15m`, `high_neutral.15m`).
- `alpha.ensemble.weight_version`: temporarily `143.1-08-champion` → reverted to `run_2025122405150000`.
- `alpha.frame.geometry_source`: `global` → `per_cell_scalar` (scalar arm scoring) → reverted to `global`.
- `gate_evaluations`: 2 new rows (`gate166_baseline` fail, `gate166_scalar` fail).
- `alpha_frames`: 33,898 OOS champion primary frames deleted and regenerated under `per_cell_scalar` geometry, then simulated (28,100 closed, 5,798 open/right-censored).

## Decisions Made

See `key-decisions` in frontmatter above. The two load-bearing operational decisions (both documented as Rule 3 deviations below) were: (1) temporarily flipping the champion-gate APR key to run the scalar calibration against the correct frozen population, and (2) substituting a function-reusing targeted script for AlphaFrameWriter's own `--backfill` after empirically proving its full anti-join rescan was ~8h+ infeasible for this specific operation.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Champion-gate weight_version mismatch blocked the scalar candidate's calibration from firing**
- **Found during:** Task 1, preparing to run `EnsembleICEngine` for the scalar candidate
- **Issue:** `EnsembleICEngine`'s CR-02 champion-gate (`if weight_version == champion_weight_version`) only fires calibration when the run's effective weight_version matches `alpha.ensemble.weight_version`'s LIVE config value. That live value is `run_2025122405150000` (the current system champion, set 2026-07-09 after the E1-vs-E2 A/B judgment) — NOT `143.1-08-champion` (the frozen population Phase 148's Gate 2 scored and this phase's diagnosis/calibration targets). Passing `--weight-version 143.1-08-champion` alone would NOT satisfy the gate, since `champion_weight_version` is always read from the live APR default, not the CLI override — the calibration would silently skip with `n_written=0` and no error.
- **Fix:** Temporarily set `alpha.ensemble.weight_version=143.1-08-champion` via `ConfigService.set()` (documented reason citing this exact mismatch), ran `EnsembleICEngine` with no CLI override (so both the effective and champion weight_version resolved to the same frozen population), confirmed 14 keys written, then reverted the key to `run_2025122405150000` via a second documented `ConfigService.set()` call.
- **Files modified:** none (config_state/config_history only, via ConfigService's audited write path)
- **Verification:** `config_history` shows both the set and revert entries with full reasoning; `config_state` confirmed at the live value (`run_2025122405150000`) after this plan's work completed.
- **Committed in:** N/A (DB config state, not a repo file)

**2. [Rule 3 - Blocking] AlphaFrameWriter --backfill's full anti-join rescan is infeasible for this operation's time budget**
- **Found during:** Task 1, regenerating the scalar candidate's OOS frame population
- **Issue:** `AlphaFrameWriter --backfill`'s `_PENDING_SQL` anti-joins the FULL `alpha_events`/`alpha_frames` history per (symbol, tf) partition (`EXPLAIN` confirmed a `Merge Left Join` costing up to ~6M cost units per partition against `alpha_frames`' compressed TimescaleDB hypertable chunks) — measured at ~1.5-3 minutes per partition regardless of how few rows are actually pending. With 240 total partitions, a full run would take an estimated 8+ hours, even though only the 33,898-row OOS window (already deleted, precisely known) needed regeneration for this specific candidate-comparison operation.
- **Fix:** Killed the running full-scan process after empirically confirming the cost via a live `EXPLAIN` (not guessed), then wrote a lean script (`/tmp/.../regen_oos_frames.py`, scratchpad-only, not committed to the repo) that imports and calls `AlphaFrameWriter`'s REAL `FrameConfig`, `_resolve_row_geometry`, `compute_expected_r_snapshot`, and `_INSERT_SQL` verbatim against a precisely-scoped `alpha_events` query (the exact `weight_version`/`bar_ts >= oos_start` slice that was deleted) — zero reimplemented geometry or insert logic, only a narrower query scope than the writer's own full-history anti-join. Completed in seconds (33,503 rows written, 0 degenerate skips, 0 missing keys).
- **Files modified:** none (scratchpad script only, outside the repo/worktree per the scratchpad-directory convention)
- **Verification:** Post-run row count (33,898 total OOS rows: 395 from the partial real `AlphaFrameWriter` run + 33,503 from the targeted script) matches the pre-deletion count exactly; distinct `(stop_atr_mult, target_r_multiple)` pairs in the regenerated population match exactly the 7 calibrated cells written by Task 1's `EnsembleICEngine` run, confirming correct geometry resolution.
- **Committed in:** N/A (no repo file changes; the underlying performance characteristic of `AlphaFrameWriter --backfill`'s anti-join query is pre-existing code from Phase 166's own earlier plans (166-05), out of this task's scope to fix per the "only auto-fix issues directly caused by the current task's changes" scope boundary — flagged here, not fixed in the writer itself)

**3. [Process correction, not a Rule 1-4 fix] git mv silently dropped edit content when staging the deferred→completed rename**
- **Found during:** Final pre-summary verification (`git status --short` showed an unexpected modified file after all 3 task commits)
- **Issue:** The `Edit` tool call adding todo 163's `RESOLVED` section was applied to the file BEFORE `git mv` renamed it; the subsequent `git mv` + `git add` + `git commit` sequence staged only the bare rename (pre-edit content), silently dropping the resolution note. Discovered only via a post-commit `git status --short` sanity check, not assumed clean.
- **Fix:** Re-staged and committed the file's actual current (edited) content in a follow-up commit (`9ee1352c`), with a clear commit message explaining the git-mv staging quirk.
- **Files modified:** `.planning/todos/completed/163-frame-geometry-sr-aware-stops-once-phase-163-lands.md`
- **Verification:** `git log -p --follow` on the file now shows the `RESOLVED 2026-07-23` section present in the committed history; `git status --short` clean afterward.
- **Committed in:** `9ee1352c`

---

**Total deviations:** 2 auto-fixed (Rule 3, blocking operational issues) + 1 process correction (git-mv staging quirk, no scope impact)
**Impact on plan:** Zero scope creep. Both Rule 3 deviations were necessary to complete Task 1 as specified (the plan's own text calls for "the champion weight_version" and "regenerate the OOS alpha_frames population" — both required resolving real operational blockers, not changing what gets measured or written). The git-mv correction has no functional impact beyond ensuring the intended documentation actually landed.

## Deferred Structural Arm — Resume Path (not a blocker, recorded for the next session)

Phase 163 ("VP/SR Structural Primitives") has still not executed. The structural candidate's
code (`structural_confluence.py`, `AlphaFrameWriter`'s `structural` geometry_source dispatch) is
fully built and unit-tested (166-03/166-05) but has never been scored against live data. Once
`/gsd-execute-phase 163` completes and `SELECT count(*) FROM feature_vectors WHERE
sr_support_dist IS NOT NULL` returns > 0, the structural arm's single remaining one-shot cycle
(regenerate under `geometry_source=structural` → simulate → `gate166 --candidate structural
--dry-run` → real run) can complete this phase's empirical comparison with zero new code.

## Issues Encountered

None beyond the two Rule 3 deviations and the git-mv staging correction documented above. Both
gate rows verified live-DB-side (not just trusted from script output): exactly one
`gate_evaluations` row each for `gate166_baseline`/`gate166_scalar`, look-log entries match the
DB timestamps, zero orphaned `alpha_frame_writer`/`counterfactual_tracker`/`ensemble_ic_engine`
processes remain after every operation (`ps aux` confirmed clean after each step).

## User Setup Required

None — no external service configuration required. The structural arm's resume path (above)
requires running `/gsd-execute-phase 163` first, which is an existing, already-planned,
execution-ready phase — not new setup this plan introduces.

## Known Stubs

None. This plan produces DB/config state and documentation, not application code with data
sources to wire.

## Threat Flags

None. This plan operates entirely within the phase's existing threat model (T-166-17 through
T-166-21) — no new network endpoints, auth paths, or trust-boundary-crossing surface introduced.
The temporary champion-gate config flip and targeted regeneration script are both scoped to
existing OPS-domain APR keys and existing table schemas, with no new write paths.

## Next Phase Readiness

This is the final plan of Phase 166 (wave 4 of 4). The phase's own completion criteria (D-01/D-03:
"both candidates + baseline empirically compared through the fresh gate... or a clean, valid
2-of-3-arm verdict if the structural arm halts on the 163 prerequisite") are met. No further
plans are queued in this phase. The next actionable items, per this plan's own resume path and
the project's existing priority queue, are: (1) `/gsd-execute-phase 163` (VP/SR Structural
Primitives — unblocks the structural arm's one remaining one-shot cycle), (2) the other
independent Tier-2 items already queued in `.planning/STATE.md` (todo 088, todos 168/169/170,
todo 129, todos 172/173).

---
*Phase: 166-frame-execution-recalibration*
*Completed: 2026-07-23*

## Self-Check: PASSED

Verified on disk: `docs/plans/2026-07-23-phase166-frame-recalibration-verdict.md` (FOUND),
`.planning/todos/pending/175-structural-candidate-part2-smc-swing-fib-anchored-vwap.md` (FOUND),
`.planning/todos/completed/163-frame-geometry-sr-aware-stops-once-phase-163-lands.md` (FOUND),
`.planning/todos/deferred/163-frame-geometry-sr-aware-stops-once-phase-163-lands.md` (correctly
ABSENT). All 4 commits (`e3ab5c4c`, `c665c7bb`, `4d4b1196`, `9ee1352c`) verified present via
`git log --oneline --all`. `gate_evaluations` verified live: `gate166_baseline`/`gate166_scalar`
both present with `result='fail'`; `gate166_structural` correctly absent (halted, not scored).
No missing items.
