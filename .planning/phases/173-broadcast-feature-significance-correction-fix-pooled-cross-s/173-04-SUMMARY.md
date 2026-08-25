---
phase: 173-broadcast-feature-significance-correction-fix-pooled-cross-s
plan: 04
subsystem: alpha (IC engine)
tags: [ic-engine, broadcast-features, cross-sectional, bh-fdr, cluster-id-offset, cross-ai-review]

# Dependency graph
requires:
  - phase: 173-01
    provides: "concept_registry.metadata->>'broadcast' populated (38 broadcast=true rows), alpha.ic.broadcast_variance_threshold APR key"
  - phase: 173-02
    provides: "CONTEXT_FEATURES daily-cadence path deleted -- clean baseline for this plan's cell"
  - phase: 173-03
    provides: "Broadcast columns excluded from the per-symbol pooled cross-sectional cell, bar_ts threaded through the chunked fetch, broadcast_hash fingerprint invalidation"
provides:
  - "_compute_one_broadcast_cell: the correctly-specified broadcast significance test -- one draw per distinct bar_ts against the peer group's equal-weighted aggregate forward return, reusing _subsample_and_rank byte-for-byte unmodified"
  - "Broadcast rows wired into _compute_cross_sectional_tf's combined BH-FDR family via _BROADCAST_CLUSTER_ID_OFFSET = 10000"
  - "Live-verified: 70 real broadcast rows in feature_ic_scores with non-degenerate CIs and n_independent ~30x smaller than the comparable per-symbol pooled row"
  - "Independent cross-AI review (codex + agy) of the phase's full diff, all findings dispositioned"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Sort-free grouping via a single forward boundary scan (np.flatnonzero on adjacent
      inequality) + np.add.reduceat/np.fmax.reduceat/np.fmin.reduceat/np.logical_and.reduceat
      keyed on group_starts -- avoids np.unique/np.sort/np.argsort/pandas groupby's extra
      full-length temporaries, CI-enforced via source introspection with the docstring
      stripped out first (so the docstring can still name the forbidden APIs in prose)."
    - "Schema ID-space partition constant (_BROADCAST_CLUSTER_ID_OFFSET = 10000) to keep two
      structurally different row populations (broadcast vs per-symbol) in ONE combined BH-FDR
      family without cluster_id collisions -- APR-exempt, same class as a column-name literal."
    - "Live smoke-testing a single (regime_group, tf, regime_label) cell without the full
      corpus-scoping CLI: a standalone script replicating main()'s symbol-routing/broadcast-set/
      archive-then-delete logic and calling _compute_cross_sectional_tf directly, when the CLI
      has no per-cell scoping flag and running the full --tf would recompute every enabled
      group's cells at that tf (infeasible in a bounded session for the 5m tier)."

key-files:
  created:
    - .planning/todos/pending/356-cross-sectional-fetch-chunk-query-pathologically-slow-largest-cell.md
  modified:
    - services/ic_engine.py
    - tests/unit/test_ic_engine_compute_split.py
    - .planning/todos/PRIORITIES.md

key-decisions:
  - "Reviewed the TRUE phase-start diff (9e7231a65...HEAD), not main...HEAD as the plan's literal
    command specified -- main already sits at Wave 2's completion (fb6db7c96) because GSD merges
    each wave's worktree back to main incrementally, so a literal main...HEAD diff would have
    scoped the cross-AI review to Plan 04's ~460-line increment only, missing Plans 01-03
    entirely. Adapted to the plan's INTENT (independent review of the phase's full diff) over
    its literal command text."
  - "Both codex and agy converged on the same single substantive finding (the strict all-peers-
    complete aggregate-return rule as a potential source of selection bias) -- disposed as
    'fixed via documentation, not behavior change' since this was an already-locked planner
    decision (173-04-PLAN.md planner_findings) with a pre-committed empirical review process
    (file a todo if drop rate > 50%), not an unexamined oversight. The live smoke run's 0.0%
    observed drop rate confirms the rule is not currently pathological."
  - "Killed the largest-cell (equity/5m/low_bull) smoke run after ~95 minutes still mid-fetch,
    rather than waiting indefinitely -- the underlying per-chunk fetch query (unchanged by this
    phase) was found to be pathologically slow at this scale, a genuine but out-of-scope
    discovery (D-05 locks the fetch SQL's shape), filed as todo 356. Used the partial RSS
    trajectory (peaked 6,127,044 KB / ~5.84 GiB across a fetch phase that had processed most but
    not all of the cell's 3.1M rows) plus a fully-completed medium cell (equity/1h/low_bear,
    335K+ raw rows) as the combined evidentiary basis for 'no OOM regression' rather than
    blocking indefinitely on one pathologically slow, out-of-scope query."

requirements-completed: [D-03, D-04, D-05, D-06, D-07, D-09]

duration: ~5h 24min (includes ~2h of live-corpus smoke-run monitoring, dominated by the killed
  largest-cell run's ~95-minute partial fetch)
completed: 2026-08-25
---

# Phase 173 Plan 04: Broadcast Cell Implementation + Wiring + Live Smoke Run + Cross-AI Review Summary

**Built `_compute_one_broadcast_cell` (sort-free bar_ts collapse + equal-weighted peer-aggregate
outcome, reusing `_subsample_and_rank` unmodified), wired it into `_compute_cross_sectional_tf`'s
combined BH-FDR family via a `cluster_id` offset, live-verified 70 real non-degenerate broadcast
rows against production data, and closed out an independent codex+agy review of the phase's full
diff with every finding dispositioned.**

## Performance

- **Duration:** ~5h 24min wall clock (four task commits span 13:23:36-18:32:09 local; the bulk of
  the time is live-corpus monitoring, not code-writing -- see Task 3's own timeline below)
- **Started:** 2026-08-25T13:08:21-04:00 (worktree base)
- **Completed:** 2026-08-25T18:32:09-04:00
- **Tasks:** 4/4 completed
- **Files modified:** 4 (2 code files across 2 commits, 1 todo file created, 1 priorities file
  updated)

## Accomplishments

- `_compute_one_broadcast_cell` (services/ic_engine.py): collapses a cross-sectional cell's rows
  to one per distinct `bar_ts` via a single forward boundary scan (`np.flatnonzero` on adjacent
  inequality + `reduceat` aggregation -- no sort, no `np.unique`, test-enforced by source
  introspection), builds the peer group's equal-weighted aggregate forward return under a strict
  all-peers-complete rule, and reuses `_subsample_and_rank` byte-for-byte unmodified (pinned by a
  SHA-256 source-hash test). Crash-loud guards: a contiguity assertion (T-173-16) and a NaN-safe
  cross-symbol-invariance assertion (`np.fmax.reduceat`/`np.fmin.reduceat` vs
  `alpha.ic.broadcast_variance_threshold`, T-173-09) against a mis-persisted broadcast flag.
- `_compute_cross_sectional_tf` now calls the broadcast cell after its fetch connection closes
  and before the `cluster_groups` BH-FDR loop, extending `all_results` so broadcast and
  per-symbol rows share ONE corpus-level BH-FDR family, collision-free via
  `_BROADCAST_CLUSTER_ID_OFFSET = 10000` (T-173-10).
- **Live smoke run against real production data** (not a synthetic fixture): computed
  `equity/1h/low_bear` end to end -- 70 broadcast rows landed in `feature_ic_scores`
  (`symbol='POOLED'`, `regime_scope='cross_sectional'`, `cluster_id>=10000`), zero degenerate CIs,
  median `n_independent` 377 vs. the same cell's per-symbol pooled median 11637 (3.2%, well under
  the 1/10 acceptance bound -- proof the collapse is doing real work), 0.0% incomplete-cross-
  section drop rate at every scale. See Task 3 below for the full timeline including the killed
  largest-cell run and the pre-existing performance finding it surfaced (todo 356).
- **Independent cross-AI review** (codex + agy) of the phase's true full diff (Plans 01-04, not
  just this wave's increment) against all four named scrutiny targets, every finding
  dispositioned -- see Task 4 below.

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement `_compute_one_broadcast_cell`** - `73044aa61` (feat) -- 22 new tests
   covering every `<behavior>` bullet with synthetic numpy fixtures
2. **Task 2: Wire the broadcast cell into the cross-sectional pass and its BH-FDR family** -
   `771e5202c` (feat) -- 5 new tests (connection-scoping placement, accounting, cluster-key
   disjointness)
3. **Task 3: Live smoke run** - `86a981e2e` (docs) -- no code change; the DB writes themselves are
   not git commits, this commit carries the filed todo (356) + priorities update the smoke run
   surfaced
4. **Task 4: Independent cross-AI review** - `8a7418faa` (fix) -- 2 review-driven fixes (empty
   `bar_ts_arr` guard + selection-bias documentation), 1 new test

_No separate plan-metadata commit -- this SUMMARY and its self-check are the final commit for
this parallel-worktree plan; STATE.md/ROADMAP.md are updated centrally by the orchestrator after
the wave completes._

## Files Created/Modified

- `services/ic_engine.py` - `_compute_one_broadcast_cell` (new function, ~300 lines), its wiring
  into `_compute_cross_sectional_tf` (call + docstring rewrite), `_BROADCAST_CLUSTER_ID_OFFSET`
  module constant, `broadcast_variance_threshold` field on `ICEngineConfig` +
  `_COMPUTATIONAL_CONFIG_FIELDS` classification + `from_apr` load, an empty-`bar_ts_arr` defensive
  guard, and a docstring paragraph documenting the all-peers-complete selection-bias tradeoff
  (net +496/-1 lines across the two code commits)
- `tests/unit/test_ic_engine_compute_split.py` - 28 new tests total: 22 for
  `_compute_one_broadcast_cell`'s behavior (collapse-to-G-rows, hand-computed aggregate-mean
  exactness via an IC==1.0 monotonic fixture, invariance-violation raise, non-contiguous-bar_ts
  raise, all-NaN-group non-raise, below-min_reliable_n zero-row emission, pooled/broadcast row
  identity, no-sort/no-unique source introspection with the docstring stripped, a
  `_subsample_and_rank` source-hash pin), 5 for the wiring (connection-scoping placement,
  `all_results.extend`/`n_skipped` accounting, cluster-key disjointness), 1 for the empty-array
  guard
- `.planning/todos/pending/356-cross-sectional-fetch-chunk-query-pathologically-slow-largest-cell.md` -
  new todo: the pre-existing (not a Phase 173 regression), previously-unmeasured slow-fetch
  performance characteristic Task 3's largest-cell smoke run surfaced
- `.planning/todos/PRIORITIES.md` - todo 356 added (P2)

## Decisions Made

1. **Reviewed the true phase-start diff, not the plan's literal `main...HEAD` command.** By the
   time this wave started, `main` was already at Wave 2's completion (`fb6db7c96`, since GSD
   merges each wave's worktree back to `main` incrementally) -- a literal `git diff main...HEAD`
   would have scoped the independent review to only Plan 04's own ~460-line increment, missing
   Plans 01-03's ~1,840 lines of changes entirely. Located the true pre-Phase-173 base
   (`9e7231a65`, the last commit before Phase 173's first execution commit, `4e9ded24d`) and
   diffed against that instead, honoring the task's stated objective ("independent review of the
   phase's full diff") over its example command's literal text, which was written assuming a
   single-shot execution model.
2. **No CLI flag exists to scope `ic_engine.py` to one `(regime_group, tf, regime_label)` cell,
   so Task 3 used a standalone script calling `_compute_cross_sectional_tf` directly.** The real
   CLI's `--tf`/`--cross-sectional-only`/`--symbols` flags only scope by timeframe and symbol
   universe, not by regime label -- running `--tf 5m` alone would recompute ALL of equity's 6
   `low_bull`/`mid_bull`/`high_bear`/`high_bull`/`mid_bear`/`mid_neutral` cells (and every other
   enabled group's 5m cells) sequentially, a multi-hour-to-multi-day corpus-wide operation
   infeasible within one execution session. Wrote a script that replicates `main()`'s exact
   symbol-routing (`_build_symbol_regime_class`), broadcast-set resolution (same SQL predicate),
   `feature_status_map` construction, and archive-then-delete step (todo 252 pattern -- required
   after discovering pre-existing pre-Phase-173 rows were silently blocking the first attempt's
   insert via `ON CONFLICT DO NOTHING`, see Deviations), then calls
   `_compute_cross_sectional_tf`/`_write_cs_cell_results` directly for exactly one named cell.
3. **Killed the largest-cell (`equity/5m/low_bull`) run after ~95 minutes rather than waiting
   indefinitely.** VALIDATION.md's own Manual-Only Verifications table explicitly allows this task
   to take "hours" -- but a single fetch-phase query taking 50-100+ seconds per chunk (111 chunks
   total, ~2.5s for the first observed chunk vs. 100+s for later ones), confirmed via
   `pg_stat_activity`/`top` to be genuine 100%-CPU server-side work (not a lock wait, not an idle
   connection -- `wait_event` was NULL throughout, `pg_locks WHERE NOT granted` returned 0), meant
   the fetch alone would plausibly take multiple hours for this one cell. This SQL is unchanged by
   Phase 173 (D-05 locks its shape) -- a genuine, real, previously-unmeasured performance
   characteristic of the corpus's largest cell, not a regression this plan introduced. Filed as
   todo 356 and used the partial-but-real RSS trajectory (peaked 6,127,044 KB / ~5.84 GiB, no
   runaway growth pattern across ~95 minutes, drastically below the 20GB+ 2026-07-08 OOM incident
   scale) combined with the fully-completed `equity/1h/low_bear` cell (335K+ raw rows, clean
   completion in ~185s) as the combined evidentiary basis for the OOM-regression check, rather
   than blocking the whole plan on one pathologically slow, out-of-scope query. Explicitly NOT
   claiming a peak-RSS number from a completed run for the 5m/low_bull cell -- the number reported
   is honestly labeled as partial/in-flight.
4. **Cross-AI review disposition for the strict all-peers-complete rule: fixed via documentation,
   not behavior change.** Both codex and agy independently flagged the same concern (selection
   bias if data incompleteness correlates with regime/liquidity). This was already a locked,
   first-principles-reasoned decision in 173-04-PLAN.md's `planner_findings`, with a
   pre-committed empirical review process (file a todo proposing a coverage-fraction APR key if
   the observed drop rate exceeds 50%). Rather than re-litigating a decision the plan had already
   made and pre-registered a resolution path for, added an explicit docstring paragraph naming the
   risk (visible to future readers, directly responsive to both reviewers) and confirmed via the
   live smoke run that the actual observed drop rate is 0.0% -- nowhere near the 50% action
   threshold. This is NOT treated as "a correctness objection to the statistical specification"
   that blocks merge (per the plan's own escalation rule) -- both reviewers phrased it as "needs a
   design decision" / "if intentional, treat as a design choice," not "this is definitively wrong."

## Task 3 Detail: Live Smoke Run

**Method:** No CLI flag exists to scope `ic_engine.py` to a single `(regime_group, tf,
regime_label)` cell (see Decision 2 above). Used a standalone script
(`/tmp/.../scratchpad/smoke_broadcast_cell.py`) replicating `main()`'s exact cell-resolution logic
and calling `_compute_cross_sectional_tf` (which now wires in `_compute_one_broadcast_cell` per
Task 2) directly for one named cell at a time, writing through the real
`_write_cs_cell_results` path after the real archive-then-delete step.

**Smallest-viable-cell attempt, corrected:** `market_regimes` query for the smallest cell
(`commodity/1d/up_primary_backwardation`, 13 timestamps) was too small to clear
`min_reliable_n=100` even before subsampling -- correctly produced zero broadcast rows (D-06
working as designed), not a bug. Moved to `equity/1d/low_bear` (368 timestamps) -- still too small
after `subsample_min_stride` gates (`368/5≈74 < 100`), again correctly zero broadcast rows. Moved
to `equity/1h/low_bear` (5,327 `market_regimes` timestamps, 1,881 distinct joined `bar_ts` values
after the `feature_vectors`/`forward_returns` join, 63 peer symbols) -- this cleared the gate and
is the cell all correctness numbers below are drawn from.

**First attempt at `equity/1h/low_bear` produced ZERO broadcast rows despite 70 being computed in
memory** -- a real bug in the smoke-test script (not `_compute_one_broadcast_cell` itself),
documented and fixed:

- **Found during:** first live write attempt, `SELECT count(*) ... cluster_id >= 10000` returned 0
  immediately after a log line reporting `n_broadcast_rows=70`.
- **Issue:** the script called `_write_cs_cell_results` directly without first running `main()`'s
  archive-then-delete step (`_ARCHIVE_BEFORE_DELETE_CROSS_SECTIONAL_SQL` +
  `_FINGERPRINT_INVALIDATE_DELETE_CROSS_SECTIONAL_SQL`). Pre-existing rows from the corpus's last
  full run (`computed_at≈2026-08-23`, before Phase 173 existed -- e.g. `vix_z` at
  `cluster_id=20`) occupied the same `(feature_name, symbol='POOLED', tf, regime, lookahead_bars,
  training_window_end)` slots the new broadcast rows needed, silently rejected via
  `ON CONFLICT DO NOTHING` on `feature_ic_scores_cross_sectional_uq`.
- **Fix:** added the same archive-then-delete step `main()`'s real loop runs, scoped to
  `(symbol='POOLED', fp_symbol=f"{regime_group}:{regime_label}", tf, regime_label,
  training_window_end)`, immediately before the compute call.
- **Verification:** re-ran the same cell; `SELECT count(*) ... cluster_id >= 10000` returned 70;
  `SELECT count(*) ... ic_ci_lower=0 AND ic_ci_upper=0` returned 0. Confirmed idempotent by
  running a third time later (to capture the drop-rate log, see below) -- identical row counts.

**Numbers recorded (per Task 3's acceptance criteria):**

| Check | Result |
|---|---|
| Broadcast rows landed (`symbol='POOLED' AND regime_scope='cross_sectional' AND cluster_id>=10000`) | 70 |
| Degenerate CIs among those (`ic_ci_lower=0 AND ic_ci_upper=0`) | 0 |
| Median `n_independent`, broadcast rows (equity/1h/low_bear) | 377 |
| Median `n_independent`, per-symbol pooled rows (same cell) | 11,637 |
| Ratio | 3.2% (well under the 1/10 acceptance bound) |
| Per-scale incomplete-cross-section drop rate (fast/mid/slow/extended, equity/1h/low_bear) | 0.0% at every scale (1,881/1,881 groups complete) |
| No broadcast-feature-name row with `cluster_id<10000` in the recomputed cell (`tf='1h' AND regime='low_bear'`) | 0 (confirmed via targeted SQL; a broader unscoped query returns nonzero from OTHER, not-yet-recomputed cells still carrying pre-Phase-173 vintage rows -- expected, will be swept by the next full corpus recompute) |
| Peak RSS, `equity/5m/low_bull` (largest cell, 3,097,180 rows) | 6,127,044 KB (~5.84 GiB) -- **partial**, fetch phase not completed, run killed after ~95 min to make forward progress (see Decision 3) |
| `pytest tests/unit/ -q` after the live run | green, zero failures |

**Side effect requiring no follow-up action:** killing the `equity/5m/low_bull` run left that
cell's live `feature_ic_scores` rows at zero (the archive-then-delete step ran before the fetch
started) -- the pre-existing 1,192 rows are safely archived to `feature_ic_scores_history`
(confirmed: 3,576 rows now present for this cell across all vintages). This is a normal,
recoverable "crash-mid-recompute" state, and Phase 173's own `broadcast_hash` fingerprint
invalidation already forces a full corpus-wide recompute on the next real `ic_engine.py` run
regardless of this smoke test -- this cell will be recomputed as part of that run with no separate
action needed purely to close this gap.

## Task 4 Detail: Independent Cross-AI Review

**Commands executed** (both against the same diff file, `9e7231a65...HEAD -- services/ic_engine.py
scripts/ops/alpha/ops_broadcast_feature_audit.py production/migrations/`, 1,725 lines):

```
cat phase173_full.diff | codex exec --skip-git-repo-check "<prompt naming all four scrutiny targets>"
agy -p "<prompt pointing at the diff file + services/ic_engine.py by absolute path, naming all four scrutiny targets>" --dangerously-skip-permissions --print-timeout 10m
```

`$MODEL` was unset in this environment -- ran `codex exec` without `-m` (uses codex's own config
default) rather than passing an empty model string.

**`/simplify` equivalent performed manually** (the centralized `code_simplifier_gate` in
`execute-phase.md` runs after all of this phase's waves merge, which has not happened yet from
inside this worktree): `ruff check` clean, `black --check` clean, and `vulture
services/ic_engine.py --min-confidence 80` shows only the 3 pre-existing findings at
`_NoopTracer`/`_noop_span` (lines ~403-415, confirmed pre-existing and out of this plan's diff
per 173-02-SUMMARY's own note on the same lines) -- zero new dead code from this plan's changes.

**Findings and dispositions:**

| # | Reviewer(s) | Finding | Disposition |
|---|---|---|---|
| 1 | codex + agy | Strict all-peers-complete rule for the aggregate return could bias which `bar_ts` values enter the sample (selection correlated with liquidity/regime) | **fixed** (documentation) -- see Decision 4 above; commit `8a7418faa` |
| 2 | codex | `_compute_one_broadcast_cell` would raise an uncontrolled `IndexError` on an empty `bar_ts_arr` (unreachable via the current single call site, since `_compute_cross_sectional_tf` already returns early on `X_raw is None`) | **fixed** -- added an explicit early-return guard + test `test_broadcast_cell_empty_bar_ts_arr_returns_empty_without_raising`; commit `8a7418faa` |
| 3 | codex | "no second full-length allocation" claim called slightly overstated | **rejected: not a correctness issue** -- the code already discloses `X_bc`'s bounded `[N, n_broadcast]` allocation explicitly in comments (Step 3); the acceptance criterion under test is specifically "no sort-based allocation," never "zero allocations," and no such claim was made |
| 4 | codex + agy | Anything still depending on Plan 02's deleted `CONTEXT_FEATURES`/`min_obs_daily` path? | **rejected: not an issue** -- both reviewers independently confirmed no dangling runtime dependency; agy additionally surfaced the pre-existing, already-filed todo 355 (orphaned `infrastructure_context_features_writer.py`), correctly identified as out of Phase 173's scope, not a new finding |
| — | agy | BH-FDR family composition, boundary-scan edge cases, cluster_id offset bound (smallint ceiling) | confirmed **looks correct**, no action needed |
| — | codex | BH-FDR family composition | confirmed **looks correct**, no action needed |

No reviewer raised a correctness objection to the statistical specification itself (both
explicitly framed finding #1 as "needs a design decision" / "if intentional, treat as a design
choice" rather than "this is wrong") -- nothing in this phase required escalation per the plan's
own merge-blocking criterion.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Smoke-test script's missing archive-then-delete step silently dropped all
broadcast-row inserts via `ON CONFLICT DO NOTHING`**
- **Found during:** Task 3, first live write attempt against `equity/1h/low_bear`
- **Issue:** see Task 3 Detail above -- the standalone smoke-test script (not
  `services/ic_engine.py` itself) omitted `main()`'s required archive-then-delete step, so
  pre-existing pre-Phase-173 rows silently blocked every new broadcast-row insert.
- **Fix:** added the same archive-then-delete SQL calls the real `main()` loop runs, before the
  compute call.
- **Files modified:** the standalone smoke-test script only (not part of this plan's git diff --
  it is a throwaway scratchpad tool, not a deliverable)
- **Verification:** re-ran; 70 broadcast rows landed correctly, confirmed via direct SQL.

**2. [Rule 3 - Blocking] Reviewed the true phase-start diff instead of the plan's literal
`main...HEAD` command**
- **Found during:** Task 4, preparing the review invocation
- **Issue:** see Decision 1 above.
- **Fix:** diffed against `9e7231a65` (the true pre-Phase-173 base) instead of `main`.
- **Files modified:** none (review-scoping decision only, not a code change)
- **Verification:** confirmed via `git log --oneline main -25` that `main` sits at Wave 2's
  completion commit (`fb6db7c96`) and that `9e7231a65` predates Phase 173's first execution
  commit (`4e9ded24d`) with zero Phase-173 commits in between (5 unrelated interleaved research
  commits excluded by scoping the diff to the plan's own named paths).

---

**Total deviations:** 2 (1 Rule-1 bug in throwaway tooling, not a deliverable; 1 Rule-3 blocking
adaptation of a stale literal command to match its own stated intent). No scope creep in either
case -- both were required to actually execute the task as specified.

## Issues Encountered

**The largest-cell smoke run did not complete within a bounded session.** See Decision 3 above
and todo 356 for the full investigation (confirmed genuine server-side CPU-bound work via
`pg_stat_activity`/`top`, not a lock wait or a bug in this plan's own code -- the fetch SQL is
unchanged by Phase 173). Handled by using the partial RSS trajectory plus a fully-completed
medium-size cell as the combined evidentiary basis for the OOM-regression check, and filing a
todo for the newly-discovered pre-existing performance characteristic rather than either (a)
blocking the plan indefinitely or (b) silently fixing out-of-scope SQL mid-task.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Todo's core bug (270) is closed: broadcast features are now measured with an effective N equal
  to distinct `bar_ts`, regime-conditionally, against an equal-weighted peer-group aggregate
  return -- live-verified against real production data, not just synthetic tests.
- The corpus's `feature_ic_scores` fingerprint is invalidated corpus-wide by Phase 173 (the
  `broadcast_hash` watermark component Plan 03 added) -- the next full `ic_engine.py` corpus run
  will recompute every cross-sectional cell, including `equity/5m/low_bull` (left at zero live
  rows by this plan's killed smoke run, safely archived) and every other cell this plan did not
  touch. No separate "trigger a recompute" follow-up is needed.
- Todo 356 (pre-existing slow-fetch performance on the corpus's largest cells) is filed and should
  be considered before or during that next full corpus run, since it could materially extend the
  run's wall-clock time if representative of other large 5m cells.
- Both cross-AI reviewers cleared this phase's diff with no blocking findings -- ready to merge
  per the phase's own Done-Coding SOP requirement.

---
*Phase: 173-broadcast-feature-significance-correction-fix-pooled-cross-s*
*Completed: 2026-08-25*

## Self-Check: PASSED

- `services/ic_engine.py` - FOUND (modified)
- `tests/unit/test_ic_engine_compute_split.py` - FOUND (modified)
- `.planning/todos/pending/356-cross-sectional-fetch-chunk-query-pathologically-slow-largest-cell.md` - FOUND
- `.planning/todos/PRIORITIES.md` - FOUND (modified)
- Commit `73044aa61` (Task 1) - FOUND in `git log`
- Commit `771e5202c` (Task 2) - FOUND in `git log`
- Commit `86a981e2e` (Task 3) - FOUND in `git log`
- Commit `8a7418faa` (Task 4) - FOUND in `git log`
- `grep -c "_compute_one_broadcast_cell" services/ic_engine.py` = 5 (def + 1 call site + 3
  docstring/comment mentions) - PASS (>= 1 required)
- `grep -c "_compute_one_broadcast_cell(" services/ic_engine.py` = 2 (def line + 1 call site) -
  PASS (exactly 2 required)
- `grep -c "_BROADCAST_CLUSTER_ID_OFFSET" services/ic_engine.py` = 4 - PASS (>= 2 required)
- `grep -c "broadcast_variance_threshold" services/ic_engine.py` = 7, every occurrence uses the
  exact key name `alpha.ic.broadcast_variance_threshold` - PASS (>= 2 required, no second key
  introduced)
- `grep -c "np.flatnonzero" services/ic_engine.py` = 2 (docstring + code) - PASS (>= 1 required)
- `grep -c "np.fmax.reduceat" services/ic_engine.py` = 1, `grep -c "np.fmin.reduceat"` = 1,
  neither `np.maximum.reduceat` nor `np.minimum.reduceat` present - PASS
- `grep -c "Float32ChunkAccumulator" services/ic_engine.py` = 7, unchanged from the pre-Task-1
  value - PASS
- `.venv/bin/pytest tests/unit/test_ic_engine_compute_split.py -q` = 45 passed - PASS
- `.venv/bin/pytest tests/unit/ -q` = full suite green, zero failures, 2 skipped (pre-existing,
  unrelated) - PASS
- `.venv/bin/ruff check services/ic_engine.py tests/unit/test_ic_engine_compute_split.py` = All
  checks passed - PASS
- `.venv/bin/black --check services/ic_engine.py tests/unit/test_ic_engine_compute_split.py` = All
  done, unchanged - PASS
- Live DB: `SELECT count(*) FROM feature_ic_scores WHERE symbol='POOLED' AND
  regime_scope='cross_sectional' AND cluster_id >= 10000` = 70 - PASS
- Live DB: `SELECT count(*) FROM feature_ic_scores WHERE cluster_id >= 10000 AND ic_ci_lower = 0
  AND ic_ci_upper = 0` = 0 - PASS
- SUMMARY contains `codex exec` and `agy -p` commands - PASS
