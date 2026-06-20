---
phase: 131-signal-generation-integrity
plan: "03"
subsystem: replay-pipeline
tags: [replay, asset_class, bar_history, cross_asset_divergence, signal-generation, run_historical_pipeline]

# Dependency graph
requires:
  - phase: 131-01
    provides: A4 CONFIRMED — asset_class=None universally in replay_symbol()
provides:
  - "A4 fix: asset_class injected into all_features for all symbols in replay_symbol() before run_i7_and_persist()"
  - "PrevDayLevelTest fix: bar_histories deque maxlen increased from 200 to 800"
  - "CrossAssetDivergence formally annotated as live-only with _CORPUS_EXCLUDABLE=True"
affects: [replay corpus rebuild, trade_framer per-asset-class thresholds, SessionLevelsPlugin prior-session window]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "COALESCE(contract_metadata, instruments) lookup for symbol->asset_class resolution in replay path"
    - "_CORPUS_EXCLUDABLE class attribute pattern for live-only plugin annotation"

key-files:
  created: []
  modified:
    - production/scripts/run_historical_pipeline.py
    - src/intelligence/trading/cross_asset_divergence.py

key-decisions:
  - "A4 fix queries COALESCE(cm.asset_class, i.asset_class) to cover both futures rolls (contract_metadata) and equities/ETFs (instruments) — cannot use get_active_contracts() which omits expired rolled contracts"
  - "asset_class injected in both normal I1-I6 path and precomputed-features path so both replay modes are fixed"
  - "_CORPUS_EXCLUDABLE is a class attribute declaration, not a behavioral gate — compute_full() is unchanged; the plugin continues to return no_signal() in replay due to missing frames['cross_asset'] data"

patterns-established:
  - "_CORPUS_EXCLUDABLE: bool = True class attribute marks I7 plugins that cannot fire in corpus replay for architectural reasons (not bugs)"

requirements-completed:
  - D-02
  - D-04
  - D-05

# Metrics
duration: 15min
completed: 2026-06-17
---

# Phase 131 Plan 03: A4 Fix + PrevDayLevelTest Fix + CrossAssetDivergence Annotation Summary

**A4 fix applied (asset_class injected for all replay symbols including rolled contracts), bar history depth increased to 800, CrossAssetDivergence formally documented as live-only**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-06-17T17:30:00Z
- **Completed:** 2026-06-17T17:45:00Z
- **Tasks:** 3
- **Files modified:** 2

## Accomplishments

### T-01: A4 fix — inject asset_class into all_features in replay_symbol()

At the top of `replay_symbol()`, after the `db_conn.commit()` call, added a psycopg2 COALESCE query that resolves `asset_class` from `contract_metadata` (covers futures rolls including expired contracts) with fallback to `instruments` (equities, ETFs). The resolved value is stored in `_symbol_asset_class: str | None`.

Injection added in two places before `run_i7_and_persist()` is called:
- Normal path: immediately after `all_features = {**i1_features, **intelligence}` (line ~1767)
- Precomputed-features path: after `all_features = precomputed_features.get((tf, ts_utc))` (line ~1735)

This mirrors what `FeaturePipelineExecutor.execute():332` does via `instrument_map` DI in the live pipeline.

### T-02: PrevDayLevelTest fix — bar_histories deque maxlen 200 → 800

Changed `defaultdict(lambda: deque(maxlen=200))` to `defaultdict(lambda: deque(maxlen=800))` at line 1670 with comment explaining the SessionLevelsPlugin `_SESSION_BARS=390` requirement. The old 200 was always insufficient for prior-session lookback, forcing `prior_session_high/low/close` to None for every replay bar.

### T-03: CrossAssetDivergence live-only annotation

Added `_CORPUS_EXCLUDABLE: bool = True` class attribute to `CrossAssetDivergencePlugin` alongside other class-level attributes. Added live-only comment block in module docstring explaining replay zero-emission is architectural (cross-instrument bar arrays not pre-loaded in single-symbol replay), not a bug, with Phase 131 D-02 cross-reference.

## Task Commits

1. **T-01 + T-02: A4 fix + maxlen fix** - `11c9d818` (fix)
2. **T-03: CrossAssetDivergence annotation** - `d26161a0` (feat)

## Files Created/Modified

- `production/scripts/run_historical_pipeline.py` - A4 fix (COALESCE lookup + asset_class injection in 2 paths) + bar_histories maxlen 200→800
- `src/intelligence/trading/cross_asset_divergence.py` - _CORPUS_EXCLUDABLE=True class attribute + live-only docstring annotation

## Decisions Made

- Batched T-01 and T-02 into a single commit since both modify `run_historical_pipeline.py` — avoids sequential merge conflicts on the same file
- Injection in precomputed-features path included even though the primary use case is normal replay — both modes should have correct asset_class for any future precomputed runs

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] .venv symlink missing in worktree**

- **Found during:** T-01 commit attempt
- **Issue:** Pre-commit hook looks for `${REPO_ROOT}/.venv/bin/ruff` where REPO_ROOT resolves to the worktree directory, not the main repo. The worktree has no `.venv` directory.
- **Fix:** Created symlink `/home/bg/dev/indicagent/.claude/worktrees/agent-ac71d7cff01331046/.venv -> /home/bg/dev/indicagent/.venv`
- **Files modified:** None (symlink only)
- **Commit:** N/A (not a code change)

## Self-Check

- [x] `_symbol_asset_class` appears 5 times in run_historical_pipeline.py (declaration, assignment, 2 injection guards, 0 extra)
- [x] `all_features["asset_class"]` injected at lines 1735 and 1767 (both paths)
- [x] `maxlen=200` count = 0 (eliminated)
- [x] `maxlen=800` present at line 1670
- [x] `_CORPUS_EXCLUDABLE: bool = True` in cross_asset_divergence.py at line 79
- [x] `Phase 131 D-02` cross-reference in docstring
- [x] `pytest tests/unit/ -q` = 4756 passed, 37 skipped (green)
- [x] Both commits exist: 11c9d818, d26161a0

## Self-Check: PASSED

---
*Phase: 131-signal-generation-integrity*
*Completed: 2026-06-17*
