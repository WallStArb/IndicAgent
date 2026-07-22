---
phase: 148-alpha-scoring-system-planned
plan: 05
subsystem: measurement
tags: [oos-gate, forward-returns, blocker, run-once-safety]

# Dependency graph
requires:
  - phase: 148-03
    provides: scripts/ops/corpus/ops_oos_gate1_signal_eval.py (Gate 1, unrun)
  - phase: 148-04
    provides: scripts/analysis/score03_gate2_execution_eval.py (Gate 2, unrun)
provides:
  - Diagnostic evidence that Gate 1's required substrate (OOS-side forward_returns) does
    not exist in the live DB -- discovered via the plan's own mandated --dry-run pre-flight,
    before any irreversible action was taken
affects: [148-05-retry, any-future-phase-touching-forward_return_writer]

# Tech tracking
tech-stack:
  added: []
  patterns: []

key-files:
  created: []
  modified: []

key-decisions:
  - "STOPPED before running either irreversible one-shot gate (D-04) after Gate 1's mandated --dry-run pre-flight surfaced input_population_row_count=0 across the ENTIRE active universe (0 of 0 symbols have any forward_returns row with bar_ts >= alpha.validation.oos_start), not the partial/sparse insufficient-N the plan anticipated -- per the plan's own critical_warning, an unexpected dry-run result is grounds to stop and report, not force through an irreversible action under uncertainty"
  - "Did not attempt to auto-fix by running forward_return_writer.py for the OOS window myself -- that is a new, previously-unscoped infrastructure operation (not in this plan's files_modified, not reviewed by 148-REVIEWS.md, not mentioned in 148-CONTEXT.md's D-02/D-03/D-04), touches the exact discipline docs/plans/OOS-EVAL-PROTOCOL.md exists to gate deliberately, and its correct invocation shape (training-window-end value, symbol/tf scope, orchestrator vs. direct invocation) requires a judgment call outside this plan's authority -- classified as Rule 4 (architectural/scope decision), not Rule 3 (mechanical blocking fix)"
  - "Did not run Gate 2 either, even though it has no forward_returns dependency and its own --dry-run would likely succeed -- D-02 requires Gate 1 to run strictly before Gate 2, and Gate 1 cannot meaningfully run for real in its current state; running Gate 2 first would violate the plan's own sequencing invariant"

requirements-completed: []

# Metrics
duration: ~35min (investigation only; no irreversible action taken)
completed: 2026-07-22
---

# Phase 148 Plan 05: OOS Gate Promotion Decision Summary

**BLOCKED before either irreversible gate ran: Gate 1's mandated --dry-run pre-flight found `forward_returns` has zero rows (0 of 0 symbols) with `bar_ts >= alpha.validation.oos_start` across every timeframe, despite raw bar data existing 7+ months past that boundary -- the OOS holdout clamp built in Phase 141.1 has apparently never been overridden to compute forward_returns for the OOS side, so Gate 1's join against `forward_returns` can never return a row today. Both one-shot gates remain unconsumed; `gate_evaluations` is still empty.**

## Performance

- **Duration:** ~35 min (investigation; no writes attempted)
- **Started:** 2026-07-22T~20:15Z
- **Completed:** 2026-07-22T20:50:06Z
- **Tasks:** 0/3 completed (Task 1 halted mid-pre-flight; Tasks 2/3 not attempted, both depend on Task 1)
- **Files modified:** 0 (read-only DB queries only; this SUMMARY.md is the only new file)

## What Was Attempted

Per the plan's mandatory sequence, Task 1's PRE-FLIGHT step was run first: `.venv/bin/python
scripts/ops/corpus/ops_oos_gate1_signal_eval.py --dry-run` (default universe: all active
contracts x `5m`/`15m`/`1h`/`1d`). Pre-run baseline was captured first per the outer guard:
`gate_evaluations` was empty (0 rows for both `gate1_signal` and `gate2_execution`),
`alpha_ensemble_ic` had 2186 rows (unrun-since baseline), no `.planning/gate_look_log.jsonl`
existed yet, and `alpha.validation.oos_start` = `2025-12-24T05:15:00Z`.

The dry-run completed cleanly (no crash) but returned:
```json
{
  "gate_id": "gate1_signal",
  "result": "insufficient",
  "evidence": {
    "cells": [],
    "snapshot": { "input_population_row_count": 0, ... },
    "verdict": {
      "result": "insufficient",
      "reason": "zero (symbol, tf, scale) cells computed from the OOS population",
      "n_cells": 0
    }
  }
}
```

This is qualitatively different from what the plan's own `<action>` text anticipated ("Expect a
meaningful fraction of OOS cells to return walk_forward_stable=None or insufficient-N because
the OOS window is much shorter than the in-sample history") -- that describes *partial*
insufficiency across some cells, not a fully empty population across the entire universe.

## Root Cause (verified empirically, not guessed)

`ops_oos_gate1_signal_eval.py`'s fetch query joins `ensemble_alpha` to `forward_returns` (on
`symbol`/`tf`/`bar_ts`, filtered to `return_type = 'executable_open_to_open'`) and to
`market_regimes`. Isolated each join to find where the population collapses to zero:

- `ensemble_alpha` HAS abundant OOS-side data: 659,522 rows across the active universe for
  `bar_ts >= 2025-12-24T05:15:00Z` (weight_version `run_2025122405150000`, the value the live
  `alpha.ensemble.weight_version` APR key currently resolves to); `alpha_ensemble_ic`-adjacent
  weight_versions `143.1-08-champion`/`143.1-08-challenger` show the same OOS coverage (max
  `bar_ts` 2026-07-07 for both).
- `market_regimes` HAS OOS-side data: 56,264 rows for `regime_group='equity'`, `tf='5m'`,
  `ts >= oos_start` alone.
- `forward_returns` HAS ZERO rows anywhere with `bar_ts >= oos_start`, for any symbol, any
  timeframe, any of the 320 registered (symbol, tf) pairs. Confirmed via
  `SELECT count(DISTINCT symbol) FROM forward_returns WHERE return_type='executable_open_to_open'
  AND bar_ts >= '2025-12-24T05:15:00Z'` = **0**. Per-timeframe `max(bar_ts)`:

  | tf  | max(bar_ts) in forward_returns | vs. oos_start (2025-12-24T05:15:00Z) |
  |-----|-------------------------------|---------------------------------------|
  | 5m  | 2025-12-23 20:55:00+00 | before |
  | 15m | 2025-12-23 20:45:00+00 | before |
  | 1h  | 2025-12-23 20:00:00+00 | before |
  | 1d  | 2025-12-24 00:00:00+00 | before (by 5h15m) |

  Meanwhile raw tradeable bar data (`market_data_ohlcv_tradeable`) extends to 2026-07-07
  16:45:00+00 (5m) -- **over 7 months past `oos_start`** -- and the largest configured IC
  lookahead (`alpha.ic.lookahead.extended` = 60 bars) cannot explain a multi-month gap; a
  60-bar lookahead would only trim the last few hours/days of coverage, not everything past
  the OOS boundary itself.

This matches exactly what `docs/plans/OOS-EVAL-PROTOCOL.md` documents as the intended
enforcement mechanism from Phase 141.1: the corpus orchestrator clamps
`--training-window-end` passed to `forward_return_writer.py` to `min(MAX(bar_ts), oos_start)`,
and `forward_return_writer.py` has no bare-`MAX(bar_ts)` fallback (by design, to prevent
silent OOS leakage into training). The practical consequence, apparently never previously
exercised: **no process has ever computed `forward_returns` for `bar_ts >= oos_start`.** The
column exists and is well-populated for the entire in-sample history, but the OOS side is not
merely sparse -- it is completely absent, for every symbol and timeframe.

Gate 1 (SCORE-02) as built requires exactly this OOS-side `forward_returns` data to measure
IC out-of-sample. With zero rows available, Gate 1's real (non-dry-run) invocation would
write a `result='insufficient'` row that reflects "no forward-return labels exist for this
window," not "there is a signal-proof answer, positive or negative." Spending the one
irreversible run (D-04, never re-runnable for this milestone) on that empty, uninformative
outcome would foreclose the actual signal-proof question this phase exists to answer.

## Why I Stopped Instead Of Proceeding

Per the plan's `<critical_warning>`: "If the dry-run pre-flight surfaces anything unexpected
... STOP and report back rather than proceeding to the real run -- do not attempt to force
through an irreversible action under uncertainty." A fully empty population across every
symbol/timeframe is exactly that kind of surfaced anomaly, distinct from the "some cells
insufficient-N" scenario the plan's action text explicitly pre-authorized as expected/normal.

I considered and rejected auto-fixing by running `forward_return_writer.py` for the OOS
window myself:
- It is a new, unscoped infrastructure operation -- not in this plan's declared
  `files_modified` (`docs/plans/2026-07-22-phase148-promotion-decision.md` and
  `.planning/gate_look_log.jsonl` only), not mentioned anywhere in `148-CONTEXT.md`'s
  decisions (D-02 through D-08), and not reviewed by the cross-AI review documented in
  `148-REVIEWS.md`.
- It touches the exact discipline `docs/plans/OOS-EVAL-PROTOCOL.md` was written to gate
  deliberately -- computing OOS-side forward-return labels is arguably sanctioned (the doc's
  banned-uses list is feature selection / IC gate calibration / ensemble weighting / threshold
  tuning / hold-horizon calibration, not "computing raw labels for an OOS proof gate"), but the
  correct invocation shape is a real judgment call: what `--training-window-end` value (likely
  `MAX(bar_ts)` minus a lookahead buffer, but which buffer, and does it collide with Phase
  162's in-flight throughput refactor of adjacent corpus-pipeline code), what symbol/tf scope,
  orchestrator-driven vs. direct script invocation, and how long/expensive this backfill would
  be against a 20M+ row `ensemble_alpha` population's shadow tables.
- Since running Gate 1 for real is irreversible and permanent for this milestone (D-04), and
  the fix itself is a meaningful, previously-undiscussed scope expansion, this is a Rule 4
  (architectural/scope decision) situation, not a Rule 3 (mechanical blocking fix) -- it
  requires a decision only the user/orchestrator can make: whether and how to backfill OOS
  `forward_returns` before spending Gate 1's one shot.

Task 2 (Gate 2) was not attempted either. D-02 requires Gate 1 to run strictly before Gate 2,
and Gate 1 cannot meaningfully produce a real verdict right now -- running Gate 2 first (even
though it has no `forward_returns` dependency and would likely dry-run cleanly against
`alpha_frames`) would violate the plan's own sequencing invariant. Task 3 (the promotion
decision record) was not attempted since it depends on both gates' real verdicts.

## Current State (verified, not assumed)

- `gate_evaluations`: 0 rows (both `gate1_signal` and `gate2_execution` untouched)
- `.planning/gate_look_log.jsonl`: does not exist (Gate 1's `--dry-run` writes nothing, as
  designed and verified)
- `alpha_ensemble_ic`: 2186 rows, unchanged from pre-run baseline
- No files were created or modified by this session other than this SUMMARY.md
- Both gate scripts (`scripts/ops/corpus/ops_oos_gate1_signal_eval.py`,
  `scripts/analysis/score03_gate2_execution_eval.py`) remain exactly as built by 148-03/148-04
  -- unmodified, unrun for real, both one-shot gates still available to consume once the
  prerequisite is resolved

## Deviations from Plan

None in the sense of unplanned code changes -- no code was written or modified. The deviation
is procedural: Tasks 1-3 were not executed because Task 1's own mandated safety pre-flight
(the `--dry-run` pre-flight the plan itself requires before consuming the one-shot) surfaced a
blocking prerequisite gap. This is the plan's own safety mechanism working as designed, not a
bug in the plan or the 148-03/148-04 scripts.

## Issues Encountered

**Blocking (not auto-fixed, escalated):** `forward_returns` has zero OOS-side coverage
(`bar_ts >= alpha.validation.oos_start`) for every symbol and timeframe, discovered via
Gate 1's `--dry-run` pre-flight. Root-caused to the Phase 141.1 OOS-holdout clamp on
`forward_return_writer.py` apparently never having been overridden to compute the OOS side.
See "Root Cause" and "Why I Stopped" above for full diagnostic evidence and reasoning.

## Recommended Next Step (not executed here -- requires a decision)

Before this plan can produce a real Gate 1 verdict, `forward_returns` needs OOS-side coverage
(`bar_ts >= 2025-12-24T05:15:00Z`) for the active universe across `5m`/`15m`/`1h`/`1d`. This
requires an explicit, reviewed decision on:
1. Whether computing OOS-side `forward_returns` labels is in fact sanctioned under
   `OOS-EVAL-PROTOCOL.md`'s discipline (my reading above is that it is -- labels are not
   themselves feature selection/calibration/tuning -- but this should be confirmed, not
   assumed, given the doc's explicit "no post-hoc renegotiation" framing).
2. The correct invocation: likely `forward_return_writer.py --training-window-end
   <MAX(bar_ts) minus lookahead buffer>` scoped to the active contract universe, run once,
   read-only afterward by Gate 1.
3. Whether this collides with Phase 162 (ic_engine Corpus Pipeline Throughput), which is
   in-flight/planned against adjacent corpus-pipeline code paths.

Once resolved and `forward_returns` has real OOS coverage, this plan (148-05) can be re-run
from Task 1's `--dry-run` pre-flight forward -- nothing consumed here needs to be undone.

## Next Phase Readiness

Not ready. This is the phase's terminal deliverable plan and it did not produce the milestone
verdict. `docs/plans/2026-07-22-phase148-promotion-decision.md` was NOT created (Task 3 never
reached). Phase 148 remains open pending resolution of the `forward_returns` OOS-coverage gap
above.

## Self-Check: PASSED

Verified no unintended file changes: `git status --short` shows only this new SUMMARY.md file
(plus the pre-existing gitignored `.venv` symlink). Verified `gate_evaluations` is still 0
rows for both gate IDs and `.planning/gate_look_log.jsonl` does not exist -- confirming zero
irreversible actions were taken. Verified the diagnostic queries in this document are
reproducible against the live DB as reported above.

---
*Phase: 148-alpha-scoring-system-planned*
*Completed: 2026-07-22 (blocked, not executed)*
