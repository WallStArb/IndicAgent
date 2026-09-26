---
phase: 174-universe-expansion-single-name-breadth-scaling-targeted-etf
plan: 01
subsystem: infra
tags: [numpy, memmap, ic_engine, apr, oom-fix, disk-backed]

# Dependency graph
requires: []
provides:
  - "Float32ChunkAccumulator disk_backed=True mode: memmap-backed accumulation, finalize() returns a view instead of vstack-ing a Python list of chunks"
  - "close()/context-manager cleanup that releases both the mmap and the NamedTemporaryFile handle"
  - "infra.ic_engine.memmap_scratch_dir and infra.ic_engine.disk_backed_min_rows APR keys (migration 336)"
affects: ["174-05", "174-09"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Additive constructor extension (keyword-only new params) over forking a parallel class"
    - "Memmap ownership contract: finalize() returns a view valid only until caller-owned close(); caller's finally must span every consumer of the view"
    - "Crash-loud overflow guard instead of silent truncation for pre-flight row estimates"

key-files:
  created:
    - production/migrations/336_ic_engine_disk_backed_cell_apr_keys.sql
  modified:
    - services/_batch_utils.py
    - tests/unit/test_batch_utils.py

key-decisions:
  - "Extended Float32ChunkAccumulator in place (additive disk_backed mode) rather than a parallel class, per RESEARCH.md's Don't-Hand-Roll table and the migration-249 precedent"
  - "Scratch dir defaults to /var/tmp/ic_engine_scratch, not /tmp -- /tmp may be tmpfs-backed and would put the disk-backed array back in anonymous RAM, defeating the fix"
  - "Both new APR keys registered under infra.* -- there is no universe.* prefix in ConfigService.OPS_PREFIXES"
  - "close() drops references to self._memmap/self._tmpfile before operating on local copies, making a second close() call naturally idempotent (no separate _closed flag needed)"

patterns-established:
  - "Disk-backed accumulator pattern: pre-allocate np.memmap sized to a conservative estimated_rows upper bound, write at a running offset, trim the view at finalize()"

requirements-completed: [D-04b]

duration: ~12min
completed: 2026-09-15
---

# Phase 174 Plan 01: Disk-backed Float32ChunkAccumulator Summary

**`Float32ChunkAccumulator` gained an additive `disk_backed=True` np.memmap mode so `finalize()` returns a view instead of holding a chunk list plus a vstacked copy simultaneously, bounding peak RSS to one chunk's size at universe scale; two new `infra.ic_engine.*` APR keys register the scratch directory and activation threshold.**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-09-15T08:30:00-04:00 (approx, worktree setup)
- **Completed:** 2026-09-15T08:41:24-04:00
- **Tasks:** 3/3
- **Files modified:** 3 (1 created, 2 modified)

## Accomplishments
- Registered `infra.ic_engine.memmap_scratch_dir` (`/var/tmp/ic_engine_scratch`) and `infra.ic_engine.disk_backed_min_rows` (2,000,000) APR keys via migration 336, applied live and verified idempotent on re-run
- Extended `Float32ChunkAccumulator` with a disk-backed accumulation mode: writes chunks directly into an `np.memmap` scratch file at a running offset; `finalize()` returns a trimmed view with zero `np.vstack` calls on that path
- Added `close()` (idempotent, releases both the mmap and the `NamedTemporaryFile` handle before unlinking) and `__enter__`/`__exit__` context-manager support
- Documented the memmap ownership contract (view valid only until `close()`; caller owns `close()`; caller's `finally` must span every consumer) in both the class docstring and `finalize()`'s docstring, for Plans 05 and 09 to depend on
- 12 new unit tests proving row-identity equivalence with the in-RAM path, over/under-estimate handling, cleanup, a 50-cycle file-descriptor-leak regression guard, and the ownership contract itself

## Task Commits

Each task was committed atomically:

1. **Task 1: Register the two disk-backed-accumulator APR keys (migration 336)** - `6a44aacb` (feat)
2. **Task 2: Add disk_backed mode to Float32ChunkAccumulator** - `36cf77b9` (feat)
3. **Task 3: Unit coverage for disk-backed equivalence, cleanup, fd hygiene, and crash-loud guards** - `4a81d7ee` (test)

_No TDD gate on this plan (not `type=tdd`); tests were written after the implementation as Task 3, per the plan's own task ordering._

## Files Created/Modified
- `production/migrations/336_ic_engine_disk_backed_cell_apr_keys.sql` - registers `infra.ic_engine.memmap_scratch_dir` and `infra.ic_engine.disk_backed_min_rows`, applied live against the running database
- `services/_batch_utils.py` - `Float32ChunkAccumulator` gains `disk_backed`/`estimated_rows`/`n_cols`/`scratch_dir` keyword-only constructor params, a `_write_disk_chunk()` helper, disk-backed branches in `append_chunk`/`_flush_buf`/`finalize`, and a new `close()` + `__enter__`/`__exit__`
- `tests/unit/test_batch_utils.py` - 12 new tests under `TestFloat32ChunkAccumulator`, all with `disk_backed` in the method name

## Decisions Made
- Followed the plan's constructor-extension shape exactly (validated in 174-PATTERNS.md) rather than a parallel accumulator class
- `close()` captures `self._tmpfile.name` as `path` before nulling references, so cleanup happens on locally-scoped copies and repeated calls are naturally no-ops without a separate `_closed` flag
- Test helper `_ragged_batches()` is a `@staticmethod` on the test class (not a module-level fixture) since it's only consumed by the two equivalence tests and keeps the disk-backed test block self-contained

## Deviations from Plan

None - plan executed exactly as written. All acceptance criteria in Tasks 1-3 were verified directly (grep checks, signature introspection, live-migration idempotency check, `findmnt` non-tmpfs confirmation, full `pytest tests/unit/ -q` green, `ruff check` clean).

## Issues Encountered
- This worktree had no `.venv` (a known GSD worktree gotcha) — symlinked `.venv` to the main checkout's `.venv` so `ruff`/`black`/`pytest` and the repo's pre-commit hook (which hardcodes `${REPO_ROOT}/.venv/bin/...`) resolve correctly. The symlink itself is gitignored and not part of any commit.

## User Setup Required

None - no external service configuration required. Migration 336 was applied live in the same step as writing it, per CLAUDE.md's "a migration applied live via `psql -f` has no forcing function to get committed" rule.

## Next Phase Readiness

- `Float32ChunkAccumulator(disk_backed=True, ...)` is ready for Plan 05 (`_compute_cross_sectional_tf`'s `X_raw`/`append_chunk` caller) and Plan 09 (`X_nd` block-column-chunking) to wire in behind a `finally: acc.close()` that spans every downstream consumer of the returned view
- Both APR keys are live and readable via `ConfigService` — Plan 05's caller still needs to read them and pass `scratch_dir=`/decide the `disk_backed_min_rows` threshold itself; this plan only made the mode reachable, per its stated scope ("the ic_engine wiring that consumes it is Plan 05")
- No blockers identified

---
*Phase: 174-universe-expansion-single-name-breadth-scaling-targeted-etf*
*Completed: 2026-09-15*

## Self-Check: PASSED

All created/modified files confirmed present on disk (migration 336, `services/_batch_utils.py`, `tests/unit/test_batch_utils.py`, this SUMMARY). All three task commit hashes (`6a44aacb`, `36cf77b9`, `4a81d7ee`) confirmed present in `git log`.
