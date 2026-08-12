---
phase: 142B-frame-simulation-counterfactual-tracking
plan: 02
subsystem: database
tags: [timescaledb, batch-compute, apr, alpha-frames, counterfactual, bootstrap, scipy]

# Dependency graph
requires:
  - phase: 142B-01
    provides: alpha_frames hypertable (composite PK, no FK), AlphaFrameWriter, compute_frame_geometry (imported here)
provides:
  - CounterfactualTracker(BaseBatch) -- direction-aware FRAME-02/03 exit lifecycle + FRAME-04 day-clustered gate
  - determine_exit / compute_frame_pnl_r / frame_gate_passes / evaluate_frame_gate pure functions
  - COUNTERFACTUAL_TRACKER_IC_ROW_AGE_SECONDS observability gauge (D-10)
  - indicagent-counterfactual-tracker oneshot registration
  - todo 089 (recurring ensemble_ic_engine cadence, non-blocking follow-on)
affects: [143, 147]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Direction-aware exit state machine: a single pure function branches internally on
      direction rather than duplicating long/short logic in separate call sites -- caught
      by cross-AI review as the highest-risk defect class in this plan (review H3)"
    - "Day-clustered block bootstrap: aggregate to per-calendar-day means before resampling
      when a strategy's samples share overlapping hold horizons, falling back to an
      analytic CLT bound above a cluster-count ceiling where BCa's jackknife becomes
      infeasible (review H4)"
    - "Bar-count-scoped named-cursor sweep: one streaming pass per (symbol, tf) cell that
      terminates on a per-frame resolution condition (every open frame activated and
      closed or exhausted its own hold window), never a wall-clock WHERE-range (review L3c)"

key-files:
  created:
    - tests/unit/test_counterfactual_tracker_exit_priority.py
    - tests/unit/test_frame_gate.py
    - tests/unit/test_counterfactual_tracker.py
    - .planning/todos/pending/089-ensemble-ic-engine-recurring-cadence.md
  modified:
    - services/counterfactual_tracker.py
    - src/observability/metrics.py
    - services/service_auditor.py

key-decisions:
  - "determine_exit takes a mandatory direction parameter and inverts the stop/target bar
    comparisons for direction='short' (stop above entry, target below) -- the single most
    important fix identified by cross-AI review (H3); a long-only implementation would have
    closed every short frame as an instant false stop-out"
  - "ATR is computed causally from market_data_ohlcv inside the same named-cursor sweep that
    scans the exit path -- the rolling true-range window is advanced AFTER each frame's own
    activation check, so a frame's ATR reflects only bars <= its own bar_ts (review H2)"
  - "FRAME-04's gate aggregates pnl to per-calendar-day cluster means before bootstrapping
    (day-clustered block bootstrap), switching to an analytic one-sided 95% CLT bound above
    alpha.scoring.bootstrap_max_n clusters where BCa's jackknife becomes infeasible (review H4)"
  - "--evaluate-gate is a CLI branch of CounterfactualTracker, not a third service -- keeps
    ROADMAP's 2-service Phase 142B scope; it is read-only (no alpha_frames writes, no D-06
    job_completed_total emission)"
  - "Gap-through stop fills settle at the worse of (bar.open, stop_price) -- the same
    executable-returns discipline as Invariant 1, applied to frame exits (review L2)"

patterns-established:
  - "Pattern: worker returns list[dict] rows with extra observability-only fields (symbol,
    tf, regime, a staleness timestamp) alongside the persistence columns; the main process
    strips to the write-column subset for the UPDATE and separately consumes the
    observability fields for gauge instrumentation -- keeps workers metric-free (DAG
    invariant #3) without a second round trip"

requirements-completed: [FRAME-02, FRAME-03, FRAME-04]

# Metrics
duration: ~20min
completed: 2026-07-10
---

# Phase 142B Plan 02: CounterfactualTracker Summary

**CounterfactualTracker(BaseBatch): direction-aware FRAME-02/03 four-trigger exit state machine (with mandatory short-frame coverage per review H3) scoring each alpha_frames row in one causal named-cursor sweep per (symbol, tf) cell, plus a `--evaluate-gate` day-clustered block-bootstrap FRAME-04 exit gate on gross counterfactual_pnl_r.**

## Performance

- **Duration:** ~20 min (implementation) + ~11.5 min full-suite verification
- **Started:** 2026-07-10T10:43:00Z
- **Completed:** 2026-07-10T11:00:00Z
- **Tasks:** 3
- **Files modified:** 7 (4 created, 3 modified)

## Accomplishments

- `determine_exit` implements the FRAME-02/03 four-trigger priority state machine
  (stop > target > max_hold > ic_decay) as a DIRECTION-AWARE pure function: for
  `direction='short'` the stop check is `bar.high >= stop_price` (stop above entry) and the
  target check is `bar.low <= target_price` (target below entry), with gap-through fills at
  the worse of `(bar.open, stop_price)` mirrored for both directions. Mandatory short-frame
  unit coverage (stop-hit, target-hit, both-hit-same-bar, gap-through) proves the review H3
  bug class is closed, not just long-side behavior.
- `compute_frame_pnl_r` and `frame_gate_passes` (FRAME-04) are separate pure functions:
  the gate aggregates frame `pnl_r` to per-calendar-day cluster means before resampling
  (`scipy.stats.bootstrap(method='BCa', alternative='greater', batch=...)` below
  `alpha.scoring.bootstrap_max_n` day-clusters, an analytic one-sided 95% CLT bound above
  it) -- proven day-clustering-vs-naive-per-frame stricter-CI and analytic-path unit tests
  cover review H4.
- `CounterfactualTracker(BaseBatch)` fills `alpha_frames` geometry (T+1 open entry + causal
  price-unit ATR via a rolling true-range window fed from `market_data_ohlcv`, never
  `feature_vectors`) and scores each open frame's exit in ONE streaming named
  (server-side) psycopg2 cursor sweep per `(symbol, tf)` cell -- no per-frame round-trip
  (review H2/M2/M4). `ProcessPoolExecutor` dispatches one worker per symbol; each worker
  returns `list[dict]` rows only and never opens a write connection (DAG invariant #3).
- `_flush_worker_results` writes each worker's rows via ONE per-symbol async
  `executemany` as results arrive from `exe.map()` -- never an all-symbols aggregate write
  (T-142B-08, the write-side twin of the named-cursor anti-OOM fix); proven by a
  3-batches-to-3-`executemany`-calls mock test. The `_UPDATE_SQL` keys on
  `(frame_id, bar_ts)` with a `status = 'open'` immutability guard (review M3) -- a re-run
  never re-closes an already-closed frame.
- The IC-decay trigger reads the most-recent `alpha_ensemble_ic` row per `(symbol, tf,
  regime)` regardless of its age (D-08); `COUNTERFACTUAL_TRACKER_IC_ROW_AGE_SECONDS`
  (`src/observability/metrics.py`) makes that staleness observable from the main process
  (D-10), keeping workers metric-free.
- `--evaluate-gate` is a read-only CLI branch (not a third service) that filters
  `bar_ts < alpha.validation.oos_start`, `frame_variant = 'primary'`, closed frames only,
  groups by `(tf, regime)` via the pure `evaluate_frame_gate` helper (per-frame calendar
  date as `cluster_id`, gross-only per D-01 -- the helper's source contains no `cost`
  substring, grep-enforced), and logs a per-cell verdict + phase roll-up.
- `indicagent-counterfactual-tracker` registered as a oneshot in `service_auditor.py`
  (`_DAG_ORDER` priority 8, `_ONESHOT_UNITS`), mirroring `indicagent-alpha-frame-writer`.
- Todo 089 filed: recurring `ensemble_ic_engine` cadence, explicitly out of scope for this
  phase (D-09), referencing the new staleness gauge as its observability hook.

## Task Commits

1. **Task 1: Pure-fn cores -- determine_exit (direction-aware), compute_frame_pnl_r, frame_gate_passes (day-clustered), IC-staleness gauge** - `befd127d` (feat)
2. **Task 2: CounterfactualTracker service -- single-sweep ATR+geometry+scan per cell, per-symbol serial write** - `43060053` (feat)
3. **Task 3: FRAME-04 gate evaluation mode (day-clustered) + D-10 follow-on todo** - `058ba6fc` (feat)

_No separate plan-metadata commit -- this is a worktree-isolated parallel executor run; the
orchestrator handles STATE.md/ROADMAP.md updates centrally after merge (per its
instructions, not a deviation)._

## Files Created/Modified

- `services/counterfactual_tracker.py` - `CounterfactualTracker(BaseBatch)`, `determine_exit`, `compute_frame_pnl_r`, `frame_gate_passes`, `evaluate_frame_gate`, worker + write-path helpers, `--backfill`/`--evaluate-gate` CLI (839 lines)
- `src/observability/metrics.py` - `COUNTERFACTUAL_TRACKER_IC_ROW_AGE_SECONDS` point gauge
- `services/service_auditor.py` - registered `indicagent-counterfactual-tracker` in `_DAG_ORDER` (priority 8) and `_ONESHOT_UNITS`
- `tests/unit/test_counterfactual_tracker_exit_priority.py` - direction-aware exit-priority + pnl-sign coverage, mandatory short-frame cases (25 tests)
- `tests/unit/test_frame_gate.py` - day-clustered block-bootstrap gate coverage, wider-CI-when-clustered proof, analytic-CLT-path proof (6 tests)
- `tests/unit/test_counterfactual_tracker.py` - worker write-free contract, incremental-flush mock test, UPDATE-key guard, gate-evaluation helper coverage, service registration (14 tests)
- `.planning/todos/pending/089-ensemble-ic-engine-recurring-cadence.md` - D-10 follow-on todo

## Decisions Made

None beyond what the plan already specified. The plan's action text had already
incorporated all four cross-AI review fixes (H2 ATR source, H3 direction-aware exits, H4
day-clustered/analytic-fallback bootstrap, L2/L3/M2/M3/M4 executable-fill and
single-sweep/UPDATE-key corrections); this execution implemented those as written. One
genuine implementation judgment call not dictated by the plan text: the bar-path scan's
termination condition uses a per-frame resolution predicate (every open frame in the cell
activated-and-closed or exhausted its own hold window) rather than a precomputed row
`LIMIT`, satisfying the "bar-count-scoped, not wall-clock arithmetic" requirement (review
L3c) without needing to estimate an upfront bar-count budget from open-frame density.

## Deviations from Plan

None (Rules 1-3 auto-fixes only, all within normal execution housekeeping):

- **[Rule 1 - Bug] Self-inflicted test-authoring bug fixed before commit, not a deviation
  from the plan's design:** the module docstring's own explanatory text initially
  contained the literal substring `feature_vectors`, which would have failed the plan's
  own Task 2 acceptance grep (`grep -c "feature_vectors" services/counterfactual_tracker.py`
  returns 0). Reworded to "feature-vector corpus's normalized ATR derivatives" before the
  Task 2 commit -- caught during Task 2's own acceptance-criteria verification, never
  landed in a commit with the literal string present at Task-2-acceptance-check time. Not
  tracked as a plan deviation since it never affected the design, only prose wording.
- **[Rule 1 - Bug] `frame_gate_passes`'s analytic-CLT branch returned a NumPy `bool_`
  instead of a Python `bool`**, which failed an `is True`/`is False` identity assertion in
  its own RED-phase unit test. Fixed with an explicit `bool(...)` cast before the Task 1
  commit; caught by the test itself, not discovered after the fact.
- **[Rule 3 - Blocking] `.venv` symlink missing in this worktree** (worktrees do not carry
  their own virtualenv) blocked the repo's pre-commit hook's ruff/black checks
  (`${REPO_ROOT}/.venv/bin/ruff` not found). Symlinked `.venv -> /home/bg/dev/indicagent/.venv`
  (gitignored, no tracked-file impact) before the first commit; this is worktree-local
  environment setup, not a code or plan change.

## Issues Encountered

None. All three tasks' automated verification passed on first or second attempt (the two
self-caught bugs above were fixed inline before their respective task commits, per the
deviation-rules "fix inline, verify, continue" protocol). Full `tests/unit/` suite run
after all three tasks: 5644 passed / 42 skipped / 1 failed -- the failure is the
pre-existing, already-tracked `test_feature_factory.py::TestRegimePrimitives::
test_no_smooth_or_backward_in_factory` (todo-086 false positive, present before this plan's
changes per Plan 01's own summary) -- no new failures introduced.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `CounterfactualTracker` and its `--evaluate-gate` mode are both implemented, tested, and
  registered. Per the plan's `<post_execution>` note, the FRAME-04 verdict itself is NOT
  produced by this plan's tasks -- it requires manual ops runs against the live
  12.2M-row `alpha_events` corpus (matching Phase 142A's EIC-04 precedent). The remaining
  operational sequence, not yet run:
  1. `python services/alpha_frame_writer.py --backfill`
  2. `python services/counterfactual_tracker.py --backfill`
  3. `python services/counterfactual_tracker.py --evaluate-gate`
  4. Record the per-(tf, regime) pass/fail verdict + `net_expected_r` reporting column in
     project memory / the Corpus pipeline state doc.
- No stubs: every code path in `CounterfactualTracker` is fully wired (no hardcoded empty
  return values, no placeholder text, no unconnected data source). The `--evaluate-gate`
  CLI branch is a genuine read-only query path, not a stub.

## Self-Check: PASSED

All created files verified present on disk; all three task-commit hashes (`befd127d`,
`43060053`, `058ba6fc`) verified present in `git log --oneline --all`.

---
*Phase: 142B-frame-simulation-counterfactual-tracking*
*Completed: 2026-07-10*
