---
phase: 161-controlled-vocabulary-system
plan: 03
subsystem: infra
tags: [asyncpg, apr, integrity_monitor, otel, vocabulary, drift-detection]

# Dependency graph
requires:
  - phase: 161-01
    provides: controlled_vocabulary/vocabulary_group/vocabulary_group_member schema (migration 239) + 6-namespace seed (migration 240)
  - phase: 161-02
    provides: VocabularyService (cached, library-embedded projection over the vocabulary tables)
provides:
  - infra.vocabulary_drift.window_days APR key (migration 241, default 30, [initial_estimate])
  - src/config/vocabulary_drift.py — importable drift-audit module + thin D-06 oneshot CLI
  - integrity_monitor persistence (monitor_type='vocabulary_drift') + OTel counter + logger.error on any unregistered live code
  - non-blocking oneshot invocation chained into scripts/ops/corpus/ops_corpus_pipeline_run.sh after alpha_publisher
affects: [161-04, future-registry-consumers]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pure comparison core (unregistered_codes/unregistered_groups/classify_namespace_drift) kept DB-free and unit-tested; all asyncpg I/O confined to run_drift_audit + the oneshot CLI"
    - "APR-sourced bounded time window: window_days read via ConfigService.get() (cache warm) then get_sync(), bound as an asyncpg $1 parameter on every recent-window query — never a hardcoded interval literal"
    - "Observability-only oneshot: exits 0 on detected drift (drift is reported via integrity_monitor + loud alert, not exit code), non-zero only on a genuine runtime error; chained into a bash pipeline with `|| true`, never wrapped in run_step"

key-files:
  created:
    - production/migrations/241_vocabulary_drift_window_apr_key.sql
    - src/config/vocabulary_drift.py
    - tests/unit/test_vocabulary_drift_audit.py
    - .planning/phases/161-controlled-vocabulary-system-planned/deferred-items.md
  modified:
    - scripts/ops/corpus/ops_corpus_pipeline_run.sh

key-decisions:
  - "Migration number 241, not 239 as originally planned — by execution time, wave 1 (161-01) had already claimed 239 for the controlled_vocabulary schema, and a concurrent unrelated migration had ALSO independently claimed 239 (a genuine pre-existing collision on main, logged in deferred-items.md, out of scope to fix here). 240 is also taken. 241 is the next free number."
  - "asset_class and tier namespace queries are intentionally unwindowed (no time-column bound) — both source tables (instruments, feature_registry) are small, non-hypertable, operator-facing dimension tables, not append-only event streams, so T-161-02's DoS concern (full-hypertable scan) does not apply to them."
  - "classify_namespace_drift takes a diff_fn parameter (default unregistered_codes) so the same idle/deprecation decision core serves both the six namespace checks and the V2 regime_group guard (via unregistered_groups) without duplicating the empty-set-is-idle logic."
  - "Did not manually invoke the oneshot (python -m src.config.vocabulary_drift) against the live DB for phase-end verification, per explicit run-time instruction: a corpus re-run (143.1-07, ic_engine.py) is actively running on this host and any additional DB/CPU load was ruled out of scope. Verified instead via bash -n, the plan's required greps, and the full unit test suite (10/10 green)."

patterns-established:
  - "Column-backed drift audit pattern: bounded recent-window SELECT DISTINCT per source column, compared against VocabularyService.codes(namespace), loud integrity_monitor + OTel + logger.error on any data-superset, silent skip (not deprecation) on an empty/idle observed set."

requirements-completed: []

# Metrics
duration: ~50min
completed: 2026-07-18
---

# Phase 161 Plan 03: Column-Backed Vocabulary Drift Audit Summary

**APR-windowed asyncpg drift audit over 6 controlled-vocabulary namespaces + a regime_group guard, writing loud `integrity_monitor` rows and chained non-blockingly into the corpus pipeline.**

## Performance

- **Duration:** ~50 min
- **Started:** 2026-07-17T20:21:00-04:00 (approx, after worktree branch check + context load)
- **Completed:** 2026-07-18T00:28:46Z
- **Tasks:** 3/3
- **Files modified:** 5 (4 created, 1 modified)

## Accomplishments
- Seeded `infra.vocabulary_drift.window_days` APR key (migration 241, default 30, `[initial_estimate]`), applied and verified live against the `indicagent` database.
- Built `src/config/vocabulary_drift.py`: pure comparison core (`unregistered_codes`, `unregistered_groups`, `extract_regime_hmm_codes`, `classify_namespace_drift`) + async `run_drift_audit` bounded-query runner + thin D-06 oneshot CLI, covering all 6 namespaces (`regime_hmm`, `regime_cross_sectional_equity`, `regime_cross_sectional_rates`, `timeframe`, `asset_class`, `tier`) plus the V2 `regime_group` guard.
- Chained the oneshot non-blockingly into `scripts/ops/corpus/ops_corpus_pipeline_run.sh` after Step 8 (`alpha_publisher`), teeing to a timestamped log with `|| true` so a drift-audit failure never halts the pipeline.
- 10/10 unit tests green (`tests/unit/test_vocabulary_drift_audit.py`), following the RED→GREEN TDD gate (confirmed `ModuleNotFoundError` with the implementation absent, then confirmed green with it present).

## Task Commits

Each task was committed atomically:

1. **Task 1: APR key migration for the drift-audit window** — `74ac2682` (feat)
2. **Task 2: Drift-audit module + oneshot CLI (TDD)**
   - RED: `10ee0d64` (test) — add failing tests, confirmed `ModuleNotFoundError` without the module present
   - GREEN: `2e816646` (feat) — implement `src/config/vocabulary_drift.py`, tests pass 10/10
3. **Task 3: Chain the drift oneshot into the corpus pipeline script** — `f6891df8` (feat)
4. **Deferred-item log (out-of-scope discovery)** — `894f0daa` (docs)

**Plan metadata:** SUMMARY commit (this file) — pending, committed separately by the worktree-mode metadata step.

_TDD task (Task 2) has 2 commits: test (RED) → feat (GREEN), no refactor pass needed._

## Files Created/Modified
- `production/migrations/241_vocabulary_drift_window_apr_key.sql` — APR key seed (config_schema/config_state/config_history triple-INSERT, migration-219-shaped)
- `src/config/vocabulary_drift.py` — drift-audit module + oneshot CLI
- `tests/unit/test_vocabulary_drift_audit.py` — 10 pure-Python tests, no DB
- `scripts/ops/corpus/ops_corpus_pipeline_run.sh` — one-block append after Step 8
- `.planning/phases/161-controlled-vocabulary-system-planned/deferred-items.md` — logs the pre-existing migration-239 numbering collision (out of scope)

## Decisions Made
- **Migration renumbered 239 → 241** (see key-decisions above). Documented inline in the migration file's header comment as well, so the numbering gap is self-explaining to future readers.
- **asset_class/tier queries left unwindowed** — both source tables are small dimension tables, not hypertables; T-161-02's DoS mitigation targets append-only event streams (`feature_vectors`, `market_regimes`, `market_data_ohlcv`), which the other four namespace queries + the regime_group guard all bound correctly.
- **`classify_namespace_drift(observed, registered, diff_fn=unregistered_codes)`** — single reusable idle/deprecation decision core parameterized by comparison function, avoiding duplicated empty-set-is-idle logic between the 6 namespace checks and the regime_group guard.
- **Symlinked a gitignored `.venv` into the worktree** pointing at the main repo's `.venv` (known gotcha: worktrees spawn without their own venv) — required to run ruff/black/pytest locally; not tracked by git, does not affect the merged commit.
- **Merged `main` into this worktree branch (fast-forward)** before starting Task 1 — this worktree's branch point predated wave 1's (161-01, 161-02) merge to `main`, so `vocabulary_service.py` and the schema migrations this plan depends on were not yet present. The fast-forward merge was clean (no local commits existed yet, no conflicts).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Migration number reassigned from 239 to 241**
- **Found during:** Task 1 (pre-check: `ls production/migrations/ | grep '^239'`)
- **Issue:** The plan's frontmatter targeted `production/migrations/239_vocabulary_drift_window_apr_key.sql`, but 239 was already taken twice on `main` by the time this plan executed (161-01's own `239_controlled_vocabulary_schema.sql`, plus an unrelated concurrent migration `239_ic_engine_cross_sectional_bootstrap_threads.sql`). 240 was also taken (161-01's seed migration).
- **Fix:** Used 241, the next free number; documented the renumbering both inline in the migration's header comment and in this SUMMARY.
- **Files modified:** `production/migrations/241_vocabulary_drift_window_apr_key.sql` (created at the new number instead of 239)
- **Verification:** Applied cleanly; `SELECT config_value FROM config_state WHERE config_key='infra.vocabulary_drift.window_days'` returns `30`.
- **Committed in:** `74ac2682` (Task 1 commit)

**2. [Rule 3 - Blocking] Worktree branch fast-forwarded onto `main` to pick up wave-1 dependencies**
- **Found during:** Pre-Task-1 context load — `src/config/vocabulary_service.py` (161-02's deliverable, a hard dependency of this plan) did not exist in the worktree's initial checkout.
- **Issue:** This worktree branch (`worktree-agent-a06dd92e08ecb72be`) was spawned from a commit predating wave 1's merge to `main` (`220676dc`), so 161-01/161-02's schema, seed, and `VocabularyService` were absent.
- **Fix:** `git merge --no-edit main` — a clean fast-forward (no local commits existed yet on this branch, no conflicts possible).
- **Files modified:** none directly (brought in 161-01/161-02's files as-is)
- **Verification:** `src/config/vocabulary_service.py` present and importable after the merge; `git merge-base --is-ancestor` sanity-checked before proceeding.
- **Committed in:** n/a (merge commit, not a task commit — precedes Task 1's own commit)

**3. [Rule 3 - Blocking] Symlinked `.venv` into the worktree**
- **Found during:** Task 1 commit attempt — pre-commit hook's ruff/black checks failed with "not found" because the worktree has no `.venv` of its own (known project gotcha).
- **Issue:** `REPO_ROOT/.venv/bin/ruff` and `.../black` did not exist in the worktree; the hook's fallback `which ruff`/`which black` also found nothing on `PATH`.
- **Fix:** `ln -s /home/bg/dev/indicagent/.venv .venv` inside the worktree — gitignored, does not affect the merged commit's tracked files.
- **Files modified:** none tracked (`.gitignore` already excludes `.venv`)
- **Verification:** `git check-ignore -v .venv` confirms it is ignored; subsequent commits' pre-commit hooks passed ruff/black checks normally.
- **Committed in:** n/a (untracked, no commit)

---

**Total deviations:** 3 auto-fixed (all Rule 3 — blocking issues preventing task completion)
**Impact on plan:** All three were necessary to execute the plan at all in this worktree's actual starting state; none changed the plan's scope or design. No scope creep.

## Issues Encountered

- **Duplicate migration number 239 on `main`** (pre-existing, not caused by this plan) — logged in `.planning/phases/161-controlled-vocabulary-system-planned/deferred-items.md` as an out-of-scope discovery per the executor's scope-boundary rule. Both 239-numbered files already applied cleanly; no functional breakage, just a numbering-hygiene gap for a future migration-tooling pass to consider.
- **Live corpus re-run (143.1-07) active on this host** during execution — per explicit run-time instruction, this plan's phase-end manual verification step (`python -m src.config.vocabulary_drift` against the live DB) was intentionally skipped to avoid DB/CPU contention with the in-flight `ic_engine.py` run. Verified instead via `bash -n`, the plan's required greps (all passing), and the full unit test suite (10/10 green). This is a deferred verification step, not a functional gap — the module is unit-tested and the pipeline wiring is syntax/shape-verified; the live-DB smoke test should be run once the corpus re-run completes (next natural corpus pipeline invocation will also exercise it automatically, since it is now the last step in `ops_corpus_pipeline_run.sh`).

## User Setup Required

None — no external service configuration required. The `infra.vocabulary_drift.window_days` APR key is already seeded and live; no manual dashboard/env step needed.

## Next Phase Readiness

- `src/config/vocabulary_drift.py` is importable and ready for any future consumer (e.g. a dashboard surfacing `integrity_monitor` drift rows, or Plan 04 if it touches the same area).
- The oneshot will run automatically as part of the NEXT full `ops_corpus_pipeline_run.sh` invocation (after the current 143.1-07 corpus re-run completes) — this is the natural first live-DB exercise of the wired invocation, satisfying the plan's phase-end verification criterion retroactively without competing with the active run.
- No blockers for 161-04.

---
*Phase: 161-controlled-vocabulary-system*
*Completed: 2026-07-18*

## Self-Check: PASSED

All 6 claimed files verified present on disk; all 6 claimed commit hashes verified present
in `git log --oneline --all` (74ac2682, 10ee0d64, 2e816646, f6891df8, 894f0daa, a5968f42).
