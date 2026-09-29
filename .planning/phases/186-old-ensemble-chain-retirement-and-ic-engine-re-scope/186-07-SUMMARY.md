---
phase: 186-old-ensemble-chain-retirement-and-ic-engine-re-scope
plan: "07"
subsystem: research
tags: [asyncpg, postgres, feature_vectors, bh-fdr, statsmodels, server-side-cursor]

requires:
  - phase: 183-research-layer
    provides: "S0 panel (build_panel, forward_returns, Panel), ic_math (apply_bh_fdr, _hac_sharpe_nd)"
provides:
  - "todo445_5m_incremental_ic.py: committed, counted-look measurement of 5m-over-15m incremental IC"
  - "phase 186 rebuild's decided timeframe set (15m, 1h, 1d, 5m) and 5m name set (ret_autocorr_1, sweep_detected)"
  - "fetch_feature_columns: server-side-cursor streaming pattern for a bounded-memory bar x symbol matrix fetch from feature_vectors, reusable by any future script with the same shape"
  - "bh_fdr_excluding_nan: the correct way to run BH-FDR over a cell family that can contain untestable (NaN) entries"
affects: [186-12, 186-26, phase 187]

tech-stack:
  added: []
  patterns:
    - "server-side cursor streaming (asyncpg conn.cursor() inside a transaction) for any feature_vectors bar x symbol matrix fetch -- never pool.fetch(), which materializes the full result as Record objects regardless of query narrowness"
    - "exclude NaN entries from a BH-FDR family entirely rather than passing them to apply_bh_fdr; a NaN input corrupts every returned corrected p-value, not just its own"

key-files:
  created:
    - scripts/research/todo445_5m_incremental_ic.py
    - tests/unit/test_todo445_5m_incremental_ic.py
    - .planning/phases/186-old-ensemble-chain-retirement-and-ic-engine-re-scope/186-07-todo445-result.json
  modified:
    - .planning/gate_look_log.jsonl
    - .planning/todos/PRIORITIES.md
    - .planning/STATE.md
    - docs/research/construction-verdict-ledger.md
  deleted: []
  moved:
    - "from: .planning/todos/pending/445-5m-features-incremental-ic-over-15m-before-feature-rebuild.md"
    - "to: .planning/todos/completed/445-5m-features-incremental-ic-over-15m-before-feature-rebuild.md"

key-decisions:
  - "keep_5m: the rebuild covers 15m, 1h, 1d and 5m, scoped to ret_autocorr_1 and sweep_detected at the 233 compute_eligible names (the 931-name extension is a separate decision after todo 449 and the R-09 disk guard)"
  - "DB fetch streams via a server-side cursor in blocks of --block-size feature columns, never pool.fetch(): memory safety is structural (bounded by the destination arrays plus one cursor prefetch batch, independent of block size), block size is a pure throughput knob with no safety implication at any value"
  - "compute stays sequential numpy, not a ProcessPoolExecutor: the fetch stage (I/O-bound) dominates wall-clock, not compute, and pickling large rank arrays across a process boundary would reintroduce a memory-blowup class for no real speed gain"
  - "a NaN partial_p (too few sessions for that feature/horizon) is excluded from the BH-FDR family entirely, never fed to apply_bh_fdr, since mixing NaN in corrupts every corrected p-value the library returns"

patterns-established:
  - "Any future feature_vectors bar x symbol matrix fetch should follow fetch_feature_columns's shape: conn.cursor() streaming, never pool.fetch()/execute_batch on a query that can return more than a few thousand rows"

requirements-completed: [D-33, R-08, D-18, D-02]

duration: "~9h (2026-09-28, across three live memory incidents and a real counted run)"
completed: 2026-09-28
---

# Phase 186 Plan 07: Todo 445 5m-over-15m incremental IC Summary

**Decided keep_5m for the phase 186 rebuild (ret_autocorr_1 and sweep_detected clear both BH-FDR and the personal cost hurdle at the 233 compute_eligible names), after a database-fetch redesign forced by two live memory incidents and a post-hoc BH-FDR bug fix that did not change the outcome.**

## Performance

- **Duration:** ~9 hours across Task 1 (script + tests), a design iteration on the DB fetch layer (not a plan task, but real work: three fetch designs, two killed live), Task 2 (the real counted run, ~88 min wall-clock), and Task 3 (closing todo 445, ledger, STATE.md).
- **Tasks:** 3 (per plan), plus one unplanned DB-fetch redesign cycle covered under the deviation rules below.
- **Files modified:** 4 code/test files, 1 new result JSON, 4 planning/doc files.

## Accomplishments

- `scripts/research/todo445_5m_incremental_ic.py`: partial rank IC of the 5m value on the forward
  return controlling for the 15m value, per bar, session-averaged, HAC t-stat, BH-FDR at q=0.05,
  cost-hurdle gate reusing `personal_cost_hurdle_by_tf.py`'s 0b formula.
- The real, counted run: 233 names, 240 features, 2 horizons, 480 cells, decision `keep_5m`.
- A DB-fetch pattern (`fetch_feature_columns`, streaming via `asyncpg`'s server-side cursor) that
  is structurally safe against the "hold the whole result in memory" failure class, matching the
  existing `personal_cost_hurdle_by_tf.py::_fetch_ranks` idiom for this exact problem shape.
- Found and fixed a real BH-FDR bug (NaN p-values corrupting every corrected p-value) by
  inspecting the completed run's own output, not by a test that happened to catch it; verified
  the fix did not change the recorded decision before treating it as safe to ship.
- Todo 445 closed, ledger section 5 entry added, STATE.md's stale clause replaced with the
  decided fact.

## Task Commits

1. **Task 1: script core + tests** - `6c883a846` (test), `1c7e04b0a` (feat)
2. **Unplanned: smoke-run bug fixes** - `3f7cb312f` (fix: 1GB Postgres buffer limit, a shape-
   broadcast bug, noisy warnings), found by the plan's own mandated smoke run, not scope creep
3. **Unplanned: DB-fetch redesign** - `f576a4ed1` (fix: server-side cursor streaming, replacing
   two prior designs that both materialized a full query result and were killed live at 10-19GB
   RSS); see Deviations
4. **Task 2: the real counted run** - `924240119` (feat), plus its own bug fix `4a93fdfb7` (fix:
   BH-FDR NaN corruption, panel_hash never surfaced), found reading the run's output before this
   commit
5. **Task 3: close todo 445** - `ff4ef478e` (docs)

**Plan metadata:** this file's own commit (docs: complete plan)

## Files Created/Modified

- `scripts/research/todo445_5m_incremental_ic.py` - the measurement script
- `tests/unit/test_todo445_5m_incremental_ic.py` - 22 tests on synthetic arrays, no DB
- `.planning/phases/186-old-ensemble-chain-retirement-and-ic-engine-re-scope/186-07-todo445-result.json` - the counted run's output, with a `_correction_note` documenting the post-hoc BH-FDR fix
- `.planning/gate_look_log.jsonl` - one new `todo445_5m_incremental_ic_over_15m` line
- `.planning/todos/completed/445-...md` - moved from pending, `## Decision` section appended
- `.planning/todos/PRIORITIES.md` - pending row removed, build lane clause updated
- `.planning/STATE.md` - stale "needs the 5m timeframe decision" clause replaced with the fact
- `docs/research/construction-verdict-ledger.md` - section 5 entry

## Decisions Made

See `key-decisions` above. The most consequential one for phase 186: the rebuild's timeframe set
is 15m/1h/1d/5m, not 15m/1h/1d; todo 445 could have gone either way, and this changes 186-12's
and 186-26's scope (5m stays in the derived-grid and feature-rebuild path, scoped to two named
features).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Server-side cursor streaming for the DB fetch layer (not in the original plan's design)**
- **Found during:** Task 2's mandated smoke run and, after a first fix attempt, the real run itself
- **Issue:** The plan's own interfaces section specified a `pool.fetch()`-based block/symbol-chunk
  fetch. Under smoke testing this hit two failure classes: (a) an exact-timestamp array bind
  (`bar_ts = ANY($3)` with ~65k elements) hit Postgres's 1GB per-value buffer limit; (b) after
  fixing that with a range query, a whole-block `Record` list measured 10-19GB RSS for one block
  of the real ~283-feature run on the live, shared box; two live kills were needed to protect the
  system before the pattern was understood.
- **Fix:** Replaced `pool.fetch()` with `asyncpg`'s server-side cursor (`async for row in
  conn.cursor(...)` inside a transaction), matching the existing
  `scripts/analysis/personal_cost_hurdle_by_tf.py::_fetch_ranks` idiom for this exact problem
  shape ("far too many to fetchall" per its own docstring). This makes memory safety structural
  (bounded by the destination arrays plus one cursor prefetch batch) rather than a function of a
  tuned block/chunk size; the root cause was never the chunk size, it was materializing a query
  result before touching it.
- **Files modified:** `scripts/research/todo445_5m_incremental_ic.py`
- **Verification:** Two live smoke runs (single-column, then a 32-column block) both held memory
  flat within a few percent of the predicted footprint under a memory watchdog for several
  minutes; the real run then completed cleanly with memory oscillating in the same bounded range
  for its full ~88-minute wall-clock.
- **Committed in:** `f576a4ed1` (and its predecessor smoke fixes, `3f7cb312f`)

**2. [Rule 1 - Bug] BH-FDR NaN contamination**
- **Found during:** post-hoc inspection of the completed real run's own output (not a test; there
  was no unit test covering a mixed-NaN p-value family before this)
- **Issue:** 14 of 480 cells had `NaN` `partial_p` (too few sessions for that feature/horizon).
  Feeding a p-value list containing NaN into `apply_bh_fdr` (a thin wrapper around statsmodels'
  `multipletests`) corrupted the returned `bh_p_corrected` to NaN for all 480 cells, not just the
  14. Isolated and confirmed with a standalone repro before touching the code.
- **Fix:** `bh_fdr_excluding_nan` excludes NaN entries from the family before calling
  `apply_bh_fdr`, returning them individually as `(reject=False, p_corrected=NaN)`. Verified the
  actual `reject` decisions were nearly unaffected (1 of 466 finite cells flipped when recomputed
  correctly, and none of the 4 cost-clearing cells driving `keep_5m` changed) before treating the
  fix as safe; the bug is fixed regardless of whether it changed the outcome this time, per this
  project's own standard.
- **Files modified:** `scripts/research/todo445_5m_incremental_ic.py`,
  `tests/unit/test_todo445_5m_incremental_ic.py` (3 new tests), the already-recorded result JSON
  (patched using the same already-observed `partial_p` values, no new DB query, documented via a
  `_correction_note` field)
- **Verification:** unit tests pass; the patched result JSON's `bh_p_corrected` is now NaN only
  for the 14 excluded cells; `decision` and `name_set_5m` confirmed unchanged from the as-run
  values
- **Committed in:** `4a93fdfb7`

**3. [Rule 1 - Bug] panel_hash silently dropped**
- **Found during:** the same post-hoc inspection pass as the BH-FDR bug
- **Issue:** the plan's own acceptance criteria require a top-level `panel_hash` field in the
  result JSON; `build_target_panel` discarded the content-hashed path `build_panel` returns
  instead of surfacing it.
- **Fix:** `build_target_panel` now returns the path's name as `panel_hash`. Recovered the real
  run's value from the still-on-disk panel directory (`logs/todo445/panels/panel_b43ebbd28c251af1`)
  rather than re-fetching, and independently re-verified its content hash before trusting it.
- **Files modified:** `scripts/research/todo445_5m_incremental_ic.py`
- **Verification:** `store.verify()` on the recovered directory reproduces its own name; full
  result JSON schema check passes
- **Committed in:** `4a93fdfb7`

---

**Total deviations:** 3 auto-fixed (2 Rule 1 bugs found post-hoc, 1 Rule 1 bug found by the plan's
own mandated smoke-test step). **Impact:** the DB-fetch redesign was necessary for correctness and
safety on shared infrastructure, not scope creep; the two post-hoc fixes did not change the
decision this plan exists to produce, but were fixed anyway since a corrupted `bh_p_corrected`
field and a missing `panel_hash` are both real defects independent of whether they altered this
run's outcome.

## Issues Encountered

Two live processes were killed by a manual memory watchdog before the DB-fetch redesign was
correct (10GB and 17GB RSS respectively, on a shared box also running the todo 449 backfill and
other sessions); both kills were clean (no orphaned process, no leftover Postgres backend,
verified each time) and no counted look was burned by either (both crashed before writing output,
which the plan's own crash-handling rule treats as safe to fix and rerun). A third monitor
(watching a background smoke test, not the counted run itself) expired without `nohup`/`disown`
protecting the child process and killed it; subsequent launches used `nohup ... & disown`
throughout, including the real counted run, which survived two monitor-window expiries cleanly.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

186-26's precondition checker can now read todo 445's `Rebuild timeframes:` and `5m name set:`
lines. 186-12 (D2b live rewrite) and 186-08 onward are unblocked by this plan; 186-26 itself
remains gated on todo 449's 5m backfill completing, independent of this decision.

---
*Phase: 186-old-ensemble-chain-retirement-and-ic-engine-re-scope*
*Completed: 2026-09-28*
