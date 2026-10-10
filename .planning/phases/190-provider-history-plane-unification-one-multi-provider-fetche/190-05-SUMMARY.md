---
phase: 190-provider-history-plane-unification-one-multi-provider-fetche
plan: 05
subsystem: infra
tags: [rename, fetcher, external-identity-freeze, live-drain-safe, compat-shim, systemd]

# Dependency graph
requires:
  - phase: 190-provider-history-plane-unification-one-multi-provider-fetche (190-04)
    provides: the generalized vendor-blind fetcher whose code identity this plan renames
provides:
  - The fetcher concept named ohlcv_history_fetcher / OHLCVHistoryFetcher in code and tests
  - A load-bearing compatibility shim at scripts/infrastructure/backfill/ibkr_history_fetcher.py (execs the renamed main verbatim; deleted by 190-06 after the unit install)
  - The checked-in unit's ExecStart pointed at the renamed script (unit filename unchanged)
  - External identities frozen byte-identical with decision comments at each constant: FETCHER_LOCK_NAME, LOCK_HELD_MESSAGE, JOB, NIGHTLY_STATUS_FILE status path
affects: [190-06 cutover (installs the unit, deletes the shim)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Code-identity rename with frozen external identities: every frozen constant gets a FROZEN (phase 190 decision) comment stating who parses or keys on it"

key-files:
  created:
    - scripts/infrastructure/backfill/ibkr_history_fetcher.py (the shim; recreated at the old path)
  modified:
    - scripts/infrastructure/backfill/ohlcv_history_fetcher.py (renamed from ibkr_history_fetcher.py)
    - tests/unit/scripts/test_ohlcv_history_fetcher.py (renamed from test_ibkr_history_fetcher.py)
    - tests/unit/test_provider_leaf_boundary.py
    - scripts/infrastructure/backfill/_fetcher_lock.py
    - scripts/ops/bars/ops_head_rerun.py
    - scripts/ops/bars/ops_split_detect.py
    - scripts/infrastructure/backfill/_history_fetch.py
    - scripts/infrastructure/backfill/_history_fetch_item.py
    - services/split_detection.py
    - src/providers/ibkr.py
    - production/systemd/indicagent-ibkr-history-fetcher.service
    - tests/unit/scripts/test_head_rerun.py
    - tests/unit/scripts/test_ops_split_detect.py
    - tests/unit/scripts/test_history_fetch.py
    - tests/unit/test_ibkr_history_lock_boundary.py
    - tests/unit/providers/test_history_conformance.py

key-decisions:
  - "External identities stay byte-identical per the adopted Open Question 1 resolution: FETCHER_LOCK_NAME (sha256 key shared by 6+ ops tools), LOCK_HELD_MESSAGE (ops_head_rerun matches exactly), JOB (metric series + BaseBatch log-file derivation), status-file path (D7 audit reads it); each carries a FROZEN (phase 190 decision) comment"
  - "The log file does NOT move with the class rename: BaseBatch derives logs/<job_name>.log from the frozen JOB, so logs/ibkr_history_fetcher.log stays and swap_1d_primary_measure.py's --fetcher-log default stays valid (research A3 assumed class-name derivation; the code reads job_name)"
  - "The shim replicates the module's own __main__ block (otel init + sys.exit(main())) by importing from the renamed module, so behavior is byte-identical at the old path"
  - "Dry-run TSV default prefix, log event names (ibkr_history_fetcher.*), and the migration 451 header (with its contract test assertion) stay unchanged: operator artifacts and historical records named after the frozen job identity, none parsed as a module path"

patterns-established:
  - "Rename discipline for shared-identity infrastructure: git mv + same-commit shim at the old path + same-commit boundary allow-list move + decision comments at every frozen constant"

requirements-completed: [P190-fetcher, P190-lock]

# Metrics
duration: 28min
completed: 2026-10-10
---

# Phase 190 Plan 05: Code-identity rename Summary

**The fetcher is now named `ohlcv_history_fetcher` / `OHLCVHistoryFetcher` in code with every external identity string byte-identical under FROZEN decision comments, and the live drain stays runnable through a compatibility shim at the old path until the 190-06 cutover installs the updated unit.**

## Performance

- **Duration:** 28 min (through the Task 2 commit)
- **Started:** 2026-10-10T08:52Z
- **Tasks:** 2 (both auto)
- **Files modified:** 17 (2 renames, 1 recreated shim, 14 edited)

## Accomplishments

- `git mv` of the module and its test suite (recorded in the commit as content moves; the old module path gains the shim in the same commit, so git shows modify+add rather than R, noted below); class `OHLCVHistoryFetcher`, module docstring rewritten for the multi-provider concept (BaseBatch oneshot, not a Ring 2 daemon), `compute_version` bumped to "190.0" (no code_content_key cache; informational)
- Compatibility shim at `scripts/infrastructure/backfill/ibkr_history_fetcher.py`: imports `JOB, main` from the renamed module and replicates its `__main__` block exactly (otel init, `sys.exit(main())`); docstring states it is a wave-4-to-wave-5 shim deleted by 190-06. Smoke-tested: `--help` and `py_compile` pass on both entry points
- FROZEN decision comments added at all four identity constants: `FETCHER_LOCK_NAME` (sha256-keyed, shared by ops_d1_bootstrap, ops_venue_study, ops_intraday_venue_recovery, the rate-limit probe, classification sourcing, onboard manifest; renaming requires moving every consumer in one commit), `LOCK_HELD_MESSAGE` (ops_head_rerun matches exactly), `JOB` (metric series + log file via BaseBatch), and the status-file default (D7 audit's `NIGHTLY_STATUS_FILE` read)
- Provider-leaf boundary allow-list entry moved to `ohlcv_history_fetcher.py` in the same commit (review adjudication, AGY MEDIUM)
- Module-path references fixed everywhere the sweep found them: `ops_head_rerun._FETCHER`, `ops_split_detect._FETCHER`, `_history_fetch.py` docstring and usage example, `_history_fetch_item.py` docstring, `services/split_detection.py`, `src/providers/ibkr.py` comment, and the test assertions in test_head_rerun and test_ops_split_detect
- Checked-in unit ExecStart now names `ohlcv_history_fetcher.py`; every other unit fact byte-identical (Type=exec, User, WorkingDirectory, Environment, NotifyAccess, WatchdogSec=1200, RuntimeMaxSec=18000, Restart=no); timer file untouched; the root-owned live copies in /etc/systemd/system were NOT touched (190-06's cutover window)
- `service_auditor.py` verified to need no change: `_DAG_ORDER` and the oneshot list key on the unit name (`indicagent-ibkr-history-fetcher`), which is frozen; neither names the script path. Logrotate config verified to reference no fetcher log filename

## Task Commits

1. **Task 1: rename module, class, tests; freeze external identities** - `ed3370ac0` (feat) + `e0887d8dd` (chore: the old test path's deletion, see deviations)
2. **Task 2: unit ExecStart to the renamed script; logrotate and registry verification** - `1d3a9cc02` (chore)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] The explicit-pathspec commit could not carry the old test path's deletion**
- **Found during:** Task 1 commit
- **Issue:** The plan (and shared-checkout rules) require `git commit -- <paths>`; the pathspec for the atomic Task 1 commit included the new test path but the old path's `git rm` stage needs its own pathspec entry, and omitting it left `D tests/unit/scripts/test_ibkr_history_fetcher.py` staged after the commit.
- **Fix:** Recorded the deletion in an immediate follow-up chore commit (`e0887d8dd`). The module pair avoids this shape (the old path exists again as the shim), so the module rename rides inside the single Task 1 commit as modify+add; `git log --follow` tracks both moves.
- **Files modified:** tests/unit/scripts/test_ibkr_history_fetcher.py (deleted)
- **Commit:** e0887d8dd

**2. [Rule 2 - Missing critical] The module-path reference surface was wider than the plan's expectation**
- **Found during:** Task 1 sweep
- **Issue:** The plan expected "only the moved file and its test reference the class/module"; the sweep found two live subprocess invokers (`ops_head_rerun.py:55`, `ops_split_detect.py:77` build `_FETCHER` paths) whose test assertions pin the exact path, plus docstring references in `_history_fetch.py`, `_history_fetch_item.py`, `services/split_detection.py`, `src/providers/ibkr.py`, and three test files.
- **Fix:** All module-path references updated to `ohlcv_history_fetcher.py` (or its docstring equivalent) in the same commit; the zero-reference grep now passes.
- **Files modified:** listed in key-files
- **Commit:** ed3370ac0

### Plan-Reality Sync

**3. Research A3 corrected: the log file does not move**
- BaseBatch derives the log filename from `job_name` (the frozen JOB), not the class name, so `logs/ibkr_history_fetcher.log` stays and `swap_1d_primary_measure.py`'s `--fetcher-log` default remains valid without edits. No logrotate change was ever needed (verified: zero fetcher references).

**Total deviations:** 1 mechanical commit split, 1 sweep-surface expansion, 1 research correction. No scope change; the live drain was never stopped and no file was left non-runnable at any commit.

## Issues Encountered

- A run was in flight on the live drain during the edits (expected; the process keeps its loaded modules). The next timer fire execs the live unit's old-path ExecStart, which now resolves to the shim; the shim was smoke-tested through `--help` and compile before the commit, and its code path is identical to the renamed module's own `__main__` block.

## Known Stubs

- None. The shim at the old path is intentional, load-bearing, and scheduled for deletion in 190-06 (its docstring says so); it is not a stub.

## User Setup Required

None for this plan. The checked-in unit changed but the live root-owned copy did not; 190-06 installs it. No migrations, no APR seeds, timer never stopped.

## Next Phase Readiness

- 190-06's checklist gains one item: after installing the updated unit and daemon-reloading, verify one timer fire through the new ExecStart, then `git rm scripts/infrastructure/backfill/ibkr_history_fetcher.py` (the shim) and drop the mention from the renamed module's docstring
- The dry-run TSV default filename keeps the `ibkr_history_fetcher_dryrun_` prefix (frozen-job artifact); if 190-06's parity gate compares TSVs across the cutover, both sides produce identically-named columns regardless of the file prefix

## Verification

- `tests/unit/scripts/test_ohlcv_history_fetcher.py test_fetcher_lock.py test_ibkr_history_lock_boundary.py test_provider_leaf_boundary.py test_head_rerun.py test_ops_split_detect.py test_history_fetch.py test_fetch_queue.py` all green; full `tests/unit/ -q` green (exit 0) after Task 2
- `grep -rn "IbkrHistoryFetcher" --include="*.py" scripts/ services/ src/ tests/` returns 0 rows
- `grep -rn "backfill[/.]ibkr_history_fetcher"` returns 0 rows; remaining `ibkr_history_fetcher` strings are exactly the frozen identities (lock name, JOB, status path, unit filenames), their decision comments, the shim, and historical artifacts (migration 451 header + its contract test)
- Frozen-identity byte checks: `FETCHER_LOCK_NAME = "ibkr_history_fetcher"`, `JOB = "ibkr-history-fetcher"`, `NIGHTLY_STATUS_FILE` unchanged in writer and reader; timer file byte-identical
- Live drain: timer active, a run in flight on the old loaded code finished its items normally during the edits; shim verified executable at the old path

## Self-Check: PASSED

All four key artifacts exist on disk (renamed module, shim, renamed test, updated unit); all three commits verified in git log (ed3370ac0, e0887d8dd, 1d3a9cc02); frozen identities byte-identical per the checks above.

---
*Phase: 190-provider-history-plane-unification-one-multi-provider-fetche*
*Completed: 2026-10-10*
